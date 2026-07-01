"""
Phase II evaluation utilities: data loading, call-graph parsing, XML parsing,
and merge-point extraction.

Re-uses the parsing logic from main/merge_node.py and main/ablation_merge_node.py
to ensure the evaluation targets are consistent with the paper pipeline.
"""
import os
import re
import json
import random
from typing import Dict, List, Tuple, Optional


# --------------------------------------------------------------------------
# Path resolution (relative to repository root AnomalyGen-main)
# --------------------------------------------------------------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_data")
EVAL_RESULT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_results")


def ensure_dirs():
    os.makedirs(EVAL_DATA_DIR, exist_ok=True)
    os.makedirs(EVAL_RESULT_DIR, exist_ok=True)


def load_json(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def write_jsonl(path: str, rows: List[dict]):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path: str) -> List[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# --------------------------------------------------------------------------
# Call-graph parsing (lightweight equivalent of main/merge_node.py::parse_call_file)
# --------------------------------------------------------------------------
def parse_call_file(filename: str) -> Dict[str, List[str]]:
    """Return simple_call_graph: caller -> [callee, ...]"""
    graph: Dict[str, List[str]] = {}
    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or "->" not in line:
                continue
            parts = line.split("->")
            if len(parts) != 2:
                continue
            caller = parts[0].strip()
            rest = parts[1].strip()
            callee = rest.rsplit(", depth", 1)[0].strip() if ", depth" in rest else rest
            if not caller or not callee:
                continue
            graph.setdefault(caller, []).append(callee)
    return graph


def list_entry_dirs(system: str) -> List[str]:
    """List all entry sub-directories under output/<system>/ that contain pruned_call_deps.txt."""
    base = os.path.join(REPO_ROOT, "output", system)
    if not os.path.isdir(base):
        return []
    dirs = []
    for name in os.listdir(base):
        d = os.path.join(base, name)
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "pruned_call_deps.txt")):
            dirs.append(d)
    return dirs


# --------------------------------------------------------------------------
# Whether a single node's log sequence is valid (matches the non-empty check in merge_node)
# --------------------------------------------------------------------------
def has_valid_log(single_log_map: dict, node: str) -> bool:
    v = single_log_map.get(node, "")
    return bool(v) and isinstance(v, str) and v.strip() != ""


# --------------------------------------------------------------------------
# Heuristic stratum labels for stratified sampling (not ground truth)
# --------------------------------------------------------------------------
_BRANCH_KW = re.compile(r"\b(if|for|while|foreach|switch)\b", re.IGNORECASE)
_THROW_KW = re.compile(r"\b(throw|throws|exception|catch)\b", re.IGNORECASE)


def as_code_str(code) -> str:
    """Value in extracted_methods.json may be str/list/dict; normalise to an analysable string."""
    if code is None:
        return ""
    if isinstance(code, str):
        return code
    if isinstance(code, (list, tuple)):
        return "\n".join(as_code_str(x) for x in code)
    if isinstance(code, dict):
        # Prefer common fields (e.g. {"source": "...", "signature": "..."})
        for k in ("source", "code", "body", "content"):
            if k in code:
                return as_code_str(code[k])
        return json.dumps(code, ensure_ascii=False)
    return str(code)


def stratum_of(caller_code, callee_code) -> str:
    """Return the stratum key for stratified sampling."""
    has_branch = bool(_BRANCH_KW.search(as_code_str(caller_code)))
    callee_throws = bool(_THROW_KW.search(as_code_str(callee_code)))
    return f"branch={int(has_branch)}_throw={int(callee_throws)}"


# --------------------------------------------------------------------------
# Parse merge-LLM XML output -> system-decided (valid_path_ids, pruned_path_ids)
# --------------------------------------------------------------------------
def parse_merge_xml(message: str) -> Tuple[List[str], List[str]]:
    """
    Extract valid / pruned paths from the LLM-returned <merge_result>.
    Returns (valid_ids, pruned_ids).

    Key: The CoT variant (get_merge_nodes_by_llm_v7) uses <wrong_path> to mark
    pruned paths, while the no-CoT variant (get_merge_nodes_by_llm_without_cot)
    uses <pruned_paths>.  Both tags must be parsed; otherwise CoT results would
    miss pruned paths (a bug in the original scheme).
    """
    if not message:
        return [], []
    valid_ids, pruned_ids = [], []

    valid_block = re.search(r"<valid_paths>(.*?)</valid_paths>", message, re.DOTALL)
    if valid_block:
        for pid in re.findall(r"<id>(.*?)</id>", valid_block.group(1), re.DOTALL):
            valid_ids.append(pid.strip())

    # No-CoT variant: <pruned_paths>; path may be <path id="..."/> or <path>...<id>..</id>..</path>
    pruned_block = re.search(r"<pruned_paths>(.*?)</pruned_paths>", message, re.DOTALL)
    if pruned_block:
        pruned_ids += [m.strip() for m in re.findall(r'id="(.*?)"', pruned_block.group(1))]
        pruned_ids += [m.strip() for m in re.findall(r"<id>(.*?)</id>", pruned_block.group(1), re.DOTALL)]

    # CoT variant: <wrong_path>; may contain id list, <path .../>, or free text (non-empty = pruned)
    wrong_block = re.search(r"<wrong_path>(.*?)</wrong_path>", message, re.DOTALL)
    if wrong_block:
        body = wrong_block.group(1)
        pruned_ids += [m.strip() for m in re.findall(r'id="(.*?)"', body)]
        pruned_ids += [m.strip() for m in re.findall(r"<id>(.*?)</id>", body, re.DOTALL)]
        # No explicit id but substantive text (explains why pruned) -> anonymous pruned entry
        if not pruned_ids and body.strip():
            pruned_ids.append("__wrong_path_text__")

    # Deduplicate and remove empty entries
    valid_ids = [v for v in dict.fromkeys(valid_ids) if v]
    pruned_ids = [p for p in dict.fromkeys(pruned_ids) if p]
    return valid_ids, pruned_ids


def system_decision_is_feasible(message: str) -> Optional[bool]:
    """
    Reduce the full merge output to a boolean: is the merge point feasible?

    Rule: at least one valid_path with <eval>true</eval> -> feasible;
    only appears in pruned -> infeasible.

    TODO: When a merge point produces multiple paths, align to the specific
    path_id sampled in build_feasibility_set (see run_feasibility_eval).
    """
    valid_ids, pruned_ids = parse_merge_xml(message)
    has_true_eval = bool(re.search(r"<eval>\s*true\s*</eval>", message, re.IGNORECASE))
    if valid_ids and has_true_eval:
        return True
    if pruned_ids and not valid_ids:
        return False
    if valid_ids:
        return True
    if pruned_ids:
        return False
    return None  # Cannot parse; the caller should treat this as a parse failure
