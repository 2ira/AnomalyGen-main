# ==============================================================================
# generate_lightad_augmented_data.py
# ==============================================================================

import os
import argparse
import pandas as pd
import numpy as np
import json
import re
from collections import OrderedDict, defaultdict
from tqdm import tqdm
from sklearn.model_selection import train_test_split

# --- Utility Functions ---
def json_pretty_dump(obj, filename):
    """Helper function to dump a dictionary to a pretty-printed JSON file."""
    with open(filename, "w") as fw:
        json.dump(obj, fw, sort_keys=True, indent=4, separators=(",", ": "), ensure_ascii=False)

# --- Data Loading and Session Creation Functions ---

def create_sessions_from_original_hdfs(log_file, label_file):
    """
    Processes the original HDFS data from structured CSVs, mimicking the
    sessionization logic required for log analysis.
    """
    print("Processing original HDFS data from structured CSV...")
    try:
        df_label = pd.read_csv(label_file)
    except FileNotFoundError as e:
        print(f"[ERROR] Label not exixts: {e}. Exiting.")
        exit()
    label_dict = dict(zip(df_label['BlockId'], df_label['Label'].apply(lambda x: '+' if x == 'Anomaly' else '-')))
    
    # 2. read files line by line
    sessions = defaultdict(list)
    block_pattern = re.compile(r"blk_-?\d+")  # block_id
    digit_pattern = re.compile(r"\d")  # digit
    
    try:
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except FileNotFoundError as e:
        print(f"[ERROR] Original logs not exists: {e}. Exiting.")
        exit()
    
    for line in tqdm(lines, desc="parse original HDFS logs"):
        block_ids = block_pattern.findall(line)
        if not block_ids:
            continue 
        block_id = block_ids[0]
        parts = line.split()
        if len(parts) < 6:
            continue 
        content_parts = parts[5:]
        filtered_parts = []
        for part in content_parts:
            # filter numbers
            if not digit_pattern.search(part):
                filtered_parts.append(part)
        if filtered_parts:  
            sessions[block_id].append(" ".join(filtered_parts))
    
    # save session with labels
    labeled_sessions = OrderedDict()
    for block_id, templates in sessions.items():
        if block_id in label_dict:
            labeled_sessions[block_id] = {
                'templates': templates,
                'label': label_dict[block_id]
            }
    
    print(f"From HDFS logs create {len(labeled_sessions)} 个session.")
    return labeled_sessions

def create_sessions_from_augmented_df(log_file, label_file):
    """Processes the new augmented data format using pandas DataFrames."""
    print("Processing augmented data...")
    try:
        df_aug_log = pd.read_csv(log_file)
        df_aug_label = pd.read_csv(label_file)
    except FileNotFoundError as e:
        print(f"[ERROR] Could not find augmentation file: {e}. Exiting.")
        exit()

    if 'block_id' in df_aug_label.columns:
        df_aug_label = df_aug_label.rename(columns={'block_id': 'BlockId', 'label': 'Label'})
    
    label_dict = dict(zip(df_aug_label['BlockId'], df_aug_label['Label'].apply(lambda x: '+' if x != 'normal' else '-')))
    
    sessions = OrderedDict()
    df_aug_log.dropna(subset=['BlockId'], inplace=True)
    
    grouped = df_aug_log.groupby('BlockId')
    for block_id, group in tqdm(grouped, desc="Sessionizing Augmented Data"):
        sessions[block_id] = {
            'templates': group['EventTemplate'].tolist(),
            'label': label_dict.get(block_id, '-')
        }
    print(f"Created {len(sessions)} sessions from augmented data.")
    return sessions

# --- Main Logic ---

