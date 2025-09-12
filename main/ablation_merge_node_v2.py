
import re
import os
import json
import logging
import argparse
from models.prompts.merge_node_info import get_merge_nodes_by_llm_v4
from models.get_resp import get_response
import xml.etree.ElementTree as ET
import tiktoken
from typing import Union


logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler("merge_log_output.log", encoding='utf-8'),
                        logging.StreamHandler()
                    ])
logger = logging.getLogger()


def count_string_tokens(
    text: Union[str, None], 
) -> int:
    if text is None or not isinstance(text, str):
        if text is None:
            return 0
        raise ValueError(f"Input must be string, now type is {type(text)}")
    if len(text.strip()) == 0: 
        return 0
    # default model -> cl100k_base
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
    except KeyError:
        print(f"Warning: can not encoding,use cl100k_base instead")
        encoding = tiktoken.get_encoding("cl100k_base")
    token_ids = encoding.encode(text)
    return len(token_ids)
 

def address_log_seq(message):

    if "'```xml" not in message:
        return message
    
    xml_content = re.search(r'```xml(.*?)```', message, re.DOTALL)
    xml_data = None
    
    if xml_content:
        xml_data = xml_content.group(1).strip() 
    else:
        xml_data = message
        
    if "<enhanced_paths>" in xml_data:
   
        pattern = r'(<enhanced_paths>.*?</enhanced_paths>)'
        match = re.search(pattern, xml_data, re.DOTALL)
        if match:
            xml_data = match.group(1)

    elif "<valid_paths>" in xml_data:
        pattern = r'(<valid_paths>.*?</valid_paths>)'
        match = re.search(pattern, xml_data, re.DOTALL)
        if match:
            xml_data = match.group(1)
    
    return xml_data

