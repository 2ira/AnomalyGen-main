import re
import os
import json

def load_json(json_file):
    try:
        with open(json_file, 'r', encoding='utf-8') as file:
            data = json.load(file)
        return data
    except FileNotFoundError:
        print(f"file {json_file} can not find")
        return None
    except json.JSONDecodeError:
        print(f"can noe analyze {json_file} json data")
        return None
    except Exception as e:
        print(f"load  {json_file} error: {e}")
        return None

def main():
    #dir ="/home/ubuntu/LLMlogger/output/hadoop/TaskAttemptImpl_createCommonContainerLaunchContext"
    #dir = "/home/ubuntu/LLMlogger/output/hadoop/MRAppMaster_main"
    
    code_path = os.path.join(dir,"extracted_methods.json")
    code_map = load_json(code_path)
    single_call_path = os.path.join(dir,"merge_single_info.json")
    single_call_map = load_json(single_call_path)
    # single log seq
    single_log_path = os.path.join(dir,"merge_single_log.json")
    single_log_map = load_json(single_log_path)

    #for key,value in single_call_map.items():
    #key = "org.apache.hadoop.metrics2.impl.MetricsSystemImpl:start()"
    #key = "org.apache.hadoop.mapreduce.v2.app.MRAppMaster:createOutputCommitter(org.apache.hadoop.conf.Configuration)"
    key = ""
    print("key is ")
    print(key)
    print("source_code is ")
    print(code_map[key]["source_code"])
    print("cfg is")
    print(single_call_map[key])
    print("log is ")
    print(single_log_map[key])

#main()

def count_func():
    count=0
    all=0
    filtered_files = set()
    with open("functions_with_logs.txt",'r') as f:
        methods = [line.strip() for line in f.readlines()]
    
    code_map = load_json("output/extracted_methods.json")
    for method in methods:
        if method in code_map:
            count+=1
            filtered_files.add(method) 
        all+=1
    
    print(all)
    print(count)

    with open("filtered_functions_with_logs.txt",'w') as f:
        for i in filtered_files:
            f.write(i)
            f.write("\n")
# count_func()

def single_node_count():
    count=0
    all=0
    filtered_files = set()
    
    methods = load_json("output/traced_signatures.json")
    code_map = load_json("output/extracted_methods.json")
    for method in methods:
        if method in code_map:
            count+=1
            filtered_files.add(method) 
        all+=1
    
    print(all)
    print(count)

    with open("filtered_single_nodes.txt",'w') as f:
        for i in filtered_files:
            f.write(i)
            f.write("\n")

# single_node_count()

def filtered():
    count=0
    all=0
    filtered_files = set()
    with open("filtered_single_nodes.txt",'r') as f:
        methods = [line.strip() for line in f.readlines()]
  
    checkpoint_data = load_json("output/enhanced_single_cfg/enhanced_cfg_temp.json")
    processed_signatures = set(checkpoint_data.get('processed_signatures', []))
    for method in methods:
        if method in processed_signatures:
            count+=1
            continue
        
        filtered_files.add(method) 
        all+=1
    
    print(all)
    print(count)

    with open("f2_single_nodes.txt",'w') as f:
        for i in filtered_files:
            f.write(i)
            f.write("\n")
# filtered()


###merge all the single 
def merge():
    merge_node = {}
    json1 = load_json("output/log_events/compressed_logs_valid.json")
    json2 = load_json("output/log_events/compressed_logs_v2.json")

    for key,value in json1.items():
        merge_node[key] = value
    for key,value in json2.items():
        merge_node[key] = value
    print(len(merge_node))
    with open("output/log_events/compressed_logs_all.json",'w') as f:
        json.dump(merge_node,f)

merge()

from pathlib import Path

def count_files_in_folder(folder_path):
    folder = Path(folder_path)
    # whether exists path
    if not folder.exists():
        print(f"file dir path is  {folder_path} not exist")
        return 0
    # whether a dir
    if not folder.is_dir():
        print(f"{folder_path} not a valid path")
        return 0

    # recusive count file amount
    file_count = len(list(folder.rglob('*'))) - len(list(folder.rglob('*/')))
    return file_count

# for example
# folder_path = 'output/merge_info'
# file_count = count_files_in_folder(folder_path)
# print(f"dir {folder_path} all have {file_count} files")