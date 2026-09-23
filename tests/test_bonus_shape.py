#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""bonus 门禁：数值修正容器（分域 / 来源 / 合并顺序 / 撤销 / 空域 / 非法域 / 往返 / 零知识）。

跑法：python tests/test_bonus_shape.py
退出码：0 = 全绿；1 = 有失败。

三处专门钉住的地方（都是「改了就静默变行为」的）：
  ① **合并顺序**：add 全累加 → mul 全连乘 → set 覆盖；空域 = 0（不是 None）。
     与包内 `content/stat_bonus.py` 的 flat 合并 / 引擎读侧折算**同值**（§5.1，真调包内函数）。
  ② **幂等覆盖**：同 (domain, src) 重复 add 只留最后一次，绝不叠加两次
     （反证：若改成累加，本文件第 1/2 组必红）。
  ③ **fail-closed**：非法域 / 非法 mode / 非数值 / 非有限数当场报错，不静默吞成 0。
"""
import ast
import importlib
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.bonus import Bonus                                          # noqa: E402

passed = failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


# ---------------------------------------------------------------- 包内参照
class _StubDB:
    """包内聚合函数的读侧替身：一律返回空（只验合并口径，不碰存档）。"""

    def get_player(self, *a):
        return {}

    def get_stats(self, *a):
        return {}

    def get_reputation(self, *a):
        return None

    def get_quests(self, *a):
        return None

    def get_achievements(self, *a):
        return []

    def get_possessed(self, *a):
        return set()

    def get_bestiary(self, *a):
        return []


def _pkg():
    return importlib.import_module("games.orlandia.content.stat_bonus")


def _pkg_panel_merge(values):
    """真调包内 `stat_bonus()`：把 `values` 当若干条 flat add 来源注入它的数据表。

    注入面只动**数据表/读口替身**（TITLES / CONDITIONS / 读口），用完还原 ——
    包内源码一个字节不改。返回包内合并结果 dict。
    """
    m = _pkg()
    tc = importlib.import_module("games.orlandia.content.title_conds")
    titles = m._cq.TITLES
    achs = m._cq.ACHIEVEMENTS
    books = m._col.books
    conds = dict(tc.CONDITIONS)
    db = m.db
    tids = [f"src{i}" for i in range(1, len(values) + 1)]
    try:
        m._cq.TITLES = [{"id": t, "name": t, "bonus": {"atk": v}}
                        for t, v in zip(tids, values)]
        m._cq.ACHIEVEMENTS = []
        m._col.books = lambda: []
        tc.CONDITIONS = {t: (lambda ctx: True) for t in tids}
        m.db = _StubDB()
        return dict(m.stat_bonus(0, "src"))
    finally:
        m._cq.TITLES = titles
        m._cq.ACHIEVEMENTS = achs
        m._col.books = books
        tc.CONDITIONS = conds
        m.db = db


def _engine_panel_mul(base, mult):
    """引擎读侧乘算口径：`op="mul"` → `int(base × mult)`（stats._apply_effects）。"""
    from ext_combat.battle import stats as _S
    st = {"atk": base}
    _S._apply_effects(st, {"effects": {"k": {"stacks": 1, "stat": "atk",
                                             "op": "mul", "mult": mult}}})
    return st["atk"]


def _engine_cap_flat(flat):
    """引擎读侧上限口径：`cap_of` = 基础 cap + 容器 flat（累加，只认正数）。"""
    from saintess_engine import config as _cfg
    from ext_combat.battle import effects as _E
    old = _cfg.get_effect_rules()
    try:
        _cfg.set_config("effect_rules", {"rage": {"cap": 10}})
        return _E.cap_of({"bonus": {"cap": {"rage": flat}}}, "rage") - 10
    finally:
        _cfg.set_config("effect_rules", old)


def _engine_cost_flat(flat_pct):
    """引擎读侧消耗口径：`skill_pay_of` = max(1, floor(声明 × (1 - flat_pct)))。"""
    from ext_combat.battle.actions import skill_pay_of
    return skill_pay_of({"bonus": {"cost": {"mp_pct": flat_pct}}}, {"mp": 100})["mp"]


# ---------------------------------------------------------------- 1 同值
def t1_same_value():
    print("\n[1] 同值：同一组来源（3 add + 1 mul）逐域与包内合并 / 引擎读口比对")
    m = _pkg()
    check("包内 BONUS_DOMAINS 与本容器 DOMAINS 同一份",
          tuple(m.BONUS_DOMAINS) == Bonus.DOMAINS, str(getattr(m, "BONUS_DOMAINS", None)))
    actor = {}
    m.bonus_seed(actor, {"atk": 15})
    check("包内容器写读口（写 15 → 读回 15）",
          sum(m.bonus_domain(actor, "panel").values()) == 15)

    # ---- panel：3 add + 1 mul ----
    pkg_adds = _pkg_panel_merge((3, 5, 7))
    pkg_flat = sum(pkg_adds.values())
    print(f"    包内 stat_bonus()（3 个 add 来源）→ {pkg_adds}")
    b = Bonus()
    for i, v in enumerate((3, 5, 7), 1):
        b.add("panel", f"src{i}", v)
    print(f"    Bonus.resolve('panel')（同 3 个 add）→ {b.resolve('panel')}")
    check("panel：3 add 与包内合并同值", b.resolve("panel") == pkg_flat == 15,
          f"bonus={b.resolve('panel')} pkg={pkg_flat}")
    b.add("panel", "src4", 2.0, mode="mul")
    eng = _engine_panel_mul(pkg_flat, 2.0)
    print(f"    Bonus.resolve('panel')（+1 mul ×2.0）→ {b.resolve('panel')}；"
          f"引擎读侧 int({pkg_flat} × 2.0) → {eng}")
    check("panel：+1 mul 与引擎读侧乘算同值", b.resolve("panel") == eng == 30,
          f"bonus={b.resolve('panel')} eng={eng}")

    # ---- cap：3 add + 1 mul ----
    c = Bonus()
    for i, v in enumerate((3, 5, 7), 1):
        c.add("cap", f"src{i}", v)
    print(f"    Bonus.resolve('cap')（3 add）→ {c.resolve('cap')}；"
          f"引擎读侧 cap_of（基础 10 + flat）− 10 → {_engine_cap_flat(c.resolve('cap'))}")
    check("cap：3 add 与引擎读侧上限口径同值（15 vs 基础 10 → 25）",
          c.resolve("cap") == _engine_cap_flat(c.resolve("cap")) == 15,
          f"bonus={c.resolve('cap')}")
    c.add("cap", "src4", 2.0, mode="mul")
    print(f"    Bonus.resolve('cap')（+1 mul ×2.0）→ {c.resolve('cap')}；"
          f"引擎读侧 cap_of − 10 → {_engine_cap_flat(c.resolve('cap'))}")
    check("cap：+1 mul 后引擎读到同一个值（30 → 基础 10 → 40）",
          c.resolve("cap") == _engine_cap_flat(c.resolve("cap")) == 30,
          f"bonus={c.resolve('cap')}")

    # ---- cost：3 add + 1 mul ----
    k = Bonus()
    for i, v in enumerate((0.03, 0.05, 0.07), 1):
        k.add("cost", f"src{i}", v)
    print(f"    Bonus.resolve('cost')（3 add）→ {k.resolve('cost')}；"
          f"引擎读侧 100 消耗 → {_engine_cost_flat(k.resolve('cost'))}")
    check("cost：3 add 与引擎读侧消耗口径同值（Σpct 0.15 ⇒ 100→85）",
          k.resolve("cost") == 0.15 and _engine_cost_flat(k.resolve("cost")) == 85,
          f"bonus={k.resolve('cost')}")
    k.add("cost", "src4", 2.0, mode="mul")
    print(f"    Bonus.resolve('cost')（+1 mul ×2.0）→ {k.resolve('cost')}；"
          f"引擎读侧 100 消耗 → {_engine_cost_flat(k.resolve('cost'))}")
    check("cost：+1 mul 后引擎读到同一个值（0.30 ⇒ 100→70）",
          k.resolve("cost") == 0.3 and _engine_cost_flat(k.resolve("cost")) == 70,
          f"bonus={k.resolve('cost')}")


# ---------------------------------------------------------------- 2 幂等
def t2_idempotent():
    print("\n[2] 幂等：同 (domain, src) add 两次 == add 一次")
    b = Bonus()
    b.add("panel", "s1", 7)
    b.add("panel", "s1", 7)
    print(f"    add('panel','s1',7) ×2 → resolve={b.resolve('panel')}（若累加会被算成 14）")
    check("同值重复 add 两次 == 一次（不许叠加）", b.resolve("panel") == 7)
    check("反证：结果不是累加值 14", b.resolve("panel") != 14)
    check("来源表仍只有一条", b.sources("panel") == ["s1"])
    b.add("panel", "s1", 9)
    check("同 src 换值 = 覆盖（不是 7+9=16）", b.resolve("panel") == 9)
    b.add("panel", "s1", 1.5, mode="mul")
    print(f"    add('panel','s1',1.5,mode='mul') → resolve={b.resolve('panel')}"
          f"（旧 add 若残留会被算成 13.5）")
    check("同 src 换 mode = 覆盖（旧 add 不留）", b.resolve("panel") == 0)
    check("反证：结果不是旧值相乘 13.5", b.resolve("panel") != 13.5)
    b.add("cap", "s1", 7)
    b.add("cap", "s1", 7)
    check("幂等按 (domain, src) 分域成立（跨域同名来源各算一次）",
          b.resolve("cap") == 7 and b.sources("cap") == ["s1"])
    check("同来源登记序不变（重复 add 不重排）", b.sources() == ["s1"])


# ---------------------------------------------------------------- 3 撤销
def t3_drop():
    print("\n[3] 撤销：drop(src) 后逐域 == 从未 add 过该来源")
    full = Bonus()
    full.add("panel", "keep_a", 3)
    full.add("panel", "gone", 5)
    full.add("panel", "keep_b", 1.5, mode="mul")
    full.add("cap", "gone", 2)
    full.add("cost", "gone", 0.1)
    never = Bonus()
    never.add("panel", "keep_a", 3)
    never.add("panel", "keep_b", 1.5, mode="mul")
    full.drop("gone")
    print(f"    drop 后逐域：{[full.resolve(d) for d in full.DOMAINS]}"
          f" vs 从未 add：{[never.resolve(d) for d in never.DOMAINS]}")
    check("drop 后逐域 == 从未 add 过该来源",
          all(full.resolve(d) == never.resolve(d) for d in full.DOMAINS))
    check("反证：若 drop 没生效，panel 会多出 5（这里必须是同一个值）",
          full.resolve("panel") == never.resolve("panel") == 4.5)
    check("drop 是跨域撤销（同名标签三档域一起摘）", "gone" not in full.sources())
    check("drop 不存在的来源 → 无操作、不抛错",
          (full.drop("nothing"), full.snapshot() == never.snapshot())[1])
    full.add("panel", "gone", 8)
    check("撤销后可重新 add（同一标签复用）(3+8)×1.5=16.5",
          full.resolve("panel") == 16.5, str(full.resolve("panel")))


# ---------------------------------------------------------------- 4 空域
def t4_empty():
    print("\n[4] 空域：resolve('panel') → 0")
    b = Bonus()
    v = b.resolve("panel")
    check("空容器 resolve('panel') == 0", v == 0)
    check("返回 0（int）而不是 None", v is not None and isinstance(v, int))
    check("三档空域都是 0", [b.resolve(d) for d in b.DOMAINS] == [0, 0, 0])
    check("snapshot 每域都是 0", b.snapshot() == {"panel": 0, "cap": 0, "cost": 0})
    check("只有 mul 没有 add → 0（与读侧基础值缺省 0 一致）",
          (lambda x: (x.add("panel", "m", 2.0, mode="mul"), x.resolve("panel"))[1])(Bonus()) == 0)


# ---------------------------------------------------------------- 5 非法域
def t5_fail_closed():
    print("\n[5] 非法域 / 非法 mode / 非法值：显式报错（不静默丢弃）")
    b = Bonus()
    try:
        b.add("hp", "s", 1)
        check("add 非法域 → ValueError", False)
    except ValueError:
        check("add 非法域 → ValueError", True)
    try:
        b.resolve("hp")
        check("resolve 非法域 → ValueError", False)
    except ValueError:
        check("resolve 非法域 → ValueError", True)
    try:
        b.sources("hp")
        check("sources 非法域 → ValueError", False)
    except ValueError:
        check("sources 非法域 → ValueError", True)
    try:
        b.add("panel", "s", 1, mode="div")
        check("非法 mode → ValueError", False)
    except ValueError:
        check("非法 mode → ValueError", True)
    try:
        b.add("panel", "s", "3")
        check("非数值 → TypeError", False)
    except TypeError:
        check("非数值 → TypeError", True)
    try:
        b.add("panel", "s", float("nan"))
        check("NaN → ValueError", False)
    except ValueError:
        check("NaN → ValueError", True)
    try:
        b.add("panel", "", 1)
        check("空来源标签 → ValueError", False)
    except ValueError:
        check("空来源标签 → ValueError", True)
    try:
        Bonus({"hp": {"s": 1}})
        check("播种未登记域 → ValueError", False)
    except ValueError:
        check("播种未登记域 → ValueError", True)
    try:
        Bonus.from_dict({"domains": {"hp": {}}})
        check("from_dict 未登记域 → ValueError", False)
    except ValueError:
        check("from_dict 未登记域 → ValueError", True)
    check("以上报错都没把容器改脏", b.sources() == [] and b.snapshot() == {"panel": 0, "cap": 0, "cost": 0})


# ---------------------------------------------------------------- 6 往返
def t6_roundtrip():
    print("\n[6] 序列化往返：to_dict → from_dict 等值（resolve 不变）")
    b = Bonus()
    b.add("panel", "s1", 3)
    b.add("panel", "s2", 5)
    b.add("panel", "s3", 1.5, mode="mul")
    b.add("cap", "s1", 2)
    b.add("cost", "s4", 0.1)
    b.add("cost", "s5", 0.25, mode="set")
    d = b.to_dict()
    b2 = Bonus.from_dict(d)
    print(f"    to_dict → {d}")
    print(f"    往返后 resolve → {b2.snapshot()}（原 {b.snapshot()}）")
    check("结构相同", b2.to_dict() == d)
    check("逐域 resolve 不变", b2.snapshot() == b.snapshot())
    check("来源标签与登记序保留",
          [b2.sources(x) for x in b2.DOMAINS] == [b.sources(x) for x in b.DOMAINS])
    b2.add("panel", "new", 99)
    check("往返是深拷贝（改副本不影响原对象）", "new" not in b.sources("panel"))
    check("from_dict(None) = 空容器", Bonus.from_dict(None).snapshot() == {"panel": 0, "cap": 0, "cost": 0})
    check("from_dict 也收播种形（省掉 domains 包装）",
          Bonus.from_dict({"panel": {"s1": 3, "s2": {"value": 5, "mode": "add"}}}).resolve("panel") == 8)
    check("播种形构造等价", Bonus({"panel": {"s1": 3, "s2": 5}}).resolve("panel") == 8)
    check("snapshot 的标量形不能回灌（缺来源标签 → 显式报错）",
          _raises(TypeError, lambda: Bonus({"panel": 8})))
    check("set 覆盖前两者（add/mul 都被压掉）",
          Bonus({"cost": {"a": 5, "b": 2.0, "c": {"value": 0.25, "mode": "set"}}}).resolve("cost") == 0.25)
    check("多个 set 取登记序最后一个",
          Bonus({"cost": {"a": {"value": 1, "mode": "set"},
                          "b": {"value": 2, "mode": "set"}}}).resolve("cost") == 2)
    check("DOMAINS 就是三档（形状合同）", Bonus.DOMAINS == ("panel", "cap", "cost"))


def _raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    except Exception:
        return False
    return False


# ---------------------------------------------------------------- 7 零知识
def t7_zero_knowledge():
    print("\n[7] 零知识：模块源码里不得出现内容侧词汇")
    GAME_WORDS = ("stat_bonus", "装备", "词条", "物品", "怪物", "公会", "职业",
                  "奥兰迪亚", "余烬", "orlandia", "guild", "monster", "gold",
                  "dungeon")
    # 代码常量（跳过 docstring：文档要能解释形状类比；判据针对写死的取值/名号）
    CONST_WORDS = GAME_WORDS + ("item", "player", "level", "equip", "quest", "skill")
    raw_bad, const_bad = [], []
    mod_dir = os.path.join(ROOT, "saintess_engine", "bonus")
    for root, _dirs, files in os.walk(mod_dir):
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            with open(path, encoding="utf-8") as f:
                src = f.read()
            low = src.lower()
            for w in GAME_WORDS:
                if (w in low) if w.isascii() else (w in src):
                    raw_bad.append(f"{fn}:{w}")
            tree = ast.parse(src)
            docs = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                     ast.AsyncFunctionDef)):
                    d = ast.get_docstring(node, clean=False)
                    if d is not None:
                        docs.add(d)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if node.value in docs:
                        continue
                    for w in CONST_WORDS:
                        if (w in node.value.lower()) if w.isascii() else (w in node.value):
                            const_bad.append(f"{fn}:{node.lineno}:{w}")
    print(f"    扫描目录：{os.path.relpath(mod_dir, ROOT)}")
    check("★ 全文无内容侧词汇（stat_bonus / 装备 / 词条 … 都不出现）", not raw_bad, str(raw_bad[:6]))
    check("★ 代码常量里无内容侧取值（取值/名号只由内容侧给）", not const_bad, str(const_bad[:6]))
    check("模块可独立 import（不依赖包门面改动）",
          importlib.import_module("saintess_engine.bonus").Bonus is Bonus)
    check("模块公开面就是 Bonus", importlib.import_module("saintess_engine.bonus").__all__ == ["Bonus"])


def main():
    print("== bonus 门禁：分域合并 / 幂等 / 撤销 / 空域 / 非法域 / 往返 / 零知识 ==")
    t1_same_value()
    t2_idempotent()
    t3_drop()
    t4_empty()
    t5_fail_closed()
    t6_roundtrip()
    t7_zero_knowledge()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
