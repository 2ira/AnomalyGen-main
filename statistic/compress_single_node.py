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

# 配置日志记录
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
    如果 xml_data 中包含 <enhanced_paths>，则提取出该部分内容，
    否则返回空字符串。
    """
    if "<enhanced_paths>" in xml_data:
        pattern = r'(<enhanced_paths>.*?</enhanced_paths>)'
        match = re.search(pattern, xml_data, re.DOTALL)
        if match:
            return match.group(1)
    return xml_data


def load_json(source_file='output/enhanced_single_cfg/merged_enhanced_cfg.json'):
    """加载签名对应的源码JSON文件"""
    with open(source_file, 'r') as file:
        return json.load(file)

def load_filtered_signatures(signature_file='filtered_single_nodes.txt'):
    """加载筛选后的签名文件（txt格式，每行一个签名）"""
    with open(signature_file, 'r') as file:
        return [line.strip() for line in file.readlines()]

def clean_text(text):
    """
    清理文本：
      - 如果存在 markdown 包裹（例如以 ``` 开始和结束），去掉这些标记；
      - 将所有连续的空白字符替换为单个空格，并去掉首尾空白；
      - 反转义 HTML 转义字符（如有需要）。
    """
    text = text.strip()
    
    # 处理以 ```xml 或 ``` 开始和结束的情况
    if text.startswith("```xml"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```xml"):
            lines = lines[1:]
        if lines and lines[-1] == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    
    # 处理以 ``` 开始的其他情况
    elif text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1] == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    
    # 替换多个空白为一个空格
    cleaned = re.sub(r"\s+", " ", text).strip()
    
    # 反转义 HTML 字符
    cleaned = html.unescape(cleaned)
    
    return cleaned

def extract_from_content(content):
    """
    从传入的文本中提取所有 <exec_flow> 与 <log_sequence> 标签内的内容，
    返回一个列表，每个元素为一个字典，包含 exec_flow 与 log 键。
    """
    exec_flows = re.findall(r"<exec_flow>(.*?)</exec_flow>", content, flags=re.DOTALL)
    log_seqs = re.findall(r"<log_seq>(.*?)</log_seq>", content, flags=re.DOTALL)
    
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


def compress_log(output_file = "output/log_events/compressed_logs_v2.json"):
    os.makedirs("output/log_events",exist_ok=True)
    signature = load_filtered_signatures()
    node_map = load_json("output/enhanced_single_cfg/merged_enhanced_cfg.json")

    if os.path.exists(output_file):
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                prev_data = json.load(f)
        except json.JSONDecodeError:
            logger.warning("输出文件格式错误，重新创建新的文件。")
            prev_data = {}
    else:
        prev_data = {}

    for sig in signature:
        if sig in node_map:
            key = hashlib.sha256(sig.encode()).hexdigest()[:8]
            # 如果该前缀已处理（例如存在 "{prefix}_1"），则跳过该前缀
            if f"{key}_1" in prev_data:
                logger.info(f"前缀 {key} 已处理，跳过。")
                continue
            origin_info = node_map[sig]
            info = extract_enhanced_paths(origin_info)
            prompt = get_log_simulate_v2(info)
            reply = get_response(prompt)
            content = clean_text(reply)
            pairs = extract_from_content(content)
            logger.info("获取压缩日志结果:")
            logger.info(pairs)
            
            # 将处理后的结果加入 prev_data 字典中
            for i, pair in enumerate(pairs, start=1):
                prev_data[f"{key}_{i}"] = pair

            # 每次处理完一个前缀后，写入更新后的结果到输出文件
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(prev_data, f, indent=2, ensure_ascii=False)
                f.write("\n")
    return prev_data

def main():
    # 提取日志
    compressed_data = compress_log()
    
    print("日志处理并保存成功。")

if __name__ == '__main__':
    main()
