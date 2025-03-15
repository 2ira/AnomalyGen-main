import re
import os
import json

def load_json(json_file):
    try:
        with open(json_file, 'r', encoding='utf-8') as file:
            data = json.load(file)
        return data
    except FileNotFoundError:
        print(f"文件 {json_file} 未找到。")
        return None
    except json.JSONDecodeError:
        print(f"无法解析 {json_file} 中的 JSON 数据。")
        return None
    except Exception as e:
        print(f"加载 {json_file} 时出现未知错误: {e}")
        return None

def main():
    #dir ="/home/ubuntu/LLMlogger/output/hadoop/TaskAttemptImpl_createCommonContainerLaunchContext"
    #dir = "/home/ubuntu/LLMlogger/output/hadoop/RMContainerAllocator_heartbeat"
    #dir = "/home/ubuntu/LLMlogger/output/hadoop/HttpServer2_initializeWebServer"
    #dir = "/home/ubuntu/LLMlogger/output/hadoop/JobHistoryUtils_getDefaultFileContext"
    #dir = "/home/ubuntu/LLMlogger/output/hadoop/JobImpl_handle"
    #dir = "/home/ubuntu/LLMlogger/output/hadoop/LeaseRenewer_run"
    #dir = "/home/ubuntu/LLMlogger/output/hadoop/MetricsSystemImpl_start"
    #dir = "/home/ubuntu/LLMlogger/output/hadoop/MRAppMaster_createOutputCommitter"
    #dir = "/home/ubuntu/LLMlogger/output/hadoop/MRAppMaster_initAndStartAppMaster"
    #dir = "/home/ubuntu/LLMlogger/output/hadoop/MRAppMaster_main"
    #dir = "/home/ubuntu/LLMlogger/output/hadoop/MRAppMaster_serviceInit"
    #dir = "/home/ubuntu/LLMlogger/output/hadoop/RackResolver_resolve"
    #dir = "/home/ubuntu/LLMlogger/output/hadoop/RMContainerRequestor_makeRemoteRequest"
    #dir = "/home/ubuntu/LLMlogger/output/hadoop/RMContainerRequestor_serviceInit"
 
    
    code_path = os.path.join(dir,"extracted_methods.json")
    code_map = load_json(code_path)
    single_call_path = os.path.join(dir,"merge_single_info.json")
    single_call_map = load_json(single_call_path)
    # single log seq
    single_log_path = os.path.join(dir,"merge_single_log.json")
    single_log_map = load_json(single_log_path)

    #for key,value in single_call_map.items():
    #key="org.apache.hadoop.mapreduce.v2.app.job.impl.TaskAttemptImpl:createCommonContainerLaunchContext(java.util.Map,org.apache.hadoop.conf.Configuration,org.apache.hadoop.security.token.Token,org.apache.hadoop.mapred.JobID,org.apache.hadoop.security.Credentials)"
    #key="org.apache.hadoop.mapreduce.v2.app.job.impl.TaskAttemptImpl:configureJobJar(org.apache.hadoop.conf.Configuration,java.util.Map)"
    #key = "org.apache.hadoop.mapreduce.v2.app.rm.RMContainerAllocator:heartbeat()"
    #key = "org.apache.hadoop.http.HttpServer2:initializeWebServer(java.lang.String,java.lang.String,org.apache.hadoop.conf.Configuration,java.lang.String[])"
    #key = "org.apache.hadoop.mapreduce.v2.jobhistory.JobHistoryUtils:getDefaultFileContext()"
    #key = "org.apache.hadoop.mapreduce.v2.app.job.impl.JobImpl:handle(org.apache.hadoop.mapreduce.v2.app.job.event.JobEvent)"
    #key = "org.apache.hadoop.hdfs.client.impl.LeaseRenewer:run(int)"
    #key = "org.apache.hadoop.metrics2.impl.MetricsSystemImpl:start()"
    #key = "org.apache.hadoop.mapreduce.v2.app.MRAppMaster:createOutputCommitter(org.apache.hadoop.conf.Configuration)"
    #key =  "org.apache.hadoop.mapreduce.v2.app.MRAppMaster:initAndStartAppMaster(org.apache.hadoop.mapreduce.v2.app.MRAppMaster,org.apache.hadoop.mapred.JobConf,java.lang.String)"
    #key = "org.apache.hadoop.mapreduce.v2.app.MRAppMaster:main(java.lang.String[])"
    #key = "org.apache.hadoop.mapreduce.v2.app.MRAppMaster:serviceInit(org.apache.hadoop.conf.Configuration)"
    #key = "org.apache.hadoop.yarn.util.RackResolver:resolve(java.util.List)"
    #key = "org.apache.hadoop.mapreduce.v2.app.rm.RMContainerRequestor:makeRemoteRequest()"
    #key="org.apache.hadoop.mapreduce.v2.app.rm.RMContainerRequestor:serviceInit(org.apache.hadoop.conf.Configuration)"
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
    json1 = load_json("output/enhanced_single_cfg/enhanced_cfg.json")
    json2 = load_json("output/enhanced_single_cfg12/enhanced_cfg.json")
    # json3 = load_json("output/enhanced_single_cfg/m3_enhanced_cfg.json")
    # json4 = load_json("output/enhanced_single_cfg/enhanced_cfg.json")
    # json2 = load_json("output/enhanced_single_cfg/m2_enhanced_cfg.json")

    for key,value in json1.items():
        merge_node[key] = value
    for key,value in json2.items():
        merge_node[key] = value
    # for key,value in json3.items():
    #     merge_node[key] = value
    # for key,value in json4.items():
    #     merge_node[key] = value
    print(len(merge_node))
    with open("output/enhanced_single_cfg/merged_enhanced_cfg.json",'w') as f:
        json.dump(merge_node,f)

# merge()

from pathlib import Path

def count_files_in_folder(folder_path):
    folder = Path(folder_path)
    # 检查路径是否存在
    if not folder.exists():
        print(f"指定的文件夹路径 {folder_path} 不存在。")
        return 0
    # 检查路径是否为文件夹
    if not folder.is_dir():
        print(f"{folder_path} 不是一个有效的文件夹路径。")
        return 0

    # 递归统计文件数量
    file_count = len(list(folder.rglob('*'))) - len(list(folder.rglob('*/')))
    return file_count

# 示例使用
# folder_path = 'output/merge_info'
# file_count = count_files_in_folder(folder_path)
# print(f"文件夹 {folder_path} 中共有 {file_count} 个文件。")