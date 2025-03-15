#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import mysql.connector
import configparser
import logging
import argparse
import os
import re

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_db_config(config_file='mysql/config.ini'):

    config = configparser.ConfigParser()
    config.read(config_file)
    return {
        'host': config.get('mysql', 'host'),
        'port': config.getint('mysql', 'port'),
        'user': config.get('mysql', 'user'),
        'password': config.get('mysql', 'password'),
        'database': config.get('mysql', 'database'),
        'charset': 'utf8mb4'
    }

def fetch_callees_from_db(cursor, caller):
   
    query = """
    SELECT callee FROM method_call 
    WHERE caller = %s AND enabled = 1 AND log_propagation = 1 
    ORDER BY call_seq;
    """
    # query = """
    # SELECT callee FROM method_call 
    # WHERE caller = %s AND enabled = 1
    # ORDER BY call_seq;
    # """
    cursor.execute(query, (caller,))
    return [row["callee"] for row in cursor.fetchall()]

def test_calldep(caller):
    # 连接数据库
    db_config = load_db_config()
    cnx = mysql.connector.connect(**db_config)
    cursor = cnx.cursor(dictionary=True)
    callee = fetch_callees_from_db(cursor,caller)
    print(callee)
    cursor.close()
    cnx.close()

def test_call(caller):
    generate_call_sequences_from_entry(entry_function=caller,max_depth=2)

def generate_call_sequences_from_entry(entry_function, output_file="output/call_deps.txt", max_depth=10):

    db_config = load_db_config()
    cnx = mysql.connector.connect(**db_config)
    cursor = cnx.cursor(dictionary=True)

    stack = [(entry_function, 0)] 
    visited = set() 
    in_stack = set()  
    logging.info(f"Starting traversal from entry function: {entry_function}")

  
    with open(output_file, "w", encoding="utf-8") as f:
        while stack:
            current, depth = stack[-1]  
            stack.pop()  

        
            if depth >= max_depth:
                logging.info(f"Skipping {current} due to depth limit reached ({depth})")
                continue  

            
            if current in in_stack:
                logging.info(f"Skipping {current} due to loop detected")
                continue
        
            visited.add(current)
            in_stack.add(current)
        
            callees = fetch_callees_from_db(cursor, current)

        
            for callee in callees:
                f.write(f"{current}->{callee}, depth {depth + 1}\n") 
                logging.info(f"Writing edge: {current}->{callee}, depth {depth + 1}")

                
                if callee not in visited:
                    stack.append((callee, depth + 1))

            in_stack.remove(current)

    cursor.close()
    cnx.close()
    logging.info(f"Call sequences have been stored in file: {output_file}")



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

def is_log_node(node_signature):
 
    lower_signature = node_sign_signature = node_signature.split('(')[0].lower()  
    log_keywords = {
        'log', 'logger', 'logging', 
        'debug', 'info', 'warn', 'error',  
        'trace', 'fatal'  
    }
    return any(kw in lower_signature for kw in log_keywords)

def build_reverse_graph(simple_call_graph):
  
    reverse_graph = {}
    for caller, callees in simple_call_graph.items():
        for callee in callees:
            if callee not in reverse_graph:
                reverse_graph[callee] = []
            reverse_graph[callee].append(caller)
    return reverse_graph

def find_relevant_nodes(simple_call_graph):
   
    all_nodes = set(simple_call_graph.keys())
    for callees in simple_call_graph.values():
        all_nodes.update(callees)
    
   
    log_leaves = {node for node in all_nodes if is_log_node(node)}
    
   
    reverse_graph = build_reverse_graph(simple_call_graph)
    
    relevant_nodes = set(log_leaves)
    queue = list(log_leaves)
    
    while queue:
        current = queue.pop(0)
        for caller in reverse_graph.get(current, []):
            if caller not in relevant_nodes:
                relevant_nodes.add(caller)
                queue.append(caller)
    
    return relevant_nodes


def prune_call_graph(original_graph, relevant_nodes, output_path):
    """严格剪枝：仅保留两端节点都在relevant_nodes中的边"""
    pruned_edges = []
    
    valid_callers = [caller for caller in original_graph.keys() 
                    if caller in relevant_nodes]
    
    for caller in valid_callers:
        valid_callees = [
            (callee, depth) 
            for callee, depth in original_graph[caller]
            if callee in relevant_nodes
        ]
        
        if valid_callees:
            pruned_edges.append((caller, valid_callees))
        with open(output_path, 'w', encoding='utf-8') as f:
        for caller, callees in pruned_edges:
            for callee, depth in callees:
                line = f"{caller}->{callee}"
                if depth is not None:
                    line += f", depth {depth}"
                f.write(line + '\n')
    
    validate_pruned_graph(pruned_edges, relevant_nodes)
    return pruned_edges

def validate_pruned_graph(pruned_edges, relevant_nodes):
    for caller, callees in pruned_edges:
        assert caller in relevant_nodes, f"illegal parent node: {caller}"
        for callee, _ in callees:
            assert callee in relevant_nodes, f"illegal child node {callee}->{callee}"


def generate_and_prune_call_sequences(entry_function, output_dir="output", max_depth=3):
  
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    call_dep_file = os.path.join(output_dir, "call_deps.txt")
    pruned_file = os.path.join(output_dir, "pruned_call_deps.txt")

    generate_call_sequences_from_entry(entry_function, call_dep_file, max_depth)

    call_graph_with_depth, all_callees = parse_call_file(call_dep_file)
    simple_call_graph = build_simple_call_graph(call_graph_with_depth)

    relevant_nodes = find_relevant_nodes(simple_call_graph)

    prune_call_graph(call_graph_with_depth, relevant_nodes, pruned_file)
    logging.info("Call graph pruning complete. Pruned call graph stored in %s", pruned_file)


def test():
    entry_function = "org.apache.hadoop.mapreduce.v2.app.rm.RMContainerAllocator$1:run()"
    # entry_functions = ["","",]
    generate_and_prune_call_sequences(entry_function)

def main():
    parser = argparse.ArgumentParser(description = "完成从入口函数的剪枝")
    parser.add_argument('--output_dir', type=str, required=False,default="output",help="输出目录路径")
    parser.add_argument('--depth', type=int, required=False,default=10,help="限制分析深度")
    parser.add_argument('--entry_function', type=str, required=True,help="设定入口函数")
    args = parser.parse_args()
    
    output_dir = args.output_dir
    depth = args.depth
    entry_function = args.entry_function

    generate_and_prune_call_sequences(entry_function,output_dir,depth)

if __name__ == "__main__":
    main()
   
