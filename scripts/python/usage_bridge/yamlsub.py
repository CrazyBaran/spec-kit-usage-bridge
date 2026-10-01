"""A stdlib parser for the small YAML subset Usage Bridge's config uses (spec §5.2).

Supported: block mappings by space indentation, scalars (true/false, null/~, int, float, quoted and
plain strings), block lists of scalars, flow collections of scalars (``[]``, ``{}``, ``{a: 1}``,
``[a, b]``) and ``#`` comments outside quotes. Anything else is reported as ``line N: …`` and the
affected key is skipped together with its indented block. PyYAML is never needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_INT = re.compile(r"[-+]?\d+")
_FLOAT = re.compile(r"[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?")
_BLOCK_SCALAR = re.compile(r"[|>][-+0-9]*")


class _Unsupported(ValueError):
    pass


@dataclass
class _Line:
    number: int
    indent: int
    tab: bool
    text: str


def parse_yaml(text: str) -> tuple[dict[str, Any], list[str]]:
    """Parse ``text`` into a mapping; return it with a list of ``line N: …`` warnings."""
    warnings: list[str] = []
    lines = _logical_lines(text, warnings)
    parser = _Parser(lines, warnings)
    if not lines:
        return {}, warnings
    if lines[0].tab or lines[0].indent != 0 or _is_list_item(lines[0].text):
        warnings.append(f"line {lines[0].number}: the top level must be a mapping")
        return {}, warnings
    data, _ = parser.mapping(0, 0)
    return data, warnings


def _logical_lines(text: str, warnings: list[str]) -> list[_Line]:
    out: list[_Line] = []
    for number, raw in enumerate(re.split(r"\r?\n", text.lstrip("﻿")), start=1):
        content = _strip_comment(raw).rstrip()
        if not content.strip():
            continue
        stripped = content.lstrip(" \t")
        lead = content[: len(content) - len(stripped)]
        if stripped == "---" and not lead:
            if out:
                warnings.append(f"line {number}: multiple documents are not supported; ignoring the rest")
                break
            continue
        out.append(_Line(number, len(lead), "\t" in lead, stripped))
    return out


def _strip_comment(line: str) -> str:
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i]
    return line


def _is_list_item(text: str) -> bool:
    return text == "-" or text.startswith("- ")


class _Parser:
    def __init__(self, lines: list[_Line], warnings: list[str]) -> None:
        self.lines = lines
        self.warnings = warnings

    def warn(self, line: _Line, message: str) -> None:
        self.warnings.append(f"line {line.number}: {message}")

    def skip_block(self, i: int, indent: int) -> int:
        while i < len(self.lines) and (self.lines[i].tab or self.lines[i].indent > indent):
            i += 1
        return i

    def mapping(self, i: int, indent: int) -> tuple[dict[str, Any], int]:
        result: dict[str, Any] = {}
        while i < len(self.lines):
            line = self.lines[i]
            if not line.tab and line.indent < indent:
                break
            if line.tab or line.indent > indent:
                self.warn(line, "tab or unexpected indentation; line skipped")
                i += 1
                continue
            if _is_list_item(line.text):
                self.warn(line, "list item where a key was expected; skipped")
                i = self.skip_block(i + 1, indent)
                continue
            try:
                key, rest = _split_key(line.text)
            except _Unsupported as exc:
                self.warn(line, str(exc))
                i = self.skip_block(i + 1, indent)
                continue
            if rest:
                try:
                    result[key] = _value(rest)
                except _Unsupported as exc:
                    self.warn(line, f"{key}: {exc}; key skipped")
                    i = self.skip_block(i + 1, indent)
                    continue
                i += 1
                continue
            j = i + 1
            if j < len(self.lines) and (self.lines[j].tab or self.lines[j].indent > indent):
                child = self.lines[j]
                if child.tab:
                    self.warn(child, f"{key}: tab indentation is not supported; key skipped")
                    i = self.skip_block(j, indent)
                    continue
                if _is_list_item(child.text):
                    value, i = self.block_list(j, child.indent)
                else:
                    value, i = self.mapping(j, child.indent)
                result[key] = value
            else:
                result[key] = None
                i = j
        return result, i

    def block_list(self, i: int, indent: int) -> tuple[list[Any], int]:
        items: list[Any] = []
        while i < len(self.lines):
            line = self.lines[i]
            if line.tab or line.indent > indent:
                self.warn(line, "only lists of scalars are supported; line skipped")
                i += 1
                continue
            if line.indent < indent or not _is_list_item(line.text):
                break
            item = line.text[1:].strip()
            try:
                if not item or _looks_like_key(item):
                    raise _Unsupported("only lists of scalars are supported")
                items.append(_value(item))
            except _Unsupported as exc:
                self.warn(line, f"{exc}; item skipped")
                i = self.skip_block(i + 1, indent)
                continue
            i += 1
        return items, i


def _looks_like_key(text: str) -> bool:
    if text[:1] in ("'", '"', "[", "{"):
        return False
    return ": " in text or text.endswith(":")


def _split_key(text: str) -> tuple[str, str]:
    """Split ``key: rest`` (the key may be quoted); raise _Unsupported for anything else."""
    if text[:1] in ("'", '"'):
        key, end = _quoted(text, 0)
        remainder = text[end:]
        if not (remainder.startswith(":") and (len(remainder) == 1 or remainder[1] in " \t")):
            raise _Unsupported("expected 'key: value'")
        return key, remainder[1:].strip()
    for i, ch in enumerate(text):
        if ch == ":" and (i + 1 == len(text) or text[i + 1] in " \t"):
            key = text[:i].strip()
            if not key:
                break
            if key[:1] in ("&", "*", "?", "!"):
                raise _Unsupported("anchors, aliases, tags and complex keys are not supported")
            return key, text[i + 1:].strip()
    raise _Unsupported("expected 'key: value'")


def _quoted(text: str, start: int) -> tuple[str, int]:
    """Parse a quoted string starting at ``text[start]``; return (value, index after the closing quote)."""
    quote = text[start]
    out: list[str] = []
    i = start + 1
    while i < len(text):
        ch = text[i]
        if quote == "'" and ch == "'":
            if text[i + 1: i + 2] == "'":
                out.append("'")
                i += 2
                continue
            return "".join(out), i + 1
        if quote == '"' and ch == "\\" and i + 1 < len(text):
            out.append({"n": "\n", "t": "\t"}.get(text[i + 1], text[i + 1]))
            i += 2
            continue
        if quote == '"' and ch == '"':
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    raise _Unsupported("unterminated quoted string")


def _value(text: str) -> Any:
    text = text.strip()
    if text[:1] in ("&", "*", "!"):
        raise _Unsupported("anchors, aliases and tags are not supported")
    if _BLOCK_SCALAR.fullmatch(text):
        raise _Unsupported("block scalars (| and >) are not supported")
    if text.startswith("{"):
        return _flow(text, "{", "}")
    if text.startswith("["):
        return _flow(text, "[", "]")
    if text[:1] in ("'", '"'):
        value, end = _quoted(text, 0)
        if text[end:].strip():
            raise _Unsupported("unexpected text after a quoted string")
        return value
    return _plain(text)


def _plain(text: str) -> Any:
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in ("null", "~"):
        return None
    if _INT.fullmatch(text):
        return int(text)
    if _FLOAT.fullmatch(text):
        return float(text)
    return text


def _flow(text: str, opener: str, closer: str) -> Any:
    if not text.endswith(closer):
        raise _Unsupported("unterminated flow collection")
    inner = text[1:-1].strip()
    if opener == "[":
        return [_flow_scalar(part) for part in _split_flow(inner)] if inner else []
    result: dict[str, Any] = {}
    for part in _split_flow(inner) if inner else []:
        key, rest = _split_key(part)
        result[key] = _flow_scalar(rest)
    return result


def _flow_scalar(text: str) -> Any:
    if text.strip()[:1] in ("{", "["):
        raise _Unsupported("nested flow collections are not supported")
    return _value(text)


def _split_flow(inner: str) -> list[str]:
    parts: list[str] = []
    quote = None
    depth = 0
    current: list[str] = []
    for ch in inner:
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(ch)
    parts.append("".join(current).strip())
    return [part for part in parts if part]
