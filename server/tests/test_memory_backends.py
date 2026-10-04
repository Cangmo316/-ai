"""
落库后端一致性测试（P2）

**为什么要有"同一套断言跑两个后端"**：记忆是老人的私事，落库后如果行为跟内存版不一致
（比如清空没删干净、待复核的漏进了检索），危害比"没落库"更大。
所以这里把核心行为抽成一份断言，内存版与 SQL 版各跑一遍。

另外守住几件运维层面的坑：
- 相对路径按 server/ 解析（不是 cwd——否则从别处启动会新建一个空库，看着像"数据丢了"）
- 建表幂等（重复启动不该报错，也不该清数据）
- `DATABASE_URL` 写错要在**启动阶段**就报错，不能等到第一次写记忆
- PG 未装驱动时报人话（而不是 ImportError 堆栈）
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.llm.fake import FakeProvider
from app.main import create_app
from app.memory import KIND_EXPERIENCE, KIND_PREFERENCE, MemoryStore, SqlMemoryStore
from app.memory.retrieval import search
from app.storage import Database, DatabaseError, open_database


def behavior_suite(case: unittest.TestCase, store) -> None:
    """核心行为断言：两个后端必须完全一致"""
    first = store.add("e_1", "老人 2023 年跟儿子去过海南", kind=KIND_EXPERIENCE, tags=["儿子", "旅行"])
    second = store.add("e_1", "老人爱听戏", kind=KIND_PREFERENCE, tags=["戏曲"])
    # 自动整理的低置信：待复核 + 家属不可见
    pending = store.add("e_1", "老人好像提过老家的桥", source="auto", confidence=0.4, tags=["老家"])

    case.assertEqual(len(store.all_of("e_1")), 3)
    case.assertEqual(len(store.family_view("e_1")), 2, "自动整理的不该出现在家属视图")
    case.assertEqual(len(store.pending_of("e_1")), 1)
    case.assertEqual(pending.review, "pending")

    # 检索：相关能捞出，无关捞不出，待复核的绝不进
    hits = search(store, "e_1", "你儿子带我去海南玩")
    case.assertTrue(hits)
    case.assertIn("海南", hits[0][0].text)
    case.assertEqual(search(store, "e_1", "老家的桥"), [], "待复核的不该被检索到")

    # 改 / 复核 / 删 / 清空
    updated = store.update(second.id, text="老人爱听评剧", tags=["戏曲", "评剧"])
    case.assertEqual(updated.text, "老人爱听评剧")
    case.assertEqual(updated.tags, ["戏曲", "评剧"])

    store.review(pending.id, approve=True)
    case.assertEqual(len(store.usable_of("e_1")), 3)
    case.assertEqual(len(search(store, "e_1", "老家的桥")), 1, "复核通过后可以参与检索")

    case.assertTrue(store.delete(first.id))
    case.assertFalse(store.delete(first.id))
    case.assertEqual(len(store.all_of("e_1")), 2)

    case.assertEqual(store.clear("e_1"), 2)
    case.assertEqual(store.all_of("e_1"), [])

    # 设置
    settings = store.settings_for("e_1")
    case.assertFalse(settings.auto_extract, "默认必须是关的")
    store.update_settings("e_1", auto_extract=True)
    case.assertTrue(settings.auto_extract)
    case.assertTrue(settings.consented_at)


class InMemoryBackendTests(unittest.TestCase):
    def test_behavior(self) -> None:
        behavior_suite(self, MemoryStore())


class SqliteBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "nested" / "bilin.db"
        self.db = open_database("sqlite:///" + str(self.db_path).replace("\\", "/"))
        self.store = SqlMemoryStore(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_behavior_matches_memory_backend(self) -> None:
        behavior_suite(self, self.store)

    def test_creates_parent_directory(self) -> None:
        self.assertTrue(self.db_path.parent.is_dir(), "父目录该被自动建出来")

    def test_survives_restart(self) -> None:
        """**落库的核心承诺**：关掉再开，记忆还在"""
        self.store.add("e_1", "老人 2023 年跟儿子去过海南", tags=["儿子"])
        pending = self.store.add("e_1", "老人好像提过老家的桥", source="auto", confidence=0.3)
        self.store.update_settings("e_1", auto_extract=True)
        self.db.close()

        reopened = open_database("sqlite:///" + str(self.db_path).replace("\\", "/"))
        reloaded = SqlMemoryStore(reopened)
        try:
            entries = reloaded.all_of("e_1")
            self.assertEqual(len(entries), 2, "重启后记忆条数应一致")
            by_id = {entry.id: entry for entry in entries}
            self.assertIn("海南", by_id[[e for e in by_id if "海南" in by_id[e].text][0]].text)
            # 复核状态、可见性、标签都得原样回来
            pending_back = reloaded.get(pending.id)
            self.assertEqual(pending_back.review, "pending")
            self.assertFalse(pending_back.visible_to_family)
            self.assertEqual(len(reloaded.pending_of("e_1")), 1)
            # 设置也要在
            self.assertTrue(reloaded.settings_for("e_1").auto_extract)
            self.assertTrue(reloaded.settings_for("e_1").consented_at)
        finally:
            reopened.close()

    def test_delete_and_clear_persist(self) -> None:
        first = self.store.add("e_1", "要去掉的一条")
        self.store.add("e_1", "留着的一条")
        self.store.delete(first.id)
        self.store.clear("e_1")
        self.db.close()

        reopened = open_database("sqlite:///" + str(self.db_path).replace("\\", "/"))
        try:
            self.assertEqual(SqlMemoryStore(reopened).all_of("e_1"), [], "清空必须落库，不能只在内存里清")
        finally:
            reopened.close()

    def test_schema_is_idempotent_and_keeps_data(self) -> None:
        self.store.add("e_1", "不该被建表操作清掉")
        self.db.close()
        # 再开一次 = 再跑一遍建表语句
        reopened = open_database("sqlite:///" + str(self.db_path).replace("\\", "/"))
        try:
            again = SqlMemoryStore(reopened)
            self.assertEqual(len(again.all_of("e_1")), 1, "重复建表不该清数据")
        finally:
            reopened.close()

    def test_other_elder_untouched(self) -> None:
        self.store.add("e_1", "老人甲的记忆")
        self.store.add("e_2", "老人乙的记忆")
        self.assertEqual(self.store.clear("e_1"), 1)
        self.db.close()

        reopened = open_database("sqlite:///" + str(self.db_path).replace("\\", "/"))
        try:
            reloaded = SqlMemoryStore(reopened)
            self.assertEqual(len(reloaded.all_of("e_2")), 1, "清空只影响一位老人")
        finally:
            reopened.close()


class DatabaseUrlTests(unittest.TestCase):
    def test_relative_path_resolves_against_base_dir(self) -> None:
        """相对路径按 server/ 解析：从别处启动也不该新建一个空库（看着像数据丢了）"""
        base = Path(tempfile.mkdtemp())
        db = Database("sqlite:///data/bilin.db", base_dir=base)
        self.assertEqual(db.path, base / "data" / "bilin.db")

    def test_memory_url_means_no_persistence(self) -> None:
        db = Database("memory://")
        self.assertFalse(db.enabled)
        self.assertIn("未落库", db.describe())
        with self.assertRaises(DatabaseError):
            db.connect()

    def test_unknown_url_fails_fast(self) -> None:
        with self.assertRaises(DatabaseError):
            Database("mysql://localhost/bilin")

    def test_postgres_without_driver_gives_human_message(self) -> None:
        db = Database("postgresql://user:pass@127.0.0.1:5432/bilin")
        self.assertEqual(db.dialect, "postgresql")
        self.assertEqual(db.placeholder, "%s")
        try:
            db.connect()
        except DatabaseError as exc:
            self.assertIn("psycopg", str(exc))
        except Exception as exc:  # pragma: no cover - 装了驱动时走这里（连不上）
            self.assertNotIsInstance(exc, ImportError, "不该抛裸 ImportError")

    def test_describe_reports_mode(self) -> None:
        self.assertIn("sqlite", Database("sqlite:///:memory:").describe())


class AppWiringTests(unittest.TestCase):
    def test_default_is_not_durable_and_says_so(self) -> None:
        app = create_app(
            settings=Settings(llm_provider="fake", scheduler_enabled=False),
            provider=FakeProvider(delay=0),
        )
        health = TestClient(app).get("/healthz").json()
        self.assertFalse(health["storageDurable"], "默认不该落库（测试要互不污染）")
        self.assertIn("未落库", health["storage"])

    def test_sqlite_backend_wired_through_app(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            url = "sqlite:///" + str(Path(tmp) / "app.db").replace("\\", "/")
            app = create_app(
                settings=Settings(llm_provider="fake", scheduler_enabled=False, database_url=url),
                provider=FakeProvider(delay=0),
            )
            client = TestClient(app)
            created = client.post("/v1/memories", json={"elderId": "e_1", "text": "老人去过海南"})
            self.assertEqual(created.status_code, 200, created.text)
            health = client.get("/healthz").json()
            self.assertTrue(health["storageDurable"])
            self.assertEqual(health["memory"]["total"], 1)
            app.state.database.close()

            # 用同一路径再建一个 app：数据应当还在（这就是"落库"的意义）
            second = create_app(
                settings=Settings(llm_provider="fake", scheduler_enabled=False, database_url=url),
                provider=FakeProvider(delay=0),
            )
            try:
                listed = TestClient(second).get("/v1/memories", params={"elderId": "e_1"}).json()
                self.assertEqual(listed["count"], 1, "重启后记忆该还在")
            finally:
                second.state.database.close()


if __name__ == "__main__":
    unittest.main()
