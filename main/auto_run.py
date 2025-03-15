import os
import sys
import subprocess
import shutil
import argparse
import time
import signal

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

def store_method_calls_in_db(input_dir):
    print("store to database...")

    subprocess.run(['python3', 'mysql/import_method_call.py', '--input_file',f"{input_dir}/method_call.txt"])

def run_prune_and_update(output_dir):
    print("pruning...")
    subprocess.run(['python3', 'mysql/prune_and_update_db.py', '--output_file', f'{output_dir}/start_nodes.txt'])

def get_global_source_code(project_dir):
    print("start MethodExtractorGateWay and analyze  code ")
    subprocess.run(['pkill', '-f', 'com.example.(MethodExtractorGateway|JavaParserServer)'], check=False)
    time.sleep(2) 

    java_gateway = subprocess.Popen(
        ['mvn', 'compile', 'exec:java', '-Dexec.mainClass=com.example.MethodExtractorGateway'],
        cwd='java-parser'
    )
    time.sleep(5) 

    try:
        print("extract all the code ...")
        subprocess.run(['python3', 'main/get_pruned_node_code.py', '--project_dir',project_dir])
    finally:
        java_gateway.send_signal(signal.SIGTERM)
        java_gateway.wait(timeout=10)
        print("MethodExtratorGateway ended")
        time.sleep(3)  
    

def get_global_cfg(input_file):
    print("mapping code...")
 
    subprocess.run(['pkill', '-f', 'com.example.(MethodExtractorGateway|JavaParserServer)'], check=False)
    time.sleep(2) 
   
    java_server = subprocess.Popen(
        ['mvn', 'compile', 'exec:java', '-Dexec.mainClass=com.example.JavaParserServer'],
        cwd='java-parser'
    )
    time.sleep(6)  

    try:
        print("finish all the cfg")
        subprocess.run(['python3', 'main/get_pruned_node_cfg.py', '--input_file',input_file])
    finally:
        #
        java_server.send_signal(signal.SIGTERM)
        java_server.wait(timeout=7)
        print("JavaParserServer ended")
        time.sleep(3)  


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


def parse_and_match_source_code(entry_functions, output_dir,project_dir):
    print("启动MethodExtractorGateWay")
    subprocess.run(['pkill', '-f', 'com.example.(MethodExtractorGateway|JavaParserServer)'], check=False)
    time.sleep(2)  

    java_gateway = subprocess.Popen(
        ['mvn', 'compile', 'exec:java', '-Dexec.mainClass=com.example.MethodExtractorGateway'],
        cwd='java-parser'
    )
    time.sleep(5)  

    try:
        for entry in entry_functions:
            simple_entry_name = get_entry_name(entry)
            entry_output_dir = os.path.join(output_dir, simple_entry_name)
            subprocess.run(['python3', 'main/match_source_code_v2.py', '--call_chain_file', f'{entry_output_dir}/pruned_call_deps.txt','--project_dir',project_dir,'--output_dir', entry_output_dir])
    finally:
        java_gateway.send_signal(signal.SIGTERM)
        java_gateway.wait(timeout=5)
        print("MethodExtratorGateway 进程已关闭。")
        time.sleep(3)  
        

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
        subprocess.run(['python3', 'main/merge_node.py', '--call_chain_file', f'{entry_output_dir}/pruned_call_deps.txt', '--source_mapping', f'{entry_output_dir}/extracted_methods.json', '--single_log_seq', f'{entry_output_dir}/prune_log_seq_javaparser.json', '--output_dir', entry_output_dir])

def main():
    parser = argparse.ArgumentParser(description="auto process")
    parser.add_argument('--project_dir', type=str, required=True, help="input project dir")
    parser.add_argument('--entry_functions', nargs='+', required=True, help="entries")
    parser.add_argument('--depth', type=int,required=False,default=10, help="depth,default 10")
    parser.add_argument('--input_dir',type=str,required=True,help="output dir of javacallgraph")
    args = parser.parse_args()

  
    project_dir = args.project_dir
    entry_functions = args.entry_functions
    depth = args.depth
    input_dir = args.input_dir


    output_dir, entry_dirs = create_output_dirs(project_dir, entry_functions)

  
    extract_classes(project_dir, output_dir)
    configure_java_callgraph2(output_dir)
    store_method_calls_in_db(input_dir)
    run_prune_and_update(output_dir)

    input_file = "output/extracted_methods.json"
    #get_global_source_code(project_dir)
    # get_global_cfg(input_file)

    extract_call_deps(entry_functions, output_dir,depth)
    parse_and_match_source_code(entry_functions, output_dir,project_dir)
    generate_cfg_and_log_seq(entry_functions, output_dir)
    merge_results(entry_functions, output_dir)

    print("all the task done!")

if __name__ == "__main__":
    main()