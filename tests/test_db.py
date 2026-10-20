import os
import unittest
from unittest import mock

from boss_crawler import config
from boss_crawler.store import COMPANY_COLUMNS, JOB_COLUMNS, Database, DatabaseError, resolve_password


class PasswordTests(unittest.TestCase):
    def test_env_var_wins(self):
        with mock.patch.dict(os.environ, {"PGPASSWORD": "secret"}):
            self.assertEqual(resolve_password(), "secret")

    def test_file_fallback(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_password(), config.PG_PASSWORD_FILE.read_text(
                encoding="utf-8").strip())

    def test_missing_password_raises(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(config, "PG_PASSWORD_FILE", config.STATE_DIR / "nope.txt"):
            with self.assertRaises(DatabaseError):
                resolve_password()


class SqlBuilderTests(unittest.TestCase):
    def test_upsert_sql_shape(self):
        sql = Database._upsert_sql("jobs", ["job_id", "title", "embedding"], "job_id")
        self.assertTrue(sql.startswith("INSERT INTO jobs (job_id, title, embedding) VALUES"))
        self.assertIn("ON CONFLICT (job_id) DO UPDATE SET", sql)
        self.assertIn("title = EXCLUDED.title", sql)
        self.assertIn("embedding = EXCLUDED.embedding", sql)
        self.assertNotIn("job_id = EXCLUDED.job_id", sql)
        self.assertIn("updated_at = now()", sql)

    def test_columns_include_metadata(self):
        # 元数据列必须齐全
        for column in ("title", "company_name", "address_full", "salary"):
            self.assertIn(column, JOB_COLUMNS)
        for column in ("company_name", "legal_name", "addresses", "industry"):
            self.assertIn(column, COMPANY_COLUMNS)

    def test_upsert_does_not_touch_vectors(self):
        # 重新 db-load 元数据时不能把已入库的向量覆盖成 NULL
        for column in ("embedding", "embedding_model", "embedding_dim", "embedding_hash"):
            self.assertNotIn(column, JOB_COLUMNS)
            self.assertNotIn(column, COMPANY_COLUMNS)


class DatabaseDefaultsTests(unittest.TestCase):
    def test_defaults_from_config(self):
        with mock.patch.dict(os.environ, {"PGPASSWORD": "secret"}):
            db = Database()
        self.assertEqual(db.host, config.PG_HOST)
        self.assertEqual(db.port, config.PG_PORT)
        self.assertEqual(db.user, config.PG_USER)
        self.assertEqual(db.database, config.PG_DATABASE)
        self.assertFalse(db._pgvector)

    def test_overrides(self):
        with mock.patch.dict(os.environ, {"PGPASSWORD": "secret"}):
            db = Database(host="db.local", port=6000, user="u", database="d")
        self.assertEqual((db.host, db.port, db.user, db.database), ("db.local", 6000, "u", "d"))


class SchemaSqlTests(unittest.TestCase):
    def test_schema_has_tables_functions_and_views(self):
        from boss_crawler.store import SCHEMA_SQL

        for fragment in ("CREATE TABLE IF NOT EXISTS jobs", "CREATE TABLE IF NOT EXISTS companies",
                         "CREATE TABLE IF NOT EXISTS embedding_runs",
                         "FUNCTION cosine_similarity", "VIEW job_vector_status",
                         "embedding       real[]", "raw             jsonb"):
            self.assertIn(fragment, SCHEMA_SQL)


if __name__ == "__main__":
    unittest.main()
