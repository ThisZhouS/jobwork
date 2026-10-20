"""生成 UI 概念图（第二版）：把提示词写成精确的版式规格。

设计思路：既然图像模型的文字渲染不可靠，提示词就不再依赖"图里写对中文"，
而是用**几何描述**（几栏、多宽、什么组件在什么位置）来固定版式。这样：
  - 图用来定风格与版式方向；
  - ``Tree/desktop-redesign.md`` 里的令牌与栅格是唯一权威；
  - 代码按令牌实现，不按图里那些糊掉的文字实现。

用法：
    python tools/gen_ui_concepts.py                # 全部
    python tools/gen_ui_concepts.py --only 03      # 只生成某张
密钥：环境变量 ARK_IMAGE_KEY（或 .state/ark_image_key.txt）。
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import urllib.request
from pathlib import Path

API_URL = "https://ark.cn-beijing.volces.com/api/plan/v3/images/generations"
MODEL = "doubao-seedream-5.0-pro"
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "concepts" / "v2"

# ---------------------------------------------------------------- 设计令牌
# 这些值同时写进 renderer/style.css，图与代码用同一套
STYLE = (
    "dark navy enterprise analytics dashboard, deep background #0A0F1C, "
    "panels #111A2E with 1px border #223052, rounded corners 12px, "
    "cyan accent #22D3EE and blue #3B82F6, green #34D399 amber #FBBF24 red #F87171 accents, "
    "left vertical sidebar 216px wide with icon+label nav, "
    "56px top bar with breadcrumb on left and small status chips on right, "
    "dense but airy data tables, thin dividers, no drop shadows, flat vector, "
    "crisp 1px strokes, high information density, professional B2B software, "
    "no 3D, no skeuomorphism, no gradients on text, no watercolor, no stock photos"
)

CONCEPTS = [
    {
        "name": "01-overview",
        "note": "概览：4 KPI + 主表格 + 右栏",
        "prompt": (
            "Desktop application screen, overview dashboard. "
            "LEFT: 216px sidebar, brand square at top, six nav rows (icon + short label). "
            "TOP: 56px bar, breadcrumb text left, two small pill chips right. "
            "BODY: a row of four equal KPI cards, each with a large cyan number and a small label below. "
            "Below that, a two-column area: left column is a wide data table with 8 columns "
            "and 6 rows, header row dimmer, right-aligned numeric columns, small colored grade badges; "
            "right column is a narrower panel with a vertical ranked list of five rows, "
            "each row a label on the left and a number plus badge on the right. "
            f"{STYLE}."
        ),
        "size": "2K",
    },
    {
        "name": "02-company-detail",
        "note": "公司详情：雷达 + 基本信息 + 分区",
        "prompt": (
            "Desktop application screen, company detail. "
            "LEFT: 216px sidebar with six nav rows. TOP: 56px bar with breadcrumb. "
            "HEADER BLOCK: large company name on the left, then a small status pill, "
            "a large score number, a letter grade badge, and a small warning pill. "
            "BODY ROW 1: left card contains a pentagon radar chart with five axes and a filled translucent polygon; "
            "right card contains a definition list of eight label/value pairs in two columns. "
            "BODY ROW 2: two equal cards side by side, left card has four thin horizontal progress bars "
            "with labels and numbers, right card has a compact list of five job rows with small tags. "
            "BODY ROW 3: a full-width card with a list of six review rows, each with a tiny colored sentiment dot. "
            f"{STYLE}."
        ),
        "size": "2K",
    },
    {
        "name": "03-skill-cloud",
        "note": "技能词云：云 + 右侧榜单",
        "prompt": (
            "Desktop application screen, skills word cloud page. "
            "LEFT: 216px sidebar. TOP: 56px bar. "
            "BODY: single large panel containing a centered word cloud where word sizes vary strongly by frequency, "
            "one very large word in the middle, several medium words around it, many small words at the edges, "
            "all words cyan to light blue, generous spacing. "
            "Below the cloud, a thin horizontal bar with three small filter chips on the left and a count text on the right. "
            "RIGHT RAIL: a narrow 260px panel listing the top ten words as rows with a label on the left, "
            "a small horizontal bar in the middle, and a number on the right. "
            f"{STYLE}."
        ),
        "size": "2K",
    },
    {
        "name": "04-jobs",
        "note": "岗位：筛选条 + 表格",
        "prompt": (
            "Desktop application screen, job listings with filters. "
            "LEFT: 216px sidebar. TOP: 56px bar. "
            "BODY ROW 1: a single wide panel acting as a filter bar with four dropdown selects, "
            "one text input, one number input, and a primary blue button on the right. "
            "BODY ROW 2: a wide data table with six columns and nine rows, each row has a bold job title, "
            "a muted company name, a salary chip, a city text, and a numeric score column with colored grade badge. "
            "BODY ROW 3: pagination row with small text on the left and three small buttons on the right. "
            f"{STYLE}."
        ),
        "size": "2K",
    },
    {
        "name": "05-job-detail",
        "note": "岗位详情：左正文 + 右来源与公司",
        "prompt": (
            "Desktop application screen, single job detail. "
            "LEFT: 216px sidebar. TOP: 56px bar with breadcrumb. "
            "HEADER: large job title, salary chip, city chip, score number with grade badge. "
            "BODY: two columns. Left wide column is a card with a vertical list of five label/value definition rows, "
            "then a row of small tag chips, then a long paragraph block of body text in a lighter muted color. "
            "Right narrow column stacks three cards: first card is company summary with a name and a score badge, "
            "second card is source info with two label/value rows and one link line, "
            "third card has five thin progress bars labeled with dimension names. "
            f"{STYLE}."
        ),
        "size": "2K",
    },
    {
        "name": "06-chat-drawer",
        "note": "对话口：底部抽屉盖在内容上",
        "prompt": (
            "Desktop application screen, same analytics dashboard, with a bottom sheet drawer open. "
            "LEFT: 216px sidebar. TOP: 56px bar. Background content is a data table partially visible behind. "
            "BOTTOM SHEET: a drawer spanning from the left sidebar edge to the right edge, occupying about 40 percent "
            "of screen height, with a 1px top border and a slightly lighter panel background, "
            "header row with a title on the left and a small text button on the right, "
            "a scrollable message area with five message blocks (each a small muted author line above a rounded bubble), "
            "and a bottom input area with a text field and a primary button. "
            "A circular floating action button with a chat glyph sits at the bottom right above the drawer. "
            f"{STYLE}."
        ),
        "size": "2K",
    },
]


def _read_key() -> str:
    """只从环境变量或 .state 读，不接受命令行参数——命令行会进 shell 历史和进程列表。"""
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
    raise SystemExit("缺少密钥：设置环境变量 ARK_IMAGE_KEY，或写入 .state/ark_image_key.txt")


def _fetch(prompt: str, size: str, key: str) -> bytes:
    payload = {"model": MODEL, "prompt": prompt, "size": size,
               "output_format": "jpeg", "watermark": False}
    request = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        body = json.loads(response.read().decode("utf-8"))
    data = (body.get("data") or [{}])[0]
    if data.get("b64_json"):
        return base64.b64decode(data["b64_json"])
    if data.get("url"):
        with urllib.request.urlopen(data["url"], timeout=180) as image:
            return image.read()
    raise RuntimeError(f"返回里没有图片：{json.dumps(body, ensure_ascii=False)[:300]}")


def _shrink(blob: bytes, max_width: int = 1600) -> bytes:
    """存成定宽 JPEG：概念图只需看版式，没必要留 5MB PNG。"""
    from PIL import Image

    with Image.open(io.BytesIO(blob)) as image:
        image = image.convert("RGB")
        if image.width > max_width:
            height = int(image.height * max_width / image.width)
            image = image.resize((max_width, height), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=86, optimize=True)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default=None, help="只生成某张（如 01）")
    parser.add_argument("--no-shrink", action="store_true")
    args = parser.parse_args()

    key = _read_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []

    for concept in CONCEPTS:
        if args.only and not concept["name"].startswith(args.only):
            continue
        print(f"生成 {concept['name']}（{concept['note']}）…", flush=True)
        try:
            blob = _fetch(concept["prompt"], concept["size"], key)
            if not args.no_shrink:
                blob = _shrink(blob)
        except Exception as exc:  # noqa: BLE001
            print(f"  失败：{type(exc).__name__}: {exc}")
            continue
        path = OUT_DIR / f"{concept['name']}.jpg"
        path.write_bytes(blob)
        print(f"  OK {len(blob)//1024} KB → {path.name}")
        manifest.append({"file": path.name, "note": concept["note"],
                         "size": concept["size"], "bytes": len(blob)})

    if manifest:
        index = OUT_DIR / "manifest.json"
        existing = []
        if index.exists():
            try:
                existing = json.loads(index.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                existing = []
        merged = {row["file"]: row for row in existing}
        for row in manifest:
            merged[row["file"]] = row
        index.write_text(json.dumps(sorted(merged.values(), key=lambda r: r["file"]),
                                    ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n清单：{index}")
    print(f"输出目录：{OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
