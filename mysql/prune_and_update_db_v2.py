#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import mysql.connector
import configparser
import logging
import threading
import queue
import json
import os
import time
import argparse

logging.basicConfig(filename="prune_and_update.log",
                    level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")

CHECKPOINT_FILE = "bfs_checkpoint.json"
CHECKPOINT_INTERVAL = 1000 
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

def ensure_log_propagation_column():
    db_config = load_db_config()
    cnx = mysql.connector.connect(**db_config)
    cursor = cnx.cursor()
    
    cursor.execute("SHOW COLUMNS FROM method_call LIKE 'log_propagation'")
    result = cursor.fetchone()
    
    if not result:
        cursor.execute("ALTER TABLE method_call ADD COLUMN log_propagation TINYINT DEFAULT 0")
        cnx.commit()
    
    cursor.close()
    cnx.close()

def load_call_graph():
    db_config = load_db_config()
    cnx = mysql.connector.connect(**db_config)
    cursor = cnx.cursor(dictionary=True)
    cursor.execute("SELECT caller, callee FROM method_call WHERE enabled = 1")
    
    forward_graph = {}
    reverse_graph = {}
    nodes = set()
    
    for row in cursor:
        caller = row["caller"]
        callee = row["callee"]
        nodes.add(caller)
        nodes.add(callee)
        forward_graph.setdefault(caller, set()).add(callee)
        reverse_graph.setdefault(callee, set()).add(caller)
    
    cursor.close()
    cnx.close()
    return forward_graph, reverse_graph, nodes


def load_logging_keywords(config_file='mysql/config.ini'):
    config = configparser.ConfigParser()
    config.read(config_file)
    keywords = config.get('logging', 'keywords', fallback='org.slf4j.Logger, LoggerFactory, getLogger')
    return [kw.strip() for kw in keywords.split(',')] if keywords else []


#
def is_logging_method(method):
    logging_keywords = load_logging_keywords()  #   
    return any(kw in method for kw in logging_keywords)


edge_queue = queue.Queue()

def db_update_worker(db_config, edge_queue, stop_event, batch_size=1000):
    cnx = mysql.connector.connect(**db_config)
    cursor = cnx.cursor()
    batch = []
    while not stop_event.is_set() or not edge_queue.empty():
        try:
            edge = edge_queue.get(timeout=1)
            batch.append(edge)
            edge_queue.task_done()
        except queue.Empty:
            pass
        if len(batch) >= batch_size:
            for caller, callee in batch:
                cursor.execute(
                    "UPDATE method_call SET log_propagation = 1 WHERE caller = %s AND callee = %s",
                    (caller, callee)
                )
            cnx.commit()
            batch = []
    if batch:
        for caller, callee in batch:
            cursor.execute(
                "UPDATE method_call SET log_propagation = 1 WHERE caller = %s AND callee = %s",
                (caller, callee)
            )
        cnx.commit()
    cursor.close()
    cnx.close()

def checkpoint_progress(marked, bfs_queue):
    checkpoint = {
        "marked": list(marked),
        "bfs_queue": list(bfs_queue.queue)
    }
    try:
        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f)
        logging.info(f"Checkpoint sucess{len(marked)}, length{bfs_queue.qsize()}")
    except Exception as e:
        logging.error(f"write  to checkpoint failed: {e}")

def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                checkpoint = json.load(f)
            marked = set(checkpoint.get("marked", []))
            bfs_list = checkpoint.get("bfs_queue", [])
            bfs_q = queue.Queue()
            for node in bfs_list:
                bfs_q.put(node)
            return marked, bfs_q
        except Exception as e:
    return None, None

def bfs_worker(bfs_queue, marked, marked_lock, reverse_graph, edge_queue, checkpoint_counter, counter_lock):
   
    while True:
        try:
            current = bfs_queue.get(timeout=3)
        except queue.Empty:
            break
        for pred in reverse_graph.get(current, set()):
            with marked_lock:
                if pred not in marked:
                    marked.add(pred)
                    bfs_queue.put(pred)
            edge_queue.put((pred, current))
        with counter_lock:
            checkpoint_counter[0] += 1
            if checkpoint_counter[0] % CHECKPOINT_INTERVAL == 0:
                checkpoint_progress(marked, bfs_queue)
        bfs_queue.task_done()

def multi_threaded_bfs_update(forward_graph, reverse_graph, nodes, db_config, start_nodes, num_workers=8):
  
    marked_lock = threading.Lock()
    counter_lock = threading.Lock()
    checkpoint_counter = [0]  
    
    marked, bfs_queue = load_checkpoint()
    if marked is None or bfs_queue is None:
        marked = set(start_nodes)
        bfs_queue = queue.Queue()
        for node in start_nodes:
            bfs_queue.put(node)
    
    stop_event = threading.Event()
    db_thread = threading.Thread(target=db_update_worker, args=(db_config, edge_queue, stop_event))
    db_thread.start()
    
    workers = []
    for _ in range(num_workers):
        t = threading.Thread(target=bfs_worker, args=(bfs_queue, marked, marked_lock, reverse_graph, edge_queue, checkpoint_counter, counter_lock))
        t.start()
        workers.append(t)
    
    bfs_queue.join()
    for t in workers:
        t.join()
    
    stop_event.set()
    db_thread.join()
    
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
    
    return marked

def update_method_call_table(marked):
    db_config = load_db_config()
    cnx = mysql.connector.connect(**db_config)
    cursor = cnx.cursor()
    
    if not marked:
        cursor.close()
        cnx.close()
        return
    
    marked_list = list(marked)
    placeholders = ','.join(['%s'] * len(marked_list))
    query = f"""
        UPDATE method_call
        SET log_propagation = 1
        WHERE caller IN ({placeholders})
          AND callee IN ({placeholders})
    """
    params = marked_list + marked_list
    cursor.execute(query, params)
    cnx.commit()
    cursor.close()
    cnx.close()
    logging.info("method_call refresh log_propagation")

def save_start_nodes(marked, reverse_graph,output_file="output/start_node.txt"):
  
    start_nodes = [node for node in marked if node not in reverse_graph or len(reverse_graph[node]) == 0]
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            for node in start_nodes:
                f.write(node + "\n")
    except Exception as e:
        logging.error(f"err writging: {e}")


def main():
    parser = argparse.ArgumentParser(description="prune")
    parser.add_argument('--output_file', type=str, required=False,default = "output/start_node.txt", help="输出目录路径")
    args = parser.parse_args()

    start_output_file = args.output_file

    ensure_log_propagation_column()  
    db_config = load_db_config()
    forward_graph, reverse_graph, nodes = load_call_graph()
    logging.info(f"load graph,num {len(nodes)}")
    
    start_nodes = [node for node in nodes if is_logging_method(node)]
    logging.info(f"start node: {len(start_nodes)}")
    
    marked_nodes = multi_threaded_bfs_update(forward_graph, reverse_graph, nodes, db_config, start_nodes)
    logging.info(f"BFS end,node: {len(marked_nodes)}")
    
    update_method_call_table(marked_nodes)
    logging.info("refresh dataset")
    
    save_start_nodes(marked_nodes, reverse_graph,start_output_file)
    logging.info("save start node")

if __name__ == "__main__":
    main()
    
