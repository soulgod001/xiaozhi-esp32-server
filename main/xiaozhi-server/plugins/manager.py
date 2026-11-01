import yaml
import os
from .base import BasePlugin, PluginAction
from .register import (
    all_function_registry,
    module_func_map,
    provider_registry,
    FunctionItem,
)


class PluginConfig:
    """插件配置类"""

    def __init__(self, name, enabled=True, priority=100, post_priority=100, config=None):
        self.name = name
        self.enabled = enabled
        # 预处理优先级（值越小越先执行）
        self.priority = priority
        # 后处理优先级（值越小越先执行）
        self.post_priority = post_priority
        self.config = config or {}


class PluginManager:
    """插件管理器 - 支持优先级、启用开关、三状态返回 + 后处理链路 + Tool/Provider 自动注册"""

    def __init__(self, config_path=None):
        self.plugins = []
        # 后处理链路，独立于预处理链路排序
        self.post_plugins = []
        self.plugin_configs = {}
        self.config_path = config_path

        if config_path and os.path.exists(config_path):
            self._load_plugin_configs_from_main()

    def _load_plugin_configs_from_main(self):
        """从主配置加载动态拦截器配置"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            for name, cfg in config.get('dynamic_interceptors', {}).items():
                self.plugin_configs[name] = PluginConfig(
                    name=name,
                    enabled=cfg.get('enabled', True),
                    priority=cfg.get('priority', 100),
                    post_priority=cfg.get('post_priority', cfg.get('priority', 100)),
                    config=cfg
                )
        except Exception as e:
            print(f"加载插件配置失败: {e}")

    # ------------------------------------------------------------------
    #  插件注册：同时注册 Tool + Provider + 生命周期
    # ------------------------------------------------------------------
    def register_plugin(self, plugin, config=None):
        """注册插件。同时自动完成：
           1) 预处理链路注册
           2) 后处理链路注册
           3) Tool 函数注入到全局 all_function_registry
           4) Provider 类注入到全局 provider_registry
           5) 调用 on_load() 生命周期钩子
        """
        if not isinstance(plugin, BasePlugin):
            return

        plugin_name = plugin.name if hasattr(plugin, 'name') and plugin.name else plugin.__class__.__name__

        if config:
            plugin_config = PluginConfig(
                name=plugin_name,
                enabled=config.get('enabled', True),
                priority=config.get('priority', 100),
                post_priority=config.get('post_priority', config.get('priority', 100)),
                config=config
            )
        elif plugin_name in self.plugin_configs:
            plugin_config = self.plugin_configs[plugin_name]
        else:
            plugin_config = PluginConfig(name=plugin_name, enabled=True, priority=100, post_priority=100)

        plugin._plugin_config = plugin_config

        if not plugin_config.enabled:
            return

        # -------- 预处理链路 --------
        self.plugins.append(plugin)
        self.plugins.sort(key=lambda p: p._plugin_config.priority if hasattr(p, '_plugin_config') else 100)

        # -------- 后处理链路 --------
        self.post_plugins.append(plugin)
        self.post_plugins.sort(
            key=lambda p: p._plugin_config.post_priority if hasattr(p, '_plugin_config') else 100
        )

        # -------- Tool 自动注册（来自 plugin.get_tools()） --------
        self._register_plugin_tools(plugin, plugin_name)

        # -------- Provider 自动注册（来自 plugin.get_providers()） --------
        self._register_plugin_providers(plugin, plugin_name)

        # -------- 生命周期钩子 --------
        try:
            plugin.on_load()
        except Exception as e:
            if hasattr(self, 'logger') and self.logger:
                self.logger.warning(f"插件 {plugin_name} on_load 执行失败: {e}")
            else:
                print(f"[WARNING] 插件 {plugin_name} on_load 执行失败: {e}")

    def _register_plugin_tools(self, plugin: BasePlugin, plugin_name: str):
        """将 plugin.get_tools() 返回的 FunctionItem 注入全局注册表。"""
        try:
            tools = plugin.get_tools() or []
        except Exception as e:
            if hasattr(self, 'logger') and self.logger:
                self.logger.warning(f"插件 {plugin_name} get_tools 执行失败: {e}")
            else:
                print(f"[WARNING] 插件 {plugin_name} get_tools 执行失败: {e}")
            return

        for item in tools:
            if not isinstance(item, FunctionItem):
                continue
            if item.name in all_function_registry:
                print(f"[WARNING] 函数 {item.name} 已存在，插件 {plugin_name} 注册被跳过")
                continue
            all_function_registry[item.name] = item
            module_func_map.setdefault(plugin_name, []).append(item.name)
            print(f"[INFO] 函数 '{item.name}' 已由插件 {plugin_name} 注册")

    def _register_plugin_providers(self, plugin: BasePlugin, plugin_name: str):
        """将 plugin.get_providers() 返回的 provider 类注入全局注册表。"""
        try:
            providers = plugin.get_providers() or {}
        except Exception as e:
            if hasattr(self, 'logger') and self.logger:
                self.logger.warning(f"插件 {plugin_name} get_providers 执行失败: {e}")
            else:
                print(f"[WARNING] 插件 {plugin_name} get_providers 执行失败: {e}")
            return

        for p_type, mapping in providers.items():
            if p_type not in provider_registry:
                print(f"[WARNING] 未知的 provider 类型: {p_type}，插件 {plugin_name}")
                continue
            if not isinstance(mapping, dict):
                continue
            for cls_name, cls in mapping.items():
                if cls_name in provider_registry[p_type]:
                    print(
                        f"[WARNING] provider {p_type}.{cls_name} 已存在，"
                        f"插件 {plugin_name} 注册被跳过"
                    )
                    continue
                provider_registry[p_type][cls_name] = cls
                print(
                    f"[INFO] Provider 已由插件 {plugin_name} 注册: "
                    f"{p_type}.{cls_name} = {cls.__name__}"
                )

    def load_plugins_from_config(self, config_path, conn):
        """从配置文件加载插件"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                plugin_config = yaml.safe_load(f)

            for plugin_info in plugin_config.get('plugins', []):
                plugin_type = plugin_info.get('type')
                enabled = plugin_info.get('enabled', True)
                priority = plugin_info.get('priority', 100)
                post_priority = plugin_info.get('post_priority', priority)

                if not enabled or not plugin_type:
                    continue

                try:
                    module_name, class_name = plugin_type.rsplit('.', 1)
                    import importlib
                    module = importlib.import_module(module_name)
                    plugin_class = getattr(module, class_name)
                    plugin = plugin_class(logger=conn.logger if hasattr(conn, 'logger') else None)
                    self.register_plugin(
                        plugin,
                        {
                            'enabled': enabled,
                            'priority': priority,
                            'post_priority': post_priority,
                            'config': plugin_info,
                        },
                    )
                except Exception as e:
                    print(f"加载插件 {plugin_type} 失败: {e}")
        except Exception as e:
            print(f"加载插件配置失败: {e}")

    # ------------------------------------------------------------------
    #  文本处理链路
    # ------------------------------------------------------------------
    async def process_text(self, conn, text):
        """预处理（进LLM前）- 支持三状态返回 (RELEASE/INTERCEPT/CLOSE)

        Returns:
            tuple: (result, action)
        """
        processed_text = text

        for plugin in self.plugins:
            try:
                result = await plugin.pre_process_text(conn, processed_text)

                # 兼容旧格式 (result, bool) 和新格式 (result, PluginAction)
                if isinstance(result, tuple) and len(result) == 2:
                    if isinstance(result[1], bool):  # 旧格式
                        action = PluginAction.INTERCEPT if result[1] else PluginAction.RELEASE
                        processed_text, action = result[0], action
                    else:  # 新格式
                        processed_text, action = result
                else:
                    # 意外格式，跳过
                    continue

                # 处理不同状态并设置连接标志位
                if action == PluginAction.CLOSE:
                    conn.close_after_chat = True
                    return processed_text, PluginAction.CLOSE
                elif action == PluginAction.INTERCEPT:
                    conn.close_after_chat = False
                    return processed_text, PluginAction.INTERCEPT
                # RELEASE: 继续下一个插件，不设置标志位

            except Exception as e:
                if hasattr(conn, 'logger'):
                    conn.logger.error(f"插件 {plugin.name} 预处理失败: {e}")
                continue

        return processed_text, PluginAction.RELEASE

    async def process_text_post(self, conn, text: str) -> str:
        """后处理（LLM 生成最终回复后）- 链式后处理，按 post_priority 顺序执行。

        注意：任何插件返回 None/空串，均视为"保持原文本"，避免误清空。
        """
        if not text:
            return text

        processed = text
        for plugin in self.post_plugins:
            try:
                new_text = await plugin.post_process_text(conn, processed)
                if new_text is not None and new_text != "":
                    processed = new_text
            except Exception as e:
                if hasattr(conn, 'logger'):
                    conn.logger.error(f"插件 {plugin.name} 后处理失败: {e}")
                continue
        return processed

    # ------------------------------------------------------------------
    #  调试/管理接口
    # ------------------------------------------------------------------
    def get_plugins_info(self):
        """获取所有插件信息"""
        result = []
        seen = set()
        for plugin in self.plugins:
            info = plugin.get_info()
            if hasattr(plugin, '_plugin_config'):
                info['enabled'] = plugin._plugin_config.enabled
                info['priority'] = plugin._plugin_config.priority
                info['post_priority'] = plugin._plugin_config.post_priority
            seen.add(id(plugin))
            result.append(info)
        return result

    def get_all_plugins_count(self):
        """获取插件总数"""
        return len(self.plugin_configs) if self.plugin_configs else len(self.plugins)

    def is_plugin_enabled(self, plugin_name):
        """检查插件是否启用"""
        if plugin_name in self.plugin_configs:
            return self.plugin_configs[plugin_name].enabled
        return any(hasattr(p, 'name') and p.name == plugin_name for p in self.plugins)
