"""离线测试：页面被销毁 / 风控 code 37 / 登录失效 三条恢复路径。

用假 browser/page 驱动 JobCrawler._fetch_json，不触网。
"""
import unittest

from boss_crawler import config
from boss_crawler.crawl import JobCrawler
from boss_crawler.crawl import LoginRequired


class FakePage:
    def __init__(self, scripted):
        self.scripted = scripted  # list of responses or exceptions
        self.url = "https://www.zhipin.com/web/geek/job"
        self.calls = 0

    def is_closed(self):
        return False

    def evaluate(self, js, arg=None):
        item = self.scripted[min(self.calls, len(self.scripted) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return item


class FakeBrowser:
    def __init__(self, page):
        self._page = page
        self.gotos = 0

    def page(self, goto=None):
        return self._page

    def goto(self, page, url, retries=2):
        self.gotos += 1
        return True

    def ensure_armed(self, page):
        return True


def make_crawler(scripted):
    page = FakePage(scripted)
    browser = FakeBrowser(page)
    crawler = JobCrawler(browser, query="Python", city="成都", pages=1)
    return crawler, page, browser


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        # 测试里不要真的等待
        import boss_crawler.crawl.job_crawler as crawler_module
        self._orig_sleep = crawler_module.human_sleep
        self._orig_time_sleep = crawler_module.time.sleep
        crawler_module.human_sleep = lambda bounds: None
        crawler_module.time.sleep = lambda seconds: None

    def tearDown(self):
        import boss_crawler.crawl.job_crawler as crawler_module
        crawler_module.human_sleep = self._orig_sleep
        crawler_module.time.sleep = self._orig_time_sleep

    def test_retry_after_page_destroyed(self):
        crawler, page, _ = make_crawler([
            Exception("Execution context was destroyed, most likely because of a navigation"),
            {"status": 200, "json": {"code": 0, "zpData": {"jobList": []}}},
        ])
        payload = crawler._fetch_json(page, "https://x/api", purpose="列表")
        self.assertEqual(payload["code"], 0)
        self.assertEqual(page.calls, 2)

    def test_retry_after_risk_code_37(self):
        crawler, page, browser = make_crawler([
            {"status": 200, "json": {"code": 37, "message": "您的环境存在异常."}},
            {"status": 200, "json": {"code": 0, "zpData": {"totalCount": 1}}},
        ])
        payload = crawler._fetch_json(page, "https://x/api", purpose="列表")
        self.assertEqual(payload["code"], 0)
        # 触发反风控时要重新预热页面
        self.assertGreaterEqual(browser.gotos, 1)

    def test_login_expired_raises(self):
        crawler, page, _ = make_crawler([
            {"status": 200, "json": {"code": 7, "message": "当前登录状态已失效"}},
        ])
        with self.assertRaises(LoginRequired):
            crawler._fetch_json(page, "https://x/api", purpose="列表")

    def test_non_json_response_returns_empty(self):
        crawler, page, _ = make_crawler([
            {"status": 200, "json": None, "text": "<html>verify</html>"},
        ])
        self.assertEqual(crawler._fetch_json(page, "https://x/api", purpose="列表"), {})

    def test_risk_retry_budget_is_finite(self):
        crawler, page, _ = make_crawler([
            {"status": 200, "json": {"code": 37, "message": "您的环境存在异常."}},
        ])
        with self.assertRaises(RuntimeError):
            crawler._fetch_json(page, "https://x/api", purpose="列表")
        self.assertEqual(page.calls, config.MAX_RISK_RETRIES + 1)


if __name__ == "__main__":
    unittest.main()
