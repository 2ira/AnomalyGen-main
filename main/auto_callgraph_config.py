import os
import sys
import subprocess
import shutil
import argparse

##Stage1:get subgraph##
def extract_classes(project_dir, output_dir):
    print("generate extract classes...")
    subprocess.run(['python3', 'main/extract_classes.py', '--input_dir', project_dir, '--output_file', f'{output_dir}/collect_class.txt'])


def configure_java_callgraph2(output_dir):
    print("config java-callgraph2...")
    config_dir = "java-callgraph2/jar_output_dir/_javacg2_config"
    with open(f"{config_dir}/config.properties", "r") as file:
        config_data = file.readlines()

    new_config_data = []
    for line in config_data:
        if line.startswith("output.root.path"):
           
            output_dir = os.path.abspath(output_dir) # absolute path
            new_config_data.append(f"output.root.path={output_dir}\n")
        else:
            new_config_data.append(line)

    shutil.copy(f"{output_dir}/collect_class.txt", f"{config_dir}/jar_dir.properties")
    print("auto config java_callgraph2 file...")

def main():
    parser = argparse.ArgumentParser(description="auto analyse process")
    parser.add_argument('--project_dir', type=str, required=True, help="input project dir")
    args = parser.parse_args()

    project_dir = args.project_dir

    repo_name = os.path.basename(project_dir)
    output_dir = f"output/{repo_name}"

    # Create the main output directory
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    extract_classes(project_dir, output_dir)
    configure_java_callgraph2(output_dir)


if __name__ == "__main__":
    main()