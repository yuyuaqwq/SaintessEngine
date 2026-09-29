#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：`saintess_engine/host/env.py` 的注入面钩子不许「真故障 → 零痕迹」。

为什么要有它（2026-09-29 审计修复车道 第三十一轮）
------------------------------------------------------
`Env` 是**包内指令处理器拿到宿主能力的唯一入口**。两个便捷方法各有一条 `except Exception`：

  · `now_tlog` —— 原 `except: pass`。契约写「没给出口就静默丢弃」，于是
    「**出口没给**」（合法可选）与「**出口接了却炸了**」（真故障：这条流水永久丢失）
    走同一条路，后者**零痕迹**。第三十轮已在 `host/runtime.py::tlog_write` 按同口径修过，
    本文件把那套判据搬进 `Env`，并钉住「合法路径必须仍然安静」。
  · `page` —— 原 `except: return default`。玩家输入乱页码（合法）与
    **解析器供体自己炸了 / 返回脏类型**（真故障）原先同路 ⇒ 调用方拿到一个
    **编造的**页码且无人知情。分界依据 = 异常类型：引擎 `parse_page` 的既定口径是
    ValueError/TypeError；其余异常（实测 RuntimeError、dict 返回值）= 供体故障 ⇒ 留痕。

判据
------------------------------------------------------------------
1. 合法路径**零日志**：没给 `tlog`、玩家输入乱页码 ⇒ 不许出声（它们不是故障）。
2. 真故障**有日志**：`tlog` 供体抛错 / 供体签名不匹配 / 解析器抛非 ValueError·TypeError
   / 解析器返回脏类型 ⇒ 必须记一条 error 级日志，且**带 exc_info**（可定位）。
3. **行为零变化**：四种情形下返回值与抛不抛异常，与改前逐项相同（回落 default / 不抛）。
4. 源码形状钉死：`except` 里必须有「按异常类型分界」的判据 —— 防止将来被改回 `pass`。

