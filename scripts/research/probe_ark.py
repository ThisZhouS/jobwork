"""探测火山方舟（Ark）向量化接口：正确路径、模型名、返回维度。

用户给的是 https://ark.cn-beijing.volces.com/api/plan/v3 ，
官方常见路径是 /api/v3/embeddings（文本）与 /api/v3/embeddings/multimodal（图文）。
这里把候选组合都试一遍，只打印状态码与响应片段（不打印密钥）。
"""
import json
from pathlib import Path

import requests

KEY = Path(r"E:\tmp\jobs\.state\ark_key.txt").read_text(encoding="utf-8").strip()
BASE = "https://ark.cn-beijing.volces.com"
HEADERS = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

TEXT = "Python 后端开发工程师，负责数据分析平台"

MODELS = [
    "doubao-embedding-vision-250328",
    "doubao-embedding-vision-241215",
    "doubao-embedding-vision",
    "doubao-embedding-text-240715",
]

PATHS = [
    ("/api/v3/embeddings", lambda m: {"model": m, "input": [TEXT]}),
    (
        "/api/v3/embeddings/multimodal",
        lambda m: {"model": m, "input": [{"type": "text", "text": TEXT}]},
    ),
    ("/api/plan/v3/embeddings", lambda m: {"model": m, "input": [TEXT]}),
]


def shape(payload: object) -> str:
    """概括响应结构，避免刷屏。"""
    if not isinstance(payload, dict):
        return type(payload).__name__
    out = {"keys": list(payload.keys())}
    data = payload.get("data")
    if isinstance(data, list) and data:
        out["data[0].keys"] = list(data[0].keys())
        emb = data[0].get("embedding")
        if isinstance(emb, list):
            out["dim"] = len(emb)
    elif isinstance(data, dict):
        out["data.keys"] = list(data.keys())
        emb = data.get("embedding")
        if isinstance(emb, list):
            out["dim"] = len(emb)
    if "error" in payload:
        out["error"] = payload["error"]
    return json.dumps(out, ensure_ascii=False)


for path, build in PATHS:
    for model in MODELS:
        try:
            response = requests.post(
                BASE + path, headers=HEADERS, json=build(model), timeout=40
            )
        except Exception as exc:  # 网络层错误
            print(f"{path} [{model}] 网络错误 {type(exc).__name__}: {exc}")
            continue
        if response.status_code != 200:
            body = response.text[:200].replace("\n", " ")
            print(f"{path} [{model}] HTTP {response.status_code} {body}")
            continue
        try:
            print(f"{path} [{model}] 200 -> {shape(response.json())}")
        except ValueError:
            print(f"{path} [{model}] 200 非 JSON: {response.text[:150]}")
        break  # 同一路径下第一个可用模型就够了
