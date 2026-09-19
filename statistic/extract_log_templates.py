#!/usr/bin/env python3
"""Extract production logging format strings from a Java source tree.

Output format matches ``hadoop/hadoop-hdfs-project/log_templates.txt``:

    <relative/path.java>: <first string literal of the logging call>

The original AnomalyGen extractor is not in the artifact. This reconstruction
takes the *first* string literal of each LOG/logger call (so concatenated
``"Created " + token`` becomes ``Created ``, while SLF4J
``"Decrypted EDEK for file: {}, output stream: 0x{}"`` is kept whole).

Validated by reproducing HDFS 3.3.6 ``hadoop-hdfs-project/log_templates.txt``.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter

LOG_IDENT = r"(?:LOG|log|LOGGER|Logger|logger|LOG_|LOGGERS)"
LEVEL = r"(?:trace|debug|info|warn|warning|error|fatal|log)"
CALL_RE = re.compile(rf"\b{LOG_IDENT}\s*\.\s*{LEVEL}\s*\(", re.I)
STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"')
TEST_HINTS = ("src/test", "/test/", "src/it/", "/tests/")


def is_test_path(path: str) -> bool:
    p = path.replace("\\", "/")
    return any(h in p for h in TEST_HINTS)


def first_string_literal(src: str, call_end: int) -> str | None:
    """Return the first Java string literal in the argument list of a call."""
    i = call_end
    n = len(src)
    depth = 1
    in_str = False
    in_char = False
    escape = False
    in_line_comment = False
    in_block_comment = False
    start = None
    while i < n and depth > 0:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if in_line_comment:
            if c == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if c == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
                return src[start : i + 1]
            i += 1
            continue
        if in_char:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == "'":
                in_char = False
            i += 1
            continue
        if c == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if c == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if c == '"':
            in_str = True
            start = i
            i += 1
            continue
        if c == "'":
            in_char = True
            i += 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        i += 1
    return None


def decode_java_string(literal: str) -> str:
    inner = literal[1:-1]
    return bytes(inner, "utf-8").decode("unicode_escape", errors="replace")


def extract_file(path: str) -> list[str]:
    with open(path, encoding="utf-8", errors="replace") as fh:
        src = fh.read()
    out = []
    for m in CALL_RE.finditer(src):
        lit = first_string_literal(src, m.end())
        if not lit:
            continue
        text = decode_java_string(lit)
        if text.strip() == "":
            continue
        out.append(text)
    return out


def iter_java(root: str):
    for dirpath, _, files in os.walk(root):
        for name in files:
            if name.endswith(".java"):
                yield os.path.join(dirpath, name)


def extract_tree(root: str, rel_base: str | None = None, drop_test: bool = True):
    root = os.path.abspath(root)
    base = os.path.abspath(rel_base or root)
    rows = []
    for path in iter_java(root):
        rel = os.path.relpath(path, base).replace("\\", "/")
        if drop_test and is_test_path(rel):
            continue
        for text in extract_file(path):
            rows.append((rel, text))
    return rows


def write_templates(rows, out_path: str):
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for rel, text in sorted(rows, key=lambda x: (x[0].lower(), x[1])):
            fh.write(f"{rel}: {text}\n")


def summarize(rows, drop_test_already: bool) -> dict:
    stmts = [t for _, t in rows]
    unique = sorted(set(stmts))
    return {
        "n_calls_with_literal": len(rows),
        "n_unique_format": len(unique),
        "drop_test": drop_test_already,
    }


def compare_hdfs(extracted_path: str, gold_path: str) -> None:
    def load(p):
        lines = []
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if line.strip():
                    lines.append(line)
        return lines

    gold = load(gold_path)
    got = load(extracted_path)
    gold_set, got_set = set(gold), set(got)
    print(f"[gold] {len(gold)} lines / {len(gold_set)} unique  ({gold_path})")
    print(f"[got ] {len(got)} lines / {len(got_set)} unique  ({extracted_path})")
    print(f"[overlap] {len(gold_set & got_set)}")
    print(f"[gold only] {len(gold_set - got_set)}")
    print(f"[got only] {len(got_set - gold_set)}")
    gold_fmt = {ln.split(": ", 1)[-1] if ": " in ln else ln for ln in gold_set}
    got_fmt = {ln.split(": ", 1)[-1] if ": " in ln else ln for ln in got_set}
    # coverage_stats universe is unique format strings after dropping test paths
    print(f"[unique formats gold] {len(gold_fmt)}")
    print(f"[unique formats got ] {len(got_fmt)}")
    print(f"[format overlap] {len(gold_fmt & got_fmt)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="Java tree to scan")
    ap.add_argument("--rel-base", default=None, help="Prefix stripped from paths")
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-test", action="store_true")
    ap.add_argument("--compare-gold", default=None)
    args = ap.parse_args()

    rows = extract_tree(args.root, args.rel_base, drop_test=not args.keep_test)
    write_templates(rows, args.out)
    stats = summarize(rows, drop_test_already=not args.keep_test)
    print(f"[extract] root={args.root}")
    print(f"[extract] calls_with_literal={stats['n_calls_with_literal']}")
    print(f"[extract] unique_format={stats['n_unique_format']}")
    print(f"[extract] wrote {args.out}")
    if args.compare_gold:
        compare_hdfs(args.out, args.compare_gold)


if __name__ == "__main__":
    sys.exit(main())
