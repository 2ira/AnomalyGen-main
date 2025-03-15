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

def fetch_callees_from_db(cursor, caller):
  
    query = """
    SELECT callee 
    FROM method_call 
    WHERE caller = %s AND enabled = 1 AND log_propagation = 1 
    ORDER BY call_seq;
    """
    cursor.execute(query, (caller,))
    return [row["callee"] for row in cursor.fetchall()]

def fetch_callers_from_db(cursor, callee):

    query = """
    SELECT caller 
    FROM method_call 
    WHERE callee = %s AND enabled = 1 AND log_propagation = 1 
    ORDER BY call_seq;
    """
    cursor.execute(query, (callee,))
    return [row["caller"] for row in cursor.fetchall()]


def trace_calls_upwards(cursor, signatures, max_depth):
    traced_signatures = set()
    to_process = set(signatures)
    current_level = set()
    
    while to_process and max_depth > 0:
        current_level = set()
        
        for signature in to_process:
            if signature not in traced_signatures:
                traced_signatures.add(signature)
                callers = fetch_callers_from_db(cursor, signature)
                current_level.update(callers)
        print(len(current_level))
        
        to_process = current_level
        max_depth -= 1 
    return traced_signatures,current_level

def process_call_graph(output_dir="output", signature_file='signatures.txt', depth=3):
    db_config = load_db_config()
    cnx = mysql.connector.connect(**db_config)
    cursor = cnx.cursor(dictionary=True)
    
    signatures = load_signature_file(signature_file)
    
    traced_signatures = trace_calls_upwards(cursor, signatures, max_depth=depth)
    
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "traced_signatures.json"), 'w') as f:
        json.dump(list(traced_signatures), f, indent=4)

    print(f"Total traced signatures: {len(traced_signatures)}")
    cursor.close()
    cnx.close()
    logging.info(f"Call graph processing completed. Traced signatures saved to {output_dir}")

def main():
    process_call_graph(output_dir="output", signature_file='functions_with_logs.txt', depth=3)

if __name__ == "__main__":
    main()