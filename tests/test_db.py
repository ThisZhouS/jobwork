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


class TransactionTests(unittest.TestCase):
    class _StubDB:
        def __init__(self):
            self.rolled_back = 0

        def rollback(self):
            self.rolled_back += 1

    def test_cursor_context_rolls_back_on_error(self):
        from boss_crawler.store.postgres import _CursorContext

        class Cur:
            closed = False

            def close(self):
                self.closed = True

        db, cur = self._StubDB(), Cur()
        with self.assertRaises(ValueError):
            with _CursorContext(db, cur):
                raise ValueError("boom")
        self.assertEqual(db.rolled_back, 1)
        self.assertTrue(cur.closed)

    def test_cursor_context_keeps_transaction_on_success(self):
        from boss_crawler.store.postgres import _CursorContext

        class Cur:
            def close(self):
                pass

        db = self._StubDB()
        with _CursorContext(db, Cur()):
            pass
        self.assertEqual(db.rolled_back, 0)


class MigrationRunnerTests(unittest.TestCase):
    def _fake_db(self, applied=(), fail_on=()):
        from contextlib import contextmanager

        class Cur:
            def __init__(self, db):
                self.db = db
                self._rows = []

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=None):
                text = sql.strip()
                if text.startswith("SELECT version FROM schema_migrations"):
                    self._rows = [{"version": v} for v in sorted(self.db.applied)]
                elif text.startswith("INSERT INTO schema_migrations"):
                    self.db.applied.add(params[0])
                elif text.startswith("CREATE TABLE IF NOT EXISTS schema_migrations"):
                    pass
                else:
                    if text in self.db.fail_on:
                        raise RuntimeError(text)
                    self.db.bodies.append(text)

            def fetchall(self):
                return self._rows

        class FakeDB(Database):
            def __init__(self):
                self.applied = set(applied)
                self.fail_on = set(fail_on)
                self.bodies = []
                self.commits = 0

            def connect(self):
                return self

            def cursor(self):
                return Cur(self)

            def commit(self):
                self.commits += 1

            def rollback(self):
                pass

            @contextmanager
            def transaction(self):
                try:
                    yield self
                except BaseException:
                    self.rollback()
                    raise
                else:
                    self.commit()

        return FakeDB()

    def test_applies_pending_in_version_order(self):
        # 只看版本字符串排序，与传入顺序无关
        db = self._fake_db(applied={"app/001"})
        applied = db.apply_migrations([
            ("app/003", "SQL_3"), ("app/001", "SQL_1"), ("app/002", "SQL_2"),
        ])
        self.assertEqual(applied, ["app/002", "app/003"])
        self.assertEqual(db.bodies, ["SQL_2", "SQL_3"])
        self.assertEqual(db.applied, {"app/001", "app/002", "app/003"})

    def test_skips_when_all_applied(self):
        db = self._fake_db(applied={"core/001", "app/001"})
        self.assertEqual(db.apply_migrations([("core/001", "SQL"), ("app/001", "SQL")]), [])

    def test_failed_migration_is_not_recorded(self):
        db = self._fake_db(fail_on={"SQL_BAD"})
        with self.assertRaises(RuntimeError):
            db.apply_migrations([("app/002", "SQL_BAD")])
        self.assertEqual(db.applied, set())


class RuntimeAssetTests(unittest.TestCase):
    def test_runtime_files_live_inside_package(self):
        """wheel 只带包内文件：schema/stealth/默认配置必须在包目录下。"""
        from boss_crawler import config
        from boss_crawler.store.app_store import SCHEMA_FILE

        assert SCHEMA_FILE.is_file()
        assert config.STEALTH_JS.is_file()
        defaults = config.Path(config.__file__).with_name("defaults")
        for name in ("agents.json", "models.json", "risk_api.json"):
            assert (defaults / name).is_file()


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
