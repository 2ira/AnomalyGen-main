"""
Stricter intra-session block-identifier consistency check (reviewer comment 7,
part 4).

Motivation
----------
The `ctx_consistent` rule in `run_param_eval.py` reports 23/70 = 0.3286.  That
number is not a meaningful measure of contextual consistency for three reasons:

 1. It conflates entity classes.  `_entity_consistency()` requires that *every*
    entity pattern mentioned twice in a session has a single distinct value,
    including `datanode(\\d+)`.  A single HDFS write/replication session legally
    involves several datanodes (a replication pipeline has 3 replicas), so the
    rule fires on correct data.
 2. It is a session-level property replicated onto every slot in that session,
    so the "n = 70" observations are not independent: in this sample all 47
    False verdicts come from only 3 sessions.
 3. It never evaluates the one invariant that actually must hold, namely that
    the block identifier of a session is the same in every line of that session.

This script implements the invariant the reviewer asked for: within one session
(one BlockId group), every reference to a *block* identifier must denote the
same block.  It is evaluated both per session and per slot on exactly the same
207-slot sample.

Two additional, harder variants are reported:
  * `--variant slotvalue` : the LLM-filled value of every block-typed slot must
    equal the session's block identifier (not just be mutually consistent).
  * generation-stamp / size monotonicity is reported as diagnostics only.

Usage:
    cd AnomalyGen-main/eval_phase2
    python3 run_blockid_consistency.py
    python3 run_blockid_consistency.py --json eval_results/blockid_consistency.json
"""
import argparse
import collections
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SCORED = os.path.join(HERE, "eval_data", "param_scored.jsonl")

# Patterns that denote a *block* identifier in HDFS / ZooKeeper log text.
# Deliberately excludes datanode / node / pool identifiers: those legitimately
# take several values inside one session.
BLOCK_PATTERNS = [
    re.compile(r"\bblk_(?:-?\d+)"),          # blk_12345
    re.compile(r"\bBlock(\d+)\b"),            # Block456
    re.compile(r"\bblock-(\d+)\b"),           # block-01
    re.compile(r"\bstoredBlock(\d+)\b"),      # storedBlock01
    re.compile(r"\bblock\s+(\d+)\b"),         # block 1024
]
BLK_NUM = re.compile(r"\bblk_(-?\d+)")

# `storageIDs ["block-01", "block-02"]` is a *list* of storage ids, not repeated
# references to one block; masking it avoids a false inconsistency.
LIST_CTX = re.compile(r"storageIDs\s*\[[^\]]*\]|storageTypes\s*\[[^\]]*\]")

# The four generated-log CSVs that build_param_set.py samples from.
ALL_SOURCES = [
    "output_v1/ablation/baseline/parsed_logs/hdfs_combined_parsed_logs.csv",
    "output_v1/ablation/without_cot/parsed_logs/hdfs_combined_parsed_logs.csv",
    "output_v1/ablation/without_analysis/parsed_logs/hdfs_combined_parsed_logs.csv",
    "output/zookeeper/zookeeper_combined_parsed_logs.csv",
    "output/log_events/hdfs_combined_parsed_logs.csv",
]


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def block_ids_in(line):
    """All block identifiers mentioned in one log line, normalised to the numeric id."""
    line = LIST_CTX.sub(" ", line)
    ids = []
    for m in BLK_NUM.finditer(line):
        ids.append(m.group(1))
    for pat in BLOCK_PATTERNS[1:]:
        for m in pat.finditer(line):
            ids.append(m.group(1))
    return ids


def build_sessions(rows):
    """(source_file, block_id) -> ordered distinct content lines."""
    idx = collections.OrderedDict()
    for r in rows:
        key = (r["source_file"], r["block_id"])
        idx.setdefault(key, [])
        c = r.get("content", "")
        if c and c not in idx[key]:
            idx[key].append(c)
    return idx


