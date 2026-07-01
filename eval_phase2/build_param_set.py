"""
Experiment B step 4: extract filled parameter instances (template slot <*> aligned
with actual values) from parsed_logs/*.csv and perform stratified sampling.

Why parsed_logs CSV instead of *_compressed_log.json:
  The CSV provides both EventTemplate (with <*> slots) and ParameterList (filled
  values) in alignment, enabling reliable "slot semantics -> type/format"
  validation.  The compressed_log only has the inlined full-text lines, requiring
  regex-based type guessing which is less reliable.

Data sources are configurable via --inputs (any parsed_logs CSV paths).

Output: eval_phase2/eval_data/param_pool.jsonl
Each line is one filled slot instance:
{
  "param_id": "<file>::<lineid>::<slot_idx>",
  "source_file": "...",
  "block_id": "26a3b790_1",
  "event_id": "441943f0",
  "event_template": "Changing meta file offset of block <*> from <*> to <*>",
  "content": "Changing meta file offset of block 1024 from 2048 to 4096",
  "slot_idx": 0,                     # which <*> slot (0-indexed)
  "param_value": "1024",
  "slot_type": "int",               # semantic type inferred from template context
  "slot_context": "block",          # nearest hint word to the left of <*>
  "param_list": ["1024","2048","4096"],
  "type_valid": null,               # <- filled by run_param_eval rules / manual review
  "ctx_consistent": null            # <- filled by run_param_eval rules / manual review
}
"""
import os
import re
import csv
import ast
import argparse
import random

import common as C


# Semantic type inference: determine slot type based on hint words to the left/right
# of each template slot <*>.  Returns (slot_type, slot_context).
# slot_type determines which validator run_param_eval uses.
#
# IMPORTANT: The log parser (Drain) may fragment a single token at hex-letter boundaries,
#   e.g. 0x2b3a becomes "...<*>x<*>a<*>b<*>c" in the template.  Such fragments are NOT
#   LLM parameter-filling errors and must be identified as hex_fragment, otherwise
#   Phase II parameter quality would be unfairly penalised.
HEX_CTX = re.compile(r"(session|0x|mask|trace\s*mask|sessionid|zxid)\s*$", re.IGNORECASE)
PATH_CTX = re.compile(r"(path|directory|dir|file|for)\s*$", re.IGNORECASE)
INT_RIGHT_MB = re.compile(r"^\s*MB\b", re.IGNORECASE)
MS_RIGHT = re.compile(r"^\s*ms\b", re.IGNORECASE)
COUNT_CTX = re.compile(r"(times|retried|count|number|to\s+zxid)\s*$", re.IGNORECASE)
NODEID_CTX = re.compile(
    r"(namenode|datanode|node|pool[\w]*|block|blk|block-|node-|blk_|block_|priority\s+queue)[\s\-_]*$",
    re.IGNORECASE)
# Parser-fragmented hex: right side looks like "x<*>a<*>b..." or left side ends with a hex char + x
HEX_FRAG_RIGHT = re.compile(r"^[0-9a-fA-FxX]")
HEX_FRAG_LEFT = re.compile(r"[0-9a-fA-F]?[xX]?$")
# IP quad: surrounding pattern ".<*>.<*>." indicates an IP address fragment
IP_CTX = re.compile(r"\.\s*$")
PORT_CTX = re.compile(r"port\s*$", re.IGNORECASE)


def _is_hex_fragment(template: str, slot_idx: int, parts) -> bool:
    """Check whether this slot is part of a parser-fragmented hex string (e.g. <*>x<*>a<*>b<*>c)."""
    # Pattern "x<*>" followed by multiple single-char-separated <*> is typical of fragmented 0x..
    if re.search(r"[xX]<\*>[0-9a-fA-F]<\*>", template):
        # Left/right connectors are single hex chars or x -> classified as fragment
        left = parts[slot_idx][-2:] if slot_idx < len(parts) else ""
        right = parts[slot_idx + 1][:1] if slot_idx + 1 < len(parts) else ""
        if re.search(r"[0-9a-fA-FxX]$", left) or HEX_FRAG_RIGHT.match(right or " "):
            return True
    return False


def _is_ip_fragment(template: str, slot_idx: int, parts) -> bool:
    """Check whether this slot is part of an IP address fragmented as <*>.<*>.<*>.<*>."""
    if re.search(r"<\*>\.<\*>\.<\*>\.<\*>", template):
        left = parts[slot_idx][-1:] if slot_idx < len(parts) else ""
        right = parts[slot_idx + 1][:1] if slot_idx + 1 < len(parts) else ""
        if left == "." or right == ".":
            return True
    return False


def infer_slot_type(template: str, slot_idx: int):
    """
    Given a template and the index of the slot_idx-th <*>, infer its semantic
    type and context hint word.

    Type catalogue:
      hex          Hex identifier (session/mask/zxid)
      hex_fragment Parser-fragmented hex substring (single hex char validation)
      ip_fragment  Parser-fragmented IP segment (integer 0-255)
      path         File / directory path
      int          Pure integer (size/count/duration etc.)
      port         Network port (0-65535)
      nodeid       Node/pool/block identifier (namenode<*>, block-<*>, blk_<*>)
      status       Status/enum word (started/completed/active...)
      generic      Undetermined semantics; only non-empty check
    """
    parts = template.split("<*>")
    left = parts[slot_idx] if slot_idx < len(parts) else ""
    right = parts[slot_idx + 1] if slot_idx + 1 < len(parts) else ""
    left_tail = left[-40:]

    if _is_hex_fragment(template, slot_idx, parts):
        return "hex_fragment", "hex_frag"
    if _is_ip_fragment(template, slot_idx, parts):
        return "ip_fragment", "ip_seg"
    if HEX_CTX.search(left_tail):
        return "hex", _last_word(left_tail)
    if PORT_CTX.search(left_tail):
        return "port", "port"
    if PATH_CTX.search(left_tail):
        return "path", _last_word(left_tail)
    if INT_RIGHT_MB.search(right):
        return "int", "size_MB"
    if MS_RIGHT.search(right):
        return "int", "duration_ms"
    if COUNT_CTX.search(left_tail):
        return "int", _last_word(left_tail)
    if NODEID_CTX.search(left_tail):
        return "nodeid", _last_word(left_tail)
    return "generic", _last_word(left_tail) or "generic"


