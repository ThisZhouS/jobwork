import unittest

from boss_crawler.structuring import (
    extract_benefits,
    extract_degree,
    extract_hiring_count,
    extract_schedule,
    extract_seniority,
    extract_years,
    normalize_skills,
    skill_category,
    split_sections,
    structure_jd,
)

JD_NAMED = """岗位职责
1、负责数据平台的后端开发与维护;
2、参与数据仓库建模与 ETL 流程优化;
任职要求
1、本科及以上学历,3年以上 Python 开发经验;
2、熟悉 MySQL、Redis,了解 Docker;
福利待遇
1、五险一金,年终奖;
2、周末双休,弹性工作;
"""

JD_ORDINAL = (
    "一、岗位职责 1. 数据挖掘:负责线索数据挖掘与特征工程 2. 模型开发:优化机器学习模型 "
    "二、能力要求 1. 熟练掌握Python,熟悉Flask框架 2. 熟悉MySQL与Redis "
    "三、加分项 1. 熟悉Golang者优先 "
    "四、福利待遇 1.五险一金; 2.年终奖 "
    "五、工作时间 9:00~18:00,弹性打卡,双休"
)

JD_PREAMBLE_FIRST = (
    "1、负责成人群体的Python公开课授课,完成线上公开课讲解、互动答疑; "
    "2、打磨公开课内容与授课逻辑; "
    "3、收集学员反馈,优化课件与授课形式。 "
    "【任职要求 1、有教学 / 分享 / 公开课经验优先; 2、逻辑清晰、表达流畅"
)


class SectionTests(unittest.TestCase):
    def test_named_headers_split(self):
        _pre, sections = split_sections(JD_NAMED)
        self.assertEqual(len(sections["responsibilities"]), 2)
        self.assertEqual(len(sections["requirements"]), 2)
        self.assertIn("五险一金", sections["benefits"][0])
        self.assertIn("负责数据平台", sections["responsibilities"][0])

    def test_ordinal_headers_split(self):
        _pre, sections = split_sections(JD_ORDINAL)
        self.assertEqual(len(sections["responsibilities"]), 2)
        self.assertEqual(len(sections["requirements"]), 2)
        self.assertEqual(len(sections["bonus"]), 1)
        self.assertIn("双休", sections["schedule"][0])

    def test_space_separated_numbering_is_split(self):
        text = "1. 负责后端接口开发 2. 承担数据库方案设计 3. 参与智能化模块研发"
        _pre, sections = split_sections("岗位职责 " + text)
        self.assertEqual(len(sections["responsibilities"]), 3)
        self.assertTrue(sections["responsibilities"][1].startswith("承担"))

    def test_preamble_becomes_duties_when_header_follows(self):
        jd = structure_jd(JD_PREAMBLE_FIRST, title="Python公开课讲师")
        self.assertEqual(len(jd["responsibilities"]), 3)
        self.assertTrue(jd["responsibilities"][0].startswith("负责成人群体的"))
        self.assertEqual(len(jd["requirements"]), 2)

    def test_unstructured_blob_still_split(self):
        jd = structure_jd("负责后端开发;参与需求评审;维护线上服务", title="后端")
        self.assertEqual(len(jd["responsibilities"]), 3)

    def test_empty_description(self):
        jd = structure_jd("", title="Python")
        self.assertFalse(jd["has_jd"])
        self.assertEqual(jd["jd_length"], 0)
        self.assertEqual(jd["responsibilities"], [])
        self.assertIsNone(jd["min_years"])


class ExtractionTests(unittest.TestCase):
    def test_years_range(self):
        self.assertEqual(extract_years("3-5年经验")[:2], (3, 5))

    def test_years_minimum(self):
        self.assertEqual(extract_years("要求5年以上工作经验")[:2], (5, None))

    def test_years_unlimited(self):
        self.assertEqual(extract_years("经验不限,欢迎应届")[:2], (0, None))

    def test_years_absent_is_none(self):
        self.assertEqual(extract_years("负责数据开发")[:2], (None, None))

    def test_degree(self):
        self.assertEqual(extract_degree("本科及以上学历"), "本科")
        self.assertEqual(extract_degree("大专以上"), "大专")
        self.assertEqual(extract_degree("硕士学历优先"), "硕士")
        self.assertEqual(extract_degree("负责开发"), "")

    def test_hiring_count(self):
        self.assertEqual(extract_hiring_count("招3人"), 3)
        self.assertIsNone(extract_hiring_count("大量招聘"))

    def test_schedule(self):
        self.assertEqual(extract_schedule("周末双休"), "双休")
        self.assertEqual(extract_schedule("大小周轮换"), "大小周")
        self.assertEqual(extract_schedule("弹性工作制"), "弹性工作")
        self.assertEqual(extract_schedule("正常上班"), "")

    def test_benefits_merge_welfare(self):
        got = extract_benefits("五险一金、年终奖", ["周末双休"])
        self.assertIn("五险一金", got)
        self.assertIn("年终奖", got)
        self.assertIn("双休", got)

    def test_seniority_from_title(self):
        self.assertEqual(extract_seniority("高级Python工程师"), "资深/高级")
        self.assertEqual(extract_seniority("数据分析实习生"), "实习")
        self.assertEqual(extract_seniority("Python开发"), "")


class SkillTests(unittest.TestCase):
    def test_dictionary_hits_in_text(self):
        jd = structure_jd("岗位职责 1、用 Python 做数据清洗,熟悉 MySQL 与 Redis", title="数据")
        for expected in ("Python", "MySQL", "Redis", "数据清洗"):
            self.assertIn(expected, jd["skills"])

    def test_latin_boundary(self):
        # Go 不应该在 Django 里被误命中
        jd = structure_jd("熟悉 Django 框架", title="后端")
        self.assertNotIn("Go", jd["skills"])
        self.assertIn("Django", jd["skills"])

    def test_normalize_drops_descriptive_junk(self):
        got = normalize_skills([
            "Linux开发/部署经验", "Spark原理/源码", "经济/工商管理相关专业", "互联网/科技",
        ])
        self.assertIn("Linux", got)
        self.assertIn("Spark", got)
        self.assertNotIn("经济", got)
        self.assertNotIn("互联网", got)

    def test_normalize_splits_compound(self):
        got = normalize_skills(["langChain、langGraph", "CI/CD"])
        self.assertIn("langChain", got)
        self.assertIn("langGraph", got)
        self.assertIn("CI/CD", got)

    def test_skill_category(self):
        self.assertEqual(skill_category("Python"), "后端")
        self.assertEqual(skill_category("NLP"), "算法/AI")
        self.assertEqual(skill_category("Vue"), "前端")
        self.assertEqual(skill_category("不存在的技能"), "其他")


if __name__ == "__main__":
    unittest.main()
