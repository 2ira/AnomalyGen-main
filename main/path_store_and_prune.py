import os
import sys
import argparse
import time
import configparser
import re
import mysql.connector
import logging
from collections import deque

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

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



def ensure_table_and_column(db_config):
    """make sure table and column all exist"""
    try:
        cnx = mysql.connector.connect(**db_config)
        cursor = cnx.cursor()
        # check and create table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS `method_call` (
              `id` int NOT NULL AUTO_INCREMENT,
              `call_seq` int DEFAULT NULL,
              `enabled` tinyint DEFAULT NULL,
              `caller` text,
              `callee` text,
              `call_line_no` int DEFAULT NULL,
              `call_return_type` text,
              `log_propagation` tinyint DEFAULT '0',
              PRIMARY KEY (`id`),
              INDEX `caller_idx` (`caller`(255)),
              INDEX `callee_idx` (`callee`(255))
            ) ENGINE=InnoDB;
        """)

        cursor.execute("SHOW COLUMNS FROM method_call LIKE 'log_propagation'")
        if not cursor.fetchone():
            logging.info("con 'log_propagation' not existing,adding...")
            cursor.execute("ALTER TABLE method_call ADD COLUMN log_propagation TINYINT DEFAULT 0")
            logging.info("列 'log_propagation' add finished!")
    
        logging.info("Clearing method_call Table...")
        cursor.execute("TRUNCATE TABLE method_call")
        cnx.commit()
        cursor.close()
        cnx.close()
        logging.info("Database prepared successfully.")
    except mysql.connector.Error as err:
        logging.error(f"Database prepared failed: {err}")
        sys.exit(1)

def load_logging_keywords(config_file='mysql/config.ini'):
    """ load log keys from log_key_words  """
    config = configparser.ConfigParser()
    config.read(config_file)
    keywords = config.get('logging', 'keywords', fallback='org.slf4j.Logger, LoggerFactory, getLogger')
    return [kw.strip() for kw in keywords.split(',')] if keywords else []


def save_start_nodes(marked, reverse_graph,output_file="output/start_node.txt"):

    start_nodes = [node for node in marked if node not in reverse_graph or len(reverse_graph[node]) == 0]
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            for node in start_nodes:
                f.write(node + "\n")
        logging.info(f"in 0 node is {output_file},number is  {len(start_nodes)}")
    except Exception as e:
        logging.error(f"write to 0 egde is failed: {e}")


## change: load config from file to memory instead of connect to db multiple times
def load_graph_from_file(input_file):
    """
    input: method_call.txt 
    return 
        - forward_graph: indirect {caller: {callee1, callee2}}
        - reverse_graph: redirect {callee: {caller1, caller2}}
        - nodes: the set of all nodes
        - all_rows: list of all rows for later bulk insert
    """
    logging.info(f"Starting from {input_file} loading graph to memory...")
    forward_graph = {}
    reverse_graph = {}
    nodes = set()
    all_rows = []

    with open(input_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            
            cols = line.strip().split("\t")
            if len(cols) < 6:
                continue

            caller = cols[2]
            callee = process_callee(cols[3])

            # store row data
            row_data = (
                get_int(cols[0]),
                get_int(cols[1]),
                caller,
                callee,
                get_int(cols[4]),
                cols[5]
            )
            all_rows.append(row_data)

            # if enabled=1，add it to graph
            if get_int(cols[1]) == 1:
                nodes.add(caller)
                nodes.add(callee)
                forward_graph.setdefault(caller, set()).add(callee)
                reverse_graph.setdefault(callee, set()).add(caller)

    logging.info(f"Load graph finished.Nodes: {len(nodes)}, the number of relations: {len(all_rows)}")
    return forward_graph, reverse_graph, nodes, all_rows

def run_bfs_in_memory(reverse_graph, start_nodes):
    """
    In memory, we use BFS to mark the reachable nodes from start_nodes.
    """
    logging.info(f"Go run BFS in memory,the numben of start node: {len(start_nodes)}")
    marked = set(start_nodes)
    queue = deque(start_nodes)
    
    processed_count = 0
    while queue:
        current = queue.popleft()
        processed_count += 1
        if processed_count % 50000 == 0:
            logging.info(f"BFS already addressed {processed_count} nodes...")

        for predecessor in reverse_graph.get(current, set()):
            if predecessor not in marked:
                marked.add(predecessor)
                queue.append(predecessor)
    
    logging.info(f"BFS Fininsed.All mark{len(marked)} nodes")
    return marked


def bulk_insert_to_db(db_config, all_rows, marked_nodes):
    """
    use executemany batch insert into database
    """
    logging.info("Preparing data and insert it...")
    data_to_insert = []
    for row in all_rows:
        caller = row[2]
        log_propagation = 1 if caller in marked_nodes else 0
        final_row = row + (log_propagation,)
        data_to_insert.append(final_row)

    if not data_to_insert:
        logging.info("No data to insert.")
        return

    try:
        cnx = mysql.connector.connect(**db_config)
        cursor = cnx.cursor()
        
        insert_sql = (
            "INSERT INTO method_call "
            "(call_seq, enabled, caller, callee, call_line_no, call_return_type, log_propagation) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)"
        )
        
        # make sure batch size is not too large
        batch_size = 50000
        total_inserted = 0
        
        logging.info(f"All {len(data_to_insert)} records to insert, and each batch {batch_size}.")

        for i in range(0, len(data_to_insert), batch_size):
            batch = data_to_insert[i:i + batch_size]
            cursor.executemany(insert_sql, batch)
            cnx.commit() 
            total_inserted += len(batch)
            logging.info(f"Successfully insert {total_inserted} / {len(data_to_insert)} records...")
        
        logging.info(f"All records inserted successfully. Total: {total_inserted}")
        
        cursor.close()
        cnx.close()
    except mysql.connector.Error as err:
        logging.error(f"Error when inserting to database {err}")




def main():
    parser = argparse.ArgumentParser(description="Address Java Call graph and prune it using BFS in memory")
    parser.add_argument('--project_dir', type=str, required=True, help="input project dir")
    parser.add_argument('--input_dir', type=str, required=True, help="javacallgraph output dir(including  method_call.txt)")
    parser.add_argument('--config_file', type=str, default='mysql/config.ini', help="data db config file")
    args = parser.parse_args()

    start_time = time.time()
    
    repo_name = os.path.basename(args.project_dir.rstrip('/'))
    output_dir = f"output/{repo_name}"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    method_call_file = os.path.join(args.input_dir, 'method_call.txt')
    if not os.path.exists(method_call_file):
        logging.error(f"Input file not exist : {method_call_file} ")
        sys.exit(1)

    # 1. load config and logging keywords
    db_config = load_db_config(args.config_file)
    logging_keywords = load_logging_keywords(args.config_file)
    
    # 2. prepare db table and column
    ensure_table_and_column(db_config)

    # 3. load to memory
    forward_graph, reverse_graph, nodes, all_rows = load_graph_from_file(method_call_file)

    # 4. get bfs start nodes
    start_bfs_nodes = [node for node in nodes if any(kw in node for kw in logging_keywords)]
    
    # 5. prune using bfs in memory
    marked_nodes = run_bfs_in_memory(reverse_graph, start_bfs_nodes)
    
    # 6. save to db
    bulk_insert_to_db(db_config, all_rows, marked_nodes)
    
    # 7. save the start nodes to file
    start_nodes_output_file = os.path.join(output_dir, 'start_nodes.txt')
    save_start_nodes(marked_nodes, reverse_graph, start_nodes_output_file)

    end_time = time.time()
    logging.info(f"All task finished! All use time: {end_time - start_time:.2f} seconds")

if __name__ == "__main__":
    main()