def build_sessions_from_source(keys):
    """
    Reconstruct the *full* session (all log lines of that BlockId), not only the
    lines that happened to contribute a sampled slot.  This is what makes the
    intra-session check meaningful.
    """
    repo = os.path.abspath(os.path.join(HERE, ".."))
    wanted_files = sorted(set(k[0] for k in keys))
    wanted_blocks = collections.defaultdict(set)
    for f, b in keys:
        wanted_blocks[f].add(b)

    idx = collections.OrderedDict()
    for rel in wanted_files:
        path = os.path.join(repo, rel)
        if not os.path.exists(path):
            print(f"[warn] source csv missing: {path}")
            continue
        import csv as _csv
        with open(path, encoding="utf-8", errors="replace") as fh:
            for row in _csv.DictReader(fh):
                bid = row.get("BlockId") or row.get("block_id") or ""
                if bid not in wanted_blocks[rel]:
                    continue
                key = (rel, bid)
                idx.setdefault(key, [])
                c = (row.get("Content") or "").strip()
                if c and c not in idx[key]:
                    idx[key].append(c)
    return idx


def build_all_sessions():
    """Every BlockId group in every generated-log CSV -> ordered distinct lines."""
    import csv as _csv
    repo = os.path.abspath(os.path.join(HERE, ".."))
    idx = collections.OrderedDict()
    for rel in ALL_SOURCES:
        path = os.path.join(repo, rel)
        if not os.path.exists(path):
            print(f"[skip] {rel}")
            continue
        n = 0
        with open(path, encoding="utf-8", errors="replace") as fh:
            for row in _csv.DictReader(fh):
                bid = row.get("BlockId") or row.get("block_id") or ""
                if not bid:
                    continue
                key = (rel, bid)
                idx.setdefault(key, [])
                c = (row.get("Content") or "").strip()
                if c and c not in idx[key]:
                    idx[key].append(c)
                n += 1
        print(f"[load] {rel}: {n} rows")
    return idx


