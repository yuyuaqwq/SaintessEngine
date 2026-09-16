#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：**两条路由路径同一口径**（B19e）—— 运行时 `Host.declared_hit()`
== 注册表 `CommandRegistry.first_hit(..., visible_only=True)`。

缺口（B19d 实测抓到，B19e 收口）
-------------------------------
引擎里曾有两套「一条文本 → 哪条声明」的排序：
  A. `CommandRegistry.hit()`                     —— `priority` 降序、同值保注册序（B19d 已收口）
  B. `Host.declared_hit()`                       —— 逐条试 `visible()`（= `order` 升序），不看 priority
实测真包：`declared_hit('5') = shortcut_trigger`，而 priority 口径应是 `npc_quick_dialog(100)`。
编辑器「试玩」tab 走的正是 B（`editor/play_worker.py` 调 `host.declared_hit(text)`）
⇒ 同一份包在编辑器里与在引擎注册表下**命中顺序可能不同**。

主线裁定（B19e，照此执行）
--------------------------
① 路由只考虑 `visible=True` 的声明（平台 gate 如 `_maint_gate` 不参与包内路由 —— 适配器职责）
② 顺序 = `priority` 降序 → 同值按**注册序**（唯一口径，与 A 完全一致）
③ **排序只有一份实现**：B 不再自己遍历/排序，改为调用 A 的能力
   （`CommandRegistry.first_hit(text, visible_only=True)`）

判据
----
① 真包：`declared_hit('5') == 'npc_quick_dialog'`（priority 100 胜出，不再是 shortcut_trigger）
② 一致性：一组样本文本，`declared_hit(t) == registry.first_hit(t, visible_only=True)`
③ 不可见声明不参与：合成 `visible=False, priority=999` 且命中的声明 → **不被选中**
   （反向证据：同一合成表上 `first_hit(t)`（缺省 `visible_only=False`）会选中它 ⇒ 过滤有牙）
④ 反证（内存对拍，不碰盘）：删掉优先级 → 结果退回**旧口径**那一条（可观测）→ 还原复绿。
   注意两处细节（本门禁实测得出，已写进报告）：
   * `item_view_mode_cmd`（priority 50）删掉即可观测 → `物品详情开始` 退回注册序在前的 `item_detail`；
   * `npc_quick_dialog`（priority 100）**单独删不够**：它在真表里注册在 `shortcut_trigger` **之前**
     （idx 129 < 165），同值 0 → 按注册序仍是它。要让它可观测，需**同时**把两条的注册序对调；
     对调后删 priority → `shortcut_trigger`（旧结果），还原 priority → `npc_quick_dialog`。
⑤ 加固：排序真的只有一份 —— `hits()` / `first_hit()` 都调 `_ranked()`；`declared_hit` 源码里
   没有自己的遍历/排序；`hit()` / `hits()` 签名未变（B19d 门禁 ⑦ 的锁仍成立）。

跑法：`python tests/test_host_route_consistency.py`（exit=0 全绿）。
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.command import CommandRegistry                      # noqa: E402
from saintess_engine.host import Host                                    # noqa: E402

#: 真包（旗舰内容包）——「真包断言」用它的**真声明表**，与 `Package.command_declarations()` 同一文件
PKG_DIR = os.path.join(ROOT, "games", "orlandia")
PKG_SPEC = os.path.join(PKG_DIR, "content", "data", "commands.json")

passed = 0
failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  ✅ %s" % name)
    else:
        failed += 1
        print("  ❌ %s  %s" % (name, detail))


def _host_with_table(tbl):
    """造一个只装了声明的 Host（**不 boot**：orlandia 的 commands 层仍硬依赖宿主树，
    见 `test_host_skeleton.py` 的 TODO(P4′)）——`declared_hit()` 是真方法，注册表装真声明。"""
    host = Host(None, PKG_DIR)
    host.commands = CommandRegistry(name="orlandia").load(tbl)
    return host, host.commands


def _old_route(reg, text):
    """**旧口径**（B19e 之前）：逐条试 `visible()`（= `order` 升序）取首条。—— 只用于对拍。"""
    for spec in reg.visible():
        if spec.hits(text):
            return spec
    return None


def _key(spec):
    return getattr(spec, "key", None) if spec is not None else None


