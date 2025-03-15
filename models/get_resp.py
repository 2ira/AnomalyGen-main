from models.model_factory import ModelFactory
import logging
import os
import json
import tiktoken

def get_model(logger_name):
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(logger_name)
    config_file='models/config/config.json'
    config_file=config_file.replace('/',os.path.sep)
    with open(config_file, "r",encoding="utf-8") as f:
        config = json.load(f)
    factory = ModelFactory(config=config, logger=logger)
    backend = "openai"
    model=None
    model = factory.create_model(backend)
    if model:
        print("getting the model")
    return model

def get_response(prompts, encoding=None):
    model = get_model("default")
    if encoding is None:
        try:
            encoding = tiktoken.encoding_for_model(model.name)
        except KeyError:
            logging.warning(f"Could not find tokenizer for model {model.name}. Using cl100k_base as fallback.")
            encoding = tiktoken.get_encoding("cl100k_base")
    response = model.codegen(prompts)
    reply = response[0]["response"]
    return reply
