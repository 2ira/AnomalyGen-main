### this script is used to augment deep-loglizer dataset by adding data to original pickle

import os
import pickle
import argparse
import pandas as pd
import numpy as np
import json
import shutil
from collections import OrderedDict
from tqdm import tqdm

# --- Utility Functions ---

def decision(probability):
    """Returns True with a given probability."""
    return np.random.rand() < probability

def json_pretty_dump(obj, filename):
    """Helper function to dump a dictionary to a pretty-printed JSON file."""
    with open(filename, "w") as fw:
        json.dump(obj, fw, sort_keys=True, indent=4, separators=(",", ": "), ensure_ascii=False)

# --- NEW: Data Processing Function for the Specific Augmented Format ---

def create_aug_sessions_from_df(log_file, label_file):
    """
    Processes the new augmented data format using pandas DataFrames.
    - Loads log and label CSVs.
    - Normalizes labels ('normal' -> 0, others -> 1).
    - Groups the log DataFrame by 'BlockId' to create sessions.
    """
    print(f"Loading new format augmentation data from: {log_file}")
    try:
        df_aug_log = pd.read_csv(log_file)
        df_aug_label = pd.read_csv(label_file)
    except FileNotFoundError as e:
        print(f"[Error] Could not find augmentation file: {e}. Please check your paths.")
        return None

    # --- Step 1: Normalize Labels ---
    # Rename columns for consistency if needed (e.g., 'block_id' -> 'BlockId')
    if 'block_id' in df_aug_label.columns:
        df_aug_label = df_aug_label.rename(columns={'block_id': 'BlockId', 'label': 'Label'})
    
    # Map string labels to numeric: 'normal' is 0, everything else is 1.
    df_aug_label['Label_numeric'] = df_aug_label['Label'].apply(lambda x: 0 if x == 'normal' else 1)
    label_dict = dict(zip(df_aug_label['BlockId'], df_aug_label['Label_numeric']))
    print(f"Processed {len(label_dict)} labels. Mapped 'normal' to 0, others to 1.")
    
    # --- Step 2: Create Sessions using groupby ---
    # This is much more efficient than row-by-row iteration for large files.
    session_dict = OrderedDict()
    
    # Filter out any rows that might not have a BlockId
    df_aug_log.dropna(subset=['BlockId'], inplace=True)

    print("Grouping log entries by BlockId to create sessions...")
    grouped = df_aug_log.groupby('BlockId')
    for block_id, group in tqdm(grouped, desc="Creating Aug Sessions"):
        session_dict[block_id] = {
            'templates': group['EventTemplate'].tolist(),
            'label': label_dict.get(block_id, 0) # Default to normal (0) if label is missing
        }
        
    print(f"Created {len(session_dict)} sessions from the new augmentation source.")
    return session_dict


# --- Main Augmentation Logic ---