# ============================================================ ① 真包断言
def t1_real_package(tbl):
    print("\n【① 真包：declared_hit('5') = npc_quick_dialog（priority 100 胜出）】")
    host, reg = _host_with_table(tbl)
    check("真声明表存在", os.path.isfile(PKG_SPEC), PKG_SPEC)
    check("注册表装了真包全部声明（195 条）", len(reg) == 195, len(reg))

    hit5 = host.declared_hit("5")
    check("declared_hit('5') == npc_quick_dialog", _key(hit5) == "npc_quick_dialog", _key(hit5))
    check("declared_hit('5') != shortcut_trigger（不再是旧口径的结果）",
          _key(hit5) != "shortcut_trigger", _key(hit5))
    check("旧口径（order 升序）确实给 shortcut_trigger —— 缺口真实存在，不是空断言",
          _key(_old_route(reg, "5")) == "shortcut_trigger", _key(_old_route(reg, "5")))
    check("declared_hit('5').priority == 100（赢在 priority，不是注册序碰巧）",
          hit5 is not None and hit5.priority == 100, getattr(hit5, "priority", None))

    check("declared_hit('物品详情开始') == item_view_mode_cmd(50)",
          _key(host.declared_hit("物品详情开始")) == "item_view_mode_cmd",
          _key(host.declared_hit("物品详情开始")))
    check("declared_hit('摆摊') == stall_deprecated(5)",
          _key(host.declared_hit("摆摊")) == "stall_deprecated",
          _key(host.declared_hit("摆摊")))

    print("\n【①-补：路由只认可见声明 —— 平台 gate 一条都不出现】")
    checked = 0
    for text in ("5", "物品详情开始", "物品详情结束", "摆摊", "角色", "背包", "起床"):
        got = host.declared_hit(text)
        if got is not None:
            checked += 1
            check("declared_hit(%r) 命中可见声明 %s" % (text, got.key), got.visible is True,
                  "visible=%r" % (got.visible,))
    check("样品里至少有一条真命中（不是全 None 的空跑）", checked >= 4, checked)
    check("统一口径下 _maint_gate（不可见 gate）从不被 declared_hit 选中",
          all(_key(host.declared_hit(t)) != "_maint_gate"
              for t in ("5", "物品详情开始", "角色", "起床", "")),
          [_key(host.declared_hit(t)) for t in ("5", "物品详情开始", "角色", "起床", "")])
    check("declared_hit('') → None（空文本不路由）", host.declared_hit("") is None)
    check("declared_hit('  5  ') 与 '5' 同结果（先 strip）",
          _key(host.declared_hit("  5  ")) == _key(host.declared_hit("5")))
    return host, reg


# ============================================================ ② 与注册表一致
SAMPLES = ["5", " 5 ", "物品详情开始", "物品详情结束", "摆摊", "角色", "背包", "起床",
           "5 号", "０５", "@At:某人 5", "帮助"]


def t2_consistency(host, reg):
    print("\n【② 一致性：declared_hit(t) == registry.first_hit(t, visible_only=True)】")
    bad = []
    for text in SAMPLES:
        a = _key(host.declared_hit(text))
        b = _key(reg.first_hit(text, visible_only=True))
        if a != b:
            bad.append((text, a, b))
    check("%d 条样本文本逐条相同" % len(SAMPLES), bad == [], bad[:6])

    # 独立复算（门禁自己的 oracle）：命中集按 priority 降序、过滤 visible → 取首条
    oracle_bad = []
    for text in SAMPLES:
        t = text.strip()
        cands = [s for s in reg.specs() if s.visible and s.hits(t)]
        cands.sort(key=lambda s: -s.priority)
        want = cands[0].key if cands else None
        got = _key(host.declared_hit(text))
        if got != want:
            oracle_bad.append((text, got, want))
    check("declared_hit == 「命中集按 priority 降序取首条」（独立复算）",
          oracle_bad == [], oracle_bad[:6])

    print("\n【②-补：默认口径未被改动 —— first_hit(visible_only=False) == hit()】")
    drift = [(t, _key(reg.first_hit(t)), _key(reg.hit(t))) for t in SAMPLES
             if _key(reg.first_hit(t)) != _key(reg.hit(t))]
    check("visible_only 缺省 False 时与 hit() 逐条同结果（B19d 语义不回退）",
          drift == [], drift[:6])
    check("整表口径 hit('5') 仍是 _maint_gate（不可见 gate 在 hit() 里照常参与）",
          _key(reg.hit("5")) == "_maint_gate", _key(reg.hit("5")))


