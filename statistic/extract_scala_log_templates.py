#!/usr/bin/env python3
"""Extract production logging format strings from a Scala/Java Spark tree.

Scala: logInfo / logWarning / logError / logDebug / logTrace / logger.info(...)
Java: same first-literal LOG.* pass as the Hadoop extractor.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Reuse Java extractor when available
sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_log_templates import extract_tree as extract_java_tree  # noqa: E402

SCALA_LOG = re.compile(
    r"\b(?:log(?:Info|Warning|Warn|Error|Debug|Trace)|"
    r"(?:LOG|log|LOGGER|Logger|logger)\s*\.\s*(?:info|warn|warning|error|debug|trace|fatal))\s*\(",
    re.I,
)
STRING = re.compile(r'(?:[sSfF]?"""(?:\\.|[^"\\])*"""|[sSfF]?"(?:\\.|[^"\\])*")')
TEST_HINTS = ("src/test", "/test/", "/tests/", "src/it/")


def is_test_path(path: str) -> bool:
    p = path.replace("\\", "/")
    return any(h in p for h in TEST_HINTS)


def first_string(src: str, call_end: int) -> str | None:
    i = call_end
    n = len(src)
    depth = 1
    while i < n and depth > 0:
        m = STRING.match(src, i)
        if m:
            raw = m.group(0)
            prefix = 0
            while prefix < len(raw) and raw[prefix] in "sSfF":
                prefix += 1
            body = raw[prefix:]
            if body.startswith('"""'):
                body = body[3:-3]
            else:
                body = body[1:-1]
            return body.replace("\n", " ").strip()
        c = src[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        i += 1
    return None


def extract_scala_tree(root: str, rel_base: str | None, drop_test: bool) -> list[tuple[str, str]]:
    root_p = Path(root)
    base = Path(rel_base) if rel_base else root_p
    rows = []
    for dirpath, dirnames, filenames in os.walk(root_p):
        dirnames[:] = [d for d in dirnames if d not in {".git", "target"}]
        for fn in filenames:
            if not fn.endswith(".scala"):
                continue
            fp = Path(dirpath) / fn
            rel = str(fp.relative_to(base)).replace("\\", "/")
            if drop_test and is_test_path(rel):
                continue
            try:
                src = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in SCALA_LOG.finditer(src):
                lit = first_string(src, m.end())
                if lit:
                    rows.append((rel, lit))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--rel-base", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    java_rows = extract_java_tree(args.root, args.rel_base, drop_test=True)
    scala_rows = extract_scala_tree(args.root, args.rel_base, drop_test=True)
    rows = [(p, t) for p, t in java_rows] + scala_rows
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for rel, text in rows:
            f.write(f"{rel}: {text}\n")
    uniq = {t for _, t in rows}
    print(f"[extract-spark] java={len(java_rows)} scala={len(scala_rows)} "
          f"calls={len(rows)} unique={len(uniq)} -> {args.out}")


if __name__ == "__main__":
    main()
