"""
比邻AI · 会话与消息（支持两个账号共享一条会话）

## 为什么需要这一层

之前"聊天记录"只存端侧（`bl_chat_v1_<conversationId>`），所以：
  · 换设备就没了
  · 两个账号**没法互相发消息**（各自看到的都是自己的本地缓存）

现在按需求做**真后端同步**：消息落库、已读状态落库，
两个账号各自登录都能看到同一条会话与同一份消息。

## 数据模型

    Conversation  一条会话
        id            会话 id
        kind          'ai'（与智能体的会话）/ 'family'（与家人的共享会话）
        owner_id      ai 会话的归属账号；family 会话为空
        participants  参与账号 id 列表（family 会话是两个人）
        created_at / updated_at

    Message       一条消息
        id / conversation_id / sender_id / sender_name
        sender_role   'agent'（智能体）/ 'elder'（老人本人）
        text / created_at

    〖已读〗用游标而不是"每条消息一个已读标记"：
        每人每会话一个 `last_read_at`，比 N 条消息 N 个标记小得多，
        而且天然支持"批量已读"。未读数 = 该会话里
        「不是自己发的」且「created_at > last_read_at」的条数。

## id 约定（端侧据此判断会话类型，别随意改）

    ai:<accountId>                     与智能体的会话
    family:<小id>__<大id>              两个账号的共享会话（排序后拼，保证双向同一个 id）
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..models.message import now_iso

logger = logging.getLogger("bilin.messaging")

KIND_AI = "ai"
KIND_FAMILY = "family"

ROLE_AGENT = "agent"
ROLE_ELDER = "elder"

#: 智能体的发送者 id。
#:
#: **必须与账号 id 区分开**：智能体的消息原本用"当前账号的 id"发送，
#: 于是数据层分不清"这条是我发的"还是"智能体发给我的"，未读/已读怎么算都不对
#: （实测：老人问一句、智能体答一句，答的那句永远显示已读）。
#: 会话级生成，保证同一会话里智能体是同一个发送者。
AGENT_ID_PREFIX = "agent:"

# ── 家人绑定的状态（绑定要对方同意才生效，见 Binding 的说明）──────────
#: 已生效（老数据默认走这个，保证升级不影响既有家人关系）
STATUS_ACCEPTED = "accepted"
#: 等对方同意（此时还没开通共享会话，也看不到对方任何数据）
STATUS_PENDING = "pending"
#: 对方拒绝了
STATUS_REJECTED = "rejected"


def agent_sender_id(conversation_id: str) -> str:
    return AGENT_ID_PREFIX + str(conversation_id or "")


def is_agent_sender(sender_id: str) -> bool:
    return str(sender_id or "").startswith(AGENT_ID_PREFIX)


def ai_conversation_id(account_id: str) -> str:
    """某个账号与智能体的会话 id"""
    return KIND_AI + ":" + str(account_id or "")


def family_conversation_id(account_a: str, account_b: str) -> str:
    """两个账号的共享会话 id。

    **排序后拼接**：这样 A 找 B 与 B 找 A 得到同一个 id，
    不需要额外维护"谁先发起"的映射表。
    """
    pair = sorted([str(account_a or ""), str(account_b or "")])
    return KIND_FAMILY + ":" + pair[0] + "__" + pair[1]


def kind_of(conversation_id: str) -> str:
    return KIND_FAMILY if str(conversation_id or "").startswith(KIND_FAMILY + ":") else KIND_AI


def participants_of(conversation_id: str) -> list[str]:
    """从会话 id 反解出参与者（family 会话有两个）"""
    cid = str(conversation_id or "")
    if cid.startswith(KIND_FAMILY + ":"):
        body = cid[len(KIND_FAMILY) + 1:]
        return [part for part in body.split("__") if part]
    if cid.startswith(KIND_AI + ":"):
        return [cid[len(KIND_AI) + 1:]]
    return []


@dataclass
class Message:
    id: str
    conversation_id: str
    sender_id: str
    sender_name: str
    sender_role: str
    text: str
    created_at: str = field(default_factory=now_iso)
    #: 撤回时间（ISO）。为空表示没撤回。
    #: 为什么是标记而不是删除：家人会话是**双方共享**的一份记录，
    #: 直接删掉对方会看到"消息凭空消失"，与微信一致的做法是留一条"已撤回"。
    recalled_at: str = ""
    #: 引用的那条消息 id（为空表示没引用）
    quote_id: str = ""

    @property
    def recalled(self) -> bool:
        return bool(self.recalled_at)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversationId": self.conversation_id,
            "senderId": self.sender_id,
            "senderName": self.sender_name,
            "senderRole": self.sender_role,
            # 撤回后**不再下发正文**：前端只显示「你撤回了一条消息」，
            # 正文留在库里是为了审计，不是为了再展示
            "text": "" if self.recalled else self.text,
            "createdAt": self.created_at,
            "recalledAt": self.recalled_at,
            "quoteId": self.quote_id,
        }


@dataclass
class Conversation:
    id: str
    kind: str
    owner_id: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def participants(self) -> list[str]:
        return participants_of(self.id)

    def to_dict(self, *, unread: int = 0, last: Message | None = None) -> dict:
        data = {
            "id": self.id,
            "kind": self.kind,
            "ownerId": self.owner_id,
            "participants": self.participants(),
            "unread": unread,
            "updatedAt": self.updated_at,
            "createdAt": self.created_at,
        }
        if last is not None:
            data["lastMessage"] = last.to_dict()
        return data


@dataclass
class Binding:
    """两个账号的家人绑定关系。

    绑定的**副作用就是开通一条共享会话**（见 ensure_family_conversation）：
    老人"绑定家人"之后，两人之间就有一条能互发消息的会话。

    ## status：绑定要**对方同意**才生效

    需求：「绑定家人需要对方同意」。

      · `pending`  —— A 发起了邀请，等 B 确认。**此时还没开通共享会话**，
                       A 也看不到 B 的任何数据（`binding_with` 只认 accepted）
      · `accepted` —— B 同意了，绑定生效、共享会话开通
      · `rejected` —— B 拒绝了（保留记录，避免 A 反复重发）

    ⚠️ 字段默认值取 `accepted` 是**有意的**：绑定一旦生效就一直是生效态，
       老数据（升级前就绑好的）必须继续算"已绑定"，否则升级会让所有家人关系失效。
       只有新发起、且走邀请流程的才显式传 `pending`。
    """

    id: str
    account_id: str
    peer_id: str
    peer_number: str
    peer_name: str
    conversation_id: str
    created_at: str = field(default_factory=now_iso)
    status: str = STATUS_ACCEPTED
    #: 回应时间（同意/拒绝）；未回应为空
    responded_at: str = ""
    #: **谁发起的**邀请（账号 id）。空表示"立即生效的老式绑定"。
    #:
    #: ⚠️ 光有 status 不够：一条邀请会在两个人名下各存一条记录（双向），
    #: 两条都是 pending。没有这个字段就分不清"我发起的"和"别人发给我、
    #: 等我同意的"——实测 bug 就是**发起方也能把它当待办同意掉**。
    initiator: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "accountId": self.account_id,
            "peerId": self.peer_id,
            "peerNumber": self.peer_number,
            "peerName": self.peer_name,
            "conversationId": self.conversation_id,
            "createdAt": self.created_at,
            "status": self.status,
            "respondedAt": self.responded_at,
            "initiator": self.initiator,
            #: 这条是"我发起的邀请"还是"别人发给我、等我回应的"
            "outgoing": bool(self.initiator) and self.initiator == self.account_id,
        }


@dataclass
class MessagingStore:
    """会话 / 消息 / 已读游标 / 绑定（内存实现，接口与 SQL 版逐字一致）"""

    _conversations: dict[str, Conversation] = field(default_factory=dict)
    _messages: dict[str, list[Message]] = field(default_factory=dict)
    #: (conversation_id, account_id) -> 已读边界时间
    _read_cursor: dict[tuple[str, str], str] = field(default_factory=dict)
    #: account_id -> [Binding]（自己绑了谁）
    _bindings: dict[str, list[Binding]] = field(default_factory=dict)

    # ---------------------------------------------------------------- 会话

    def ensure_ai_conversation(self, account_id: str) -> Conversation:
        """每个账号与智能体有一条固定会话（不存在就建）"""
        cid = ai_conversation_id(account_id)
        existing = self._conversations.get(cid)
        if existing is not None:
            return existing
        conversation = Conversation(id=cid, kind=KIND_AI, owner_id=account_id)
        self._conversations[cid] = conversation
        self._messages.setdefault(cid, [])
        return conversation

    def ensure_family_conversation(self, account_a: str, account_b: str) -> Conversation:
        """两个账号的共享会话（不存在就建）。绑定家人时调用。"""
        cid = family_conversation_id(account_a, account_b)
        existing = self._conversations.get(cid)
        if existing is not None:
            return existing
        conversation = Conversation(id=cid, kind=KIND_FAMILY, owner_id="")
        self._conversations[cid] = conversation
        self._messages.setdefault(cid, [])
        return conversation

    def conversations_of(self, account_id: str) -> list[Conversation]:
        """某账号参与的全部会话（按最近更新倒序）"""
        wanted = str(account_id or "")
        out = [c for c in self._conversations.values() if wanted in c.participants()]
        out.sort(key=lambda c: (c.updated_at or "", c.id), reverse=True)
        return out

    def conversation(self, conversation_id: str) -> Conversation | None:
        return self._conversations.get(str(conversation_id or ""))

    # ---------------------------------------------------------------- 消息

    def messages_of(self, conversation_id: str, limit: int = 100) -> list[Message]:
        list_ = self._messages.get(str(conversation_id or ""), [])
        if limit and len(list_) > limit:
            return list_[-limit:]
        return list(list_)

    def last_message(self, conversation_id: str) -> Message | None:
        list_ = self._messages.get(str(conversation_id or ""), [])
        return list_[-1] if list_ else None

    def add_message(
        self,
        conversation_id: str,
        *,
        sender_id: str,
        sender_name: str,
        sender_role: str,
        text: str,
        created_at: str = "",
        quote_id: str = "",
    ) -> Message:
        cid = str(conversation_id or "")
        conversation = self._conversations.get(cid)
        if conversation is None:
            # 容错：没有会话就补建一个，避免"消息发到空气里"
            conversation = Conversation(id=cid, kind=kind_of(cid))
            self._conversations[cid] = conversation
            self._messages.setdefault(cid, [])

        moment = created_at or now_iso()
        # 同一秒内追加多条时 created_at 会相同，靠 id 里的随机后缀保证唯一；
        # 但排序必须稳定，所以这里在同一秒内把时间戳往后推 1 毫秒
        list_ = self._messages.setdefault(cid, [])
        if list_ and list_[-1].created_at >= moment:
            moment = _bump_millisecond(list_[-1].created_at)

        who = str(sender_id or "")
        # 智能体不是"某个账号"：它只该读到别人发给它的，不该有"我已读"这回事。
        # 这样它的消息对账号永远是"别人发的"，未读才算得出来。
        if not is_agent_sender(who):
            self._advance_cursor(cid, who, moment)

        message = Message(
            id="m_" + secrets.token_hex(8),
            conversation_id=cid,
            sender_id=who,
            sender_name=str(sender_name or ""),
            sender_role=sender_role if sender_role in (ROLE_AGENT, ROLE_ELDER) else ROLE_ELDER,
            text=str(text or ""),
            created_at=moment,
            quote_id=str(quote_id or ""),
        )
        list_.append(message)
        conversation.updated_at = moment
        return message

    # -------------------------------------------------------------- 撤回/删除

    def find_message(self, message_id: str) -> Message | None:
        """按 id 找一条消息（撤回/删除前要校验归属）。"""
        target = str(message_id or "")
        if not target:
            return None
        for list_ in self._messages.values():
            for message in list_:
                if message.id == target:
                    return message
        return None

    def recall_message(self, message_id: str, at: str) -> bool:
        """
        标记撤回。**保留正文**，只写 `recalled_at`。
        理由见 `Message.recalled_at`：家人会话是双方共享的一份记录，
        直接删掉对方会看到消息凭空消失；与微信一致的做法是留一条"已撤回"。
        """
        message = self.find_message(message_id)
        if message is None:
            return False
        message.recalled_at = at or now_iso()
        return True

    def delete_message(self, message_id: str) -> bool:
        """物理删除（"删除"用，非撤回）。"""
        target = str(message_id or "")
        for cid, list_ in self._messages.items():
            for index, message in enumerate(list_):
                if message.id == target:
                    list_.pop(index)
                    return True
        return False

    # ---------------------------------------------------------------- 已读

    def read_cursor(self, conversation_id: str, account_id: str) -> str:
        return self._read_cursor.get((str(conversation_id or ""), str(account_id or "")), "")

    def mark_read(self, conversation_id: str, account_id: str, at: str = "") -> int:
        """老人打开会话，把已读推到 `at`（默认"现在"）。

        @returns 本次从"未读"变成"已读"的条数
        """
        return self._advance_cursor(conversation_id, account_id, at or now_iso())

    def _advance_cursor(self, conversation_id: str, account_id: str, moment: str) -> int:
        """把 (会话, 账号) 的已读边界推到 moment（只前进，不后退）"""
        cid = str(conversation_id or "")
        who = str(account_id or "")
        if not who or is_agent_sender(who):
            return 0
        previous = self.read_cursor(cid, who)
        if previous and previous >= moment:
            return 0
        newly = 0
        for message in self._messages.get(cid, []):
            if message.sender_id == who:
                continue
            if previous and message.created_at <= previous:
                continue
            if message.created_at <= moment:
                newly += 1
        self._read_cursor[(cid, who)] = moment
        return newly

    def unread_count(self, conversation_id: str, account_id: str) -> int:
        """未读数 = 不是自己发的 且 晚于自己已读边界的条数"""
        cid = str(conversation_id or "")
        who = str(account_id or "")
        cursor = self.read_cursor(cid, who)
        count = 0
        for message in self._messages.get(cid, []):
            if message.sender_id == who:
                continue
            if not cursor or message.created_at > cursor:
                count += 1
        return count

    def total_unread(self, account_id: str) -> int:
        return sum(self.unread_count(c.id, account_id) for c in self.conversations_of(account_id))

    # ---------------------------------------------------------------- 绑定

    def bindings_of(self, account_id: str) -> list[Binding]:
        return list(self._bindings.get(str(account_id or ""), []))

    def binding_with(self, account_id: str, peer_id: str) -> Binding | None:
        """
        取"已生效"的绑定。

        ⚠️ **只认 `accepted`**：`pending`（等对方同意）与 `rejected` 都不算绑定。
        这是授权链的关键——家人查看管理、代回等都靠它，所以"待同意"期间
        对方看不到你的任何数据。
        """
        for item in self.bindings_of(account_id):
            if item.peer_id == peer_id and item.status == STATUS_ACCEPTED:
                return item
        return None

    def any_binding_with(self, account_id: str, peer_id: str) -> Binding | None:
        """取任意状态的绑定（含 pending / rejected）。用于"是否重复发起邀请"的判断。"""
        for item in self.bindings_of(account_id):
            if item.peer_id == peer_id:
                return item
        return None

    def pending_invites_for(self, account_id: str) -> list[Binding]:
        """
        **别人发给我、等我同意**的邀请。

        ⚠️ 必须排除"我自己发起的"：双向记录两条都是 pending，
        只看 status 会把发起方自己的邀请也算进来（实测 bug）。
        """
        me = str(account_id or "")
        return [
            b for b in self.bindings_of(me)
            if b.status == STATUS_PENDING and b.initiator and b.initiator != me
        ]

    def respond_invite(self, account_id: str, peer_id: str, accept: bool) -> Binding | None:
        """
        回应一条邀请：同意 / 拒绝。

        两边都要改状态（双向记录），否则会出现"我这边显示已绑定、他那边还是待同意"。

        ⚠️ **同意时才开通共享会话**：邀请期间故意没有会话（没同意之前不该有一条
        能互发消息的通道）。这一段原来只写在 SQL 实现里，基类漏了 ——
        结果是内存库下同意完 `conversation_id` 还是空的（测试用内存库，直接暴露）。
        """
        me = str(account_id or "")
        peer = str(peer_id or "")
        moment = now_iso()
        status = STATUS_ACCEPTED if accept else STATUS_REJECTED

        # 先开通会话（同意时），再统一改状态
        conversation_id = ""
        if accept:
            existing = None
            for item in self._bindings.get(me, []):
                if item.peer_id == peer and item.status == STATUS_PENDING:
                    existing = item
                    break
            if existing is not None and not existing.conversation_id:
                conversation_id = self.ensure_family_conversation(me, peer).id

        found = None
        for owner, other in ((me, peer), (peer, me)):
            for item in self._bindings.get(owner, []):
                if item.peer_id == other and item.status == STATUS_PENDING:
                    item.status = status
                    item.responded_at = moment
                    if conversation_id and not item.conversation_id:
                        item.conversation_id = conversation_id
                    if owner == me:
                        found = item
        return found

    def bind(
        self,
        *,
        account_id: str,
        account_number: str,
        account_name: str,
        peer_id: str,
        peer_number: str,
        peer_name: str,
        status: str = STATUS_ACCEPTED,
    ) -> Binding:
        """绑定家人。

        **双向**：A 绑 B 之后，B 那边也能看到 A（否则只有一方能发起消息）。
        幂等：重复绑定返回已有那条，不产生重复记录。

        `status=accepted`（默认）立即生效；传 `pending` 表示"发起邀请、等对方同意"，
        此时**不开通共享会话**，双方也互相看不到数据（见 Binding 的说明）。
        """
        me = str(account_id or "")
        peer = str(peer_id or "")
        existing = self.any_binding_with(me, peer)
        if existing is not None:
            # 双方可能改了名字，顺手刷新两边
            existing.peer_name = peer_name or existing.peer_name
            existing.peer_number = peer_number or existing.peer_number
            self.patch_reverse_binding(me, peer, peer_number=account_number, peer_name=account_name)
            return existing

        moment = now_iso()
        # 待同意的邀请**不开通共享会话**：没同意之前不该有一条能互发消息的通道
        conversation_id = ""
        if status == STATUS_ACCEPTED:
            conversation_id = self.ensure_family_conversation(me, peer).id

        forward = Binding(
            id="b_" + secrets.token_hex(8),
            account_id=me,
            peer_id=peer,
            peer_number=peer_number,
            peer_name=peer_name,
            conversation_id=conversation_id,
            created_at=moment,
            status=status,
            # 谁发起的：只有 pending 的邀请才有意义（立即生效的绑定不需要区分）
            initiator=me if status == STATUS_PENDING else "",
        )
        self._bindings.setdefault(me, []).append(forward)
        # 反向那条用的是**我**的编号与名字（对方看我要看到我的信息）
        self._bindings.setdefault(peer, []).append(
            Binding(
                id="b_" + secrets.token_hex(8),
                account_id=peer,
                peer_id=me,
                peer_number=account_number,
                peer_name=account_name,
                conversation_id=conversation_id,
                created_at=moment,
                status=status,
                initiator=me if status == STATUS_PENDING else "",
            )
        )
        return forward

    def unbind(self, account_id: str, peer_id: str) -> bool:
        me = str(account_id or "")
        peer = str(peer_id or "")
        before = len(self.bindings_of(me))
        self._bindings[me] = [b for b in self.bindings_of(me) if b.peer_id != peer]
        self._bindings[peer] = [b for b in self.bindings_of(peer) if b.peer_id != me]
        return len(self._bindings[me]) != before

    def patch_reverse_binding(self, account_id: str, peer_id: str, *, peer_number: str, peer_name: str) -> None:
        """刷新反向绑定里存的"我的"显示信息"""
        for item in self._bindings.get(str(peer_id or ""), []):
            if item.peer_id == str(account_id or ""):
                item.peer_number = peer_number or item.peer_number
                item.peer_name = peer_name or item.peer_name


def _bump_millisecond(iso: str) -> str:
    """把 ISO 时间往后推 1 毫秒（同一秒内多条消息时保持顺序稳定）"""
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return now_iso()
    return (moment + timedelta(milliseconds=1)).isoformat(timespec="milliseconds")
