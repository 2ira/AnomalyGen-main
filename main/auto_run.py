import os
import sys
import subprocess
import shutil
import argparse
import time
import signal
import socket

def get_entry_name(entry):
 
    parts = entry.split(":", 1)
    fqcn = parts[0]
    method_with_params = parts[1]
    simple_class_name = ""

    if '$' in fqcn:
        simple_class_name = fqcn.split('$')[-1]
    else:
        simple_class_name = fqcn.split('.')[-1]

    method_name_end = method_with_params.find('(')
    method_name = method_with_params[:method_name_end]

    simple_entry_name = f"{simple_class_name}_{method_name}"
    return simple_entry_name


def create_output_dirs(project_dir, entry_functions):
    repo_name = os.path.basename(project_dir)
    output_dir = f"output/{repo_name}"

    # Create the main output directory
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Create subdirectories for each entry function
    entry_dirs = {}
    for entry in entry_functions:
        simple_entry_name = get_entry_name(entry)
        entry_dir = os.path.join(output_dir, simple_entry_name)
        if not os.path.exists(entry_dir):
            os.makedirs(entry_dir)
        entry_dirs[entry] = entry_dir

    return output_dir, entry_dirs


def extract_call_deps(entry_functions, output_dir,depth,batch_size=2):
  
    total_entries = len(entry_functions)
    print(f"all address {total_entries} entry ")
    

    for i in range(0, total_entries, batch_size):
        batch = entry_functions[i:i + batch_size] 
        print(f"processing {i // batch_size + 1} ,call{len(batch)} entry")

      
        for entry in batch:
            simple_entry_name = get_entry_name(entry)
            entry_output_dir = os.path.join(output_dir, simple_entry_name)
            subprocess.run(['python3', 'main/call_dep.py', '--entry_function', entry, '--output_dir', f'{entry_output_dir}', '--depth', str(depth)])
        
        print(f" {i // batch_size + 1} finish ,waiting")
        time.sleep(3)  

