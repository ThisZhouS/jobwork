"""探测 Ark 是否能用当前密钥做「看图」：把概念图压小后当图片输入问模型。

只打印状态码与回答片段，不打印密钥。
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / ".state" / "ui-concepts" / "01-概览-dashboard.png"

# 端点候选：图片生成在 plan/v3 上可用，聊天可能在 plan/v3 或 v3
ENDPOINTS = [
    "https://ark.cn-beijing.volces.com/api/plan/v3/chat/completions",
    "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
]

MODELS = [
    "doubao-seed-1.6",
    "doubao-1.5-vision-pro-32k",
    "doubao-vision-pro-32k",
    "doubao-seed-1.6-vision",
    "doubao-1.5-vision-lite",
]

PROMPT = (
    "这是一个桌面软件界面的设计稿。请只描述你看到的布局事实，不要评价："
    "1) 整体分成几块，各在什么位置；2) 每块里有哪些组件（表格/图表/卡片/列表）；"
    "3) 顶部和左侧分别有什么；4) 有哪些可见的中文标签。"
)


def load_key() -> str:
    for env in ("ARK_IMAGE_KEY", "ARK_API_KEY"):
        value = os.environ.get(env, "").strip()
        if value:
            return value
    for name in ("ark_image_key.txt", "ark_key.txt"):
        path = ROOT / ".state" / name
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    raise SystemExit("没有密钥：设置 ARK_IMAGE_KEY / ARK_API_KEY")


def jpeg_b64(path: Path, max_width: int = 1280) -> str:
    """压到可接受的体积（原图 5MB 太大，接口会拒）。"""
    from PIL import Image

    with Image.open(path) as image:
        image = image.convert("RGB")
        if image.width > max_width:
            height = int(image.height * max_width / image.width)
            image = image.resize((max_width, height), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=82, optimize=True)
    raw = buffer.getvalue()
    print(f"  压图 {image.width}x{image.height}  {len(raw)//1024} KB", flush=True)
    return base64.b64encode(raw).decode()


def main() -> int:
    if not IMG.exists():
        print(f"找不到图：{IMG}")
        return 2
    key = load_key()
    b64 = jpeg_b64(IMG)

    for endpoint in ENDPOINTS:
        for model in MODELS:
            payload = {
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        {"type": "text", "text": PROMPT},
                    ],
                }],
                "max_tokens": 900,
            }
            try:
                response = requests.post(
                    endpoint, headers={"Authorization": f"Bearer {key}",
                                       "Content-Type": "application/json"},
                    json=payload, timeout=120,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[{endpoint.split('/api/')[1].split('/')[0]}] {model} 网络 {type(exc).__name__}")
                continue

            host = endpoint.split("/api/")[1].split("/")[0]
            if response.status_code == 200:
                body = response.json()
                text = (body.get("choices") or [{}])[0].get("message", {}).get("content", "")
                print(f"\n*** 成功：{host} / {model} ***\n")
                print(text)
                return 0

            message = ""
            try:
                message = response.json().get("error", {}).get("message", "")[:90]
            except Exception:  # noqa: BLE001
                message = response.text[:90]
            print(f"[{host}] {model} -> {response.status_code} {message}")

    print("\n所有组合都不可用：当前密钥没有对话/视觉权限。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
