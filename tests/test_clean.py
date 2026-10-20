import unittest

from boss_crawler.structuring import (
    build_companies,
    build_report,
    clean_company,
    clean_record,
    extract_legal_name,
    normalize_text,
    parse_address,
    salary_unit,
)


class NormalizeTests(unittest.TestCase):
    def test_fullwidth_and_spaces(self):
        self.assertEqual(normalize_text("　成都　某  公司　"), "成都 某 公司")

    def test_edge_punctuation(self):
        self.assertEqual(normalize_text("，成都锦江区，"), "成都锦江区")

    def test_none(self):
        self.assertEqual(normalize_text(None), "")


class CompanyTests(unittest.TestCase):
    def test_truncated_name(self):
        info = clean_company("成都悠鑫龙商务信...")
        self.assertTrue(info["is_truncated"])
        self.assertEqual(info["name"], "成都悠鑫龙商务信")
        self.assertEqual(info["raw"], "成都悠鑫龙商务信...")

    def test_anonymous_name(self):
        for name in ("某大型互联网公司", "郑州某大型高校信息化服务上市公司", "某知名智能硬件公司"):
            info = clean_company(name)
            self.assertTrue(info["is_anonymous"], name)

    def test_normal_name(self):
        info = clean_company("凌策科技")
        self.assertFalse(info["is_anonymous"])
        self.assertFalse(info["is_truncated"])
        self.assertEqual(info["key"], "凌策科技")

    def test_legal_name_from_intro(self):
        intro = "华为技术有限公司成立于1987年，总部位于中国深圳。"
        self.assertEqual(extract_legal_name(intro, "某大型互联网公司"), "华为技术有限公司")

    def test_legal_name_fallback(self):
        self.assertEqual(extract_legal_name("在线课堂前身成立于2009年。", "衔芦文化"), "衔芦文化")


class AddressTests(unittest.TestCase):
    def test_detail_address(self):
        out = parse_address("成都锦江区航天科技大厦32楼", city="成都")
        self.assertEqual(out["city"], "成都")
        self.assertEqual(out["district"], "锦江区")
        self.assertEqual(out["detail"], "航天科技大厦32楼")
        self.assertEqual(out["source"], "detail")

    def test_detail_address_without_city_prefix(self):
        out = parse_address("西安雁塔区飞阳广场221", city="西安")
        self.assertEqual(out["district"], "雁塔区")
        self.assertEqual(out["detail"], "飞阳广场221")

    def test_same_company_district_kept_in_detail(self):
        out = parse_address("郑州中原区新开普大厦高新区新开普大厦", city="郑州")
        self.assertEqual(out["district"], "中原区")
        # 站点把商圈与详细地址拼在一起造成重复，折叠后只留一份
        self.assertEqual(out["detail"], "高新区新开普大厦")
        self.assertEqual(out["full"], "郑州中原区新开普大厦高新区新开普大厦")

    def test_repeated_prefix_collapsed(self):
        out = parse_address("成都武侯区天合凯旋广场成都武侯区天合凯旋广场1栋6层", city="成都")
        self.assertEqual(out["full"], "成都武侯区天合凯旋广场1栋6层")

    def test_real_name_with_repeated_char_kept(self):
        # "成都成都银行大厦" 属于真名，不能折叠成 "成都"
        out = parse_address("成都成都银行大厦", city="成都")
        self.assertIn("银行大厦", out["full"])

    def test_city_only_address_degrades_to_derived(self):
        out = parse_address("成都", city="成都", district="金牛区")
        self.assertEqual(out["source"], "list")
        self.assertEqual(out["full"], "成都金牛区")
        self.assertEqual(out["detail"], "")

    def test_derived_from_list_fields(self):
        out = parse_address(None, city="成都", district="武侯区", business_district="中和")
        self.assertEqual(out["full"], "成都武侯区中和")
        self.assertEqual(out["source"], "list")

    def test_no_address(self):
        out = parse_address(None, city="成都")
        self.assertEqual(out["source"], "city-only")
        out = parse_address(None)
        self.assertEqual(out["source"], "none")


class SalaryUnitTests(unittest.TestCase):
    def test_units(self):
        self.assertEqual(salary_unit("20-30K"), "month")
        self.assertEqual(salary_unit("100-200元/天"), "day")
        self.assertEqual(salary_unit("30元/时"), "hour")
        self.assertEqual(salary_unit("面议"), "month")


class RecordTests(unittest.TestCase):
    def test_clean_record_shape(self):
        record = {
            "job_id": "abc",
            "title": " Python开发 ",
            "company": "日新咨询",
            "company_intro": "日新战研(成都)企业管理咨询有限公司成立于2010年。",
            "address": "成都武侯区迈空间国际中心-T3713",
            "city": "成都",
            "salary": "10-15K",
            "salary_min": 10000,
            "salary_max": 15000,
            "industry": "咨询",
        }
        job = clean_record(record)
        self.assertEqual(job["title"], "Python开发")
        self.assertEqual(job["company"]["name"], "日新咨询")
        self.assertEqual(job["company"]["legal_name"], "日新战研(成都)企业管理咨询有限公司")
        self.assertEqual(job["workplace"]["district"], "武侯区")
        self.assertEqual(job["workplace"]["detail"], "迈空间国际中心-T3713")
        self.assertEqual(job["salary_unit"], "month")


class CompanyAggregationTests(unittest.TestCase):
    def _job(self, company, address, title, city="成都", low=10000, high=15000, unit="month"):
        return {
            "title": title,
            "salary_min": low,
            "salary_max": high,
            "salary_unit": unit,
            "company": {"name": company, "legal_name": company, "key": company,
                        "is_anonymous": False, "is_truncated": False,
                        "industry": "计算机软件", "industry_code": 100021, "scale": "", "stage": ""},
            "workplace": parse_address(address, city=city),
        }

    def test_aggregate(self):
        jobs = [
            self._job("凌策科技", "成都锦江区航天科技大厦32楼", "Python讲师"),
            self._job("凌策科技", "成都锦江区航天科技大厦32楼", "Java讲师", low=12000, high=18000),
            self._job("某大型互联网公司", "西安雁塔区飞阳广场221", "后端", city="西安",
                      low=20000, high=40000),
        ]
        companies = {c["company_name"]: c for c in build_companies(jobs)}
        self.assertEqual(companies["凌策科技"]["job_count"], 2)
        self.assertEqual(len(companies["凌策科技"]["addresses"]), 1)
        self.assertEqual((companies["凌策科技"]["salary_min"], companies["凌策科技"]["salary_max"]),
                         (10000, 18000))

    def test_daily_salary_excluded_from_monthly_range(self):
        jobs = [
            self._job("安捷智合", "成都郫都区红光镇", "办公自动化", low=100, high=200, unit="day"),
        ]
        company = build_companies(jobs)[0]
        self.assertIsNone(company["salary_min"])

    def test_report_counts(self):
        jobs = [clean_record({
            "job_id": "1", "title": "a", "company": "某大型互联网公司",
            "address": "西安雁塔区飞阳广场221", "city": "西安",
        })]
        companies = build_companies(jobs)
        report = build_report(jobs, companies)
        self.assertEqual(report["jobs"], 1)
        self.assertEqual(report["address_detail"], 1)
        self.assertEqual(report["anonymous_companies"], 1)


if __name__ == "__main__":
    unittest.main()
