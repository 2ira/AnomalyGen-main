import mysql.connector
import configparser
import logging
import os
import json
from py4j.java_gateway import JavaGateway
import re
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
        logging.error("error java:%s", e)
        return None


def locate_source_code(signature,file_path):
    gateway = JavaGateway()

    fqcn, simple_class_name, method_name, param_signature = parse_method_signature(signature)
    
    method_code = get_java_method_code(gateway, file_path, simple_class_name, method_name, param_signature)
    
    if method_code is None or method_code.strip() == "":
        logging.warning("failed:%s", signature)
        return None
    else:
        logging.info("success:%s", signature)
        return method_code


def load_package(config_file='mysql/config.ini'):
    config = configparser.ConfigParser()
    config.read(config_file)
    keywords = config.get('package', 'name', fallback='org.apache.hadoop')
    return [kw.strip() for kw in keywords.split(',')] if keywords else []

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

def fetch_nodes_from_db(cursor):
  
    query = """
    SELECT caller, callee 
    FROM method_call 
    WHERE enabled = 1 AND log_propagation = 1;
    """
    cursor.execute(query)
    nodes_set = set()  
    for row in cursor.fetchall():
        nodes_set.add(row["caller"])
        nodes_set.add(row["callee"])
    return nodes_set

def fetch_callees_from_db(cursor, caller):
 
    query = """
    SELECT callee 
    FROM method_call 
    WHERE caller = %s AND enabled = 1 AND log_propagation = 1 
    ORDER BY call_seq;
    """
    cursor.execute(query, (caller,))
    return [row["callee"] for row in cursor.fetchall()]

def process_nodes_and_source_code(project_dir, output_dir="output"):
   
    db_config = load_db_config()
    cnx = mysql.connector.connect(**db_config)
    cursor = cnx.cursor(dictionary=True)

    nodes_set = fetch_nodes_from_db(cursor)
    nodes = set()
    package = load_package()
    for node in nodes_set:
        if package is not None:
            for pk_name in package:
                if node.startswith(pk_name):
                    nodes.add(node)
        else:
            nodes = nodes_set

    missing_methods = {}
    extracted_methods = {}
    for node in nodes:
        file_path = locate_source_code_file_path(node, project_dir)
        if file_path:
            source_code = locate_source_code(node, file_path)
            if source_code:
                extracted_methods[node] = {'source_code': source_code, 'file_path': file_path}
            else:
                missing_methods[node] = {"file_path": file_path}  
        else:
            missing_methods[node] = {"file_path": None} 
    
    cursor.close()
    cnx.close()

    #nodes_set_file = os.path.join(output_dir, "nodes_set.json")
    extracted_methods_file = os.path.join(output_dir, "extracted_methods.json")
    missing_methods_file = os.path.join(output_dir, "missing_methods.json")

    with open(extracted_methods_file, 'w', encoding='utf-8') as f:
        json.dump(extracted_methods, f, indent=4, ensure_ascii=False)

    with open(missing_methods_file, 'w', encoding='utf-8') as f:
        json.dump(missing_methods, f, indent=4, ensure_ascii=False)
    
    logging.info(f"Processing completed. Results saved to {output_dir}")


def main():
    parser = argparse.ArgumentParser(description = "finishd sub graph code mapping")
    parser.add_argument('--project_dir', type=str, required=True,help="the root dir of project dir")
    # parser.add_argument('--output_dir', type=str, required=False,help="output dir of mapping json")
    
    args = parser.parse_args()

    project_dir = args.project_dir
    # output_dir = args.output_dir

    process_nodes_and_source_code(project_dir)

if __name__ == "__main__":
    main()