# ============================================================ ③ 不可见声明不参与
def t3_invisible_excluded():
    print("\n【③ 不可见声明不参与路由（合成 visible=False, priority=999）】")
    gate = {"key": "secret_gate", "pattern": "^go$", "priority": 999, "visible": False}
    cmd = {"key": "visible_cmd", "pattern": "^go$", "priority": 1, "visible": True}
    for label, order in (("gate 注册在前", [gate, cmd]), ("gate 注册在后", [cmd, gate])):
        host, reg = _host_with_table({s["key"]: s for s in order})
        check("%s：declared_hit('go') == visible_cmd（999 的不可见不参与）" % label,
              _key(host.declared_hit("go")) == "visible_cmd", _key(host.declared_hit("go")))
        check("%s：反向证据 —— first_hit(visible_only=False) 会选中 secret_gate（过滤有牙）" % label,
              _key(reg.first_hit("go")) == "secret_gate", _key(reg.first_hit("go")))
        check("%s：hit('go') 同样是 secret_gate（整表口径不变）" % label,
              _key(reg.hit("go")) == "secret_gate", _key(reg.hit("go")))

    host, reg = _host_with_table({"secret_gate": gate})
    check("只有不可见声明命中 → declared_hit 给 None（不静默塞一条平台 gate）",
          host.declared_hit("go") is None, _key(host.declared_hit("go")))
    check("同表 hit('go') 仍是 secret_gate（两口径分工明确）",
          _key(reg.hit("go")) == "secret_gate", _key(reg.hit("go")))

    # 真包反向加固：把真表里唯一的 priority 不可见声明（_maint_gate）优先级升到 99999 也不参与
    tbl = json.load(open(PKG_SPEC, encoding="utf-8"))
    mut = copy.deepcopy(tbl)
    mut["_maint_gate"]["priority"] = 99999
    host2, _ = _host_with_table(mut)
    check("真表把 _maint_gate 抬到 99999 → declared_hit('5') 仍是 npc_quick_dialog",
          _key(host2.declared_hit("5")) == "npc_quick_dialog", _key(host2.declared_hit("5")))


# ============================================================ ④ 反证
def t4_counterproof(tbl):
    print("\n【④ 反证（内存对拍）：删掉 priority → 退回旧结果（可观测）→ 还原复绿】")
    md5_before = hashlib.md5(open(PKG_SPEC, "rb").read()).hexdigest()

    host, reg = _host_with_table(tbl)
    check("前置：带 priority 时 declared_hit('物品详情开始') == item_view_mode_cmd",
          _key(host.declared_hit("物品详情开始")) == "item_view_mode_cmd",
          _key(host.declared_hit("物品详情开始")))

    # ④-a 真表直接删（不重排注册序）：item_view_mode_cmd(50) 删掉 → 注册序在前的 item_detail
    mut = copy.deepcopy(tbl)
    mut["item_view_mode_cmd"].pop("priority", None)
    mhost, mreg = _host_with_table(mut)
    check("删掉 item_view_mode_cmd.priority → declared_hit('物品详情开始') 退回 item_detail（旧结果）",
          _key(mhost.declared_hit("物品详情开始")) == "item_detail",
          _key(mhost.declared_hit("物品详情开始")))
    check("删除只改顺序、不改命中集合（同文本命中集不变）",
          [s.key for s in mreg.specs() if s.visible and s.hits("物品详情开始")]
          == [s.key for s in reg.specs() if s.visible and s.hits("物品详情开始")],
          [s.key for s in mreg.specs() if s.visible and s.hits("物品详情开始")])
    check("还原（重新装真表）→ item_view_mode_cmd 复赢",
          _key(_host_with_table(tbl)[0].declared_hit("物品详情开始")) == "item_view_mode_cmd")

    # ④-b '5' 这一对：npc_quick_dialog 注册序在 shortcut_trigger 之前 ⇒ 单独删 priority 不可观测，
    #      必须同时把两条的注册序对调（这正是「同值按注册序」的体现，不是门禁放水）。
    host5 = _host_with_table(tbl)[0]
    check("前置：带 priority 时 declared_hit('5') == npc_quick_dialog",
          _key(host5.declared_hit("5")) == "npc_quick_dialog", _key(host5.declared_hit("5")))
    mut5 = copy.deepcopy(tbl)
    mut5["npc_quick_dialog"].pop("priority", None)
    solo = _host_with_table(mut5)[0]
    check("前置（记录）：只删 npc_quick_dialog.priority → 仍是 npc_quick_dialog"
          "（同值 0 时注册序在前，故单独删不可观测）",
          _key(solo.declared_hit("5")) == "npc_quick_dialog", _key(solo.declared_hit("5")))
    check("同值 0 时胜负确由注册序决定：对调两条注册序后 → shortcut_trigger（旧结果可观测）",
          _key(_reversed_pair(mut5).declared_hit("5")) == "shortcut_trigger",
          _key(_reversed_pair(mut5).declared_hit("5")))
    back = _reversed_pair(copy.deepcopy(tbl))
    check("还原 priority（保持对调后的注册序）→ npc_quick_dialog 复赢（priority 压过注册序）",
          _key(back.declared_hit("5")) == "npc_quick_dialog", _key(back.declared_hit("5")))

    md5_after = hashlib.md5(open(PKG_SPEC, "rb").read()).hexdigest()
    check("全过程没碰盘：真声明表 md5 前后一致", md5_before == md5_after,
          "%s → %s" % (md5_before, md5_after))


