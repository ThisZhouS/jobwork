"""尝试密钥的几种拆分形式，找出可用的那个（只打印状态码/结构，不打印密钥）。"""
import json
from pathlib import Path

import requests

RAW = Path(r"E:\tmp\jobs\.state\ark_key.txt").read_text(encoding="utf-8").strip()
BASE = "https://ark.cn-beijing.volces.com"
TEXT = "Python 后端开发工程师，负责数据分析平台"

VARIANTS = {
    "原样": RAW,
    "去掉 ark- 前缀": RAW.removeprefix("ark-"),
    "去掉末尾段": RAW.rsplit("-", 1)[0],
    "去掉前缀与末尾": RAW.removeprefix("ark-").rsplit("-", 1)[0],
    "末段作为 key": RAW.rsplit("-", 1)[1],
    "ark- + 末段": f"ark-{RAW.rsplit('-', 1)[1]}",
}

CALLS = [
    ("/api/v3/embeddings", lambda m: {"model": m, "input": [TEXT]}),
    ("/api/v3/embeddings/multimodal", lambda m: {"model": m, "input": [{"type": "text", "text": TEXT}]}),
]

MODELS = ["doubao-embedding-vision-250328", "doubao-embedding-vision-241215"]


def summarize(payload: dict) -> str:
    data = payload.get("data")
    if isinstance(data, list) and data:
        emb = data[0].get("embedding")
        return f"dim={len(emb)} keys={list(data[0].keys())}"
    if isinstance(data, dict):
        emb = data.get("embedding")
        return f"dim={len(emb) if isinstance(emb, list) else '?'} keys={list(data.keys())}"
    return json.dumps(payload, ensure_ascii=False)[:160]


for label, key in VARIANTS.items():
    if not key:
        continue
    for path, build in CALLS:
        for model in MODELS:
            try:
                response = requests.post(
                    BASE + path,
                    headers={"Authorization": f"Bearer {key}"},
                    json=build(model),
                    timeout=40,
                )
            except Exception as exc:
                print(f"[{label}] {path} 网络错误 {type(exc).__name__}")
                break
            if response.status_code == 200:
                print(f"[{label}] {path} [{model}] 200 -> {summarize(response.json())}")
                raise SystemExit(0)
            message = ""
            try:
                message = response.json().get("error", {}).get("message", "")[:60]
            except ValueError:
                message = response.text[:60]
            print(f"[{label}] {path} [{model}] {response.status_code} {message}")
            if "model" in message.lower() and "not" in message.lower():
                break
    print("---")
print("所有拆分都失败")
