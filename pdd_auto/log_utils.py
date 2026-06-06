"""子进程日志清洗：过滤 Chrome / DrissionPage 写入的二进制乱码。"""
import re
import sys
from typing import TextIO

# 典型业务日志特征
_LOG_LINE_HINT = re.compile(
    r"(\[[\w\-]+\]|预览图|SKU|耗时|store_|成功|失败|警告|上传|提交|款式|型号)"
)


def sanitize_log_text(text: str) -> str:
    """去掉不可打印字符与疑似二进制解码产生的长乱码行。"""
    if not text:
        return ""
    cleaned_chars = []
    for ch in text:
        if ch in "\n\r\t":
            cleaned_chars.append(ch)
            continue
        if ord(ch) < 32:
            continue
        if ch.isprintable():
            cleaned_chars.append(ch)
    text = "".join(cleaned_chars)

    kept: list[str] = []
    for line in text.splitlines():
        if _is_garbage_line(line):
            continue
        kept.append(line)
    return "\n".join(kept) + ("\n" if text.endswith("\n") and kept else "")


def _is_garbage_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if len(s) < 120:
        return False
    if _LOG_LINE_HINT.search(s):
        return False
    if re.search(r"[\u4e00-\u9fff]", s):
        return False
    high = sum(1 for c in s if ord(c) > 127)
    if high / len(s) > 0.55:
        return True
    if len(s) > 300 and " " not in s[:150]:
        return True
    return False


def decode_subprocess_chunk(chunk: bytes) -> str:
    if not chunk:
        return ""
    text = chunk.decode("utf-8", errors="ignore")
    if not text.strip():
        text = chunk.decode("gbk", errors="ignore")
    return sanitize_log_text(text)


class SafeStdout(TextIO):
    """包装 stdout，丢弃明显乱码块（Python 侧 print 兜底）。"""

    def __init__(self, stream: TextIO | None = None):
        self._stream = stream or sys.__stdout__

    def write(self, s: str) -> int:
        if not s:
            return 0
        if isinstance(s, bytes):
            s = s.decode("utf-8", errors="ignore")
        cleaned = sanitize_log_text(s)
        if not cleaned:
            return len(s)
        self._stream.write(cleaned)
        return len(s)

    def flush(self):
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def install_safe_stdout():
    if not isinstance(sys.stdout, SafeStdout):
        sys.stdout = SafeStdout(sys.stdout)