def main():
    parser = argparse.ArgumentParser(description="Append augmented data (new format) to an existing dataset.")
    # ... (Argument parsing remains the same) ...
    parser.add_argument("--base_data_dir", type=str,default="deep-loglizer/data/processed/HDFS/hdfs_0.0_tar", help="Path to the directory containing the existing train.pkl and test.pkl.")
    parser.add_argument("--aug_log_file", type=str, required=True, help="Path to the augmented structured log file (new format).")
    parser.add_argument("--aug_label_file", type=str, required=True, help="Path to the augmented anomaly label file (new format).")
    parser.add_argument("--output_base_dir", type=str, default="deep-loglizer/data/processed/HDFS/hdfs_aug", help="Base directory where the new augmented dataset folder will be created.")
    parser.add_argument("--train_anomaly_ratio", default=0.0, type=float, help="Ratio of anomalies to keep from the augmentation pool.")
    parser.add_argument("--aug_ratio", default=0.01, type=float, help="Ratio of augmented data to add, relative to the size of the existing training set.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility.")

    args = parser.parse_args()
    np.random.seed(args.seed)

    # --- Step 1: Load Existing Data ---
    print("\n--- Step 1: Loading existing pre-processed data ---")
    path_to_train_pkl = os.path.join(args.base_data_dir, "session_train.pkl")
    path_to_test_pkl = os.path.join(args.base_data_dir, "session_test.pkl")

    try:
        with open(path_to_train_pkl, "rb") as f:
            original_session_train = pickle.load(f)
        if not os.path.exists(path_to_test_pkl):
            raise FileNotFoundError("Could not find 'session_test.pkl' in the base directory.")
    except FileNotFoundError as e:
        print(f"[Fatal Error] Could not load base data: {e}")
        return

    num_original_train = len(original_session_train)
    print(f"Loaded {num_original_train} sessions from existing train.pkl.")

    # --- Step 2: Load and Filter Augmentation Data (using the NEW function) ---
    print("\n--- Step 2: Processing new augmentation data ---")
    aug_session_dict = create_aug_sessions_from_df(args.aug_log_file, args.aug_label_file)
    if not aug_session_dict:
        print("Failed to process augmentation data. Aborting.")
        return

    print(f"\nFiltering the augmentation pool with train_anomaly_ratio={args.train_anomaly_ratio}...")
    aug_pool_filtered = {
        k: v for k, v in aug_session_dict.items()
        if (v["label"] == 0) or (v["label"] == 1 and decision(args.train_anomaly_ratio))
    }
    print(f"Augmentation pool size reduced from {len(aug_session_dict)} to {len(aug_pool_filtered)}.")

    # --- Step 3: Sample and Merge ---
    ### permit repeat sampling ##
    print("\n--- Step 3: Sampling from augmentation pool and merging ---")
    num_aug_to_add = int(num_original_train * args.aug_ratio)
    aug_pool_size = len(aug_pool_filtered)
    new_session_train = original_session_train.copy()

    if num_aug_to_add == 0:
        print("Warning: Calculated number of augmented sessions to add is 0. The output will be a copy of the original.")
    elif aug_pool_size == 0:
        print("Error: No available sessions in the filtered augmentation pool. Cannot add any augmented data.")
    else:
        if num_aug_to_add > aug_pool_size:
            print(f"Warning: Requested {num_aug_to_add} augmented sessions, but only {aug_pool_size} are available. "
                  f"Using replacement sampling to reach the target number.")

        # 1. sample to target id
        aug_pool_filtered_ids = list(aug_pool_filtered.keys())
        selected_aug_ids = np.random.choice(aug_pool_filtered_ids, size=num_aug_to_add, replace=True)

        # 2. Fix: for same id adding post_fix to ensure unique key
        sessions_to_add = {}
        # id sample times
        id_count = {} 

        for original_id in selected_aug_ids:
            # target original id target session
            session_content = aug_pool_filtered[original_id]
            # checking id in all datasets
            if original_id in new_session_train or original_id in sessions_to_add:
                # repeat times
                id_count[original_id] = id_count.get(original_id, 0) + 1
                # generate new id
                new_id = f"{original_id}_{id_count[original_id]}"

                while new_id in new_session_train or new_id in sessions_to_add:
                    id_count[original_id] += 1
                    new_id = f"{original_id}_{id_count[original_id]}"
            else:
                new_id = original_id

            sessions_to_add[new_id] = session_content

        overlapping_keys = set(new_session_train.keys()).intersection(sessions_to_add.keys())
        if overlapping_keys:
            print(f"Warning: {len(overlapping_keys)} overlapping BlockIds found. Augmented data will overwrite original for these keys.")
        else:
            print("No overlapping BlockIds found (duplicates handled by adding suffixes).")

    # 4. combine sample dataset
    new_session_train.update(sessions_to_add)
    #  get sample numbers
    unique_original_ids = len(set(selected_aug_ids))
    repeated_count = num_aug_to_add - unique_original_ids
    print(f"Successfully added {num_aug_to_add} augmented sessions (including {repeated_count} repeated original sessions, with unique suffixes).")

    # --- Step 4: Save New Dataset ---
    print("\n--- Step 4: Saving the new, combined dataset ---")
    base_name = os.path.basename(os.path.normpath(args.base_data_dir))
    new_dir_name = f"{base_name}_plus_new_aug_{args.aug_ratio}"
    new_data_dir = os.path.join(args.output_base_dir, new_dir_name)
    os.makedirs(new_data_dir, exist_ok=True)
    
    with open(os.path.join(new_data_dir, "session_train.pkl"), "wb") as fw:
        pickle.dump(new_session_train, fw)
        
    shutil.copy2(path_to_test_pkl, os.path.join(new_data_dir, "session_test.pkl"))
    
    desc_data = {
        "source_dataset": args.base_data_dir,
        "augmentation_added": True,
        "aug_log_file": args.aug_log_file,
        "aug_label_file": args.aug_label_file,
        "aug_ratio_vs_base": args.aug_ratio,
        "train_anomaly_ratio_for_aug": args.train_anomaly_ratio,
        "seed": args.seed,
        "original_train_size": num_original_train,
        "final_train_size": len(new_session_train)
    }
    json_pretty_dump(desc_data, os.path.join(new_data_dir, "data_desc.json"))

    final_labels = [v["label"] for v in new_session_train.values()]
    final_anomaly_perc = (100 * sum(final_labels) / len(final_labels)) if final_labels else 0

    print(f"\nFinal # train sessions: {len(new_session_train)} ({final_anomaly_perc:.2f}% anomaly)")
    print(f"Test set was copied without changes.")
    print(f"New dataset successfully saved to: {new_data_dir}")

