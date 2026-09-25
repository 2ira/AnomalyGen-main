#!/usr/bin/env python3
"""Append depth-3 unique-dir merge logs into the archived HDFS corpus and recompute D1."""
from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "statistic"))
from coverage_stats import covered_templates, load_generated, read_source_templates  # noqa: E402

OUT = ROOT / "statistic/x5_out"
SOURCE = ROOT / "hadoop/hadoop-hdfs-project/log_templates.txt"
ARCHIVED = ROOT / "output/log_events/final_logs.json"
HADOOP_OUT = ROOT / "output/hadoop"
HASH_DIR = re.compile(r"_[0-9a-f]{8}$")


def extract_messages(obj) -> list[str]:
    msgs = []
    if isinstance(obj, dict):
        for v in obj.values():
            msgs.extend(extract_messages(v))
    elif isinstance(obj, list):
        for v in obj:
            msgs.extend(extract_messages(v))
    elif isinstance(obj, str) and len(obj) >= 8:
        msgs.append(obj)
    return msgs


def d3_merge_files():
    files = []
    for p in HADOOP_OUT.glob("*/merge_single_log.json"):
        if HASH_DIR.search(p.parent.name):
            files.append(p)
    return sorted(files)


def main():
    files = d3_merge_files()
    extra = []
    for p in files:
        try:
            extra.extend(extract_messages(json.loads(p.read_text(encoding="utf-8"))))
        except json.JSONDecodeError:
            continue
    archived = load_generated(str(ARCHIVED))
    # also include prior unreached-entry merges (non-hash dirs) so the combined
    # corpus is archived + previous refill + this depth-3 fill
    prior_extra = []
    for p in sorted(HADOOP_OUT.glob("*/merge_single_log.json")):
        if HASH_DIR.search(p.parent.name):
            continue
        try:
            prior_extra.extend(extract_messages(json.loads(p.read_text(encoding="utf-8"))))
        except json.JSONDecodeError:
            continue
    combined_msgs = list(archived) + prior_extra + extra
    payload = {str(i): {"log": m} for i, m in enumerate(combined_msgs)}

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = ARCHIVED.with_name(f"final_logs.pre_d3_{stamp}.json")
    if not bak.exists():
        shutil.copy2(ARCHIVED, bak)

    sidecar = OUT / "final_logs_d3_merged.json"
    OUT.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    ARCHIVED.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    _, templates = read_source_templates(str(SOURCE))
    g_old, _ = covered_templates(archived, templates)
    g_new, _ = covered_templates(combined_msgs, templates)
    summary = {
        "d3_dirs": len(files),
        "d3_blobs": len(extra),
        "prior_refill_blobs": len(prior_extra),
        "archived_messages": len(archived),
        "combined_messages": len(combined_msgs),
        "archived_d1": f"{len(g_old)}/{len(templates)} = {100.0 * len(g_old) / len(templates):.2f}%",
        "combined_d1": f"{len(g_new)}/{len(templates)} = {100.0 * len(g_new) / len(templates):.2f}%",
        "archived_hit": len(g_old),
        "combined_hit": len(g_new),
        "delta_hit": len(g_new) - len(g_old),
        "universe": len(templates),
        "backup": str(bak),
        "sidecar": str(sidecar),
    }
    (OUT / "d3_merged_d1.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
