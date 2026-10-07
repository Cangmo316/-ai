"""
比邻AI · 账号密码的哈希与校验

**为什么不能存明文**：这套账号以后要放测试机甚至线上，密码落库必须是哈希。
原型阶段也不能省——明文密码一旦写进备份/日志就收不回来了。

**为什么用标准库 PBKDF2 而不是 bcrypt/argon2**：
仓库约定「优先开源免费、能不加依赖就不加」（见 requirements.txt 的说明），
而 `hashlib.pbkdf2_hmac` 是标准库、无需编译、跨平台一致。
对"老人陪伴 App 的账号"这个威胁模型足够；真要上大规模生产再换 argon2 也只是换本文件。

存储格式（单字段自描述，便于以后换算法时**旧密码仍可校验**）：

    pbkdf2_sha256$<迭代次数>$<盐 hex>$<派生密钥 hex>

校验时按字符串里带的算法和迭代次数重算，所以调高迭代次数不会让老账号登不上。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
# 迭代次数：2026 年的手机端 Python 侧约几十毫秒，登录体感无感、暴力破解代价够高
ITERATIONS = 200_000
SALT_BYTES = 16
KEY_BYTES = 32

# 密码规则：8–16 位，只能是数字或字母（与端侧 common/password.js 保持一致）
PASSWORD_MIN = 8
PASSWORD_MAX = 16


def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    """把明文密码hash成可落库的字符串"""
    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, KEY_BYTES)
    return "$".join([ALGORITHM, str(iterations), salt.hex(), derived.hex()])


def verify_password(password: str, stored: str) -> bool:
    """校验明文密码与落库字符串是否匹配。

    任何格式异常都返回 False（而不是抛异常）：一条坏记录不该让登录接口 500。
    """
    if not stored or not password:
        return False
    parts = str(stored).split("$")
    if len(parts) != 4 or parts[0] != ALGORITHM:
        return False
    try:
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected = bytes.fromhex(parts[3])
    except (ValueError, TypeError):
        return False
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, len(expected))
    # compare_digest：定长比较，避免用耗时差异反推密码
    return hmac.compare_digest(derived, expected)


def password_problem(password: str) -> str:
    """校验密码是否符合规则。

    @returns 空串 = 合法；否则返回一句可直接给老人看的说明
    """
    value = "" if password is None else str(password)
    if not value:
        return "请输入密码"
    if len(value) < PASSWORD_MIN:
        return "密码至少 " + str(PASSWORD_MIN) + " 位"
    if len(value) > PASSWORD_MAX:
        return "密码最多 " + str(PASSWORD_MAX) + " 位"
    if not value.isascii() or not value.isalnum():
        return "密码只能用数字或字母，不能有空格或符号"
    return ""
