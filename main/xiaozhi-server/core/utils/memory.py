import os
import sys
import importlib
from config.logger import setup_logging

logger = setup_logging()


def create_instance(class_name, *args, **kwargs):
    # ---- 步骤1: 优先从插件注册表中查找 ----
    try:
        from plugins.register import provider_registry
        if class_name in provider_registry.get("memory", {}):
            cls = provider_registry["memory"][class_name]
            logger.info(f"使用插件提供的Memory实现: {class_name} -> {cls.__name__}")
            return cls(*args, **kwargs)
    except Exception as e:
        logger.warning(f"从插件注册表加载Memory {class_name} 失败，回退内置实现: {e}")

    # ---- 步骤2: 原有内置路径加载 ----
    if os.path.exists(
        os.path.join("core", "providers", "memory", class_name, f"{class_name}.py")
    ):
        lib_name = f"core.providers.memory.{class_name}.{class_name}"
        if lib_name not in sys.modules:
            sys.modules[lib_name] = importlib.import_module(f"{lib_name}")
        return sys.modules[lib_name].MemoryProvider(*args, **kwargs)

    raise ValueError(f"不支持的记忆服务类型: {class_name}")