跑法：`python tests/test_env_silent_fallback.py`；退出码 0 = 全绿 · 1 = 有失败。
"""
from __future__ import annotations

import inspect
import logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
for _p in (ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _check import bind_check  # noqa: E402

PASS = 0
FAILS: list = []
check = bind_check(globals(), "PASS", "FAIL", "FAILS")


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records: list = []

    def emit(self, r):
        self.records.append(r)


def _capturing(fn):
    """跑 `fn` 并返回它期间记下的 error 级日志（走标准库根 logger，引擎门面同源）。"""
    root = logging.getLogger()
    h = _Capture()
    prev_level, prev_prop = root.level, root.propagate
    root.addHandler(h)
    root.setLevel(logging.DEBUG)
    try:
        out = fn()
    finally:
        root.removeHandler(h)
        root.setLevel(prev_level)
        root.propagate = prev_prop
    return out, [r for r in h.records if r.levelno >= logging.ERROR]


def main() -> int:                                             # noqa: C901
    from saintess_engine.host import env as env_mod
    from saintess_engine.host.env import Env
    import saintess_engine.command as command_mod

    print("== 1. 合法路径必须安静（没有故障就不许出声）==")
    (_, recs) = _capturing(lambda: Env().now_tlog("x.y", a=1))
    check("没给 tlog 出口 ⇒ 零日志（可选钩子不给也能跑）", not recs, str(len(recs)))

    (_, recs) = _capturing(lambda: Env(text="abc").page("abc"))
    check("玩家输入乱页码 ⇒ 零日志（合法回落第 1 页）", not recs, str(len(recs)))

    print()
    print("== 2. 真故障必须留痕 ==")
    # 2a. 流水供体抛错
    def boom_tlog(kind, **f):
        raise RuntimeError("tlog sink exploded")
    _, recs = _capturing(lambda: Env(tlog=boom_tlog).now_tlog("player.login", uid="p1"))
    check("tlog 供体抛 RuntimeError ⇒ 记一条 error 日志", len(recs) == 1, f"{len(recs)} 条")
    check("★ 日志带 exc_info（栈可定位，不是干巴巴一句话）",
          bool(recs and recs[0].exc_info), str([r.exc_info for r in recs]))
    check("★ 日志点名 kind（能定位是哪条流水丢了）",
          bool(recs) and "player.login" in recs[0].getMessage(),
          recs[0].getMessage() if recs else "")

    # 2b. 供体签名不匹配（TypeError）
    _, recs = _capturing(lambda: Env(tlog=lambda kind: None).now_tlog("player.login", uid="p1"))
    check("供体签名不匹配（TypeError）⇒ 也记 error（TypeError 不是玩家乱输入）",
          len(recs) == 1, f"{len(recs)} 条")

    # 2c. 解析器抛非 ValueError/TypeError
    orig = command_mod.parse_page
    try:
        command_mod.parse_page = lambda t: (_ for _ in ()).throw(RuntimeError("parse boom"))
        got, recs = _capturing(lambda: Env(text="9").page("9"))
        check("解析器抛 RuntimeError ⇒ 记一条 error 日志", len(recs) == 1, f"{len(recs)} 条")
        check("★ 且仍回落 default（行为零变化：指令不炸）", got == 1, f"page()={got}")

        # 2d. 解析器返回脏类型（dict ⇒ int() TypeError）—— 这也是**真故障**：
        #     玩家输入乱页码到不了这里（parse_page 自己返回 1），脏返回值只可能来自供体故障。
        command_mod.parse_page = lambda t: {"not": "a number"}
        got, recs = _capturing(lambda: Env(text="9").page("9"))
        check("解析器返回 dict（脏数据）⇒ 记一条 error 日志", len(recs) == 1, f"{len(recs)} 条")
        check("★ 且仍回落 default", got == 1, f"page()={got}")
    finally:
        command_mod.parse_page = orig

    print()
    print("== 2e. 前提钉死：玩家乱输入**到不了** except（否则「全部留痕」会变成噪音）==")
    from saintess_engine.command import parse_page
    quiet = [t for t in ("abc", "zzz", "第 2 页", "-1", "") 
             if not (lambda: (parse_page(t) == 1))()]  # parse_page 对它们返回 1 ⇒ 不抛
    check("★ parse_page 对五种乱输入都返回 1（自己抛不了 ⇒ except 里全是真故障）",
          not quiet, str(quiet))

    print()
    print("== 3. 行为零变化：四种情形都不抛、返回值与改前一致 ==")
    e = Env(tlog=boom_tlog)
    try:
        e.now_tlog("k", a=1)
        check("tlog 供体抛错时 now_tlog **不抛**（流水不该阻断命令通道）", True)
    except Exception as exc:                                    # noqa: BLE001
        check("tlog 供体抛错时 now_tlog **不抛**", False, f"抛了 {type(exc).__name__}: {exc}")

    # ★ 既得事实（探针实测 · 改前逐条对拍）：`command.parse_page` 对乱输入一律**返回 1**、
    #   自己不抛 ⇒ 乱输入**根本到不了** except，default 形参在这条路上从未生效。
    #   这里钉住的是「与改前逐字相同」，不是「default 该不该生效」——后者是另一个议题。
    check("page 对乱输入回落 1（与改前逐字相同）", Env(text="zzz").page("zzz", 1) == 1)
    check("★ 乱输入的 default 形参本就不生效（既得事实，非本次引入）",
          Env(text="zzz").page("zzz", 7) == 1, f"got={Env(text='zzz').page('zzz', 7)}")
    check("正常页码仍正常解析（没被新判据误伤）",
          Env(text="3").page("3") == 3, Env(text="3").page("3"))

    print()
    print("== 4. 源码形状钉死（防止被改回 pass / 改回单一 except）==")
    src_now = inspect.getsource(Env.now_tlog)
    check("now_tlog 的 except 体里有 error 级留痕（不是 pass）",
          "_log.error" in src_now and "pass" not in src_now.split("except", 1)[-1].split("\n\n")[0],
          src_now.strip().splitlines()[-3:])
    src_page = inspect.getsource(Env.page)
    check("page 的 except 体里有 error 级留痕（不是 pass）",
          "_log.error" in src_page and "exc_info" in src_page,
          src_page.strip().splitlines()[-5:])

    print()
    print("== 5. 反证：把两处留痕改回静默 ⇒ 本门禁必须转红 ==")
    # 不改产品码文件；用一次「等价于改回」的动态验证：把 _log 换成哑巴，
    # 若门禁仍绿，说明它没在真验留痕通道。
    real_log = env_mod._log

    class _Mute:
        def error(self, *a, **k): pass
    env_mod._log = _Mute()
    try:
        _, recs2 = _capturing(lambda: Env(tlog=boom_tlog).now_tlog("player.login"))
        check("★ 留痕通道被哑巴化 ⇒ 真的记不到（证明上面那些绿不是恒真）",
              len(recs2) == 0, f"{len(recs2)} 条")
    finally:
        env_mod._log = real_log

    print()
    return 0 if PASS and not FAILS else 1


if __name__ == "__main__":
    rc = main()
    print(f"\n===== 结果：通过 {PASS} / 失败 {len(FAILS)} =====")
    for f in FAILS:
        print("  ❌", f)
    sys.exit(rc)
