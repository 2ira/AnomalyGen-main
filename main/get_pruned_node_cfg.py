import os
import json
import re
import sys
import configparser
import logging
from py4j.java_gateway import JavaGateway
import argparse
from java_parser_client import analyze_java_code

def process_node_cfg(input_file, output_dir="output"):

    with open(input_file, 'r', encoding='utf-8') as f:
        extracted_methods = json.load(f)

    analysis_results = {}
    for signature, method_info in extracted_methods.items():
        java_code = method_info['source_code']
        control_flow = analyze_java_code(java_code)
        analysis_results[signature] = control_flow

    analysis_results_file = os.path.join(output_dir, "simple_cfg.json")
    with open(analysis_results_file, 'w', encoding='utf-8') as f:
        json.dump(analysis_results, f, indent=4, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description = "create each node cfg")
    parser.add_argument('--input_file', type=str, required=True,help="the source_code_file")
    # parser.add_argument('--output_dir', type=str, required=False,help="output dir of mapping json")
    
    args = parser.parse_args()
    input_file = args.input_file
    # output_dir = args.output_dir

    process_node_cfg(input_file)

if __name__ == "__main__":
    main()
