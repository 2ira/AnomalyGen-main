import os
import sys
import subprocess
import shutil
import argparse
import time
import signal

def get_entry_name(entry):
 
    parts = entry.split(":", 1)
    fqcn = parts[0]
    method_with_params = parts[1]
    simple_class_name = ""

    if '$' in fqcn:
        simple_class_name = fqcn.split('$')[-1]
    else:
        simple_class_name = fqcn.split('.')[-1]

    method_name_end = method_with_params.find('(')
    method_name = method_with_params[:method_name_end]

    simple_entry_name = f"{simple_class_name}_{method_name}"
    return simple_entry_name



def create_output_dirs(project_dir, entry_functions):
    repo_name = os.path.basename(project_dir)
    output_dir = f"output/{repo_name}"

    # Create the main output directory
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Create subdirectories for each entry function
    entry_dirs = {}
    for entry in entry_functions:
        simple_entry_name = get_entry_name(entry)
        entry_dir = os.path.join(output_dir, simple_entry_name)
        if not os.path.exists(entry_dir):
            os.makedirs(entry_dir)
        entry_dirs[entry] = entry_dir

    return output_dir, entry_dirs


def store_method_calls_in_db(input_dir):
    print("store to database...")

    subprocess.run(['python3', 'mysql/import_method_call.py', '--input_file',f"{input_dir}/method_call.txt"])

def run_prune_and_update(output_dir):
    print("pruning...")
    subprocess.run(['python3', 'mysql/prune_and_update_db_v2.py', '--output_file', f'{output_dir}/start_nodes.txt'])

    

def main():
    parser = argparse.ArgumentParser(description="auto process")
    parser.add_argument('--input_dir',type=str,required=True,help="output dir of javacallgraph")
    args = parser.parse_args()


    input_dir = args.input_dir

    store_method_calls_in_db(input_dir)

    print("all the task done!")

if __name__ == "__main__":
    main()