def _reversed_pair(tbl):
    """把 `npc_quick_dialog` 与 `shortcut_trigger` 的注册序对调（其余一字不动）。"""
    out = {k: v for k, v in tbl.items() if k not in ("npc_quick_dialog", "shortcut_trigger")}
    if "shortcut_trigger" in tbl:
        out["shortcut_trigger"] = tbl["shortcut_trigger"]
    if "npc_quick_dialog" in tbl:
        out["npc_quick_dialog"] = tbl["npc_quick_dialog"]
    return _host_with_table(out)[0]


# ============================================================ ⑤ 单一实现加固
def t5_single_implementation():
    print("\n【⑤ 加固：排序只有一份实现 + 签名锁不变】")
    h_src = inspect.getsource(CommandRegistry.hits)
    f_src = inspect.getsource(CommandRegistry.first_hit)
    d_src = inspect.getsource(Host.declared_hit)
    check("hits() 调 _ranked()（唯一排序实现）", "_ranked(" in h_src, h_src.strip()[:60])
    check("first_hit() 调 _ranked()（唯一排序实现）", "_ranked(" in f_src, f_src.strip()[:60])
    check("declared_hit 调 commands.first_hit(..., visible_only=True)",
          "first_hit(" in d_src and "visible_only=True" in d_src, d_src.strip()[:80])
    check("declared_hit 不再自己遍历可见声明（无 .visible( / for spec in）",
          ".visible(" not in d_src and "for spec in" not in d_src, d_src.strip()[:80])
    check("declared_hit 不再自己排序（无 sorted(）", "sorted(" not in d_src, d_src.strip()[:80])
    check("hits() 签名仍 = (text, *, mode)（B19d 门禁 ⑦ 的锁不被破坏）",
          list(inspect.signature(CommandRegistry.hits).parameters) == ["self", "text", "mode"],
          str(inspect.signature(CommandRegistry.hits)))
    check("hit() 签名仍 = (text, *, mode)（同上）",
          list(inspect.signature(CommandRegistry.hit).parameters) == ["self", "text", "mode"],
          str(inspect.signature(CommandRegistry.hit)))
    check("first_hit() 签名 = (text, *, visible_only, mode)",
          list(inspect.signature(CommandRegistry.first_hit).parameters)
          == ["self", "text", "visible_only", "mode"],
          str(inspect.signature(CommandRegistry.first_hit)))


def main():
    print("=" * 74)
    print("两条路由路径同一口径（B19e）：Host.declared_hit == CommandRegistry.first_hit(visible_only)")
    print("=" * 74)
    print("  真包声明表 = %s" % PKG_SPEC)
    if not os.path.isfile(PKG_SPEC):
        print("  ❌ 读不到真包声明表")
        return 1
    with open(PKG_SPEC, encoding="utf-8") as f:
        tbl = json.load(f)

    host, reg = t1_real_package(tbl)
    t2_consistency(host, reg)
    t3_invisible_excluded()
    t4_counterproof(tbl)
    t5_single_implementation()

    print("\n===== 结果：通过 %d / 共 %d =====" % (passed, passed + failed))
    if failed:
        return 1
    print("全绿 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
