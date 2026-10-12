"""比邻AI · 语音数据的**安全处理**：multipart 解析 + 临时文件脱敏

本模块把两条硬约束固化成代码，而不是只写在注释里：

## 一、不引入新依赖（仓库约定"只装四个包"）

FastAPI 的 `request.form()` 需要 `python-multipart`，本仓库不装它。
改用**标准库 `email`** 把 body 当 MIME 文档解析 —— 实测**二进制逐字节保真**
（`_probe_multipart.py`：1039 字节进、1039 字节出，含 0x00/0xFF/CRLF 等易踩字节）。
⚠️ 关键：**只解析 body**。把整个 HTTP 请求（含请求行）交给 email 会被当成单一部分。

## 二、老人语音是敏感信息（PIPL），必须"用过即焚"

语音数据的安全不是靠"记得删"，而是靠结构：

| 措施 | 实现 |
|---|---|
| **绝不落盘持久化** | 只写系统临时目录，且用 `mkdtemp` 生成**唯一目录** |
| **用完立刻删** | `try/finally` 保证**无论成功/失败/超时都删**（含目录本身） |
| **目录权限收紧** | POSIX 下 `chmod 0700`，避免同机其他用户读到录音 |
| **绝不写日志** | 只记字节数、时长、引擎名；**不记音频内容、不记识别出的文本** |
| **不留副本** | 不复制、不缓存、不重命名留档；转写结果只经响应返回 |
| **拒绝超长录音** | 端点侧限制体积，避免大文件长时间停留 |
| **引擎不打印文本** | 命令模板建议带 `--no-prints`（whisper.cpp），防止识别文本进日志 |

> ⚠️ 一个容易忽略的点：**很多 ASR 引擎会把识别结果打到日志**（whisper.cpp 默认如此），
> 那样老人的话就会留在系统日志里。所以 `--no-prints` **不是可选项而是隐私要求**，
> 本模块的 `describe()` 会把"命令模板里是否有抑制打印的开关"报出来以便核查。
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import tempfile
import uuid
from email.parser import BytesParser
from email.policy import default as default_policy

logger = logging.getLogger(__name__)

# 单次录音体积上限：60 秒 16bit/16kHz 单声道 ≈ 1.9MB，留足余量
MAX_UPLOAD_BYTES = 8 * 1024 * 1024

# 需要抑制引擎打印的参数（不同引擎各写各的；用于 describe() 体检）
_PRINT_SUPPRESS_FLAGS = ("--no-prints", "-np", "--no-print", "--quiet", "-q")


def parse_multipart(body: bytes, content_type: str) -> tuple[str, str, bytes] | None:
    """解析 `multipart/form-data`，返回 (文件名, 内容类型, 字节)；失败返回 None。

    用标准库 email：不引入 `python-multipart` 依赖（仓库只装四个包）。
    """
    if not body:
        return None
    boundary = _boundary_of(content_type)
    if not boundary:
        return None
    document = (
        ("Content-Type: multipart/form-data; boundary=%s\r\n" % boundary).encode()
        + b"MIME-Version: 1.0\r\n\r\n"
        + body
    )
    try:
        message = BytesParser(policy=default_policy).parsebytes(document)
    except Exception:  # noqa: BLE001 —— 畸形请求不该让服务 500
        logger.info("multipart 解析失败（畸形请求）")
        return None
    if not message.is_multipart():
        return None
    for part in message.iter_parts():
        disposition = part.get_content_disposition()
        if disposition != "form-data":
            continue
        name = part.get_param("name", header="content-disposition")
        # 只认名为 file 的部件（契约固定），不看顺序，避免客户端字段顺序变化导致错位
        if name != "file":
            continue
        payload = part.get_payload(decode=True) or b""
        filename = part.get_filename() or ""
        return filename, part.get_content_type(), payload
    return None


def _boundary_of(content_type: str) -> str:
    """从 Content-Type 里取 boundary（大小写不敏感，支持带引号）。"""
    text = content_type or ""
    lowered = text.lower()
    index = lowered.find("boundary=")
    if index < 0:
        return ""
    value = text[index + len("boundary="):].strip()
    # 去掉后续参数（如 `; charset=...`）
    for separator in (";", ","):
        cut = value.find(separator)
        if cut >= 0:
            value = value[:cut]
    return value.strip().strip('"')


class TempAudio:
    """录音的**临时落点**：进入时创建、离开时**无条件删除**。

    用法::

        with TempAudio(data, ".wav") as path:
            result = await provider.transcribe(path)

    `finally` 里连目录一起删 —— 不能只删文件，否则临时目录会一直堆积，
    而且目录名可能成为"某次录音存在过"的痕迹。
    """

    def __init__(self, data: bytes, suffix: str):
        self.data = data
        self.suffix = suffix if suffix.startswith(".") else "." + suffix
        self.dir = ""
        self.path = ""

    def __enter__(self) -> str:
        # 唯一目录名：不用可预测的名字（避免同机猜测/竞争）
        self.dir = tempfile.mkdtemp(prefix="bilin-asr-" + uuid.uuid4().hex[:8] + "-")
        # 权限收紧：POSIX 下 0700，只有本进程可读写。
        # （Windows 无 POSIX 位，chmod 基本无效，但那里靠"唯一目录 + 立即删除"。）
        try:
            os.chmod(self.dir, stat.S_IRWXU)
        except OSError:
            pass
        self.path = os.path.join(self.dir, "input" + self.suffix)
        # 用底层 open + 0o600 创建，避免"先按默认权限建好再改"的窗口
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        handle = os.open(self.path, flags, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(handle, "wb") as stream:
            stream.write(self.data)
        return self.path

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.destroy()
        return False        # 不吞异常

    def destroy(self) -> None:
        """删除录音与所属目录。**幂等**，失败也不抛（清理不能反过来影响请求）。"""
        if self.dir and os.path.isdir(self.dir):
            shutil.rmtree(self.dir, ignore_errors=True)
        self.path = ""
        self.dir = ""


def command_suppresses_prints(template: str) -> bool:
    """命令模板里是否带了"抑制引擎打印"的开关。

    为什么要体检它：whisper.cpp 默认会把**识别文本**打进日志，
    那样老人的原话就留在系统日志里 —— 属于隐私泄漏。所以这不是"可选优化"。
    """
    text = (template or "").lower()
    return any(flag in text for flag in _PRINT_SUPPRESS_FLAGS)


def privacy_report() -> dict:
    """给 `/healthz` 用：把语音数据的处理方式**如实报出来**，便于部署方核查。"""
    from . import gateway as asr_gateway
    template = os.environ.get("BILIN_ASR_CMD") or ""
    provider = asr_gateway.build_asr_provider()
    info = {
        "voiceDataRetention": "仅内存/临时文件，用完立即删除（不落盘持久化、不进日志）",
        "maxUploadBytes": MAX_UPLOAD_BYTES,
        "logsTranscript": False,
    }
    # 命令式引擎：核查是否抑制了引擎自身的打印（否则识别文本会进日志）
    if template:
        info["enginePrintsSuppressed"] = command_suppresses_prints(template)
        if not info["enginePrintsSuppressed"]:
            info["warning"] = ("命令模板未带 --no-prints/--quiet，"
                               "whisper.cpp 默认会把识别文本打进日志（老人原话会留存）")
    elif type(provider).__name__ == "HttpAsrProvider":
        # HTTP 引擎的打印行为在对方进程里，本进程无法保证 —— 如实说明
        info["enginePrintsSuppressed"] = None
        info["warning"] = "HTTP 引擎的日志行为由对端决定，请自行确认对端不留存音频与文本"
    return info
