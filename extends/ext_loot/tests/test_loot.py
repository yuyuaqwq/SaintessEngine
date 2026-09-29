#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""loot 门禁：抽取原语 / 池与策略注册表 / 展开 / 审计 / 档位插值与升档 / 挂载 / 零知识。

跑法：python tests/test_loot.py
退出码：0 = 全绿；1 = 有失败。

三处专门钉住的地方（都是"改了就静默变行为"的）：
  ① **随机流**：抽取必须与参考实现的手写累加版**同一个调用序列**（换 `random.choices` 就红）
  ② **末档容错**：`cutoff` 累计到不了 1.0 时兜底给最后一档（不吞奖励）
  ③ **零知识**：`loot/` 源码常量里不得出现任何内容侧取值（档位取值 / 引用前缀 / 专属策略名）
"""
import ast
import io
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ---- 扩展包门禁路径（2026-09-23 从引擎 tests/ 搬到本包）----
# 本文件现在位于 extends/<pkg>/tests/ ⇒ 往上四级才是**引擎根**，ROOT 重新绑定到它，
# 这样下面原有的 `os.path.join(ROOT, "saintess_engine", ...)` 一类路径扫描仍然指对地方。
_HERE_DIR = os.path.dirname(os.path.abspath(__file__))   # extends/<pkg>/tests
_PKG_ROOT = os.path.dirname(_HERE_DIR)                   # extends/<pkg>
_EXT_BASE = os.path.dirname(_PKG_ROOT)                   # extends
ROOT = os.path.dirname(_EXT_BASE)                        # 引擎根
for _p in (ROOT, _EXT_BASE, _HERE_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ext_loot.loot import (LootTable, SimpleCtx, TierTable, count_for,   # noqa: E402
                                 draw_slots, pick_many, pick_weighted, register_strategy,
                                 roll_range, strategy_names, total_weight, weigh)
import ext_loot.loot.pool as LP                                          # noqa: E402

passed = failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


class FixRng:
    """定值随机源：`random()` 返回给定序列（用于钉住「累加命中/兜底」这类分支）。"""

    def __init__(self, *vals):
        self.vals = list(vals)
        self.sample = random.Random(7).sample
        self.choice = random.Random(7).choice
        self.randint = random.Random(7).randint
        self.calls = 0

    def random(self):
        self.calls += 1
        return self.vals.pop(0) if self.vals else 0.0


# ---------------------------------------------------------------- 1 抽取原语
def t1_pick():
    print("\n[1] 加权抽取原语")
    E = [{"k": "a", "w": 1}, {"k": "b", "w": 3}]
    check("空表 → None", pick_weighted([]) is None and pick_weighted(None) is None)
    check("权重和 0 → None", pick_weighted([{"k": "a", "w": 0}]) is None)
    check("权重缺失 → 默认 1（等价参考实现 e.get('w',1)）",
          weigh([{}, {"w": None}, {"w": 2}]) == [1, 0, 2] and total_weight([{}, {}]) == 2)
    check("★ rng 定值时按『累加首个 > roll』命中（roll=0.3×4=1.2 > a 的 1 → 落在 b）",
          pick_weighted(E, rng=FixRng(0.3))["k"] == "b"
          and pick_weighted(E, rng=FixRng(0.1))["k"] == "a")
    check("★ 浮点越界 → 兜底返回**最后一个**（不是第一个）",
          pick_weighted(E, rng=FixRng(1.0))["k"] == "b")
    check("返回的是原对象（同一引用）", pick_weighted(E, rng=FixRng(0.0)) is E[0])
    check("每次都消费一个随机数", (lambda r: (pick_weighted(E, rng=r), r.calls)[1])(FixRng(0.1)) == 1)

    check("pick_many 等概率不放回 = rng.sample（同种子同结果）",
          [e["k"] for e in pick_many(E + [{"k": "c"}], 2, rng=random.Random(3))]
          == random.Random(3).sample(["a", "b", "c"], 2))
    check("pick_many 带权不放回：不重复且给尽",
          len(pick_many(E, 5, weighted=True, rng=random.Random(1))) == 2)
    check("pick_many where 过滤", [e["k"] for e in pick_many(E, 1, where=lambda x: x["k"] == "a",
                                                          rng=random.Random(1))] == ["a"])
    check("pick_many 全被过滤 → [] 且不抛错",
          pick_many(E, 2, where=lambda x: False) == [] and pick_many(E, 0) == [])
    check("pick_many replace=True 可重复", len(pick_many(E, 4, replace=True, rng=random.Random(2))) == 4)
    print("  · roll_range 形态：", [roll_range(x, rng=random.Random(5))
                                for x in (3, [2, 2], [4], None, "5", True, [1, 3])])
    check("roll_range：int→本身 / [a,b]→闭区间 / 非法→default",
          roll_range(3) == 3 and roll_range([2, 2]) == 2 and roll_range([4]) == 4
          and roll_range("5") == 5 and roll_range(object(), default=7) == 7)


# ---------------------------------------------------------------- 2 策略注册表
def t2_registry():
    print("\n[2] 策略注册表（可拔插 + 元数据）")
    check("内置四种策略", set(strategy_names()) >= {"weighted", "fixed", "table", "table_choice"})
    check("weighted 声明『用 entries + 需要权重』",
          LP.STRATEGIES["weighted"]["uses"] == "entries" and LP.STRATEGIES["weighted"]["needs_weights"])
    check("table 声明『用 rolls』", LP.STRATEGIES["table"]["uses"] == "rolls")

    def _mine(pool, ctx, table):
        return []

    register_strategy("test_mine", _mine, doc="测试用", uses="none", replace=True)
    check("注册自定义策略", "test_mine" in strategy_names())
    check("重名默认报错", _raises(ValueError, lambda: register_strategy("test_mine", _mine)))
    check("replace=True 才覆盖",
          register_strategy("test_mine", _mine, replace=True) is _mine)
    check("非法 uses → ValueError", _raises(ValueError, lambda: register_strategy("bad1", _mine, uses="x")))
    check("非可调用 → TypeError", _raises(TypeError, lambda: register_strategy("bad2", 123)))
    LP.STRATEGIES.pop("test_mine", None)
    check("清理后回到内置集合", "test_mine" not in strategy_names())


def _raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    except Exception:                                     # noqa: BLE001
        return False
    return False


# ---------------------------------------------------------------- 3 池与入口
def _tbl(pools, **kw):
    return LootTable(pools, rng=random.Random(11), **kw)


def t3_roll():
    print("\n[3] LootTable.roll：四种内置策略")
    pools = {
        "w1": {"type": "weighted", "entries": [
            {"item": "mat_a", "w": 3, "n": 2}, {"item": "mat_b", "w": 1}]},
        "lv": {"type": "weighted", "entries": [
            {"item": "mat_low", "w": 1, "max_lv": 10}, {"item": "mat_high", "w": 1, "min_lv": 50}]},
        "f1": {"type": "fixed", "entries": [{"item": "mat_c", "n": 3}, {"item": "mat_d"}]},
        "t1": {"type": "table", "rolls": [
            {"pool": "w1", "chance": 1.0}, {"pool": "mat_x", "chance": 0.0}]},
        "tc": {"type": "table_choice", "rolls": [
            {"pool": "mat_1", "cutoff": 0.25}, {"pool": "mat_2", "cutoff": 0.75}]},
        "tc_bad": {"type": "table_choice", "rolls": [{"pool": "mat_z", "cutoff": 0.5}]},
        "empty": {"type": "weighted", "entries": []},
    }
    seen = []

    def resolve(ref, ctx):
        seen.append(ref)
        return {"type": "item", "item_id": ref}

    t = _tbl(pools, resolver=resolve, inline_prefixes=("gold:", "item:"))

    # ★ 审计 L565：resolver 返**域表里的共享对象**时，count 写口不得把数据表就地写脏
    #   （旧行为：第一次 roll 把 count 1→4、第二次 →16、第三次 →64，数据表永久污染且自污染）
    _DOM = {"shared": {"type": "item", "item_id": "shared", "count": 1, "data": {"lv": 3}}}
    _td = _tbl({"ps": {"type": "weighted", "entries": [{"item": "shared", "w": 1, "n": 2}]}},
               resolver=lambda ref, ctx: _DOM.get(ref))
    _got = [_td.roll("ps", qty=2) for _ in range(3)]
    check("域表不被写回：三次 roll 的 count 逐次相同（1→2/2→2/3→2）",
          all(len(x) == 2 and all(e["count"] == 2 for e in x) for x in _got), str(_got))
    check("域表对象逐字未改：count 仍 1、data 子层不共享",
          _DOM["shared"]["count"] == 1 and _DOM["shared"]["data"] == {"lv": 3}, str(_DOM))
    check("返回的是副本（改返回值不写回域表）",
          (_td.resolve("shared", None) or {}).pop("count", None) is not None
          and _DOM["shared"]["count"] == 1, str(_DOM))
    check("空解析结果仍按『出不来』处理（None / 空 dict 都不给条）",
          _td.resolve("没有这个", None) is None)

    r = t.roll("w1", t.ctx if hasattr(t, "ctx") else None, qty=2) if False else t.roll("w1", qty=2)
    check("weighted：抽 qty 次且每条 count 乘 n",
          len(r) == 2 and all(x["count"] == 2 for x in r), str(r))
    check("weighted：等级窗口过滤（5 级只出低档 / 60 级只出高档）",
          [x["item_id"] for x in t.roll("lv", player_level=5)] == ["mat_low"]
          and [x["item_id"] for x in t.roll("lv", player_level=60)] == ["mat_high"])
    check("weighted：窗口空档（20 级夹在 max_lv=10 与 min_lv=50 中间）→ 走兜底 → []",
          t.roll("lv", player_level=20) == [])
    check("weighted：SImpleCtx 缺属性当 None（不抛 AttributeError）",
          SimpleCtx().whatever is None and SimpleCtx(a=1).a == 1)
    r = t.roll("f1")
    check("fixed：全给且 count 乘 n",
          sorted((x["item_id"], x["count"]) for x in r) == [("mat_c", 3), ("mat_d", 1)])
    r = t.roll("t1")
    check("table：独立判定（0 概率那行不中）", [x["item_id"] for x in r] == ["mat_a"] or
          [x["item_id"] for x in r] == ["mat_b"], str(r))
    check("table：子池递归（走子池策略、qty 进子 ctx）", all(x["type"] == "item" for x in r))
    r = t.roll("tc")
    check("table_choice：一次只进一档", len(r) == 1, str(r))
    r = t.roll("tc_bad")
    check("★ table_choice：累计 cutoff 不足 1.0 → 兜底给最后一档（不吞奖励）",
          [x["item_id"] for x in r] == ["mat_z"], str(r))
    check("空池 → []", t.roll("empty") == [] and t.roll("不存在") == [])
    check("ctx 传入 + kw：kw 就地设到 ctx 上（参考实现行为）",
          (lambda c: (t.roll("w1", c, qty=1), getattr(c, "qty"))[1])(SimpleCtx()) == 1)
    check("roll 缺省 ctx 走 SimpleCtx（不传 ctx、只给 kw）", len(t.roll("w1", qty=1)) == 1)

    def boom(pool, ctx, table):
        raise RuntimeError("x")

    # ★ 审计 L566：`strict` 默认已由 False 改 True（不写就默认降级 = 把声明错误静默成空掉落）。
    #   下面两条把两种模式都**显式**钉住：`strict=False` 仍可优雅跳过（能力未删），
    #   `strict=True`（含**不传** = 新默认）一律抛。判据意图「可选择性优雅跳过」原样保留。
    t2 = _tbl({"b": {"type": "boom", "entries": []}}, strategies={"boom": boom},
              strict=False)
    check("策略抛错 → 吞掉返回 []（显式 strict=False，参考实现行为）", t2.roll("b") == [])
    t3 = LootTable({"b": {"type": "boom", "entries": []}}, strategies={"boom": boom}, strict=True)
    check("strict=True → 抛出来", _raises(RuntimeError, lambda: t3.roll("b")))
    t4 = LootTable({"b": {"type": "boom", "entries": []}}, strategies={"boom": boom})
    check("默认 strict=True（不传也抛，审计 L566）",
          t4.strict is True and _raises(RuntimeError, lambda: t4.roll("b")))
    check("池查找会剥内容侧前缀（pool_key_prefixes）",
          _tbl(pools, pool_key_prefixes=("weighted:",)).has_pool("weighted:w1"))


# ---------------------------------------------------------------- 4 兜底钩子
def t4_fallback():
    print("\n[4] 兜底钩子（池抽空时）")
    pools = {"e": {"type": "weighted", "entries": [], "fallback": "mat_fb"}}
    calls = []
    def _boom_strat(pool, ctx, table):
        raise RuntimeError("boom")
    t3_strict = _tbl({"boom_pool": {"type": "boom", "entries": []}},
                     strategies={"boom": _boom_strat})      # strict 默认 True

    def fb(pool, decl, ctx):
        calls.append(decl)
        return [{"type": "item", "item_id": decl, "count": 1}]

    t = _tbl(pools)
    c = SimpleCtx(fallback_roll=fb)
    check("池空 → 调 ctx.fallback_roll(pool, decl, ctx)",
          [x["item_id"] for x in t.roll("e", c)] == ["mat_fb"] and calls == ["mat_fb"])
    check("无 fallback 声明 → []", _tbl({"e2": {"type": "weighted", "entries": []}}).roll("e2", c) == [])
    # ★ 审计 L566 同族（2026-09-29，批次 1）：钩子抛错**按 strict 分流**。
    #   旧判据「钩子抛错 → 吞掉返回 []」钉的是**无条件吞**那条支 —— 它与同轮刚立的
    #   `strict=True` 契约（t3_roll 那组）**逐字相反**：同一个表，同一个 `strict=True`，
    #   策略抛错上抛、兜底钩子抛错却静默空掉落。判据只**换口径**不放松：
    #   ① 默认 strict=True → 上抛（新默认，防的正是线上那一支）；
    #   ② **显式** strict=False 仍可优雅跳过（能力未删，意图原样保留）；
    #   ③ 钩子**正常返回 falsy** 时仍回落 []（不是「抛错就空」）。
    _boom = lambda *a: (_ for _ in ()).throw(RuntimeError())
    check("★ 钩子抛错 + strict=True（默认）→ 抛出来",
          _raises(RuntimeError, lambda: t.roll("e", SimpleCtx(fallback_roll=_boom))))
    check("★ 钩子抛错 + 显式 strict=False → 吞掉返回 []（能力保留）",
          _tbl(pools, strict=False).roll("e", SimpleCtx(fallback_roll=_boom)) == [])
    check("钩子正常返回 None → 回落 []（不是抛）",
          t.roll("e", SimpleCtx(fallback_roll=lambda *a: None)) == [])
    check("★ 兜底支与策略支同口径：strict=True 下两者都上抛",
          _raises(RuntimeError, lambda: t.roll("e", SimpleCtx(fallback_roll=_boom)))
          and _raises(RuntimeError, lambda: t3_strict.roll("boom_pool")))


# ---------------------------------------------------------------- 5 展开 / 审计
def t5_expand_audit():
    print("\n[5] 展开与结构审计")
    pools = {
        "w": {"type": "weighted", "entries": [{"item": "a", "w": 2}, {"item": "b", "w": 1}]},
        "f": {"type": "fixed", "entries": [{"item": "c"}]},
        "tb": {"type": "table", "rolls": [{"pool": "w"}, {"pool": "gold:1:9"}, {"pool": "item:x"}]},
        "bad_weight": {"type": "weighted", "entries": [{"item": "a", "w": 0}]},
        "bad_empty": {"type": "weighted", "entries": []},
        "bad_noitem": {"type": "weighted", "entries": [{"w": 1}]},
        "bad_sub": {"type": "table", "rolls": [{"pool": "nowhere"}]},
    }
    t = _tbl(pools, inline_prefixes=("gold:", "item:"),
             resolver=lambda ref, ctx: ({"type": "item", "item_id": ref} if ref in ("a", "b", "c", "x")
                                        else None))
    check("展开：weighted 按权重重复", t.expand("w") == ["a", "a", "b"])
    check("展开：fixed 全给", t.expand("f") == ["c"])
    check("展开：table 递归子池 + 内联引用", t.expand("tb") == ["a", "a", "b", "gold:1:9", "item:x"])
    check("展开：未知池 → []", t.expand("nope") == [])
    check("展开：单条权重上限 1000（防撑爆）",
          _tbl({"big": {"type": "weighted", "entries": [{"item": "a", "w": 99999}]}}).expand("big") == ["a"] * 1000)
    au = t.audit()
    kinds = sorted({(lvl, key) for lvl, key, _ in au["issues"]})
    check("审计：权重和 ≤ 0 报空池", ("空池", "bad_weight") in kinds)
    check("审计：entries 为空报空池", ("空池", "bad_empty") in kinds)
    check("审计：条目缺 item 报断链", ("断链", "bad_noitem") in kinds)
    check("审计：table 子池指向不存在的池报断链",
          ("断链", "bad_sub") in kinds
          and any("子池/引用未知" in m for l, k, m in au["issues"] if k == "bad_sub"))
    check("审计：解析不了的引用报断链（resolvable 判定）",
          ("断链", "bad_noitem") in kinds and any("引用无法解析" in m or "条" in m for _l, _k, m in au["issues"]))
    check("审计：池数 / 条目数 / ok",
          au["pool_count"] == len(pools) and au["ok"] is False and isinstance(au["entry_count"], int))
    clean = _tbl({"w": pools["w"]}, resolver=lambda ref, ctx: {"type": "item", "item_id": ref})
    check("审计：干净池 → ok=True 且 issues 空",
          clean.audit(resolvable=lambda ref, pool: True)["ok"] is True
          and clean.audit(resolvable=lambda ref, pool: True)["issues"] == [])
    check("审计：resolvable 返回 None 时不判（内容侧自己管）",
          _tbl({"w": pools["w"]}, resolver=lambda r, c: None)
          .audit(resolvable=lambda ref, pool: None)["ok"] is True)
    check("★ 审计：resolvable 给字符串 → 就用它当措辞（内容侧自己的词汇表说话）",
          any(m == "物品缺失: a" for l, k, m in
              _tbl({"w": pools["w"]}, resolver=lambda r, c: None)
              .audit(resolvable=lambda ref, pool: f"物品缺失: {ref}")["issues"]))
    check("审计：回调收到的是 (ref, pool) 两个参数（pool 能给上下文）",
          _tbl({"w": pools["w"]}, resolver=lambda r, c: None)
          .audit(resolvable=lambda ref, pool: (pool or {}).get("type") == "weighted"
                 or "池类型不对")["ok"] is True)
    check("audit_pretty 出字符串", "掉落池审计" in clean.audit_pretty())

    # 内联前缀默认「内容侧自管、不判」；内容侧声明「这族内联引用其实有域落点」时**照判**（opt-in）
    au_plain = t.audit()
    check("审计：内联前缀默认跳过（无回调时 gold:1:9 / item:x 都不报）",
          not any("gold:" in m or "item:" in m for _l, _k, m in au_plain["issues"]))

    def rsv_judged(ref, pool):                 # noqa: ARG001
        return str(ref).endswith("_ok")

    rsv_judged.judged_inline_prefixes = ("item:",)      # 只声明 item: 这一族要判
    au3 = t.audit(resolvable=rsv_judged)
    check("★ 审计：回调声明 judged_inline_prefixes 后，该族内联引用照判（item:x → 断链）",
          any("item:x" in m for _l, _k, m in au3["issues"]))
    check("审计：没被声明的那族内联前缀照旧跳过（gold:1:9 不报）",
          not any("gold:1:9" in m for _l, _k, m in au3["issues"]))


# ---------------------------------------------------------------- 6 档位阶梯
def t6_tier():
    print("\n[6] 档位阶梯（TierTable）")
    T = TierTable(["t1", "t2", "t3", "t4", "t5"],
                  info={"t1": {"mult": 1.0, "name": "首档"}},
                  weights_by_level={1: [100, 0, 0, 0, 0], 5: [20, 30, 30, 15, 5], 9: [0, 10, 30, 40, 20]},
                  aliases={"t1": "低", "t5": "高"})
    check("顺序 / 序号 / 档位取值", T.order == ("t1", "t2", "t3", "t4", "t5") and T.index("t3") == 2
          and T.tier_at(1) == "t2" and T.tier_at(-1) == "t5" and T.tier_at(99) is None)
    check("未知档位 index → -1（不抛错）", T.index("nope") == -1 and "nope" not in T)
    check("info_of 是副本（改它不污染表）",
          (lambda d: (d.update({"mult": 9}), T.info_of("t1")["mult"] == 1.0)[1])(T.info_of("t1")))
    check("别名反查（resolve：先取值后别名）", T.resolve("t4") == "t4" and T.resolve("高") == "t5"
          and T.resolve("没这个") is None)
    check("升档封顶 / 降档触底",
          T.next_tier("t4") == "t5" and T.next_tier("t5") == "t5" and T.next_tier("t1", -1) == "t1")
    check("未知档位升档 → None", T.next_tier("nope") is None and T.upgrade("nope") is None)
    check("upgrade：chance=1 必升 / chance=0 不升",
          T.upgrade("t2") == "t3" and T.upgrade("t2", chance=0.0) == "t2")
    check("upgrade：chance 走注入 rng", T.upgrade("t2", chance=0.5, rng=FixRng(0.4)) == "t3"
          and T.upgrade("t2", chance=0.5, rng=FixRng(0.6)) == "t2")
    check("★ weights_at 表内插值（手工核对：lv=3 → 1↔5 的中点）",
          T.weights_at(3) == [60.0, 15.0, 15.0, 7.5, 2.5], str(T.weights_at(3)))
    check("weights_at：低于最小 / 高于最大取端点",
          T.weights_at(0) == [100, 0, 0, 0, 0] and T.weights_at(99) == [0, 10, 30, 40, 20])
    check("weights_at：clamp 夹等级（内容侧『副业 1..9』就是它）",
          TierTable(["a"], weights_by_level={1: [1], 9: [9]}, clamp=(1, 9)).weights_at(5) == [5.0])
    check("weights_at：无权重表 → 等权",
          TierTable(["a", "b"]).weights_at(3) == [1, 1])
    check("pick：命中非零权重档（fix rng）",
          T.pick(weights=[0, 0, 1, 0, 0], rng=FixRng(0.5)) == "t3")
    check("pick：exclude 全排除 → None",
          T.pick(weights=[0, 0, 1, 0, 0], exclude=("t3",), rng=FixRng(0.5)) is None)
    check("pick：dict 权重按 key 对齐", T.pick(weights={"t5": 5}, rng=FixRng(0.5)) == "t5")
    check("pick：权重行比档位短 → 缺的补 0",
          T.pick_weights([1, 0], rng=FixRng(0.5)) == "t1")
    check("权重行长度不符 → 构造时报错",
          _raises(ValueError, lambda: TierTable(["a", "b"], weights_by_level={1: [1]})))
    check("档位 key 重复 → 构造时报错", _raises(ValueError, lambda: TierTable(["a", "a"])))
    check("别名指向未知档位 → 构造时报错", _raises(ValueError, lambda: TierTable(["a"], aliases={"b": "x"})))
    check("count_for：定值 / 区间（extra_chance 0 取小、1 取大）/ 未知档 → 0",
          count_for({"t1": 0, "t3": 2, "t5": [3, 4]}, "t3") == 2
          and count_for({"t5": [3, 4]}, "t5", extra_chance=0.0) == 3
          and count_for({"t5": [3, 4]}, "t5", extra_chance=1.0) == 4
          and count_for({}, "t9") == 0)


# ---------------------------------------------------------------- 7 挂载
def t7_mount():
    print("\n[7] 槽位挂载（固定 + 随机补足）")
    pool = ["a", "b", "c", "d"]
    out = draw_slots(pool, 3, fixed=("mark",), rng=random.Random(4))
    check("固定项在最前", out[0] == "mark" and len(out) == 3, str(out))
    check("不重复（3 条各不相同）", len(set(out)) == 3)
    check("固定项与池重复时去重",
          draw_slots(["a", "b"], 2, fixed=("a",), rng=random.Random(4)) == ["a", "b"])
    check("池不够 → 给尽不抛错", len(draw_slots(["a"], 5, fixed=("m",))) == 2)
    check("count ≤ 固定数 → 只给固定项", draw_slots(pool, 1, fixed=("m", "n")) == ["m", "n"])
    check("count=0 → 返回固定项", draw_slots(pool, 0) == [])
    check("no_dup=False 允许重复", len(draw_slots(["a"], 3, no_dup=False)) == 3)
    check("weighted=True 走带权抽取", len(draw_slots([{"k": 1, "w": 1}, {"k": 2, "w": 9}], 1,
                                                    weighted=True, weight_key="w")) == 1)


# ---------------------------------------------------------------- 8 零知识
def t8_zero_knowledge():
    print("\n[8] 零知识：引擎源码常量里不得出现内容侧取值")
    BANNED = ("white", "green", "blue", "purple", "orange", "legend", "fish", "equip",
              "petegg", "mat_", "gold:", "item:", "special:", "战意", "旋律", "词条", "品质")
    bad = []
    for root, _dirs, files in os.walk(os.path.join(ROOT, "extends", "ext_loot", "loot")):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            with open(os.path.join(root, fn), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            # 跳过**文档串**（模块/类/函数 docstring）：文档要能解释「档位（品质那一类）」
            # 这件事本身，判据针对的是**代码里写死的取值**（那才是"把某款游戏焊进引擎"）
            docs = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    d = ast.get_docstring(node, clean=False)
                    if d is not None:
                        docs.add(d)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if node.value in docs:
                        continue
                    for b in BANNED:
                        if b in node.value:
                            bad.append(f"{fn}:{node.lineno}:{b}")
    check("★ 代码常量里无内容侧取值/前缀/专属策略名（取值只由内容侧给）", not bad, str(bad[:6]))
    check("内置策略名都是形状词（weighted/fixed/table/table_choice）",
          set(strategy_names()) == {"weighted", "fixed", "table", "table_choice"})


# ---------------------------------------------------------------- 9 可复现
def t9_determinism():
    print("\n[9] 可复现：同种子同结果（两个独立实例）")
    pools = {"w": {"type": "weighted", "entries": [{"item": "a", "w": 5}, {"item": "b", "w": 3}]}}
    a = LootTable(pools, resolver=lambda r, c: {"type": "item", "item_id": r}, rng=random.Random(99))
    b = LootTable(pools, resolver=lambda r, c: {"type": "item", "item_id": r}, rng=random.Random(99))
    check("同种子 → 逐条一致",
          [(x["item_id"], x["count"]) for x in a.roll("w", qty=8)]
          == [(x["item_id"], x["count"]) for x in b.roll("w", qty=8)])
    c = LootTable(pools, resolver=lambda r, c2: {"type": "item", "item_id": r}, rng=random.Random(100))
    check("不同种子 → 结果不同（拿到的是真随机流，不是写死的）",
          [x["item_id"] for x in c.roll("w", qty=30)] != [x["item_id"] for x in a.roll("w", qty=30)])
    check("不传 rng 时默认标准库 random", LootTable(pools).rng is random)


def t10_sub_ctx_copy_contract():
    """审计 L568（批次 1）：`SimpleCtx` 吞 dunder ⇒ `sub_ctx` 的复制**恒**失败。

    旧形态：`__getattr__` 无条件返回 None，于是 `copy.copy` 的协议探针
    （`__copy__` → `__reduce_ex__` → `__setstate__`）拿到的全是 None（不是「调用它」），
    标准库抛 `TypeError` ⇒ `sub_ctx` 的 `except Exception: return ctx` 永远命中、
    永远返回**原对象** ⇒ 嵌套池的 `n:[3,7]` 整段失效（实跑每次只出 1 条）。
    """
    import copy as _copy

    # ① 宽容袋子只对**数据属性**开，dunder 一律走正常查找链
    check("★ 数据属性缺失仍给 None（不抛）", SimpleCtx().whatever is None)
    check("★ dunder 缺失抛 AttributeError（不许被袋子吞成 None）",
          _raises(AttributeError, lambda: getattr(SimpleCtx(), "__no_such_dunder__")))

    # ② copy.copy 真能复制 SimpleCtx，且副本与原件不共享 qty
    c = SimpleCtx(uid="p1", qty=1)
    cc = _copy.copy(c)
    cc.qty = 9
    check("★ copy.copy(SimpleCtx) 可用", cc is not c and c.qty == 1 and cc.qty == 9)

    # ③ 端到端：子池 `n:[3,7]` 必须真的按 3~7 抽（旧形态恒为 1）
    pools = {
        "main": {"type": "table", "rolls": [{"pool": "sub", "n": [3, 7]}]},
        "sub": {"type": "weighted", "entries": [{"item": "sword", "w": 1}]},
    }
    t = LootTable(pools, strategies={}, strict=True, rng=random.Random(7),
                  resolver=lambda ref, ctx: {"type": "item", "item_id": ref})
    ctx = SimpleCtx(uid="p1", qty=1)
    got = t.roll("main", ctx)
    check("★ 嵌套池 n:[3,7] 真的抽 3~7 条（sub_ctx 复制生效）",
          3 <= len(got) <= 7, "got %d 条" % len(got))
    check("★ sub_ctx 不改原 ctx（外层 qty 保持 1）", ctx.qty == 1)

    # ④ 反向护栏：复制真失败时**抛**，不静默拿原对象顶替
    #    （copy 对任何普通对象都能靠 __reduce_ex__ 复制，所以要显式打断它）
    class _Uncopyable:
        def __init__(self):
            self.qty = 1

        def __reduce_ex__(self, proto):
            raise TypeError("这个 ctx 不可复制")

        def __reduce__(self):
            raise TypeError("这个 ctx 不可复制")

    def _raise_on_getattr(name):
        raise AssertionError("不该走到 getattr：%s" % name)

    _c = _Uncopyable()
    _c.__getattr__ = _raise_on_getattr
    check("★ 复制失败抛（不静默改原对象）", _raises(TypeError, lambda: t.sub_ctx(_c, 3)))


# ── L-audit2（afix2 自查新开口）────────────────────────────────────────────
# `LootTable.pool` 剥前缀时写死 `split(":", 1)`，而前缀是**内容侧声明的**。
# 前缀不含 ":" 时，切点落在**池名自己的冒号**上 ⇒ 静默查出另一个池；
# 前缀恰好等于整串时 ⇒ IndexError，把「不存在 → None、不抛错」的契约也破掉。
# 下面全部**真调生产函数**（不在测试里重写一遍剥前缀逻辑，否则反证会假通过）。
def t11_pool_key_prefix_strip():
    pools = {
        "a:b": {"type": "weighted", "entries": [{"item": "RIGHT", "w": 1}]},
        "b":   {"type": "weighted", "entries": [{"item": "WRONG", "w": 1}]},
    }
    def items(t, k):
        # ★ 必须**吞掉异常并回报**，不能让它冒出去：冒出去会让门禁在第一条红就
        #   Traceback 中止 ⇒ 后面的断言一条都不跑 ⇒ 看不到完整红集（Step 0c 守恒）。
        #   召回「本车道 gate 崩在第一处」那一族：判据要报红，不是要崩。
        try:
            r = t.pool(k)
        except Exception as e:                              # noqa: BLE001
            return ("RAISED", type(e).__name__)
        return None if r is None else [e["item"] for e in r["entries"]]

    # ① 含冒号前缀（既有口径）：剥掉后按整名查
    t_colon = LootTable(pools, pool_key_prefixes=("weighted:", "fixed:"))
    check("剥冒号前缀后按整名查得着",
          items(t_colon, "weighted:a:b") == ["RIGHT"]
          and items(t_colon, "fixed:a:b") == ["RIGHT"])
    check("冒号前缀 + 池名自带冒号 ≠ 切在池名的冒号上",
          items(t_colon, "weighted:a:b") != ["WRONG"])

    # ② 不含冒号的前缀（内容侧命名空间）：按**声明的前缀**切，不能切池名的冒号
    t_dot = LootTable(pools, pool_key_prefixes=("side.",))
    check("★ 无冒号前缀：整名命中 RIGHT（改前静默给 WRONG）",
          items(t_dot, "side.a:b") == ["RIGHT"])
    check("★ 无冒号前缀：不被切到 WRONG（这条是静默错池，防复发）",
          items(t_dot, "side.a:b") != ["WRONG"])

    # ③ 剥完剩空串 ⇒ 没有池名可查 ⇒ None，**不抛**（契约：不存在 → None）
    for key, tbl in (("side.", t_dot), ("weighted:", t_colon), ("fixed:", t_colon)):
        def _empty(k, tt):
            return not _raises(Exception, lambda: tt.pool(k)) and tt.pool(k) is None
        check("剥完剩空串 %r → None 且不抛（改前 IndexError）" % key, _empty(key, tbl))
    check("前缀恰好等于整串时 has_pool 也不抛",
          not _raises(Exception, lambda: t_dot.has_pool("side."))
          and t_dot.has_pool("side.") is False)

    # ④ 上游两个读口（roll / expand）跟着不抛 —— 它们都走 pool()
    for meth in ("roll", "expand"):
        check("%s 遇空串键 → [] 而非 IndexError" % meth,
              not _raises(Exception, lambda m=meth: getattr(t_dot, m)("side."))
              and getattr(t_dot, meth)("side.") == [])

    # ⑤ 未命中的一律 None（正常路逐字不变）
    check("未命中 → None", items(t_dot, "side.nope") is None and items(t_colon, "nope") is None)
    check("命中本体键不经剥前缀", items(t_dot, "a:b") == ["RIGHT"])

    # ⑥ AST：pool() 里不许再出现写死的 split(":", …) 切法
    src = io.open(os.path.join(_PKG_ROOT, "loot", "pool.py"), encoding="utf-8").read()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "pool")
    body = ast.dump(fn)
    check("★ AST：pool() 内不再出现按冒号切前缀的写法（改前是 split 冒号 取下标 1）",
          not (("split" in body) and ("':'" in body or "'\:'" in body)))
    # ★ 这条第一版写成 `len(p) in body.replace(" ","")` —— **ast.dump 不会把
    #   `len(p)` 渲染成这串字面量**（它是 Call(func=Name('len')) 结构）
    #   ⇒ 子串判据恒假 = 假门禁。改成真判 AST 节点形状。
    def _has_len_call(n):
        for x in ast.walk(n):
            if (isinstance(x, ast.Call) and isinstance(x.func, ast.Name)
                    and x.func.id == "len" and x.args
                    and isinstance(x.args[0], ast.Name)):
                return True
        return False
    check("★ AST：pool() 用 len(前缀变量) 切声明的前缀本身", _has_len_call(fn))



def main():
    print("== loot 门禁：抽取 / 池与策略 / 展开审计 / 档位 / 挂载 / 零知识 ==")
    t1_pick()
    t2_registry()
    t3_roll()
    t4_fallback()
    t5_expand_audit()
    t6_tier()
    t7_mount()
    t8_zero_knowledge()
    t9_determinism()
    t10_sub_ctx_copy_contract()
    t11_pool_key_prefix_strip()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
