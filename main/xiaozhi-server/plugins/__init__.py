"""
统一插件系统

该模块提供统一的插件扫描和注册机制，支持：
1. 动态拦截插件（BasePlugin子类）
2. MCP函数插件（@register_function装饰器）
3. 插件子目录结构（支持配置文件和辅助模块）
4. 外部插件目录（默认 data/plugins，独立于代码仓库，可被用户移除或修改）
"""

import os
import sys
import importlib
import importlib.util
from typing import Optional

# 简单的日志记录，避免依赖 loguru
class SimpleLogger:
    def __init__(self, tag):
        self.tag = tag

    def info(self, msg):
        print(f"[INFO] [{self.tag}] {msg}")

    def warning(self, msg):
        print(f"[WARNING] [{self.tag}] {msg}")

    def error(self, msg):
        print(f"[ERROR] [{self.tag}] {msg}")

    def bind(self, tag):
        return SimpleLogger(tag)

TAG = __name__
logger = SimpleLogger(TAG)

# 导出常用类和函数，方便插件开发
from .base import BasePlugin, PluginAction
from .register import register_function, ToolType, ActionResponse, Action, provider_registry
from .manager import PluginManager

__all__ = [
    "BasePlugin",
    "PluginAction",
    "register_function",
    "ToolType",
    "ActionResponse",
    "Action",
    "PluginManager",
    "provider_registry",
    "scan_plugins",
    "register_plugins_to_conn",
]


def _is_plugin_module(dirname: str) -> bool:
    """判断目录是否为插件模块"""
    # 跳过特殊目录
    if dirname.startswith("_") or dirname.startswith("."):
        return False
    # 跳过已知的非插件目录
    if dirname in ["__pycache__", "functions"]:
        return False
    return True


def _scan_plugin_directory(plugin_root: str, module_prefix: str) -> list:
    """
    扫描插件目录，返回所有需要导入的模块路径

    Args:
        plugin_root:   插件根目录路径（文件系统路径）
        module_prefix: 导入前缀，如 'plugins' 或 'external_plugins'

    Returns:
        模块路径列表，如 ['plugins.some_builtin_plugin', 'external_plugins.smart_home_plugin']
    """
    modules_to_import = []

    if not os.path.exists(plugin_root):
        return modules_to_import

    # 遍历插件根目录
    for item in os.listdir(plugin_root):
        item_path = os.path.join(plugin_root, item)

        # 只处理目录
        if not os.path.isdir(item_path):
            continue

        if not _is_plugin_module(item):
            continue

        # 检查目录中是否有 __init__.py
        init_file = os.path.join(item_path, "__init__.py")
        if os.path.exists(init_file):
            module_name = f"{module_prefix}.{item}"
            modules_to_import.append(module_name)

    return modules_to_import


def _import_module_safe(module_name: str) -> bool:
    """安全地导入模块"""
    try:
        importlib.import_module(module_name)
        logger.bind(tag=TAG).info(f"已加载插件模块: {module_name}")
        return True
    except Exception as e:
        logger.bind(tag=TAG).warning(f"加载插件模块 {module_name} 失败: {e}")
        return False


# ------------------ 外部插件目录支持 ------------------
# 虚拟包名：外部插件会以 external_plugins.<插件名> 的模块名被导入
EXTERNAL_PKG_NAME = "external_plugins"


