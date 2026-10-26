"""把 pytest 失败用例转成 GitHub Actions 注解。

公开仓库的 Actions 日志也要登录才能看，注解匿名可见；输出前先给密钥打码。
"""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_MASKS = (
    re.compile(r"(gh[pousr]_)[A-Za-z0-9]{20,}"),
    re.compile(r"(sk-)[A-Za-z0-9_-]{20,}"),
    re.compile(r"(ark-)[0-9a-f-]{8,}"),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._-]{20,}"),
    re.compile(r"((?:postgres|mysql)://[^:\s]+:)[^@\s]+@"),
    re.compile(r"((?:PGPASSWORD|ARK_API_KEY|ARK_IMAGE_KEY|TIANYANCHA_TOKEN|"
               r"TIANYANCHA_API_KEY|DEEPSEEK_API_KEY)\s*=\s*)\S+"),
)


def mask(text: str) -> str:
    for pattern in _MASKS:
        text = pattern.sub(r"\1***", text)
    return text


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def failure_annotations(xml_path: Path) -> list[str]:
    if not xml_path.is_file():
        return []
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError:
        return []
    lines: list[str] = []
    for case in root.iter("testcase"):
        node = case.find("failure")
        if node is None:
            node = case.find("error")
        if node is None:
            continue
        name = f"{case.get('classname', '')}::{case.get('name', '')}".strip(":")
        message = (node.get("message") or node.text or "failed").strip().splitlines()
        detail = mask(message[0][:300] if message else "failed")
        props = [f"title={name}"]
        if case.get("file"):
            props.insert(0, f"file={case.get('file')}")
        if case.get("line"):
            props.insert(1, f"line={case.get('line')}")
        lines.append(f"::error {','.join(props)}::{_escape(detail)}")
    return lines


def main(argv: list[str]) -> int:
    xml_path = Path(argv[1]) if len(argv) > 1 else Path("pytest.xml")
    log_path = Path(argv[2]) if len(argv) > 2 else Path("pytest.log")
    lines = failure_annotations(xml_path)
    if not lines:
        tail = ""
        if log_path.is_file():
            tail = "\n".join(log_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-12:])
        lines = [f"::error::pytest failed without a test case. Tail: {_escape(mask(tail)[-900:])}"]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
