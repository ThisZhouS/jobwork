"""采集层：浏览器会话 + 接口解析 + 抓取编排。

* :mod:`boss_crawler.crawl.browser` —— 持久化登录态、反检测注入、页面生命周期与风控退避；
* :mod:`boss_crawler.crawl.parser` —— 列表/详情接口响应解析（纯函数）；
* :mod:`boss_crawler.crawl.job_crawler` —— 搜索、翻页、补详情、去重入库。
"""
from .browser import BossBrowser, BrowserUnavailable, LoginRequired, PageDestroyed, human_sleep
from .job_crawler import JobCrawler

__all__ = [
    "BossBrowser",
    "BrowserUnavailable",
    "JobCrawler",
    "LoginRequired",
    "PageDestroyed",
    "human_sleep",
]
