# -*- coding: utf-8 -*-
"""from_state 的 killed 还原：一个 uid 只还原成**一个** actor（2026-09-29 afix1 第 28 轮）。

判据只加强不放松 —— 全部围绕「还原条数 = 落盘 uid 条数」这一条不变式：
改前的 `break` 只跳出最内层循环 ⇒ 同 uid 跨两个 side 时被 append 两次。
"""
import sys, pathlib
sys.path.insert(0, "C:/Users/yuyu/framework-engine")
sys.path.insert(0, "C:/Users/yuyu/framework-engine/extends")

import saintess_engine.config as _cfg
_cfg.mount(action_base_fn=lambda a: 1.0,
           time_model_fn=lambda spd, base: max(0.1, base / max(0.1, float(spd))))

from extends.ext_combat.battle import Battle, to_state, from_state
from extends.ext_combat.battle.actors import make_actor

PASS, FAIL = 0, 0
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print("  PASS %s" % name)
    else:
        FAIL += 1; print("  FAIL %s %s" % (name, detail))

def build(sides):
    return Battle(btype="instance", sides=sides)

def A(uid, name, side):
    return make_actor(uid=uid, name=name, side=side)

# ── A 段：黑盒 —— 落盘 N 个 uid ⇒ 还原必须恰好 N 条 ──────────────────
def a_case(name, sides_fn, kill_uids):
    b = build(sides_fn())
    by_uid = {}
    for acts in b.sides.values():
        for a in acts:
            by_uid.setdefault(a.get("uid"), []).append(a)
    for u in kill_uids:
        # 落盘名单允许含「恢复后已不在 sides」的 uid（阵亡离场）⇒ 取不到就跳过，
        # 正是 A5 要钉的那一格，不是 KeyError。
        if u in by_uid:
            b.killed_actors.append(by_uid[u][0])
    st = to_state(b)
    b2 = from_state(st)
    got = len(b2.killed_actors)
    check(name, got == len(kill_uids) and len(st["killed"]) == len(kill_uids),
          "落盘 %d 个 uid → 还原 %d 条" % (len(st["killed"]), got))
    return b2

# A1：普通单杀（基线行为必须不变）
a_case("A1 单杀还原 1 条",
       lambda: {"player": [A("u1", "玩家", "player")], "enemy": [A("m1", "怪", "enemy")]},
       ["m1"])
# A2 ★ 本条修的病：同一 uid 出现在两个 side
a_case("A2 同 uid 跨两个 side 仍只还原 1 条",
       lambda: {"player": [A("u1", "玩家", "player")],
                "enemy": [A("m1", "怪", "enemy")],
                "ally":  [A("m1", "镜像怪", "ally")]},
       ["m1"])
# A3：同 uid 横跨 player/enemy 两个 side
a_case("A3 同 uid 跨 player/enemy 只还原 1 条",
       lambda: {"player": [A("u1", "甲", "player"), A("u1", "乙", "player")],
                "enemy": [A("u1", "怪", "enemy")]},
       ["u1"])
# A4：多个 uid 同时还原，条数守恒
a_case("A4 多 uid 还原条数守恒",
       lambda: {"player": [A("u1", "玩家", "player")],
                "enemy": [A("m1", "怪1", "enemy"), A("m2", "怪2", "enemy")],
                "ally":  [A("m2", "镜像", "ally")]},
       ["m1", "m2"])
# A5：落盘名单里**手工塞一个恢复后查不到的 uid**（阵亡已离场）⇒ 跳过，不报错。
# 注意：a_case 是从 sides 反查 uid 来建名单的，所以这一格不经过 a_case，
# 直接构造 state —— 否则「查不到」在构造阶段就变成 KeyError 了（第一版就踩了这个）。
_b = build({"player": [A("u1", "玩家", "player")], "enemy": [A("m1", "怪", "enemy")]})
_b.killed_actors.append(_b.sides["enemy"][0])
_st = to_state(_b)
_st["killed"] = ["m1", "gone"]          # 多一个恢复后查不到的 uid
_b2 = from_state(_st)
check("A5 查无此 uid 跳过不抛", [a.get("uid") for a in _b2.killed_actors] == ["m1"],
      "实际 %s" % [a.get("uid") for a in _b2.killed_actors])

