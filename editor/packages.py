# -*- coding: utf-8 -*-
"""游戏包（game package）IO —— 框架编辑器的数据层。

一个「游戏包」= 框架侧对一个游戏的完整描述，纯 JSON + 少量 py 装配代码：

    <pkg>/
      game.json                 包清单（manifest）：id/name/desc/engine 要求/域声明
      content/
        data/<域>.json         数据表（技能 / 职业 / 怪物 / 词条 / 物品）
        rules/<域>.json        声明表（effect_rules / passive_proc / mech_cash）
        apply.py               装配入口（内容 → 引擎方向；挂 hook + 规则表）
        mech/actions.py        机制动作（可选；@register_action 回调）

**为什么 JSON 为源**：编辑器要稳定读写；py dict 回写会毁注释与排版（见 EDITOR_SPEC
的方案 A）。`apply.py` 仍然可以是 py —— 那是「代码」，不是「数据」。

本模块**只做文件 IO 与结构校验**，不 import `saintess_engine`（编辑器主进程零引擎副作用；
真正跑战斗在子进程里，见 simulate.py）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FRAMEWORK_ROOT = os.path.dirname(HERE)
DEFAULT_GAMES_DIR = os.path.join(FRAMEWORK_ROOT, "games")

# ---------------- 域注册表（加一个域 = 加一行） ----------------
# kind: "data"（content/data/）| "rules"（content/rules/）
# schema: framework/schemas/<file>；primary: schema $defs 里「一条数据」的 def 名
DOMAINS = {
    "skills":   {"label": "技能",   "kind": "data",  "schema": "skill.schema.json",
                 "primary": "skill", "icon": "⚔️"},
    "classes":  {"label": "职业",   "kind": "data",  "schema": None, "primary": None,
                 "icon": "🧙"},
    "monsters": {"label": "怪物",   "kind": "data",  "schema": "monster.schema.json",
                 "primary": "monster_skill", "icon": "🐺"},
    "affixes":  {"label": "词条",   "kind": "data",  "schema": "affix.schema.json",
                 "primary": "affix", "icon": "💠"},
    "items":    {"label": "物品",   "kind": "data",  "schema": "item.schema.json",
                 "primary": "item", "icon": "🎒"},
    "effect_rules": {"label": "声明表", "kind": "rules", "schema": "effect_rules.schema.json",
                     "primary": "effect_rule", "icon": "📜"},
    "passive_proc": {"label": "被动声明", "kind": "rules",
                     "schema": "passive_proc.schema.json", "primary": "passive_proc",
                     "icon": "🌀"},
}


# ---------------- 包清单 ----------------
def manifest_path(pkg_dir: str) -> str:
    return os.path.join(pkg_dir, "game.json")


def domain_path(pkg_dir: str, dom: str) -> str:
    d = DOMAINS[dom]
    sub = "data" if d["kind"] == "data" else "rules"
    return os.path.join(pkg_dir, "content", sub, f"{dom}.json")


def read_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")
    os.replace(tmp, path)


def load_manifest(pkg_dir: str) -> dict:
    m = read_json(manifest_path(pkg_dir), None)
    if not isinstance(m, dict):
        return {}
    return m


def save_manifest(pkg_dir: str, m: dict) -> None:
    write_json(manifest_path(pkg_dir), m)


# ---------------- 发现 / 新建 ----------------
def ensure_games_dir(root_dir: str | None = None) -> str:
    """游戏包根目录（参数 > 环境变量 > framework/games/），不存在则创建。"""
    d = root_dir or os.environ.get("FW_GAMES_DIR") or DEFAULT_GAMES_DIR
    os.makedirs(d, exist_ok=True)
    return d


def list_packages(root_dir: str | None = None) -> list:
    root = ensure_games_dir(root_dir)
    out = []
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name)
        if not os.path.isdir(p) or not os.path.exists(manifest_path(p)):
            continue
        m = load_manifest(p)
        out.append({
            "id": m.get("id") or name,
            "dir": p,
            "name": m.get("name") or name,
            "desc": m.get("desc", ""),
            "engine": m.get("engine", ""),
            "domains": m.get("domains") or list(DOMAINS),
        })
    return out


def resolve_package(pkg_id: str, games_dir_: str | None = None) -> str | None:
    """按 id 找包目录（也接受绝对路径，便于「打开任意目录」）。"""
    if os.path.isabs(pkg_id) and os.path.exists(manifest_path(pkg_id)):
        return pkg_id
    root = ensure_games_dir(games_dir_)
    p = os.path.join(root, pkg_id)
    if os.path.exists(manifest_path(p)):
        return p
    for m in list_packages(games_dir_):
        if m["id"] == pkg_id:
            return m["dir"]
    return None


_ID_RE = re.compile(r"^[a-z][a-z0-9_\-]{1,40}$")


def create_package(pkg_id: str, name: str, desc: str = "",
                   domains=None, games_dir_: str | None = None) -> dict:
    """脚手架：建一个游戏包（含选中的域 + apply.py + 冒烟测试骨架）。"""
    if not _ID_RE.match(pkg_id or ""):
        raise ValueError("包 id 只能小写字母/数字/下划线/连字符，字母开头，2-41 字符")
    root = ensure_games_dir(games_dir_)
    pkg_dir = os.path.join(root, pkg_id)
    if os.path.exists(pkg_dir):
        raise ValueError(f"目标目录已存在：{pkg_dir}")
    doms = [d for d in (domains or list(DOMAINS)) if d in DOMAINS]
    for d in doms:
        write_json(domain_path(pkg_dir, d), {})
    os.makedirs(os.path.join(pkg_dir, "content", "mech"), exist_ok=True)
    write_json(manifest_path(pkg_dir), {
        "id": pkg_id, "name": name or pkg_id, "desc": desc,
        "engine": ">=0.1", "domains": doms,
        "entry": "content/apply.py",
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    _write_apply_scaffold(pkg_dir, pkg_id, name or pkg_id)
    return {"dir": pkg_dir, "id": pkg_id, "domains": doms}


def _write_apply_scaffold(pkg_dir: str, pkg_id: str, name: str) -> None:
    """生成装配入口骨架（内容 → 引擎方向；第三方照这个写自己的挂载）。"""
    body = f'''# -*- coding: utf-8 -*-
"""{name}（{pkg_id}）—— 内容装配入口（由框架编辑器脚手架生成）。

