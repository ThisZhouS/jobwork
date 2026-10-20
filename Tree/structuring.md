# boss_crawler/structuring —— 结构化层（纯函数，无 IO）

输入是平台返回的文本/字典，输出是结构化字段。**不读写文件、不连数据库、不调模型**，
因此可以完全离线单测（`tests/test_jd.py`、`tests/test_clean.py` 共 41 条）。

## 文件

| 文件 | 职责 | 关键符号 |
|---|---|---|
| `__init__.py` | 门面，跨包只用这里 | 22 个导出 |
| `jd.py` | JD 结构化编排 | `structure_jd(description, *, title, welfare, experience)` |
| `jd_sections.py` | 分节与切条目 | `SECTION_NAMES`、`split_sections`、`_find_headers`、`_split_items`、`_split_banner`、`_looks_like_duty`、`_dedupe` |
| `jd_extract.py` | 标量字段抽取 | `extract_years` `extract_degree` `extract_hiring_count` `extract_schedule` `extract_benefits` `extract_seniority` |
| `jd_skills.py` | 技能识别与规范化 | `SKILL_WORDS` `extract_skills` `normalize_skills` `skill_category` |
| `text.py` | 文本与地址 | `normalize_text` `clean_company` `extract_legal_name` `parse_address` `salary_unit` `collapse_repeat_prefix/tail` |
| `cleaning.py` | 记录级清洗 | `clean_record` `build_companies` `build_report` |

## 数据结构（`structure_jd` 输出）

```python
{
  "has_jd": bool, "jd_length": int,
  "sections": {"responsibilities": [...], "requirements": [...], "bonus": [...],
               "benefits": [...], "company": [...], "location": [...],
               "schedule": [...], "other": [...]},
  "responsibilities": [str], "requirements": [str],
  "skills": [str], "benefits": [str],
  "min_years": int|None, "max_years": int|None, "years_text": str,
  "degree_required": str, "hiring_count": int|None,
  "work_schedule": str, "seniority": str,
  "percent_mentions": [str],
}
```

## 扩展方式

* **加技能词**：只改 `jd_skills.SKILL_WORDS`（词表 -> 类别），不动逻辑；
* **加小节名**：只改 `jd_sections.SECTION_NAMES`（长词在前，保证最长匹配）；
* **加福利/工时/资深度**：改 `jd_extract` 里的 `_BENEFIT_WORDS` / `_SCHEDULE_RULES` / `_SENIORITY_RULES`；
* **加字段**：在 `structure_jd` 里组装，并同步 `store/schema.py` 的列与 `store/postgres.py` 的 `JOB_COLUMNS`。

## 设计约束

抽不到就留空，**不猜测、不用模型补写**。例：JD 没写年限返回 `None`，而不是沿用
列表页的 `experience`（两者语义不同，`experience` 单独保留在记录里）。