def _ensure_external_package(external_root: str) -> bool:
    """确保 external_plugins 作为一个可导入的虚拟包存在。"""
    if not os.path.exists(external_root):
        return False
    # 若外部插件目录的父目录已在 sys.path 且包已注册，直接返回
    parent_dir = os.path.dirname(os.path.abspath(external_root))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    # 构造 external_plugins 这个虚拟包名：实际上 external_root 的父目录必须允许导入
    # 我们期望 data/plugins 目录被作为包名 external_plugins，
    # 所以在运行时以 importlib.util 方式构造虚拟 module
    external_abs = os.path.abspath(external_root)
    if EXTERNAL_PKG_NAME in sys.modules and hasattr(sys.modules[EXTERNAL_PKG_NAME], "__path__"):
        return True

    # 动态创建虚拟包 external_plugins，其 __path__ = external_root
    spec = importlib.util.spec_from_loader(
        EXTERNAL_PKG_NAME,
        loader=None,
        is_package=True,
    )
    if spec is None:
        logger.bind(tag=TAG).warning(f"无法创建虚拟包 {EXTERNAL_PKG_NAME}")
        return False
    mod = importlib.util.module_from_spec(spec)
    mod.__path__ = [external_abs]
    # 提供占位 __file__ 便于调试
    try:
        mod.__file__ = os.path.join(external_abs, "__init__.py")
    except Exception:
        pass
    sys.modules[EXTERNAL_PKG_NAME] = mod
    # 确保父目录在 sys.path，让 Python 能 resolve external_plugins.xxx
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    return True


def _default_external_plugins_dir() -> Optional[str]:
    """返回默认的外部插件目录：{project_root}/data/plugins
    project_root 定义为 plugins 目录往上两级（plugins -> xiaozhi-server -> main -> 往上是 xiaozhi-server 项目根）
    更稳妥：相对于 connection.py / 启动入口所在目录（即 main/xiaozhi-server）的 data/plugins。
    """
    # plugins/__init__.py 位于 {xiaozhi_server_root}/plugins/__init__.py
    plugins_root = os.path.dirname(os.path.abspath(__file__))
    xiaozhi_server_root = os.path.dirname(plugins_root)
    # 优先使用项目启动目录（工作目录）下的 data/plugins
    candidates = [
        os.path.join(os.getcwd(), "data", "plugins"),
        os.path.join(xiaozhi_server_root, "data", "plugins"),
    ]
    for p in candidates:
        # 只要路径存在或其上级 data 存在就算候选，我们返回第一个存在的；若都不存在，返回最后一个作为默认创建位置
        if os.path.exists(p):
            return p
    return candidates[-1]


def scan_plugins(external_dir: Optional[str] = None) -> dict:
    """
    扫描并导入内置 plugins/ 目录 + 外部插件目录下的所有插件。

    该函数会：
      1. 扫描内置 plugins/ 下的所有子目录
      2. 扫描外部插件目录（默认 data/plugins；可通过参数传入或 EXTERNAL_PLUGINS_DIR 环境变量）
      3. 导入每个子目录的 __init__.py
      4. 触发 @register_function 装饰器注册
      5. 触发 BasePlugin 子类的定义（后续通过 register_plugins_to_conn 注册）

    Args:
        external_dir: 可选，外部插件目录的绝对路径。若不传，
                      则使用环境变量 EXTERNAL_PLUGINS_DIR 或默认路径。

    Returns:
        dict: {
            "builtin":  [成功加载的内置插件模块列表],
            "external": [成功加载的外部插件模块列表],
        }
    """
    result = {"builtin": [], "external": []}

    # ------- 内置插件目录 -------
    plugins_dir = os.path.dirname(os.path.abspath(__file__))
    builtin_modules = _scan_plugin_directory(plugins_dir, "plugins")
    loaded_builtin = []
    for module_name in builtin_modules:
        if _import_module_safe(module_name):
            loaded_builtin.append(module_name)
    result["builtin"] = loaded_builtin

    # 兼容旧的扁平 functions 目录
    functions_dir = os.path.join(plugins_dir, "functions")
    if os.path.exists(functions_dir):
        try:
            from . import loadplugins
            loadplugins.auto_import_modules("plugins.functions")
            logger.bind(tag=TAG).info("已加载 plugins/functions 目录下的MCP函数")
        except Exception as e:
            logger.bind(tag=TAG).warning(f"加载 plugins/functions 目录失败: {e}")

    # ------- 外部插件目录 -------
    if external_dir is None:
        external_dir = os.environ.get("EXTERNAL_PLUGINS_DIR")
    if not external_dir:
        external_dir = _default_external_plugins_dir()
    external_dir = os.path.abspath(external_dir)

    if os.path.exists(external_dir) and os.path.isdir(external_dir):
        if _ensure_external_package(external_dir):
            external_modules = _scan_plugin_directory(external_dir, EXTERNAL_PKG_NAME)
            loaded_external = []
            for module_name in external_modules:
                if _import_module_safe(module_name):
                    loaded_external.append(module_name)
            result["external"] = loaded_external
            logger.bind(tag=TAG).info(
                f"外部插件目录扫描完成 ({external_dir})，共加载 {len(loaded_external)} 个外部插件"
            )
        else:
            logger.bind(tag=TAG).warning(f"外部插件目录初始化失败: {external_dir}")
    else:
        logger.bind(tag=TAG).info(
            f"外部插件目录不存在或不是目录，跳过: {external_dir} "
            f"（可设置环境变量 EXTERNAL_PLUGINS_DIR 指定其它路径）"
        )

    logger.bind(tag=TAG).info(
        f"插件扫描完成，内置 {len(result['builtin'])} 个模块，外部 {len(result['external'])} 个模块"
    )
    return result


