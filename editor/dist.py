# -*- coding: utf-8 -*-
"""游戏包导出 / 导入（E5：分发）—— 让一个包能被第三方拿走并跑起来。

导出物（`export_zip`）
---------------------
zip 布局 = **包内容在 zip 根部**（`game.json` 就在根），第三方解压即用：

    my_game-20260911.zip
      game.json                 包清单（含 engine 版本要求）
      content/data/*.json       数据表
      content/rules/*.json      声明表
      content/apply.py          装配入口（内容 → 引擎）
      content/mech/actions.py   机制动作（可选）
      DIST_README.md            ← 导出附赠：这是什么 / 怎么跑 / 引擎要求（**不参与导入**）
      DIST_smoke.py             ← 导出附赠：一条命令跑通一场最小战斗（**不参与导入**）

zip 的 **comment** 里另放一份机读元数据（导入时不产生任何额外文件）。

导入（`import_zip`）的四道闸
---------------------------
1. **zip slip**：绝对路径 / `..` / 符号链接一律拒绝（一个都不写盘）
2. **zip bomb**：条目数与解压总量有上限
3. **清单合规**：`game.json` 必须是合法 JSON + `id` 合法（与新建包同一条正则）
4. **引擎版本**：`engine` 要求不满足 → 默认**拒绝**（设计约定：不静默降级）；`force=True` 才放行并留警告

冲突策略：目标目录已存在 → 拒绝（`overwrite=True` 才覆盖）。**只写游戏包目录之内**。

两种 zip 布局都吃：根有 `game.json`，或唯一顶层目录里有 `game.json`（GitHub 下载风格）。
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import time
import zipfile

from . import packages as PK

FORMAT = "saintess-engine-game-package"
FORMAT_VERSION = 1
MAX_ENTRIES = 2000
MAX_TOTAL_UNCOMPRESSED = 64 * 1024 * 1024

# 导出时排除的东西（缓存 / 库文件 / 版本控制 / 临时件）
_SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules", ".idea", ".vscode"}
_SKIP_EXT = (".pyc", ".pyo", ".pyd", ".db", ".sqlite", ".sqlite3", ".log")
# 导出附赠件：只在 zip 里存在，导入时不落盘（前缀判据，见 _EXPORT_ONLY_RE）
EXPORT_ONLY = ("DIST_README.md", "DIST_smoke.py")
_EXPORT_ONLY_RE = re.compile(r"^DIST_", re.I)

# ── 渲染扩展面风险标注（第 3 层批 4；设计稿 §7.2 T11 / §9「批 4」/ §8.2 G5-3）────────────
# 为什么这件事值得在**导入/导出报告**里做：包内 `editor/` 会随 zip 传播到第三方（F10），
# 而「请求跑代码 / 请求注入 JS」是**该包自己声明的**风险面。导入方在**落盘之后**就该看到。
RENDER_DIR_REL = "editor/render"
RENDER_MAX_FILES = 128                    # 与 `editor/render_decl.py:MAX_FILES` 同口径
RENDER_MAX_FILE_BYTES = 256 * 1024        # 与 `editor/render_decl.py:MAX_FILE_BYTES` 同口径
RENDER_LIST_MAX = 64                      # 报告里最多列几项（避免报告被包刷爆）
#: 有渲染扩展面时写进「导入报告」warnings 与 DIST_README 的那一行 —— **标红**：一眼可见
RENDER_RED_NOTE = ("⚠️ 请注意：该包声明了「渲染扩展面」（要求执行代码 / 注入 JS）—— "
                   "内容来自包，属不可信输入；请先看清包里的 editor/render/ 再决定是否使用")


def _iter_files(pkg_dir: str):
    """包内待打包的文件（相对路径，POSIX 风格），已按排除规则过滤。"""
    out = []
    for root, dirs, files in os.walk(pkg_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for f in sorted(files):
            if f.endswith(_SKIP_EXT) or f.endswith(".tmp") or f.startswith("~"):
                continue
            if _EXPORT_ONLY_RE.match(f) and os.path.dirname(root) == pkg_dir:
                continue                                   # 老包里的 DIST_* 残留
            p = os.path.join(root, f)
            rel = os.path.relpath(p, pkg_dir).replace("\\", "/")
            out.append((p, rel))
    out.sort(key=lambda x: x[1])
    return out


# ─────────────────────────────────────────────────────────── 附带件（导出时生成）
_README = """# {name}（{pkg_id}）—— 游戏包

