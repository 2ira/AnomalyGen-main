from abc import ABC, abstractmethod
from typing import List, Dict
import tiktoken
import time
import openai


class DecoderBase(ABC):
    def __init__(self, name: str, logger, batch_size: int, temperature: float, max_tokens: int):
        self.name = name
        self.logger = logger
        self.batch_size = batch_size
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


class OpenAIChatDecoder(DecoderBase):
    def get_tokenizer(self, model_name):
        try:
            return tiktoken.encoding_for_model(model_name)
        except KeyError:
            self.logger.warning(f"Could not find tokenizer for model {model_name}. Using cl100k_base as fallback.")
            return tiktoken.get_encoding("cl100k_base")

    def codegen(self, message: str, num_samples: int = 1) -> List[Dict]:
        # 计算字符串的 token 数量
        def num_tokens_from_string(string: str, encoding) -> int:
            num_tokens = len(encoding.encode(string))
            return num_tokens


        # 切片消息
        def slice_message(message: str, max_tokens: int, encoding) -> List[str]:
            tokens = encoding.encode(message)
            slices = []
            start = 0
            while start < len(tokens):
                end = min(start + max_tokens, len(tokens))
                slices.append(encoding.decode(tokens[start:end]))
                start = end
            return slices


        def compress_memory(memory: str, encoding):
            summary_config = {
                "model": self.name,
                "messages": [
                    {"role": "user", "content": f"Please give a summary of below info, notice the question to be solved and the before reply: {memory}"},
                ],
                "temperature": 0, 
                "max_tokens": 4000
            }
            try:
                summary_response = openai.ChatCompletion.create(**summary_config)
                return summary_response["choices"][0]["message"]["content"]
            except Exception as e:
                self.logger.error(f"OpenAI API error during memory compression: {str(e)}")
                return memory
        encoding = self.get_tokenizer(self.name)

        max_message_tokens = self.max_tokens - 50  
        message_slices = slice_message(message, max_message_tokens, encoding)

        all_responses = [{"response": "", "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}} for _ in
                         range(num_samples)]
        memory = ""  

        max_retries = 10 
        retry_delay = 5  

        for i, slice_msg in enumerate(message_slices):
            if num_tokens_from_string(memory, encoding) + num_tokens_from_string(slice_msg, encoding) > max_message_tokens:
                memory = compress_memory(memory, encoding)

            current_message = memory + slice_msg if memory else slice_msg

            config = {
                "model": self.name,
                "messages": [{"role": "user", "content": current_message}],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "n": num_samples,
            }

            for attempt in range(max_retries):
                try:
                    response = openai.ChatCompletion.create(**config)
                    print("*************** origin response *************")
                    print(response)

                    for choice in response["choices"]:
                        index = choice["index"]
                        all_responses[index]["response"] += choice["message"]["content"]
                        all_responses[index]["usage"]["prompt_tokens"] += response["usage"]["prompt_tokens"]
                        all_responses[index]["usage"]["completion_tokens"] += response["usage"]["completion_tokens"]
                        all_responses[index]["usage"]["total_tokens"] += response["usage"]["total_tokens"]

                    if i < len(message_slices) - 1:
                        memory += slice_msg + choice["message"]["content"]

                    break  

                except Exception as e:
                    self.logger.error(f"OpenAI API error (attempt {attempt + 1}/{max_retries}): {str(e)}")
                    if attempt == max_retries - 1:
                        return []  
                    else:
                        self.logger.info(f"Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)  

        return all_responses

    def is_direct_completion(self) -> bool:
        return False
