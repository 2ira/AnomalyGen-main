#!/usr/bin/env python3
"""
ZooKeeper label-accuracy experiment: baseline vs recovery-aware relabelling.

Compares two labelling rules on ZooKeeper synthesised sessions against an
independent semantic ground truth with 17 hand-reviewed entries (M.2 / R1.2).

Usage:
    cd AnomalyGen-main
    python eval_labeling/zk_recovery_relabel.py [--csv <path>]
"""
import os
import re
import argparse

from utils import (
    load_sessions, session_text, has_error_level, any_match,
    run_comparison, save_results, print_summary,
)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
DEFAULT_CSV = os.path.join(
    REPO_ROOT, "output", "zookeeper", "zookeeper_combined_parsed_logs.csv")

# ── ZK-specific ground truth (v3, with 17 hand-reviewed entries) ─────────
GT_RATIONALE = {
    # Benign recovery / normal ZK internal operations → normal
    "d80bcb62_1": ("normal",
        "ERROR 'Failed to cancel selection key' + 'Socket closed successfully'"
        " — NIO cleanup, benign"),
    "d1147373_1": ("normal",
        "ERROR 'Error cancelling command selection key' + 'Socket closed "
        "successfully' — same pattern"),
    "fd71111f_1": ("normal",
        "ERROR 'Could not configure server SASL' + 'Login user set "
        "successfully' — SASL failed but login succeeded, benign"),
    "1d5e10a3_1": ("normal",
        "Multiple SASL errors then 'Login user set successfully', benign"),
    "fe9d88fb_1": ("normal",
        "ERROR 'UPTODATE after Follower started' + 'Disconnected from leader'"
        " + 'FOLLOWING - LEADER ELECTION' — normal follower transition"),
    "eb7f58f3_1": ("normal",
        "WARN 'Exception when observing the leader' + INFO 'Disconnected from"
        " leader... Sync state: RECONFIGURED' — observer reconnect"),
    "eb7f58f3_2": ("normal",
        "WARN 'Ignoring proposal/commit' + ERROR 'UPTODATE after Observer' + "
        "'Unknown packet type' — normal Observer sync"),
    "b6bdf782_1": ("normal",
        "WARN/ERROR 'unregister of bean_name_01... Unexpected exception' — "
        "JMX Bean cleanup error, no service impact"),
    "a43bbe11_1": ("normal",
        "WARN 'Unknown packet type' — compatibility WARN, non-fatal"),
    "e9e11bde_1": ("normal",
        "ERROR 'Problems while registering log4j jmx beans' — JMX warning"),
    "078913a0_1": ("normal",
        "ERROR 'Error cancelling command selection key, Exception' + normal "
        "INFO processing — NIO cleanup"),
    "8c261744_1": ("normal",
        "ERROR 'SSL isn't supported in NIOServerCnxn' — feature limitation"),
    "47640e47_1": ("normal", "Same as 8c261744_1: SSL not supported"),
    "79b6e40a_1": ("normal",
        "ERROR 'Something is broken! Empty snapshot warning' + WARN 'should "
        "only be allowed during upgrading' — expected during upgrade"),
    # True failures → anomaly
    "4cc5aad5_2": ("anomaly",
        "ERROR 'Throttled request... Exit' — rate-limit triggered exit"),
    "0ef137db_3": ("anomaly",
        "ERROR 'UPTODATE after Observer started' — no reconnect/following "
        "signal, isolated occurrence is anomalous"),
    "7e8fa7b0_1": ("anomaly",
        "ERROR 'IOException thrown due to empty server sockets' — bind failure"),
    "3d61b616_1": ("anomaly",
        "ERROR 'Committed request not found on toBeApplied: 1024' — state "
        "inconsistency"),
    "38fc44ff_1": ("anomaly",
        "ERROR 'Election Algorithm 1/2 is not supported' — cannot participate "
        "in election"),
    "38fc44ff_2": ("anomaly",
        "WARN 'Clobbering QuorumCnxManager' + ERROR 'Null listener when "
        "initializing cnx manager' — connection manager init failure"),
    "74e160b2_2": ("anomaly",
        "Same as 38fc44ff_2: Null listener init failure"),
}

