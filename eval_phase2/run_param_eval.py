"""
Experiment B step 5: fully automated rule-based scoring on sampled filled
template slots (zero LLM calls, zero re-runs).  Optionally ingests a small
human-annotated sample to compute agreement (Cohen's kappa).

Two dimensions:
  - type_valid     : whether the slot value conforms to the format convention
                     of its semantic type (validated per slot_type)
  - ctx_consistent : cross-entry consistency within the same block
        * Hex identifiers in the same BlockId should be consistent
        * "from X to Y" offset chains should be monotonically increasing
        * Same nodeid/path across siblings should be stable
      Samples that cannot be decided by rules -> None (left for manual review).

Input : eval_phase2/eval_data/param_pool.jsonl
Output: eval_phase2/eval_data/param_scored.jsonl
Optional: --human eval_phase2/eval_data/param_human.jsonl  (human-annotated subset for kappa)
"""
from __future__ import annotations

import os
import re
import csv
import ast
import argparse
import collections

import common as C


# --------------------------------------------------------------------------
# Dimension 1: type / format validity (per slot_type)
# --------------------------------------------------------------------------
def _valid_hex(v: str) -> bool:
    return bool(re.fullmatch(r"0x[0-9a-fA-F]+", v.strip()))


def _valid_path(v: str) -> bool:
    v = v.strip()
    return v.startswith("/") and " " not in v and bool(re.fullmatch(r"/[\w./\-]+", v))


def _valid_int(v: str) -> bool:
    return bool(re.fullmatch(r"\d+", v.strip()))


# Drain template already carries the role prefix. The slot is the numeric suffix
# (namenode01 -> "01", datanode02 -> "02", node-01 -> "01"). A full hostname such
# as "namenode01" stuffed into node-<*> or datanode<*> is type-invalid.
ROLE_PREFIX_LEFT = re.compile(
    r"(namenode|datanode|node-|(?<![A-Za-z])node)\s*$",
    re.IGNORECASE,
)
HOST_IN_VALUE = re.compile(r"(?i)(namenode|datanode)")


