
import re
import os
import json
import logging
import argparse
from models.prompts.merge_node_info import get_merge_nodes_by_llm_v7
from models.get_resp import get_response
import xml.etree.ElementTree as ET

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler("merge_log_output.log", encoding='utf-8'),
                        logging.StreamHandler()
                    ])
logger = logging.getLogger()

_JAVA_STRING = r'"(?:\\.|[^"\\])*"'
_JAVA_CONCAT = rf'{_JAVA_STRING}(?:\s*\+\s*{_JAVA_STRING})*'
_LOG_CALL = re.compile(
    r'(?:[A-Za-z_][\w\.]*\.)?(?:LOG|log|LOGGER|logger)\s*\.\s*'
    r'(trace|debug|info|warn|warning|error|fatal)\s*\(\s*(' + _JAVA_CONCAT + ')',
    re.I,
)
_LLM_FAIL = re.compile(
    r'(Failed to get a response|Error: Failed to get|Error: Empty response|Error: Prompts list)',
    re.I,
)


def extract_log_literals(source_code: str):
    """Pull SLF4J/Log4j format strings out of a Java method body."""
    if not source_code:
        return []
    out = []
    seen = set()
    for m in _LOG_CALL.finditer(source_code):
        level = m.group(1).upper()
        if level == "WARNING":
            level = "WARN"
        raw = m.group(2)
        parts = re.findall(_JAVA_STRING, raw)
        msg = "".join(_unescape_java_string(p[1:-1]) for p in parts)
        key = (level, msg)
        if msg and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _unescape_java_string(s: str) -> str:
    return (
        s.replace(r"\\", "\\")
        .replace(r"\"", '"')
        .replace(r"\n", "\n")
        .replace(r"\t", "\t")
    )


def llm_failed(text) -> bool:
    if text is None:
        return True
    s = str(text).strip()
    return (not s) or bool(_LLM_FAIL.search(s))


def source_log_xml(node: str, source_code: str) -> str:
    lits = extract_log_literals(source_code)
    if not lits:
        return ""
    lines = "\n".join(f"        [{node}][{lvl}] {msg}" for lvl, msg in lits)
    return (
        "```xml\n<merge_result>\n  <valid_paths>\n    <path>\n"
        "      <id>SRC</id>\n      <eval>true</eval>\n      <log_sequence>\n"
        f"{lines}\n"
        "      </log_sequence>\n    </path>\n  </valid_paths>\n</merge_result>\n```"
    )


