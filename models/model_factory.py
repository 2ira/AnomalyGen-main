import logging
from models.decoder import OpenAIChatDecoder
import openai


class ModelFactory:
    def __init__(self, config: dict, logger=None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)

    def create_model(self, backend: str) -> OpenAIChatDecoder:
        if backend == "openai":
            api_config = self.config["openai"]
            openai.api_key = api_config["api_key"]
            openai.api_base = api_config["base_url"]
            return OpenAIChatDecoder(
                name=api_config["default_model"],
                logger=self.logger,
                batch_size=api_config["batch_size"],
                temperature=api_config["temperature"],
                max_tokens=api_config["max_tokens"],
            )
        else:
            raise ValueError(f"Unsupported backend: {backend}")