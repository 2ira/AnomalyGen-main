import os
import json
import re
import csv
import pandas as pd
from logparser.Drain import LogParser
import hashlib
from typing import Dict, List, Tuple

##---- 1. load the merged dict<exec_flow,logs> to label d
def load_merged_json(merged_json_path: str) -> Dict:
    if not os.path.exists(merged_json_path):
        raise FileNotFoundError(f"merged json not exists{merged_json_path}")
    with open(merged_json_path, 'r', encoding='utf-8') as f:
        try:
            merged_data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Error when merging{str(e)}")
    # data check: 'exec_flow' and 'log' key must be included
    for log_key, log_entry in merged_data.items():
        if not isinstance(log_entry, dict) or "exec_flow" not in log_entry or "log" not in log_entry:
            raise ValueError(f"Log Format Error (key:{log_key}) including")
    return merged_data


def valid_log(log_segment: str) -> bool:
    if not log_segment or not log_segment.strip():
        return False
    # match "[Level]: Content" 
    pattern = r'^\[\w+\]\s*:\s*.+$'
    return bool(re.match(pattern, log_segment.strip()))

## mark for each logs
def mark_abnormal(log_segment: str, exec_flow: str) -> str:
    explicit = False
    implicit = False

    # 1.explicit:
    if "Exception" in log_segment or re.search(r'\b(ERROR|FATAL)\b', log_segment):
        explicit = True
    if re.search(r'\b(EXCEPTION|CATCH|FAIL)\b', exec_flow, re.IGNORECASE):
        explicit = True

    # 2. implicit error:
    failure_keywords = ["fail", "cannot", "invalid", "failed"]
    if any(re.search(r'\b' + kw + r'\b', log_segment, re.IGNORECASE) for kw in failure_keywords):
        implicit = True
    if re.search(r'error_code\s*=\s*\d+', log_segment, re.IGNORECASE):
        implicit = True

    # 3. final tag
    if explicit and implicit:
        return "both"
    elif explicit:
        return "explicit"
    elif implicit:
        return "implicit"
    else:
        return "normal"


def process_single_log_entry(log_key: str, log_entry: Dict) -> List[Dict]:
    """Addressing single logs: split into logs, check and label"""
    exec_flow = log_entry.get("exec_flow", "").strip()
    raw_log = log_entry.get("log", "").replace("※", "").strip() 

    # split logs by [label]
    log_segments = re.split(r'(?=\[\w+\]\s*:\s*)', raw_log) 
    log_segments = [seg.strip() for seg in log_segments if seg.strip()]

    processed_segments = []
    for seg in log_segments:
        if valid_log(seg):
            label = mark_abnormal(seg, exec_flow)
            processed_segments.append({
                "log_key": log_key, 
                "exec_flow": exec_flow,
                "log_segment": seg, 
                "label": label   
            })
    return processed_segments


##--- 2. group,label, and split
def process_merged_logs(merged_json_path: str, output_root: str = "log_process_output") -> Tuple[Dict, Dict]:
    """
    1.load merged logs → 2. address logs(split and label)→ 3. group by BlockID → 4. store the results
    """
    # 1. initial the dir
    os.makedirs(output_root, exist_ok=True)
    block_label_dir = os.path.join(output_root, "block_labels")
    entry_dir = os.path.join(output_root, "entries")
    os.makedirs(block_label_dir, exist_ok=True)
    os.makedirs(entry_dir, exist_ok=True)

    # 2. load merged log files
    print(f"🔍 Starting loading files:{merged_json_path}")
    merged_logs = load_merged_json(merged_json_path)
    print(f"✅ Successfully load {len(merged_logs)} logs")

    # 3. Group by Block(BlockID = log_key)
    block_mapping = {}  # BlockID → global labal
    entry_mapping = {}  # ID → single log detailed logs
    entry_counter = 1   # add it to logs

    print("\n📝 Addressing logs and tag it ...")
    for log_key, log_entry in merged_logs.items():
        block_id = log_key

        # Addressing Log: split and label -> for each single log
        processed_segs = process_single_log_entry(log_key, log_entry)
        if not processed_segs:
            print(f"⚠️ Log key {log_key} have invalid log tag, skip it")
            continue

        # One error, all the block error
        seg_labels = [seg["label"] for seg in processed_segs]
        if "both" in seg_labels:
            block_label = "both"
        elif "explicit" in seg_labels:
            block_label = "explicit"
        elif "implicit" in seg_labels:
            block_label = "implicit"
        else:
            block_label = "normal"
        block_mapping[block_id] = block_label

        # record the detailed log infos [group by block]
        for seg in processed_segs:
            entry_mapping[entry_counter] = {
                "entry_id": entry_counter,
                "BlockId": block_id,
                "log_key": seg["log_key"],
                "exec_flow": seg["exec_flow"],
                "log_segment": seg["log_segment"],
                "single_log_label": seg["label"],
                "block_log_label": block_label,
            }
            entry_counter += 1

    # 4. store the results(json and cvs)
    print(f"\n💾 Starting saving {len(block_mapping)} Blocks, {len(entry_mapping)} numbers of logs in total.")
    
    # 4.1 store block_id mapping 
    block_json_path = os.path.join(block_label_dir, "hdfs_block_labels.json")
    with open(block_json_path, "w", encoding='utf-8') as f:
        json.dump(block_mapping, f, indent=2, ensure_ascii=False)
    
    block_csv_path = os.path.join(block_label_dir, "hdfs_block_labels.csv")
    with open(block_csv_path, "w", newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["BlockId", "Label"])
        for bid, label in block_mapping.items():
            writer.writerow([bid, label])

    # 4.2 store detailed logs
    entry_json_path = os.path.join(entry_dir, "hdfs_entries.json")
    with open(entry_json_path, "w", encoding='utf-8') as f:
        json.dump(entry_mapping, f, indent=2, ensure_ascii=False)
    
    entry_csv_path = os.path.join(entry_dir, "hdfs_entries.csv")
    with open(entry_csv_path, "w", newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["entry_id", "BlockId", "log_key", "exec_flow", "log_segment", "single_log_label","block_log_label"])
        writer.writeheader()
        for entry in entry_mapping.values():
            writer.writerow(entry)

    print(f"✅ Results are stored ")
    print(f"  - Block label is {block_json_path} / {block_csv_path}")
    print(f"  - Log is saved in {entry_json_path} / {entry_csv_path}")
    return block_mapping, entry_mapping


