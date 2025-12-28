import os
import re
import json
import logging
from py4j.java_gateway import JavaGateway
import configparser
import argparse
logging.basicConfig(filename="match_source_code.log", level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def locate_source_code_file_path(caller_method,project_dir):
    try:
        parts = caller_method.split(":")
        if len(parts) < 2:
            return None, None
        class_full = parts[0].strip()
        if "$" in class_full:
            outer_class = class_full.split("$")[0]
        else:
            outer_class = class_full
        simple_name = outer_class.split(".")[-1]
        candidate_filename = simple_name + ".java"
        package_dirs = class_full.split(".")[:-1]

        found_path = None
        for root, dirs, files in os.walk(project_dir):
            if candidate_filename in files:
                candidate_path = os.path.join(root, candidate_filename)
                match_count = sum(1 for pkg in package_dirs if pkg in candidate_path)
                if match_count >= len(package_dirs):
                    found_path = candidate_path
                    break
                if not found_path:
                    found_path = candidate_path

        if not found_path:
            print(f"No Java file found for {caller_method}")
            return None
        return found_path
    
    except Exception as e:
        logging.error(f"Error locating source code for {caller_method}: {e}")
        return None

def parse_method_signature(signature):
    parts = signature.split(":", 1)
    fqcn = parts[0]
    method_with_params = parts[1]
    
    if '$' in fqcn:
        simple_class_name = fqcn.split('$')[-1]
    else:
        simple_class_name = fqcn.split('.')[-1]
    
    method_name_end = method_with_params.find('(')
    method_name = method_with_params[:method_name_end]
    param_signature = method_with_params[method_name_end:] 
    return fqcn, simple_class_name, method_name, param_signature

def get_java_method_code(gateway, file_path, simple_class_name, method_name, param_signature):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            code_content = f.read()
        method_code = gateway.entry_point.extractMethodFromCode(code_content, simple_class_name, method_name, param_signature)
        return method_code
    except Exception as e:
        logging.error("error:%s", e)
        return None


def locate_source_code(gateway,signature,file_path):
    # gateway = JavaGateway()

    fqcn, simple_class_name, method_name, param_signature = parse_method_signature(signature)
    
    method_code = get_java_method_code(gateway, file_path, simple_class_name, method_name, param_signature)
    
    if method_code is None:
        logging.warning("failed (None): %s", signature)
        return None
    if isinstance(method_code, str) and method_code.startswith("ERROR:"):
        logging.warning("failed (JavaParser ERROR): %s -> %s", signature, method_code)
        return None
    if str(method_code).strip() == "":
        logging.warning("failed (empty): %s", signature)
        return None

    logging.info("success: %s", signature)
    return method_code

def load_package(config_file='mysql/config.ini'):
    config = configparser.ConfigParser()
    config.read(config_file)
    keywords = config.get('package', 'name', fallback='org.apache')
    return [kw.strip() for kw in keywords.split(',')] if keywords else []

def process_log_file(input_file, project_dir,output_dir="output"):
    gateway = JavaGateway()  # ✅ 只创建一次
    output_file=os.path.join(output_dir,"extracted_methods.json")
    missing_line_info_file=os.path.join(output_dir,"missing_methods.json")

    result_dict = {}
    method_signatures = set()
    missing_dict = {}
    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            # match = re.match(r'(.+)->(.+), depth (\d+)', line.strip())
            match = re.match(r'(.+?)\s*->\s*(.+?)(?:,\s*depth\s*(\d+))?$', line.strip())
            if match:
                caller = match.group(1).strip()
                callee = match.group(2).strip()
                packages = load_package()
                if packages:  # if null, do not filter
                    if any(caller.startswith(pk) for pk in packages):
                        method_signatures.add(caller)
                    if any(callee.startswith(pk) for pk in packages):
                        method_signatures.add(callee)
                else:
                    method_signatures.add(caller)
                    method_signatures.add(callee)
                    
            else:
                print(f"Failed to match line: {line.strip()}")


    for method_signature in method_signatures:
        file_path = locate_source_code_file_path(method_signature,project_dir)
        source_code = locate_source_code(gateway,method_signature,file_path)
      
        if source_code:
            result_dict[method_signature] = {
                'source_code': source_code,
                'file_path': file_path
            }
        else:
            logging.warning(f"Source code not found for method signature: {method_signature}")
            if file_path:
                missing_dict[method_signature] = {
                    'file_path': file_path
                }
            #print(f"Source code not found for {method_signature}")

    with open(output_file, 'w', encoding='utf-8') as json_file:
        json.dump(result_dict, json_file, indent=4, ensure_ascii=False)
    
    with open(missing_line_info_file, 'w', encoding='utf-8') as missing_file:
        json.dump(missing_dict, missing_file, indent=4, ensure_ascii=False)

    logging.info(f"Method source code extraction completed and saved to {output_file}")
    logging.info("finish, all %d methods,no locate %d methods",
                 len(result_dict), len(missing_dict))

def prune_call_chain_by_log_node(call_chain_file, output_file):

    def is_log_node(node_signature):
        lower_signature = node_signature.split('(')[0].lower()
        log_keywords = {'log', 'logger', 'logging', 'debug', 'info', 'warn', 'error', 'trace', 'fatal'}
        return any(kw in lower_signature for kw in log_keywords)
    reverse_call_graph = {}
    with open(call_chain_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("->")
            if len(parts) != 2:
                continue
            caller = parts[0].strip()
            remainder = parts[1].strip()
            if ", depth" in remainder:
                callee_part, _ = remainder.rsplit(", depth", 1)
                callee = callee_part.strip()
            else:
                callee = remainder

            if callee not in reverse_call_graph:
                reverse_call_graph[callee] = set()
            if caller not in reverse_call_graph:
                reverse_call_graph[caller] = set()

            reverse_call_graph[callee].add(caller)
        
    log_nodes = set()
    for node in reverse_call_graph:
        if is_log_node(node):
            log_nodes.add(node)

    nodes_to_keep = set()

    def dfs(node):
        if node in nodes_to_keep:
            return
        nodes_to_keep.add(node)
        if node in reverse_call_graph:
            for caller in reverse_call_graph[node]:
                dfs(caller)
    for log_node in log_nodes:
        dfs(log_node)

    pruned_lines = []
    with open(call_chain_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("->")
            if len(parts) != 2:
                continue
            caller = parts[0].strip()
            remainder = parts[1].strip()
            if ", depth" in remainder:
                callee_part, _ = remainder.rsplit(", depth", 1)
                callee = callee_part.strip()
            else:
                callee = remainder

            if caller in nodes_to_keep and callee in nodes_to_keep:
                pruned_lines.append(line)

    with open(output_file, 'w', encoding='utf-8') as f:
        for pline in pruned_lines:
            f.write(pline + "\n")
    logging.info("pruned all %s", output_file)


def test():

    input_file = "output/pruned_call_deps.txt"
    project_dir = "hadoop"
    process_log_file(input_file, project_dir)
    logging.info("Processing complete.")
    
def main():

    parser = argparse.ArgumentParser(description = "finishd sub graph code mapping")
    parser.add_argument('--call_chain_file', type=str, required=True,help="sub graph file")
    parser.add_argument('--project_dir', type=str, required=True,help="the root dir of project dir")
    parser.add_argument('--output_dir', type=str, required=True,help="output dir of mapping json")
    
    args = parser.parse_args()

    input_file = args.call_chain_file
    project_dir = args.project_dir
    output_dir = args.output_dir

    process_log_file(input_file,project_dir,output_dir)
    prune_call_chain_by_log_node(args.call_chain_file,args.call_chain_file)
    logging.info("Processing complete.")

if __name__ == "__main__":
    # test()
    main()
