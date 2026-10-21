"""巨潮资讯（cninfo）工具测试：分类、日期、翻页、降级。

全部离线：用假 http 对象喂固定 JSON，不碰网络。
"""
from __future__ import annotations

import pytest

from boss_crawler.agents.base import AgentContext, AgentStatus
from boss_crawler.agents.tools.base import _TOOLS, ToolBox
from boss_crawler.agents.tools.sites.cninfo import classify_risk, is_risk, to_date


class FakeHttp:
    """按页返回预置数据；记录调用次数，用来验翻页。"""

    def __init__(self, pages: list[dict] | None = None, error: Exception | None = None):
        self.pages = pages or []
        self.error = error
        self.calls = 0
        self.payloads: list[dict] = []

    async def post_json(self, url, *, data=None, headers=None):
        self.calls += 1
        self.payloads.append(dict(data or {}))
        if self.error is not None:
            raise self.error
        index = min(self.calls - 1, len(self.pages) - 1) if self.pages else 0
        return self.pages[index] if self.pages else {"announcements": []}


def item(title, *, code="600518", name="康美药业", ts=1729440000000, path="finalpage/x.pdf"):
    return {
        "announcementTitle": title,
        "announcementTime": ts,
        "secCode": code,
        "secName": name,
        "adjunctUrl": path,
    }


async def call(tool_http, **kwargs):
    ctx = AgentContext(http=tool_http)
    box = ToolBox(ctx, delay=0, retries=0, allow_browser=False)
    return await _TOOLS["cninfo_notices"].call(box, **kwargs)


# ---------------------------------------------------------------- 分类
@pytest.mark.parametrize("title,expected", [
    ("关于收到证监会立案告知书的公告", "立案调查"),
    ("关于收到行政处罚决定书的公告", "立案调查"),
    ("关于涉及诉讼进展的公告", "重大诉讼"),
    ("关于公司被列为失信被执行人的公告", "失信被执行"),
    ("关于控股股东股份被司法冻结的公告", "股权风险"),
    ("关于公司股票可能被终止上市的风险提示公告", "业绩预警"),
    ("关于收到深交所问询函的公告", "监管问询"),
    ("关于董事长辞职的公告", "高管变动"),
    ("2024年年度权益分派实施公告", "其他公告"),
    ("关于召开2024年第一次临时股东大会的通知", "其他公告"),
])
def test_classify_risk(title, expected):
    assert classify_risk(title) == expected


def test_is_risk_only_for_keyword_hits():
    assert is_risk("关于涉及诉讼进展的公告") is True
    assert is_risk("2024年年度权益分派实施公告") is False


def test_risk_keywords_order_matters():
    # 「立案」优先于「诉讼」，同一条标题只归一类
    assert classify_risk("关于立案调查及诉讼进展的公告") == "立案调查"


# ---------------------------------------------------------------- 日期
def test_to_date_from_millisecond_timestamp():
    assert to_date(1729440000000) == "2024-10-21"
    assert to_date("1729440000000") == "2024-10-21"


def test_to_date_from_text_and_none():
    assert to_date("2024-10-20") == "2024-10-20"
    assert to_date(None) is None
    assert to_date("") is None
    assert to_date("不是日期") is None


# ---------------------------------------------------------------- 正常解析
async def test_parses_rows_and_strips_highlight_tags():
    http = FakeHttp([{"announcements": [
        item("<em>康美药业</em>关于涉及诉讼进展的公告"),
        item("2024年年度权益分派实施公告"),
    ]}])
    result = await call(http, company="康美药业", limit=10)

    assert result.status is AgentStatus.OK
    rows = result.data
    assert len(rows) == 2
    assert rows[0]["title"] == "康美药业 关于涉及诉讼进展的公告"
    assert rows[0]["risk_type"] == "重大诉讼"
    assert rows[0]["is_risk"] is True
    assert rows[0]["date"] == "2024-10-21"
    assert rows[0]["url"].startswith("http://static.cninfo.com.cn/")
    assert result.meta["risky"] == 1


async def test_no_risk_rows_is_partial_not_safe():
    """全是常规公告时状态是 PARTIAL，且明确说明"不等于无风险"。"""
    http = FakeHttp([{"announcements": [item("2024年年度权益分派实施公告")]}])
    result = await call(http, company="比亚迪", limit=10)
    assert result.status is AgentStatus.PARTIAL
    assert any("不等于无风险" in note for note in result.notes)


async def test_empty_announcements_returns_empty_with_reason():
    http = FakeHttp([{"announcements": []}])
    result = await call(http, company="某非上市公司", limit=10)
    assert result.status is AgentStatus.EMPTY
    assert any("非上市" in note for note in result.notes)


async def test_missing_company_name_fails():
    result = await call(FakeHttp([]), company="")
    assert result.status is AgentStatus.FAILED


# ---------------------------------------------------------------- 翻页与降级
async def test_pages_until_limit_collected():
    page = {"announcements": [item(f"公告{i}") for i in range(30)]}
    http = FakeHttp([page, page])
    result = await call(http, company="比亚迪", limit=50)
    assert http.calls == 2
    assert len(result.data) == 50
    assert http.payloads[0]["pageNum"] == "1"
    assert http.payloads[1]["pageNum"] == "2"


async def test_stops_when_page_not_full():
    http = FakeHttp([{"announcements": [item(f"公告{i}") for i in range(5)]}])
    result = await call(http, company="比亚迪", limit=50)
    assert http.calls == 1
    assert len(result.data) == 5


async def test_network_error_returns_failed():
    http = FakeHttp(error=RuntimeError("连接超时"))
    result = await call(http, company="比亚迪", limit=10)
    assert result.status is AgentStatus.FAILED
    assert "连接超时" in (result.error or "")


async def test_non_dict_response_returns_failed():
    class Weird(FakeHttp):
        async def post_json(self, url, *, data=None, headers=None):
            return ["不是对象"]

    result = await call(Weird([]), company="比亚迪", limit=10)
    assert result.status is AgentStatus.FAILED
