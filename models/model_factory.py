# model_factory.py
import logging
from openai import OpenAI
from models.decoder import APIChatDecoder  # 我们将把 OpenAIChatDecoder 重命名为更通用的名字

class ModelFactory:
    def __init__(self, config: dict, logger=None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)

    def create_model(self, backend: str) -> APIChatDecoder:
        if backend == "openai":
            api_config = self.config["openai"]
            
            try:
                client = OpenAI(
                    api_key=api_config["api_key"],
                    base_url=api_config["base_url"],
                    max_retries=api_config.get("max_retries", 3),  # 从配置读取重试次数，默认为3
                    timeout= 40.0
                )
            except Exception as e:
                self.logger.error(f"Failed to create OpenAI client: {e}")
                raise ValueError(f"Invalid OpenAI configuration: {e}")

            return APIChatDecoder(
                client=client,
                name=api_config["default_model"],
                logger=self.logger,
                temperature=api_config["temperature"],
                max_tokens=api_config["max_tokens"],
            )
        else:
            # 这个逻辑保持不变，如果未来支持其他后端（如本地的 Transformers），可以在这里扩展。
            raise ValueError(f"Unsupported backend: {backend}")



# import logging
# from models.decoder import OpenAIChatDecoder
# import openai


# class ModelFactory:
#     def __init__(self, config: dict, logger=None):
#         self.config = config
#         self.logger = logger or logging.getLogger(__name__)

#     def create_model(self, backend: str) -> OpenAIChatDecoder:
#         if backend == "openai":
#             api_config = self.config["openai"]
#             openai.api_key = api_config["api_key"]
#             openai.api_base = api_config["base_url"]
#             return OpenAIChatDecoder(
#                 name=api_config["default_model"],
#                 logger=self.logger,
#                 batch_size=api_config["batch_size"],
#                 temperature=api_config["temperature"],
#                 max_tokens=api_config["max_tokens"],
#             )
#         else:
#             raise ValueError(f"Unsupported backend: {backend}")