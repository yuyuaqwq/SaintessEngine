# -*- coding: utf-8 -*-
"""宿主运行时（引擎侧）—— 任何平台、任何包的宿主都要做的「通用那一半」。

    from saintess_engine.host import Host, load_package

    host = Host(adapter, "path/to/package", seed=12345)   # adapter = 你自己的平台适配器
    host.boot()                                            # 加载包 + 装引擎
    host.serve_forever()                                   # 或在自己的事件回调里 host.handle(ctx)

三函数契约（宿主适配器的**唯一必填**面）
----------------------------------------
    recv() -> ctx | None                    没有新消息 → None（循环自旋）
    load_player(uid) -> dict | None         None = 新玩家（引擎造初始档 / 问包要）
    save_player(uid, data) -> None          一条消息一次（改完必存）
    say(to, text) -> None                   to = {"uid", "group_id"}；text **已渲染**

ctx 七字段：`uid` · `text` · `group_id` · `is_group` · `at[]` · `ts` · `raw`
（多给的字段忽略；见 `examples/host-skeleton/adapter_template.py` 的映射写法）

可选钩子（不给也能跑）：`clock()` · `rng()` · `on_tlog(record)` · `load_blob(key)`+`save_blob(key,val)` ·
`on_event(name, payload)` · `should_stop()`

命令通道（2026-09-14 起）
------------------------
声明在包（`content/data/commands.json`）、**处理器也在包**（`content/commands.py::COMMANDS`）。
引擎负责：命中声明 → 跑守卫（内置 `player`/`battle` + 包侧 `hook:<名>`）→ 构造 `Env` → 调处理器 → 投递回话。
所以宿主代码里**不出现任何游戏名词**，换包 = 换 `package_dir`（一个进程一个包，换包请重启进程）。

接缝纪律（不可谈判）：包内**只拿普通 dict 进来、只交普通 dict 出去**；
序列化 / 并发锁 / 落库 / 迁移全在适配器侧。别把 ORM 对象或连接句柄递给包。
"""
from .env import BUILTIN_GUARDS, Env, run_guards
from .outcome import BattleOutcome, Scenario, StandIns
from .package import Package, PackageError, load_package
from .runtime import (DEFAULTS_HINTS, DEFAULT_BATTLE_HINT, DEFAULT_REGISTER_HINT,
                      MINIMAL_SAVE_KEYS, Host)

__all__ = [
    "Host",
    "Env", "run_guards", "BUILTIN_GUARDS",
    "Package", "PackageError", "load_package",
    "Scenario", "BattleOutcome", "StandIns",
    "DEFAULTS_HINTS", "DEFAULT_REGISTER_HINT", "DEFAULT_BATTLE_HINT", "MINIMAL_SAVE_KEYS",
]
