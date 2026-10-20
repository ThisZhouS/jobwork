"""数据集加载：把散落的 JSONL 合并成一份可用数据集。

三个命令（``enrich`` / ``process`` / ``db-load`` / ``embed``）都需要「读输入目录下
所有 JSONL → 按 job_id 合并 → 得到记录列表」。这段逻辑以前在 CLI 里重复了四遍，
现在集中在这里，改一处即可。

约定：

* ``expand_inputs`` 只做 glob 展开，并**跳过清洗产物**（``output/clean/*``），
  避免把已清洗的记录当成原始数据再次吞进去；
* ``merge_record`` 的合并语义是「非空值覆盖空值、字符串取更长、列表取并集」，
  因为详情是分批补的，后到的记录往往更完整；
* ``load_raw_records`` 返回 ``{job_id: record}``，``load_clean_records`` 返回
  ``(清洗后的 jobs, 原始记录索引, 公司聚合)``。
"""

from __future__ import annotations

from pathlib import Path

from .. import config
from ..structuring import build_companies, clean_record

def expand_inputs(patterns: list[str]) -> list[Path]:
    """支持 文件 / 目录 / glob（相对当前目录）。

    通配符和目录展开时会跳过清洗产物（`jobs_clean.jsonl`、clean/ 目录），
    否则 `output/*.jsonl` 会把上一次的清洗结果再当成原始数据读一遍；
    显式写出的路径（如 `output/clean/enriched.jsonl`）不跳过。
    """
    import glob as globmod

    found: list[tuple[Path, bool]] = []
    for pattern in patterns:
        path = Path(pattern)
        if any(ch in pattern for ch in "*?["):
            found.extend((Path(p), False) for p in globmod.glob(pattern))
        elif path.is_dir():
            found.extend((p, False) for p in sorted(path.glob("*.jsonl")))
        elif path.exists():
            found.append((path, True))

    seen: set[Path] = set()
    ordered: list[Path] = []
    for item, explicit in found:
        resolved = item.resolve()
        if resolved in seen or item.suffix != ".jsonl":
            continue
        if not explicit and (item.name == "jobs_clean.jsonl" or item.parent.name == "clean"):
            continue
        seen.add(resolved)
        ordered.append(item)
    return ordered


def merge_record(base: dict, extra: dict) -> dict:
    """同一岗位在多份文件里出现时合并：非空字段优先，地址优先保留完整的那份。"""
    for key, value in extra.items():
        if value in (None, "", [], {}):
            continue
        if base.get(key) in (None, "", [], {}):
            base[key] = value
        elif key == "address" and len(str(value)) > len(str(base.get(key) or "")):
            base[key] = value
    return base


def load_raw_records(inputs: list[str]) -> dict[str, dict]:
    """读出「原始」记录并合并（跳过已清洗产物）。"""
    import json

    records: dict[str, dict] = {}
    for path in expand_inputs(inputs):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if isinstance(record.get("company"), dict):
                    continue
                key = record.get("job_id") or f"{record.get('title')}|{record.get('company')}"
                record.setdefault("job_id", key)
                if key in records:
                    merge_record(records[key], record)
                else:
                    records[key] = record
    return records


def load_clean_records(inputs: list[str]):
    """读取原始 JSONL -> (清洗后的 jobs, raw_by_id, companies)。"""
    import json

    from ..structuring import build_companies, clean_record

    raw_by_id: dict[str, dict] = {}
    jobs: list[dict] = []
    for path in expand_inputs(inputs):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if isinstance(record.get("company"), dict):
                    continue  # 已清洗的产物
                key = record.get("job_id") or f"{record.get('title')}|{record.get('company')}"
                if key in raw_by_id:
                    merge_record(raw_by_id[key], record)
                else:
                    raw_by_id[key] = record
    for key, record in raw_by_id.items():
        record.setdefault("job_id", key)
        jobs.append(clean_record(record, source_file=record.get("source_file", "")))
    return jobs, raw_by_id, build_companies(jobs)
