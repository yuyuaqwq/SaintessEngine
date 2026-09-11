# -*- coding: utf-8 -*-
"""命令基类骨架 —— 宿主命令层的通用那一半。

分工（这是本包存在的意义）
--------------------------
| 框架提供（通用形状） | 使用方提供（内容/宿主） |
|---|---|
| 分页 / 页码解析 / 文本剥离 / 提示抽取 | 提示文案库（`_tip_pool_map`） |
| handler 查找与转发（`_find_handler` / `_run_shortcut`） | 宿主注册表探测（`_host_handler_finder`） |
| 守卫装饰器（`require_player` / `require_battle`） | 判定与文案（`_player` / `_in_any_battle` / hint 类属性） |
| 列表视图状态记录（`_record_list_state`） | 存储与 key 格式（`_record_state` + `list_state_key`） |
| 指令正则集合（`PatternSet`） | 正则表本身（`_build_command_regex_strings`） |

约定：**子类覆盖钩子，不改方法名** —— 既有的调用点（`self._page_items(...)`
等）一行都不用动。

`_find_handler` 的返回形状是**兼容契约**：`HandlerHit` 是 `NamedTuple`，
`hit[0]` 取到 handler 名（既有测试这样断言）。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional, Sequence

from .guards import DEFAULT_BATTLE_HINT, DEFAULT_REGISTER_HINT, require_battle, require_player
from .paging import page_items, parse_page
from .router import HandlerHit, PatternSet, find_static, matches_any, run_shortcut
from .text import strip_command
from .tips import DEFAULT_TIP, pick_tip

__all__ = ["CommandBase"]


class CommandBase:
    """通用命令基类骨架。子类通过覆盖钩子注入差异。"""

    # ---------- 可覆盖：文案 ----------
    register_hint: str = DEFAULT_REGISTER_HINT
    battle_none_hint: str = DEFAULT_BATTLE_HINT
    tip_fallback: Sequence[str] = (DEFAULT_TIP,)
    logger_name: str = "saintess_engine.command"

    # ---------- 可覆盖：指令别名（剥参数时用） ----------
    command_aliases: Sequence[str] = ()

    # ---------- 内部缓存 ----------
    _STATIC_HANDLERS = None
    _COMMAND_PATTERNS = None

    # ============================================================ 钩子（子类实现）
    def _uid(self, event) -> tuple:
        """从宿主事件取 `(group_id, user_id)`。"""
        raise NotImplementedError("子类须实现 _uid(event)")

    def _player(self, group_id, qq_id):
        """取玩家对象（不存在 → 假值）。"""
        raise NotImplementedError("子类须实现 _player(group_id, qq_id)")

    def _in_any_battle(self, group_id, qq_id) -> bool:
        """是否处于战斗中（默认 False；不涉及战斗的游戏可不覆盖）。"""
        return False

    def _tip_pool_map(self) -> dict:
        """提示语分类库 `{cat: [文案, ...]}`（默认空 → 走兜底）。"""
        return {}

    def _record_state(self, key: str, value: str) -> None:
        """写一条「列表视图状态」（子类接自己的存储）。"""
        return None

    def list_state_key(self, qq_id) -> str:
        """列表视图状态的存储 key。"""
        return f"last_list_{qq_id}"

    def _host_handler_finder(self):
        """返回宿主注册表探测函数 `finder(text) -> HandlerHit | None`；
        没有（测试/静态环境）→ None（此时只用静态表）。"""
        return None

    # ---- 类级内容（子类覆盖） ----
    @classmethod
    def _build_static_handlers(cls) -> list:
        """静态兜底表 `[(已编译正则, 方法名)]`；默认空。"""
        return []

    @classmethod
    def _build_command_regex_strings(cls) -> Sequence[str]:
        """「怎样算一条指令」的正则字符串集合（供 `command_patterns()` 用）；默认空。"""
        return []

    # ============================================================ 日志
    def _logger(self) -> logging.Logger:
        return logging.getLogger(getattr(self, "logger_name", "saintess_engine.command"))

    def _warn(self, msg: str, *args, **kwargs) -> None:
        self._logger().warning(msg, *args, **kwargs)

    # ============================================================ 分页
    @staticmethod
    def _page_items(items: list, page: int, per_page: int = 5) -> tuple:
        """通用翻页：返回 `(当前页条目, 总页数, 当前页码)`。"""
        return page_items(items, page, per_page)

    def _parse_page(self, raw: str) -> int:
        """解析参数中的页码；纯数字 → 页码，否则 1。"""
        return parse_page(raw)

    # ============================================================ 文本
    def _strip_cmd(self, event, cmd: str) -> str:
        """从消息中剥离 At 前缀和指令名，返回剩余参数。"""
        msg = event.get_message_str().strip()
        return strip_command(msg, cmd, getattr(self, "command_aliases", ()))

    # ============================================================ 提示
    def _tip(self, cat: str) -> str:
        """按分类随机抽一条提示（含 emoji 前缀规则）。"""
        return pick_tip(self._tip_pool_map(), cat,
                        fallback=getattr(self, "tip_fallback", None))

    # ============================================================ 列表视图状态
    def _record_list_state(self, qq_id, cmd, page, pages) -> None:
        """记录玩家最后一次列表视图（翻页快捷键用）。

        `cmd`：重建指令文本（不含页码，如 `'背包 材料'`）。失败静默（附加功能）。
        """
        if not qq_id:
            return
        import json
        try:
            self._record_state(self.list_state_key(qq_id),
                               json.dumps({"cmd": cmd, "page": page, "pages": pages},
                                          ensure_ascii=False))
        except Exception:
            pass

    # ============================================================ 宿主事件小工具
    @staticmethod
    def _stop_event_safe(event) -> None:
        """安全 `stop_event`：宿主事件没有该方法（如回环测试链路）时静默跳过。"""
        stop = getattr(event, "stop_event", None)
        if not stop:
            return
        try:
            stop()
        except Exception:
            logging.getLogger("saintess_engine.command").warning(
                "[saintess_engine.command] stop_event 调用失败（已忽略）", exc_info=True)

    # ============================================================ handler 路由
    @classmethod
    def _static_handlers(cls) -> list:
        """静态兜底表（懒构建 + 缓存）。"""
        if cls._STATIC_HANDLERS is None:
            cls._STATIC_HANDLERS = cls._build_static_handlers()
        return cls._STATIC_HANDLERS

    @classmethod
    def command_patterns(cls) -> PatternSet:
        """「怎样算一条指令」的正则集合（懒编译 + 缓存）。"""
        if cls._COMMAND_PATTERNS is None:
            cls._COMMAND_PATTERNS = PatternSet(cls._build_command_regex_strings)
        return cls._COMMAND_PATTERNS

    @staticmethod
    def matches_command_text(text: str, patterns: Sequence) -> bool:
        """文本是否命中任一指令正则（宿主 filter 类可用；零宽匹配默认跳过）。"""
        return matches_any(text or "", patterns)

    def _find_handler(self, text: str) -> Optional[HandlerHit]:
        """按指令文本找 handler（宿主注册表优先，静态表兜底）。

        返回 `HandlerHit | None`；`hit[0]` 是 handler 名（**兼容契约**）。
        """
        text = (text or "").strip()
        finder = self._host_handler_finder()
        if finder is not None:
            try:
                hit = finder(text)
                if hit is not None:
                    return hit
            except Exception:
                self._warn("遍历宿主注册表异常，回退静态表", exc_info=True)
        return find_static(text, self._static_handlers(), self)

    def _run_shortcut(self, event, text: str):
        """执行快捷指令：把文本转发给命中的 handler（async generator）。"""
        return run_shortcut(self, event, text, self._find_handler, logger=self._logger())
