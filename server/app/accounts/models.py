"""
比邻AI · 账号（账号名称 + 密码 + 8 位编号）

**关于编号**：注册成功后给账号分配一个 **8 位数字编号**，从 `00000000` 开始，
每注册一个 +1（`00000001`、`00000002`…）。编号是账号对外的身份标识
（「我的」页显示 `ID:00000000`）。

**为什么编号分配一定要落库**：编号必须**永不复用**。如果只在内存里自增，
服务重启后计数器归零，下一个新账号就会拿到一个已被占用的编号——
两个账号撞号，而编号是要显示给用户、甚至用来找人的。
所以已用到的最大编号存库，分配新编号时从库里续上（见 `SqlAccountStore.next_number`）。

**编号格式**：固定 8 位十进制、左补零。超过 8 位（99999999 之后）会报错而不是
静默变成 9 位——8 位是端侧 UI 的既定长度，悄悄变长会让界面上的 `ID:` 长出一截。

编号给的是**第 n 个账号**（`00000000` 是第 1 个），所以：
    编号 = 已发出的编号数（从 0 起）
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field

from .password import hash_password, verify_password

logger = logging.getLogger("bilin.accounts")

#: 编号长度与起点（按需求：8 位数字，从 00000000 开始）
NUMBER_WIDTH = 8
FIRST_NUMBER = 0
#: 8 位能表示到的最大编号
MAX_NUMBER = 10 ** NUMBER_WIDTH - 1

#: 测试开发账号（按需求写入）：编号固定 00000000
DEV_ACCOUNT_NAME = "比邻AI"
DEV_ACCOUNT_PASSWORD = "BILINAI0316"
DEV_ACCOUNT_NUMBER = "00000000"

#: 会话 token 的有效期（秒）。老人端不做后台登出，给足 30 天。
TOKEN_TTL_SECONDS = 30 * 24 * 3600

AVATAR_PRESETS = (
    "grandma",
    "grandpa",
    "daughter",
    "son",
    "nurse",
    "doctor",
)


def format_number(value: int) -> str:
    """把整数编号格式化成 8 位字符串（左补零）"""
    if value < FIRST_NUMBER or value > MAX_NUMBER:
        raise ValueError("账号编号超出 " + str(NUMBER_WIDTH) + " 位范围：" + str(value))
    return str(value).zfill(NUMBER_WIDTH)


def new_token() -> str:
    return secrets.token_hex(16)


@dataclass
class Account:
    """一个账号。`number` 是 8 位字符串编号，落库与对外都用它。"""

    id: str
    name: str
    number: str
    password_hash: str
    avatar: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        """对外表示。

        ⚠️ **绝不包含 password_hash**：这个 dict 会直接进 HTTP 响应、
        日志和前端缓存，密码哈希一旦漏出去就等于把账号送人。
        """
        return {
            "id": self.id,
            "name": self.name,
            "number": self.number,
            "avatar": self.avatar,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }

    def check_password(self, password: str) -> bool:
        return verify_password(password, self.password_hash)


@dataclass
class Session:
    """一次登录签发的会话。token 是随机串，服务端只存它的摘要。"""

    token: str
    account_id: str
    created_at: str = ""
    expires_at: str = ""


@dataclass
class AccountStore:
    """账号（内存实现）。

    ⚠️ 编号分配是这类最要紧的一处：内存实现只在**单进程 + 不重启**的前提下正确。
    真跑起来必须用 `SqlAccountStore`（见本文件末尾的说明），
    这也是 `create_app` 里按 `database.enabled` 二选一的原因。
    """

    _by_id: dict[str, Account] = field(default_factory=dict)
    _by_name: dict[str, Account] = field(default_factory=dict)
    _sessions: dict[str, Session] = field(default_factory=dict)
    #: 已发出的编号数 = 下一个新账号的编号
    _issued: int = 0

    # ---------------------------------------------------------------- 编号

    def peek_next_number(self) -> str:
        """下一个会被分配到的编号（不占用），给测试与界面预告用"""
        return format_number(self._issued)

    def issued_count(self) -> int:
        """已发出的编号数（= 下一个新账号的编号）。路由用它判断编号是否用满。"""
        return self._issued

    def allocate_number(self) -> str:
        """占用下一个编号。**只增不减、绝不复用。**"""
        number = format_number(self._issued)
        self._issued += 1
        return number

    # ---------------------------------------------------------------- 读

    def by_id(self, account_id: str) -> Account | None:
        return self._by_id.get(str(account_id or ""))

    def by_number(self, number: str) -> Account | None:
        """按 8 位编号查账号（编号唯一，见 SqlAccountStore 的唯一索引）。

        "绑定家人"要靠它把老人填的编号认到具体的人。
        编号是纯数字，这里统一按左补零后的形式比，避免 '0' 与 '00000000' 认不出来。
        """
        wanted = str(number or "").strip()
        if not wanted.isdigit():
            return None
        try:
            padded = format_number(int(wanted))
        except ValueError:
            return None
        for account in self._by_id.values():
            if account.number == padded:
                return account
        return None

    def by_name(self, name: str) -> Account | None:
        # 账号名称不区分大小写：老人记不住有没有大写，
        # 「bilinai」和「BiLinAI」应当是同一个人
        return self._by_name.get(self._name_key(name))

    def count(self) -> int:
        return len(self._by_id)

    @staticmethod
    def _name_key(name: str) -> str:
        return str(name or "").strip().casefold()

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
        """建账号。`number` 只在写入固定编号的测试账号时传入（见 ensure_dev_account）。"""
        clean = str(name or "").strip()
        if self.by_name(clean) is not None:
            raise ValueError("duplicate_name")
        if number is None:
            number = self.allocate_number()
        else:
            # 显式指定编号（测试账号）：把计数器推到它之后，避免后续撞号
            self._issued = max(self._issued, int(number) + 1)
        account = Account(
            id="a_" + secrets.token_hex(8),
            name=clean,
            number=number,
            password_hash=hash_password(password),
            avatar=avatar,
            created_at=created_at,
            updated_at=created_at,
        )
        self._by_id[account.id] = account
        self._by_name[self._name_key(clean)] = account
        return account

    def save(self, account: Account) -> None:
        self._by_id[account.id] = account
        self._by_name[self._name_key(account.name)] = account

    # ---------------------------------------------------------------- 会话

    def issue_session(self, account: Account, *, created_at: str = "", expires_at: str = "") -> Session:
        session = Session(
            token=new_token(),
            account_id=account.id,
            created_at=created_at,
            expires_at=expires_at,
        )
        self._sessions[session.token] = session
        return session

    def session(self, token: str) -> Session | None:
        return self._sessions.get(str(token or "").strip())

    def revoke_session(self, token: str) -> bool:
        return self._sessions.pop(str(token or "").strip(), None) is not None


def ensure_dev_account(store: AccountStore, *, created_at: str = "") -> Account | None:
    """写入测试开发账号（比邻AI / BILINAI0316，编号 00000000）。

    **幂等**：账号已存在就原样返回，不覆盖密码——否则每次重启都会把
    测试人员改过的密码重置回去，排查问题时会很困惑。
    """
    existing = store.by_name(DEV_ACCOUNT_NAME)
    if existing is not None:
        return existing
    account = store.create(
        DEV_ACCOUNT_NAME,
        DEV_ACCOUNT_PASSWORD,
        number=DEV_ACCOUNT_NUMBER,
        created_at=created_at,
    )
    logger.info(
        "已写入测试开发账号：%s（编号 %s）", account.name, account.number
    )
    return account