if __name__ == "__main__":
    main()

## for use
## 0.0_anomaly + 0.01 augment
## python aug_hdfs_data.py --aug_log_file aug_data/hdfs_combined_parsed_logs.csv --aug_label_file aug_data/hdfs_block_labels.csv   

## 0.0_anomaly + 0.001 augment
# python aug_hdfs_data.py --aug_log_file aug_data/hdfs_combined_parsed_logs.csv --aug_label_file aug_data/hdfs_block_labels.csv --aug_ratio 0.001


## 0.0_anomaly + 0.1 augment
## python aug_hdfs_data.py --aug_log_file aug_data/hdfs_combined_parsed_logs.csv --aug_label_file aug_data/hdfs_block_labels.csv --aug_ratio 0.1


## 0.0_anomaly + 1 augment
# python aug_hdfs_data.py --aug_log_file aug_data/hdfs_combined_parsed_logs.csv --aug_label_file aug_data/hdfs_block_labels.csv --aug_ratio 1


# parser.add_argument("--base_data_dir", type=str,default="deep-loglizer/data/processed/HDFS/hdfs_0.0_tar"


## 1.0_anomaly + 0.01 augment
# python aug_hdfs_data.py --base_data_dir deep-loglizer/data/processed/HDFS/hdfs_1.0_tar --aug_log_file aug_data/hdfs_combined_parsed_logs.csv --aug_label_file aug_data/hdfs_block_labels.csv --train_anomaly_ratio 1.0

## 1.0_anomaly + 0.001 augment
# python aug_hdfs_data.py --base_data_dir deep-loglizer/data/processed/HDFS/hdfs_1.0_tar --aug_log_file aug_data/hdfs_combined_parsed_logs.csv --aug_label_file aug_data/hdfs_block_labels.csv --train_anomaly_ratio 1.0 --aug_ratio 0.001  


## 1.0_anomaly + 0.1 augment
# python aug_hdfs_data.py --base_data_dir deep-loglizer/data/processed/HDFS/hdfs_1.0_tar --aug_log_file aug_data/hdfs_combined_parsed_logs.csv --aug_label_file aug_data/hdfs_block_labels.csv --train_anomaly_ratio 1.0 --aug_ratio 0.1  

# ## 1.0_anomaly + 1 augment
# python aug_hdfs_data.py --base_data_dir deep-loglizer/data/processed/HDFS/hdfs_1.0_tar --aug_log_file aug_data/hdfs_combined_parsed_logs.csv --aug_label_file aug_data/hdfs_block_labels.csv --train_anomaly_ratio 1.0 --aug_ratio 1.0  


