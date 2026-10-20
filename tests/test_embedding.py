import os
import unittest
from unittest import mock

from boss_crawler import config
from boss_crawler.embedding import (
    ArkEmbedder,
    EmbeddingError,
    company_embedding_text,
    content_hash,
    job_embedding_text,
    load_api_key,
)


def sample_job():
    return {
        "job_id": "j1",
        "title": "Python 数据分析工程师",
        "salary": "20-30K",
        "experience": "3-5年",
        "degree": "本科",
        "skills": ["Python", "SQL"],
        "welfare": ["五险一金"],
        "description": "负责数据平台建设。" * 50,
        "company": {"name": "凌策科技", "industry": "计算机软件"},
        "workplace": {"city": "成都", "district": "锦江区",
                      "business_district": "天府广场",
                      "full": "成都锦江区航天科技大厦32楼"},
    }


def sample_company():
    return {
        "company_name": "凌策科技",
        "legal_name": "凌策科技有限公司",
        "industry": "计算机软件",
        "scale": "100-499人",
        "stage": "B轮",
        "cities": ["成都"],
        "addresses": ["成都锦江区航天科技大厦32楼"],
        "intro": "专注企业数字化。" * 50,
    }


class TextBuilderTests(unittest.TestCase):
    def test_job_text_contains_key_metadata(self):
        text = job_embedding_text(sample_job())
        for expected in ("Python 数据分析工程师", "凌策科技", "计算机软件", "成都锦江区",
                         "20-30K", "3-5年", "本科", "Python、SQL", "五险一金"):
            self.assertIn(expected, text)

    def test_job_text_is_clipped(self):
        text = job_embedding_text(sample_job())
        self.assertLessEqual(len(text), config.EMBED_MAX_CHARS)

    def test_company_text(self):
        text = company_embedding_text(sample_company())
        for expected in ("凌策科技", "凌策科技有限公司", "计算机软件", "100-499人", "B轮",
                         "成都锦江区航天科技大厦32楼"):
            self.assertIn(expected, text)

    def test_empty_fields_are_skipped(self):
        text = job_embedding_text({"title": "测试岗", "company": {}, "workplace": {}})
        self.assertEqual(text.strip(), "岗位：测试岗")


class HashTests(unittest.TestCase):
    def test_stable_and_sensitive(self):
        self.assertEqual(content_hash("abc"), content_hash("abc"))
        self.assertNotEqual(content_hash("abc"), content_hash("abd"))
        self.assertEqual(len(content_hash("abc")), 32)


class ParseTests(unittest.TestCase):
    def test_parse_list_sorted_by_index(self):
        embedder = ArkEmbedder(api_key="k")
        body = {"data": [
            {"index": 1, "embedding": [0.0, 1.0]},
            {"index": 0, "embedding": [1.0, 0.0]},
        ]}
        self.assertEqual(embedder._parse(body), [[1.0, 0.0], [0.0, 1.0]])
        self.assertEqual(embedder.dim, 2)

    def test_parse_single_object(self):
        embedder = ArkEmbedder(api_key="k")
        self.assertEqual(embedder._parse({"data": {"embedding": [0.5]}}), [[0.5]])

    def test_parse_missing_data_raises(self):
        embedder = ArkEmbedder(api_key="k")
        with self.assertRaises(EmbeddingError):
            embedder._parse({"error": {"message": "boom"}})

    def test_parse_inconsistent_dim_raises(self):
        embedder = ArkEmbedder(api_key="k")
        with self.assertRaises(EmbeddingError):
            embedder._parse({"data": [{"index": 0, "embedding": [1.0]},
                                      {"index": 1, "embedding": [1.0, 2.0]}]})


class BatchingTests(unittest.TestCase):
    def test_embed_splits_batches_and_keeps_order(self):
        embedder = ArkEmbedder(api_key="k", batch_size=2)
        calls = []

        def fake_post(texts):
            calls.append(list(texts))
            return [[float(len(t))] for t in texts]

        embedder._post = fake_post
        vectors = embedder.embed(["a", "bb", "ccc", "dddd", "eeeee"])
        self.assertEqual(calls, [["a", "bb"], ["ccc", "dddd"], ["eeeee"]])
        self.assertEqual(vectors, [[1.0], [2.0], [3.0], [4.0], [5.0]])

    def test_embed_empty(self):
        self.assertEqual(ArkEmbedder(api_key="k").embed([]), [])


class HttpErrorTests(unittest.TestCase):
    def _response(self, status, payload):
        response = mock.Mock()
        response.status_code = status
        response.json.return_value = payload
        response.text = str(payload)
        return response

    def test_client_error_raises_without_retry(self):
        embedder = ArkEmbedder(api_key="k", max_retries=3)
        with mock.patch("boss_crawler.embedding.requests.post") as post:
            post.return_value = self._response(401, {"error": {"message": "bad key"}})
            with self.assertRaises(EmbeddingError) as ctx:
                embedder.embed(["x"])
            self.assertEqual(post.call_count, 1)
            self.assertIn("bad key", str(ctx.exception))

    def test_429_is_retried(self):
        embedder = ArkEmbedder(api_key="k", max_retries=2, log=lambda *_: None)
        responses = [
            self._response(429, {"error": {"message": "rate limited"}}),
            self._response(200, {"data": [{"index": 0, "embedding": [1.0, 2.0]}]}),
        ]
        with mock.patch("boss_crawler.embedding.requests.post", side_effect=responses) as post, \
                mock.patch("boss_crawler.embedding.time.sleep"):
            self.assertEqual(embedder.embed(["x"]), [[1.0, 2.0]])
            self.assertEqual(post.call_count, 2)


class ApiKeyTests(unittest.TestCase):
    def test_env_var_wins(self):
        with mock.patch.dict(os.environ, {"ARK_API_KEY": "from-env"}):
            self.assertEqual(load_api_key(), "from-env")

    def test_file_fallback(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(load_api_key(config.ARK_KEY_FILE), config.ARK_KEY_FILE.read_text(
                encoding="utf-8").strip())

    def test_missing_key_raises(self):
        from pathlib import Path
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(EmbeddingError):
                load_api_key(Path("E:/tmp/jobs/.state/does-not-exist.txt"))


if __name__ == "__main__":
    unittest.main()
