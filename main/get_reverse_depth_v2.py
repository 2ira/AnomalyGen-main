import mysql.connector
import configparser
import logging
import os
import json
import re
import argparse

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

def load_signature_file(signature_file='signatures.txt'):
   
    with open(signature_file, 'r') as file:
        return [line.strip() for line in file.readlines()]

def fetch_all_call_relationships(cursor):

    query = """
    SELECT caller, callee 
    FROM method_call 
    WHERE enabled = 1 AND log_propagation = 1
    """
    cursor.execute(query)
    
    caller_to_callees = {}
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


def trace_calls_upwards(caller_to_callees, callee_to_callers, signatures, max_depth, output_dir):
    traced_signatures = set()
    to_process = set(signatures) 
    current_level = set()
    for depth_level in range(max_depth):
        current_level = set()

        for signature in to_process:
            if signature not in traced_signatures:
                traced_signatures.add(signature)
                if signature in callee_to_callers:
                    callers = callee_to_callers[signature]
                    current_level.update(callers)
                if current_level:
            with open(os.path.join(output_dir, f"depth_{depth_level + 1}_calls.json"), 'w') as f:
                json.dump(list(current_level), f, indent=4)

        to_process = current_level
    
    return traced_signatures

def process_call_graph(output_dir="output", signature_file='signatures.txt', depth=3):
    db_config = load_db_config()
    cnx = mysql.connector.connect(**db_config)
    cursor = cnx.cursor(dictionary=True)
    
    signatures = load_signature_file(signature_file)
    
    caller_to_callees, callee_to_callers = fetch_all_call_relationships(cursor)
    
    traced_signatures= trace_calls_upwards(caller_to_callees, callee_to_callers, signatures, max_depth=depth, output_dir=output_dir)
    
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "traced_signatures.json"), 'w') as f:
        json.dump(list(traced_signatures), f, indent=4)

    print(f"Total traced signatures: {len(traced_signatures)}")
    cursor.close()
    cnx.close()
    logging.info(f"Call graph processing completed. Traced signatures saved to {output_dir}")

def main():
    process_call_graph(output_dir="output", signature_file='filtered_functions_with_logs.txt', depth=3)

if __name__ == "__main__":
    main()