def _last_word(s: str) -> str:
    toks = re.findall(r"[A-Za-z_]+", s)
    return toks[-1].lower() if toks else ""


def _looks_status(v: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z\-]*", v))


def parse_param_list(raw: str):
    """Parse ParameterList cell (e.g. "['1024', '2048']" or []) into a Python list."""
    raw = (raw or "").strip()
    if not raw or raw == "[]":
        return []
    try:
        v = ast.literal_eval(raw)
        return [str(x) for x in v] if isinstance(v, (list, tuple)) else [str(v)]
    except (ValueError, SyntaxError):
        return [s.strip().strip("'\"") for s in raw.strip("[]").split(",") if s.strip()]


def extract_params_from_csv(path: str) -> list:
    out = []
    fname = os.path.relpath(path, C.REPO_ROOT)
    with open(path, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            template = (row.get("EventTemplate") or "").strip()
            params = parse_param_list(row.get("ParameterList", ""))
            n_slots = template.count("<*>")
            if n_slots == 0 or not params:
                continue
            # Slot count and param count should match; on mismatch, align by min and flag it
            n = min(n_slots, len(params))
            for i in range(n):
                slot_type, slot_ctx = infer_slot_type(template, i)
                # Re-classify generic slots whose value looks like a status word
                if slot_type == "generic" and _looks_status(params[i]):
                    slot_type = "status"
                out.append({
                    "param_id": f"{fname}::{row.get('LineId','?')}::{i}",
                    "source_file": fname,
                    "block_id": row.get("BlockId", ""),
                    "event_id": row.get("EventId", ""),
                    "event_template": template,
                    "content": (row.get("Content") or "").strip(),
                    "slot_idx": i,
                    "param_value": params[i],
                    "slot_type": slot_type,
                    "slot_context": slot_ctx,
                    "param_list": params,
                    "slot_count_mismatch": (n_slots != len(params)),
                    "type_valid": None,
                    "ctx_consistent": None,
                })
    return out


def stratified_sample(pool: list, n: int, seed: int) -> list:
    """
    Two-phase sampling that prioritises cross-entry consistency coverage:
    1) Group by block_id; prioritise blocks with >=2 param entries (keep all
       entries so ctx_consistent rules have sufficient cross-entry comparisons);
    2) Fill remaining quota from single-entry blocks via slot_type-stratified
       sampling to maintain type coverage.
    """
    rng = random.Random(seed)
    # Group by block
    by_block: dict = {}
    for p in pool:
        by_block.setdefault(p["block_id"], []).append(p)
    multi = {bid: items for bid, items in by_block.items() if len(items) >= 2}
    single = {bid: items for bid, items in by_block.items() if len(items) == 1}

    # Include all multi-entry blocks first (ctx_consistent coverage is most critical)
    selected = []
    multi_keys = sorted(multi.keys())
    rng.shuffle(multi_keys)
    for bid in multi_keys:
        selected.extend(multi[bid])
        if len(selected) >= n:
            break

    # Fill remaining quota from single-entry blocks, stratified by slot_type
    remaining = n - len(selected)
    if remaining > 0:
        singles = [items[0] for items in single.values()]
        rng.shuffle(singles)
        # Allocate proportionally by slot_type
        type_groups: dict = {}
        for p in singles:
            type_groups.setdefault(p["slot_type"], []).append(p)
        total_single = len(singles)
        for stype, items in type_groups.items():
            quota = max(1, round(remaining * len(items) / max(total_single, 1)))
            selected.extend(items[:quota])
        selected = selected[:n]

    rng.shuffle(selected)
    return selected


# Default gpt-4o parsed_logs CSVs in the repository (readily available for Experiment B)
DEFAULT_INPUTS = [
    "output_v1/ablation/baseline/parsed_logs/hdfs_combined_parsed_logs.csv",
    "output_v1/ablation/without_cot/parsed_logs/hdfs_combined_parsed_logs.csv",
    "output_v1/ablation/without_analysis/parsed_logs/hdfs_combined_parsed_logs.csv",
    "output/zookeeper/zookeeper_combined_parsed_logs.csv",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", nargs="+", default=DEFAULT_INPUTS,
                    help="parsed_logs CSV paths (can point to DeepSeek variant outputs)")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    C.ensure_dirs()
    pool = []
    for inp in args.inputs:
        path = inp if os.path.isabs(inp) else os.path.join(C.REPO_ROOT, inp)
        if not os.path.exists(path):
            print(f"[skip] not found: {path}")
            continue
        items = extract_params_from_csv(path)
        print(f"[{inp}] extracted {len(items)} filled-slot instances")
        pool.extend(items)

    sampled = stratified_sample(pool, args.n, args.seed)
    # Stratum distribution overview
    dist = {}
    for s in sampled:
        dist[s["slot_type"]] = dist.get(s["slot_type"], 0) + 1
    out = os.path.join(C.EVAL_DATA_DIR, "param_pool.jsonl")
    C.write_jsonl(out, sampled)
    print(f"pool total={len(pool)}, sampled {len(sampled)} -> {out}")
    print(f"  slot_type distribution: {dist}")


if __name__ == "__main__":
    main()