> 由 **saintess_engine 框架编辑器** 导出（{exported_at}）。这是一个**游戏包（game package）**，
> 不是引擎本体：它只描述「这个游戏内容长什么样」，跑起来需要一个 saintess_engine 引擎。

## 引擎要求

| 项 | 值 |
|---|---|
| `game.json` 里声明的要求 | `{req}` |
| 导出时的引擎版本 | `{ver}` |
| 版本检查结论 | {verdict} |

## 怎么跑

```bash
# ① 让引擎能被 import（二选一）
#    a) 已安装：pip install -e /path/to/framework-engine
#    b) 用环境变量指向框架仓根目录：
export FW_FRAMEWORK_ROOT=/path/to/framework-engine      # Windows: set FW_FRAMEWORK_ROOT=...

# ② 一条命令跑通一场最小战斗（本包自带，无需第三方依赖）
python DIST_smoke.py
```

或在你自己的代码里装配（**推荐**：用引擎官方的包加载器 —— 它会以「包」的方式导入 `content`，
所以包里写 `from .mech import …` 这类相对导入才可用）：

```python
import sys; sys.path.insert(0, ".")          # 本包目录
from saintess_engine.package import probe_stack
info = probe_stack(".")                 # game.json → 版本门禁 → 加载包栈（不抛，错误在 info["errors"]）
assert info["ok"], info["errors"]
stack = info["stack"]                   # PackageStack：扩展包（拓扑序）+ 数据包
        from ext_combat import Battle, make_actor
```

## 内容清单

| 域 | 条目数 |
|---|---|
{domains}

{render_section}
## 改这个包

用框架编辑器打开它（`python editor/server.py` → 左上角包名 → 导入 zip），
或者直接改 `content/*.json`（JSON 是源；`content/apply.py` 是装配代码）。

> 引擎只认两条：`content/apply.py` 提供 `install_engine()`；`game.json` 的 `engine` 字段声明所需版本。
"""

_SMOKE = '''# -*- coding: utf-8 -*-
"""DIST_smoke.py —— 一条命令验证这个游戏包能在当前环境跑起来（导出附赠，不属于包内容）。

    python DIST_smoke.py

做四件事：把框架放进 import 路径 → 调本包的 apply.install_engine()
        → 补齐「能打出伤害」的最小装配（**仅当包自己没装配时**，只影响本进程）
        → 起一场最小战斗并打印日志。
