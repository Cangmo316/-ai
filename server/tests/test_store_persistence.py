"""
会话与计划的落库一致性测试（P2）

**为什么要有"同一套断言跑两个后端"**（与 `tests/test_memory_backends.py` 同一套理由）：
计划一旦落库，"重启后 `active()` 还在不在"就不再是存储细节，而是**产品硬约束**——
`GET /v1/plans/today` 与所有提醒都只从 `active()` 取数，「未确认不产生提醒」这条闸门
完全依赖它。落库后行为与内存版不一致（状态退回去、打卡丢一条、顺序乱了），
危害比"没落库"更大。所以这里把核心行为抽成断言，内存版与 SQL 版各跑一遍。

另外守住几件运维层面的坑：
- **同一秒写入的多条消息，重启后顺序不能乱**（`created_at` 只精确到秒，顺序靠写入序号）
- **重复建表幂等**（重复启动不该报错，也不该清数据）
- **被内存裁掉的老消息不能留在库里**（否则重启后条数与内存版分叉）
- 相对路径、`memory://` 的语义由 `test_memory_backends.py` 守着，这里不重复

⚠️ 用例一律用**专用老人 id `e_plan_test`**：`build_plan` 会按档案匹配知识库条目，
但 `ElderStore` 里没有这个 id 时会兜底到默认档案——用它就是为了任何"清空/删除"类断言
都碰不到演示数据 `e_1`（上一轮的记忆契约测试就是拿 `e_1` 跑一键清空，把演示数据清了）。
测试库一律落在 `tempfile` 的临时目录或 `sqlite:///:memory:`，**不在仓库里留库文件**。
"""

from __future__ import annotations

import dataclasses
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.knowledge.loader import load_knowledge
from app.llm.fake import FakeProvider
from app.main import create_app
from app.models.elder import ElderStore
from app.models.message import (
    MAX_MESSAGES,
    ROLE_AGENT,
    ROLE_ELDER,
    TYPE_CARD,
    TYPE_STICKER,
    TYPE_TEXT,
    ConversationStore,
    Message,
)
from app.models.sql_store import SqlConversationStore
from app.plan.engine import PlanEngine
from app.plan.models import (
    STATUS_ACTIVE,
    STATUS_ADJUSTING,
    STATUS_DRAFT,
    STATUS_ENDED,
    STATUS_PENDING,
    STATUS_REJECTED,
    CarePlan,
    PlanCheckin,
    PlanItem,
    today_str,
)
from app.plan.sql_store import SqlPlanStore
from app.plan.store import PlanStore
from app.storage import Database, JsonPayloadTable, open_database

# 专用老人 id：这些用例会 clear()，绝不能碰 e_1（演示数据）
ELDER = "e_plan_test"
CONVERSATION = "c_store_test"


def sqlite_url(directory: str | Path) -> str:
    return "sqlite:///" + str(Path(directory) / "nested" / "bilin-test.db").replace("\\", "/")


def sample_plan(plan_id: str = "plan_test_1", elder_id: str = ELDER, status: str = STATUS_DRAFT) -> CarePlan:
    """一份最小的计划：不依赖知识库，专测存取（引擎的行为另有用例守着）"""
    return CarePlan(
        id=plan_id,
        elder_id=elder_id,
        status=status,
        items=[
            PlanItem(
                id="pi_test_1",
                time="08:00",
                type="monitor",
                title="量个血压",
                detail="坐着歇五分钟再量",
                freq="每日",
                strong_remind=True,
                entry_id="nphis_bp",
                source="s_nphis",
                source_name="国家基本公共卫生服务规范",
                version="第三版",
                boundary="不做诊断、不改药量",
            )
        ],
        goal="稳住日常起居",
        start_date="2026-01-01",
        end_date="2026-03-31",
        knowledge_version="0.1.0-draft",
        sources=[{"id": "s_nphis", "name": "国家基本公共卫生服务规范", "entries": 1}],
        note="依据公开权威指南整理的生活提醒，不构成诊断或用药建议",
    )


# ---------------------------------------------------------------- 行为断言


