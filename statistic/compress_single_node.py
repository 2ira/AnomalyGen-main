import os 
import json
import re
import html
import openai
import tiktoken 
import logging
from models.prompts.standard_log import get_log_simulate_v2
from models.get_resp import get_model
import xml.etree.ElementTree as ET
import hashlib
from utils import clean_text

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler("standardlize_single_log.log", encoding='utf-8'),
                        logging.StreamHandler()
                    ])
logger = logging.getLogger()

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


def extract_enhanced_paths(xml_data: str) -> str:
    """
    if xml_data including <enhanced_paths>
    """
    if "<enhanced_paths>" in xml_data:
        pattern = r'(<enhanced_paths>.*?</enhanced_paths>)'
        match = re.search(pattern, xml_data, re.DOTALL)
        if match:
            return match.group(1)
    return xml_data

def load_json(source_file='output/enhanced_single_cfg/merged_enhanced_cfg.json'):
    with open(source_file, 'r') as file:
        return json.load(file)

def load_filtered_signatures(signature_file='filtered_hdfs_single_nodes.txt'):
    ## candidata signature to address
    with open(signature_file, 'r') as file:
        return [line.strip() for line in file.readlines()]



def extract_from_content(content):
    """
    from all the text,  extract <exec_flow> 与 <log_sequence> 
    return a dict including 'exec_flow' and 'log' 
    """
    exec_flows = re.findall(r"<exec_flow>(.*?)</exec_flow>", content, flags=re.DOTALL)
    log_seqs = re.findall(r"<log_sequence>(.*?)</log_sequence>", content, flags=re.DOTALL)
    
    exec_flows = [clean_text(flow) for flow in exec_flows]
    log_seqs = [clean_text(seq) for seq in log_seqs]
    
    count = min(len(exec_flows), len(log_seqs))
    pairs = []
    for i in range(count):
        pairs.append({
            "exec_flow": exec_flows[i],
            "log": log_seqs[i]
        })
    return pairs


def compress_log(output_file = "output/log_events/compressed_logs_without_cot.json"):
    os.makedirs("output/log_events",exist_ok=True)
    signature = load_filtered_signatures()
    node_map = load_json("output/enhanced_single_cfg/merged_enhanced_cfg.json")

    if os.path.exists(output_file):
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                prev_data = json.load(f)
        except json.JSONDecodeError:
            logger.warning("Output file format error.")
            prev_data = {}
    else:
        prev_data = {}

    for sig in signature:
        if sig in node_map:
            key = hashlib.sha256(sig.encode()).hexdigest()[:8]
            # if prefix exists（if exiist "{prefix}_1"），skip it
            if f"{key}_1" in prev_data:
                logger.info(f"Already addressed {key}")
                continue
            
            ## there have something wrong, we should get compressed log from the each sigtures's output
            origin_info = node_map[sig]
            info = extract_enhanced_paths(origin_info)
            prompt = get_log_simulate_v2(info)
            reply = get_response(prompt)
            content = clean_text(reply)
            pairs = extract_from_content(content)
            logger.info("Get compressed data:")
            logger.info(pairs)
            
            # add logs to prev_data dict
            for i, pair in enumerate(pairs, start=1):
                prev_data[f"{key}_{i}"] = pair

            # After addressing a prefix and refresh the results
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(prev_data, f, indent=2, ensure_ascii=False)
                f.write("\n")
    return prev_data

def main():
    compressed_data = compress_log()
    
    print("Successfully Addressed all logs")

if __name__ == '__main__':
    main()