### three ablation pairs
# baseline/parsed_logs/hdfs_combined_parsed_logs.csv
# baseline/block_labels/hdfs_block_labels.csv

# without_analysis/parsed_logs/hdfs_combined_parsed_logs.csv
# without_analysis/block_labels/hdfs_block_labels.csv

# without_cot/parsed_logs/hdfs_combined_parsed_logs.csv
# without_cot/block_labels/hdfs_block_labels.csv

## baseline 
### 0.0 anomaly
# python aug_hdfs_data.py --aug_log_file ablation/baseline/parsed_logs/hdfs_combined_parsed_logs.csv --aug_label_file ablation/baseline/block_labels/hdfs_block_labels.csv --aug_ratio 0.001 --output_base_dir deep-loglizer/data/processed/HDFS/hdfs_baseline

# python aug_hdfs_data.py --aug_log_file ablation/baseline/parsed_logs/hdfs_combined_parsed_logs.csv --aug_label_file ablation/baseline/block_labels/hdfs_block_labels.csv --aug_ratio 0.01 --output_base_dir deep-loglizer/data/processed/HDFS/hdfs_baseline

# python aug_hdfs_data.py --aug_log_file ablation/baseline/parsed_logs/hdfs_combined_parsed_logs.csv --aug_label_file ablation/baseline/block_labels/hdfs_block_labels.csv --aug_ratio 0.1 --output_base_dir deep-loglizer/data/processed/HDFS/hdfs_baseline

### 1.0 anomaly 
# python aug_hdfs_data.py --base_data_dir deep-loglizer/data/processed/HDFS/hdfs_1.0_tar --aug_log_file ablation/baseline/parsed_logs/hdfs_combined_parsed_logs.csv --aug_label_file ablation/baseline/block_labels/hdfs_block_labels.csv --train_anomaly_ratio 1.0 --aug_ratio 0.001 --output_base_dir deep-loglizer/data/processed/HDFS/hdfs_baseline

# python aug_hdfs_data.py --base_data_dir deep-loglizer/data/processed/HDFS/hdfs_1.0_tar --aug_log_file ablation/baseline/parsed_logs/hdfs_combined_parsed_logs.csv --aug_label_file ablation/baseline/block_labels/hdfs_block_labels.csv --train_anomaly_ratio 1.0 --aug_ratio 0.01 --output_base_dir deep-loglizer/data/processed/HDFS/hdfs_baseline

# python aug_hdfs_data.py --base_data_dir deep-loglizer/data/processed/HDFS/hdfs_1.0_tar --aug_log_file ablation/baseline/parsed_logs/hdfs_combined_parsed_logs.csv --aug_label_file ablation/baseline/block_labels/hdfs_block_labels.csv --train_anomaly_ratio 1.0 --aug_ratio 0.1 --output_base_dir deep-loglizer/data/processed/HDFS/hdfs_baseline




## without_cot
### 0.0 anomaly
# python aug_hdfs_data.py --aug_log_file ablation/without_cot/parsed_logs/hdfs_combined_parsed_logs.csv --aug_label_file ablation/without_cot/block_labels/hdfs_block_labels.csv --aug_ratio 0.001 --output_base_dir deep-loglizer/data/processed/HDFS/hdfs_without_cot

# python aug_hdfs_data.py --aug_log_file ablation/without_cot/parsed_logs/hdfs_combined_parsed_logs.csv --aug_label_file ablation/without_cot/block_labels/hdfs_block_labels.csv --aug_ratio 0.01 --output_base_dir deep-loglizer/data/processed/HDFS/hdfs_without_cot

# python aug_hdfs_data.py --aug_log_file ablation/without_cot/parsed_logs/hdfs_combined_parsed_logs.csv --aug_label_file ablation/without_cot/block_labels/hdfs_block_labels.csv --aug_ratio 0.1 --output_base_dir deep-loglizer/data/processed/HDFS/hdfs_without_cot