def main():
    parser = argparse.ArgumentParser(description="Generate augmented datasets for the LightAD project from scratch.")

    # Paths
    parser.add_argument("--original_log_path", type=str, required=True, help="Path to the original HDFS structured log CSV.")
    parser.add_argument("--original_label_path", type=str, required=True, help="Path to the original HDFS anomaly label CSV.")
    parser.add_argument("--aug_log_file", type=str, required=True, help="Path to the augmented structured log file.")
    parser.add_argument("--aug_label_file", type=str, required=True, help="Path to the augmented anomaly label file.")
    parser.add_argument("--output_dir", type=str, required=True, help="Directory to save the final .npz file and metadata.")
    
    # Ratios & Seed
    parser.add_argument("--aug_ratio", default=0.1, type=float, help="Ratio of augmented data to add, relative to the size of the original training set.")
    parser.add_argument("--test_ratio", default=0.2, type=float, help="Ratio of the original data to be used as the test set.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility.")

    args = parser.parse_args()
    np.random.seed(args.seed)

    # --- Step 1: Load and Sessionize ALL data ---
    print("\n--- Step 1: Loading all data sources ---")
    original_sessions = create_sessions_from_original_hdfs(args.original_log_path, args.original_label_path)
    augmented_sessions = create_sessions_from_augmented_df(args.aug_log_file, args.aug_label_file)

    # --- Step 2: Split original data into a base train/test set ---
    print("\n--- Step 2: Splitting original data ---")
    original_ids = list(original_sessions.keys())
    train_ids, test_ids = train_test_split(original_ids, test_size=args.test_ratio, random_state=args.seed)

    base_train_sessions = {id: original_sessions[id] for id in train_ids}
    test_sessions = {id: original_sessions[id] for id in test_ids}
    print(f"Split original data into {len(base_train_sessions)} base train sessions and {len(test_sessions)} test sessions.")

    # --- Step 3: Sample augmented data and add to the training set ---
    print("\n--- Step 3: Sampling and adding augmented data ---")
    num_base_train = len(base_train_sessions)
    num_aug_to_add = int(num_base_train * args.aug_ratio)
    
    final_train_sessions = base_train_sessions.copy()
    
    if num_aug_to_add > 0 and len(augmented_sessions) > 0:
        aug_ids = list(augmented_sessions.keys())
        replace = num_aug_to_add > len(aug_ids)
        if replace: print(f"Warning: Target augmentation size {num_aug_to_add} > available {len(aug_ids)}. Using replacement sampling.")
        
        selected_aug_ids = np.random.choice(aug_ids, size=num_aug_to_add, replace=replace)
        
        # Add with a prefix to avoid key collisions, ensuring all sessions are unique
        sessions_to_add = {f"aug_{i}_{id}": augmented_sessions[id] for i, id in enumerate(selected_aug_ids)}
        final_train_sessions.update(sessions_to_add)
        print(f"Added {len(sessions_to_add)} augmented sessions to the training set.")
    else:
        print("No augmented data added.")
        
    print(f"Final training set contains {len(final_train_sessions)} sessions.")

    # --- Step 4: Create Unified Vocabulary and Vectorize ---
    print("\n--- Step 4: Building unified vocabulary and vectorizing ---")
    
    # Vocabulary is built from the FINAL training set and the test set
    all_known_sessions = {**final_train_sessions, **test_sessions}
    all_templates = set()
    for session in all_known_sessions.values():
        all_templates.update(session['templates'])
    
    master_vocabulary = sorted(list(all_templates))
    vocab_map = {template: i for i, template in enumerate(master_vocabulary)}
    print(f"Built unified vocabulary with {len(master_vocabulary)} unique event templates.")

    def vectorize(sessions_dict):
        vectors, labels = [], []
        for session in sessions_dict.values():
            vec = [0] * len(master_vocabulary)
            for template in session['templates']:
                if template in vocab_map:
                    vec[vocab_map[template]] += 1
            vectors.append(vec)
            labels.append(session['label'])
        return np.array(vectors, dtype=np.int32), np.array(labels)

    x_train, y_train = vectorize(final_train_sessions)
    x_test, y_test = vectorize(test_sessions)
    
    print(f"Vectorization complete. Train shape: {x_train.shape}, Test shape: {x_test.shape}")

    # --- Step 5: Save in LightAD .npz format ---
    print("\n--- Step 5: Saving final dataset ---")
    os.makedirs(args.output_dir, exist_ok=True)
    
    output_npz_path = os.path.join(args.output_dir, f"hdfs_aug_{args.aug_ratio}.npz")
    np.savez(
        output_npz_path,
        x_train=x_train,
        x_test=x_test,
        y_train=y_train,
        y_test=y_test
    )
    print(f"Successfully saved LightAD-compatible dataset to: {output_npz_path}")
    
    # Save metadata for reproducibility
    desc_data = vars(args).copy()
    desc_data["final_train_size"] = len(x_train)
    desc_data["final_test_size"] = len(x_test)
    desc_data["vocabulary_size"] = len(master_vocabulary)
    json_pretty_dump(desc_data, os.path.join(args.output_dir, f"hdfs_aug_{args.aug_ratio}_desc.json"))

