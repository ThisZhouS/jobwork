"""生成 UI 概念图：验证 doubao-seedream-5.0-pro 接口。

用法：
    python tools/gen_ui_concepts.py

密钥从环境变量 ARK_IMAGE_KEY 或命令行 --key 读取，不落仓库。
输出到 .state/ui-concepts/。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

API_URL = "https://ark.cn-beijing.volces.com/api/plan/v3/images/generations"
MODEL = "doubao-seedream-5.0-pro"
OUT_DIR = Path(__file__).resolve().parent.parent / ".state" / "ui-concepts"

# 统一风格基调：深蓝科技感、深色主题、数据可视化向
STYLE = "deep navy blue tech style, dark theme, data visualization dashboard, clean modern UI, subtle grid lines, cyan and blue accents, professional, high quality, 4k"

CONCEPTS = [
    {
        "name": "01-概览-dashboard",
        "prompt": (
            "A desktop app dashboard page for a job-hunting due-diligence workbench. "
            "Left sidebar navigation with icons: Overview, Jobs, Companies, Resume, Settings. "
            "Main area shows KPI cards (companies tracked, jobs scored, evidence collected), "
            "a skill word cloud panel, and a list of top companies with dimension scores. "
            f"Style: {STYLE}. Flat design, no 3D, no gradients on text, no lorem ipsum, "
            "Chinese labels like 概览, 岗位, 公司, 简历, 技能词云, 风险, 待遇, 压力, 环境, 福利."
        ),
        "size": "2K",
    },
    {
        "name": "02-公司详情-company-detail",
        "prompt": (
            "A desktop app company detail page. Header: company name + registration status badge + total score 67.6 with grade C. "
            "Body left: radar chart with 5 axes labeled 风险/待遇/压力/环境/福利. "
            "Body right: sections for 基本信息 (registration info table), 风险 (risk counts), 评价 (review list from zhihu/tieba). "
            "Bottom: 在招岗位 job list with salary tags. A badge shows 是否劳务派遣: 否. "
            f"Style: {STYLE}. Clean layout, data-dense, Chinese labels."
        ),
        "size": "2K",
    },
    {
        "name": "03-技能词云-skill-cloud",
        "prompt": (
            "A skill word cloud visualization panel. Center shows large 'Python', medium 'MySQL', 'SQL', '数据分析', "
            "smaller 'Redis', 'Go', 'Java'. Dark background, cyan/blue text gradient sizes by frequency. "
            "Panel title 技能词云, subtitle 出现在 21 个岗位. "
            f"Style: {STYLE}. Minimal, no extra decorations."
        ),
        "size": "2K",
    },
    {
        "name": "04-对话口-chat-drawer",
        "prompt": (
            "A desktop app with a bottom slide-up drawer panel open. The drawer shows a conversation: "
            "system asks '目标岗位最想强调哪一段经历？', user answers '后端高并发订单系统那段'. "
            "Above the drawer, the main app shows a job list with filter chips (薪资, 经验, 学历). "
            f"Style: {STYLE}. The drawer has a subtle top border and shadow, Chinese labels."
        ),
        "size": "2K",
    },
]


def _read_key(cli_key: str | None) -> str:
    if cli_key:
        return cli_key.strip()
    for env in ("ARK_IMAGE_KEY", "ARK_API_KEY"):
        value = os.environ.get(env, "").strip()
        if value:
            return value
    key_file = Path(__file__).resolve().parent.parent / ".state" / "ark_image_key.txt"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    raise SystemExit("缺少密钥：设置 ARK_IMAGE_KEY 或传 --key，或写入 .state/ark_image_key.txt")


def generate(prompt: str, size: str, key: str) -> tuple[bytes, str]:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "size": size,
        "output_format": "png",
        "watermark": False,
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read().decode("utf-8"))

    data = (body.get("data") or [{}])[0]
    if data.get("b64_json"):
        return base64.b64decode(data["b64_json"]), "b64"
    if data.get("url"):
        with urllib.request.urlopen(data["url"], timeout=120) as img:
            return img.read(), "url"
    raise RuntimeError(f"返回里没有图片：{json.dumps(body, ensure_ascii=False)[:400]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", default=None, help="API 密钥（也可用 ARK_IMAGE_KEY）")
    parser.add_argument("--only", default=None, help="只生成某一张（如 01）")
    args = parser.parse_args()

    key = _read_key(args.key)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for concept in CONCEPTS:
        if args.only and not concept["name"].startswith(args.only):
            continue
        print(f"生成 {concept['name']} ...", flush=True)
        try:
            blob, via = generate(concept["prompt"], concept["size"], key)
        except Exception as exc:
            print(f"  失败：{type(exc).__name__}: {exc}")
            continue
        path = OUT_DIR / f"{concept['name']}.png"
        path.write_bytes(blob)
        print(f"  OK（{via}，{len(blob) // 1024} KB）→ {path}")

    print(f"\n完成，输出目录：{OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
