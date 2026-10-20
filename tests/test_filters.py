import unittest

from boss_crawler.crawl import JobCrawler
from boss_crawler.filters import describe, resolve_code, resolve_filters


class FilterTests(unittest.TestCase):
    def test_salary_label(self):
        self.assertEqual(resolve_code("salary", "20-50K"), "406")

    def test_salary_alias_lowercase(self):
        self.assertEqual(resolve_code("salary", "10-20k"), "405")

    def test_degree_label(self):
        self.assertEqual(resolve_code("degree", "本科"), "203")

    def test_experience_label(self):
        self.assertEqual(resolve_code("experience", "3-5年"), "105")

    def test_industry_label_from_collected_map(self):
        self.assertEqual(resolve_code("industry", "计算机软件"), "100021")
        self.assertEqual(resolve_code("industry", "人工智能"), "100028")

    def test_numeric_code_passthrough(self):
        self.assertEqual(resolve_code("salary", "406"), "406")
        self.assertEqual(resolve_code("industry", "100020"), "100020")

    def test_blank_means_no_filter(self):
        self.assertIsNone(resolve_code("degree", None))
        self.assertIsNone(resolve_code("degree", "不限"))
        self.assertIsNone(resolve_code("degree", "  "))

    def test_unknown_raises_with_options(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_code("degree", "博士后")
        self.assertIn("本科", str(ctx.exception))

    def test_resolve_filters_combination(self):
        filters = resolve_filters(
            salary="20-50K", experience="3-5年", degree="本科", industry="计算机软件"
        )
        self.assertEqual(
            filters,
            {"salary": "406", "experience": "105", "degree": "203", "industry": "100021"},
        )

    def test_resolve_filters_skips_blank(self):
        self.assertEqual(resolve_filters(salary=None, degree="本科"), {"degree": "203"})

    def test_describe(self):
        text = describe({"salary": "406", "industry": "100021"})
        self.assertIn("20-50K", text)
        self.assertIn("计算机软件", text)
        self.assertEqual(describe({}), "无")


class UrlBuildingTests(unittest.TestCase):
    def _crawler(self, **filters):
        # 不启动浏览器：_search_page_url/_list_api_url 是纯字符串拼接
        return JobCrawler(None, query="Python", city="成都", pages=1, **filters)

    def test_urls_include_filters(self):
        crawler = self._crawler(salary="20-50K", degree="本科")
        page_url = crawler._search_page_url()
        api_url = crawler._list_api_url(2)
        self.assertIn("query=Python", page_url)
        self.assertIn("city=101270100", page_url)
        self.assertIn("salary=406", page_url)
        self.assertIn("degree=203", page_url)
        self.assertIn("page=2", api_url)
        self.assertIn("salary=406", api_url)

    def test_urls_without_filters_have_no_trailing_amp(self):
        crawler = self._crawler()
        self.assertFalse(crawler._search_page_url().endswith("&"))
        self.assertFalse(crawler._list_api_url(1).endswith("&"))


if __name__ == "__main__":
    unittest.main()
