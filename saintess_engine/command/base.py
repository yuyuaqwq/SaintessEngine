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
from typing import Optional, Sequence

from ..log import get_logger

from .paging import page_items, parse_page
from .router import HandlerHit, PatternSet, find_static, matches_any, run_shortcut
from .text import strip_command
from .tips import pick_tip

__all__ = ["CommandBase"]


class CommandBase:
    """通用命令基类骨架。子类通过覆盖钩子注入差异。"""

    # ---------- 可覆盖：文案 ----------
    #: 守卫拦截句（属内容；★ 2026-09-25 审计 E2b：引擎不再自带文案 ⇒ 空 = 没声明，
    #: 用到时由 guards 抛 `EngineNotConfigured`，不静默编一句）
    register_hint: str = ""
    battle_none_hint: str = ""
    #: 提示池兜底（内容侧给；不给 ⇒ 不出提示行，见 `tips.pick_tip`）
    tip_fallback: Sequence[str] = ()
    # 空 = 用日志门面的默认名（`<prefix>.command`）；宿主可给完整名（如自己的 "astrbot"）
    logger_name: str = ""

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
        name = getattr(self, "logger_name", "") or ""
        return logging.getLogger(name) if name else get_logger("command")

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

        `cmd`：重建指令文本（不含页码，如 `'背包 材料'`）。

        ★ 2026-09-29 晚到批第二十九轮（探针实测，非推断）：原先整段是
        `except Exception: pass` —— **零痕迹**。但这处有两个语义完全不同的情况，
        而 `self._record_state` 恰好把「没接」与「炸了」编码在**同一个形状**里：

        · 基类 `_record_state` 是个 `return None` 的空实现（base.py:72），
          即「这个壳没接存储半边」= **合法**（纯静态/测试链路），
          此时本方法什么都不做是对的；
        · `host/shell.py:151` 的实现是 `self._store.set_event_state(key, value)`
          —— 真宿主。**接了却炸了**（列不存在 / 锁库 / 事务回滚）是真故障。

        两者在原写法下运维侧**完全一样**：翻页快捷键用不到、`last_list_<qq>` 没写进去，
        玩家下一次翻页静默回到第 1 页，**零日志零异常**。这不是降级，是丢功能。

        处置 = **按有没有覆写判定**「接了没有」：`type(self)._record_state is
        CommandBase._record_state` ⇒ 没接 ⇒ 早退（合法）；否则写入失败要留痕。
        留痕面用这层既有的 `self._warn`（同文件 `_run_shortcut` 已在用），
        不新造旁路、不静默。
        """
        if not qq_id:
            return
        import json
        if type(self)._record_state is CommandBase._record_state:
            return                      # 没接存储半边（合法早退，与 _player 的 NotImplemented 同族）
        try:
            self._record_state(self.list_state_key(qq_id),
                               json.dumps({"cmd": cmd, "page": page, "pages": pages},
                                          ensure_ascii=False))
        except Exception as exc:        # noqa: BLE001
            self._warn("列表视图状态写入失败（翻页快捷键会退回第 1 页）key=%r: %s",
                       self.list_state_key(qq_id), exc)

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
            get_logger("command").warning(
                "stop_event 调用失败（已忽略）", exc_info=True)

    # ============================================================ handler 路由
    @classmethod
    def _static_handlers(cls) -> list:
        """静态兜底表（懒构建 + 缓存）。"""
        # ★ 2026-09-28 审计 L287-1 / L288-1：缓存**按类隔离**。
        #   原写法读 `cls._STATIC_HANDLERS`（属性查找会沿 MRO 落到父类那份）：
        #   父类先建过缓存后，子类拿到**父类**的表 —— 复现 Child 拿到 ['p_h']（期望 ['c_h']）。
        #   判据 = 「这个键是不是 cls 自己的」：命中 cls.__dict__ 才算已缓存；
        #   否则（含 None 占位、继承而来的父类缓存）一律按本类重建，
        #   写也只写 cls.__dict__，绝不污染父类那份。
        cache = cls.__dict__.get("_STATIC_HANDLERS")
        if cache is None:
            cache = cls._build_static_handlers()
            cls._STATIC_HANDLERS = cache
        return cache

    @classmethod
    def command_patterns(cls) -> PatternSet:
        """「怎样算一条指令」的正则集合（懒编译 + 缓存）。"""
        cache = cls.__dict__.get("_COMMAND_PATTERNS")
        if cache is None:
            cache = PatternSet(cls._build_command_regex_strings)
            cls._COMMAND_PATTERNS = cache
        return cache

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
