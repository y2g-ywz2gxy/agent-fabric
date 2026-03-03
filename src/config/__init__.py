# -*- coding: utf-8 -*-
"""
配置模块

提供模型配置的加载和管理功能。
"""
from config.model_config import ModelConfig, load_model_config
from config.runtime_config import RuntimeConfig, load_runtime_config

__all__ = ["ModelConfig", "RuntimeConfig", "load_model_config", "load_runtime_config"]
