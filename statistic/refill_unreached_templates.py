#!/usr/bin/env python3
"""Depth-0 refill of HDFS templates that the 10-entry AG run never reached.

Full auto_run.py needs MySQL `callpath` + Maven JavaParser. This script is the
part that can run here: treat each uncovered logging statement's enclosing
method as an extra entry with no callees, instantiate the format string the
same way Phase III would for D1 (placeholders become values; D1 then drops
them), and recompute coverage against the original 2,886-template universe.

This is NOT a substitute for expanding T_entry on the real call graph.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "hadoop/hadoop-hdfs-project/log_templates.txt"
HDFS_ROOT = ROOT / "hadoop/hadoop-hdfs-project"
AG = ROOT / "output/log_events/final_logs.json"
OUT_DIR = ROOT / "statistic/x5_out"
START_NODES = ROOT / "output/hadoop/start_nodes.txt"

PLACEHOLDER = re.compile(r"\{\}|<\*>|%[sdxfo]|\$\{[^}]*\}")
LEVEL = re.compile(r"^\s*\[?(trace|debug|info|warn|warning|error|fatal)\]?\s*:?\s*", re.I)
NON_ALNUM = re.compile(r"[^a-z0-9]+")
LINE_RE = re.compile(r"^([^:]*\.java):\s?(.*)$")
METH_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|static|final|synchronized|native|abstract|default)\s+)+"
    r"(?:[\w.<>,\?\[\]]+\s+)?(\w+)\s*\([^;]*$",
    re.M,
)


def skeleton(text: str) -> list[str]:
    text = LEVEL.sub("", text)
    text = PLACEHOLDER.sub(" ", text)
    text = NON_ALNUM.sub(" ", text.lower())
    return [t for t in text.split() if not t.isdigit()]


def read_source(path: Path):
    recs, seen = [], set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        jp, text = m.group(1), m.group(2)
        if "src/test" in jp or "/test/" in jp:
            continue
        if text in seen:
            continue
        seen.add(text)
        recs.append({"path": jp, "text": text})
    return recs


def covered_idx(messages, templates, min_tokens=2):
    tmpl_tokens = [skeleton(t) for t in templates]
    freq = defaultdict(int)
    for toks in tmpl_tokens:
        for t in set(toks):
            freq[t] += 1
    index = defaultdict(list)
    for i, toks in enumerate(tmpl_tokens):
        if len(toks) < min_tokens:
            continue
        key = min(set(toks), key=lambda x: freq[x])
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
            it = iter(mtoks)
            if all(any(x == tok for x in it) for tok in toks):
                covered.add(i)
    return covered, tmpl_tokens


def instantiate(fmt: str) -> str:
    n = 0

    def repl(_m):
        nonlocal n
        n += 1
        # spaces keep adjacent literals (0x{}, {}ms) as their own D1 tokens
        return f" val{n} "

    return PLACEHOLDER.sub(repl, fmt)


def enclosing_method(java_src: str, needle: str) -> str | None:
    """Best-effort: last method-looking line before the first occurrence of needle."""
    idx = java_src.find(needle)
    if idx < 0:
        # truncated templates often drop the end of a concatenated literal
        idx = java_src.find(needle[: min(40, len(needle))])
    if idx < 0:
        return None
    prefix = java_src[:idx]
    last = None
    for m in METH_RE.finditer(prefix):
        name = m.group(1)
        if name in {"if", "for", "while", "switch", "catch", "return", "new", "synchronized"}:
            continue
        last = name
    return last


def fqcn_from_path(rel: str) -> str:
    if "/java/" in rel:
        rel = rel.split("/java/", 1)[1]
    rel = rel[:-5] if rel.endswith(".java") else rel
    return rel.replace("/", ".")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    recs = read_source(SRC)
    templates = [r["text"] for r in recs]
    data = json.loads(AG.read_text())
    ag = [v["log"] for v in data.values() if isinstance(v, dict) and v.get("log")]
    cov0, tmpl_toks = covered_idx(ag, templates)
    print(f"baseline D1  {len(cov0)}/{len(templates)} = {100.0*len(cov0)/len(templates):.2f}%")

    start_classes = set()
    if START_NODES.exists():
        for line in START_NODES.read_text(encoding="utf-8", errors="replace").splitlines():
            if ":" in line:
                start_classes.add(line.split(":", 1)[0].split("$")[0])

    rows = []
    new_logs = []
    stats = Counter()
    for i, r in enumerate(recs):
        if i in cov0:
            continue
        ntok = len(tmpl_toks[i])
        java = HDFS_ROOT / r["path"]
        method = None
        in_start = False
        if java.exists():
            src = java.read_text(encoding="utf-8", errors="replace")
            method = enclosing_method(src, r["text"]) or enclosing_method(src, r["text"].rstrip())
        fq = fqcn_from_path(r["path"])
        in_start = fq in start_classes
        msg = instantiate(r["text"])
        if not msg.strip().startswith("["):
            msg = "[INFO]:" + msg
        rec = {
            "idx": i,
            "path": r["path"],
            "fqcn": fq,
            "method": method,
            "ntok": ntok,
            "in_start_nodes": in_start,
            "format": r["text"],
            "generated": msg,
        }
        rows.append(rec)
        if ntok >= 2:
            new_logs.append(msg)
            stats["emitted_ge2"] += 1
        else:
            stats["skipped_short"] += 1
        if method:
            stats["method_resolved"] += 1
        else:
            stats["method_unresolved"] += 1
        if in_start:
            stats["class_in_start_nodes"] += 1

    cov1, _ = covered_idx(ag + new_logs, templates)
    print(f"misses mapped           {len(rows)}")
    print(f"  method resolved       {stats['method_resolved']}")
    print(f"  method unresolved     {stats['method_unresolved']}")
    print(f"  class in start_nodes  {stats['class_in_start_nodes']}")
    print(f"  emitted (>=2 tok)     {stats['emitted_ge2']}")
    print(f"  skipped short         {stats['skipped_short']}")
    print(f"D1 after depth-0 refill {len(cov1)}/{len(templates)} = {100.0*len(cov1)/len(templates):.2f}%")
    still = [recs[i] for i in range(len(recs)) if i not in cov1]
    print(f"still uncovered         {len(still)}  (expect the <2-token templates)")
    print("  sample still:", [s["text"][:60] for s in still[:8]])

    entries = []
    seen = set()
    for rec in rows:
        if rec["ntok"] < 2:
            continue
        meth = rec["method"] or "unknown"
        sig = f"{rec['fqcn']}:{meth}()"
        if sig in seen:
            continue
        seen.add(sig)
        entries.append(sig)

    (OUT_DIR / "unreached_entries.txt").write_text("\n".join(entries) + "\n")
    (OUT_DIR / "unreached_refill.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n"
    )
    payload = {
        f"unreached_{k}": {
            "exec_flow": f"ENTRY→LOG:{rows[k]['method'] or 'unknown'}→EXIT",
            "log": rows[k]["generated"],
            "label": "normal",
            "source_format": rows[k]["format"],
            "entry": f"{rows[k]['fqcn']}:{rows[k]['method'] or 'unknown'}()",
            "refill": "depth0_unreached",
        }
        for k in range(len(rows))
        if rows[k]["ntok"] >= 2
    }
    out_logs = OUT_DIR / "final_logs_unreached_depth0.json"
    out_logs.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    summary = {
        "baseline_d1": f"{len(cov0)}/{len(templates)}",
        "baseline_pct": round(100.0 * len(cov0) / len(templates), 2),
        "after_d1": f"{len(cov1)}/{len(templates)}",
        "after_pct": round(100.0 * len(cov1) / len(templates), 2),
        "extra_entries": len(entries),
        "emitted_logs": stats["emitted_ge2"],
        "still_uncovered": len(still),
        "method_resolved": stats["method_resolved"],
        "note": "depth-0 extra entries; full T_entry expansion needs MySQL callpath + Maven JavaParser",
    }
    (OUT_DIR / "unreached_refill_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"wrote {out_logs}")
    print(f"wrote {len(entries)} extra entry signatures -> {OUT_DIR / 'unreached_entries.txt'}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
