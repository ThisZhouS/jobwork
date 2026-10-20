"""命令行入口。

* :mod:`boss_crawler.cli.parser` —— 参数解析（含共享参数组）；
* :mod:`boss_crawler.cli.commands` —— 每个子命令一个 ``cmd_*``，只做编排。

新增子命令只需三步：在 ``commands.py`` 写 ``cmd_xxx``、在 ``parser.py`` 注册、
什么也不用改 ``main``（``set_defaults(func=...)`` 自动派发）。
"""

from __future__ import annotations

import sys

from .. import config
from ..crawl import BrowserUnavailable, LoginRequired
from .parser import build_parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BrowserUnavailable as exc:
        print(f"浏览器不可用：{exc}")
        return 4
    except LoginRequired as exc:
        print(f"需要登录：{exc}\n请运行：python -m boss_crawler login")
        return 3
    except ValueError as exc:
        print(f"参数错误：{exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
