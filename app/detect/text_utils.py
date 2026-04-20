from __future__ import annotations

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher


_WHITESPACE_RE = re.compile(r"[\s\u3000]+")
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
_CJK_SPACE_RE = re.compile(r"(?<=[\u3400-\u4dbf\u4e00-\u9fff]) (?=[\u3400-\u4dbf\u4e00-\u9fff])")


def _tighten_cjk_spacing(text: str) -> str:
    previous = text
    current = _CJK_SPACE_RE.sub("", previous)
    while current != previous:
        previous = current
        current = _CJK_SPACE_RE.sub("", previous)
    return current


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    lines: list[str] = []
    for raw_line in text.replace("\r", "\n").split("\n"):
        line = _WHITESPACE_RE.sub(" ", raw_line).strip()
        line = _tighten_cjk_spacing(line)
        if not line:
            continue
        lines.append(line)
    return "\n".join(lines)


def compact_text(text: str) -> str:
    return _WHITESPACE_RE.sub("", normalize_text(text))


def _keep_relevant_chars(text: str) -> str:
    kept: list[str] = []
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" or ch.isascii() and ch.isalnum():
            kept.append(ch)
        elif ch == "#":
            kept.append(ch)
    return "".join(kept)


def build_text_key(text: str) -> str:
    normalized = compact_text(text)
    normalized = _TIME_RE.sub("#", normalized)
    normalized = re.sub(r"\d+", "#", normalized)
    return _keep_relevant_chars(normalized.lower())


def extract_keyword_hits(text: str, keywords: list[str]) -> list[str]:
    normalized = normalize_text(text)
    hits: list[str] = []
    for keyword in keywords:
        token = keyword.strip()
        if token and token in normalized:
            hits.append(token)
    return hits


def build_question_fingerprint(question_key: str, keyword_hits: list[str]) -> str:
    source = f"{question_key}|{'|'.join(sorted(keyword_hits))}"
    return hashlib.sha1(source.encode("utf-8")).hexdigest()


def is_similar_question(left_key: str, right_key: str) -> bool:
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    shortest = min(len(left_key), len(right_key))
    if shortest < 8:
        return False
    ratio = SequenceMatcher(None, left_key, right_key).ratio()
    return ratio >= 0.94
