# -*- coding: utf-8 -*-
"""门禁辅助（cue 绝对时刻）：在**真结算路径**上量每条 cue 实际收到的 payload。

为什么需要这个辅助（`tests/test_cues_shape.py` §8 用）
-----------------------------------------------------
判据是「**每**一条 cue 的 payload 都含绝对时刻」。要证它，就得量**全部**声明的 cue ——
不是挑几条好看的。手搓场景必然漏（62 条里有一半只在特定战斗形态下才发：
`schedule.dot_tick` / `gauge.*` / `landing.taken_mult_skipped` …），漏一条门禁就变成自证。

所以这里复用覆盖尺那套真驱动（`tools/_cue_coverage.py` + `tools/_cue_freeze.py`）：
  · 冻结 5 组战斗（`F.collect`）+ 覆盖尺补驱动（`C.DRIVERS`）
  · 每一条都走引擎**真实**结算路径发 cue（覆盖尺自身被 `tests/test_cue_coverage.py` §3
    钉死「驱动函数体里零 `cue(...)` / `emit(...)`」——不许凭空发那一行）
在订阅层挂一个探针，把每条 cue 真实收到的 payload 原样记下来。

`seal=False` 时走**反证**那条路：把各模块里的 `cue` 换成不补时刻的版本
（＝「拿掉补格那一步」），同一批驱动重跑一遍 ⇒ 全部缺格。判据必须有牙。
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if os.path.join(_ROOT, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "tools"))

#: `ext_combat` 包根（反证要在**全包**里找那些把 `cue` 绑成 `_cue` 的模块）。
_EXT_COMBAT = os.path.join(_ROOT, "extends", "ext_combat")


def _emit_modules() -> dict:
    """扫全包，找出每一支 `from …cues import cue as _cue` 的模块 → {模块名: 模块对象}。

    ★ 为什么用 AST 扫而不是手写模块清单：反证要把**每一支**都换掉才能真的「拿掉补格」。
    手写清单会漏掉子包（`gauge/` 就有两支）⇒ 漏掉的那两支仍走真出口 ⇒ 反证只验了一半，
    门禁就成了「看着有牙、其实有豁免」。新增子包也自动被算进来。
    """
    import ast
    import importlib

    mods = {}
    for dirpath, _dirs, files in os.walk(_EXT_COMBAT):
        for fn in sorted(files):
            if not fn.endswith(".py") or fn.startswith("test_"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, _EXT_COMBAT).replace("\\", "/")
            if rel == "battle/cues.py":
                continue
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                # `node.names` 里装的是 ast.alias 对象 —— 必须逐个取 `.name`，
                # 写成 `"cue" in node.names` 恒为 False（实测：扫到 0 个模块，反证只验了一半）。
                if not any(a.name == "cue" and (a.asname or a.name) == "_cue"
                           for a in node.names):
                    continue
                mod = rel[:-3].replace("/", ".")
                if mod.endswith(".__init__"):
                    mod = mod[: -len(".__init__")]
                try:
                    mods[mod] = importlib.import_module("ext_combat." + mod)
                except Exception:                                    # noqa: BLE001
                    pass
                break
    return mods


def _probe_subs(seen: dict):
    """探针订阅表：每条 cue = 内容侧的 text 订阅（渲染仍走真表）+ 一个记账的 call 订阅者。

    ★ 保留真 text 订阅是刻意的：订阅者**什么都不改**也照样被量到 payload
    （我们要看的是「订阅者收到什么」，不是「有没有人用」）。
    """
    from ext_combat.battle.cues import CUE_NAMES

    def _rec(name):
        def _fn(payload):
            seen.setdefault(name, dict(payload or {}))
        return _fn

    return {n: ({"kind": "text", "key": n}, {"kind": "call", "handler": _rec(n)})
            for n in CUE_NAMES}


def _unsealed_cue(cues_mod):
    """「拿掉补格那一步」的出口（**只**少 `with_now`，其余逐行照抄 `cues.cue`）。"""
    def cue(battle, logs, name, payload=None):
        bus = cues_mod.cue_of(battle)
        if bus is not None:
            try:
                bus.emit(logs, name, payload)          # ← 与真出口唯一的差别
                return
            except Exception as e:                     # noqa: BLE001
                cues_mod._diag(battle, "cue().emit", e)
        else:
            cues_mod._diag(battle, "cue()", cues_mod.EngineNotConfigured(
                "cue %r 发了但这场战斗没有 cue 总线：内容侧该在 cue_subs_fn 里声明订阅表" % name))
        cues_mod._cue_broken_line(logs, name)
    return cue


def run(seal: bool = True) -> tuple:
    """跑冻结 5 组 + 覆盖尺补驱动 → `(seen, fired, missing)`。

    * `seen`    —— cue 名 → 该 cue 真实收到的 payload 样本（第一手，只记第一次）
    * `fired`   —— 覆盖尺声明面（引擎 `CUE_NAMES`）里**真发过**的条数
    * `missing` —— 声明了但这一轮没发到的 cue（门禁单独红这一条：没量到 ≠ 通过）

    `seal=True`  = 现状（出口补时刻）；`seal=False` = 反证（出口不补时刻）。
    """
    import _cue_coverage as C
    import _cue_freeze as F
    from ext_combat.battle import cues as CUES_MOD
    from saintess_engine import config as CFG

    tree = _ROOT
    F._setup_path(tree)
    seen: dict = {}

    # ★ 顺序很重要：示例包 `content` 是 **import 即接管**（`content/__init__.py` 里
    #   `install_engine()` 会 `mount(cue_subs_fn=本包自己的 subs)`）。若在它之后才装探针，
    #   它会把手表覆盖掉 ⇒ 探针只量到 21/62 条（实测）。
    #   所以**先** import content 把那次接管走完，**再**装探针 —— 探针此后一直赢。
    #   （门禁侧还有一条「每条都真发过一次」兜底，量少了会当场红；这里是不依赖那条兜底。）
    try:
        import content  # noqa: F401
    except Exception:                                                # noqa: BLE001
        pass

    saved_subs = CFG._HOOKS.get("cue_subs_fn")
    saved_cue = CUES_MOD.cue
    mods = _emit_modules()
    saved_bind = {name: getattr(m, "_cue", None) for name, m in mods.items()}
    try:
        if not seal:
            alt = _unsealed_cue(CUES_MOD)
            CUES_MOD.cue = alt
            for m in mods.values():
                if hasattr(m, "_cue"):
                    m._cue = alt

        # ① 冻结 5 组（真结算路径；探针表须在**构造 Battle 之前**装好 —— 总线是构造期建的）
        CFG._HOOKS["cue_subs_fn"] = lambda: _probe_subs(seen)
        F.collect(tree, "none")

        # ② 覆盖尺补驱动（真结算路径）
        CFG._HOOKS["cue_subs_fn"] = lambda: _probe_subs(seen)
        rig = C.Rig(tree)
        CFG._HOOKS["cue_subs_fn"] = lambda: _probe_subs(seen)
        rig.battle([rig.player()], [rig.mob()])           # 触发一次装配期对账
        for k in sorted(C.DRIVERS):
            fn = C.DRIVERS.get(k)
            if fn is None:
                continue
            try:
                fn(rig)
            except Exception:                            # noqa: BLE001 —— 覆盖尺自己会报差集
                pass
    finally:
        CUES_MOD.cue = saved_cue
        for name, m in mods.items():
            if hasattr(m, "_cue"):
                m._cue = saved_bind[name]
        if saved_subs is None:
            CFG._HOOKS["cue_subs_fn"] = None
        else:
            CFG._HOOKS["cue_subs_fn"] = saved_subs

    from ext_combat.battle.cues import CUE_NAMES
    return seen, len(seen), [n for n in CUE_NAMES if n not in seen]
