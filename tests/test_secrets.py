"""守住「仓库里不许有密钥」这条线。

扫描逻辑在 tools/check_secrets.py，这里只做断言，这样本地跑 pytest 就等于
跑一次提交前检查。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import check_secrets  # noqa: E402


def test_no_secret_in_tracked_files():
    files = check_secrets.tracked_files()
    if not files:
        pytest.skip("不在 git 仓库里，跳过")
    findings = check_secrets.scan(files)
    detail = "\n".join(
        f"{path.relative_to(ROOT)}:{lineno} [{label}] {masked}"
        for path, lineno, label, masked in findings)
    assert not findings, f"仓库里出现疑似密钥：\n{detail}"


def test_no_secret_in_workspace():
    findings = check_secrets.scan(check_secrets.workspace_files())
    detail = "\n".join(
        f"{path.relative_to(ROOT)}:{lineno} [{label}] {masked}"
        for path, lineno, label, masked in findings)
    assert not findings, f"工作区里出现疑似密钥：\n{detail}"


def test_state_dir_is_not_tracked():
    """运行期状态（含 key/cookie）必须始终被 .gitignore 排除。"""
    try:
        out = subprocess.run(["git", "ls-files", ".state"], cwd=ROOT,
                             capture_output=True, text=True, encoding="utf-8", timeout=30)
    except Exception:  # noqa: BLE001
        pytest.skip("没有 git")
    assert out.stdout.strip() == "", f".state 被跟踪了：{out.stdout[:200]}"


@pytest.mark.parametrize("line,should_hit", [
    # 样本用拼接构造，避免这个测试文件自己被扫描器命中
    ("ARK_API_KEY=" + "-".join(["ark", "81c80c23", "60ea", "468c"]), True),
    ('ARK_API_KEY="' + "-".join(["ark", "81c80c23", "60ea", "468c"]) + '"', True),
    ("ARK_API_KEY=<your-key-here>", False),
    ("ARK_API_KEY=", False),
    ("TIANYANCHA_TOKEN=...", False),
    ("TIANYANCHA_TOKEN=<在 .env 里填>", False),
    ("# 编辑 .env，填 TIANYANCHA_TOKEN=...", False),
    ("PGPASSWORD=" + "post" + "gres", True),
    ("PGPASSWORD=" + "os.environ['PGPASSWORD']", False),
    ("TIANYANCHA_TOKEN=" + "a" * 24, True),
])
def test_scanner_recognises_shapes(line, should_hit, tmp_path):
    sample = tmp_path / "sample.txt"
    sample.write_text(line + "\n", encoding="utf-8")
    hits = check_secrets.scan([sample])
    assert bool(hits) is should_hit, f"{line!r} 判定错误：{hits}"
