"""
Firstly, we prepare the data for training and evaluation.
Inputs:
  - `--original_log_path`, `--original_label_path`: original data paths.
  - `--augmented_log_path`, `--augmented_label_path`: our augmented data paths.
  - `--output_dir`: output directory for prepared data.
  - `--test_ratio`: original data split ratio for test set.
  - `--augmentation_ratio`: for augmentation ratio like`1.5` 表示增加的增强样本数量是原始训练集样本数量的1.5倍。
  - `--train_anomaly_ratio`: In the final training set, we propose th ratio of test最终生成的训练集中，异常样本所占的期望比例。例如，`0.1` 表示希望最终训练集中有10%是异常会话。
Outputs:
  - for `deep-loglizer`
    - `combined_log_structured.csv`: 合并后的日志文件。
    - `combined_anomaly_label.csv`: 合并后的标签文件。
  - 为 `anomaly-detection-log-datasets` (ADLD) 准备：
    - `combined_train_sequences.csv`: 包含原始训练序列和增强序列的文件。
"""
#### step1_split_data -> step2_augment_data -> step3_prepare_data_to_format
import pandas as pd
import argparse
import os
import numpy as np
import re
import pickle
from collections import defaultdict, OrderedDict
from tqdm import tqdm


def get_sessions_from_raw_hdfs(df_log):
    """
    from Content extract BlockId。
    return a DataFrame including ['BlockId', 'EventTemplate', 'AdldEventId']。
    """
    session_dict = defaultdict(list)
    # tqdm(df_log.iterrows(), total=df_log.shape[0])
    for _, row in tqdm(df_log.iterrows(), total=df_log.shape[0], desc="Parsing Raw HDFS log"):
        blkId_list = re.findall(r"(blk_-?\d+)", row["Content"])
        for blk_Id in set(blkId_list):
            session_dict[blk_Id].append({
                'EventTemplate': row['EventTemplate'], 
                'AdldEventId': row['AdldEventId']
            })
    records = []
    for blk_id, events in session_dict.items():
        for event in events:
            records.append({
                'BlockId': blk_id, 
                'EventTemplate': event['EventTemplate'], 
                'AdldEventId': event['AdldEventId']
            })
    return pd.DataFrame(records)

def get_sessions_from_structured(df_log):
    """
    from 'BlockId' to get sessions.
    return a DataFrame including ['BlockId', 'EventTemplate', 'AdldEventId']。
    """
    if 'block_id' in df_log.columns:
        df_log = df_log.rename(columns={'block_id': 'BlockId'})
    return df_log[['BlockId', 'EventTemplate', 'AdldEventId']]

