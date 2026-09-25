# -*- coding: utf-8 -*-
"""战斗诊断通道：阶段/钩子出错时**记下来**——不阻断落地，也不静默。

为什么要有它（2026-09-25 引擎审计 P-44）
------------------------------------------------------------------
本包的战斗核心原先在每个阶段外面套 `except Exception: pass`（注释写「XX 异常不阻断落地」），
动机对（一场战斗不该因为一个钩子写错就炸），后果糟：内容侧任何一处出错都会被吞掉 ——
伤害照落、状态没加、**一条日志都没有**。玩家看到「放了没效果」，我们和探针看到「一切正常」。

本模块只做一件事：**记下来**。
  · 行为零变化：异常照样按原样吞掉 / 返回原值（调用方一行都不改）；
  · 记进 `battle.diagnostics`（list[dict]：stage / kind / msg / at / actor）；
  · 同时走引擎日志通道（`log`），运维侧查得到，**不进玩家可见的战斗日志**。
  · 门禁口径：**整场战斗 diagnostics 必须为空**（内容侧探针跑完一场断言 0 条）——
    空 = 这条通道在正常路径上零成本；非空 = 内容侧有 bug，当场有人管。
"""
from __future__ import annotations

import time
from typing import Any


def _stage_ctx(battle: Any) -> str:
    """记一条时顺手带上下文：谁在打、打到哪一刻。取不到就留空串（诊断本身不许再抛）。"""
    try:
        who = ""
        if battle is not None:
            f = getattr(battle, "focus", None)
            if callable(f):
                a = f()
                who = str((a or {}).get("name") or "")
        return who
    except Exception:
        return ""


def diag(battle: Any, stage: str, exc: BaseException | None = None, **ctx) -> dict:
    """记一条诊断（返回那条记录，永不抛）。`battle` 允许为 None（只落日志）。"""
    rec = {"stage": str(stage), "kind": type(exc).__name__ if exc is not None else "",
           "msg": str(exc)[:300] if exc is not None else "", "at": time.time(),
           "actor": _stage_ctx(battle)}
    for k, v in (ctx or {}).items():
        rec[str(k)] = v
    try:
        if battle is not None:
            box = getattr(battle, "diagnostics", None)
            if box is None:
                box = []
                setattr(battle, "diagnostics", box)
            box.append(rec)
    except Exception:
        pass
    try:                                    # 引擎日志通道（stderr/宿主 sink），不进玩家战斗日志
        from saintess_engine.log import facade as _L          # noqa: PLC0415
        _L.get_logger("battle.diagnostics").warning(
            "阶段出错：%s · %s: %s", stage, rec["kind"], rec["msg"])
    except Exception:
        pass
    return rec


def of(battle: Any) -> list:
    """这一场目前的诊断条目（没有就是空表）。"""
    return list(getattr(battle, "diagnostics", None) or [])


def clear(battle: Any) -> None:
    if battle is not None:
        try:
            setattr(battle, "diagnostics", [])
        except Exception:
            pass
