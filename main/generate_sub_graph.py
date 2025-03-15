import mysql.connector
import configparser
import logging
import os
import json
import hashlib

logging.basicConfig(filename="callgraph_code.log", level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


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

def load_signature_file(signature_file='signatures.json'):
    with open(signature_file, 'r') as file:
        data = json.load(file)
        return data  # 返回签名列表

def fetch_all_call_relationships(cursor):
  
    query = """
    SELECT caller, callee 
    FROM method_call 
    WHERE enabled = 1 AND log_propagation = 1
    """
    cursor.execute(query)
    
  
    callee_to_callers = {}

    for row in cursor.fetchall():
        caller = row["caller"]
        callee = row["callee"]

        if caller not in caller_to_callees:
            caller_to_callees[caller] = set()
        caller_to_callees[caller].add(callee)

        if callee not in callee_to_callers:
            callee_to_callers[callee] = set()
        callee_to_callers[callee].add(caller)
    
    return caller_to_callees, callee_to_callers

def construct_simple_call_graph(caller_to_callees, signatures, max_depth):
 
    call_graph = {}

    for signature in signatures:
        current_level = set([signature])
        traced_nodes = set()
        graph = {}

        for depth in range(max_depth):
            next_level = set()

            for node in current_level:
                if node not in traced_nodes:
                    traced_nodes.add(node)
                  
                    if node in caller_to_callees:
                        callees = caller_to_callees[node]
                        graph[node] = list(callees)
                        next_level.update(callees)

            current_level = next_level

        call_graph[signature] = graph
    
    return call_graph

def save_call_graph(call_graph, output_dir):
    
    os.makedirs(output_dir, exist_ok=True)

    for signature, graph in call_graph.items():
    
        hashed_signature = hashlib.sha256(signature.encode()).hexdigest()[:8]
        with open(os.path.join(output_dir, f"{hashed_signature}_callpath.txt"), 'w') as f:
            for caller, callees in graph.items():
                for callee in callees:
                    f.write(f"{caller}->{callee}\n")

def process_call_graph(output_dir="output", signature_file='signatures.json', depth=4):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
 
    db_config = load_db_config()
    cnx = mysql.connector.connect(**db_config)
    cursor = cnx.cursor(dictionary=True)
    
   
    signatures = load_signature_file(signature_file)
    
 
    caller_to_callees, callee_to_callers = fetch_all_call_relationships(cursor)
    

    call_graph = construct_simple_call_graph(caller_to_callees, signatures, max_depth=depth)
    
    save_call_graph(call_graph, output_dir)

    print(f"Processed call graph for {len(signatures)} signatures.")
    cursor.close()
    cnx.close()
    logging.info(f"Call graph processing completed. Call graphs saved to {output_dir}")


def main():
    process_call_graph(output_dir="output/subgraph", signature_file='output/depth_3_calls.json', depth=4)

if __name__ == "__main__":
    main()