def conversation_behavior(case: unittest.TestCase, store) -> None:
    """会话的核心行为：两个后端必须完全一致"""
    # 第一次访问会话 = 建桶，会先塞一句问候语（老人一进对话页就有内容，不白屏）
    initial = store.history(CONVERSATION)
    case.assertEqual(len(initial), 1, "新会话应先有一句问候")
    case.assertEqual(initial[0].role, ROLE_AGENT)

    store.append(CONVERSATION, Message(id="m_1", role=ROLE_ELDER, type=TYPE_TEXT, text="妈 药吃了没"))
    store.append(CONVERSATION, Message(id="a_1", role=ROLE_AGENT, type=TYPE_TEXT, text="吃了 你别惦记"))
    store.append(CONVERSATION, Message(id="a_2", role=ROLE_AGENT, type=TYPE_STICKER, sticker="pill"))
    store.append(
        CONVERSATION,
        Message(
            id="a_3",
            role=ROLE_AGENT,
            type=TYPE_CARD,
            card={"kind": "plan_item", "plan": {"time": "08:00", "title": "量个血压", "state": "todo"}},
        ),
    )
    store.append(CONVERSATION, Message(id="m_2", role=ROLE_ELDER, type=TYPE_TEXT, text="知道了", seconds=7))

    history = store.history(CONVERSATION, limit=0)
    case.assertEqual(
        [item.id for item in history],
        [initial[0].id, "m_1", "a_1", "a_2", "a_3", "m_2"],
        "顺序必须是追加顺序",
    )
    case.assertEqual(history[3].sticker, "pill", "表情要原样回来")
    case.assertEqual(history[4].card["kind"], "plan_item", "卡片要原样回来")
    case.assertEqual(history[5].seconds, 7)
    # limit 取的是**最后** N 条（端侧一次只拉一屏）
    case.assertEqual([item.id for item in store.history(CONVERSATION, limit=2)], ["a_3", "m_2"])

    # 会话之间互不串台
    case.assertEqual(len(store.history("c_other")), 1, "另一个会话只有它自己的问候语")
    store.clear(CONVERSATION)
    case.assertEqual(len(store.history(CONVERSATION)), 1, "清空一个会话 = 回到只有问候语的初始态")
    case.assertNotIn("m_1", [item.id for item in store.history(CONVERSATION, limit=0)])
    case.assertEqual(len(store.history("c_other", limit=0)), 1, "清空一个会话不影响另一个会话")

    store.clear()
    case.assertEqual(len(store.history("c_other", limit=0)), 1, "全局清空后另一个会话也只剩问候语")


def plan_behavior(case: unittest.TestCase, store) -> None:
    """计划与打卡的核心行为：两个后端必须完全一致"""
    plan = sample_plan()
    store.add(plan)
    case.assertEqual(store.get(plan.id).id, plan.id)
    case.assertEqual(len(store.plans_of(ELDER)), 1)

    # 「未确认不产生提醒」的落点：draft 与 pending 都拿不到 active
    case.assertIsNone(store.active(ELDER), "草稿绝不能生效")
    plan.status = STATUS_PENDING
    plan.log("submit", "已提交家属确认")
    store.save(plan)
    case.assertEqual(len(store.pending(ELDER)), 1)
    case.assertIsNone(store.active(ELDER), "待确认仍然不算生效")

    plan.status = STATUS_ACTIVE
    plan.confirmed_at = "2026-01-01T09:00:00+08:00"
    plan.confirmed_by = "女儿小丽"
    plan.log("confirm", "家属确认，计划生效", "女儿小丽")
    store.save(plan)
    active = store.active(ELDER)
    case.assertEqual(active.id, plan.id)
    case.assertEqual(active.status, STATUS_ACTIVE)
    case.assertEqual(active.confirmed_by, "女儿小丽")
    case.assertEqual(active.items[0].title, "量个血压")
    case.assertEqual(active.items[0].source_name, "国家基本公共卫生服务规范")

    # 打卡：同一天同一项幂等
    item_id = plan.items[0].id
    first = store.checkin(plan, item_id, ELDER, "2026-01-05")
    second = store.checkin(plan, item_id, ELDER, "2026-01-05")
    case.assertEqual(first.id, second.id, "同一天同一项重复打卡只留一条")
    case.assertEqual(len(store.checkins_of(ELDER)), 1)
    case.assertEqual(store.find_checkin(item_id, "2026-01-05").source, "elder")
    case.assertEqual(store.last_checkin(item_id).date, "2026-01-05")
    case.assertTrue(store.undo_checkin(item_id, "2026-01-05"))
    case.assertFalse(store.undo_checkin(item_id, "2026-01-05"), "已经取消掉的再取消就该返回 False")
    case.assertEqual(store.checkins_of(ELDER), [])

    # 一位老人多份计划；清空只影响这一份库
    other = sample_plan(plan_id="plan_other", elder_id="e_other")
    store.add(other)
    case.assertEqual(len(store.plans_of(ELDER)), 1)
    case.assertEqual(len(store.plans_of("e_other")), 1)
    store.clear()
    case.assertEqual(store.plans_of(ELDER), [])
    case.assertEqual(store.plans_of("e_other"), [])


