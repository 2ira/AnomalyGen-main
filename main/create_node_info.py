import os
import json
import re
import argparse
import time
from java_parser_client import analyze_java_code
from models.prompts.analysis_code import get_java_parser_with_llm
from models.prompts.generate_node_info import generate_node_log_seq_v2
from models.get_resp import get_response
import concurrent.futures

def load_json(json_file):
    try:
        with open(json_file, 'r', encoding='utf-8') as file:
            data = json.load(file)
        return data
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None
    except Exception as e:
        return None
    
# def address_log_seq(message):
#     xml_content = re.search(r'```xml(.*?)```', message, re.DOTALL)
#     if xml_content:
#         xml_data = xml_content.group(1).strip() 
#         return xml_data
#     else:
#         return message

def analyze_code_by_source(source_code):
   
    return source_code

def analyze_code_by_javaparser(source_code):
   
    return analyze_java_code(source_code)

def analyze_code_by_llm(source_code):
   
    prompts = list(get_java_parser_with_llm(source_code))
    reply = get_response(prompts)
    return reply

# def get_single_node_log(info):
#     #### Fix: 注意新的get_response的prompt输入是一个list
#     prompts = list(generate_node_log_seq_v2(info))
#     reply = get_response(prompts)
#     print("====================== DEBUG: REPLY TO LLM ======================")
#     print(reply)
#     print("==================================================================")
#     reply = address_log_seq(reply)
#     return reply

def parse_call_file(filename):
    call_graph_with_depth = {}
    all_callees = set()
    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("->")
            if len(parts) != 2:
                continue  
            caller = parts[0].strip()
            rest = parts[1].strip()
            if ", depth" in rest:
                callee_part, depth_part = rest.rsplit(", depth", 1)
                callee = callee_part.strip()
                try:
                    depth = int(depth_part.strip())
                except ValueError:
                    depth = None
            else:
                callee = rest
                depth = None

            if caller not in call_graph_with_depth:
                call_graph_with_depth[caller] = []
            call_graph_with_depth[caller].append((callee, depth))
            all_callees.add(callee)
    return call_graph_with_depth, all_callees

def build_simple_call_graph(call_graph_with_depth):
    simple_call_graph = {}
    for caller, callees in call_graph_with_depth.items():
        unique_callees = []
        seen = set()
        for callee, _ in callees:
            if callee not in seen:
                unique_callees.append(callee)
                seen.add(callee)
        simple_call_graph[caller] = unique_callees
    return simple_call_graph

def collect_tasks_dfs(signature, simple_call_graph, code_map, visited, tasks_to_run):
    if signature in visited:
        return
    visited.add(signature)
    if signature in code_map and code_map[signature].get('source_code'):
        # if have code, then we need to process this node
        tasks_to_run.append(signature)
    for child in simple_call_graph.get(signature, []):
        collect_tasks_dfs(child, simple_call_graph, code_map, visited, tasks_to_run)

# parallel address llm call
def process_single_node(signature, simple_call_graph, code_map):
    source_code = code_map[signature]['source_code']
    node_info = str(analyze_code_by_javaparser(source_code))
    callpaths = ""
    for child in simple_call_graph.get(signature, []):
        callpaths = callpaths + "->"+child+"\n"      
    # info = f"signature: {signature}, source_code: {source_code}, all the callpath: {callpaths} , the origin cfg of this signature: {node_info}"
    print(f"--- Submitting task for: {signature} ---")
    # node_log_seq = get_single_node_log(info)
    return signature, node_info

def test():
    call_file = "output/hadoop/MRAppMaster_main/pruned_call_deps.txt"
    call_graph_with_depth, all_callees = parse_call_file(call_file)
    simple_call_graph = build_simple_call_graph(call_graph_with_depth)

    code_map =  load_json("output/hadoop/MRAppMaster_main/extracted_methods.json")

    global visited, single_call_path_json, single_log_seq_json
    visited = set()
    single_call_path_json = {}
    single_log_seq_json = {}

    all_callers = set(simple_call_graph.keys())
    roots = all_callers - all_callees
    if not roots:
        if simple_call_graph:
            roots = {next(iter(simple_call_graph.keys()))}
        else:
            print("empty")
            return  

    for root in roots:
        dfs(root, simple_call_graph, code_map)
    
    single_call_path = "output/hadoop/MRAppMaster_main/prune_call_path_javaparser.json"
    with open(single_call_path, "w", encoding="utf-8") as f:
        json.dump(single_call_path_json, f, indent=2, ensure_ascii=False)

    single_log_seq = "output/hadoop/MRAppMaster_main/prune_log_seq_javaparser.json"
    with open(single_log_seq, "w", encoding="utf-8") as f:
        json.dump(single_log_seq_json, f, indent=2, ensure_ascii=False)
    
    print(f"finish prune")

def main():
    parser = argparse.ArgumentParser(description = "finishd sub graph code mapping")
    parser.add_argument('--call_chain_file', type=str, required=True,help="sub graph file")
    parser.add_argument('--source_mapping', type=str, required=True,help="source_code mapping file path")
    parser.add_argument('--output_dir', type=str, required=True,help="output dir of mapping json")
    
    args = parser.parse_args()

    start_time = time.time()

    call_file = args.call_chain_file
    source_mapping = args.source_mapping
    output_dir = args.output_dir

    call_graph_with_depth, all_callees = parse_call_file(call_file)
    simple_call_graph = build_simple_call_graph(call_graph_with_depth)
    code_map = load_json(source_mapping)

    all_callers = set(simple_call_graph.keys())
    roots = all_callers - all_callees
    if not roots:
        if simple_call_graph:
            roots = {next(iter(simple_call_graph.keys()))}
        else:
            print("empty")
            return  
    
    visited = set()
    tasks_to_run = []
    
    for root in roots:
        collect_tasks_dfs(root, simple_call_graph, code_map, visited, tasks_to_run)

    print(f"Found {len(tasks_to_run)} nodes with source code to analyze.")

    single_call_path_json = {}
    
    ## set a thread pool to address llm call
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_to_sig = {executor.submit(process_single_node, sig, simple_call_graph, code_map): sig for sig in tasks_to_run}
        for future in concurrent.futures.as_completed(future_to_sig):
            sig = future_to_sig[future]
            try:
                signature, node_info = future.result()
                single_call_path_json[signature] = node_info
                print(f"+++ Successfully processed: {signature} +++")
            except Exception as exc:
                print(f"!!! Task for {sig} generated an exception: {exc} !!!")
    
    single_call_path = os.path.join(output_dir,"prune_call_path_javaparser.json")
    with open(single_call_path, "w", encoding="utf-8") as f:
        json.dump(single_call_path_json, f, indent=2, ensure_ascii=False)
    
    print(f"single java callgraph finished")
    end_time = time.time()
    print(f"Total time in generating callgraph {end_time - start_time} seconds")

if __name__ == "__main__":
    main()
    # test()