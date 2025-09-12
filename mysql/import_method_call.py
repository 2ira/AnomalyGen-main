import mysql.connector
import configparser
import re
import argparse
import os

def load_db_config(config_file='mysql/config.ini'):
    config = configparser.ConfigParser()
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Config file {config_file} not found.")
    config.read(config_file)
    db_conf = {
        'host': config.get('mysql', 'host'),
        'port': config.getint('mysql', 'port'),
        'user': config.get('mysql', 'user'),
        'password': config.get('mysql', 'password'),
        'database': config.get('mysql', 'database'),
        'charset': 'utf8mb4'
    }
    return db_conf

def get_int(value):
    try:
        return int(value)
    except ValueError:
        return None

def process_callee(callee_field):
 
    return re.sub(r'^\([^)]+\)', '', callee_field)

def process_method_call_file(input_file="auth-javacg2_merged.jar-output_javacg2/method_call.txt"):
    db_config = load_db_config()
    try:
        cnx = mysql.connector.connect(**db_config)
        cursor = cnx.cursor()

        insert_sql = (
            "INSERT INTO method_call "
            "(call_seq, enabled, caller, callee, call_line_no, call_return_type) "
            "VALUES (%s, %s, %s, %s, %s, %s)"
        )

        with open(input_file, "r", encoding="utf-8") as f:
            for line in f:
                # 跳过空行
                if not line.strip():
                    continue

                cols = line.strip().split("\t")
                # 要求至少 6 列数据：call_seq, enabled, caller, callee, call_line_no, call_return_type
                if len(cols) < 6:
                    print("skip to line:", line)
                    continue
                
                raw_callee = cols[3]
                callee = process_callee(raw_callee)

                values = (
                    get_int(cols[0]),  
                    get_int(cols[1]),  
                    cols[2],           
                    callee,           
                    get_int(cols[4]),  
                    cols[5]            
                )
                try:
                    cursor.execute(insert_sql, values)
                except mysql.connector.Error as err:
                    print("insert error", err, "line", line)

        cnx.commit()
        cursor.close()
        cnx.close()
        print("success!")
    except mysql.connector.Error as err:
        print("error connecting ", err)

def main():
    parser = argparse.ArgumentParser(description="address call_info and restore to mysql")
    parser.add_argument('--input_file',type=str,required=False,default="auth-javacg2_merged.jar-output_javacg2/method_call.txt",help="write the file_path of javacallgraph2 method_call_info.txt")

    args = parser.parse_args()
    input_file = args.input_file
    
    process_method_call_file(input_file)

if __name__ == "__main__":
    main()
