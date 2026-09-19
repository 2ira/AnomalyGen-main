#!/usr/bin/env python3
"""Score ctx v2: one session = one path filled by Phase III.

Pass iff ≥2 block identifiers are mentioned and they all normalise to one id.
Datanode / node / pool identifiers are ignored.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(HERE)
sys.path.insert(0, EVAL)
from common import read_jsonl  # noqa: E402

BLK = re.compile(r"\bblk_(-?\d+)", re.IGNORECASE)
BLOCK = re.compile(r"\b(?:stored)?block-?(\d+)\b", re.IGNORECASE)
LIST_CTX = re.compile(r"storageIDs\s*\[[^\]]*\]|storageTypes\s*\[[^\]]*\]", re.I)
LOG_SEQ = re.compile(r"<log_seq>(.*?)</log_seq>|<log_sequence>(.*?)</log_sequence>",
                     re.DOTALL | re.I)


def block_ids(text):
    text = LIST_CTX.sub(" ", text or "")
    ids = [m.group(1) for m in BLK.finditer(text)]
    ids += [m.group(1) for m in BLOCK.finditer(text)]
    norm = []
    for i in ids:
        try:
            norm.append(str(int(i)))
        except ValueError:
            norm.append(i)
    return norm


def filled_text(raw):
    m = LOG_SEQ.search(raw or "")
    if m:
        return (m.group(1) or m.group(2) or "").strip()
    return raw or ""


def score_row(r):
    text = filled_text(r.get("raw_response") or "")
    ids = block_ids(text)
    distinct = sorted(set(ids))
    if len(ids) < 2:
        verdict = None
    else:
        verdict = len(distinct) == 1
    return {
        "session_id": r.get("session_id"),
        "method": r.get("method"),
        "n_mentions": len(ids),
        "distinct": distinct,
        "verdict": verdict,
        "finish_reason": r.get("finish_reason"),
        "filled_excerpt": text[:400],
    }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True)
    args = ap.parse_args()
    rows = [score_row(r) for r in read_jsonl(args.pred)]
    dec = [r for r in rows if r["verdict"] is not None]
    ok = [r for r in dec if r["verdict"]]
    report = {
        "n_sessions": len(rows),
        "n_decidable": len(dec),
        "n_pass": len(ok),
        "n_fail": len(dec) - len(ok),
        "n_undecidable": len(rows) - len(dec),
        "rate": round(len(ok) / len(dec), 4) if dec else None,
        "failing": [r for r in dec if not r["verdict"]],
        "rows": rows,
    }
    out = args.pred.replace(".jsonl", "_scored.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(json.dumps({k: report[k] for k in
                      ("n_sessions", "n_decidable", "n_pass", "n_fail",
                       "n_undecidable", "rate")}, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
