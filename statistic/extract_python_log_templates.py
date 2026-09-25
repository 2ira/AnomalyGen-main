#!/usr/bin/env python3
"""Extract production logging format strings from a Python tree (OpenStack Nova).

Output lines: ``<relative/path.py>: <first string literal of the logging call>``
Same first-literal convention as the Java extractor.
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

LOG_IDENT = r"(?:LOG|log|LOGGER|logger|_LOG)"
LEVEL = r"(?:debug|info|warning|warn|error|exception|critical|fatal)"
CALL_RE = re.compile(rf"\b{LOG_IDENT}\s*\.\s*{LEVEL}\s*\(", re.I)
STRING_RE = re.compile(
    r"(?:[fFrRbBuU]*'''(?:\\.|[^'\\])*'''|[fFrRbBuU]*\"\"\"(?:\\.|[^\"\\])*\"\"\""
    r"|[fFrRbBuU]*'(?:\\.|[^'\\])*'|[fFrRbBuU]*\"(?:\\.|[^\"\\])*\")"
)
TEST_HINTS = ("/tests/", "/test/", "src/test", "/functional/")


def is_test_path(path: str) -> bool:
    p = path.replace("\\", "/")
    return any(h in p for h in TEST_HINTS)


def first_string_literal(src: str, call_end: int) -> str | None:
    i = call_end
    n = len(src)
    depth = 1
    while i < n and depth > 0:
        m = STRING_RE.match(src, i)
        if m:
            raw = m.group(0)
            # strip prefixes and quotes
            body = raw
            while body and body[0] in "fFrRbBuU":
                body = body[1:]
            if body.startswith("'''") or body.startswith('"""'):
                body = body[3:-3]
            else:
                body = body[1:-1]
            return body.replace("\\n", " ").replace("\\t", " ").strip()
        c = src[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        i += 1
    return None


def extract_file(path: Path, rel: str) -> list[tuple[str, str]]:
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for m in CALL_RE.finditer(src):
        lit = first_string_literal(src, m.end())
        if lit and lit.strip():
            out.append((rel, lit.replace("\n", " ").strip()))
    return out


def extract_tree(root: str, rel_base: str | None, drop_test: bool) -> list[tuple[str, str]]:
    root_p = Path(root)
    base = Path(rel_base) if rel_base else root_p
    rows = []
    for dirpath, dirnames, filenames in os.walk(root_p):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", ".tox"}]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            fp = Path(dirpath) / fn
            rel = str(fp.relative_to(base)).replace("\\", "/")
            if drop_test and is_test_path(rel):
                continue
            rows.extend(extract_file(fp, rel))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--rel-base", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-test", action="store_true")
    args = ap.parse_args()
    rows = extract_tree(args.root, args.rel_base, drop_test=not args.keep_test)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for rel, text in rows:
            f.write(f"{rel}: {text}\n")
    uniq = sorted({t for _, t in rows})
    print(f"[extract-py] calls={len(rows)} unique={len(uniq)} -> {args.out}")


if __name__ == "__main__":
    main()