class StackDFSMerger:
    def __init__(self, simple_call_graph, code_map,single_log_map):
        self.simple_call_graph = simple_call_graph
        self.code_map = code_map
        self.single_log_map = single_log_map
        self.processed = {}        
        self.stack = []
        self.in_stack = set()
        self.call_to_times = 0
        self.total_cost_token = 0
        
        self.merged_info = {}       
        self.merged_logs = ""

    def _is_leaf(self, node):
        return not bool(self.simple_call_graph.get(node))

    def _get_node_code(self, node):
        if node in self.code_map:
            return self.code_map[node]
        elif "access$" in node:
            return ""
        else:
            return ""

    def _process_leaf(self, node):
        code = self._get_node_code(node)
        if not code:
            print(f"[WARN] {node} no code")
            return
        
        log_seq = self.single_log_map.get(node,"")
        if not log_seq:
            print(f"[WARN] {node} no single node cfg")

        log_seq = address_log_seq(log_seq)
        print(f"{node}-------log_seq----- leaf  -----{log_seq}")
        
        self.merged_info[node] = log_seq
        address_log = address_log_seq(log_seq)
        self.single_log_map[node] = address_log
   
    def _merge_parent(self, node):
        parent_code = self._get_node_code(node)
        if not parent_code:
            print(f"[WARN] {node} no code")
            parent_code = ""
        parent_log = self.single_log_map.get(node,"")
        if not parent_log:
            print(f"[WARN] {node} no log analysis")
            parent_log = ""

        parent_log = address_log_seq(parent_log)
        print(f"{node}-------log_seq------parent -----{parent_log}")

        self.merged_info[node]=parent_log
        address_log = address_log_seq(parent_log)
        self.single_log_map[node]=address_log
        
        for child in self.simple_call_graph[node]:
            child_code = self._get_node_code(child)
            if not child_code:
             
                continue
                
            child_log = self.single_log_map.get(child,"")
            # if not child_log:
            #     continue
            
            child_log = address_log_seq(child_log)
            print(f"{child}-------log_seq----- child  ----{child_log}")
            
            parent_info = "node name is "+node+"node log is"+str(parent_log)+"souce code:"+ str(parent_code)
            child_info ="node name is"+child+ "node log is"+str(child_log)+"source code:"+str(child_code)


             ## call llm
            self.call_to_times = self.call_to_times + 1
            prompts = list(get_merge_nodes_by_llm_v4(parent_info,child_info))
            merged = get_response(prompts)
            ## calculate token
            self.total_cost_token +=  count_string_tokens(prompts[0]) + count_string_tokens(merged)

            self.merged_info[node]=merged
            addressed_merged = address_log_seq(merged)
            self.single_log_map[node] = addressed_merged
            print("--------merged info is ---------------------")
            print(addressed_merged)
            self.merged_logs = addressed_merged
            print(f"[MERGE] {node}merged {child} ")
            parent_log = addressed_merged

    def _get_pending_children(self, node):
        return [n for n in self.simple_call_graph.get(node, []) 
                if not self.processed.get(n)]

    def push(self, node):
        if node not in self.processed and node not in self.in_stack:
            self.stack.append(node)
            self.in_stack.add(node)
            # print(f"[DEBUG] Adding {node} to stack")
            logger.debug(f"Adding {node} to stack")

    def pop(self):
        """出栈操作"""
        if self.stack:
            node = self.stack.pop()
            self.in_stack.remove(node)
            # print(f"[DEBUG] Popping {node} from stack")
            logger.debug(f"Popping {node} from stack")
            return node
        return None


    def merge(self, entry_points):
        #set is not reverible
        entry_points = list(entry_points)
        for node in entry_points:
            self.push(node)

        while self.stack:
            current = self.stack[-1]
           
            if self.processed.get(current, False):
                self.pop()
                continue
            
           
            pending = self._get_pending_children(current)
            
            if not pending:  
                if self._is_leaf(current):
                    self._process_leaf(current)
                else:
                    self._merge_parent(current)
                
             
                self.processed[current] = True
                self.stack.pop()
                
            else:   
                new_nodes = [n for n in reversed(pending) 
                            if n not in self.in_stack]
                
                if new_nodes: 
                    for n in new_nodes: 
                        self.push(n)

                else: 
                    logger.warning(f"cycle,force {current}")
                    if self._is_leaf(current):
                        self._process_leaf(current)
                    else:
                        self._merge_parent(current)
                    self.processed[current] = True
                    self.pop()

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

def parse_call_file(filename):
    call_graph_with_depth = {}
    all_callees = set()
    line_count = 0  
    valid_line_count = 0  
    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            line_count += 1
            original_line = line
            line = line.strip()
            if not line:
                logger.debug(f"The {line_count} line is empty,skip it.")
                continue
            parts = line.split("->")
            if len(parts) != 2:
                continue  
            caller = parts[0].strip()
            rest = parts[1].strip()
            if not caller or not rest:
                logger.debug(f"The {line_count} line, callee or caller is empty,skip it.")
                continue 
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

            if not callee:
                logger.debug(f"The {line_count} line, callee is empty,skip it.")
                continue

            if caller not in call_graph_with_depth:
                call_graph_with_depth[caller] = []
            call_graph_with_depth[caller].append((callee, depth))
            all_callees.add(callee)
            valid_line_count += 1 
    logger.info(f" parse call_chain_file,total line is {line_count},valid line is {valid_line_count},call_graph_with_depth size is {len(call_graph_with_depth)}")
    if len(call_graph_with_depth) == 0:
        logger.error(f"Warning:call_graph_with_depth is empty,please check call_chain_file format is empty or error.")
    
    return call_graph_with_depth, all_callees

def build_simple_call_graph(call_graph_with_depth):
   
    simple_call_graph = {}
    for caller, callees in call_graph_with_depth.items():
        simple_call_graph[caller] = [callee for callee, _ in callees]
    return simple_call_graph