退出码 0 = 跑通（产生了伤害）；1 = 没跑通（附原因）。
"""
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))


def _setup_paths():
    """框架根 + 本包 content（第三方拿到包后通常只需装好 saintess_engine）。"""
    cands = [os.environ.get("FW_FRAMEWORK_ROOT") or "", HERE, os.path.dirname(HERE)]
    for p in cands:
        if p and os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
    sys.path.insert(0, os.path.join(HERE, "content"))


def _ensure_minimum_assembly():
    """包没装配「最小可打」三件套时补上 —— 否则任何包都打不出伤害，冒烟就失去意义。

    ⚠ 这不是包的内容：只在本次冒烟进程里临时挂，不改包的任何文件。
    真正的内容侧装配应该写在 content/apply.py 里（本包是否已装配由 get_hook 判断）。
    """
    from saintess_engine import config as cfg
    from ext_combat.battle import formulas as F
    add = {}
    if not cfg.get_hook("formulas"):
        add["formulas"] = F
    if not cfg.get_hook("kinds"):
        add["kinds"] = {"phys": "phys", "magi": "magi", "true": "true",
                        "heal": "heal", "buff": "buff"}
    if not cfg.get_hook("basic_fallback"):
        add["basic_fallback"] = {"name": "普攻", "kind": "phys", "exprs": ["atk*1.0"]}
    if not cfg.get_hook("skill_flat_fn"):
        add["skill_flat_fn"] = lambda: {"SKILL_FLAT_BASE": 12, "SKILL_FLAT_PER_PLAYER_LV": 1,
                                        "SKILL_FLAT_PER_SKILL_LV": 2}
    if not cfg.get_hook("formula_skeleton_fn"):
        add["formula_skeleton_fn"] = lambda: {"skill_growth": {
            "power_per_lv_divisor": 100, "buff_turns_base": 3, "buff_turns_per_lv": 1,
            "cond_default": 0.05, "mech_default_div": 2,
            "lifesteal_default": 0.2, "lifesteal_per_lv_divisor": 100},
            "skill_learn_cost": {"divisor": 6, "base": 2}}
    if add:
        cfg.mount(**add)
        print("[i] 本包未装配 %s —— 冒烟脚本临时补了最小装配（不改包文件）"
              % ", ".join(sorted(add)))


def main():
    _setup_paths()
    try:
        # 用**引擎官方的包加载器**：它把 `content` 当**包**导入 → 包内 `from .mech import …`
        # 这类相对导入可用。
        from saintess_engine.package import probe_stack       # noqa: PLC0415
        info = probe_stack(HERE, install=True)
        if not info["ok"]:
            print("[x] 装配失败（content/apply.py）：")
            for e in info["errors"]:
                print("   ", e)
            return 1
        if len(info.get("plan") or []) > 1:
            print("[i] 本包栈：%s" % " → ".join(p["id"] for p in info["plan"]))
    except Exception:
        print("[x] 引擎 import 失败 —— 先装好 saintess_engine，"
              "或用 FW_FRAMEWORK_ROOT 指向框架仓根目录。")
        traceback.print_exc()
        return 1
    try:
        from saintess_engine import version                        # noqa: PLC0415
        from ext_combat import Battle, make_actor                  # noqa: PLC0415
        from saintess_engine import config as cfg                  # noqa: PLC0415
    except Exception:
        print("[x] 引擎 import 失败 —— 先装好 saintess_engine，"
              "或用 FW_FRAMEWORK_ROOT 指向框架仓根目录。")
        traceback.print_exc()
        return 1

    with open(os.path.join(HERE, "game.json"), encoding="utf-8") as f:
        man = json.load(f)
    print("[i] 包 %s（%s）· 引擎 %s · 声明要求 %s"
          % (man.get("id"), man.get("name"), version.__version__, man.get("engine") or "—"))
    print("[i] 域：%s" % ", ".join(man.get("domains") or []))
    _ensure_minimum_assembly()

    hero = make_actor("h1", "冒烟者", "player", kind="player", human_controlled=True,
                      level=10, skills=[], hp=300, max_hp=300, mp=100, max_mp=100,
                      atk=60, matk=60, spd=60, crit=0.0, dodge=0.0,
                      **{"def": 20, "mdef": 20})
    dummy = make_actor("d1", "木桩", "enemy", kind="monster", level=10,
                       hp=5000, max_hp=5000, atk=0, matk=0, spd=0, crit=0.0, dodge=0.0,
                       skills=[], **{"def": 0, "mdef": 0})
    try:
        b = Battle(btype="monster", sides={"player": [hero], "enemy": [dummy]})
        logs, _ended, _who = b.human_act("attack", None, actor=hero, target=dummy)
    except Exception:
        print("[x] 起战斗 / 出手失败：")
        traceback.print_exc()
        return 1

    for line in (logs or [])[:12]:
        print("    " + str(line))
    dmg = 5000 - int(dummy["hp"])
    if dmg <= 0:
        print("[x] 没产生伤害 —— 检查 content/data/*.json 与 content/apply.py 的装配")
        return 1
    print("[√] 跑通：普攻造成 %d 点伤害" % dmg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _domain_table(pkg_dir: str) -> tuple:
    """README 的域清单 + 校验汇总（域表 = 该包的**有效域表**：内置 + 包自带声明）。"""
    rows, invalid_total, total = [], 0, 0
    domains, _warns = PK.effective_domains(pkg_dir)
    doms = PK.load_manifest(pkg_dir).get("domains") or list(domains)
    for d in doms:
        if d not in domains:
            continue
        st = PK.domain_status(pkg_dir, d, domains)
        total += st["count"]
        invalid_total += len(st["invalid"])
        label = domains[d]["label"]
        bad = f"⚠ {len(st['invalid'])} 条不合 schema" if st["invalid"] else "✅"
        rows.append(f"| {label}（`{d}`） | {st['count']} | {bad} |")
    return rows, {"entries": total, "invalid": invalid_total, "domains": len(rows)}


# ─────────────────────────────────────── 渲染扩展面（「该包请求执行代码吗」）—— 批 4
def render_extension_surface(pkg_dir: str) -> dict:
    """扫「该包的**渲染扩展面**」→ 导入/导出报告里那句小结（设计稿 §7.2 T11 / §8.2 G5-3）。

    判据**只有三条**（都只看**文件名 / 一个布尔键**，与 `editor/render.py` 的
    存在性口径一字不差）：

    1. `editor/render/<域>.html.js` —— 包自带的 **JS**（设计 §5.4 路径 B：iframe 只读预览；
       默认关，但仍属「请我跑代码」）；
    2. `editor/render/<域>.py` —— 包自带的**受限渲染函数**（设计 §3.7/§5.3 代码档；
       ★ **批 3 已砍**：本仓只做**存在性识别 + 标红 + 告警**，**绝不 import / 绝不执行**）；
    3. `editor/render/<域>.json` 里 `"$allow_code": true` —— 代码档**开关**（同上，只记不发车）；
       兼容历史形态 `editor/render.json` 的 `{域: {…}}`（与 `editor/render.py` 同款兼容）。

    **绝不执行、绝不 import 包内任何文件**（只 `os.stat` + `json.loads` 一个声明文件）；
    本函数**永不抛**（坏 JSON / 读不了 → 那条判据静默跳过，判据是"同一文件"）。

    返回（机读；键序稳定）::

        {"ok": bool,                # False = 包目录不可用（读不了 → 报告里写「未扫」）
         "red": bool,               # ★ 是否含**渲染扩展面**（True = 该报告要标红）
         "html_js": [rel, …],       # `editor/render/*.html.js`
         "code_py": [rel, …],       # `editor/render/*.py`
         "decl_allow_code": [rel, …],   # 声明里 `$allow_code: true`
         "reasons": [给用户看的理由],
         "message": str,            # 一行小结（**没扩展面时也要有话**，不许静默）
         "skipped": {"too_many": n, "too_big": n}}   # 被上限挡掉、未参与判定的文件数
    """
    root = str(pkg_dir or "")
    out = {"ok": False, "red": False, "html_js": [], "code_py": [], "decl_allow_code": [],
           "reasons": [], "message": "", "skipped": {"too_many": 0, "too_big": 0}}
    if not root or not os.path.isdir(root):
        out["message"] = "渲染扩展面：包目录不可用 —— 未扫（**未判定**，不等于没有）"
        return out
    out["ok"] = True
    d = os.path.join(root, *RENDER_DIR_REL.split("/"))
    html_js: list = []
    code_py: list = []
    decl_allow: list = []
    skipped = {"too_many": 0, "too_big": 0}
    if not os.path.isdir(d):
        out["message"] = ('渲染扩展面：**没有** —— 该包未声明 `editor/render/`'
                          '（更不可能请求执行代码 / 注入 JS）')
        return out
    try:
        names = sorted(os.listdir(d))
    except OSError:
        out["ok"] = False
        out["message"] = f"渲染扩展面：`{RENDER_DIR_REL}/` 读不了 —— 未扫（**未判定**）"
        return out
    decls: list = []
    for n in names:
        full = os.path.join(d, n)
        if not os.path.isfile(full):
            continue
        rel = f"{RENDER_DIR_REL}/{n}"
        lname = n.lower()
        if lname.endswith(".html.js"):
            html_js.append(rel)
            continue
        if lname.endswith(".py"):
            code_py.append(rel)
            continue
        if not (n.endswith(".json") and n != "$schema.json"):
            continue                                  # `$schema.json` 是元 schema，不是域声明
        if len(decls) >= RENDER_MAX_FILES:
            skipped["too_many"] += 1
            continue
        try:
            if os.path.getsize(full) > RENDER_MAX_FILE_BYTES:
                skipped["too_big"] += 1
                continue
        except OSError:
            continue
        decls.append((full, rel))
    for full, rel in decls:
        try:
            with open(full, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            continue                                  # 坏声明：那条判据静默跳过（同一文件）
        blobs = []
        if isinstance(raw, dict) and raw.get("$version") in (None, 1):
            blobs.append(raw)                         # 每域文件形态：`$version` 在声明里
        if isinstance(raw, dict):                     # 历史形态：`{域: {…}}`（含 `$version` 键）
            blobs.extend(v for v in raw.values() if isinstance(v, dict))
        if any(b.get("$allow_code") is True for b in blobs):
            decl_allow.append(rel)
    for lst in (html_js, code_py, decl_allow):
        lst.sort()
    if html_js:
        out["reasons"].append(
            f"含 {len(html_js)} 个 `.html.js`（包自带 JS —— 若被加载即在编辑器里执行包代码）")
    if code_py:
        out["reasons"].append(
            f"含 {len(code_py)} 个渲染函数 `.py`（代码档；★ 本批只识别不执行，但**包在请求跑代码**）")
    if decl_allow:
        out["reasons"].append(f"声明里 `$allow_code: true`（{len(decl_allow)} 处，代码档开关开着）")
    if skipped["too_many"] or skipped["too_big"]:
        out["reasons"].append(
            f"另有 {skipped['too_many']} 个（超文件数上限 {RENDER_MAX_FILES}）"
            f"/ {skipped['too_big']} 个（超 {RENDER_MAX_FILE_BYTES // 1024} KB）声明文件**未参与判定**")
    out["html_js"] = html_js[:RENDER_LIST_MAX]
    out["code_py"] = code_py[:RENDER_LIST_MAX]
    out["decl_allow_code"] = decl_allow[:RENDER_LIST_MAX]
    out["red"] = bool(html_js or code_py or decl_allow)
    hits = len(html_js) + len(code_py) + len(decl_allow)
    detail = "；".join(out["reasons"])
    # ⚠ 小结的判据是 **hits / reasons**，不是 `red`：这样「文案说没有」与「报告列了东西」
    #   永远不可能自相矛盾（`red` 只是给调用方的一个布尔便利键）。
    if hits:
        out["message"] = (f"⚠️ 该包含渲染扩展面（{len(html_js)} 个 .html.js / "
                          f"{len(code_py)} 个 .py / {len(decl_allow)} 处 $allow_code:true）—— "
                          f"{detail}")
    elif skipped["too_many"] or skipped["too_big"]:
        out["message"] = (f"渲染扩展面：**本次未扫全**（{detail}）—— 属**未判定**，"
                          "不保证没有（请缩包或手工核对）")
    else:
        out["message"] = ("渲染扩展面：**没有** —— 该包只声明了纯数据渲染"
                          f"（`{RENDER_DIR_REL}/*.json`），不含 `.html.js` / `.py` / "
                          "`$allow_code:true`")
    return out


def _render_risk_readme_lines(surface: dict) -> list:
    """DIST_README 里的风险小结：**红色包一行不少；默认包 `[]`**（README 逐字节不变）。"""
    if not surface.get("ok"):
        return ["## ⚠️ 渲染扩展面（未扫）", "",
                f"> {surface.get('message') or '包目录不可用 —— 未扫'}", ""]
    lines = ["## 渲染扩展面", "",
             f"> {surface.get('message') or '—'}", ""]
    if not surface.get("red"):
        return lines                              # 没扩展面：一行小结 + 空行（**不许静默**）
    items = list(surface.get("html_js") or []) + list(surface.get("code_py") or []) \
        + list(surface.get("decl_allow_code") or [])
    lines += [f"### ⚠️ 该包请求执行代码（渲染扩展面）", "",
              f"> {RENDER_RED_NOTE}", "",
              *[f"* `{p}`" for p in items[:RENDER_LIST_MAX]],
              *([f"* …还有 {len(items) - RENDER_LIST_MAX} 项（见导入/导出报告）"]
                if len(items) > RENDER_LIST_MAX else []),
              "",
              "**怎么处理**：本框架**默认不执行**包内代码（代码档已砍；这些文件只被"
              "「数一下存在性」，绝不 import / 绝不执行）；但「包请求过」这件事本身是你"
              "决定用不用它的依据。", ""]
    return lines


# ───────────────────────────────────────────────────────────────────── 导出
def export_zip(pkg_dir: str, out_path: str | None = None, *, generated_at: str | None = None) -> dict:
    """打包游戏包 → {ok, path, bytes, files, manifest, engine, validation}。"""
    man = PK.load_manifest(pkg_dir)
    pkg_id = man.get("id") or os.path.basename(os.path.normpath(pkg_dir))
    if not pkg_id:
        return {"ok": False, "message": "包清单缺少 id，无法导出"}
    ec = PK.engine_check(man)
    rows, val = _domain_table(pkg_dir)
    # ★ 批 4：渲染扩展面（只做存在性识别 —— **绝不执行包内任何代码**）
    surface = render_extension_surface(pkg_dir)
    stamp = generated_at or time.strftime("%Y-%m-%d %H:%M:%S")
    if out_path is None:
        out_path = os.path.join(os.path.dirname(os.path.normpath(pkg_dir)),
                                f"{pkg_id}-{time.strftime('%Y%m%d-%H%M')}.zip")

    verdict = {True: "✅ 满足", False: "❌ 不满足", None: "⚠ 未能判定（框架不在 import 路径）"}.get(ec.get("ok"), "—")
    readme = _README.format(
        name=man.get("name") or pkg_id, pkg_id=pkg_id, exported_at=stamp,
        req=ec.get("requirement") or "（未声明）", ver=ec.get("version") or "—",
        verdict=verdict, domains="\n".join(rows) or "| （空包） | 0 | ✅ |",
        render_section="\n".join(_render_risk_readme_lines(surface)))

    files = _iter_files(pkg_dir)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for abs_p, rel in files:
            z.write(abs_p, rel)
        z.writestr("DIST_README.md", readme)
        z.writestr("DIST_smoke.py", _SMOKE)
        z.comment = json.dumps({
            "format": FORMAT, "format_version": FORMAT_VERSION,
            "exported_at": stamp, "id": pkg_id, "name": man.get("name") or pkg_id,
            "engine_requirement": ec.get("requirement") or "",
            "engine_version_at_export": ec.get("version") or "",
            "engine_ok": ec.get("ok"), "generator": "framework-editor",
            "file_count": len(files), "validation": val,
            "render_surface": surface,               # ★ 批 4：机读小结也进 zip comment
        }, ensure_ascii=False).encode("utf-8")
    data = buf.getvalue()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)
    return {"ok": True, "path": out_path, "bytes": len(data),
            "files": len(files) + len(EXPORT_ONLY), "content_files": len(files),
            "manifest": man, "engine": ec, "validation": val,
            "name": f"{pkg_id}.zip",
            "render_surface": surface}               # ★ 批 4：导出报告的小结


# ───────────────────────────────────────────────────────────────────── 检查
def _safe_members(z: zipfile.ZipFile) -> tuple:
    """挑出可安全落盘的条目；返回 (ok_list, rejected)。三道判据：绝对路径 / `..` / 符号链接。"""
    ok, bad = [], []
    for zi in z.infolist():
        raw = zi.filename.replace("\\", "/")
        name = raw.lstrip("/")
        parts = [p for p in name.split("/") if p not in ("", ".")]
        is_link = (zi.external_attr >> 16) & 0o170000 == 0o120000
        if (raw.startswith("/") or re.match(r"^[A-Za-z]:", raw) or ".." in parts
                or is_link or not parts):
            bad.append(zi.filename)
            continue
        ok.append((zi, "/".join(parts)))
    return ok, bad


def inspect_zip(path: str) -> dict:
    """看一眼 zip：格式 / 元数据 / 顶层布局 / 文件数（不写盘）。"""
    if not os.path.isfile(path):
        return {"ok": False, "message": f"文件不存在：{path}"}
    try:
        with zipfile.ZipFile(path) as z:
            members, bad = _safe_members(z)
            if bad:
                return {"ok": False, "unsafe": bad,
                        "message": f"zip 含不安全路径（绝对路径 / 上级目录 / 符号链接）：{bad[:3]}"}
            names = [n for _zi, n in members if not n.endswith("/")]
            total = sum(zi.file_size for zi, _n in members)
            if len(members) > MAX_ENTRIES or total > MAX_TOTAL_UNCOMPRESSED:
                return {"ok": False, "message": f"zip 过大（{len(members)} 项 / {total} 字节），已拒绝"}
            meta = {}
            if z.comment:
                try:
                    meta = json.loads(z.comment.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    meta = {}
            root = _find_package_root(names)
            return {"ok": True, "meta": meta, "entries": len(names),
                    "total_bytes": total, "root": root, "names": names[:80],
                    "manifest_inside": (f"{root}game.json".replace("//", "/") in names)}
    except zipfile.BadZipFile as e:
        return {"ok": False, "message": f"不是有效的 zip：{e}"}
    except OSError as e:
        return {"ok": False, "message": f"读取失败：{e}"}


def _find_package_root(names: list) -> str:
    """zip 里的包根前缀（'' = 根目录；`my_game/` = GitHub 风格的单层目录）。"""
    if "game.json" in names:
        return ""
    tops = {n.split("/")[0] for n in names if "/" in n}
    if len(tops) == 1:
        t = tops.pop()
        if f"{t}/game.json" in names:
            return t + "/"
    return ""


# ───────────────────────────────────────────────────────────────────── 导入
def import_zip(path: str, games_dir_: str | None = None, *,
               overwrite: bool = False, force: bool = False) -> dict:
    """把 zip 解成游戏包 → {ok, id, dir, report} / {ok: False, message, code}。"""
    info = inspect_zip(path)
    if not info.get("ok"):
        return {**info, "code": "bad_zip"}
    root = info["root"]
    if f"{root}game.json" not in info["names"] and not info["manifest_inside"]:
        return {"ok": False, "code": "no_manifest",
                "message": "zip 里找不到 game.json（既不在根，也不在唯一的顶层目录里）"}

    # 先在临时目录解包 + 验证，全部通过才搬进 games/（失败不留垃圾）
    root_dir = PK.ensure_games_dir(games_dir_)
    tmp = os.path.join(root_dir, f".import_{os.getpid()}_{int(time.time())}")
    try:
        with zipfile.ZipFile(path) as z:
            for zi, name in _safe_members(z)[0]:
                if name.endswith("/"):
                    continue
                rel = name[len(root):] if root and name.startswith(root) else name
                if _EXPORT_ONLY_RE.match(rel):          # 导出附赠件不落盘
                    continue
                dst = os.path.normpath(os.path.join(tmp, *rel.split("/")))
                if not dst.startswith(os.path.normpath(tmp)):
                    return {"ok": False, "code": "unsafe", "message": f"路径越界：{name}"}
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with z.open(zi) as src, open(dst, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 16)

        man_path = PK.manifest_path(tmp)
        if not os.path.isfile(man_path):
            return {"ok": False, "code": "no_manifest",
                    "message": "解包后没有 game.json —— 这个 zip 不像游戏包"}
        try:
            with open(man_path, encoding="utf-8") as f:
                man = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            return {"ok": False, "code": "bad_manifest", "message": f"game.json 不是合法 JSON：{e}"}
        if not isinstance(man, dict):
            return {"ok": False, "code": "bad_manifest", "message": "game.json 顶层必须是对象"}
        pkg_id = str(man.get("id") or "")
        if not PK._ID_RE.match(pkg_id):
            return {"ok": False, "code": "bad_id",
                    "message": f"包 id 不合规：{pkg_id!r}（只能小写字母/数字/下划线/连字符，字母开头）"}

        ec = PK.engine_check(man)
        if ec.get("ok") is False and not force:
            return {"ok": False, "code": "engine_mismatch",
                    "message": f"引擎版本不满足：包要求 {ec.get('requirement')}，当前 {ec.get('version')}"
                               f"（{ec.get('note')}）—— 需强制导入请确认",
                    "engine": ec, "id": pkg_id}

        dest = os.path.join(root_dir, pkg_id)
        if os.path.exists(dest) and not overwrite:
            return {"ok": False, "code": "exists",
                    "message": f"已存在同名包：{pkg_id}", "id": pkg_id}
        if os.path.exists(dest):
            shutil.rmtree(dest, ignore_errors=True)
        os.replace(tmp, dest)
        tmp = ""                                        # 搬走了，别再删
    finally:
        if tmp and os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)

    # 导入后体检：条目数 + 不合 schema 的条目（**不阻断**，让编辑器里能看到）
    rows, val = _domain_table(dest)
    # ★ 批 4：渲染扩展面小结（导入报告）—— 含 `.html.js` / 代码档开关 → **标红**，且进 warnings。
    #   纯存在性识别：**绝不 import / 绝不执行**包内任何文件。
    surface = render_extension_surface(dest)
    warns = [] if ec.get("ok") is not False else ["引擎版本要求不满足（已强制导入）"]
    if surface.get("red"):
        warns.append(RENDER_RED_NOTE)
        warns.append(surface["message"])
    elif not surface.get("ok"):
        warns.append(surface["message"])          # 未扫也算风险可见（未判定 ≠ 没有）
    if val["invalid"]:
        warns.append(f"{val['invalid']} 个条目不合 schema，可在编辑器里修")
    return {
        "ok": True, "id": os.path.basename(dest), "dir": dest,
        "manifest": PK.load_manifest(dest), "engine": ec, "validation": val,
        "warnings": warns,
        "report": {"files": info["entries"], "domains": val["domains"], "entries": val["entries"]},
        "meta": info.get("meta") or {},
        "render_surface": surface,                # ★ 批 4：导入报告的渲染扩展面小结
    }


def export_bytes(pkg_dir: str, *, generated_at: str | None = None) -> tuple:
    """导出到内存（HTTP 下载直发，不落盘）→ (data, filename)。"""
    import tempfile
    tmpd = tempfile.mkdtemp(prefix="fw_dist_")
    try:
        r = export_zip(pkg_dir, os.path.join(tmpd, "pkg.zip"), generated_at=generated_at)
        if not r.get("ok"):
            return None, r.get("message") or "导出失败"
        with open(r["path"], "rb") as f:
            data = f.read()
        pkg_id = (r.get("manifest") or {}).get("id") or "package"
        return data, f"{pkg_id}-{time.strftime('%Y%m%d-%H%M')}.zip"
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
