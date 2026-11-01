from enum import Enum
from typing import List, Dict, Optional, Any


class PluginAction(Enum):
    """插件返回状态枚举"""
    RELEASE = "release"  # 放行，继续原有流程
    INTERCEPT = "intercept"  # 拦截，返回结果
    CLOSE = "close"  # 关闭连接，返回结果


# 为避免循环导入，延迟引用 FunctionItem
def _get_function_item_cls():
    try:
        from .register import FunctionItem
        return FunctionItem
    except Exception:
        return None


class BasePlugin:
    """插件基类 - 所有扩展点均提供默认空实现，子类仅需覆盖极小部分。

    能力划分（可选择性实现）：
      1) 文本处理钩子：
         - pre_process_text(conn, text)   : 指令进入 LLM 前拦截/修改
         - post_process_text(conn, text)  : LLM 生成回复后做文本润色/替换

      2) Tool / 函数定义：
         - get_tools() -> List[FunctionItem]  : 返回该插件提供的 Tool（LLM 可调用的函数）

      3) Provider 扩展（自定义供应商）：
         - get_providers() -> Dict[str, Dict[str, type]]
             例：{"asr": {"MyASR": MyASRProviderClass}, "llm": {"FancyLLM": FancyLLMProviderClass}}
             支持的 key: asr / llm / tts / memory / vllm / vad / intent

      4) 生命周期钩子：
         - on_load()   : 插件被系统发现并实例化后调用（进程级，一次）
         - on_unload() : 插件卸载时调用（可选）

      5) 元信息（可选，默认使用类名）：
         - name / description / version / author
    """

    # ---------- 元信息 ----------
    name: str = "BasePlugin"
    description: str = "插件基类，所有方法均提供默认空实现。"
    version: str = "1.0.0"
    author: str = ""

    def __init__(self, logger=None):
        self.logger = logger

    # ===================================================================
    #  1) 文本处理钩子
    # ===================================================================
    async def pre_process_text(self, conn, text):
        """进入 LLM 前的文本预处理（指令/输入侧）。

        Returns:
            tuple: (processed_text, action)
                - action: PluginAction.RELEASE  放行（processed_text 会被作为新的输入）
                          PluginAction.INTERCEPT 拦截，用 processed_text 作为回复播放
                          PluginAction.CLOSE     拦截回复并关闭连接
        """
        return text, PluginAction.RELEASE

    async def post_process_text(self, conn, text: str) -> str:
        """LLM 生成最终回复后的文本后处理（输出侧）。

        注意：
          - 该钩子仅处理最终要播报/返回的纯文本内容，
            工具调用中间结果、system prompt 等不会进入这里。
          - 返回值会被用作最终回复；若返回 None/空串 则保持原文本不变。
        """
        return text

    # ===================================================================
    #  2) Tool / 函数定义
    # ===================================================================
    def get_tools(self) -> List[Any]:
        """返回插件提供的 Tool 函数列表（FunctionItem 实例）。

        若插件通过 @register_function 装饰器注册函数，则不需要覆盖此方法。
        两种方式可同时存在，互不冲突。
        """
        return []

    # ===================================================================
    #  3) Provider 扩展（自定义供应商）
    # ===================================================================
    def get_providers(self) -> Dict[str, Dict[str, type]]:
        """返回插件提供的自定义供应商类。

        Returns:
            Dict[provider_type, Dict[class_name, provider_class]]
              provider_type 取值范围: asr / llm / tts / memory / vllm / vad / intent
              class_name 为配置文件中使用的 type 名称
        例:
            return {
                "llm": {
                    "MyCustomLLM": MyCustomLLMProvider,
                },
                "tts": {
                    "MyTTS": MyTTSProvider,
                },
            }
        """
        return {}

    # ===================================================================
    #  4) 生命周期钩子
    # ===================================================================
    def on_load(self) -> None:
        """插件加载完成后调用一次（进程级）。"""
        pass

    def on_unload(self) -> None:
        """插件卸载时调用（可选）。"""
        pass

    # ===================================================================
    #  5) 辅助方法
    # ===================================================================
    def speak(self, conn, text):
        """发送语音消息（封装TTS和队列操作）"""
        from core.providers.tts.dto.dto import ContentType
        from core.handle.sendAudioHandle import send_stt_message
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(send_stt_message(conn, text))
        except RuntimeError:
            pass

        if hasattr(conn, 'tts') and conn.tts:
            conn.tts.tts_one_sentence(conn, ContentType.TEXT, content_detail=text)

    def get_info(self):
        """获取插件信息（用于调试/展示）"""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
        }