if __name__ == "__main__":
    main()
    
    
#  parser.add_argument("--original_log_path", type=str, required=True, help="Path to the original HDFS structured log CSV.")
#     parser.add_argument("--original_label_path", type=str, required=True, help="Path to the original HDFS anomaly label CSV.")
#     parser.add_argument("--aug_log_file", type=str, required=True, help="Path to the augmented structured log file.")
#     parser.add_argument("--aug_label_file", type=str, required=True, help="Path to the augmented anomaly label file.")
#     parser.add_argument("--output_dir", type=str, required=True, help="Directory to save the final .npz file and metadata.")
    
#     # Ratios & Seed
#     parser.add_argument("--aug_ratio", default=0.1, type=float, help="Ratio of augmented data to add, relative to the size of the original training set.")
#     parser.add_argument("--test_ratio", default=0.2, type=float, help="Ratio of the original data to be used as the test set.")
#     parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility.")


## 0.001 aug
## python aug_lightad_data.py --original_log_path LightAD/datasets/full_datasets/hdfs --original_label_path LightAD/datasets/full_datasets/anomaly_label.csv  --aug_log_file aug_data/hdfs_combined_parsed_logs.csv --aug_label_file aug_data/hdfs_block_labels.csv  --output_dir LightAD/datasets/aug_datasets  --aug_ratio 0.001

### 
#python aug_lightad_data.py --original_log_path LightAD/datasets/full_datasets/hdfs --original_label_path LightAD/datasets/full_datasets/anomaly_label.csv  --aug_log_file ablation/baseline/parsed_logs/hdfs_combined_parsed_logs.csv --aug_label_file ablation/baseline/block_labels/hdfs_block_labels.csv  --output_dir LightAD/datasets/baseline_datasets  --aug_ratio 0.001

#python aug_lightad_data.py --original_log_path LightAD/datasets/full_datasets/hdfs --original_label_path LightAD/datasets/full_datasets/anomaly_label.csv  --aug_log_file ablation/without_cot/parsed_logs/hdfs_combined_parsed_logs.csv --aug_label_file ablation/without_cot/block_labels/hdfs_block_labels.csv  --output_dir LightAD/datasets/without_cot_datasets  --aug_ratio 0.001

#python aug_lightad_data.py --original_log_path LightAD/datasets/full_datasets/hdfs --original_label_path LightAD/datasets/full_datasets/anomaly_label.csv  --aug_log_file ablation/without_analysis/parsed_logs/hdfs_combined_parsed_logs.csv --aug_label_file ablation/without_analysis/block_labels/hdfs_block_labels.csv  --output_dir LightAD/datasets/without_analysis_datasets  --aug_ratio 0.001


## 0.01 aug
# python aug_lightad_data.py --original_log_path LightAD/datasets/full_datasets/hdfs --original_label_path LightAD/datasets/full_datasets/anomaly_label.csv  --aug_log_file aug_data/hdfs_combined_parsed_logs.csv --aug_label_file aug_data/hdfs_block_labels.csv  --output_dir LightAD/datasets/aug_datasets  --aug_ratio 0.01


## 0.1 aug
# python aug_lightad_data.py --original_log_path LightAD/datasets/full_datasets/hdfs --original_label_path LightAD/datasets/full_datasets/anomaly_label.csv  --aug_log_file aug_data/hdfs_combined_parsed_logs.csv --aug_label_file aug_data/hdfs_block_labels.csv  --output_dir LightAD/datasets/aug_datasets  --aug_ratio 0.1



## 1.0 aug
# python aug_lightad_data.py --original_log_path LightAD/datasets/full_datasets/hdfs --original_label_path LightAD/datasets/full_datasets/anomaly_label.csv  --aug_log_file aug_data/hdfs_combined_parsed_logs.csv --aug_label_file aug_data/hdfs_block_labels.csv  --output_dir LightAD/datasets/aug_datasets  --aug_ratio 1.0
