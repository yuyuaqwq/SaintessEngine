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

或在你自己的代码里装配：

```python
import sys; sys.path.insert(0, ".")          # 本包目录
sys.path.insert(0, "./content")
import apply                                  # content/apply.py
apply.install_engine()                        # 内容 → 引擎（幂等）
from saintess_engine import Battle, make_actor
```

## 内容清单

| 域 | 条目数 |
|---|---|
{domains}

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
    from saintess_engine import formulas as F
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
        import apply as pkg_apply                 # noqa: PLC0415  content/apply.py
        pkg_apply.install_engine()
    except Exception:
        print("[x] 装配失败（content/apply.py）：")
        traceback.print_exc()
        return 1
    try:
        from saintess_engine import Battle, make_actor, version   # noqa: PLC0415
        from saintess_engine import config as cfg                 # noqa: PLC0415
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
    """README 的域清单 + 校验汇总。"""
    rows, invalid_total, total = [], 0, 0
    doms = PK.load_manifest(pkg_dir).get("domains") or list(PK.DOMAINS)
    for d in doms:
        if d not in PK.DOMAINS:
            continue
        st = PK.domain_status(pkg_dir, d)
        total += st["count"]
        invalid_total += len(st["invalid"])
        label = PK.DOMAINS[d]["label"]
        bad = f"⚠ {len(st['invalid'])} 条不合 schema" if st["invalid"] else "✅"
        rows.append(f"| {label}（`{d}`） | {st['count']} | {bad} |")
    return rows, {"entries": total, "invalid": invalid_total, "domains": len(rows)}


# ───────────────────────────────────────────────────────────────────── 导出
def export_zip(pkg_dir: str, out_path: str | None = None, *, generated_at: str | None = None) -> dict:
    """打包游戏包 → {ok, path, bytes, files, manifest, engine, validation}。"""
    man = PK.load_manifest(pkg_dir)
    pkg_id = man.get("id") or os.path.basename(os.path.normpath(pkg_dir))
    if not pkg_id:
        return {"ok": False, "message": "包清单缺少 id，无法导出"}
    ec = PK.engine_check(man)
    rows, val = _domain_table(pkg_dir)
    stamp = generated_at or time.strftime("%Y-%m-%d %H:%M:%S")
    if out_path is None:
        out_path = os.path.join(os.path.dirname(os.path.normpath(pkg_dir)),
                                f"{pkg_id}-{time.strftime('%Y%m%d-%H%M')}.zip")

    verdict = {True: "✅ 满足", False: "❌ 不满足", None: "⚠ 未能判定（框架不在 import 路径）"}.get(ec.get("ok"), "—")
    readme = _README.format(
        name=man.get("name") or pkg_id, pkg_id=pkg_id, exported_at=stamp,
        req=ec.get("requirement") or "（未声明）", ver=ec.get("version") or "—",
        verdict=verdict, domains="\n".join(rows) or "| （空包） | 0 | ✅ |")

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
        }, ensure_ascii=False).encode("utf-8")
    data = buf.getvalue()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)
    return {"ok": True, "path": out_path, "bytes": len(data),
            "files": len(files) + len(EXPORT_ONLY), "content_files": len(files),
            "manifest": man, "engine": ec, "validation": val,
            "name": f"{pkg_id}.zip"}


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
    return {
        "ok": True, "id": os.path.basename(dest), "dir": dest,
        "manifest": PK.load_manifest(dest), "engine": ec, "validation": val,
        "warnings": ([] if ec.get("ok") is not False else ["引擎版本要求不满足（已强制导入）"])
                    + ([f"{val['invalid']} 个条目不合 schema，可在编辑器里修"] if val["invalid"] else []),
        "report": {"files": info["entries"], "domains": val["domains"], "entries": val["entries"]},
        "meta": info.get("meta") or {},
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
