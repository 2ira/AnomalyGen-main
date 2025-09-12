import os
import sys
import subprocess
import shutil
import argparse
import time 
from pathlib import Path

# the script directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# project root dir
ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))


##Stage1:get subgraph##
def extract_classes(project_dir, output_dir):
    print("generate extract classes...")
    extract_script = os.path.join(SCRIPT_DIR, "extract_classes.py")
    # check if the script exists
    if not os.path.exists(extract_script):
        print(f"Error: file not exists - {extract_script}")
        sys.exit(1)
    
    try:
        result = subprocess.run(
            ['python3', extract_script, '--input_dir', project_dir, '--output_file', f'{output_dir}/collect_class.txt'],
            check=True,
            capture_output=True,
            text=True
        )
        print("Extracted classes successfully.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error when extracting classes: {e.stderr}")
        return False

   # subprocess.run(['python3', 'main/extract_classes.py', '--input_dir', project_dir, '--output_file', f'{output_dir}/collect_class.txt'])


def configure_java_callgraph2(output_dir):
    print("config java-callgraph2...")

    config_dir = os.path.join(ROOT_DIR, "java-callgraph2/jar_output_dir/_javacg2_config")
    config_file = os.path.join(config_dir, "config.properties")

    if not os.path.exists(config_dir):
        print(f"Error: config not exist - {config_dir}")
        sys.exit(1)
    
    with open(config_file, "r") as file:
        config_data = file.readlines()

    new_config_data = []
    output_root_set = False
    continue_when_error_set = False
    output_ext_set = False
    
    for line in config_data:
        if line.startswith("output.root.path"):
            output_path = os.path.abspath(output_dir)
            new_config_data.append(f"output.root.path={output_path}\n")
            output_root_set = True
        elif line.startswith("continue.when.error"):
            new_config_data.append("continue.when.error=true\n")
            continue_when_error_set = True
        elif line.startswith("output.file.ext"):
            new_config_data.append("output.file.ext=.txt\n")
            output_ext_set = True
        else:
            new_config_data.append(line)

    if not output_root_set:
        output_path = os.path.abspath(output_dir)
        new_config_data.append(f"\noutput.root.path={output_path}\n")
    if not continue_when_error_set:
        new_config_data.append("continue.when.error=true\n")
    if not output_ext_set:
        new_config_data.append("output.file.ext=.txt\n")
    
    with open(config_file, "w") as file:
        file.writelines(new_config_data)

    source_classes = os.path.join(output_dir, "collect_class.txt")
    dest_classes = os.path.join(config_dir, "jar_dir.properties")
    
    if os.path.exists(source_classes):
        shutil.copy(source_classes, dest_classes)
        print("classes file copied to jar_dir.properties")
    else:
        print(f"Erro: class file not exists- {source_classes}")
        sys.exit(1)
    
    print("java-callgraph2 finish configuration")
    return True

def run_callgraph_generator():
    print("Starting running global callgraph...")
    run_script_dir = os.path.join(ROOT_DIR, "java-callgraph2/jar_output_dir")
    run_script_path = os.path.join(run_script_dir, "run.sh")
    
    # check if the script exists
    if not os.path.exists(run_script_path):
        print(f"Error: run script not exists- {run_script_path}")
        sys.exit(1)

    if not os.access(run_script_path, os.X_OK):
        print(f"Fix: adding properity of {run_script_path}")
        os.chmod(run_script_path, 0o755) 
    
    with open(run_script_path, "r") as f:
        first_line = f.readline().strip()
    if not first_line.startswith("#!"):
        print(f"Fix: add {run_script_path} bash interpreter")
        # add #!/bin/bash at the top of the script
        with open(run_script_path, "r+") as f:
            content = f.read()
            f.seek(0, 0)
            f.write("#!/bin/bash\n" + content)
    
    try:
        # switch to the script directory
        print(f"Running: {run_script_path}[ Run script dir is: {run_script_dir}]")
        result = subprocess.run(
            [run_script_path],
            check=True,
            capture_output=True,
            text=True,
            cwd=run_script_dir,  
            shell=False
        )
    
        print("Call graph generation completed successfully.")
  
    except subprocess.CalledProcessError as e:
        print(f"Error when generating callgraph: {e.stderr}")
        return None


def main():
    parser = argparse.ArgumentParser(description="auto analyse process")
    parser.add_argument('--project_dir', type=str, required=True, help="input project dir")
    args = parser.parse_args()

    start_time = time.time()
    project_dir = args.project_dir

    repo_name = os.path.basename(project_dir)
    output_dir = f"output/{repo_name}"

    # Create the main output directory
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    extract_classes(project_dir, output_dir)
    configure_java_callgraph2(output_dir)
    run_callgraph_generator()

    end_time = time.time()

    print(f"Total time taken: {end_time - start_time:.2f} seconds")

if __name__ == "__main__":
    main()