def prepare_data_for_augmentation(
    original_log_path,
    original_label_path,
    augmented_log_path,
    augmented_label_path,
    output_dir,
    augmentation_ratio=1.0,
    test_ratio=0.2, # test set ratio from original data
    train_anomaly_ratio=0.5, # in the final training set, the expected ratio of anomaly samples
    random_seed=42
):
    """
    prepare data for training and evaluation.
    test set is fixed from original data.
    """

    print("="*50)
    print("Executing Data Preparation Script V3 (Final Adaptation)")
    print(f"Params: test_ratio={test_ratio}, augmentation_ratio={augmentation_ratio}, train_anomaly_ratio={train_anomaly_ratio}")
    print("="*50)

    ##------ 1. load all data
    df_orig_log = pd.read_csv(original_log_path)
    df_orig_label = pd.read_csv(original_label_path)
    df_aug_log = pd.read_csv(augmented_log_path)
    df_aug_label = pd.read_csv(augmented_label_path)

    os.makedirs(output_dir, exist_ok=True) #make output dir

    # original label is 'Normal' or 'Anomaly'
    df_orig_label['Label'] = df_orig_label['Label'].apply(lambda x: 'Anomaly' if x != 'Normal' else 'Normal')
    # new label is 'normal', 'explicit', 'implicit' -> all map to new label
    df_aug_label['Label'] = df_aug_label['Label'].apply(lambda x: 'Anomaly' if x != 'normal' else 'Normal')

    ##------ 2. create global template ids mapping -> from template content to template id
    print("\nStep 2: Creating global template-to-integer-ID mapping...")
    all_templates = pd.concat([df_orig_log['EventTemplate'], df_aug_log['EventTemplate']]).unique()
    template_to_adld_id = {template: i + 1 for i, template in enumerate(all_templates)}
    
    df_orig_log['AdldEventId'] = df_orig_log['EventTemplate'].map(template_to_adld_id)
    df_aug_log['AdldEventId'] = df_aug_log['EventTemplate'].map(template_to_adld_id)
    print(f"Created mapping for {len(template_to_adld_id)} unique templates.")

    ##------ 3. extract session information (differential processing)
    print("\nStep 3: Extracting session information (differential processing)...")
    # original HDFS logs have no block_id, need to extract from Content
    print("Processing original HDFS log (raw format)...")
    df_orig_sessions = get_sessions_from_raw_hdfs(df_orig_log)
    # augment_data have BlockId
    print("Processing augmented log (structured format)...")
    df_aug_sessions = get_sessions_from_structured(df_aug_log)

    ##------ 4. split original data into train/test
    print("\nStep 4: Splitting original data into train and a fixed test set...")
    np.random.seed(random_seed)
    all_orig_block_ids = df_orig_label['BlockId'].unique()
    np.random.shuffle(all_orig_block_ids)
    
    train_size = int(len(all_orig_block_ids) * (1 - test_ratio))
    orig_train_ids = set(all_orig_block_ids[:train_size])
    gold_standard_test_ids = set(all_orig_block_ids[train_size:])
   
    df_orig_train_sessions = df_orig_sessions[df_orig_sessions['BlockId'].isin(orig_train_ids)]
    df_gold_test_sessions = df_orig_sessions[df_orig_sessions['BlockId'].isin(gold_standard_test_ids)]

    # **【FIX】**: Define df_gold_test_label here so it can be used later.
    df_gold_test_label = df_orig_label[df_orig_label['BlockId'].isin(gold_standard_test_ids)]
    print(f"Golden test set created with {len(gold_standard_test_ids)} sessions.")
   
    # --- 4. construct the final training set according to augmentation_ratio and train_anomaly_ratio ---
    print("\nStep 5: Constructing the final augmented training set...")
    orig_train_labels_map = dict(zip(df_orig_label['BlockId'], df_orig_label['Label']))
    aug_labels_map = dict(zip(df_aug_label['BlockId'], df_aug_label['Label']))
    
    orig_train_normal_ids = {bid for bid in orig_train_ids if orig_train_labels_map.get(bid) == 'Normal'}
    orig_train_abnormal_ids = {bid for bid in orig_train_ids if orig_train_labels_map.get(bid) == 'Anomaly'}
    
    aug_normal_ids = {bid for bid, label in aug_labels_map.items() if label == 'Normal'}
    aug_abnormal_ids = {bid for bid, label in aug_labels_map.items() if label == 'Anomaly'}
    
    available_normal_ids = list(orig_train_normal_ids.union(aug_normal_ids))
    available_abnormal_ids = list(orig_train_abnormal_ids.union(aug_abnormal_ids))
    
    base_train_size = len(orig_train_ids)
    final_train_size = base_train_size + int(base_train_size * augmentation_ratio)
    target_abnormal_count = int(final_train_size * train_anomaly_ratio)
    target_normal_count = final_train_size - target_abnormal_count
    
    final_train_normal_ids = np.random.choice(available_normal_ids, size=target_normal_count, replace=len(available_normal_ids) < target_normal_count)
    final_train_abnormal_ids = np.random.choice(available_abnormal_ids, size=target_abnormal_count, replace=len(available_abnormal_ids) < target_abnormal_count)
    final_train_ids = set(final_train_normal_ids).union(set(final_train_abnormal_ids))
    
    all_sessions = pd.concat([df_orig_sessions, df_aug_sessions])
    df_final_train_sessions = all_sessions[all_sessions['BlockId'].isin(final_train_ids)]
     
     # --- 5. packing dataset ---
    print("\nStep 6: Packaging data for each repository...")
    
    # A) for deep-loglizer generate .pkl files
    deeploglizer_dir = os.path.join(output_dir, f'deeploglizer_aug_{augmentation_ratio}_ano_{train_anomaly_ratio}_test_{test_ratio}')
    os.makedirs(deeploglizer_dir, exist_ok=True)
    all_labels_map = {**orig_train_labels_map, **aug_labels_map}
    
    def create_session_dict(df_sessions, labels_map):
        session_dict = OrderedDict()
        for _, row in df_sessions.iterrows():
            blk_id = row['BlockId']
            if blk_id not in session_dict:
                session_dict[blk_id] = defaultdict(list)
            session_dict[blk_id]['templates'].append(row['EventTemplate'])
        for blk_id in session_dict.keys():
            label_str = labels_map.get(blk_id, 'Normal') # Normal
            session_dict[blk_id]['label'] = 1 if label_str == 'Anomaly' else 0
        return session_dict
    
    session_train_dict = create_session_dict(df_final_train_sessions, all_labels_map)
    session_test_dict = create_session_dict(df_gold_test_sessions, orig_train_labels_map)
   
    with open(os.path.join(deeploglizer_dir, "session_train.pkl"), "wb") as fw:
        pickle.dump(session_train_dict, fw)
    
    with open(os.path.join(deeploglizer_dir, "session_test.pkl"), "wb") as fw:
        pickle.dump(session_test_dict, fw)
    print(f"-> deep-loglizer .pkl files saved to: {deeploglizer_dir}")
    print(f"   (Train sessions: {len(session_train_dict)}, Test sessions: {len(session_test_dict)})")
    
    # B) pack for ADLD
    adld_dir = os.path.join(output_dir, f'adld_aug_{augmentation_ratio}_ano_{train_anomaly_ratio}_test_{test_ratio}')
    os.makedirs(adld_dir, exist_ok=True)
    
    def sessions_to_adld_sequences(df_sessions):
        if df_sessions.empty: return pd.DataFrame(columns=['BlockId', 'Sequence'])
        df_sessions['AdldEventId_str'] = df_sessions['AdldEventId'].astype(str)
        sequences = df_sessions.groupby('BlockId')['AdldEventId_str'].apply(' '.join).reset_index(name='Sequence')
        return sequences
    
    train_seq = sessions_to_adld_sequences(df_final_train_sessions)
    test_seq = sessions_to_adld_sequences(df_gold_test_sessions)
    
    test_labels_map = dict(zip(df_gold_test_label['BlockId'], df_gold_test_label['Label']))
    test_normal_seq = test_seq[test_seq['BlockId'].map(test_labels_map) == 'Normal']
    test_abnormal_seq = test_seq[test_seq['BlockId'].map(test_labels_map) == 'Anomaly']
    
    dir_prefix = 'hdfs'
    train_seq[['BlockId', 'Sequence']].to_csv(os.path.join(adld_dir, f'{dir_prefix}_train'), index=False, header=False)
    test_normal_seq[['BlockId', 'Sequence']].to_csv(os.path.join(adld_dir, f'{dir_prefix}_test_normal'), index=False, header=False)
    test_abnormal_seq[['BlockId', 'Sequence']].to_csv(os.path.join(adld_dir, f'{dir_prefix}_test_abnormal'), index=False, header=False)
    
    print(f"-> ADLD sequence files saved to: {adld_dir}")
    print("\nData preparation V5 complete!")
    
   

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--original_log_path', type=str, required=True)
    parser.add_argument('--original_label_path', type=str, required=True)
    parser.add_argument('--augmented_log_path', type=str, required=True)
    parser.add_argument('--augmented_label_path', type=str, required=True)
    parser.add_argument('--output_dir', type=str, default='./prepared_data')
    parser.add_argument('--augmentation_ratio', type=float, default=1.0)
    parser.add_argument('--test_ratio', type=float, default=0.2)
    parser.add_argument('--train_anomaly_ratio', type=float, default=0.5)
    args = parser.parse_args()
    prepare_data_for_augmentation(**vars(args))

# ```
# Use the test examples:
# python prepare_data.py \
#     --original_log_path /path/to/HDFS.log_structured.csv \
#     --original_label_path /path/to/anomaly_label.csv \
#     --augmented_log_path /path/to/your_augmented_log.csv \
#     --augmented_label_path /path/to/your_augmented_label.csv \
#     --output_dir ./prepared_data \
#     --augmentation_ratio 1.0  # 增强数据量 = 1倍原始训练数据

# Use the test examples:
"""
python data_preparing.py \
  --original_log_path deep-loglizer/data/HDFS/HDFS_100k.log_structured.csv \
  --original_label_path deep-loglizer/data/HDFS/anomaly_label.csv \
  --augmented_log_path output/log_events/hdfs_combined_parsed_logs.csv \
  --augmented_label_path output/log_events/hdfs_block_labels.csv \
  --output_dir ./prepared_data \
  --augmentation_ratio 0.1 \
  --test_ratio 0.2 \
  --train_anomaly_ratio 0.1
"""




# ```

