"""把 research/industry_codes.json 生成为 boss_crawler/industry_codes.py。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
data = json.loads((ROOT / "research" / "industry_codes.json").read_text(encoding="utf-8"))

lines = [
    '"""BOSS直聘 行业名称 -> 行业码。',
    "",
    "数据由 research/collect_industry_codes.py 从真实职位数据采集；",
    "接口的 industry 参数接受这些数字码，父级码会自动包含子行业。",
    '"""',
    "",
    "INDUSTRY_CODES = {",
]
for name, code in sorted(data.items(), key=lambda kv: kv[1]):
    lines.append(f"    {name!r}: {str(code)!r},")
lines.append("}")
lines.append("")

target = ROOT / "boss_crawler" / "industry_codes.py"
target.write_text("\n".join(lines), encoding="utf-8")
print("written", len(data), "entries ->", target)
