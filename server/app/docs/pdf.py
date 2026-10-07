"""
比邻AI · 读医院给的 PDF（零依赖）

## 为什么自己解析而不是装 pypdf

仓库约定「优先开源免费、能不加就不加」（见 requirements.txt），
而"从医院 PDF 里取文字"这件事范围很窄：只要认得出文本流、按顺序拼出来即可。
为此拉一个带二进制依赖的库不划算。

**能做到什么**：FlateDecode（以及无压缩）文本流、`Tj`/`TJ`/`'`/`"` 文本操作符、
ToUnicode CMap 的反查、UTF-16BE 字符串。
**做不到什么**（会明确告诉调用方"读不出文字"）：
  · 扫描件（整页是图片，没有文本层）——这类要靠识图，见 vision 模块
  · 特殊编码的子集字体且没有 ToUnicode（数字被映射成私用区码位）
  · 加密 PDF（`/Encrypt`）

**做不到时必须如实说**，不能返回一堆乱码——老人会拿这堆字当病历内容。
所以 `extract_text()` 返回 (文本, 诊断信息)，诊断信息里写清楚为什么读不出。
"""

from __future__ import annotations

import logging
import re
import zlib
from dataclasses import dataclass, field

logger = logging.getLogger("bilin.docs.pdf")

#: 抽出来的正文上限（病历可能很长，但进 prompt 只要摘要级的信息量）
MAX_TEXT = 20000


@dataclass
class PdfResult:
    text: str = ""
    pages: int = 0
    #: 是不是扫描件（整页图片、没有文本层）——这种要转识图
    looks_scanned: bool = False
    encrypted: bool = False
    reason: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.text.strip())


# --------------------------------------------------------------------- 基础工具


def _decode_stream(raw: bytes) -> bytes:
    """解 FlateDecode。解不开就原样返回（可能是未压缩的文本流）"""
    try:
        return zlib.decompress(raw)
    except zlib.error:
        pass
    # 有些 PDF 的流前面多一个字节、或 zlib 头不完整，跳过前导空白再试
    for offset in (1, 2):
        try:
            return zlib.decompress(raw[offset:])
        except zlib.error:
            continue
    return raw


_PDF_STRING = re.compile(rb"\((?:\\.|[^\\()])*\)", re.S)
_HEX_STRING = re.compile(rb"<([0-9A-Fa-f\s]+)>", re.S)
_ESCAPES = {
    b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f",
    b"(": b"(", b")": b")", b"\\": b"\\",
}


def _unescape_pdf_string(raw: bytes) -> bytes:
    """处理 PDF 字面量字符串里的转义（\\( \\) \\\\ \\n \\ddd 等）"""
    out = bytearray()
    i = 0
    while i < len(raw):
        ch = raw[i:i + 1]
        if ch != b"\\":
            out += ch
            i += 1
            continue
        nxt = raw[i + 1:i + 2]
        if not nxt:
            break
        if nxt in _ESCAPES:
            out += _ESCAPES[nxt]
            i += 2
            continue
        # 八进制 \ddd
        if nxt.isdigit():
            digits = b""
            j = i + 1
            while j < len(raw) and len(digits) < 3 and raw[j:j + 1].isdigit():
                digits += raw[j:j + 1]
                j += 1
            try:
                out.append(int(digits, 8) & 0xFF)
            except ValueError:
                pass
            i = j
            continue
        # 行尾反斜杠 = 续行
        if nxt in (b"\n", b"\r"):
            i += 2
            continue
        out += nxt
        i += 2
    return bytes(out)


# --------------------------------------------------------------------- 编码


_CMAP_PAIR = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")


def _parse_tounicode_cmap(data: bytes) -> dict[int, str]:
    """解析 ToUnicode CMap：把字形码位映射回真正的 Unicode。

    只处理 `beginbfchar/endbfchar` 与 `beginbfrange/endbfrange` 里最常见的两种写法。
    """
    mapping: dict[int, str] = {}

    for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in _CMAP_PAIR.findall(block):
            try:
                code = int(src, 16)
                text = bytes.fromhex(dst.decode("ascii")).decode("utf-16-be", "ignore")
            except (ValueError, UnicodeDecodeError):
                continue
            mapping[code] = text

    for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
        # <lo> <hi> <dst>
        for lo, hi, dst in re.findall(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block, re.S
        ):
            try:
                lo_i, hi_i = int(lo, 16), int(hi, 16)
                base = int(dst, 16)
            except ValueError:
                continue
            if hi_i - lo_i > 65535:  # 明显异常的范围，跳过
                continue
            for offset in range(hi_i - lo_i + 1):
                try:
                    mapping[lo_i + offset] = chr(base + offset)
                except (ValueError, OverflowError):
                    break
    return mapping


