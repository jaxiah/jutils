#!/usr/bin/env python3
"""
md_punct_cn2en.py — Markdown 中文标点转英文标点

将 Markdown 文件中的中文（全角）标点替换为英文（半角）标点，并修正
CJK 与 Latin/数字之间的空格。代码块、行内代码、URL 保持原样不动。
转换后建议用 prettier 做最终格式化。

用法
----
    python md_punct_cn2en.py file.md               # 输出到 stdout
    python md_punct_cn2en.py -i file.md            # 原地修改
    python md_punct_cn2en.py -i docs/              # 递归处理目录
    python md_punct_cn2en.py -i "**/*.md"          # glob 模式

Changelog
---------
2026-03-21  从 convert.py 重命名，补充文件头说明
"""

import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Punctuation mapping: Chinese → English (spaces added liberally)
# Prettier will normalise any extra whitespace afterwards.
# ---------------------------------------------------------------------------

PUNCT_MAP = [
    # Commas & enumeration comma
    ("，", ", "),
    ("、", ", "),
    # Period / full stop
    ("。", ". "),
    # Question / exclamation
    ("？", "? "),
    ("！", "! "),
    # Colon / semicolon
    ("：", ": "),
    ("；", "; "),
    # Parentheses — space on the outer side
    ("（", " ("),
    ("）", ") "),
    # Square brackets
    ("【", " ["),
    ("】", "] "),
    ("〔", " ["),
    ("〕", "] "),
    # Angle / book-title brackets → double quotes
    ("《", ' "'),
    ("》", '" '),
    ("〈", ' "'),
    ("〉", '" '),
    # Curly quotes → straight quotes
    ("\u201c", ' "'),  # "
    ("\u201d", '" '),  # "
    ("\u2018", " '"),  # '
    ("\u2019", "' "),  # '
    # Ellipsis
    ("…", "... "),
    # Em dash
    ("—", " — "),
    # Full-width hyphen
    ("－", " - "),
    # Middle dot
    ("·", "."),
    # Wavy dash / tilde
    ("～", "~"),
]

# ---------------------------------------------------------------------------
# Regex constants
# ---------------------------------------------------------------------------

# BMP CJK ranges (covers virtually all Chinese characters in practice).
# NOTE: Do NOT include supplementary-plane ranges like \u20000-\u2a6df here —
# Python's re module parses \uXXXX as 4-hex digits, so \u20000 becomes
# U+2000 (EN QUAD) + literal "0", which accidentally matches ASCII chars.
_CJK = r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]"
_LATIN_NUM = r"[A-Za-z0-9]"

# Regions that must not be modified: fenced code blocks, inline code, URLs.
_PROTECTED_RE = re.compile(
    r"(```[\s\S]*?```|`[^`\n]+`|https?://\S+|ftp://\S+)",
    re.MULTILINE,
)

# Placeholder format — NUL-delimited so it won't appear in real Markdown.
_PH_FMT = "\x00{n}PH\x00"
_PH_PAT = r"\x00\d+PH\x00"


# ---------------------------------------------------------------------------
# Core conversion
# ---------------------------------------------------------------------------


def _convert_text(text: str) -> str:
    """
    Apply punctuation substitution and spacing fixes to a plain-text block
    (no code spans or URLs inside).
    """
    # 1. Chinese punctuation → English
    for cn, en in PUNCT_MAP:
        text = text.replace(cn, en)

    # 2. Space between CJK and Latin/digits
    text = re.sub(rf"({_CJK})({_LATIN_NUM})", r"\1 \2", text)
    text = re.sub(rf"({_LATIN_NUM})({_CJK})", r"\1 \2", text)

    # 3. Clean up whitespace artefacts introduced by the substitutions above
    # a) Remove space that ended up immediately before punctuation
    text = re.sub(r" +([,.:;!?])", r"\1", text)
    # b) Remove space just inside brackets
    text = re.sub(r"\( +", "(", text)
    text = re.sub(r" +\)", ")", text)
    text = re.sub(r"\[ +", "[", text)
    text = re.sub(r" +\]", "]", text)
    # c) Collapse multiple consecutive spaces (but not leading indentation)
    text = re.sub(r"(?<=\S) {2,}", " ", text)
    # d) Strip trailing whitespace from every line
    text = re.sub(r" +$", "", text, flags=re.MULTILINE)

    return text


def convert_markdown(content: str) -> str:
    """
    Convert a full Markdown document.

    Code fences, inline code spans, and URLs are left completely untouched.
    Spaces are added at the boundary between those protected regions and
    adjacent CJK characters.
    """
    # --- Step 1: replace protected regions with opaque placeholders ----------
    protected: dict[str, str] = {}
    counter = 0

    def _store(m: re.Match) -> str:
        nonlocal counter
        key = _PH_FMT.format(n=counter)
        protected[key] = m.group(0)
        counter += 1
        return key

    text = _PROTECTED_RE.sub(_store, content)

    # --- Step 2: convert the remaining plain text ----------------------------
    text = _convert_text(text)

    # --- Step 3: add spaces at CJK ↔ placeholder boundaries -----------------
    # (handles inline-code or URL sitting right next to a Chinese character)
    text = re.sub(rf"({_CJK})({_PH_PAT})", r"\1 \2", text)
    text = re.sub(rf"({_PH_PAT})({_CJK})", r"\1 \2", text)

    # --- Step 4: restore protected regions -----------------------------------
    for key, value in protected.items():
        text = text.replace(key, value)

    return text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def process_file(path: Path, in_place: bool = False) -> None:
    original = path.read_text(encoding="utf-8")
    converted = convert_markdown(original)
    if in_place:
        path.write_text(converted, encoding="utf-8")
        print(f"[converted] {path}", file=sys.stderr)
    else:
        sys.stdout.write(converted)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Convert Chinese punctuation in Markdown files to English.")
    parser.add_argument(
        "files",
        nargs="+",
        metavar="FILE",
        help="Markdown file(s), directory, or glob pattern(s) to process.",
    )
    parser.add_argument(
        "-i",
        "--in-place",
        action="store_true",
        help="Overwrite the original file(s) instead of printing to stdout.",
    )
    args = parser.parse_args()

    paths: list[Path] = []
    for pattern in args.files:
        p = Path(pattern)
        if "*" in pattern or "?" in pattern:
            paths.extend(Path(".").glob(pattern))
        elif p.is_dir():
            paths.extend(p.rglob("*.md"))
        else:
            paths.append(p)

    if not paths:
        print("No files matched.", file=sys.stderr)
        sys.exit(1)

    for path in paths:
        process_file(path, in_place=args.in_place)


if __name__ == "__main__":
    main()
