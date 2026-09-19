# -*- coding: utf-8 -*-
"""沙箱试跑（子进程侧）—— 在本进程里装配引擎 + 游戏包，跑一场最小战斗。

入参（stdin JSON）：
    {"skill": {...}, "skill_lv": 1, "attacker": {...}|null, "defender": {...}|null,
     "seed": 1, "pkg_dir": "..."}   pkg_dir 缺省读环境变量 FW_PKG_DIR

出参（stdout 一行 MARKER+JSON）：
    {"ok": true, "damage": N, "logs": [...], "events": [...], "attacker": {...}}
    {"ok": false, "stage": "load|engine|crash", "message": "...", ...}

引擎/内容零星 print 不会污染结果（父进程只认 MARKER 行）。
"""
from __future__ import annotations

import json
import os
import sys
import traceback

MARKER = "__FW_SIM_RESULT__"
FW_ROOT = os.environ.get("FW_FRAMEWORK_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
PKG_DIR = os.environ.get("FW_PKG_DIR") or ""

_PANEL_KEYS = ("max_hp", "max_mp", "atk", "def", "matk", "mdef", "spd", "crit", "dodge")


def _emit(obj: dict) -> None:
    sys.stdout.write(MARKER + json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _setup_paths(pkg_dir: str) -> None:
    """框架根（saintess_engine 所在）+ 游戏包根（它的 content 包）+ 包目录本身。"""
    for p in (os.path.join(pkg_dir, "content"), pkg_dir, FW_ROOT):
        if p and os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
    # 临时 DB：试跑全程不该碰真实库（保险栓，实测不创建文件）
    import tempfile
    os.environ.setdefault("GWEN_GAME_DB",
                          os.path.join(tempfile.mkdtemp(prefix="fw_sim_"), "game.db"))
    os.environ.setdefault("GWEN_TEST_MODE", "1")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    pkg_dir = payload.get("pkg_dir") or PKG_DIR
    if not pkg_dir or not os.path.isdir(pkg_dir):
        return _emit({"ok": False, "stage": "load", "message": f"包目录不存在：{pkg_dir}"}) or 0
    _setup_paths(pkg_dir)

    # ---- 载入游戏包（走引擎官方加载器：它以「包」的方式导入 content，包内相对导入可用）----
    try:
        from saintess_engine import package as pkg_loader
        info = pkg_loader.load(pkg_dir)
        if not info["ok"]:
            return _emit({"ok": False, "stage": "load", "message": "游戏包装配失败",
                          "traceback": "\n".join(info["errors"])}) or 0
    except Exception:
        return _emit({"ok": False, "stage": "load", "message": "游戏包装配失败",
                      "traceback": traceback.format_exc()}) or 0

    # ---- 引擎 ----
    try:
        from saintess_engine import Battle, make_actor
        from saintess_engine import version as _V
    except Exception:
        return _emit({"ok": False, "stage": "engine", "message": "引擎 import 失败",
                      "traceback": traceback.format_exc()}) or 0

    # ---- 版本门禁（设计约定：不满足要显式报错，不静默降级）----
    _req = ""
    try:
        with open(os.path.join(pkg_dir, "game.json"), encoding="utf-8") as _f:
            _req = str((json.load(_f) or {}).get("engine") or "")
    except Exception:                                     # 清单缺失/损坏：不拦（编辑器另有校验）
        _req = ""
    _ok, _note = _V.check(_req)
    if not _ok:
        return _emit({"ok": False, "stage": "version", "message": _note}) or 0

    skill = payload.get("skill") or {}
    skill_lv = int(payload.get("skill_lv") or 1)
    seed = payload.get("seed") or 1
    try:
        import random
        random.seed(int(seed))
    except Exception:
        pass

    # ---- 施法者 ----
    atk_spec = payload.get("attacker") or {}
    cls = atk_spec.get("class_name") or "战士"
    level = int(atk_spec.get("level") or 20)
    panel = dict(atk_spec.get("panel") or {})
    if not panel:
        panel = {"max_hp": 500, "max_mp": 200, "hp": 500, "mp": 200,
                 "atk": 100, "def": 50, "matk": 100, "mdef": 50, "spd": 60,
                 "crit": 0.05, "dodge": 0.0}
    _stats = {
        "hp": panel.get("hp", panel.get("max_hp", 500)),
        "max_hp": panel.get("max_hp", 500),
        "mp": panel.get("mp", panel.get("max_mp", 200)),
        "max_mp": panel.get("max_mp", 200),
        "atk": panel.get("atk", 100), "matk": panel.get("matk", 100),
        "spd": panel.get("spd", 60), "crit": panel.get("crit", 0.05),
        "dodge": panel.get("dodge", 0.0),
        # `def` / `mdef` 是面板字段名，但 `def` 是 Python 关键字 → 只能字典展开传
        "def": panel.get("def", 50), "mdef": panel.get("mdef", 50),
    }
    hero = make_actor("h1", "模拟者", "player", kind="player", human_controlled=True,
                      level=level, skills=[], **_stats)

    # ---- 目标（木桩：不还手）----
    d_spec = payload.get("defender") or {}
    d_hp = int(d_spec.get("hp") or 10_000_000)
    dummy = make_actor("d1", "木桩", "enemy", kind="monster",
                       level=int(d_spec.get("level") or level), hp=d_hp, max_hp=d_hp,
                       atk=0, matk=0, spd=0, crit=0.0, dodge=0.0, skills=[],
                       **{"def": int(d_spec.get("def") or 0),
                          "mdef": int(d_spec.get("mdef") or 0)})

    # ---- 把编辑器里的技能（可能还没保存）直接挂进施法者索引 ----
    if skill:
        name = skill.get("name") or "测试技能"
        info = dict(skill)
        info["name"] = name
        hero["skills"] = [name]
        hero["_skill_index"] = {name: info, skill.get("key") or name: info}

    try:
        b = Battle(btype="monster", sides={"player": [hero], "enemy": [dummy]})
    except Exception:
        return _emit({"ok": False, "stage": "engine", "message": "起战斗失败",
                      "traceback": traceback.format_exc()}) or 0

    events = []
    try:
        from saintess_engine import effect_triggers as ET
        _orig = ET.fire

        def _spy(battle, ev, ctx, logs=None):
            try:
                events.append({"event": ev, "ctx": {k: (v.get("name") if isinstance(v, dict) else v)
                                                    for k, v in (ctx or {}).items()
                                                    if k in ("actor", "target", "dmg", "skill")}})
            except Exception:
                pass
            return _orig(battle, ev, ctx, logs)
        ET.fire = _spy
    except Exception:
        pass

    hp0 = dummy["hp"]
    logs = []
    try:
        if skill:
            logs, _, _ = b.human_act("skill", skill.get("name") or "测试技能", actor=hero,
                                     target=dummy)
            if not logs:
                logs = [f"（技能 {skill.get('name')!r} 未产生日志 —— 检查 kind/公式字段）"]
        else:
            logs, _, _ = b.human_act("attack", None, actor=hero, target=dummy)
    except Exception:
        return _emit({"ok": False, "stage": "engine", "message": "施放失败",
                      "traceback": traceback.format_exc()}) or 0

    damage = max(0, hp0 - int(dummy["hp"]))
    return _emit({
        "ok": True, "damage": damage, "mp_used": max(0, panel.get("max_mp", 200) - int(hero.get("mp", 0))),
        "hp": {"target_before": hp0, "target_after": int(dummy["hp"])},
        "logs": logs, "events": events[-12:], "seed": seed,
        "attacker": {k: hero.get(k) for k in ("name", "atk", "matk", "spd", "mp")},
    }) or 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        _emit({"ok": False, "stage": "crash", "message": "子进程异常",
               "traceback": traceback.format_exc()})
        sys.exit(1)