# ---------------------------------------------------------------- 模型互逆


class ModelRoundTripTests(unittest.TestCase):
    """`from_dict()` 必须与 `to_dict()` 严格互逆（落库就是存 to_dict 的结果）"""

    def test_message_round_trip(self) -> None:
        messages = [
            Message(id="m_1", role=ROLE_ELDER),
            Message(id="m_2", role=ROLE_ELDER, type=TYPE_TEXT, text="妈 药吃了没"),
            Message(id="a_1", role=ROLE_AGENT, type=TYPE_STICKER, sticker="pill"),
            Message(id="a_2", role=ROLE_AGENT, type=TYPE_CARD, card={"kind": "plan_item", "plan": {"time": "08:00"}}),
            Message(id="m_3", role=ROLE_ELDER, type=TYPE_TEXT, text="嗯", seconds=12),
        ]
        for message in messages:
            with self.subTest(message=message.id):
                self.assertEqual(Message.from_dict(message.to_dict()), message)

    def test_message_missing_optional_fields_use_defaults(self) -> None:
        """to_dict 会省掉空字段，读回来必须补成 dataclass 的默认值（不能是 None）"""
        back = Message.from_dict({"id": "m_x", "role": ROLE_AGENT, "type": TYPE_TEXT, "createdAt": "2026-01-05T08:00:00+08:00"})
        self.assertEqual(back.text, "")
        self.assertEqual(back.sticker, "")
        self.assertIsNone(back.card)
        self.assertEqual(back.seconds, 0)

    def test_message_dirty_values_do_not_crash(self) -> None:
        back = Message.from_dict({"id": None, "role": "", "type": "", "text": None, "card": "不是对象", "seconds": "3"})
        self.assertEqual(back.id, "")
        self.assertEqual(back.role, ROLE_ELDER, "角色缺失时兜底成老人（不安全的方向宁可当成对方说话）")
        self.assertEqual(back.type, TYPE_TEXT)
        self.assertEqual(back.text, "")
        self.assertIsNone(back.card)
        self.assertEqual(back.seconds, 3)
        self.assertTrue(back.created_at, "缺 createdAt 时补当前时间")

    def test_plan_round_trip(self) -> None:
        plan = sample_plan()
        self.assertEqual(CarePlan.from_dict(plan.to_dict()), plan)

    def test_plan_item_basis_mapping_and_weight(self) -> None:
        """items 的字段名映射是本文件最该守住的一处：扁平字段 ↔ basis 子对象"""
        item = dataclasses.replace(sample_plan().items[0], weight=1.5)
        back = PlanItem.from_dict(item.to_dict())
        self.assertEqual(back.entry_id, item.entry_id)
        self.assertEqual(back.source, item.source)
        self.assertEqual(back.source_name, item.source_name)
        self.assertEqual(back.version, item.version)
        self.assertEqual(back.boundary, item.boundary)
        self.assertTrue(back.basis_text(), "依据文案要能重新拼出来")
        # weight 不在端侧契约里（to_dict 不下发），所以读回来是 0——这是刻意的，见 from_dict 注释
        self.assertEqual(back.weight, 0.0)
        self.assertEqual(dataclasses.replace(back, weight=item.weight), item, "除 weight 外逐字段一致")

    def test_care_plan_tolerates_missing_and_dirty_fields(self) -> None:
        back = CarePlan.from_dict({"id": "plan_x", "elderId": ELDER})
        self.assertEqual(back.status, STATUS_DRAFT, "状态缺失时退回草稿（最不危险的那一档）")
        self.assertEqual(back.items, [])
        self.assertEqual(back.sources, [])
        self.assertEqual(back.history, [])
        self.assertEqual(back.created_by, "agent")
        self.assertTrue(back.created_at)

        dirty = CarePlan.from_dict({"id": "plan_y", "items": "坏数据", "sources": [1, {"id": "s"}], "history": None})
        self.assertEqual(dirty.items, [])
        self.assertEqual(dirty.sources, [{"id": "s"}], "只留 dict 元素")
        self.assertEqual(dirty.history, [])

    def test_checkin_round_trip(self) -> None:
        record = PlanCheckin(
            id="pi_1",
            plan_id="plan_1",
            plan_item_id="pi_item",
            elder_id=ELDER,
            date="2026-01-05",
            done_at="2026-01-05T08:05:00+08:00",
            source="family",
        )
        self.assertEqual(PlanCheckin.from_dict(record.to_dict()), record)
        # 打卡是完成率的凭据：字段缺失也保留这条记录，不丢掉老人真做过的事
        kept = PlanCheckin.from_dict({"id": "pi_2", "date": "2026-01-06"})
        self.assertEqual(kept.id, "pi_2")
        self.assertEqual(kept.source, "elder")
        self.assertTrue(kept.done_at)


