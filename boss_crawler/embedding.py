"""向量化：调用火山方舟（Ark）的 doubao-embedding-vision 生成文本向量。

实测（2026-10，本账号）：
  * 可用端点是 `https://ark.cn-beijing.volces.com/api/plan/v3`，
    官方 `/api/v3` 会返回 401（The API key or AK/SK ... invalid）；
  * `POST {base}/embeddings`，body `{"model": ..., "input": ["文本", ...]}`
    支持批量，返回 OpenAI 风格结构，**维度 2048**；
  * `POST {base}/embeddings/multimodal` 接受 `[{"type":"text","text":...}]`，
    图文混排时用这个路径。
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import requests

from . import config


class EmbeddingError(RuntimeError):
    """向量化失败（密钥、额度、网络或响应结构异常）。"""


def load_api_key(path: Path | None = None) -> str:
    """优先环境变量 ARK_API_KEY，其次 .state/ark_key.txt。"""
    import os

    key = (os.environ.get("ARK_API_KEY") or "").strip()
    if key:
        return key
    key_file = path or config.ARK_KEY_FILE
    if key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()
    if not key:
        raise EmbeddingError(
            f"未找到方舟密钥：请设置环境变量 ARK_API_KEY 或写入 {key_file}"
        )
    return key


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _clip(text: str, limit: int | None = None) -> str:
    limit = limit or config.EMBED_MAX_CHARS
    text = " ".join(str(text or "").split())
    return text[:limit]


def job_embedding_text(job: dict) -> str:
    """岗位向量化的「必要数据」：岗位、公司、地点、薪资、经验学历、技能、JD 摘要。"""
    company = job.get("company") or {}
    workplace = job.get("workplace") or {}
    parts = [
        f"岗位：{job.get('title', '')}",
        f"公司：{company.get('name', '')}",
        f"行业：{company.get('industry', '')}",
        f"地点：{workplace.get('city', '')}{workplace.get('district', '')}{workplace.get('business_district', '')}",
        f"地址：{workplace.get('full', '')}",
        f"薪资：{job.get('salary', '')}",
        f"经验：{job.get('experience', '')}",
        f"学历：{job.get('degree', '')}",
    ]
    skills = job.get("skills_all") or job.get("skills") or []
    if skills:
        parts.append("技能：" + "、".join(str(s) for s in skills))
    welfare = job.get("jd_benefits") or job.get("welfare") or []
    if welfare:
        parts.append("福利：" + "、".join(str(w) for w in welfare))
    # 结构化后的职责/要求比原始 JD 更聚焦：优先用它们，再补 JD 原文
    for label, key in (("职责", "responsibilities"), ("要求", "requirements")):
        items = job.get(key) or []
        if items:
            parts.append(f"{label}：" + "；".join(str(item) for item in items[:6]))
    if job.get("description"):
        parts.append("描述：" + _clip(job["description"], config.EMBED_MAX_CHARS // 2))
    return _clip("\n".join(p for p in parts if p.split("：", 1)[-1].strip()))


def company_embedding_text(company: dict) -> str:
    """公司向量化的「必要数据」：名称、工商全称、行业、规模、融资、介绍、地址。"""
    parts = [
        f"公司：{company.get('company_name', '')}",
        f"工商全称：{company.get('legal_name', '')}",
        f"行业：{company.get('industry', '')}",
        f"规模：{company.get('scale', '')}",
        f"融资阶段：{company.get('stage', '')}",
        f"城市：{'、'.join(company.get('cities') or [])}",
        f"地址：{'；'.join(company.get('addresses') or [])}",
    ]
    if company.get("intro"):
        parts.append("介绍：" + _clip(company["intro"]))
    return _clip("\n".join(p for p in parts if p.split("：", 1)[-1].strip()))


class ArkEmbedder:
    """批量向量化客户端：失败重试、返回顺序与入参一致。"""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        model: str | None = None,
        batch_size: int | None = None,
        timeout: int = 60,
        max_retries: int = 3,
        log=print,
    ) -> None:
        self.api_key = api_key or load_api_key()
        self.base_url = (base_url or config.ARK_BASE_URL).rstrip("/")
        self.model = model or config.ARK_MODEL
        self.batch_size = batch_size or config.ARK_BATCH_SIZE
        self.timeout = timeout
        self.max_retries = max_retries
        self.log = log
        self.dim: int | None = None

    # ------------------------------------------------------------------ 请求
    def _post(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": self.model, "input": texts}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error = ""
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.post(
                    f"{self.base_url}/embeddings",
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code == 200:
                    return self._parse(response.json())
                last_error = f"HTTP {response.status_code} {self._error_message(response)}"
                # 4xx（除 429）重试没有意义
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    raise EmbeddingError(f"向量化被拒绝：{last_error}")
            if attempt < self.max_retries:
                sleep_for = 2.0 * attempt
                self.log(f"  ! 向量化失败（{last_error}），{sleep_for:.0f}s 后重试 {attempt}/{self.max_retries}")
                time.sleep(sleep_for)
        raise EmbeddingError(f"向量化失败：{last_error}")

    @staticmethod
    def _error_message(response) -> str:
        try:
            body = response.json()
        except ValueError:
            return response.text[:200]
        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)[:200]
        return json.dumps(body, ensure_ascii=False)[:200]

    def _parse(self, body: dict) -> list[list[float]]:
        data = body.get("data")
        if isinstance(data, dict):  # multimodal 路径可能返回单个对象
            data = [data]
        if not isinstance(data, list) or not data:
            raise EmbeddingError(f"响应缺少 data：{json.dumps(body, ensure_ascii=False)[:200]}")
        rows = sorted(data, key=lambda item: item.get("index", 0))
        vectors = [row.get("embedding") for row in rows]
        if any(not isinstance(vec, list) or not vec for vec in vectors):
            raise EmbeddingError("响应里的 embedding 不是非空数组")
        self.dim = len(vectors[0])
        if any(len(vec) != self.dim for vec in vectors):
            raise EmbeddingError("同一批返回的向量维度不一致")
        return vectors

    # ------------------------------------------------------------------ 对外
    def embed(self, texts: list[str]) -> list[list[float]]:
        """按批向量化，返回顺序与入参严格一致。"""
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            vectors.extend(self._post(batch))
        return vectors

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]
