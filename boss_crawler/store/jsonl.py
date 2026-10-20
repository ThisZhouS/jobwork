"""落盘：内存聚合 + JSONL 主存 + CSV 导出。

详情是后补的，所以用 upsert 语义（按 job_id 合并），最后统一 flush。
"""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path

CSV_COLUMNS = [
    "job_id", "title", "salary", "salary_min", "salary_max", "city", "district",
    "business_district", "experience", "degree", "company", "industry",
    "industry_code", "stage", "scale", "boss_name", "boss_title", "boss_online",
    "skills", "welfare", "description", "address", "url",
]


class JobStore:
    def __init__(self, out_dir: Path, name: str) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.jsonl_path = out_dir / f"{name}_{stamp}.jsonl"
        self.csv_path = out_dir / f"{name}_{stamp}.csv"
        self._records: dict[str, dict] = {}

    def upsert(self, job: dict) -> bool:
        """返回 True 表示新增，False 表示合并更新。"""
        key = job.get("job_id") or f"{job.get('title')}|{job.get('company')}"
        existing = self._records.get(key)
        if existing is None:
            self._records[key] = dict(job)
            return True
        existing.update({k: v for k, v in job.items() if v not in (None, "", [], {})})
        return False

    def flush(self) -> Path:
        with self.jsonl_path.open("w", encoding="utf-8") as fh:
            for record in self._records.values():
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return self.jsonl_path

    def export_csv(self) -> Path:
        self.flush()
        with self.csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for record in self._records.values():
                row = {k: record.get(k, "") for k in CSV_COLUMNS}
                for key in ("skills", "welfare"):
                    if isinstance(row.get(key), list):
                        row[key] = " / ".join(row[key])
                writer.writerow(row)
        return self.csv_path

    def __len__(self) -> int:
        # 注意：__len__ 会让空 JobStore 在布尔判断里变成 False，
        # 所以内部一律用 `is not None` 判断，不要写 `if store:`。
        return len(self._records)

    @property
    def count(self) -> int:
        return len(self._records)

    def records(self) -> list[dict]:
        return list(self._records.values())