# ---------------------------------------------------------------- 两个后端


class InMemoryBackendTests(unittest.TestCase):
    def test_conversation_behavior(self) -> None:
        conversation_behavior(self, ConversationStore())

    def test_plan_behavior(self) -> None:
        plan_behavior(self, PlanStore())


class SqliteBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.url = sqlite_url(self.tmp.name)
        self.db = open_database(self.url)
        self.conversations = SqlConversationStore(self.db)
        self.plans = SqlPlanStore(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_conversation_behavior_matches_memory_backend(self) -> None:
        conversation_behavior(self, self.conversations)

    def test_plan_behavior_matches_memory_backend(self) -> None:
        plan_behavior(self, self.plans)

    def test_creates_parent_directory(self) -> None:
        self.assertTrue(Path(self.url[len("sqlite:///") :]).parent.is_dir(), "父目录该被自动建出来")


class ConversationPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.url = sqlite_url(self.tmp.name)
        self.db = open_database(self.url)
        self.store = SqlConversationStore(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def reopen(self) -> SqlConversationStore:
        """关库再开 = 重启服务"""
        self.db.close()
        self.db = open_database(self.url)
        return SqlConversationStore(self.db)

    def test_messages_survive_restart_with_order_and_roles(self) -> None:
        # 刻意让所有消息的时间戳**完全相同**：顺序只能靠写入序号，
        # 靠 created_at 排的话（只精确到秒）重启后对话就乱了
        stamp = "2026-01-05T08:00:00+08:00"
        self.store.append(CONVERSATION, Message(id="m_1", role=ROLE_ELDER, type=TYPE_TEXT, text="第一句", created_at=stamp))
        self.store.append(CONVERSATION, Message(id="a_1", role=ROLE_AGENT, type=TYPE_TEXT, text="第二句", created_at=stamp))
        self.store.append(CONVERSATION, Message(id="a_2", role=ROLE_AGENT, type=TYPE_STICKER, sticker="pill", created_at=stamp))
        self.store.append(CONVERSATION, Message(id="m_2", role=ROLE_ELDER, type=TYPE_TEXT, text="第四句", created_at=stamp))
        before = self.store.history(CONVERSATION, limit=0)

        after = self.reopen().history(CONVERSATION, limit=0)
        self.assertEqual([item.id for item in after], [item.id for item in before], "重启后消息顺序必须一致")
        self.assertEqual([item.role for item in after], [item.role for item in before], "角色顺序必须一致")
        self.assertEqual([item.text for item in after], [item.text for item in before])
        self.assertEqual(after[0].role, ROLE_AGENT, "第一条仍是问候语")
        self.assertEqual(after[3].sticker, "pill")
        self.assertEqual(after[1].created_at, stamp, "时间戳本身也不能被改写")

    def test_greeting_id_is_stable_across_restart(self) -> None:
        first = self.store.history(CONVERSATION)[0]
        again = self.reopen().history(CONVERSATION)
        self.assertEqual(len(again), 1, "重启不该再补一条问候语")
        self.assertEqual(again[0].id, first.id, "问候语的 id 要稳定（端侧按 id 去重）")

    def test_clear_persists(self) -> None:
        self.store.append(CONVERSATION, Message(id="m_keep", role=ROLE_ELDER, text="这条要被清掉"))
        self.store.clear(CONVERSATION)
        reloaded = self.reopen().history(CONVERSATION, limit=0)
        self.assertNotIn("m_keep", [item.id for item in reloaded], "清空必须落库，不能只在内存里清")
        self.assertEqual(len(reloaded), 1, "清空后回到只有问候语的初始态")

    def test_global_clear_persists(self) -> None:
        self.store.append("c_a", Message(id="m_a", role=ROLE_ELDER, text="A"))
        self.store.append("c_b", Message(id="m_b", role=ROLE_ELDER, text="B"))
        self.store.clear()
        reloaded = self.reopen()
        self.assertNotIn("m_a", [item.id for item in reloaded.history("c_a", limit=0)])
        self.assertNotIn("m_b", [item.id for item in reloaded.history("c_b", limit=0)])

    def test_trimmed_messages_are_deleted_from_db(self) -> None:
        """内存里超过 MAX_MESSAGES 会裁掉最老的：库里也必须删，否则重启后条数变多"""
        for index in range(MAX_MESSAGES + 5):
            self.store.append(
                CONVERSATION, Message(id="m_%03d" % index, role=ROLE_ELDER, text="第 %d 句" % index)
            )
        reloaded = self.reopen().history(CONVERSATION, limit=0)
        self.assertEqual(len(reloaded), MAX_MESSAGES)
        self.assertEqual(reloaded[-1].id, "m_%03d" % (MAX_MESSAGES + 4))
        self.assertNotIn("m_000", [item.id for item in reloaded], "被裁掉的老消息不该从库里回来")

    def test_schema_is_idempotent_and_keeps_data(self) -> None:
        self.store.append(CONVERSATION, Message(id="m_1", role=ROLE_ELDER, text="不该被建表操作清掉"))
        again = SqlConversationStore(self.db)  # 再跑一遍建表语句 = 再启动一次
        self.assertEqual(len(again.history(CONVERSATION, limit=0)), 2, "重复建表不该清数据")


class PlanPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.url = sqlite_url(self.tmp.name)
        self.db = open_database(self.url)
        self.engine, self.store = self.build(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    @staticmethod
    def build(db: Database) -> tuple[PlanEngine, SqlPlanStore]:
        store = SqlPlanStore(db)
        engine = PlanEngine(
            load_knowledge(),
            store,
            ElderStore(),
            Settings(llm_provider="fake", scheduler_enabled=False),
        )
        return engine, store

    def reopen(self) -> tuple[PlanEngine, SqlPlanStore]:
        self.db.close()
        self.db = open_database(self.url)
        return self.build(self.db)

    def test_unconfirmed_plan_never_becomes_active_after_restart(self) -> None:
        """**产品硬约束**：未确认的计划重启后依然不产生提醒"""
        plan = self.engine.build_plan(ELDER)
        self.engine.submit(plan)
        self.assertIsNone(self.store.active(ELDER), "未确认前不该生效")
        self.assertTrue(plan.items, "知识库该匹配出条目")

        engine, store = self.reopen()
        self.assertIsNone(store.active(ELDER), "重启后未确认的仍然不生效")
        self.assertEqual([item.id for item in store.pending(ELDER)], [plan.id], "待确认列表要还在")
        self.assertEqual(store.get(plan.id).status, STATUS_PENDING, "状态不能退回 draft")
        self.assertEqual(engine.today(ELDER)["total"], 0, "今日计划必须还是空的")

    def test_confirmed_plan_stays_active_after_restart(self) -> None:
        """**产品硬约束**：确认生效后关库重开，`active()` 仍返回同一份"""
        first = self.engine.build_plan(ELDER, goal="第一份")
        self.engine.submit(first)
        self.engine.confirm(first, actor="女儿小丽")
        self.assertEqual(self.store.active(ELDER).id, first.id)

        # 第二份提交后不生效：过渡期旧计划继续执行
        second = self.engine.build_plan(ELDER, goal="第二份")
        self.engine.submit(second)
        self.assertEqual(self.store.active(ELDER).id, first.id, "未确认的新计划不能顶掉生效中的旧计划")

        engine, store = self.reopen()
        active = store.active(ELDER)
        self.assertIsNotNone(active, "重启后 active 必须还在——未确认不产生提醒全靠它")
        self.assertEqual(active.id, first.id)
        self.assertEqual(active.status, STATUS_ACTIVE)
        self.assertEqual(active.goal, "第一份")
        self.assertEqual(active.confirmed_by, "女儿小丽")
        self.assertTrue(active.confirmed_at)
        self.assertEqual([item.title for item in active.items], [item.title for item in first.items])
        self.assertEqual(
            [item.time for item in active.items], [item.time for item in first.items], "时段顺序也要一致"
        )
        self.assertTrue(active.items[0].source_name, "依据（basis 映射）要原样回来")
        self.assertTrue(active.history, "流转留痕要一起回来")
        self.assertIn("confirm", [entry.get("action") for entry in active.history])
        self.assertEqual({plan.id for plan in store.plans_of(ELDER)}, {first.id, second.id})
        self.assertGreater(engine.today(ELDER)["total"], 0, "重启后今日计划照常有内容")

        # 确认第二份 → 第一份 ended，这个状态同样要落库
        engine.confirm(store.get(second.id), actor="儿子小明")
        _, again = self.reopen()
        self.assertEqual(again.active(ELDER).id, second.id)
        self.assertEqual(again.get(first.id).status, STATUS_ENDED, "旧计划的 ended 没落库就会多出一份生效计划")

    def test_rejected_state_survives_restart(self) -> None:
        plan = self.engine.build_plan(ELDER)
        self.engine.submit(plan)
        self.engine.reject(plan, reason="这一项家里人不放心")
        _, store = self.reopen()
        rejected = store.get(plan.id)
        self.assertEqual(rejected.status, STATUS_REJECTED)
        self.assertEqual(rejected.rejected_reason, "这一项家里人不放心")
        self.assertIsNone(store.active(ELDER), "驳回的计划永远不生效")

    def test_adjusting_state_survives_restart_and_keeps_reminding(self) -> None:
        plan = self.engine.build_plan(ELDER)
        self.engine.submit(plan)
        self.engine.confirm(plan)
        self.engine.mark_adjusting(plan, "最近几天只完成了 1/5 项")
        engine, store = self.reopen()
        adjusting = store.get(plan.id)
        self.assertEqual(adjusting.status, STATUS_ADJUSTING)
        self.assertEqual(store.active(ELDER).id, plan.id, "调整期间旧计划继续执行，不出现提醒真空")
        self.assertIn("adjusting", [entry.get("action") for entry in adjusting.history])
        self.assertGreater(engine.today(ELDER)["total"], 0, "调整期间今日计划照常")

    def test_checkin_is_idempotent_and_completion_survives_restart(self) -> None:
        plan = self.engine.build_plan(ELDER)
        self.engine.submit(plan)
        self.engine.confirm(plan)
        item_id = plan.items[0].id
        day = today_str()

        first = self.store.checkin(plan, item_id, ELDER, day)
        second = self.store.checkin(plan, item_id, ELDER, day)
        self.assertEqual(first.id, second.id, "同一天同一项重复点只记一条")
        before = self.engine.completion(plan, days=7)
        self.assertEqual(before["done"], 1)

        engine, store = self.reopen()
        again = store.checkin(store.get(plan.id), item_id, ELDER, day)
        self.assertEqual(again.id, first.id, "重启后重复打卡仍是同一条（幂等口径没变）")
        self.assertEqual(len(store.checkins_of(ELDER)), 1, "库里也只该有一条")
        self.assertEqual(store.find_checkin(item_id, day).done_at, first.done_at)
        self.assertEqual(engine.completion(store.get(plan.id), days=7), before, "完成率口径重启前后逐字段一致")

        # 取消打卡同样要落库：留着的话完成率会比取消前还高
        self.assertTrue(store.undo_checkin(item_id, day))
        engine2, store2 = self.reopen()
        self.assertEqual(store2.checkins_of(ELDER), [])
        self.assertEqual(engine2.completion(store2.get(plan.id), days=7)["done"], 0)

    def test_schema_is_idempotent_and_keeps_data(self) -> None:
        plan = self.engine.build_plan(ELDER)
        self.engine.submit(plan)
        self.engine.confirm(plan)
        self.store.checkin(plan, plan.items[0].id, ELDER, today_str())

        again = SqlPlanStore(self.db)  # 再跑一遍建表语句
        self.assertEqual(len(again.plans_of(ELDER)), 1, "重复建表不该清数据")
        self.assertEqual(again.active(ELDER).id, plan.id)
        self.assertEqual(len(again.checkins_of(ELDER)), 1)

    def test_other_elder_untouched(self) -> None:
        """一位老人的计划与打卡不能串到另一位身上"""
        mine = sample_plan()
        theirs = sample_plan(plan_id="plan_other", elder_id="e_other")
        self.store.add(mine)
        self.store.add(theirs)
        self.store.checkin(mine, mine.items[0].id, ELDER, today_str())

        _, store = self.reopen()
        self.assertEqual([plan.id for plan in store.plans_of(ELDER)], [mine.id])
        self.assertEqual([plan.id for plan in store.plans_of("e_other")], [theirs.id])
        self.assertEqual(len(store.checkins_of(ELDER)), 1)
        self.assertEqual(store.checkins_of("e_other"), [], "打卡要按老人分桶")

        self.assertTrue(store.undo_checkin(mine.items[0].id, today_str()))
        _, again = self.reopen()
        self.assertEqual(again.checkins_on(ELDER, today_str()), [])
        self.assertEqual(len(again.plans_of("e_other")), 1, "取消打卡不该动另一位老人的计划")


# ---------------------------------------------------------------- JSON 载荷表


class JsonPayloadTableTests(unittest.TestCase):
    """通用助手自己的口径：覆盖而不是追加、坏行只跳它自己、顺序靠写入序号"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.url = sqlite_url(self.tmp.name)
        self.db = open_database(self.url)
        self.table = JsonPayloadTable(self.db, "demo_rows", "owner_id")
        self.table.init_schema()

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_save_same_id_overwrites_in_place(self) -> None:
        self.table.save("r1", "o1", {"v": 1}, "2026-01-01T00:00:00+08:00")
        self.table.save("r1", "o1", {"v": 2}, "2026-01-01T00:00:01+08:00")
        rows = self.table.load()
        self.assertEqual(len(rows), 1, "同一个 id 是覆盖，不是追加")
        self.assertEqual(rows[0]["payload"], {"v": 2})
        self.assertEqual(rows[0]["created_at"], "2026-01-01T00:00:01+08:00")
        self.assertEqual(self.table.count(), 1)

    def test_load_filters_by_owner_and_delete_owner(self) -> None:
        self.table.save("r1", "o1", {"v": 1})
        self.table.save("r2", "o2", {"v": 2})
        self.table.save("r3", "o2", {"v": 3})
        self.assertEqual([row["id"] for row in self.table.load("o2")], ["r2", "r3"])
        self.assertEqual(self.table.count("o2"), 2)
        self.table.delete_owner("o2")
        self.assertEqual([row["id"] for row in self.table.load()], ["r1"])

    def test_broken_payload_row_is_skipped(self) -> None:
        self.table.save("r1", "o1", {"v": 1})
        ph = self.db.placeholder
        self.db.execute(
            "INSERT INTO demo_rows (id, owner_id, payload, created_at, seq) VALUES ("
            + ", ".join([ph] * 5)
            + ")",
            ("r2", "o1", "{这不是 JSON", "", 99),
        )
        self.assertEqual([row["id"] for row in self.table.load()], ["r1"], "坏行只跳过它自己，不影响别的")
        self.assertEqual(self.table.count(), 2, "坏行仍在库里（没被删），只是读不出来")

    def test_write_order_survives_reopen_even_with_identical_timestamps(self) -> None:
        stamp = "2026-01-05T08:00:00+08:00"
        for index in range(5):
            self.table.save("r%d" % index, "o1", {"v": index}, stamp)
        self.db.close()
        self.db = open_database(self.url)
        again = JsonPayloadTable(self.db, "demo_rows", "owner_id")
        again.init_schema()
        self.assertEqual([row["id"] for row in again.load()], ["r0", "r1", "r2", "r3", "r4"])
        # 序号要接着库里已有的最大值，不能从头开始（否则新写入的行会插到老行前面）
        again.save("r5", "o1", {"v": 5}, stamp)
        self.assertEqual([row["id"] for row in again.load()][-1], "r5")


# ---------------------------------------------------------------- 应用级


class AppWiringTests(unittest.TestCase):
    def test_memory_backend_keeps_in_memory_stores(self) -> None:
        app = create_app(
            settings=Settings(llm_provider="fake", scheduler_enabled=False),
            provider=FakeProvider(delay=0),
        )
        self.assertIsInstance(app.state.chat_service.store, ConversationStore)
        self.assertNotIsInstance(app.state.chat_service.store, SqlConversationStore)
        self.assertIsInstance(app.state.plan_engine.store, PlanStore)
        self.assertNotIsInstance(app.state.plan_engine.store, SqlPlanStore)
        health = TestClient(app).get("/healthz").json()
        self.assertFalse(health["storageDurable"], "默认不该落库（测试要互不污染）")
        self.assertIn("未落库", health["storage"])

    def test_sqlite_backend_wires_sql_stores(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                settings=Settings(llm_provider="fake", scheduler_enabled=False, database_url=sqlite_url(tmp)),
                provider=FakeProvider(delay=0),
            )
            try:
                self.assertIsInstance(app.state.chat_service.store, SqlConversationStore)
                self.assertIsInstance(app.state.plan_engine.store, SqlPlanStore)
                self.assertTrue(TestClient(app).get("/healthz").json()["storageDurable"])
            finally:
                app.state.database.close()

    def test_plan_and_conversation_survive_app_restart(self) -> None:
        """端到端（应用级）：走 API 生成 → 确认 → 重启 app → 今日计划还是同一份"""
        with tempfile.TemporaryDirectory() as tmp:
            url = sqlite_url(tmp)
            settings = Settings(llm_provider="fake", scheduler_enabled=False, database_url=url)

            app = create_app(settings=settings, provider=FakeProvider(delay=0))
            try:
                client = TestClient(app)
                draft = client.post(
                    "/v1/plans/draft",
                    json={"elderId": ELDER, "polish": False, "goal": "稳住日常起居"},
                )
                self.assertEqual(draft.status_code, 200, draft.text)
                plan_id = draft.json()["plan"]["id"]
                # 未确认时今日计划必须是空的（闸门在起作用，不是坏了）
                self.assertEqual(client.get("/v1/plans/today", params={"elderId": ELDER}).json()["total"], 0)

                confirmed = client.post(
                    "/v1/plans/confirm", json={"planId": plan_id, "actor": "女儿小丽"}
                )
                self.assertEqual(confirmed.status_code, 200, confirmed.text)
                today = client.get("/v1/plans/today", params={"elderId": ELDER}).json()
                self.assertEqual(today["planId"], plan_id)
                self.assertGreater(today["total"], 0)

                checkin = client.post(
                    "/v1/plans/checkin",
                    json={"elderId": ELDER, "planItemId": today["items"][0]["id"], "source": "elder"},
                )
                self.assertEqual(checkin.status_code, 200, checkin.text)
                self.assertEqual(checkin.json()["done"], True)
                after_checkin = client.get("/v1/plans/today", params={"elderId": ELDER}).json()
                self.assertEqual(after_checkin["done"], 1)

                sent = client.post(
                    "/v1/chat/send",
                    json={"conversationId": CONVERSATION, "elderId": ELDER, "text": "妈 今天吃什么"},
                )
                self.assertEqual(sent.status_code, 200, sent.text)
            finally:
                app.state.database.close()

            # 同一路径再建一个 app = 重启服务
            second = create_app(settings=settings, provider=FakeProvider(delay=0))
            try:
                client2 = TestClient(second)
                today2 = client2.get("/v1/plans/today", params={"elderId": ELDER}).json()
                self.assertEqual(today2["planId"], today["planId"], "重启后今日计划还是同一份")
                self.assertEqual(today2["total"], today["total"])
                self.assertEqual(today2["done"], after_checkin["done"], "打卡状态也要在")
                self.assertEqual(today2["status"], "active")
                self.assertEqual(today2["items"][0]["title"], today["items"][0]["title"])
                self.assertTrue(today2["items"][0]["basis"]["sourceName"], "依据字段要能从库里还原")

                history = client2.get(
                    "/v1/chat/history", params={"conversationId": CONVERSATION}
                ).json()["messages"]
                self.assertTrue(
                    any(m["role"] == ROLE_ELDER and m["text"] == "妈 今天吃什么" for m in history),
                    "会话消息也要在",
                )
                self.assertTrue(any(m["role"] == ROLE_AGENT and m["type"] == TYPE_TEXT for m in history))

                pending = client2.get("/v1/plans/history", params={"elderId": ELDER}).json()["plans"]
                self.assertEqual([item["id"] for item in pending], [plan_id], "计划历史也在")
            finally:
                second.state.database.close()


if __name__ == "__main__":
    unittest.main()