## -- 3. Drain parsing --------------------------
def export_block_logs(entry_mapping: Dict, output_root: str = "log_process_output") -> Dict:
    """group by BlockID for Drain parsing """
    raw_log_dir = os.path.join(output_root, "raw_logs_by_block")
    os.makedirs(raw_log_dir, exist_ok=True)

    # group by Block and save to logs for parsing
    block_logs = {}
    for entry in entry_mapping.values():
        block_id = entry["BlockId"]
        log_segment = entry["log_segment"]
        if block_id not in block_logs:
            block_logs[block_id] = []
        block_logs[block_id].append(log_segment)

    # export to .log
    block_log_paths = {}
    print(f"\n📂 {len(block_logs)} Blocks...")
    for block_id, logs in block_logs.items():
        log_path = os.path.join(raw_log_dir, f"{block_id}_logs.log")
        with open(log_path, "w", encoding='utf-8') as f:
            f.write("\n".join(logs))
        block_log_paths[block_id] = log_path
        print(f"  - Block {block_id}: {log_path}")
    return block_log_paths


def parse_logs_with_drain(block_log_paths: Dict, output_root: str = "log_process_output") -> None:
    """Use Drain to pars logs of each Block and generating log files"""
    parsed_log_dir = os.path.join(output_root, "parsed_logs")
    os.makedirs(parsed_log_dir, exist_ok=True)

    log_format = r'<Level>:<Content>'  
    regex = [
        r'\d+',                         
        r'\[.*?\]',                 
        r'\'[^\']+\'',             
        r'"[^"]+"',                 
        r'(?:/|)(?:[0-9]+\.){3}[0-9]+(?::[0-9]+|)(?::|)',
        r'<\*>',                    
        r'%\%',                     
        r'\b(?:\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2})\b', 
        r'\b(?:[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12})\b', 
        r'/[\w./-]+'         
    ]
    st = 0.5 
    depth = 2  

    all_parsed_dfs = []
    print(f"\n🔧 Using Drain parsing {len(block_log_paths)} files...")
    for block_id, log_path in block_log_paths.items():

        parser = LogParser(
            log_format=log_format,
            indir=os.path.dirname(log_path),
            outdir=parsed_log_dir,
            depth=depth,
            st=st,
            rex=regex
        )
        try:
            parser.parse(os.path.basename(log_path))
            parsed_csv_path = os.path.join(parsed_log_dir, f"{os.path.basename(log_path)}_structured.csv")
            if not os.path.exists(parsed_csv_path):
                print(f"⚠️ Block {block_id} parse failed, skip it ")
                continue

            #  read parsed logs and add BlockID
            parsed_df = pd.read_csv(parsed_csv_path)
            parsed_df["BlockId"] = block_id  
            all_parsed_dfs.append(parsed_df)
            print(f"  ✅ Block {block_id}: parsed successfully {parsed_csv_path}")
        except Exception as e:
            print(f"  ❌ Block {block_id}: parsed failed{str(e)}")
            continue

    # merge all results and save them
    if all_parsed_dfs:
        combined_parsed_df = pd.concat(all_parsed_dfs, ignore_index=True)
        combined_csv_path = os.path.join(parsed_log_dir, "hdfs_combined_parsed_logs.csv")
        combined_parsed_df.to_csv(combined_csv_path, index=False, encoding='utf-8')
        print(f"\n✅ All results are parsed：{combined_csv_path}")
    else:
        print("\n⚠️ No parsing results")

def main():
    # MERGED_JSON_PATH = "ablation_v2_compressed_log.json" 
    # OUTPUT_ROOT = "output_v2/hadoop"
    
    # MERGED_JSON_PATH = "ablation_v1_compressed_log.json" 
    # OUTPUT_ROOT = "output/hadoop"

    MERGED_JSON_PATH = "baseline_compressed_log.json"
    OUTPUT_ROOT = "output/hadoop"
    
    try:
        # Step 1: label,gpoup and store
        block_mapping, entry_mapping = process_merged_logs(MERGED_JSON_PATH, OUTPUT_ROOT)

        # Step 2: group Block by block
        block_log_paths = export_block_logs(entry_mapping, OUTPUT_ROOT)

        # Step 3: use Drain parse and save
        parse_logs_with_drain(block_log_paths, OUTPUT_ROOT)

        print(f"\n🎉 All results are saved! Which is saved to:{os.path.abspath(OUTPUT_ROOT)}")

    except Exception as e:
        print(f"\n❌ Parse failed:{str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    import sys
    main()