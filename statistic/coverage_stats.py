"""
Unified log-template coverage statistics (single counting convention).

Convention (applies to every cell of the coverage table):
  * Universe / denominator = the set of *distinct* logging statements that
    exist in the **production** source tree of the target system
    (``src/main/java``; test code excluded), extracted by the AST pass and
    deduplicated on the normalised format string.
  * A source template is *covered* by a log corpus if at least one message in
    that corpus matches the template after normalisation (placeholders ``{}``
    / ``<*>`` become wildcards, whitespace/case/punctuation normalised).
  * Coverage = |covered| / |universe|.
  * Improvement = |covered by AnomalyGen| / |covered by the public dataset|.

Usage:
    python statistic/coverage_stats.py \
        --source-templates hadoop/hadoop-hdfs-project/log_templates.txt \
        --generated output/log_events/final_logs.json \
        [--public dataset/HDFS/HDFS.log_templates.csv]
"""

import argparse
import csv
import json
import os
import re


PLACEHOLDER = re.compile(r"\{\}|<\*>|%[sdxfo]|\$\{[^}]*\}")
NON_ALNUM = re.compile(r"[^a-z0-9]+")
LEVEL_PREFIX = re.compile(r"^\s*\[?(trace|debug|info|warn|warning|error|fatal)\]?\s*:?\s*", re.I)


def read_source_templates(path):
    """Return (statements, unique_templates) for an AST-extracted template file.

    Lines are either ``<relative/java/path>: <format string>`` or a bare
    format string. Test-tree statements are dropped so that the denominator
    reflects production logging only.
    """
    statements = []
    line_re = re.compile(r"^([^:]*\.java):\s?(.*)$")
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            m = line_re.match(line.rstrip("\n"))
            if m:
                java_path, text = m.group(1), m.group(2)
                if "src/test" in java_path or "/test/" in java_path:
                    continue
            else:
                text = line.rstrip("\n")
            if text.strip():
                statements.append(text)
    return statements, sorted(set(statements))


def skeleton(text):
    """Normalise a template or a concrete message to a comparable skeleton."""
    text = LEVEL_PREFIX.sub("", text)
    text = PLACEHOLDER.sub(" ", text)
    text = NON_ALNUM.sub(" ", text.lower())
    # drop pure-numeric tokens: they are runtime values, never template identity
    tokens = [t for t in text.split() if not t.isdigit()]
    return tokens


def template_matcher(template):
    """Build a token-subsequence predicate for one source template.

    A message covers the template when the template's literal tokens all
    appear, in order, inside the message. This is the standard
    'template-literal containment' criterion and is robust both to
    placeholder expansion and to parser-introduced fragmentation.
    """
    tokens = skeleton(template)
    return tokens


def covered_templates(messages, templates, min_tokens=2):
    """Return the set of template indices covered by ``messages``."""
    tmpl_tokens = [template_matcher(t) for t in templates]
    # index templates by their rarest token to keep the scan tractable
    from collections import defaultdict

    freq = defaultdict(int)
    for toks in tmpl_tokens:
        for t in set(toks):
            freq[t] += 1
    index = defaultdict(list)
    usable = []
    for i, toks in enumerate(tmpl_tokens):
        if len(toks) < min_tokens:
            continue  # degenerate template (e.g. a bare "=" or "D: ")
        usable.append(i)
        key = min(set(toks), key=lambda t: freq[t])
        index[key].append(i)

    covered = set()
    for msg in messages:
        mtoks = skeleton(msg)
        mset = set(mtoks)
        cands = set()
        for t in mset:
            cands.update(index.get(t, ()))
        for i in cands:
            if i in covered:
                continue
            toks = tmpl_tokens[i]
            if not mset.issuperset(toks):
                continue
            # order-preserving subsequence check
            it = iter(mtoks)
            if all(any(x == tok for x in it) for tok in toks):
                covered.add(i)
    return covered, usable


def load_generated(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    msgs = []
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, dict) and "log" in v:
                msgs.append(v["log"])
    elif isinstance(data, list):
        for v in data:
            if isinstance(v, dict) and "log" in v:
                msgs.append(v["log"])
    return msgs


def load_public(path):
    msgs = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            for key in ("EventTemplate", "Content", "template"):
                if key in row and row[key]:
                    msgs.append(row[key])
                    break
    return msgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-templates", required=True)
    ap.add_argument("--generated", required=True)
    ap.add_argument("--public", default=None,
                    help="parsed templates of the public dataset (csv)")
    args = ap.parse_args()

    stmts, templates = read_source_templates(args.source_templates)
    print(f"[universe] file            : {args.source_templates}")
    print(f"[universe] logging stmts   : {len(stmts)}")
    print(f"[universe] unique templates: {len(templates)}")

    gen = load_generated(args.generated)
    gcov, usable = covered_templates(gen, templates)
    print(f"[AG      ] messages        : {len(gen)}  ({args.generated})")
    print(f"[AG      ] templates hit   : {len(gcov)}")
    print(f"[AG      ] coverage        : {len(gcov)}/{len(templates)} = "
          f"{100.0 * len(gcov) / len(templates):.2f}%")
    print(f"[note    ] non-degenerate templates (>=2 literal tokens): {len(usable)}")

    if args.public and os.path.exists(args.public):
        pub = load_public(args.public)
        pcov, _ = covered_templates(pub, templates)
        print(f"[public  ] templates       : {len(pub)}  ({args.public})")
        print(f"[public  ] templates hit   : {len(pcov)}")
        print(f"[public  ] coverage        : {len(pcov)}/{len(templates)} = "
              f"{100.0 * len(pcov) / len(templates):.2f}%")
        if pcov:
            print(f"[compare ] improvement     : {len(gcov) / len(pcov):.1f}x")


if __name__ == "__main__":
    main()
