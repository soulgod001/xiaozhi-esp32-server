import os
import sys

# 添加项目根目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
sys.path.insert(0, project_root)

from config.logger import setup_logging
import importlib

logger = setup_logging()


def create_instance(class_name, *args, **kwargs):
    # 创建VLLM实例
    # ---- 步骤1: 优先从插件注册表中查找 ----
    try:
        from plugins.register import provider_registry
        if class_name in provider_registry.get("vllm", {}):
            cls = provider_registry["vllm"][class_name]
            logger.info(f"使用插件提供的VLLM实现: {class_name} -> {cls.__name__}")
            return cls(*args, **kwargs)
    except Exception as e:
        logger.warning(f"从插件注册表加载VLLM {class_name} 失败，回退内置实现: {e}")

    # ---- 步骤2: 原有内置路径加载 ----
    if os.path.exists(os.path.join("core", "providers", "vllm", f"{class_name}.py")):
        lib_name = f"core.providers.vllm.{class_name}"
        if lib_name not in sys.modules:
            sys.modules[lib_name] = importlib.import_module(f"{lib_name}")
        return sys.modules[lib_name].VLLMProvider(*args, **kwargs)

    raise ValueError(f"不支持的VLLM类型: {class_name}，请检查该配置的type是否设置正确")
