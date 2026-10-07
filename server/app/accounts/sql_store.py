"""
比邻AI · 账号的落库实现（写穿透 + 启动加载）

沿用仓库既有的「缓存 + 写穿透」范式（见 `app/memory/sql_store.py` 的说明）：
读走内存、写同时落库，所以重启不丢，且读路径不受数据库延迟影响。

**本文件存在的主要理由是编号**：编号绝不能复用（见 `models.py` 的说明），
而"下一个编号是多少"必须跨重启确定——所以编号在库里用一张单行表记录，
分配时先 `UPDATE ... SET issued = issued + 1`，再把自增后的值读回来。
这样即使将来上了多 worker，编号也不会撞（SQLite 下由 `db.py` 的锁串行化）。
"""

from __future__ import annotations

import logging

from ..storage.db import Database
from .models import (
    MAX_NUMBER,
    Account,
    AccountStore,
    Session,
    format_number,
)

logger = logging.getLogger("bilin.accounts")

#: 编号计数器只有一行，用固定主键
COUNTER_KEY = "account_number"

_COLUMNS = "id, name, number, name_key, password_hash, avatar, created_at, updated_at"

SCHEMA_TEMPLATE = [
    """
    CREATE TABLE IF NOT EXISTS accounts (
        id             TEXT PRIMARY KEY,
        name           TEXT NOT NULL,
        number         TEXT NOT NULL,
        name_key       TEXT NOT NULL,
        password_hash  TEXT NOT NULL,
        avatar         TEXT NOT NULL DEFAULT '',
        created_at     TEXT NOT NULL DEFAULT '',
        updated_at     TEXT NOT NULL DEFAULT ''
    )
    """,
    # 账号名称（大小写不敏感）唯一：重名在应用层拦，这里再兜一层
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_name_key ON accounts (name_key)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_number ON accounts (number)",
    """
    CREATE TABLE IF NOT EXISTS account_sessions (
        token       TEXT PRIMARY KEY,
        account_id  TEXT NOT NULL,
        created_at  TEXT NOT NULL DEFAULT '',
        expires_at  TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_account_sessions_account ON account_sessions (account_id)",
    """
    CREATE TABLE IF NOT EXISTS account_counters (
        key     TEXT PRIMARY KEY,
        issued  INTEGER NOT NULL DEFAULT 0
    )
    """,
]


class SqlAccountStore(AccountStore):
    """账号的落库实现：内存里放一份，写操作同时落库。"""

    def __init__(self, db: Database) -> None:
        super().__init__()
        self.db = db

    # ---------------------------------------------------------------- 启动

    def init_schema(self) -> None:
        if not self.db.enabled:
            return
        self.db.init_schema(SCHEMA_TEMPLATE)

    def load(self) -> int:
        """把库里的账号读进内存，并把编号计数器续上。返回加载到的账号数。"""
        if not self.db.enabled:
            return 0
        for row in self.db.query("SELECT " + _COLUMNS + " FROM accounts"):
            account = Account(
                id=row["id"],
                name=row["name"],
                number=row["number"],
                password_hash=row["password_hash"],
                avatar=row.get("avatar") or "",
                created_at=row.get("created_at") or "",
                updated_at=row.get("updated_at") or "",
            )
            self._by_id[account.id] = account
            self._by_name[self._name_key(account.name)] = account

        # 计数器续上：取「库里的计数」与「已有账号的最大编号 + 1」的较大者。
        # 两个都要看，是因为可能出现"计数表丢了但账号还在"的情况
        # （手工改库、或早期版本没写计数器）——那时若只看计数表就会从 0 重发。
        issued = self._stored_issued()
        highest = 0
        for account in self._by_id.values():
            try:
                highest = max(highest, int(account.number) + 1)
            except (TypeError, ValueError):
                continue
        self._issued = max(issued, highest)

        for row in self.db.query("SELECT token, account_id, created_at, expires_at FROM account_sessions"):
            self._sessions[row["token"]] = Session(
                token=row["token"],
                account_id=row["account_id"],
                created_at=row.get("created_at") or "",
                expires_at=row.get("expires_at") or "",
            )
        return len(self._by_id)

    def _stored_issued(self) -> int:
        rows = self.db.query(
            "SELECT issued FROM account_counters WHERE key = " + self.db.placeholder,
            (COUNTER_KEY,),
        )
        if not rows:
            return 0
        try:
            return int(rows[0]["issued"])
        except (TypeError, ValueError):
            return 0

    def _write_issued(self, issued: int) -> None:
        ph = self.db.placeholder
        # ON CONFLICT 写法 SQLite 与 PostgreSQL 一致，不用分支
        self.db.execute(
            "INSERT INTO account_counters (key, issued) VALUES (" + ph + ", " + ph + ") "
            "ON CONFLICT (key) DO UPDATE SET issued=EXCLUDED.issued",
            (COUNTER_KEY, issued),
        )

    # ---------------------------------------------------------------- 编号

    def allocate_number(self) -> str:
        """落库式分配编号：先写库、再返回，保证跨重启不复用。"""
        if not self.db.enabled:
            return super().allocate_number()
        assert_number_in_range(self._issued)
        number = super().allocate_number()  # 内存计数器先推进
        self._write_issued(self._issued)
        return number

    # ---------------------------------------------------------------- 写

    def create(
        self,
        name: str,
        password: str,
        *,
        avatar: str = "",
        number: str | None = None,
        created_at: str = "",
    ) -> Account:
        account = super().create(
            name, password, avatar=avatar, number=number, created_at=created_at
        )
        self._insert(account)
        # 显式指定编号（测试账号）时也要把计数器写库，否则重启后会重发 00000000
        self._write_issued(self._issued)
        return account

    def _insert(self, account: Account) -> None:
        if not self.db.enabled:
            return
        ph = self.db.placeholder
        self.db.execute(
            "INSERT INTO accounts (" + _COLUMNS + ") VALUES ("
            + ", ".join([ph] * 8) + ")",
            (
                account.id,
                account.name,
                account.number,
                self._name_key(account.name),
                account.password_hash,
                account.avatar,
                account.created_at,
                account.updated_at,
            ),
        )

    def save(self, account: Account) -> None:
        super().save(account)
        if not self.db.enabled:
            return
        ph = self.db.placeholder
        self.db.execute(
            "UPDATE accounts SET name=" + ph + ", avatar=" + ph + ", updated_at=" + ph
            + " WHERE id=" + ph,
            (account.name, account.avatar, account.updated_at, account.id),
        )

    # ---------------------------------------------------------------- 会话

    def issue_session(self, account: Account, *, created_at: str = "", expires_at: str = "") -> Session:
        session = super().issue_session(account, created_at=created_at, expires_at=expires_at)
        if not self.db.enabled:
            return session
        ph = self.db.placeholder
        self.db.execute(
            "INSERT INTO account_sessions (token, account_id, created_at, expires_at) VALUES ("
            + ", ".join([ph] * 4) + ")",
            (session.token, session.account_id, session.created_at, session.expires_at),
        )
        return session

    def revoke_session(self, token: str) -> bool:
        removed = super().revoke_session(token)
        if removed and self.db.enabled:
            self.db.execute(
                "DELETE FROM account_sessions WHERE token = " + self.db.placeholder,
                (str(token or "").strip(),),
            )
        return removed


def assert_number_in_range(issued: int) -> None:
    """越界尽早报出来，而不是悄悄给出 9 位编号（见 models.py 的说明）"""
    if issued > MAX_NUMBER:
        raise ValueError(
            "账号编号已用满 " + str(len(format_number(0))) + " 位（上限 " + format_number(MAX_NUMBER) + "）"
        )