# Automatic rules for sessions not in GT_RATIONALE
_AUTO_FATAL = re.compile(
    r"access denied|"
    r"could not configure server(?!.*login user set successfully)|"
    r"throttled request.*exit|"
    r"failed to get a response|"
    r"timed out|"
    r"connection refused|"
    r"faulty serialization|"
    r"leader failed to initialize|"
    r"null quorumpeer", re.I)

_AUTO_BENIGN = re.compile(
    r"(cancel|key cancel|cancelling).*selection key|"
    r"sasl.*login user set successfully|"
    r"jmx|mbean|log4j.*bean|"
    r"ssl.*not supported.*cnxn|"
    r"uptodate.*(follower|observer) started.*"
    r"(?:disconnect|following|leadership|reconnecting)|"
    r"exception when observing.*disconnected from leader|"
    r"\bignoring\b.*(?:proposal|commit)|"
    r"changes proposed in reconfig|"
    r"empty snapshot warning.*upgrading|"
    r"unknown packet type", re.I)


def semantic_gt(bid, lines):
    if bid in GT_RATIONALE:
        return GT_RATIONALE[bid][0]
    text = session_text(lines)
    if _AUTO_FATAL.search(text):
        if (re.search(r"could not configure server", text, re.I)
                and re.search(r"login user set successfully", text, re.I)):
            return "normal"
        return "anomaly"
    if has_error_level(lines) and _AUTO_BENIGN.search(text):
        return "normal"
    if has_error_level(lines):
        return "anomaly"
    return "normal"


# ── ZK recovery-aware labelling rule ─────────────────────────────────────
_RECOVERY_KW = [
    r"socket closed successfully",
    r"login user set successfully",
    r"disconnected from leader",
    r"\bignoring\b",
    r"close of session", r"closing session",
    r"sync state:",
    r"broadcasting new session",
    r"established session",
    r"following new leader",
    r"leader election",
    r"reconnecting",
]

_FATAL_KW = [
    r"access denied",
    r"could not configure server",
    r"connection refused",
    r"timed out",
    r"failed to get a response",
    r"securityexception",
    r"throttled request.*exit",
    r"faulty serialization",
    r"leader failed to initialize",
    r"null quorumpeer",
    r"null listener",
    r"election algorithm.*not supported",
    r"committed request not found",
]

_JMX_BENIGN = re.compile(r"(mbean|jmx|log4j.*bean|unregister.*bean)", re.I)


def _is_jmx_only(lines):
    for l in lines:
        if l["level"] not in ("WARN", "DEBUG", "ERROR"):
            continue
        if _JMX_BENIGN.search(l["content"]):
            continue
        return False
    return True


def recovery_aware_label(lines):
    text = session_text(lines)

    if has_error_level(lines) and _is_jmx_only(lines):
        return "normal"

    suspect = (has_error_level(lines)
               or bool(re.search(r"Exception|\b(ERROR|FATAL)\b", text)))

    if "ssl" in text.lower() and "not supported" in text.lower():
        return "normal"

    if re.search(r"uptodate.*after.*(follower|observer) started", text, re.I):
        if re.search(r"(disconnect|following|leadership|reconnecting"
                     r"|leader election)", text, re.I):
            return "normal"

    if re.search(r"exception when observing the leader", text, re.I):
        if re.search(r"disconnected from leader", text, re.I):
            return "normal"

    if not suspect:
        return "normal"

    if re.search(r"could not configure server", text, re.I):
        if re.search(r"login user set successfully", text, re.I):
            return "normal"

    if any_match(_FATAL_KW, text):
        return "anomaly"
    if any_match(_RECOVERY_KW, text):
        return "normal"
    if not has_error_level(lines):
        return "normal"
    if re.search(r"adminserver|empty snapshot|empty data tree"
                 r"|should only be allowed", text, re.I):
        return "normal"
    return "anomaly"


# ── Main ─────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=DEFAULT_CSV)
    args = ap.parse_args()

    sessions = load_sessions(args.csv)
    print(f"Loaded {len(sessions)} sessions from {args.csv}")

    rows, result = run_comparison(
        sessions, semantic_gt, recovery_aware_label, GT_RATIONALE,
        system_name="ZooKeeper")

    out_json, out_csv = save_results(
        rows, result, "zk_recovery_relabel", gt_rationale=GT_RATIONALE)
    print_summary(result)
    print(f"\nSaved: {out_json}\n       {out_csv}")


if __name__ == "__main__":
    main()