两件事，都幂等：
    install_engine()            全局：把本游戏的公式/面板/技能表/kind 词表/声明表挂进引擎
    apply_game_content(actor)   单个 actor：把资源渠道/机制/被动翻成 triggers

方向只有一个：**内容 → 引擎**。框架不 import 本包，也不认识本包的表。
数据源是 content/data/*.json 与 content/rules/*.json（编辑器直接改这些文件）。
"""
from __future__ import annotations

import json
import os

import saintess_engine.config as config   # 引擎公开注入面

_HERE = os.path.dirname(os.path.abspath(__file__))
_MOUNTED = False


def _load(name: str, rules: bool = False):
    sub = "rules" if rules else "data"
    p = os.path.join(_HERE, sub, f"{{name}}.json")
    if not os.path.exists(p):
        return {{}}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _lazy_mount():
    """引擎首次访问未装配 hook 时的自举（框架只认这一个回调）。"""
    install_engine()


def install_engine() -> None:
    """把本游戏配置挂进引擎（幂等）。表为空时挂空表（引擎按零默认值处理）。"""
    global _MOUNTED
    if _MOUNTED:
        return
    import saintess_engine.battle.formulas as formulas

    config.register_hook_provider(_lazy_mount)
    config.mount(
        formulas=formulas,                    # 引擎自带通用公式模块
        effect_rules=_load("effect_rules", True),   # 状态/资源声明表
        effect_actions=_load("effect_actions", True),
        passive_proc=_load("passive_proc", True),
    )
    _MOUNTED = True


def apply_game_content(actor: dict) -> dict:
    """把本游戏内容挂到 actor 上（幂等）。"""
    if not isinstance(actor, dict):
        return actor
    install_engine()
    return actor
'''
    p = os.path.join(pkg_dir, "content", "apply.py")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)


# ---------------- 条目 CRUD ----------------
def list_entries(pkg_dir: str, dom: str) -> dict:
    """返回 {entries: [{key, name, kind, ...}], count}。"""
    if dom not in DOMAINS:
        raise KeyError(dom)
    table = read_json(domain_path(pkg_dir, dom), {})
    if not isinstance(table, dict):
        table = {}
    rows = []
    for k, v in table.items():
        if not isinstance(v, dict):
            continue
        rows.append({
            "key": k,
            "name": v.get("name") or k,
            "kind": v.get("kind") or v.get("type") or "",
            "lv": v.get("lv"),
            "summary": (v.get("desc") or "")[:60],
        })
    rows.sort(key=lambda r: (str(r.get("kind") or ""), str(r["name"])))
    return {"domain": dom, "count": len(rows), "entries": rows}


def get_entry(pkg_dir: str, dom: str, key: str):
    table = read_json(domain_path(pkg_dir, dom), {})
    if not isinstance(table, dict) or key not in table:
        return None
    return table[key]


def put_entry(pkg_dir: str, dom: str, key: str, data: dict) -> None:
    table = read_json(domain_path(pkg_dir, dom), {})
    if not isinstance(table, dict):
        table = {}
    table[key] = data
    write_json(domain_path(pkg_dir, dom), table)


def delete_entry(pkg_dir: str, dom: str, key: str) -> bool:
    table = read_json(domain_path(pkg_dir, dom), {})
    if not isinstance(table, dict) or key not in table:
        return False
    table.pop(key)
    write_json(domain_path(pkg_dir, dom), table)
    return True


def domain_status(pkg_dir: str, dom: str) -> dict:
    """域概览：条目数 + 校验结果（供 tab 上的徽标）。"""
    st = {"domain": dom, "count": 0, "invalid": [], "ok": True}
    try:
        st.update({k: v for k, v in list_entries(pkg_dir, dom).items() if k == "count"})
    except KeyError:
        return st
    from . import validate as V          # 同目录模块
    table = read_json(domain_path(pkg_dir, dom), {})
    for k, v in (table or {}).items():
        if not isinstance(v, dict):
            continue
        errs = V.validate_entry(dom, v)
        if errs:
            st["invalid"].append({"key": k, "errors": errs})
    st["ok"] = not st["invalid"]
    return st


def package_overview(pkg_dir: str) -> dict:
    m = load_manifest(pkg_dir)
    doms = m.get("domains") or list(DOMAINS)
    return {
        "manifest": m,
        "engine_check": engine_check(m),
        "domains": [{"id": d, **{k: DOMAINS[d][k] for k in ("label", "icon", "kind")},
                     **domain_status(pkg_dir, d)}
                    for d in doms if d in DOMAINS],
    }


def engine_check(manifest: dict) -> dict:
    """校验 game.json 声明的 `engine` 版本要求（设计约定：不满足要显式报错，不静默降级）。

    框架不在 sys.path 时（例如纯文件操作场景）返回 {ok: None}，不阻断。
    """
    req = str((manifest or {}).get("engine") or "")
    try:
        _root = FRAMEWORK_ROOT
        if _root not in os.sys.path:
            os.sys.path.insert(0, _root)
        from saintess_engine import version as V          # noqa: PLC0415
    except Exception as e:                                # noqa: BLE001
        return {"ok": None, "requirement": req, "version": "", "note": f"未加载框架版本：{e}"}
    ok, note = V.check(req)
    return {"ok": ok, "requirement": req, "version": V.__version__, "note": note}
