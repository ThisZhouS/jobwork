import unittest

from boss_crawler.crawl.parser import (
    deep_find,
    normalize_job,
    parse_detail,
    parse_joblist,
    parse_joblist_dom,
    parse_salary,
)

RAW_JOB = {
    "encryptJobId": "ff80b37c2dda59620nNy3d-5F1pZ",
    "securityId": "xmyA60PMFs9aG-t1gVY3Bbto9YIRoiM9",
    "lid": "2hvjTqBFRsu.search.1",
    "jobName": "Python公开课讲师",
    "salaryDesc": "20-30K",
    "cityName": "成都",
    "areaDistrict": "锦江区",
    "businessDistrict": "天府广场",
    "jobExperience": "1-3年",
    "jobDegree": "大专",
    "jobLabels": ["1-3年", "大专"],
    "skills": ["可兼职"],
    "welfareList": ["五险一金"],
    "brandName": "衔芦文化",
    "brandIndustry": "职业培训",
    "brandStageName": "不需要融资",
    "brandScaleName": "100-499人",
    "bossName": "赵女士",
    "bossTitle": "人事招聘",
    "bossOnline": True,
}

DETAIL_PAYLOAD = {
    "code": 0,
    "zpData": {
        "jobInfo": {
            "postDescription": "负责 Python 公开课授课。",
            "address": "成都锦江区航天科技大厦32楼",
            "showSkills": ["Python", "授课"],
            "jobStatusDesc": "最新",
        },
        "bossInfo": {
            "name": "赵女士",
            "title": "人事招聘",
            "activeTimeDesc": "刚刚活跃",
            "bossOnline": True,
        },
        "brandComInfo": {
            "introduce": "在线课堂前身成立于2009年。",
            "scaleName": "100-499人",
            "industryName": "职业培训",
            "stageName": "不需要融资",
            "labels": ["A轮"],
        },
    },
}

DOM_HTML = """
<div class="job-card-box">
  <a href="/job_detail/abc123.html">
    <span class="job-name">Python开发</span>
    <span class="job-salary">15-25K</span>
    <span class="company-name">示例科技</span>
    <span class="job-area">成都·武侯区</span>
    <ul class="tag-list"><li>3-5年</li><li>本科</li></ul>
  </a>
</div>
"""


class SalaryTests(unittest.TestCase):
    def test_range(self):
        self.assertEqual(parse_salary("20-30K"), (20000, 30000))

    def test_month_count_suffix_ignored(self):
        self.assertEqual(parse_salary("15-30K·14薪"), (15000, 30000))

    def test_daily_rate(self):
        self.assertEqual(parse_salary("100-200元/天"), (100, 200))

    def test_single_value(self):
        self.assertEqual(parse_salary("8K"), (8000, 8000))

    def test_empty(self):
        self.assertEqual(parse_salary(None), (None, None))


class JobListTests(unittest.TestCase):
    def test_normalize_job(self):
        job = normalize_job(RAW_JOB)
        self.assertEqual(job["title"], "Python公开课讲师")
        self.assertEqual((job["salary_min"], job["salary_max"]), (20000, 30000))
        self.assertEqual(job["company"], "衔芦文化")
        self.assertTrue(job["url"].endswith("ff80b37c2dda59620nNy3d-5F1pZ.html"))

    def test_parse_joblist_meta(self):
        payload = {
            "code": 0,
            "zpData": {"jobList": [RAW_JOB], "totalCount": 300, "hasMore": True, "lid": "x"},
        }
        jobs, meta = parse_joblist(payload)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(meta["total"], 300)
        self.assertTrue(meta["has_more"])

    def test_parse_joblist_empty(self):
        jobs, meta = parse_joblist({"code": 37, "message": "您的环境存在异常."})
        self.assertEqual(jobs, [])
        self.assertIsNone(meta["total"])


class DetailTests(unittest.TestCase):
    def test_detail_fields(self):
        detail = parse_detail(DETAIL_PAYLOAD)
        self.assertEqual(detail["description"], "负责 Python 公开课授课。")
        self.assertEqual(detail["address"], "成都锦江区航天科技大厦32楼")
        self.assertEqual(detail["company_intro"], "在线课堂前身成立于2009年。")
        self.assertEqual(detail["company_industry"], "职业培训")

    def test_deep_find(self):
        self.assertEqual(deep_find({"a": [{"b": {"postDescription": "hi"}}]}, ("postDescription",)), "hi")
        self.assertEqual(deep_find({}, ("x",)), "")


class DomFallbackTests(unittest.TestCase):
    def test_parse_dom(self):
        jobs = parse_joblist_dom(DOM_HTML)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["job_id"], "abc123")
        self.assertEqual(jobs[0]["title"], "Python开发")
        self.assertEqual(jobs[0]["tags"], ["3-5年", "本科"])
        self.assertEqual(jobs[0]["source"], "dom")


if __name__ == "__main__":
    unittest.main()
