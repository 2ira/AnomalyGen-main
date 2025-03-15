#!/usr/bin/env python3
import os
import sys
import argparse

def collect_bytecode_directories(root_dir):
    
    bytecode_dirs = set()
    for dirpath, dirnames, filenames in os.walk(root_dir):
        if "target/test-classes" in dirpath:
            continue
        if any(filename.endswith('.class') for filename in filenames):
            dirpath = os.path.abspath(dirpath) 
            bytecode_dirs.add(dirpath)
    return sorted(bytecode_dirs)

def get_all_classes(output_file = "extract_classes.txt",input_dir="hadoop"):
    project_dir = input_dir

    if not os.path.isdir(project_dir):
        print("error{} ".format(project_dir))
        sys.exit(1)

    dirs = collect_bytecode_directories(project_dir)

    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            for directory in dirs:
                directory=directory+"/"
                f.write(directory + "\n")
        print(" {} :{}".format(len(dirs), output_file))
    except Exception as e:
        print("error", e)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description = "extract classes")
    parser.add_argument('--input_dir', type=str, required=True,help="project dir")
    parser.add_argument('--output_file', type=str, required=True,help="output file of extract_classes")

    args = parser.parse_args()

    input_dir = args.input_dir
    output_file = args.output_file

    get_all_classes(output_file,input_dir)

if __name__ == "__main__":
    main()
