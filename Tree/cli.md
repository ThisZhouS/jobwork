# boss_crawler/cli —— 命令行层

只做「参数 → 调底层 → 打印摘要」。业务逻辑不写在这里，否则测试与复用都得绕命令行。

## 文件

| 文件 | 职责 | 关键符号 |
|---|---|---|
| `__init__.py` | 入口与异常归一 | `main(argv) -> int`（返回退出码：0 成功 / 2 参数错 / 3 需登录 / 4 浏览器不可用） |
| `parser.py` | 参数定义 | `build_parser()` |
| `commands.py` | 子命令实现 | `cmd_login` `cmd_crawl` `cmd_doctor` `cmd_filters` `cmd_process` `cmd_enrich` `cmd_db_init` `cmd_db_load` `cmd_embed` `cmd_search` `cmd_db_stats` |

## 新增子命令

1. `commands.py` 写 `cmd_xxx(args) -> int`；
2. `parser.py` 注册 `sub.add_parser("xxx")` 并 `set_defaults(func=cmd_xxx)`；
3. `main()` 不用改（按 `args.func` 派发）。

## 共享参数组

`parser.py` 内的 `add_input_args()` / `add_db_args()` 收敛了在多个子命令重复出现的
`--input` / 数据库连接参数，改一处即可。