def test():
    call_file = "output/hadoop/MRAppMaster_main/pruned_call_deps.txt"
    call_graph_with_depth, all_callees = parse_call_file(call_file)
    simple_call_graph = build_simple_call_graph(call_graph_with_depth)
    
    all_callers = set(simple_call_graph.keys())
    roots = all_callers - all_callees
    if not roots:
        print("have no root,auto set")
        roots = {list(simple_call_graph.keys())[0]}

    code_map =  load_json("output/hadoop/MRAppMaster_main/extracted_methods.json")
    single_log_map = load_json("output/hadoop/MRAppMaster_main/single_call_path_javaparser.json")
    
    merger = StackDFSMerger(simple_call_graph, code_map,single_log_map)
    merger.merge(roots)
    
    single_log_seq_json = merger.merged_info
    single_log_info_json = merger.single_log_map
    merged_logs = merger.merged_logs
    
    single_log_info = "output/hadoop/MRAppMaster_main/merge_single_info.json"
    with open(single_log_info, "w", encoding="utf-8") as f:
        json.dump(single_log_info_json, f, indent=2, ensure_ascii=False)

    single_log_seq = "output/hadoop/MRAppMaster_main/merge_single_log.json"
    with open(single_log_seq, "w", encoding="utf-8") as f:
        json.dump(single_log_seq_json, f, indent=2, ensure_ascii=False)
    print(merged_logs)

def main():

    parser = argparse.ArgumentParser(description = "finishd sub graph code mapping")
    parser.add_argument('--call_chain_file', type=str, required=True,help="sub graph file")
    parser.add_argument('--source_mapping', type=str, required=True,help="source_code mapping file path")
    parser.add_argument('--single_call_path', type=str, required=True,help="single log generation mapping file path")
    parser.add_argument('--output_dir', type=str, required=True,help="output dir of mapping json")
    
    args = parser.parse_args()

    call_file = args.call_chain_file
    source_mapping = args.source_mapping
    output_dir = args.output_dir
    single_call_path = args.single_call_path

    call_graph_with_depth, all_callees = parse_call_file(call_file)
    simple_call_graph = build_simple_call_graph(call_graph_with_depth)

    if not simple_call_graph:
        logger.error(f"simple_call_graph is empty, no more root.")
        return
    
    all_callers = set(simple_call_graph.keys())
    roots = all_callers - all_callees
    if not roots:
        print("have no root,auto set")
        roots = {list(simple_call_graph.keys())[0]}
        
    code_map =  load_json(source_mapping)
    # print(source_mapping)
    single_log_map = load_json(single_call_path)
    if single_log_map is None:
        print(f"load {single_call_path} failed")
        return
    
    # no provide any call path analysis
    for entry in single_log_map:
        single_log_map[entry] = ""

    merger = StackDFSMerger(simple_call_graph, code_map,single_log_map)
    merger.merge(roots)
    
    single_log_seq_json = merger.merged_info
    single_log_info_json = merger.single_log_map
    merged_logs = merger.merged_logs

    print(f"all call times {merger.call_to_times}")
    print(f"all cost token is {merger.total_cost_token}")

    with open(os.path.join(output_dir,"ablation_v1_call_times.txt"), "w+", encoding="utf-8") as f:
        f.write(f"the entry function is {roots}\n")
        f.write(f"all call times {merger.call_to_times}\n")
        f.write(f"all cost token is {merger.total_cost_token}\n")

    single_log_info =os.path.join(output_dir,"merge_single_info_without_static_analysis.json")
    with open(single_log_info, "w", encoding="utf-8") as f:
        json.dump(single_log_info_json, f, indent=2, ensure_ascii=False)

    # single log seq
    single_log_seq = os.path.join(output_dir,"merge_single_log_without_static_analysis.json")
    with open(single_log_seq, "w", encoding="utf-8") as f:
        json.dump(single_log_seq_json, f, indent=2, ensure_ascii=False)
    print(merged_logs)
    print(f"merge all")

if __name__ == "__main__":
    main()
    # test()