"""简历 agent：用户确认后，把简历往目标岗位方向调整。

三条硬纪律：

1. **不编造事实**。只重排、筛选、改写已有内容，绝不新增没写过的经历/数字。
2. **先问再改**。用 ``ask_user`` 工具问清"这段经历想强调什么"，
   没有交互通道时（批处理）就只做规则化重排，并在 notes 里说明。
3. **产出是版本**。结果由流水线写进 ``resume_version``，可回溯父版本。

因为当前没有对话模型可用（只有 embedding），这里的"改写"是**规则化**的：
按目标岗位关键词给已有条目排序、挑出命中技能、生成一段可直接用的概述。
真要润色成文，等接入对话模型后再替换 :meth:`ResumeTailorAgent.rewrite` 即可。
"""
from __future__ import annotations

from typing import Any

from .base import Agent, AgentContext, AgentKind, AgentRequest, AgentResult, AgentStatus
from .registry import register
from .toolagent import open_toolbox
from .tools import get_tool
from .tools.parsing import clip

#: 问用户的问题（前端渲染成输入框）
QUESTIONS = (
    "目标岗位最想强调哪一段经历？",
    "有没有希望弱化或者不写的内容？",
    "这份简历最想证明的三个能力是什么？",
)


class ResumeTailorAgent(Agent):
    name = "resume_tailor"
    kind = AgentKind.SCORING          # 产出"简历版本"，与评分同属加工类
    description = "按目标岗位调整简历（只重排已有事实，先问用户）"
    requires = ()
    produces = ("resume",)
    #: 想要对话能力：有则润色成文，没有就退回规则化重排
    requires_models = ("chat",)
    mandatory_tools: tuple[str, ...] = ("log_event", "ask_user")
    log_tool = "log_event"

    def describe(self) -> dict[str, Any]:
        info = super().describe()
        info["tools"] = []
        info["mandatory_tools"] = list(self.mandatory_tools)
        return info

    async def run(self, request: AgentRequest, ctx: AgentContext) -> AgentResult:
        resume = dict(getattr(request, "resume", None) or {})
        if not resume:
            return AgentResult.failed(self.name, "输入不足：需要简历内容（--resume）")

        job = dict(getattr(request, "job", None) or {})
        answers: list[dict] = []
        notes: list[str] = []

        async with open_toolbox(ctx) as box:
            # 1) 先问用户（没有通道就跳过，不阻塞）
            ask_tool = get_tool("ask_user")
            for question in QUESTIONS:
                result = await ask_tool.execute(box, question=question)
                notes.extend(result.notes)
                if result.usable and isinstance(result.data, dict) and result.data.get("answer"):
                    answers.append({"question": question, "answer": result.data["answer"]})

            # 2) 规则化重排（不新增事实）
            tailored = self.rewrite(resume, job, answers)

            # 3) 有对话模型就润色概述；没有就保持规则化文本（降级不报错）
            polished = await self.polish(ctx, tailored, job)
            if polished:
                tailored["summary"] = polished
                notes.append("概述已由对话模型润色")

            # 4) 诊断：没问到人就说明是按规则改的
            if not answers:
                await get_tool(self.log_tool).execute(
                    box, message="没有交互通道，定向简历按规则生成（未经用户确认）",
                    level="warn", status="partial", code="no_interaction",
                    agent=self.name, context={"job": job.get("title")})

        status = AgentStatus.OK if answers else AgentStatus.PARTIAL
        if not answers:
            notes.append("未获取到用户回答，仅按关键词规则重排；建议在前端确认后再定稿")
        return AgentResult(
            agent=self.name, status=status, notes=notes,
            meta={
                "resume": tailored,
                "questions": list(QUESTIONS),
                "answers": answers,
                "needs_confirmation": not answers,
            },
        )

    # ------------------------------------------------------------ 润色
    async def polish(self, ctx: AgentContext, tailored: dict, job: dict) -> str | None:
        """有对话模型时润色概述。不可用就返回 None——**不编造、不报错**。"""
        base = str(tailored.get("summary") or "").strip()
        if not base:
            return None
        box = ctx.model_box()
        if not box.available("chat"):
            return None
        prompt = (
            "下面是一段求职简历概述草稿。请只做措辞润色，"
            "必须保留草稿中的年限、技能和目标岗位，不得删减信息点；"
            "不得新增任何事实、数字或经历；保持一段话，不超过 120 字。\n"
            f"目标岗位：{job.get('title') or '未指定'}\n草稿：{base}"
        )
        return await box.text_of([
            {"role": "system", "content": "你是简历措辞编辑，只改表达不改事实。"},
            {"role": "user", "content": prompt},
        ])

    # ------------------------------------------------------------ 改写
    def rewrite(self, resume: dict, job: dict, answers: list[dict]) -> dict:
        """规则化定向：重排条目、挑技能、生成概述。不新增任何事实。"""
        from .scoring.rubric import as_text, normalize_skills

        skills = list(resume.get("skills") or [])
        # JD 的结构化 skills 可能为空，所以再拿简历技能去 JD 正文里做命中，
        # 这样概述和项目排序仍然有依据，而不是只写一句"2 年经验"。
        jd_text = as_text(job).lower()
        wanted = set(normalize_skills(job.get("skills"))) | set(
            normalize_skills(job.get("title")))
        wanted |= {s for s in normalize_skills(skills) if s and s in jd_text}
        out = dict(resume)

        # 技能：把命中的排前面，其余保持原顺序
        if skills and wanted:
            out["skills"] = sorted(
                skills,
                key=lambda item: 0 if normalize_skills(item) and
                set(normalize_skills(item)) & wanted else 1,
            )

        # 经历：按与 JD 的关键词命中数排序（稳定排序，不改内容）
        items = list(resume.get("experience") or resume.get("projects") or [])
        if items and wanted:
            def hits(entry: Any) -> int:
                if isinstance(entry, dict):
                    text = as_text({key: entry.get(key) for key in
                                    ("title", "description", "stack", "highlights")})
                else:
                    text = str(entry)
                return sum(1 for word in wanted if word and word in text.lower())

            out["experience" if resume.get("experience") else "projects"] = sorted(
                items, key=hits, reverse=True)

        # 概述：只用已有信息拼，不编造
        pieces: list[str] = []
        title = str(job.get("title") or "").strip()
        if title:
            pieces.append(f"目标岗位：{title}")
        years = resume.get("years") or resume.get("experience_years")
        if years:
            pieces.append(f"{years} 年经验")
        matched = [s for s in skills if set(normalize_skills(s)) & wanted][:4]
        if matched:
            pieces.append("熟悉 " + "、".join(matched))
        if answers:
            pieces.append(f"重点方向：{clip(str(answers[0]['answer']), 60)}")
        if pieces:
            out["summary"] = "；".join(pieces)
        return out


register(ResumeTailorAgent)
