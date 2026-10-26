"""运行期配置与路径。

敏感凭据（天眼查 token、数据库密码、Ark 密钥）一律从环境变量或 ``.env`` 读取，
不写进代码、不进版本库。
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path | None = None) -> None:
    """把 ``.env`` 读进 ``os.environ``（不覆盖已存在的变量）。

    自己实现而不引入 python-dotenv：格式简单（``KEY=VALUE``、``#`` 注释、
    可选的单/双引号），少一个依赖就少一处安装失败。
    """
    env_file = path or (ROOT / ".env")
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env()

# 运行期状态（登录态、Cookie 快照）— 含敏感信息，不要提交到版本库
# 打包成桌面端后由 Electron 指向用户数据目录，避免写只读的 resources。
STATE_DIR = Path(os.environ.get("BOSS_STATE_DIR") or (ROOT / ".state"))
STATE_DIR.mkdir(parents=True, exist_ok=True)
PROFILE_DIR = STATE_DIR / "chrome-profile"
STORAGE_STATE = STATE_DIR / "storage_state.json"

def _resolve_config_dir() -> Path:
    """仓库开发时用 ``config/``；wheel 安装后把包内默认配置复制到可写目录。

    site-packages 通常不可写，所以不能直接读写包内 ``defaults/``。
    """
    repo_config = ROOT / "config"
    if repo_config.is_dir():
        return repo_config
    target = STATE_DIR / "config"
    source = Path(__file__).with_name("defaults")
    if source.is_dir() and not target.exists():
        import shutil

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
    target.mkdir(parents=True, exist_ok=True)
    return target


# 声明式配置目录；打包后复制到用户目录，允许设置页写回。
CONFIG_DIR = Path(os.environ.get("BOSS_CONFIG_DIR") or _resolve_config_dir())

OUTPUT_DIR = ROOT / "output"
STEALTH_JS = Path(__file__).with_name("stealth.js")

HOME_URL = "https://www.zhipin.com/"
LOGIN_URL = "https://www.zhipin.com/web/user/?ka=header-login"
SEARCH_PAGE_URL = "https://www.zhipin.com/web/geek/job?query={query}&city={city}"
JOB_LIST_API = (
    "https://www.zhipin.com/wapi/zpgeek/search/joblist.json"
    "?scene=1&query={query}&city={city}&page={page}&pageSize={page_size}"
)
JOB_DETAIL_API = "https://www.zhipin.com/wapi/zpgeek/job/detail.json?securityId={security_id}&lid={lid}"
ACCOUNT_API = "https://www.zhipin.com/wapi/zpuser/h5/account/getStatus"

# 城市编码（BOSS直聘 city code），按需自行补充
CITY_CODES = {
    "全国": "100010000",
    "北京": "101010100",
    "上海": "101020100",
    "广州": "101280100",
    "深圳": "101280600",
    "成都": "101270100",
    "杭州": "101210100",
    "武汉": "101200100",
    "西安": "101110100",
    "南京": "101190100",
    "重庆": "101040100",
    "苏州": "101190400",
    "长沙": "101250100",
    "郑州": "101180100",
    "天津": "101030100",
    "合肥": "101220100",
    "厦门": "101230200",
    "青岛": "101120200",
    "东莞": "101281600",
    "佛山": "101280800",
}

# 默认节奏：单页之间 4~9 秒，详情之间 2~5 秒。刻意保持低频。
PAGE_DELAY = (4.0, 9.0)
DETAIL_DELAY = (2.0, 5.0)
RISK_BACKOFF = (8.0, 20.0)

DEFAULT_PAGE_SIZE = 30
MAX_RISK_RETRIES = 3

# 职位筛选：界面上的固定档位，值是对应接口参数的数字码。
# 取值来自真实筛选器（ka="sel-job-rec-salary-406" 这类属性）。
SALARY_CODES = {
    "3K以下": "402",
    "3-5K": "403",
    "5-10K": "404",
    "10-20K": "405",
    "20-50K": "406",
    "50K以上": "407",
}

EXPERIENCE_CODES = {
    "在校生": "108",
    "应届生": "102",
    "经验不限": "101",
    "1年以内": "103",
    "1-3年": "104",
    "3-5年": "105",
    "5-10年": "106",
    "10年以上": "107",
}

DEGREE_CODES = {
    "初中及以下": "209",
    "中专/中技": "208",
    "高中": "206",
    "大专": "202",
    "本科": "203",
    "硕士": "204",
    "博士": "205",
}

# ----------------------------------------------------------------- 向量化（火山方舟）
# 注意：本账号的可用端点是 /api/plan/v3（官方 /api/v3 返回 401），密钥放在
# .state/ark_key.txt 或环境变量 ARK_API_KEY，不要写进代码。
ARK_BASE_URL = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/plan/v3")
ARK_MODEL = os.environ.get("ARK_MODEL", "doubao-embedding-vision-250328")
ARK_KEY_FILE = STATE_DIR / "ark_key.txt"
ARK_BATCH_SIZE = int(os.environ.get("ARK_BATCH_SIZE", "10"))
EMBED_MAX_CHARS = int(os.environ.get("EMBED_MAX_CHARS", "1500"))

# ----------------------------------------------------------------- DeepSeek（OpenAI 兼容）
# 密钥放在 .state/deepseek_key.txt 或环境变量 DEEPSEEK_API_KEY，不要写进代码。
# Anthropic 兼容端点 https://api.deepseek.com/anthropic 当前未被使用；
# 项目里的模型客户端统一走 OpenAI 风格的 /chat/completions。
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_KEY_FILE = STATE_DIR / "deepseek_key.txt"

# ----------------------------------------------------------------- PostgreSQL
PG_HOST = os.environ.get("PGHOST", "127.0.0.1")
PG_PORT = int(os.environ.get("PGPORT", "5432"))
PG_USER = os.environ.get("PGUSER", "postgres")
PG_DATABASE = os.environ.get("PGDATABASE", "boss_jobs")
PG_PASSWORD_FILE = STATE_DIR / "pg_password.txt"

# ----------------------------------------------------------------- 天眼查开放平台
# token 走 .env 的 TIANYANCHA_TOKEN，或 .state/tyc_token.txt（两者取先存在的）。
# 单次价格见 TYC_PRICES，用于成本预估（单位：元/次，来自页面标价）。
TYC_BASE_URL = os.environ.get("TIANYANCHA_BASE_URL", "https://open.api.tianyancha.com")
TYC_TOKEN = os.environ.get("TIANYANCHA_TOKEN", "")
TYC_TOKEN_FILE = STATE_DIR / "tyc_token.txt"
TYC_TIMEOUT = float(os.environ.get("TIANYANCHA_TIMEOUT", "20"))
TYC_QPS_DELAY = float(os.environ.get("TIANYANCHA_QPS_DELAY", "0.35"))
TYC_MAX_RETRIES = int(os.environ.get("TIANYANCHA_MAX_RETRIES", "3"))

# 接口路径（来自开放平台接口目录）
TYC_API = {
    "search": "/services/open/search/2.0",                 # 816  ¥0.01 关键词->企业
    "ic": "/services/open/cb/ic/2.0",                      # 1001 ¥1.00 工商全景（含母子/风险清单）
    "invest": "/services/open/ic/inverst/2.0",             # 823  ¥0.15 对外投资（分页全量）
    "parent": "/services/open/ic/parentCompany/2.0",       # 963  ¥0.15 总公司
    "dishonest": "/services/open/jr/dishonest/2.0",        # 843  ¥0.15 失信人
    "zhixing": "/services/open/jr/zhixinginfo/2.0",        # 839  ¥0.15 被执行人
    "abnormal": "/services/open/mr/abnormal/2.0",          # 848  ¥0.15 经营异常
    "illegal": "/services/open/mr/illegalinfo/2.0",        # 846  ¥0.15 严重违法
    "punish": "/services/open/mr/punishmentInfo/3.0",      # 1124 ¥0.15 行政处罚
}

TYC_PRICES = {
    "search": 0.01, "ic": 1.00, "invest": 0.15, "parent": 0.15,
    "dishonest": 0.15, "zhixing": 0.15, "abnormal": 0.15,
    "illegal": 0.15, "punish": 0.15,
}