def wait_for_port(port, host='127.0.0.1', timeout=60):
    """waiting for the port to be open"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            result = sock.connect_ex((host, port))
            if result == 0:
                print(f"Java Gateway is ready on port {port}")
                return True
        time.sleep(1)
        print("Waiting for Java Gateway to start...")
    return False

def parse_and_match_source_code(entry_functions, output_dir,project_dir):
    print("Starting MethodExtractorGateWay")
    subprocess.run(['pkill', '-f', 'com.example.(MethodExtractorGateway|JavaParserServer)'], check=False)
    time.sleep(2)  

    # 1. 创建日志文件，用来查看 Java 端的报错
    java_log_file = open("java_gateway_debug.log", "w")

    # 2. 启动 Java Gateway，并重定向输出到日志文件
    java_gateway = subprocess.Popen(
        ['mvn', 'exec:java', '-Dexec.mainClass=com.example.MethodExtractorGateway'],
        cwd='java-parser',
        stdout=java_log_file, # 关键：把标准输出写入文件
        stderr=java_log_file  # 关键：把错误输出写入文件
    )
    time.sleep(5)  

    try:
        if not wait_for_port(25333):
            print("Error: Java Gateway failed to start in 60 seconds.")
            print("Please check 'java_gateway_debug.log' for details.")
            return # exit 

        for entry in entry_functions:
            simple_entry_name = get_entry_name(entry)
            entry_output_dir = os.path.join(output_dir, simple_entry_name)
            print(f"Processing source code matching for entry: {entry}")
            subprocess.run(['python3', 'main/match_source_code_v2.py', '--call_chain_file', f'{entry_output_dir}/pruned_call_deps.txt','--project_dir',project_dir,'--output_dir', entry_output_dir])
    finally:
        if java_gateway:
            java_gateway.terminate()
            try:
                java_gateway.wait(timeout=5)
            except subprocess.TimeoutExpired:
                java_gateway.kill()
        if java_log_file:
            java_log_file.close()
        print("MethodExtractorGateway Closed")
        

def generate_cfg_and_log_seq(entry_functions, output_dir):
    print("code mapping...")
 
    subprocess.run(['pkill', '-f', 'com.example.(MethodExtractorGateway|JavaParserServer)'], check=False)
    time.sleep(2)  
    java_server = subprocess.Popen(
        ['mvn', 'compile', 'exec:java', '-Dexec.mainClass=com.example.JavaParserServer'],
        cwd='java-parser'
    )
    time.sleep(6)  

    try:
        for entry in entry_functions:
            simple_entry_name = get_entry_name(entry)
            entry_output_dir = os.path.join(output_dir, simple_entry_name)
            subprocess.run(['python3', 'main/create_node_info.py', '--call_chain_file', f'{entry_output_dir}/pruned_call_deps.txt', '--source_mapping', f'{entry_output_dir}/extracted_methods.json', '--output_dir', entry_output_dir])

    finally:
        java_server.send_signal(signal.SIGTERM)
        java_server.wait(timeout=7)
        print("JavaParserServer Closed")
        time.sleep(3)  
        
## Stage 3: Merge and stimulate log Sequence ##
def merge_results(entry_functions, output_dir):
    print("merging...")
    for entry in entry_functions:
        simple_entry_name = get_entry_name(entry)
        entry_output_dir = os.path.join(output_dir, simple_entry_name)
        subprocess.run(['python3', 'main/merge_node.py', '--call_chain_file', f'{entry_output_dir}/pruned_call_deps.txt', '--source_mapping', f'{entry_output_dir}/extracted_methods.json', '--single_call_path', f'{entry_output_dir}/prune_call_path_javaparser.json', '--output_dir', entry_output_dir])


def merge_results_without_cot(entry_functions, output_dir):
    print("Merge results...")
    for entry in entry_functions:
        simple_entry_name = get_entry_name(entry)
        entry_output_dir = os.path.join(output_dir, simple_entry_name)
        subprocess.run(['python3', 'main/ablation_merge_node.py', '--call_chain_file', f'{entry_output_dir}/pruned_call_deps.txt', '--source_mapping', f'{entry_output_dir}/extracted_methods.json', '--single_call_path', f'{entry_output_dir}/prune_call_path_javaparser.json', '--output_dir', entry_output_dir])

def merge_results_without_static_analysis(entry_functions, output_dir):
    print("Merge results...")
    for entry in entry_functions:
        simple_entry_name = get_entry_name(entry)
        entry_output_dir = os.path.join(output_dir, simple_entry_name)
        subprocess.run(['python3', 'main/ablation_merge_node_v2.py', '--call_chain_file', f'{entry_output_dir}/pruned_call_deps.txt', '--source_mapping', f'{entry_output_dir}/extracted_methods.json', '--output_dir', entry_output_dir])


def default_process(project_dir,entry_functions, output_dir,depth):
    extract_call_deps(entry_functions, output_dir,depth)
    parse_and_match_source_code(entry_functions, output_dir,project_dir)
    generate_cfg_and_log_seq(entry_functions, output_dir)
    merge_results(entry_functions, output_dir)


def main():
    parser = argparse.ArgumentParser(description="auto process")
    parser.add_argument('--project_dir', type=str, required=True, help="input project dir")
    parser.add_argument('--entry_functions', nargs='+', required=True, help="entries")
    parser.add_argument('--depth', type=int,required=False,default=3, help="depth, default 3")
    # parser.add_argument('--input_dir',type=str,required=True,help="output dir of javacallgraph")
    args = parser.parse_args()

  
    project_dir = args.project_dir
    entry_functions = args.entry_functions
    depth = args.depth
    # input_dir = args.input_dir

    start_time = time.time()


    repo_name = os.path.basename(project_dir)
    output_dir = f"output/{repo_name}"

    # Create the main output directory
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    need_entry_functions = []

    for entry in entry_functions:
        simple_entry_name = get_entry_name(entry)
        entry_output_dir = os.path.join(output_dir, simple_entry_name)
        if not os.path.exists(entry_output_dir):
            need_entry_functions.append(entry)
    
    output_dir, entry_dirs = create_output_dirs(project_dir,need_entry_functions)
    default_process(project_dir,need_entry_functions, output_dir,depth)
    
    print("all the task done!")

    end_time = time.time()  
    print(f"All we address entry function:{len(need_entry_functions)}")
    print(f"All use time: {end_time - start_time:.2f} seconds.")
    if len(need_entry_functions) > 0:
        print(f"average time per entry: {(end_time - start_time)/len(need_entry_functions):.2f} seconds.")
    else:
        print("No new entry functions were processed, so average time per entry is not calculated.")
    
if __name__ == "__main__":
    main()