def _decode_pdf_text(raw: bytes, cmap: dict[int, str] | None) -> str:
    """把 PDF 字符串（字面量或十六进制）解成 Python 字符串"""
    if raw.startswith(b"<"):
        try:
            data = bytes.fromhex(re.sub(rb"\s", b"", raw[1:-1]).decode("ascii"))
        except (ValueError, UnicodeDecodeError):
            return ""
        return _decode_bytes(data, cmap)
    return _decode_bytes(_unescape_pdf_string(raw[1:-1]), cmap)


def _decode_bytes(data: bytes, cmap: dict[int, str] | None) -> str:
    # UTF-16BE with BOM
    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16-be", "ignore")

    if cmap:
        # 有 ToUnicode：按 2 字节码位查表（覆盖绝大多数中文 PDF）
        out = []
        for i in range(0, len(data) - 1, 2):
            code = (data[i] << 8) | data[i + 1]
            out.append(cmap.get(code, ""))
        mapped = "".join(out)
        if mapped.strip():
            return mapped

    # 没有 CMap 时的兜底：先按 UTF-8，再按 latin-1
    try:
        text = data.decode("utf-8")
        if text.isprintable() or any("\u4e00" <= ch <= "\u9fff" for ch in text):
            return text
    except UnicodeDecodeError:
        pass
    return data.decode("latin-1", "ignore")


# --------------------------------------------------------------------- 抽取


#: 取文本的操作符：Tj / TJ / ' / "
_TEXT_OP = re.compile(
    rb"(?P<str>\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]+>)\s*(?P<op>Tj|TJ|'|\")",
    re.S,
)


def _extract_from_content(content: bytes, cmap: dict[int, str] | None) -> list[str]:
    """从一条内容流里按顺序取所有文本片段"""
    pieces: list[str] = []
    for match in _TEXT_OP.finditer(content):
        text = _decode_pdf_text(match.group("str"), cmap)
        if text:
            pieces.append(text)
    return pieces


def extract_text(data: bytes, *, max_text: int = MAX_TEXT) -> PdfResult:
    """从 PDF 字节里抽文字。

    @returns PdfResult（`ok` 为假时看 `reason` 与 `looks_scanned`）
    """
    result = PdfResult()
    if not data:
        result.reason = "文件是空的"
        return result

    if not data.lstrip()[:5].startswith(b"%PDF"):
        result.reason = "这个文件不像 PDF"
        return result

    if b"/Encrypt" in data:
        result.encrypted = True
        result.reason = "这份 PDF 有密码保护，打不开。可以拍照发给我"
        return result

    # ① 先找 ToUnicode CMap（可能有多份，合并起来用）
    cmap: dict[int, str] = {}
    for match in re.finditer(rb"stream\r?\n", data):
        start = match.end()
        end = data.find(b"endstream", start)
        if end == -1:
            continue
        chunk = _decode_stream(data[start:end])
        if b"beginbfchar" in chunk or b"beginbfrange" in chunk:
            cmap.update(_parse_tounicode_cmap(chunk))
    if cmap:
        logger.debug("PDF ToUnicode 映射 %s 条", len(cmap))

    # ② 逐条流取文本
    pieces: list[str] = []
    page_count = 0
    stream_count = 0
    for match in re.finditer(rb"stream\r?\n", data):
        start = match.end()
        end = data.find(b"endstream", start)
        if end == -1:
            continue
        stream_count += 1
        chunk = _decode_stream(data[start:end])
        if b"Tj" not in chunk and b"TJ" not in chunk:
            continue
        page_count += 1
        pieces.extend(_extract_from_content(chunk, cmap or None))

    result.pages = page_count

    text = "".join(pieces)
    # 压缩空白：PDF 抽出来的换行很碎，直接进 prompt 会很浪费
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if len(text) > max_text:
        text = text[:max_text] + "\n…（后面还有内容，只取了前面一段）"

    result.text = text

    if not text.strip():
        # 有内容流但没有文本操作符 → 多半是扫描件（整页图片）
        result.looks_scanned = stream_count > 0
        result.reason = (
            "这份 PDF 是扫描件（整页是图片，没有文字层），我读不出文字。"
            "可以拍照发给我，我用识图来看"
            if result.looks_scanned
            else "这份 PDF 里没找到可以读的文字"
        )
    return result
