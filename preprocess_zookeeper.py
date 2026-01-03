import os
import argparse
import pandas as pd
import numpy as np

DEFAULT_EXTENDED_KEYWORDS = [
    "cannot open channel",
    "notification time out",
    "timeout",
    "timed out",
    "exception",
    "failed",
    "refused",
    "unable",
]

def to_std_label(x: int) -> str:
    return "Anomaly" if int(x) == 1 else "Normal"

def is_anomaly_line(level: str, content: str, rule: str, keywords):
    lvl = str(level).upper()
    if rule == "strict":
        return lvl == "ERROR"
    # extended
    if lvl == "ERROR":
        return True
    if lvl in ("WARN", "FATAL"):
        s = str(content).lower()
        return any(k in s for k in keywords)
    return False

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--structured_csv", type=str, required=True, help="Drain输出的 Zookeeper.log_structured.csv")
    ap.add_argument("--output_dir", type=str, required=True, help="输出目录")
    ap.add_argument("--window_size", type=int, default=20)
    ap.add_argument("--step_size", type=int, default=4)
    ap.add_argument("--label_rule", choices=["strict", "extended"], default="strict")
    ap.add_argument("--keywords", type=str, default="", help="extended规则的关键词，逗号分隔；空则用默认")
    ap.add_argument("--max_windows", type=int, default=None, help="可选：限制生成窗口数")
    ap.add_argument("--time_split_ratio_for_id", type=float, default=None,
                    help="可选：只用前 x 比例日志生成窗口（方便你后续按时间切分 train/test）")
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    out_windows = os.path.join(args.output_dir, "zookeeper.log_structured_windows.csv")
    out_labels  = os.path.join(args.output_dir, "zookeeper.anomaly_label.csv")

    keywords = DEFAULT_EXTENDED_KEYWORDS
    if args.keywords.strip():
        keywords = [x.strip().lower() for x in args.keywords.split(",") if x.strip()]

    df = pd.read_csv(args.structured_csv)

    # Drain structured 通常至少有：Date, Time, Level, Content, EventTemplate
    required = ["Level", "EventTemplate"]
    for c in required:
        if c not in df.columns:
            raise ValueError(f"Missing column '{c}' in structured csv. Columns: {list(df.columns)}")

    # Content 用于 extended 规则；如果没有就退化为只看 Level
    if "Content" not in df.columns:
        df["Content"] = ""

    # 让顺序稳定（按 Date+Time）
    if "Date" in df.columns and "Time" in df.columns:
        df["__ts"] = pd.to_datetime(df["Date"].astype(str) + " " + df["Time"].astype(str), errors="coerce")
        df = df.dropna(subset=["__ts"]).sort_values("__ts").reset_index(drop=True)
    else:
        df = df.reset_index(drop=True)

    if args.time_split_ratio_for_id is not None:
        n = int(len(df) * float(args.time_split_ratio_for_id))
        df = df.iloc[:n].reset_index(drop=True)

    # 全局 template->int
    templates = df["EventTemplate"].astype(str).tolist()
    uniq = pd.unique(templates)
    template2id = {t: i + 1 for i, t in enumerate(uniq)}
    df["AdldEventId"] = df["EventTemplate"].map(template2id).astype(int)

    # 构造滑窗 BlockId（窗口级序列）
    n = len(df)
    if n < args.window_size:
        raise ValueError(f"Not enough rows: {n} < window_size={args.window_size}")

    window_rows = []
    label_rows = []

    win_id = 0
    for start in range(0, n - args.window_size + 1, args.step_size):
        if args.max_windows is not None and win_id >= args.max_windows:
            break
        end = start + args.window_size
        bid = f"zk_win_{win_id:07d}"

        chunk = df.iloc[start:end]

        # window label（弱标注）
        is_anom = 0
        for _, r in chunk.iterrows():
            if is_anomaly_line(r["Level"], r["Content"], args.label_rule, keywords):
                is_anom = 1
                break

        label_rows.append({"BlockId": bid, "Label": to_std_label(is_anom)})

        # windows 行级输出（每个窗口包含 window_size 行）
        # 注意：同一条日志行会出现在多个窗口，这是 sliding window 的定义（与 LogAction 一致）
        for _, r in chunk.iterrows():
            window_rows.append({
                "BlockId": bid,
                "EventTemplate": str(r["EventTemplate"]),
                "AdldEventId": int(r["AdldEventId"]),
                "Level": str(r["Level"])
            })

        win_id += 1

    pd.DataFrame(window_rows).to_csv(out_windows, index=False)
    pd.DataFrame(label_rows).to_csv(out_labels, index=False)

    print("[OK] Generated:")
    print(" ", out_windows, f"(rows={len(window_rows)})")
    print(" ", out_labels,  f"(windows={len(label_rows)})")
    print(f"Unique templates: {len(template2id)}")
    print(f"Weak label rule: {args.label_rule}")

if __name__ == "__main__":
    main()

"""
python preprocess_zookeeper.py \
  --structured_csv dataset/Zookeeper/Zookeeper.log_structured.csv \
  --output_dir zk_windows_strict \
  --window_size 10 \
  --step_size 2 \
  --label_rule strict
"""