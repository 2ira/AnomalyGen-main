import json
import html
import re

def clean_text(text):
    text = text.strip()

    if text.startswith("```xml"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```xml"):
            lines = lines[1:]
        if lines and lines[-1] == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    
    elif text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1] == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = html.unescape(cleaned)
    return cleaned

def extract_from_content_log_seq(content):
    """
    from all the text,  extract <exec_flow> 与 <log_sequence> 
    return a dict including 'exec_flow' and 'log' 
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

def extract_from_content_log_sequence(content):
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