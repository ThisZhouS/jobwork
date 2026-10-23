"""社媒背调的相关性判定：由 agent 用对话模型完成。

抓取工具只负责"把页面变成结构化行"；一条结果是否真的在讨论目标公司，
属于语义判断，放在 agent 层。这样工具里不需要维护"本手=围棋术语"这类
关键词特例，换公司/换平台时判断口径也能统一。

模型不可用时**不猜**：保留工具返回的全部结果，并在 notes 里说明未判定。
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

from ..base import AgentContext, AgentStatus, Finding
from ..toolagent import ToolAgent
from ..tools.parsing import extract_json_object

BATCH_SIZE = 10
MAX_SNIPPET = 140
MAX_SUMMARY_ITEMS = 30


def _prompt(company: str, batch: list[Finding]) -> str:
    lines = [
        f"公司名：{company}",
        "下面是搜索平台返回的候选内容。请判断哪些条目对求职者判断"
        "“这家公司作为雇主是否值得去”有帮助。",
        "有帮助的范围：招聘、面试、薪资、加班、管理、裁员、外包、员工评价、经营风险。",
        "只讨论产品、技术、评测、新闻，但对雇主评价没有帮助的，算无关。",
        "公司名可能在标题里只出现品牌/简称（省略地名或“科技/信息/商贸”等后缀），"
        "例如“本手信息”可能以“本手科技”出现；请结合摘要判断。",
        "同名词语、围棋术语、其他公司、泛化问答都属于无关。",
        "候选：",
    ]
    for index, finding in enumerate(batch, start=1):
        title = str(getattr(finding, "title", "") or "").strip()
        snippet = re.sub(r"\s+", " ", str(getattr(finding, "snippet", "") or "")).strip()
        lines.append(f"{index}. 标题：{title}\n   摘要：{snippet[:MAX_SNIPPET]}")
    lines.append("只返回 JSON 数组，列出相关条目的编号，例如 [1,3]；没有相关条目返回 []。")
    return "\n".join(lines)


def parse_indices(text: str | None, size: int) -> list[int] | None:
    """从模型回复里取编号数组；格式不对返回 None（调用方据此保留原批次）。"""
    if not text:
        return None
    match = re.search(r"\[[\d,\s]*\]", text)
    if not match:
        return None
    try:
        raw = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, list):
        return None
    out: list[int] = []
    for item in raw:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= size and number not in out:
            out.append(number)
    return out


async def filter_findings(findings: Iterable[Finding], company: str,
                          ctx: AgentContext) -> tuple[list[Finding], dict[str, Any]]:
    """用 agent 的 chat 模型判断相关性，返回 (保留的条目, 判定信息)。"""
    items = list(findings or [])
    info: dict[str, Any] = {
        "judged": False, "total": len(items), "kept": len(items), "reason": "",
    }
    if not items or not str(company or "").strip():
        info["reason"] = "没有候选或公司名为空"
        return items, info

    box = ctx.model_box()
    if not box.available("chat"):
        info["reason"] = "chat 模型不可用，保留全部"
        return items, info

    kept: list[Finding] = []
    batches = failed = 0
    for start in range(0, len(items), BATCH_SIZE):
        batch = items[start:start + BATCH_SIZE]
        batches += 1
        text = await box.text_of([
            {"role": "system", "content": "你是企业背调结果审核员，只做相关性判断，不做其他分析。"},
            {"role": "user", "content": _prompt(str(company), batch)},
        ])
        indices = parse_indices(text, len(batch))
        if indices is None:
            failed += 1
            kept.extend(batch)
            continue
        kept.extend(batch[index - 1] for index in indices)

    info.update({"judged": True, "kept": len(kept), "batches": batches,
                 "failed_batches": failed})
    if failed:
        info["reason"] = f"{failed} 个批次判定失败，已保留该批次全部"
    return kept, info


def normalize_summary(data: Any) -> dict[str, Any] | None:
    """模型有时会把整个 JSON 再包一层字符串，这里统一拆开。"""
    if isinstance(data, str):
        data = extract_json_object(data)
    if isinstance(data, dict):
        summary = data.get("summary")
        if isinstance(summary, str) and summary.strip().startswith("{"):
            inner = extract_json_object(summary)
            if isinstance(inner, dict):
                data = inner
    return data if isinstance(data, dict) else None


async def summarize_findings(findings: Iterable[Finding], company: str,
                             ctx: AgentContext) -> dict[str, Any] | None:
    """AI agent 的总结：把已筛选证据归纳成雇主背调摘要。"""
    items = list(findings or [])
    company = str(company or "").strip()
    if not items or not company:
        return None
    box = ctx.model_box()
    if not box.available("chat"):
        return None

    selected = items[:MAX_SUMMARY_ITEMS]
    lines = [
        f"公司名：{company}",
        "下面是已筛选的背调证据。请以背调分析 agent 的身份，总结这家公司作为雇主的要点。",
        "要求：",
        "1. 只使用证据里出现的信息，不编造；证据不足就写“证据不足”。",
        "2. 按招聘/面试、薪资福利、加班压力、管理氛围、风险事件归类；没有证据的类别可省略。",
        "3. 每条要点用 [编号] 引用证据。",
        '4. 只输出 JSON：{"summary":"120字以内总体结论",'
        '"points":[{"topic":"...","text":"...","evidence":[1,2]}],'
        '"risk_level":"low|medium|high|unknown"}',
        "证据：",
    ]
    for index, finding in enumerate(selected, start=1):
        title = str(getattr(finding, "title", "") or "").strip()
        snippet = re.sub(r"\s+", " ", str(getattr(finding, "snippet", "") or "")).strip()
        lines.append(f"{index}. 标题：{title}\n   摘要：{snippet[:160]}")

    result = await box.chat([
        {"role": "system", "content": "你是企业背调分析 agent，只基于给定证据总结，不编造。"},
        {"role": "user", "content": "\n".join(lines)},
    ])
    if not result.usable:
        return None

    data = normalize_summary(extract_json_object(result.text))
    if data is None:
        text = str(result.text or "").strip()
        if not text:
            return None
        data = {"summary": text, "points": [], "risk_level": "unknown"}

    summary = str(data.get("summary") or "").strip()
    points = data.get("points") if isinstance(data.get("points"), list) else []
    if not summary and not points:
        return None
    return {
        "summary": summary,
        "points": points[:12],
        "risk_level": str(data.get("risk_level") or "unknown"),
        "model": result.spec,
        "evidence_count": len(items),
        "used": len(selected),
        "usage": result.usage,
    }


class AiSocialAgent(ToolAgent):
    """社媒背调 AI agent：抓取 → 模型相关性判断 → 模型生成摘要。"""

    async def run(self, request, ctx):
        result = await super().run(request, ctx)
        company = getattr(request, "company_name", "")
        if not result.findings:
            return result

        kept, info = await filter_findings(result.findings, company, ctx)
        result.meta["relevance"] = info
        if info.get("judged"):
            result.findings = kept
            result.notes.append(
                f"模型相关性判定：保留 {info['kept']}/{info['total']} 条")
            if not kept:
                result.status = AgentStatus.EMPTY
        else:
            result.notes.append(f"相关性未判定：{info.get('reason')}")

        if kept:
            summary = await summarize_findings(kept, company, ctx)
            if summary:
                result.meta["summary"] = summary
                result.notes.append("AI 背调摘要已生成")
            else:
                result.notes.append("AI 背调摘要未生成（模型不可用或返回不可解析）")
        return result


__all__ = ["AiSocialAgent", "filter_findings", "normalize_summary",
           "parse_indices", "summarize_findings"]
