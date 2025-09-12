# decoder.py
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
import tiktoken
import time
from openai import OpenAI, APIError  # import OpenAI client and special type

class DecoderBase(ABC):
    def __init__(self, name: str, logger, temperature: float, max_tokens: int):
        # rm batch_size
        self.name = name
        self.logger = logger
        self.temperature = temperature
        self.max_tokens = max_tokens

    @abstractmethod
    def codegen(self, message: str, num_samples: int = 1) -> List[Dict]:
        pass

    @abstractmethod
    def is_direct_completion(self) -> bool:
        pass

    def __repr__(self):
        return self.name

# 将 OpenAIChatDecoder 重命名为 APIChatDecoder，因为它更通用
class APIChatDecoder(DecoderBase):
    # 1. **更新 __init__ 方法**
    # 接收一个 OpenAI 客户端实例，而不是一堆配置参数
    def __init__(self, client: OpenAI, name: str, logger, temperature: float, max_tokens: int):
        # 调用父类的构造函数
        super().__init__(name=name, logger=logger, temperature=temperature, max_tokens=max_tokens)
        self.client = client  # 存储客户端实例

    def get_tokenizer(self, model_name):
        try:
            return tiktoken.encoding_for_model(model_name)
        except KeyError:
            self.logger.warning(f"Could not find tokenizer for model {model_name}. Using cl100k_base as fallback.")
            return tiktoken.get_encoding("cl100k_base")

    def codegen(self, message: str, num_samples: int = 1) -> List[Dict]:
        # 内部辅助函数保持不变，因为它们不依赖于 API 版本
        def num_tokens_from_string(string: str, encoding) -> int:
            num_tokens = len(encoding.encode(string))
            return num_tokens

        def slice_message(message: str, max_tokens: int, encoding) -> List[str]:
            if not isinstance(message, str):
                message = str(message)
            tokens = encoding.encode(message)
            slices = []
            start = 0
            while start < len(tokens):
                end = min(start + max_tokens, len(tokens))
                slices.append(encoding.decode(tokens[start:end]))
                start = end
            return slices

        # 2. **更新 `compress_memory` 中的 API 调用**
        def compress_memory(memory: str, encoding):
            summary_config = {
                "model": self.name,
                "messages": [
                    {"role": "user", "content": f"Please give a summary of below info, notice the question to be solved and the before reply: {memory}"},
                ],
                "temperature": 0,
                "max_tokens": 12000
            }
            try:
                # 使用 self.client 进行调用，并解析新版 Pydantic 模型对象
                summary_response = self.client.chat.completions.create(**summary_config)
                return summary_response.choices[0].message.content
            except APIError as e:
                self.logger.error(f"OpenAI API error during memory compression: {e}")
                return memory # 压缩失败时返回原始记忆

        encoding = self.get_tokenizer(self.name)
        max_message_tokens = self.max_tokens - 50
        temp_max_prompt_tokens = 8000 
        # message_slices = slice_message(message, max_message_tokens, encoding)
        self.logger.info(f"Original message length (tokens): {len(encoding.encode(message))}")
        self.logger.info(f"Max prompt tokens for slicing: {temp_max_prompt_tokens}")
        message_slices = slice_message(message, temp_max_prompt_tokens, encoding)
        # +++ 添加日志 +++
        self.logger.info(f"Message has been sliced into {len(message_slices)} part(s).")

        all_responses = [{"response": "", "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}} for _ in
                         range(num_samples)]
        memory = ""

        # 3. **简化主循环，移除手动重试**
        for i, slice_msg in enumerate(message_slices):
            # +++ 添加日志 +++
            self.logger.info(f"--- Processing slice {i+1}/{len(message_slices)} ---")
            self.logger.info(f"Memory size (tokens) before check: {num_tokens_from_string(memory, encoding)}")
            self.logger.info(f"Slice size (tokens): {num_tokens_from_string(slice_msg, encoding)}")
            
            if num_tokens_from_string(memory, encoding) + num_tokens_from_string(slice_msg, encoding) > max_message_tokens:
                # +++ 添加日志 +++
                self.logger.warning("Token limit exceeded, compressing memory...")
                memory = compress_memory(memory, encoding)
                # +++ 添加日志 +++
                self.logger.warning(f"Memory after compression: {memory[:200]}...") # 只打印前200个字符

            current_message = memory + slice_msg if memory else slice_msg

            # +++ 添加日志 +++
            self.logger.info(f"Final `current_message` being sent to API (first 200 chars): {current_message[:200]}...")

            config = {
                "model": self.name,
                "messages": [{"role": "user", "content": current_message}],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "n": num_samples,
            }

            try:
                response = self.client.chat.completions.create(**config)
                
                self.logger.info("*************** origin response *************")
                self.logger.info(response) # 使用 logger 打印，避免污染 stdout

                # 5. **使用新的响应对象结构**
                # 响应不再是字典，而是 Pydantic 模型对象，通过属性访问
                for choice in response.choices:
                    index = choice.index
                    content = choice.message.content or "" # 确保 content 不为 None
                    all_responses[index]["response"] += content
                
                # `usage` 对象现在是响应的顶级属性
                if response.usage:
                    for resp_item in all_responses:
                        resp_item["usage"]["prompt_tokens"] += response.usage.prompt_tokens
                        resp_item["usage"]["completion_tokens"] += response.usage.completion_tokens
                        resp_item["usage"]["total_tokens"] += response.usage.total_tokens

                # 更新记忆
                if i < len(message_slices) - 1 and response.choices:
                    # 使用第一个 choice 的回复来构建记忆
                    memory += slice_msg + (response.choices[0].message.content or "")

            except APIError as e:
                # 如果所有重试都失败了，库会抛出 APIError
                self.logger.error(f"OpenAI API error after all retries: {e}")
                self.logger.error(f"Request config that failed: {config}")
                return [] # 返回空列表表示失败

        return all_responses

    def is_direct_completion(self) -> bool:
        return False



# from abc import ABC, abstractmethod
# from typing import List, Dict
# import tiktoken
# import time
# import openai


# class DecoderBase(ABC):
#     def __init__(self, name: str, logger, batch_size: int, temperature: float, max_tokens: int):
#         self.name = name
#         self.logger = logger
#         self.batch_size = batch_size
#         self.temperature = temperature
#         self.max_tokens = max_tokens


#     @abstractmethod
#     def codegen(self, message: str, num_samples: int = 1) -> List[Dict]:
#         pass


#     @abstractmethod
#     def is_direct_completion(self) -> bool:
#         pass


#     def __repr__(self):
#         return self.name


# class OpenAIChatDecoder(DecoderBase):
#     def get_tokenizer(self, model_name):
#         try:
#             return tiktoken.encoding_for_model(model_name)
#         except KeyError:
#             self.logger.warning(f"Could not find tokenizer for model {model_name}. Using cl100k_base as fallback.")
#             return tiktoken.get_encoding("cl100k_base")

#     def codegen(self, message: str, num_samples: int = 1) -> List[Dict]:
#         # 计算字符串的 token 数量
#         def num_tokens_from_string(string: str, encoding) -> int:
#             num_tokens = len(encoding.encode(string))
#             return num_tokens


#         # 切片消息
#         def slice_message(message: str, max_tokens: int, encoding) -> List[str]:
#             # make sure message is str 
#             if not isinstance(message, str):
#                 message = str(message)

#             tokens = encoding.encode(message)
#             slices = []
#             start = 0
#             while start < len(tokens):
#                 end = min(start + max_tokens, len(tokens))
#                 slices.append(encoding.decode(tokens[start:end]))
#                 start = end
#             return slices


#         # 压缩记忆机制
#         def compress_memory(memory: str, encoding):
#             # 使用模型对记忆信息进行总结
#             summary_config = {
#                 "model": self.name,
#                 "messages": [
#                     {"role": "user", "content": f"Please give a summary of below info, notice the question to be solved and the before reply: {memory}"},
#                 ],
#                 "temperature": 0,  # 较低的温度以保证总结的确定性
#                 "max_tokens": 4000  # 可根据实际情况调整总结的最大 token 数
#             }
#             try:
#                 summary_response = openai.ChatCompletion.create(**summary_config)
#                 return summary_response["choices"][0]["message"]["content"]
#             except Exception as e:
#                 self.logger.error(f"OpenAI API error during memory compression: {str(e)}")
#                 return memory


#         # 获取 tokenizer
#         encoding = self.get_tokenizer(self.name)

#         # 计算剩余可用于消息的 token 数量
#         # 这里减去一些预留的 token 用于系统消息和 API 开销
#         max_message_tokens = self.max_tokens - 50  # 预留 50 个 token

#         # 切片消息
#         message_slices = slice_message(message, max_message_tokens, encoding)

#         all_responses = [{"response": "", "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}} for _ in
#                          range(num_samples)]
#         memory = ""  # 记忆机制，用于记录之前的交互信息


#         # 设置重试机制
#         max_retries = 10  # 最大重试次数
#         retry_delay = 5  # 每次重试的延迟（秒）

#         for i, slice_msg in enumerate(message_slices):
#             # 检查记忆信息是否过长，若过长则进行压缩
#             if num_tokens_from_string(memory, encoding) + num_tokens_from_string(slice_msg, encoding) > max_message_tokens:
#                 memory = compress_memory(memory, encoding)

#             current_message = memory + slice_msg if memory else slice_msg

#             config = {
#                 "model": self.name,
#                 "messages": [{"role": "user", "content": current_message}],
#                 "temperature": self.temperature,
#                 "max_tokens": self.max_tokens,
#                 "n": num_samples,
#             }

#             # 重试逻辑
#             for attempt in range(max_retries):
#                 try:
#                     response = openai.ChatCompletion.create(**config)
#                     print("*************** origin response *************")
#                     print(response)

#                     # 合并响应和使用情况
#                     for choice in response["choices"]:
#                         index = choice["index"]
#                         all_responses[index]["response"] += choice["message"]["content"]
#                         all_responses[index]["usage"]["prompt_tokens"] += response["usage"]["prompt_tokens"]
#                         all_responses[index]["usage"]["completion_tokens"] += response["usage"]["completion_tokens"]
#                         all_responses[index]["usage"]["total_tokens"] += response["usage"]["total_tokens"]

#                     # 更新记忆
#                     if i < len(message_slices) - 1:
#                         memory += slice_msg + choice["message"]["content"]

#                     break  # 成功响应时跳出重试循环

#                 except Exception as e:
#                     self.logger.error(f"OpenAI API error (attempt {attempt + 1}/{max_retries}): {str(e)}")
#                     if attempt == max_retries - 1:
#                         return []  # 如果已达到最大重试次数，返回空列表
#                     else:
#                         self.logger.info(f"Retrying in {retry_delay} seconds...")
#                         time.sleep(retry_delay)  # 等待一段时间再重试

#         return all_responses

#     def is_direct_completion(self) -> bool:
#         return False
