#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：框架层不得出现游戏身份（任一具体游戏的专有名词/枚举）。

跑法：python tests/test_no_game_vocabulary.py
退出码：0 = 干净；1 = 发现泄漏。

为什么需要它
------------
2026-09-11 实测发现框架仓里漏了一整层游戏语义：
  - `schemas/*.json` 把奥兰迪亚的 33 个机制名、11 个技能种类、23 个物品分类
    抄成了 enum（`mech: [...zhan_yi...]`），示例里写着「命中积攒 1 点战意」
  - `$id` 写着 `https://dragonfall.local/...`
  - 引擎注释里点名游戏实例（牧师 faith / 战意 / 旋律 / randuin / ice_vein）
这些让「换配置+挂机制=换游戏」的承诺失效：第三方拿到会以为战意是框架概念。
本门禁把这条锁死，并给出词表出处，避免再犯。

判定项
------
A. **结构性**（零假阳性）：`schemas/*.json` 任何 `enum` 的取值不得含非 ASCII 字符
   —— 中文枚举值基本等同「某个游戏的内容分类」。
B. **词表**：下列文件集不得出现 `GAME_TERMS` 里的词
   —— `saintess_engine/`（含全部子模块） `schemas/` `editor/` `examples/` `games/`
   （**不含** `docs/`：引擎 wiki 会以「参考实现」的身份正当地提到那只游戏；
     **不含** `tests/`：本文件自身持有词表）
C. `schemas/*.json` 的 `$id` 不得含游戏名。

词表出处（可复现）
------------------
`GAME_TERMS` 由**游戏侧数据反查**得到（`dragonfall/game/data/{classes,battle_rules}.py`
的职业 id / EFFECT_RULES / MECH_CASH / PASSIVE_PROC 键），再剔掉框架合法词汇
（引擎内置动词与字段名如 element/energy/shield/stun/reduce 等 —— 这些是框架协议，
见 `docs/engine-wiki/concepts/declaration-tables.md`）。
若将来框架**确实需要**某个词（例如新增同名通用能力），请在此显式移出并写下理由，
不要为了让门禁变绿而扩大白名单。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SCAN_DIRS = ("saintess_engine", "schemas", "editor", "examples", "games")
SCAN_EXT = (".py", ".json", ".js", ".html")

# 游戏身份词（反查自游戏侧数据；框架层不得出现）
GAME_TERMS = [
    # 游戏/仓库名
    "奥兰迪亚", "余烬纪年", "剑与魔法", "dragonfall",
    # 职业 id（cls_*）
    "cls_ci_ke", "cls_fa_shi", "cls_mu_shi", "cls_novice",
    "cls_shi_ren", "cls_wu_seng", "cls_you_xia", "cls_zhan_shi",
    # 该游戏的机制/资源/状态名
    "zhan_yi", "lian_duan", "randuin", "ice_vein", "melody", "faith",
    "finisher", "fury", "faith_unload",
    "战意", "旋律", "连段", "破绽", "信仰", "奥术", "狂暴",
]


def _iter_files():
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dirpath, dirs, fs in os.walk(base):
            dirs[:] = [x for x in dirs if x not in {"__pycache__", ".git"}]
            for f in sorted(fs):
                if f.endswith(SCAN_EXT):
                    yield os.path.join(dirpath, f)


def _rel(p):
    return os.path.relpath(p, ROOT).replace("\\", "/")


def check_a_no_non_ascii_enum():
    """A：schema 的 enum 取值不得含非 ASCII（中文枚举 = 某个游戏的内容分类）。"""
    bad = []
    for d in ("schemas",):
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for f in sorted(os.listdir(base)):
            if not f.endswith(".json"):
                continue
            doc = json.loads(open(os.path.join(base, f), encoding="utf-8").read())
            stack = []

            def walk(node):
                if isinstance(node, dict):
                    if "enum" in node:
                        for v in node["enum"]:
                            if any(ord(c) > 127 for c in str(v)):
                                bad.append(f"{d}/{f}  {'/'.join(stack[-3:])}  值 {v!r}")
                    for k, v in node.items():
                        if k != "enum":
                            stack.append(k)
                            walk(v)
                            stack.pop()
                elif isinstance(node, list):
                    for v in node:
                        walk(v)

            walk(doc)
    return bad


def check_b_no_game_terms():
    """B：扫描目录不得出现游戏身份词（ASCII 词按词边界匹配）。"""
    bad = []
    pats = []
    for t in GAME_TERMS:
        if t.isascii():
            pats.append((t, re.compile(r"(?<![A-Za-z0-9_])" + re.escape(t) + r"(?![A-Za-z0-9_])")))
        else:
            pats.append((t, re.compile(re.escape(t))))
    for p in _iter_files():
        try:
            txt = open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for i, line in enumerate(txt.splitlines(), 1):
            for term, pat in pats:
                if pat.search(line):
                    bad.append(f"{_rel(p)}:{i}  [{term}]  {line.strip()[:80]}")
    return bad


def check_c_schema_id_neutral():
    """C：schema 的 $id 不得含游戏名。"""
    bad = []
    base = os.path.join(ROOT, "schemas")
    if os.path.isdir(base):
        for f in sorted(os.listdir(base)):
            if not f.endswith(".json"):
                continue
            doc = json.loads(open(os.path.join(base, f), encoding="utf-8").read())
            sid = str(doc.get("$id", ""))
            for t in ("dragonfall", "奥兰迪亚", "余烬"):
                if t in sid:
                    bad.append(f"schemas/{f}  $id={sid}")
    return bad


def main() -> int:
    results = [
        ("A. schema enum 不含非 ASCII（游戏内容分类）", check_a_no_non_ascii_enum()),
        ("B. 框架层不含游戏身份词", check_b_no_game_terms()),
        ("C. schema $id 不含游戏名", check_c_schema_id_neutral()),
    ]
    failed = 0
    print("=== 框架中立性门禁（不得含任一具体游戏的身份）===")
    for name, bad in results:
        if bad:
            failed += 1
            print(f"\n❌ {name}：{len(bad)} 处")
            for b in bad[:25]:
                print(f"    {b}")
            if len(bad) > 25:
                print(f"    … 另 {len(bad) - 25} 处")
        else:
            print(f"✅ {name}")
    if failed:
        print(f"\n共 {failed} 项未过。修法：把游戏语义移到内容包（游戏仓），"
              f"框架只留结构/协议；若某词确属框架协议，按本文件 docstring 显式移出词表并写理由。")
        return 1
    print("\n框架层干净：无游戏身份残留 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