def _is_plugin_module_name(module_name: str) -> bool:
    """判断模块名是否属于「插件来源模块」（用于 register_plugins_to_conn 扫描）"""
    if module_name.startswith("plugins.") and not module_name.startswith("plugins.functions"):
        return True
    if module_name.startswith(f"{EXTERNAL_PKG_NAME}."):
        return True
    return False


def register_plugins_to_conn(conn):
    """
    将已扫描的插件注册到连接的 plugin_manager。

    同时会自动：
      - 将插件的 get_tools() 注册为函数
      - 将插件的 get_providers() 注册到 provider_registry
      - 调用插件的 on_load() 生命周期钩子
      （以上由 PluginManager.register_plugin 内部完成）

    Args:
        conn: ConnectionHandler 实例（必须具备 plugin_manager 属性）
    """
    if not hasattr(conn, 'plugin_manager'):
        logger.bind(tag=TAG).warning("连接对象没有 plugin_manager 属性")
        return

    # 查找所有已导入的插件模块（内置 + 外部）
    plugins_modules = [
        name for name in sys.modules.keys() if _is_plugin_module_name(name)
    ]

    registered_count = 0

    for module_name in plugins_modules:
        try:
            module = sys.modules.get(module_name)
            if not module:
                continue

            # 查找模块中的 BasePlugin 子类
            for attr_name in dir(module):
                attr = getattr(module, attr_name)

                # 检查是否是 BasePlugin 的子类且不是 BasePlugin 本身
                if (isinstance(attr, type) and
                    issubclass(attr, BasePlugin) and
                    attr != BasePlugin):

                    # 创建实例并注册
                    try:
                        plugin_instance = attr(logger=conn.logger if hasattr(conn, 'logger') else None)
                        conn.plugin_manager.register_plugin(plugin_instance)
                        logger.bind(tag=TAG).info(
                            f"已注册插件: {plugin_instance.name} (来自 {module_name})"
                        )
                        registered_count += 1
                    except Exception as e:
                        logger.bind(tag=TAG).error(
                            f"注册插件 {attr_name} 失败: {e}"
                        )
        except Exception as e:
            logger.bind(tag=TAG).error(f"处理模块 {module_name} 时出错: {e}")

    logger.bind(tag=TAG).info(f"插件注册完成，共注册 {registered_count} 个插件实例")


# 向后兼容：导入旧路径的类
try:
    from .register import all_function_registry, module_func_map
    if "all_function_registry" not in __all__:
        __all__.append("all_function_registry")
    if "module_func_map" not in __all__:
        __all__.append("module_func_map")
except ImportError:
    pass
