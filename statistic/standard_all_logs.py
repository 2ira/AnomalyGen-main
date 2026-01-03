"""
This file is used to collect all the output files and merge their analysis into a json file.
Then, use a simulator to standardlize the logs.
"""

import os
import json
import argparse
from typing import Dict
import re
import html
import openai
from utils import clean_text,extract_from_content_log_seq,extract_from_content_log_sequence
from typing import Dict, List
import logging
from models.prompts.standard_log import get_log_simulate_v2
from models.get_resp import get_response
import hashlib

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler("standardlize_single_log.log", encoding='utf-8'),
                        logging.StreamHandler()
                    ])
logger = logging.getLogger()

def find_log_json_files(input_dir: str) -> List[str]:
    """
    input: the dictory including all the single entry results
    """

    if not os.path.isdir(input_dir):
        raise NotADirectoryError(f"Input dir is'{input_dir}' not valid, please check their valiation.")
    
    log_json_paths = []
    # find file recusively
    for root, _, files in os.walk(input_dir):
        for file in files:
            # filter rules ：json file, with '_log_' included in the name 
            if "merge_single_log" in file and file.endswith(".json"):
                file_abs_path = os.path.abspath(os.path.join(root, file))
                log_json_paths.append(file_abs_path)
    
    return log_json_paths


def merge_json_files(file_paths: List[str]) -> Dict:
    """
    Read the file list and combine them into a dict. 
    For duplicate keys, save all values with incremental numeric suffixes (e.g., key → key_1 → key_2).
    """
    merged_dict = {}
    processed_count = 0  
    failed_count = 0    

    for file_path in file_paths:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                try:
                    json_data = json.load(f)
                except json.JSONDecodeError as e:
                    print(f"❌ Skip: '{file_path}' for json format error - {str(e)}")
                    failed_count += 1
                    continue

            # Validate if the parsed data is a dictionary
            if not isinstance(json_data, dict):
                print(f"❌ Skip: '{file_path}' - json content is not a dict (current type: {type(json_data).__name__})")
                failed_count += 1
                continue

            # Core logic: Handle duplicate keys with incremental suffixes
            for original_key, value in json_data.items():
                # Initialize target key as original key first
                target_key = original_key
                # If key exists, generate new key with suffix (e.g., key → key_1 → key_2)
                suffix = 1
                while target_key in merged_dict:
                    target_key = f"{original_key}_{suffix}"
                    suffix += 1  # Increment suffix until finding an unused key
                # Add to merged dict (no overwriting, all values are preserved)
                merged_dict[target_key] = value

            # Update count and print success info
            processed_count += 1
            print(f"✅ Successfully processed file: {file_path}")

        except PermissionError:
            print(f"❌ Permission Error: Cannot read '{file_path}' (insufficient permissions)")
            failed_count += 1
        except Exception as e:
            print(f"❌ Unknown Error: Failed to process '{file_path}' - {str(e)}")
            failed_count += 1

    # Print final statistics
    total = len(file_paths)
    print(f"\n📊 Processing finished: Total {total} target files, successfully processed {processed_count}, failed {failed_count}")
    return merged_dict


def save_merged_json(merged_dict: Dict, output_path: str) -> None:
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        print(f"📁 Automated Output Files: {os.path.abspath(output_dir)}")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(merged_dict, f, indent=4, ensure_ascii=False)

    print(f"\n🎉 Merged json is saved to {os.path.abspath(output_path)}")


## step_1: get_merge_files
def get_merged_files(input,output):
    try: 
        
        log_json_files = find_log_json_files(input)

        if not log_json_files:
            print("⚠️ can not find any files")
            return
        print(f"\n🔗 merging {len(log_json_files)} JSON files...")
        merged_data = merge_json_files(log_json_files)

        if not merged_data:
            print("⚠️ All files finised, without generating merged JSON")
            return
        print(f"\n💾 Start saving ...")
        save_merged_json(merged_data,output)

    except Exception as e:
        print(f"\n❌ Exit with error:{str(e)}")


## step_2: standilized logs, with interrupt continue
def compress_log(merged_file,output_file):
    os.makedirs("output/zookeeper/log_events",exist_ok=True)
    with open(merged_file, 'r') as file:
        merge_map = json.load(file)

    if os.path.exists(output_file):
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                prev_data = json.load(f)
        except json.JSONDecodeError:
            logger.warning("Output file format error.")
            prev_data = {}
    else:
        prev_data = {}


    for sig in merge_map:
        key = hashlib.sha256(sig.encode()).hexdigest()[:8]
        # if prefix exists（if exiist "{prefix}_1"），skip it
        if f"{key}_1" in prev_data:
            logger.info(f"Already addressed {key}")
            continue
        # load full message and extract the key info
        origin_info = merge_map[sig]
        # info = extract_from_content_log_sequence(origin_info)
        info = origin_info
        prompt = list(get_log_simulate_v2(info))
        reply = get_response(prompt)
        content = clean_text(reply)
        pairs = extract_from_content_log_seq(content)
        logger.info("Get compressed data:")
        logger.info(pairs)
        
        # add logs to prev_data dict
        for i, pair in enumerate(pairs, start=1):
            prev_data[f"{key}_{i}"] = pair

        # After addressing a prefix and refresh the results
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(prev_data, f, indent=2, ensure_ascii=False)
            f.write("\n")
    return prev_data

## another: for single node, read the single cfg to generate some results.

def main():
    # input_dir = "output/hadoop"
    # output_file  = "output/hadoop/merge_hdfs.json"
    # write_file = "baseline_compressed_log.json"
    # output_file  = "output/hadoop/merge_hdfs_without_cot.json"
    # write_file = "ablation_v1_compressed_log.json"
    # input_dir =  "output_v2/hadoop"
    # output_file = "output_v2/hadoop/merge_hdfs_without_static_analysis.json"
    # write_file = "ablation_v2_compressed_log.json"

    input_dir = "output/zookeeper"
    output_file  = "output/zookeeper/merge_zookeeper.json"
    write_file = "baseline_zookeeper_compressed_log.json"
    
    get_merged_files(input_dir,output_file)
    compress_log(output_file,write_file)
    
if __name__ == "__main__":
    main()