# ── B 段：还原出的对象必须与 sides 里的**同一批对象**是同一批（身份一致）──
b = build({"player": [A("u1", "玩家", "player")],
           "enemy": [A("m1", "怪", "enemy")],
           "ally":  [A("m1", "镜像", "ally")]})
b.killed_actors.append(b.sides["enemy"][0])
b2 = from_state(to_state(b))
check("B1 还原对象是 sides 里的同一个对象（非副本）",
      len(b2.killed_actors) == 1 and b2.killed_actors[0] is b2.sides["enemy"][0],
      "实际 is-enemy=%s" % [a is b2.sides["enemy"][0] for a in b2.killed_actors])
check("B2 名单里不混进另一个 side 的对象",
      all(a is not b2.sides["ally"][0] for a in b2.killed_actors))

# ── C 段：下游消费方按对象身份判定的活功能（复活被动族）──────────────
# `class_mech.py` 的复活被动用 `owner in ka`（**对象身份**）移除死亡记录。
# 若名单里混进别的 side 的同 uid 对象，真死者可能拿不到自己那条 ⇒ 复活后
# 仍被算作已死（掉经验/不掉落）。这里钉「真死者一定在名单里」。
b3 = build({"player": [A("u1", "玩家", "player")],
            "enemy": [A("m1", "怪", "enemy")],
            "ally":  [A("m1", "镜像", "ally")]})
b3.killed_actors.append(b3.sides["enemy"][0])
b4 = from_state(to_state(b3))
owner = b4.sides["enemy"][0]
check("C1 复活被动能按身份命中真死者（owner in ka）",
      owner in b4.killed_actors)
b4.killed_actors = [x for x in b4.killed_actors if x is not owner]
check("C2 移除后真死者不在名单里（复活生效）",
      owner not in b4.killed_actors and len(b4.killed_actors) == 0)

# ── D 段：源码形状钉住（不靠行号；用 AST 找 nested For 的 break 归属）────
import ast, pathlib
src = pathlib.Path("C:/Users/yuyu/framework-engine/extends/ext_combat/battle/serialize.py").read_text(encoding="utf-8")
tree = ast.parse(src)
fn = next(n for n in ast.walk(tree)
          if isinstance(n, ast.FunctionDef) and n.name == "from_state")
loops = [n for n in ast.walk(fn) if isinstance(n, ast.For)]
check("D1 from_state 里三个 for（killed × sides × actors）",
      len(loops) == 3, "实际 %d" % len(loops))
# killed 那个**最外层** for（body 里直接放 side 循环的）必须以 break 收尾。
# ★ 不能用 loops[0] 定位：ast.walk 是 BFS，嵌套的 side/actor 循环先于它被取出。
# 末位是 `for...else: continue`（ast 把它包成 If），不是裸 For ⇒ 判「含 For 子句」
kill_loop = next(n for n in fn.body
                 if isinstance(n, ast.For)
                 and any(isinstance(x, ast.For) for x in n.body))
# ★ `else: continue` 挂在**内层**（for acts）上，autopep8/AST 都这么归位；
#   所以「终止整条 uid 查找」的那句 break 落在 **side 循环的 body 末位**，
#   而不是 killed 循环自己的 body 末位（它的 body 只有一条 For）。
check("D2 side 循环以 break 收尾（命中后终止整条 uid 查找）",
      isinstance(kill_loop.body[0].body[-1], ast.Break),
      "实际末位 = %s" % type(kill_loop.body[0].body[-1]).__name__)
check("D2b 查不到该 uid 时走 continue（换下一个 side）而非跳出",
      any(isinstance(x, ast.Continue) for x in ast.walk(kill_loop))
      and len(kill_loop.body[0].orelse) == 0)
# D3：内层 actor 循环仍保留自己的 break（找到即离内层），语义不被改坏
actor_loop = next(n for n in ast.walk(fn)
                  if isinstance(n, ast.For) and n is not kill_loop
                  and any(isinstance(x, ast.For) for x in ast.walk(n)))
check("D3 内层 actor 循环保留 break（命中即离内层）",
      isinstance(actor_loop.body[-1], ast.Break),
      "实际末位 = %s" % type(actor_loop.body[-1]).__name__)

print("=" * 56)
print("PASS %d / FAIL %d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