### 1.0 anomaly 
# python aug_hdfs_data.py --base_data_dir deep-loglizer/data/processed/HDFS/hdfs_1.0_tar --aug_log_file ablation/without_cot/parsed_logs/hdfs_combined_parsed_logs.csv --aug_label_file ablation/without_cot/block_labels/hdfs_block_labels.csv --train_anomaly_ratio 1.0 --aug_ratio 0.001 --output_base_dir deep-loglizer/data/processed/HDFS/hdfs_without_cot

# python aug_hdfs_data.py --base_data_dir deep-loglizer/data/processed/HDFS/hdfs_1.0_tar --aug_log_file ablation/without_cot/parsed_logs/hdfs_combined_parsed_logs.csv --aug_label_file ablation/without_cot/block_labels/hdfs_block_labels.csv --train_anomaly_ratio 1.0 --aug_ratio 0.01 --output_base_dir deep-loglizer/data/processed/HDFS/hdfs_without_cot

# python aug_hdfs_data.py --base_data_dir deep-loglizer/data/processed/HDFS/hdfs_1.0_tar --aug_log_file ablation/without_cot/parsed_logs/hdfs_combined_parsed_logs.csv --aug_label_file ablation/without_cot/block_labels/hdfs_block_labels.csv --train_anomaly_ratio 1.0 --aug_ratio 0.1 --output_base_dir deep-loglizer/data/processed/HDFS/hdfs_without_cot



## without_analysis
### 0.0 anomaly
# python aug_hdfs_data.py --aug_log_file ablation/without_analysis/parsed_logs/hdfs_combined_parsed_logs.csv --aug_label_file ablation/without_analysis/block_labels/hdfs_block_labels.csv --aug_ratio 0.001 --output_base_dir deep-loglizer/data/processed/HDFS/hdfs_without_analysis

# python aug_hdfs_data.py --aug_log_file ablation/without_analysis/parsed_logs/hdfs_combined_parsed_logs.csv --aug_label_file ablation/without_analysis/block_labels/hdfs_block_labels.csv --aug_ratio 0.01 --output_base_dir deep-loglizer/data/processed/HDFS/hdfs_without_analysis

# python aug_hdfs_data.py --aug_log_file ablation/without_analysis/parsed_logs/hdfs_combined_parsed_logs.csv --aug_label_file ablation/without_analysis/block_labels/hdfs_block_labels.csv --aug_ratio 0.1 --output_base_dir deep-loglizer/data/processed/HDFS/hdfs_without_analysis

### 1.0 anomaly 
# python aug_hdfs_data.py --base_data_dir deep-loglizer/data/processed/HDFS/hdfs_1.0_tar --aug_log_file ablation/without_analysis/parsed_logs/hdfs_combined_parsed_logs.csv --aug_label_file ablation/without_analysis/block_labels/hdfs_block_labels.csv --train_anomaly_ratio 1.0 --aug_ratio 0.001 --output_base_dir deep-loglizer/data/processed/HDFS/hdfs_without_analysis

# python aug_hdfs_data.py --base_data_dir deep-loglizer/data/processed/HDFS/hdfs_1.0_tar --aug_log_file ablation/without_analysis/parsed_logs/hdfs_combined_parsed_logs.csv --aug_label_file ablation/without_analysis/block_labels/hdfs_block_labels.csv --train_anomaly_ratio 1.0 --aug_ratio 0.01 --output_base_dir deep-loglizer/data/processed/HDFS/hdfs_without_analysis

# python aug_hdfs_data.py --base_data_dir deep-loglizer/data/processed/HDFS/hdfs_1.0_tar --aug_log_file ablation/without_analysis/parsed_logs/hdfs_combined_parsed_logs.csv --aug_label_file ablation/without_analysis/block_labels/hdfs_block_labels.csv --train_anomaly_ratio 1.0 --aug_ratio 0.1 --output_base_dir deep-loglizer/data/processed/HDFS/hdfs_without_analysis

