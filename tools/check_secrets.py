"""扫描仓库里是否混进了真实密钥。

用法：
    python tools/check_secrets.py          # 扫 git 跟踪的文件
    python tools/check_secrets.py --all    # 扫工作区（含未跟踪，排除 .state/node_modules）

退出码 0 表示干净，1 表示命中。测试里也调它，所以误提交会被 CI 拦住。

**为什么需要这个**：密钥一旦进了 git 历史，删文件是删不掉的——必须改写历史
强推。与其事后补救，不如提交前拦一道。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: 每一条都是"看起来像真密钥"的形状，而不是占位符。
#: 带 ``(?P<v>...)`` 组的，只对组内容判定（避免把 ``os.environ[...]`` 这类表达式当密钥）。
_SECRET_NAMES = r"(?:PGPASSWORD|ARK_API_KEY|ARK_IMAGE_KEY|TIANYANCHA_TOKEN|TIANYANCHA_API_KEY)"

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("火山方舟/Ark key", re.compile(r"ark-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}")),
    ("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("OpenAI/通用 sk-", re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
    ("明文 Bearer", re.compile(r"Bearer\s+(?P<v>[A-Za-z0-9\-_.]{20,})")),
    ("带密码的连接串", re.compile(r"(?:postgres(?:ql)?|mysql)://[^\s:@/]+:[^\s@/]{3,}@")),
    ("环境变量字面量", re.compile(_SECRET_NAMES + r"""\s*=\s*["'](?P<v>[^"'\s]{6,})["']""")),
    ("环境变量裸值", re.compile(_SECRET_NAMES + r"\s*=\s*(?P<v>[A-Za-z0-9_\-]{6,})\s*$")),
]

#: 这些词出现在值里就当占位符，不算命中
PLACEHOLDERS = ("<", "...", "${", "=", "xxxx", "your", "changeme", "placeholder",
                "填", "占位", "示例")

SKIP_DIRS = {".git", ".state", "node_modules", "__pycache__", ".pytest_cache",
             "dist", "out", ".venv", "venv"}
SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf",
               ".zip", ".exe", ".dll", ".woff", ".woff2"}


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                             text=True, encoding="utf-8", timeout=30)
    except Exception:  # noqa: BLE001
        return []
    if out.returncode != 0:
        return []
    return [ROOT / line.strip() for line in out.stdout.splitlines() if line.strip()]


def workspace_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIX:
            continue
        files.append(path)
    return files


def scan(files: list[Path]) -> list[tuple[Path, int, str, str]]:
    findings: list[tuple[Path, int, str, str]] = []
    for path in files:
        try:
            if path.stat().st_size > 2_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if "check_secrets" in line and "PATTERNS" in line:
                continue
            for label, pattern in PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                # 有命名组的只看组内容，避免整行都算进去
                groups = match.groupdict()
                value = groups.get("v") or match.group(0)
                lowered = value.lower()
                if any(token.lower() in lowered for token in PLACEHOLDERS):
                    continue
                findings.append((path, lineno, label, _mask(value)))
    return findings


def _mask(value: str, keep: int = 6) -> str:
    """命中内容只露头尾，避免扫描报告本身泄漏密钥。"""
    if len(value) <= keep * 2:
        return value[:2] + "***"
    return f"{value[:keep]}…{value[-4:]}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="扫工作区而不只是 git 跟踪文件")
    args = parser.parse_args()

    files = workspace_files() if args.all else tracked_files()
    if not files:
        print("没有可扫的文件（不在 git 仓库里？）")
        return 0

    findings = scan(files)
    print(f"扫描 {len(files)} 个文件…")
    if not findings:
        print("干净：没有发现密钥特征。")
        return 0

    print(f"\n发现 {len(findings)} 处疑似密钥：")
    for path, lineno, label, masked in findings:
        rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        print(f"  {rel}:{lineno}  [{label}]  {masked}")
    print("\n处理建议：删掉该值、改从环境变量或 .state/ 读；"
          "如果已经提交过，需要改写历史后再强推。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
