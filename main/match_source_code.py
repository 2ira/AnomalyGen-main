import mysql.connector
import configparser
import logging
import json
import os
import re

logging.basicConfig(filename="process_method_line_3.log", level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

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

def fetch_method_line_number(cursor, method_signature):
    query = """
    SELECT start_line, end_line FROM method_line_number
    WHERE method_signature = %s
    """
    #print(f"Querying for method signature: '{method_signature}'")
    cursor.execute(query, (method_signature,))
    result = cursor.fetchall()
    if result:
        start_line = result[0]['start_line']
        end_line = result[0]['end_line']
        print(f"Found line numbers for '{method_signature}': start={start_line}, end={end_line}")
        return start_line, end_line
    print(f"No line numbers found for '{method_signature}'")
    return None, None

def locate_source_code(caller_method, start_line, end_line, project_dir):

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
            return None, None
        
        if start_line is None or end_line is None:
            return found_path,None
        
        print(f"Found Java file: {found_path}")
        with open(found_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            if start_line > len(lines):
                return found_path, f"Start line {start_line} exceeds total lines in the file"
            if end_line > len(lines):
                end_line = len(lines)

            source_lines = lines[start_line - 1:end_line]
            source_code = "".join(source_lines).strip()

            if source_code:
                return found_path, source_code
            else:
                return found_path,None
    
    except Exception as e:
        logging.error(f"Error locating source code for {caller_method}: {e}")
        return None, None

def process_log_file(input_file, project_dir, output_file="method_source_info_3.json",missing_line_info_file="missing_method_source_info_3.json"):
   
    result_dict = {}
    method_signatures = set()
    missing_dict = {}

   
    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
           
            match = re.match(r'(.+)->(.+), depth (\d+)', line.strip())
            if match:
                caller = match.group(1).strip()
                callee = match.group(2).strip()
                
                if caller.startswith("org.apache.hadoop") and callee.startswith("org.apache.hadoop"):
                    method_signatures.add(caller)
                    method_signatures.add(callee)
                    #print(f"Added method signatures: {caller}, {callee}")
            else:
                print(f"Failed to match line: {line.strip()}")

    #print(f"Unique method signatures found: {method_signatures}")
    db_config = load_db_config()
    cnx = mysql.connector.connect(**db_config)
    cursor = cnx.cursor(dictionary=True)

  
    for method_signature in method_signatures:
       
        start_line, end_line = fetch_method_line_number(cursor, method_signature)
        # if start_line is None or end_line is None:
        #     logging.warning(f"Method signature not found in method_line_number table: {method_signature}")
        #     continue
        
        file_path, source_code = locate_source_code(method_signature, start_line, end_line, project_dir)
        if source_code:
            result_dict[method_signature] = {
                'start_line': start_line,
                'end_line': end_line,
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

    cursor.close()
    cnx.close()
    logging.info(f"Method source code extraction completed and saved to {output_file}")

if __name__ == "__main__":
    input_file = "call_deps3.txt"  
    project_dir = "hadoop"  
    process_log_file(input_file, project_dir)
    logging.info("Processing complete.")
