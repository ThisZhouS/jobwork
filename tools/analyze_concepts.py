"""从概念图像素里量出「配色 + 版式骨架」，供前端还原。

视觉模型读不了图时，这是一种仍然"看图"的办法：不猜语义，只量事实——
主色、侧边栏宽度、横向分带位置、卡片边界。

用法：
    python tools/analyze_concepts.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CONCEPTS = ROOT / "docs" / "concepts"


def quantize(pixel: tuple[int, int, int], step: int = 8) -> tuple[int, int, int]:
    return tuple((value // step) * step for value in pixel[:3])


def hexof(pixel) -> str:
    return "#{:02x}{:02x}{:02x}".format(*pixel[:3])


def palette(image: Image.Image, top: int = 10) -> list[tuple[str, float]]:
    small = image.resize((240, int(240 * image.height / image.width)))
    counts = Counter(quantize(p) for p in small.convert("RGB").getdata())
    total = sum(counts.values())
    return [(hexof(color), round(count / total * 100, 1)) for color, count in counts.most_common(top)]


def sidebar_width(image: Image.Image) -> tuple[int, str, str]:
    """左侧导航栏：从左边开始，找到一个持续同色、且与右侧主区不同的列。"""
    rgb = image.convert("RGB")
    width, height = rgb.size
    step_y = max(1, height // 60)
    columns = []
    for x in range(0, min(width, int(width * 0.45)), 2):
        samples = [rgb.getpixel((x, y)) for y in range(0, height, step_y)]
        columns.append((x, quantize(Counter(quantize(s) for s in samples).most_common(1)[0][0])))
    if not columns:
        return 0, "", ""
    side_color = columns[0][1]
    main = quantize(Counter(quantize(s) for s in
                            [rgb.getpixel((x, y)) for x in range(int(width * 0.6), width, 8)
                             for y in range(0, height, step_y)]).most_common(1)[0][0])
    edge = 0
    for x, color in columns:
        if color == side_color:
            edge = x
        else:
            break
    return edge, hexof(side_color), hexof(main)


def bands(image: Image.Image, limit: int = 6) -> list[tuple[int, str]]:
    """横向分带：找整行都接近同一色的"分隔行"（卡片缝/边框）。"""
    rgb = image.convert("RGB")
    width, height = rgb.size
    step_x = max(1, width // 80)
    rows = []
    for y in range(0, height, 2):
        sample = [rgb.getpixel((x, y)) for x in range(int(width * 0.3), width, step_x)]
        dominant = Counter(quantize(s) for s in sample).most_common(1)[0]
        share = dominant[1] / max(1, len(sample))
        if share > 0.9:
            rows.append((y, hexof(dominant[0])))
    # 只保留"颜色变化"的位置
    out, last = [], None
    for y, color in rows:
        if last is None or color != last:
            out.append((y, color))
            last = color
    return out[:limit]


def analyze(path: Path) -> None:
    with Image.open(path) as image:
        image = image.convert("RGB")
        print(f"\n=== {path.name} ===")
        print(f"尺寸: {image.width}x{image.height}")
        print("主色:")
        for color, share in palette(image):
            print(f"  {color}  {share}%")
        edge, side, main = sidebar_width(image)
        print(f"侧栏宽度: {edge}px  侧栏色 {side}  主区色 {main}")
        print("横向分带（颜色变化处）:")
        for y, color in bands(image):
            print(f"  y={y:<5} {color}")


def main() -> int:
    files = sorted(CONCEPTS.glob("*.png"))
    if not files:
        print(f"没有图：{CONCEPTS}")
        return 2
    for path in files:
        analyze(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
