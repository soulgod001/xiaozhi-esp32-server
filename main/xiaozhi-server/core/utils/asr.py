import importlib
import logging
import os
import sys
import time
import wave
import uuid
from abc import ABC, abstractmethod
from typing import Optional, Tuple, List
from core.providers.asr.base import ASRProviderBase
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

def create_instance(class_name: str, *args, **kwargs) -> ASRProviderBase:
    """工厂方法创建ASR实例。

    解析顺序：
      1) 插件注册的自定义 provider（plugins.register.provider_registry['asr']）
      2) 内置的 core.providers.asr.{class_name}
    """
    # ---- 步骤1: 优先从插件注册表中查找 ----
    try:
        from plugins.register import provider_registry
        if class_name in provider_registry.get("asr", {}):
            cls = provider_registry["asr"][class_name]
            logger.bind(tag=TAG).info(f"使用插件提供的ASR实现: {class_name} -> {cls.__name__}")
            return cls(*args, **kwargs)
    except Exception as e:
        logger.bind(tag=TAG).warning(f"从插件注册表加载ASR {class_name} 失败，回退内置实现: {e}")

    # ---- 步骤2: 原有内置路径加载 ----
    if os.path.exists(os.path.join('core', 'providers', 'asr', f'{class_name}.py')):
        lib_name = f'core.providers.asr.{class_name}'
        if lib_name not in sys.modules:
            sys.modules[lib_name] = importlib.import_module(f'{lib_name}')
        return sys.modules[lib_name].ASRProvider(*args, **kwargs)

    raise ValueError(f"不支持的ASR类型: {class_name}，请检查该配置的type是否设置正确")