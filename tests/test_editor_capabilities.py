# -*- coding: utf-8 -*-
"""门禁：能力开关（扩展包「装了 / 没装」的试算与代价）。

守两件事：

① **后端试算的口径**（`editor/capabilities.py`）—— 域表一律走
   `saintess_engine.domains.layered_decls()`（唯一源），不许在编辑器侧另拼一套。
   本门禁用**真包**（`games/orlandia`）验：关掉某个扩展包 → 少哪几个域；
   关掉全部 → 只剩包自己的内容域 + 引擎默认集。

② **前端渲染**（`node/test_capabilities.js`）—— node + 最小 DOM 打桩真跑渲染器。
   机器上没有 node 时**显式跳过**（环境缺件不该变成红）。

为什么值得一道门禁：开关这东西的错法都是**静默**的 —— 域表少算了两个域、
引用数算成 0、勾选状态没跟着 depends 走，界面上都「看起来正常」。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "editor"))

from _check import bind_check  # noqa: E402

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")

from editor import capabilities as CAP  # noqa: E402

ORL = os.path.join(ROOT, "games", "orlandia")
ALL = ["ext_combat", "ext_world", "ext_life", "ext_economy",
       "ext_social", "ext_loot", "ext_dialogue", "ext_quest",
       "ext_reward",        # ★ 2026-09-24 B4a：流水采集半边抽包
       "ext_achieve"]       # ★ 2026-09-24 B2a：条件注册表 / 环境位图形状抽包


def section(t):
    print("\n【%s】" % t)


def main():
    section("1. 真包上试算：域表随 depends 变（走唯一源）")
    base = CAP.effects(ORL)
    ids = sorted(e["id"] for e in base["extensions"])
    check("扫到 10 个扩展包", ids == sorted(ALL), ids)
    check("orlandia 全装（depends 与磁盘一致）",
          sorted(base["enabled"]) == sorted(ALL), base["enabled"])
    check("有效域 = 106", base["trial"]["domains_before"] == 106,
          base["trial"]["domains_before"])

    # 逐个关：只有带域声明的包会少域
    expect_lose = {"ext_combat": ["effect_rules", "passive_proc"],
                   "ext_world": ["instances", "maps"],
                   "ext_loot": ["drop_pools"]}
    for ext_id, want in expect_lose.items():
        row = next(e for e in base["extensions"] if e["id"] == ext_id)
        check("%s 关掉会失去 %s" % (ext_id, want), row["loses_domains"] == want,
              row["loses_domains"])
    for ext_id in ("ext_life", "ext_economy", "ext_social", "ext_dialogue", "ext_quest"):
        row = next(e for e in base["extensions"] if e["id"] == ext_id)
        check("%s 关掉不动域表（它给的是指令与机制）" % ext_id,
              row["loses_domains"] == [], row["loses_domains"])

    section("2. 试算 = 只算不写；结果与逐包相加一致")
    t = CAP.effects(ORL, disable=["ext_world", "ext_loot"])["trial"]
    check("关 ext_world+ext_loot → 106 减 3 个域", t["domains_after"] == 103, t)
    check("失去的域 = 三个包各自失去的并集",
          t["loses_domains"] == ["drop_pools", "instances", "maps"], t["loses_domains"])
    check("断引用按涉及文件去重后非空", t["refs_cut"] > 0 and t["ref_files_cut"], t)
    # 试算不许碰盘
    import io as _io
    mf = os.path.join(ORL, "game.json")
    before = _io.open(mf, encoding="utf-8").read()
    CAP.effects(ORL, disable=ALL)
    check("试算不写 game.json", _io.open(mf, encoding="utf-8").read() == before)

    section("3. 内容侧引用计数能对上（拿 ext_combat 这个大户验）")
    row = next(e for e in base["extensions"] if e["id"] == "ext_combat")
    check("ext_combat 引用数 > 100（它是内容侧最大依赖）", row["refs"] > 100, row["refs"])
    check("给出了引用它的文件清单", len(row["ref_all"]) > 10, len(row["ref_all"]))
    check("每个文件都在包里", all(os.path.isfile(os.path.join(ORL, f))
                                  for f in row["ref_all"][:20]))

    section("4. 前端渲染（node + DOM 打桩；无 node 跳过）")
    node = None
    for cand in ("node", "node.exe"):
        try:
            r = subprocess.run([cand, "--version"], capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                node = cand
                break
        except (OSError, subprocess.SubprocessError):
            continue
    script = os.path.join(ROOT, "node", "test_capabilities.js")
    if not node or not os.path.isfile(script):
        print("  --  跳过（本机没有 node 或脚本不在）：%s" % script)
    else:
        r = subprocess.run([node, script], capture_output=True, text=True, timeout=180, cwd=ROOT)
        last = [x for x in (r.stdout or "").splitlines() if "结果" in x]
        check("前端渲染 12 项全过（%s）" % (last[-1].strip() if last else "?"),
              r.returncode == 0, (r.stdout or "")[-400:] + (r.stderr or "")[-300:])

    print("\n" + "=" * 56)
    _f = globals().get("FAILURES") or []
    print("===== 结果：通过 %d / 失败 %d =====" % (globals().get("PASS", 0), len(_f)))
    for _x in _f[:6]:
        print("   ❌ " + str(_x))
    return 0 if not (globals().get("FAILURES") or []) else 1


if __name__ == "__main__":
    sys.exit(main())