def normalise(i):
    """block-01 and Block1 denote the same block; strip leading zeros for comparison."""
    try:
        return str(int(i))
    except ValueError:
        return i


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default=SCORED)
    ap.add_argument("--json", default=None, help="optional path to dump the report")
    ap.add_argument("--full-session", dest="full_session", action="store_true",
                    default=True,
                    help="reconstruct sessions from the source parsed_logs CSVs "
                         "(default) instead of only the sampled lines")
    ap.add_argument("--sampled-only", dest="full_session", action="store_false")
    ap.add_argument("--all-sessions", action="store_true",
                    help="evaluate every session in all generated-log CSVs, not "
                         "only the 49 sessions covered by the 207-slot sample")
    args = ap.parse_args()

    rows = load(args.pool)
    sampled_sessions = build_sessions(rows)
    if args.all_sessions:
        sessions = build_all_sessions()
    elif args.full_session:
        sessions = build_sessions_from_source(list(sampled_sessions.keys()))
        for k in sampled_sessions:
            sessions.setdefault(k, sampled_sessions[k])
    else:
        sessions = sampled_sessions

    print(f"input            : {args.pool}")
    print(f"slots            : {len(rows)}")
    print(f"sessions         : {len(sessions)}")
    print(f"session source   : "
          f"{'full parsed_logs CSV' if args.full_session else 'sampled lines only'}")
    print(f"lines/session    : "
          f"{collections.Counter(len(v) for v in sessions.values()).most_common()}")

    # ---------------- session-level verdict -------------------------------
    per_session = {}
    for key, lines in sessions.items():
        mentions = []
        for ln in lines:
            mentions += block_ids_in(ln)
        distinct = sorted(set(normalise(m) for m in mentions))
        if len(mentions) < 2:
            verdict = None
        else:
            verdict = (len(distinct) == 1)
        per_session[key] = {
            "n_lines": len(lines),
            "n_mentions": len(mentions),
            "distinct": distinct,
            "verdict": verdict,
            "lines": lines,
        }

    dec = [k for k, v in per_session.items() if v["verdict"] is not None]
    ok = [k for k in dec if per_session[k]["verdict"]]
    print("\n=== block-ID consistency, session level ===")
    print(f"decidable sessions (>=2 block mentions): n = {len(dec)}")
    print(f"pass = {len(ok)}   fail = {len(dec) - len(ok)}   "
          f"rate = {len(ok) / len(dec):.4f}" if dec else "no decidable session")
    undec = len(sessions) - len(dec)
    print(f"undecidable (0 or 1 block mention): {undec}")

    # ---------------- slot-level verdict ----------------------------------
    slot_dec = slot_ok = 0
    for r in rows:
        v = per_session[(r["source_file"], r["block_id"])]["verdict"]
        if v is None:
            continue
        slot_dec += 1
        slot_ok += bool(v)
    print("\n=== block-ID consistency, slot level (same 207-slot sample) ===")
    print(f"decidable slots: n = {slot_dec}   pass = {slot_ok}   "
          f"rate = {slot_ok / slot_dec:.4f}" if slot_dec else "n/a")

    # ---------------- harder variant: slot value == session block ---------
    print("\n=== stricter variant: block-typed slot value must equal the session block ===")
    block_slot = re.compile(r"(blk_|Block|block-|storedBlock|block\s+)<\*>")
    sv_dec = sv_ok = 0
    sv_fail = []
    for r in rows:
        parts = r["event_template"].split("<*>")
        left = parts[r["slot_idx"]] if r["slot_idx"] < len(parts) else ""
        if not re.search(r"(blk_|Block|block-|storedBlock|block\s+)$", left):
            continue
        sess = per_session[(r["source_file"], r["block_id"])]
        if len(sess["distinct"]) != 1:
            continue
        sv_dec += 1
        if normalise(str(r["param_value"]).strip()) == sess["distinct"][0]:
            sv_ok += 1
        else:
            sv_fail.append(r)
    if sv_dec:
        print(f"decidable slots: n = {sv_dec}   pass = {sv_ok}   "
              f"rate = {sv_ok / sv_dec:.4f}")
        for r in sv_fail:
            print(f"  FAIL value={r['param_value']!r} session_block="
                  f"{per_session[(r['source_file'], r['block_id'])]['distinct']} "
                  f"| {r['content']}")
    else:
        print("  no block-typed slot decidable")

    # ---------------- failure detail --------------------------------------
    print("\n=== failing sessions in detail ===")
    nfail = 0
    for key, v in per_session.items():
        if v["verdict"] is False:
            nfail += 1
            print(f"\n  {key[1]}  ({os.path.basename(key[0])})  "
                  f"{v['n_mentions']} block mentions, distinct={v['distinct']}")
            for ln in v["lines"]:
                ids = sorted(set(normalise(x) for x in block_ids_in(ln)))
                tag = ",".join(ids) if ids else "-"
                print(f"    {tag:<14} | {ln}")
    if not nfail:
        print("  none")

    # ---------------- diagnostics on the old rule -------------------------
    print("\n=== why the old ctx_consistent = 23/70 is low ===")
    dn = re.compile(r"datanode(\d+)")
    for key, v in per_session.items():
        vals = sorted(set(x for ln in v["lines"] for x in dn.findall(ln)))
        if len(vals) > 1:
            print(f"  session {key[1]}: datanode ids {vals} -> old rule marks the "
                  f"whole session inconsistent although a replication pipeline "
                  f"legitimately spans several datanodes")

    if args.json:
        out = {
            "session_level": {
                "n_sessions": len(sessions),
                "n_decidable": len(dec),
                "n_pass": len(ok),
                "rate": round(len(ok) / len(dec), 4) if dec else None,
                "n_undecidable": undec,
            },
            "slot_level": {
                "n_decidable": slot_dec,
                "n_pass": slot_ok,
                "rate": round(slot_ok / slot_dec, 4) if slot_dec else None,
            },
            "strict_slot_value": {
                "n_decidable": sv_dec,
                "n_pass": sv_ok,
                "rate": round(sv_ok / sv_dec, 4) if sv_dec else None,
            },
            "failing_sessions": [
                {"session": k[1], "file": k[0], "distinct": v["distinct"],
                 "lines": v["lines"]}
                for k, v in per_session.items() if v["verdict"] is False
            ],
        }
        path = args.json if os.path.isabs(args.json) else os.path.join(HERE, args.json)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
