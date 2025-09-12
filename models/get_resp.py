# get_resp.py
from models.model_factory import ModelFactory
import logging
import os
import json

# 都通过兼容 OpenAI 的 API 提供服务。
def get_response(prompts: list, encoding=None) -> str:
    """
    获取模型响应的核心函数。
    
    Args:
        prompts (list): 包含一个或多个 prompt 的列表。当前实现只使用第一个 prompt。
        encoding: (可选) tiktoken 编码器，当前未使用，但保留接口。
        
    Returns:
        str: 模型的回复内容。
    """
    # 1. **简化了模型获取和调用流程**
    # 创建模型工厂，并获取一个配置好的模型实例
    model = get_model("default")
    
    # check prompts list is not empty
    if not prompts:
        logging.error("Prompts list cannot be empty.")
        return "Error: Prompts list is empty."
        
    prompt_text = prompts[0]
    print("====================== DEBUG: PROMPT TO LLM ======================")
    logging.info(f"Sending prompt to model '{prompt_text}'...")
    print("==================================================================")
    response_list = model.codegen(prompt_text)
    
    if not response_list:
        logging.error(f"Failed to get a response from model '{model.name}'.")
        return f"Error: Failed to get a response from model '{model.name}' after multiple retries."
        
    reply = response_list[0].get("response", "Error: Empty response content.")
    
    return reply

def get_model(logger_name="default_logger"):
    # 使用更健壮的日志记录设置
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(logger_name)
    
    # 使用 os.path.join 保证跨平台兼容性
    config_file = os.path.join('models', 'config', 'config.json')
    
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.error(f"Configuration file not found at: {config_file}")
        raise
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from the configuration file: {config_file}")
        raise

    factory = ModelFactory(config=config, logger=logger)
    backend = "openai" # 目前只支持这个后端
    
    logger.info("Creating model instance...")
    model = factory.create_model(backend)
    
    if model:
        logger.info(f"Successfully created model: {model.name}")
    
    return model


# from models.model_factory import ModelFactory
# import logging
# import os
# import json
# import tiktoken
# import anthropic
# from anthropic import Anthropic
# import requests
# from requests.adapters import HTTPAdapter
# from urllib3.util.retry import Retry

# def get_model(logger_name):
#     logging.basicConfig(level=logging.INFO)
#     logger = logging.getLogger(logger_name)
#     config_file='models/config/config.json'
#     config_file=config_file.replace('/',os.path.sep)
#     with open(config_file, "r",encoding="utf-8") as f:
#         config = json.load(f)
#     factory = ModelFactory(config=config, logger=logger)
#     backend = "openai"
#     model=None
#     model = factory.create_model(backend)
#     if model:
#         print("getting the model")
#     return model

# def get_response(prompts, encoding=None):
#     model = get_model("default")
#     model_name = model.name if hasattr(model, 'name') else model.__class__.__name__
#     if model_name.startswith("claude"):
#         # 使用 OpenKey Cloud API 调用 Claude 模型
#         url = "https://openkey.cloud/v1/chat/completions"
#         headers = {
#             'Content-Type': 'application/json',
#             'Authorization': 'Bearer sk-F5nvXCAAkijuGkHv1eA093Bd8d2a48Ce9fB6Aa63A41dCf32'
#         }
        
#         # 构建消息列表
#         messages = [{"role": "user", "content": prompt} for prompt in prompts]
        
#         data = {
#             "model": model_name,
#             "messages": messages,
#             "temperature": 1,
#             "max_tokens": 16000,
#         }
        
#         # 配置重试机制
#         retry_strategy = Retry(
#             total=3,  # 最大重试次数
#             backoff_factor=2,  # 退避因子，每次重试等待时间加倍
#             status_forcelist=[429, 500, 502, 503, 504],  # 需要重试的HTTP状态码
#             allowed_methods=["POST"]  # 允许重试的HTTP方法
#         )
        
#         # 创建带有重试机制的会话
#         session = requests.Session()
#         adapter = HTTPAdapter(max_retries=retry_strategy)
#         session.mount("https://", adapter)
        
#         try:
#             # 发送请求，设置连接超时和读取超时
#             response = session.post(url, headers=headers, json=data, timeout=(10, 30))
#             response.raise_for_status()  # 检查请求是否成功
            
#             # 解析响应
#             response_data = response.json()
#             return response_data["choices"][0]["message"]["content"]
#         except requests.exceptions.ConnectTimeout as e:
#             logging.error(f"连接超时: {e}")
#             return f"连接超时: {e}"
#         except requests.exceptions.ReadTimeout as e:
#             logging.error(f"读取超时: {e}")
#             return f"读取超时: {e}"
#         except requests.exceptions.RequestException as e:
#             logging.error(f"API请求错误: {e}")
#             # 只有当响应已经成功接收时才尝试获取状态码和内容
#             if 'response' in locals() and response:
#                 logging.error(f"响应状态码: {response.status_code}")
#                 logging.error(f"响应内容: {response.text}")
#             return f"API请求错误: {e}"
#         except (KeyError, json.JSONDecodeError) as e:
#             logging.error(f"响应解析错误: {e}")
#             if 'response' in locals() and response:
#                 logging.error(f"原始响应: {response.text}")
#             return f"响应解析错误: {e}"
#     else:
#         # 处理 OpenAI 模型的情况
#         try:
#             import tiktoken
#             encoding = tiktoken.encoding_for_model(model_name)
#             tokens = encoding.encode(prompts[0])
#             print(f"OpenAI 模型的 token 数量: {len(tokens)}")
#         except KeyError:
#             print(f"找不到模型 {model_name} 的分词器，使用 cl100k_base 作为后备")
#             encoding = tiktoken.get_encoding("cl100k_base")
#     response = model.codegen(prompts)
#     reply = response[0]["response"]
#     return reply