def _valid_nodeid(v: str, item: dict | None = None) -> bool:
    v = (v or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", v):
        return False
    if not item:
        return True
    tmpl = item.get("event_template") or ""
    try:
        idx = int(item.get("slot_idx") or 0)
    except (TypeError, ValueError):
        idx = 0
    parts = tmpl.split("<*>")
    left = parts[idx] if idx < len(parts) else ""
    if ROLE_PREFIX_LEFT.search(left[-40:]):
        if HOST_IN_VALUE.search(v):
            return False
        return bool(re.fullmatch(r"\d+", v))
    return True


def _valid_status(v: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z\-]*", v.strip()))


def _valid_hex_fragment(v: str) -> bool:
    # Parser-fragmented hex substring: should be 1+ hex chars (e.g. '2b3', 'A', '4')
    return bool(re.fullmatch(r"[0-9a-fA-F]+", v.strip()))


def _valid_ip_segment(v: str) -> bool:
    # One fragment of a parser-split IP address: should be an integer in 0-255
    v = v.strip()
    return v.isdigit() and 0 <= int(v) <= 255


def _valid_port(v: str) -> bool:
    v = v.strip()
    return v.isdigit() and 0 <= int(v) <= 65535


TYPE_VALIDATORS = {
    "hex": _valid_hex,
    "hex_fragment": _valid_hex_fragment,
    "ip_fragment": _valid_ip_segment,
    "port": _valid_port,
    "path": _valid_path,
    "int": _valid_int,
    "nodeid": _valid_nodeid,
    "status": _valid_status,
    # generic: can only check "non-empty and no obvious contradiction"; left as None to avoid false positives
    "generic": None,
}


def score_type_validity(item: dict):
    stype = item.get("slot_type")
    if stype == "generic":
        return None
    if stype == "nodeid":
        return bool(_valid_nodeid(str(item.get("param_value", "")), item))
    fn = TYPE_VALIDATORS.get(stype)
    if fn is None:
        return None
    return bool(fn(str(item["param_value"])))


# --------------------------------------------------------------------------
# Dimension 2: cross-entry consistency
# Requires a global view: aggregate all entries by (source_file, block_id).
# --------------------------------------------------------------------------
HEX_RE = re.compile(r"0x[0-9a-fA-F]+")
OFFSET_TMPL = "Changing meta file offset of block <*> from <*> to <*>"
# General entity references (block id / blk_ / node- / datanode etc.) for same-sequence entity consistency
ENTITY_RES = [
    re.compile(r"blk_(\d+)"),
    re.compile(r"block-(\d+)"),
    re.compile(r"node-(\d+)"),
    re.compile(r"datanode(\d+)"),
    re.compile(r"namenode(\d+)"),
    re.compile(r"data_pool_(\d+)"),
]


def build_block_index(rows):
    """(source_file, block_id) -> all content lines in the sequence (deduplicated, order-preserving)."""
    idx = collections.defaultdict(list)
    for r in rows:
        key = (r["source_file"], r["block_id"])
        c = r.get("content", "")
        if c and c not in idx[key]:
            idx[key].append(c)
    return idx


def score_ctx_consistency(item: dict, block_index) -> object:
    key = (item["source_file"], item["block_id"])
    siblings = block_index.get(key, [])
    stype = item["slot_type"]
    val = str(item["param_value"])

    # (a) Hex identifiers: multiple hex values within the same block should be consistent
    if stype in ("hex", "hex_fragment"):
        hexes = []
        for line in siblings:
            hexes += HEX_RE.findall(line)
        if len(hexes) >= 2:
            return len(set(hexes)) == 1  # Multiple references in same session should be consistent
        # Fallback: use general entity consistency
        return _entity_consistency(siblings)

    # (b) "from X to Y" offset chains should be monotonically increasing within the same block
    if item["event_template"] == OFFSET_TMPL:
        chain = []
        for line in siblings:
            m = re.search(r"from\s+(\d+)\s+to\s+(\d+)", line)
            if m:
                chain.append((int(m.group(1)), int(m.group(2))))
        if not chain:
            return None
        return bool(all(a < b for a, b in chain))

    # (c) General: repeated entity identifiers within the same block should be consistent
    if stype in ("nodeid", "int", "ip_fragment", "port"):
        return _entity_consistency(siblings)

    return None


def _entity_consistency(siblings) -> object:
    """
    Within the same block, each entity type (blk_/node-/datanode...) should have
    consistent values if mentioned multiple times.
    Returns True/False; returns None if no comparable entities exist.
    """
    judged = False
    for pat in ENTITY_RES:
        vals = []
        for line in siblings:
            vals += pat.findall(line)
        if len(vals) >= 2:
            judged = True
            if len(set(vals)) != 1:
                return False
    return True if judged else None


# --------------------------------------------------------------------------
# Cohen's kappa (automated rules vs human annotation, binary)
# --------------------------------------------------------------------------
def cohen_kappa(pairs):
    """pairs: list of (auto_bool, human_bool); only counts pairs where both are non-None."""
    pairs = [(a, h) for a, h in pairs if a is not None and h is not None]
    n = len(pairs)
    if n == 0:
        return None, 0
    a1 = sum(1 for a, _ in pairs if a)
    h1 = sum(1 for _, h in pairs if h)
    po = sum(1 for a, h in pairs if a == h) / n
    pe = (a1 / n) * (h1 / n) + (1 - a1 / n) * (1 - h1 / n)
    if abs(1 - pe) < 1e-9:
        return 1.0, n
    return round((po - pe) / (1 - pe), 4), n


def load_human(path):
    """Load human annotations: each line is {param_id, type_valid_human, ctx_consistent_human}."""
    out = {}
    if not path or not os.path.exists(path):
        return out
    for r in C.read_jsonl(path):
        out[r["param_id"]] = r
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default=os.path.join(C.EVAL_DATA_DIR, "param_pool.jsonl"))
    ap.add_argument("--human", default=os.path.join(C.EVAL_DATA_DIR, "param_human.jsonl"),
                    help="optional: human-annotated subset for computing Cohen's kappa")
    args = ap.parse_args()

    C.ensure_dirs()
    if not os.path.exists(args.pool):
        raise SystemExit(f"Not found: {args.pool}; please run build_param_set.py first")

    rows = C.read_jsonl(args.pool)
    block_index = build_block_index(rows)

    n_auto_type = n_auto_ctx = 0
    for item in rows:
        tv = score_type_validity(item)
        item["type_valid"] = tv
        if tv is not None:
            n_auto_type += 1
        cc = score_ctx_consistency(item, block_index)
        item["ctx_consistent"] = cc
        if cc is not None:
            n_auto_ctx += 1

    out = os.path.join(C.EVAL_DATA_DIR, "param_scored.jsonl")
    C.write_jsonl(out, rows)
    print(f"scored {len(rows)} items -> {out}")
    print(f"  rule-decidable type_valid: {n_auto_type}/{len(rows)}; ctx_consistent: {n_auto_ctx}/{len(rows)}")

    # --- If human-annotated subset is available, output agreement / kappa ---
    human = load_human(args.human)
    if human:
        tv_pairs, cc_pairs = [], []
        for item in rows:
            h = human.get(item["param_id"])
            if not h:
                continue
            tv_pairs.append((item["type_valid"], h.get("type_valid_human")))
            cc_pairs.append((item["ctx_consistent"], h.get("ctx_consistent_human")))
        k_tv, n_tv = cohen_kappa(tv_pairs)
        k_cc, n_cc = cohen_kappa(cc_pairs)
        print(f"  [human agreement] type_valid κ={k_tv} (n={n_tv}); "
              f"ctx_consistent κ={k_cc} (n={n_cc})")
    else:
        print(f"  (--human not provided; to compute agreement, prepare {args.human}:")
        print(f"    each line: {{\"param_id\":..., \"type_valid_human\":true/false, \"ctx_consistent_human\":true/false}})")


if __name__ == "__main__":
    main()
