import mysql.connector
import configparser
import logging
import os
import json
import hashlib
from models.prompts.analysis_code import get_java_parser_with_llm
from models.prompts.generate_node_info import generate_node_log_seq_v2
from models.get_resp import get_model
import re
import time
import tiktoken

model  = get_model("default_model")

def get_response(prompts, encoding=None):
    if encoding is None:
        try:
            encoding = tiktoken.encoding_for_model(model.name)
        except KeyError:
            logging.warning(f"Could not find tokenizer for model {model.name}. Using cl100k_base as fallback.")
            encoding = tiktoken.get_encoding("cl100k_base")
    response = model.codegen(prompts)
    reply = response[0]["response"]
    return reply

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

def load_filtered_signatures(signature_file='filtered_single_nodes.txt'):
    with open(signature_file, 'r') as file:
        return [line.strip() for line in file.readlines()]

def load_json(source_file='output/extracted_methods.json'):
    with open(source_file, 'r') as file:
        return json.load(file)

def get_callees(call_graph, signature):

    if signature in call_graph:
        return call_graph[signature]
    else:
        return []
    
def address_log_seq(message):
    xml_content = re.search(r'```xml(.*?)```', message, re.DOTALL)
    if xml_content:
        xml_data = xml_content.group(1).strip() 
        return xml_data
    else:
        return message
    
def get_single_node_log(info):
    prompts = generate_node_log_seq_v2(info)
    reply = get_response(prompts)
    reply = address_log_seq(reply)
    return reply

def process_single_node_analysis(output_dir="output", signature_file='filtered_single_nodes.txt', source_file='output/extracted_methods.json',simple_node_cfg='output/simple_cfg.json'):
    db_config = load_db_config()
    cnx = mysql.connector.connect(**db_config)
    cursor = cnx.cursor(dictionary=True)
    
    caller_to_callees, callee_to_callers = fetch_all_call_relationships(cursor)
    
    signatures = load_filtered_signatures(signature_file)
    
    code_map = load_json(source_file)

    simple_cfg = load_json(simple_node_cfg)
    
    os.makedirs(output_dir, exist_ok=True)

    checkpoint_file = os.path.join(output_dir, "enhanced_cfg_temp.json")
    processed_signatures = set()
    analysis_results = {}

    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, 'r') as f:
                checkpoint_data = json.load(f)
                processed_signatures = set(checkpoint_data.get('processed_signatures', []))
                analysis_results = checkpoint_data.get('analysis_results', {})
            logging.info(f"Resuming from checkpoint: {len(processed_signatures)} signatures processed")
        except json.JSONDecodeError:
            logging.error("Checkpoint file corrupted. Starting fresh.")
            os.remove(checkpoint_file)

    for signature in signatures:
        if signature in processed_signatures:
            continue  

        try:
            callees = get_callees(caller_to_callees, signature)
            cfg_info = simple_cfg.get(signature, "")
            source_code = code_map[signature]
            if len(source_code) > 0:
                callpaths = ""
                for child in callees:
                    callpaths = callpaths + signature + "->" + child + "\n"      
                info = f"signature: {signature}, source_code: {source_code}, all the callpath: {callpaths} , the origin cfg of this signature: {cfg_info}"
                node_log_seq = get_single_node_log(info)
                analysis_results[signature] = str(node_log_seq)
                processed_signatures.add(signature)

                if len(processed_signatures) % 10 == 0:
                    with open(checkpoint_file, 'w') as f:
                        json.dump({
                            "processed_signatures": list(processed_signatures),
                            "analysis_results": analysis_results
                        }, f, indent=4, ensure_ascii=False)
                    logging.info(f"Checkpoint saved after {len(processed_signatures)} signatures")

        except Exception as e:
            logging.error(f"Error processing {signature}: {str(e)}")
            continue

    analysis_results_file = os.path.join(output_dir, "enhanced_cfg.json")
    with open(analysis_results_file, 'w', encoding='utf-8') as f:
        json.dump(analysis_results, f, indent=4, ensure_ascii=False)

    if os.path.exists(checkpoint_file):
        os.remove(checkpoint_file)
        logging.info("Checkpoint file removed")

    print(f"Processed {len(signatures)} signatures for single node analysis.")
    cursor.close()
    cnx.close()
    logging.info(f"Single node analysis completed. Results saved to {output_dir}")


def main():
    process_single_node_analysis(output_dir="output/enhanced_single_cfg12", signature_file='f12.txt', source_file='output/extracted_methods.json',simple_node_cfg='output/simple_cfg.json')

if __name__ == "__main__":
    main()