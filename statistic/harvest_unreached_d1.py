#!/usr/bin/env python3
"""Combine archived AG logs with newly merged unreached-entry logs and recompute D1."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "statistic"))
from coverage_stats import covered_templates, load_generated, read_source_templates  # noqa: E402

OUT = ROOT / "statistic/x5_out"
SOURCE = ROOT / "hadoop/hadoop-hdfs-project/log_templates.txt"
ARCHIVED = ROOT / "output/log_events/final_logs.json"
HADOOP_OUT = ROOT / "output/hadoop"


def new_merge_files():
    files = []
    for p in HADOOP_OUT.glob("*/merge_single_log.json"):
        files.append(p)
    return sorted(files)


def extract_messages(obj) -> list[str]:
    msgs = []
    if isinstance(obj, dict):
        for v in obj.values():
            msgs.extend(extract_messages(v))
    elif isinstance(obj, list):
        for v in obj:
            msgs.extend(extract_messages(v))
    elif isinstance(obj, str) and v_ok(obj):
        msgs.append(obj)
    return msgs


def v_ok(s: str) -> bool:
    return len(s) >= 8


def main():
    files = new_merge_files()
    extra = []
    for p in files:
        try:
            extra.extend(extract_messages(json.loads(p.read_text(encoding="utf-8"))))
        except json.JSONDecodeError:
            continue
    archived = load_generated(str(ARCHIVED))
    combined = []
    for i, m in enumerate(archived):
        combined.append({"log": m})
    for i, m in enumerate(extra):
        combined.append({"log": m})
    out_json = OUT / "final_logs_unreached_merged.json"
    OUT.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps({str(i): v for i, v in enumerate(combined)}, ensure_ascii=False), encoding="utf-8")

    _, templates = read_source_templates(str(SOURCE))
    gcov_old, _ = covered_templates(archived, templates)
    gcov_new, _ = covered_templates([c["log"] for c in combined], templates)
    gcov_extra, _ = covered_templates(extra, templates)
    summary = {
        "new_entry_dirs": len(files),
        "archived_messages": len(archived),
        "new_merge_blobs": len(extra),
        "archived_d1": f"{len(gcov_old)}/{len(templates)} = {100.0 * len(gcov_old) / len(templates):.2f}%",
        "new_only_d1": f"{len(gcov_extra)}/{len(templates)} = {100.0 * len(gcov_extra) / len(templates):.2f}%",
        "combined_d1": f"{len(gcov_new)}/{len(templates)} = {100.0 * len(gcov_new) / len(templates):.2f}%",
        "archived_hit": len(gcov_old),
        "combined_hit": len(gcov_new),
        "delta_hit": len(gcov_new) - len(gcov_old),
        "universe": len(templates),
    }
    (OUT / "unreached_merged_d1.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