def combine_with_source_logs(existing, source_xml: str):
    if llm_failed(existing):
        return source_xml or existing or ""
    if not source_xml:
        return existing
    return str(existing).rstrip() + "\n" + source_xml


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
    def __init__(self, simple_call_graph, code_map, single_log_map, no_llm=False):
        self.simple_call_graph = simple_call_graph or {}
        self.code_map = code_map or {}
        self.single_log_map = single_log_map or {}
        self.no_llm = no_llm
        self.processed = {}
        self.stack = []
        self.in_stack = set()
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

    def _source_text(self, node) -> str:
        code = self._get_node_code(node)
        if isinstance(code, dict):
            return code.get("source_code") or ""
        return str(code) if code else ""

    def _attach_source_logs(self, node, existing):
        xml = source_log_xml(node, self._source_text(node))
        return combine_with_source_logs(existing, xml)

    def _process_leaf(self, node):
        code = self._get_node_code(node)
        src = self._source_text(node)
        if not code and not src:
            print(f"[WARN] {node} no code")
            return

        log_seq = self.single_log_map.get(node, "")
        if log_seq:
            log_seq = address_log_seq(log_seq)
        combined = self._attach_source_logs(node, log_seq)
        if not combined:
            print(f"[WARN] {node} no log analysis")
            return
        print(f"{node}-------log_seq----- leaf  -----{combined[:500]}")
        self.merged_info[node] = combined
        self.single_log_map[node] = combined
        self.merged_logs = combined

    def _merge_parent(self, node):
        parent_code = self._get_node_code(node)
        if not parent_code:
            print(f"[WARN] {node} no code")
            parent_code = ""
        parent_log = self.single_log_map.get(node, "")
        if not parent_log:
            print(f"[WARN] {node} no log analysis")
            parent_log = ""

        parent_log = address_log_seq(parent_log) if parent_log else ""
        parent_log = self._attach_source_logs(node, parent_log)
        print(f"{node}-------log_seq------parent -----{str(parent_log)[:500]}")

        self.merged_info[node] = parent_log
        self.single_log_map[node] = parent_log

        for child in self.simple_call_graph.get(node, []):
            child_code = self._get_node_code(child)
            if not child_code:
                continue

            child_log = self.single_log_map.get(child, "")
            if not child_log:
                child_log = self._attach_source_logs(child, "")
            if not child_log:
                continue

            child_log = address_log_seq(child_log)
            child_log = self._attach_source_logs(child, child_log)
            print(f"{child}-------log_seq----- child  ----{str(child_log)[:500]}")

            if self.no_llm:
                parent_log = self._attach_source_logs(
                    node, str(parent_log) + "\n" + str(child_log)
                )
                self.merged_info[node] = parent_log
                self.single_log_map[node] = parent_log
                self.merged_logs = parent_log
                continue

            parent_info = "node name is "+node+"node log is"+str(parent_log)+"souce code:"+ str(parent_code)
            child_info ="node name is"+child+ "node log is"+str(child_log)+"source code:"+str(child_code)
            prompts = list(get_merge_nodes_by_llm_v7(parent_info,child_info))

            merged = get_response(prompts)
            if llm_failed(merged):
                logger.warning("LLM merge failed for %s + %s; keeping source logs", node, child)
                addressed_merged = self._attach_source_logs(
                    node, str(parent_log) + "\n" + str(child_log)
                )
            else:
                addressed_merged = self._attach_source_logs(node, address_log_seq(merged))
            self.merged_info[node] = addressed_merged
            self.single_log_map[node] = addressed_merged
            print("--------merged info is ---------------------")
            print(str(addressed_merged)[:500])
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
    if not filename or not os.path.exists(filename):
        return call_graph_with_depth, all_callees
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
    parser.add_argument('--no-llm', action='store_true',
                        help="Attach source log literals without calling the merge LLM")
    
    args = parser.parse_args()

    call_file = args.call_chain_file
    source_mapping = args.source_mapping
    output_dir = args.output_dir
    single_call_path = args.single_call_path

    call_graph_with_depth, all_callees = parse_call_file(call_file)
    simple_call_graph = build_simple_call_graph(call_graph_with_depth)
    code_map = load_json(source_mapping) or {}
    single_log_map = load_json(single_call_path)
    if single_log_map is None:
        print(f"load {single_call_path} failed")
        single_log_map = {}

    all_callers = set(simple_call_graph.keys())
    roots = all_callers - all_callees
    if not simple_call_graph and code_map:
        simple_call_graph = {sig: [] for sig in code_map}
        roots = set(code_map)
        print("empty call graph, treating extracted methods as leaves")
    elif not roots:
        print("have no root,auto set")
        if simple_call_graph:
            roots = {next(iter(simple_call_graph.keys()))}
        elif code_map:
            simple_call_graph = {sig: [] for sig in code_map}
            roots = set(code_map)
        else:
            print("empty graph and no extracted methods")
            os.makedirs(output_dir, exist_ok=True)
            with open(os.path.join(output_dir, "merge_single_info.json"), "w") as f:
                json.dump({}, f)
            with open(os.path.join(output_dir, "merge_single_log.json"), "w") as f:
                json.dump({}, f)
            return

    merger = StackDFSMerger(simple_call_graph, code_map, single_log_map, no_llm=args.no_llm)
    merger.merge(roots)
    
    single_log_seq_json = merger.merged_info
    single_log_info_json = merger.single_log_map
    merged_logs = merger.merged_logs

    single_log_info =os.path.join(output_dir,"merge_single_info.json")
    with open(single_log_info, "w", encoding="utf-8") as f:
        json.dump(single_log_info_json, f, indent=2, ensure_ascii=False)

    # single log seq
    single_log_seq = os.path.join(output_dir,"merge_single_log.json")
    with open(single_log_seq, "w", encoding="utf-8") as f:
        json.dump(single_log_seq_json, f, indent=2, ensure_ascii=False)
    print(merged_logs)
    print(f"merge all")

if __name__ == "__main__":
    main()
    # test()