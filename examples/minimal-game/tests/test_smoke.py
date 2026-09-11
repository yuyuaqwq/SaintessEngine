# -*- coding: utf-8 -*-
"""《铆炉回声》冒烟测试 + 纯度自检。

运行：python examples/minimal-game/tests/test_smoke.py   （exit 0 全绿）

覆盖：
  1) 能起战斗 + 普攻造成伤害
  2) 资源渠道攒层（声明驱动的 channels → res_gain）
  3) 自定义机制生效（@register_action("heat_vent") 追加伤害 + 耗层）
  4) 主动技能 res_cost 扣资源（引擎原生消费）
  5) 名词→动词（EFFECT_ACTIONS["clamp"] → apply mode=skip 控制跳过）
  6) 被动 proc（PASSIVE_PROC → on_taken → backdraft 反击）
  7) ★ 纯度自检：AST 扫全部文件，零 game.data / game.services /
     game.content_rules / game.content 依赖；且运行期 sys.modules 里也不出现它们
"""
import ast
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_EXAMPLE = os.path.dirname(_HERE)                              # examples/minimal-game
_REPO = os.path.dirname(os.path.dirname(_EXAMPLE))             # 框架根（saintess_engine 所在）
sys.path.insert(0, _EXAMPLE)
sys.path.insert(0, _REPO)

from saintess_engine import ActCtx, Battle, deal_damage               # noqa: E402
from content import apply_game_content                          # noqa: E402
from content.data.classes import build_player                   # noqa: E402
from content.data.monsters import build_monster                 # noqa: E402

# 骨架不得依赖的**任何其他游戏包**（第三方视角的纯度契约）：
# 只准依赖 `saintess_engine`（框架）+ 自己的 `content` + 标准库。
# 游戏内容包在 `game.*` 命名空间下 —— 整根禁掉，比逐个子包点禁更严也更持久。
FORBIDDEN = ("game",)

passed = 0
failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} {detail}")


def _fresh(hero_hp=0, foe_hp=0, foe_key="rustmite"):
    """造「玩家 + 一只怪」并装配内容；血量为 0 表示用模板值。"""
    random.seed(20260911)
    hero = build_player("cls_kiln", "p1", "铆炉匠·阿铆", level=6)
    foe = build_monster(foe_key, "e1")
    for actor in (hero, foe):
        apply_game_content(actor)
    if hero_hp:
        hero["max_hp"] = hero["hp"] = hero_hp
    if foe_hp:
        foe["max_hp"] = foe["hp"] = foe_hp
    return hero, foe


def _battle(hero, foe):
    return Battle(btype="monster", sides={"player": [hero], "enemy": [foe]})


def test_battle_runs_and_attack_damages():
    hero, foe = _fresh()
    b = _battle(hero, foe)
    logs = [f"⚔ {hero['name']} VS {foe['name']}"]
    b.auto_run(logs)
    text = "\n".join(logs)
    check("能起战斗并跑完（auto_run 有结果）", b.result in ("victory", "defeat", "fled"),
          f"result={b.result}")
    check("普攻落地造成伤害（日志有「受到 N 点伤害」）", "受到" in text and "点伤害" in text)
    check("战斗以胜利结束", b.result == "victory", f"result={b.result}")


def test_resource_channel():
    hero, foe = _fresh(foe_hp=500)
    b = _battle(hero, foe)
    logs, _ended, _who = b.human_act("attack", None)
    check("普攻命中触发资源渠道（炉温 +1）",
          int((hero["effects"].get("kiln") or {}).get("stacks", 0)) == 1,
          f"kiln={hero['effects'].get('kiln')}")


def test_custom_mechanic():
    hero, foe = _fresh(foe_hp=500)
    b = _battle(hero, foe)
    logs = []
    for _ in range(3):                      # 3 次普攻 → 炉温 3 层 → 机制触发
        got, ended, _who = b.human_act("attack", None)
        logs.extend(got)
        if ended:
            break
    text = "\n".join(logs)
    check("自定义机制触发（@register_action heat_vent 追加伤害）", "炉温喷涌" in text)
    check("机制消耗了资源层（3 层 → 剩 1 层）",
          int((hero["effects"].get("kiln") or {}).get("stacks", 0)) == 1,
          f"kiln={hero['effects'].get('kiln')}")


def test_skill_consumes_resource():
    hero, foe = _fresh(foe_hp=500)
    hero["effects"]["kiln"] = {"stacks": 3}     # 直接给资源（渠道攒层已单独验证）
    b = _battle(hero, foe)
    logs, _ended, _who = b.human_act("skill", "过载铆钉", target=foe)
    check("主动技能命中并造成伤害", "点伤害" in "\n".join(logs))
    check("引擎原生 res_cost 扣资源（3 → 1）",
          int(hero["effects"]["kiln"]["stacks"]) == 1,
          f"kiln={hero['effects']['kiln']}")


def test_noun_to_verb_control():
    hero, foe = _fresh(foe_hp=500, foe_key="ironbuoy")   # 铆壳浮标的技能是「铁钳拘束」
    b = _battle(hero, foe)
    # 让怪放出「铁钳拘束」：技能 mech → 名词 → EFFECT_ACTIONS → apply mode=skip
    foe["auto_act"] = {"act": {"type": "skill", "skill": "ms_clamp"}}
    logs = []
    b.actor_auto(foe, ctx_target=hero)
    check("名词→动词链把控制写到目标身上", "clamp" in hero["effects"],
          f"hero effects={hero['effects']}")
    before = foe["hp"]
    logs2, _ended = b.act(ActCtx(caster=hero, action="attack"))
    check("被控者行动被跳过（mode=skip）", "无法行动" in "\n".join(logs2),
          "\n".join(logs2))
    check("被控刻未造成伤害", foe["hp"] == before, f"foe hp {before}→{foe['hp']}")


def test_passive_proc():
    hero, foe = _fresh(foe_hp=500)
    b = _battle(hero, foe)
    logs = []
    deal_damage(b, foe, hero, 10, logs)        # 怪打玩家 → 玩家 on_taken → 回火
    check("被动 proc 触发（PASSIVE_PROC → backdraft）", "回火" in "\n".join(logs))
    check("反击伤害落到来源身上", foe["hp"] < foe["max_hp"], f"foe hp={foe['hp']}")


def test_engine_mounts():
    """装配自检：引擎的 hook 是「写错名字静默忽略」的，所以要自己点名核对。"""
    from saintess_engine import config
    names = ("formulas", "kinds", "panel_fn", "skill_lookup", "monster_skill_fn",
             "basic_skill_fn", "basic_fallback", "formula_skeleton_fn",
             "skill_flat_fn", "skill_up_fn", "skill_level_of_fn")
    missing = [n for n in names if config.get_hook(n) is None]
    check(f"{len(names)} 个 hook 全部装配到位（无拼错 → 静默忽略）", not missing,
          f"missing={missing}")
    check("两张规则表已挂载（effect_actions / effect_rules）",
          bool(config.get_effect_actions()) and bool(config.get_effect_rules()))
    check("basic_fallback 是内容侧自己的名字（引擎零字面量）",
          (config.get_hook("basic_fallback") or {}).get("name") == "应急撬棍",
          f"fallback={config.get_hook('basic_fallback')}")
    check("kind 词表是内容侧自己的词（引擎不认「冲击」）",
          config.kind_of("phys") == "冲击", f"kind={config.kind_of('phys')!r}")


def _iter_py(root):
    for dirpath, _dirs, files in os.walk(root):
        for fn in sorted(files):
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def _imports_of(path):
    """AST 取一个文件里所有绝对/相对 import 的目标名。"""
    tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
    pkg = os.path.relpath(os.path.dirname(path), _EXAMPLE).replace("\\", ".").replace("/", ".")
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if not node.level:
                out.append(node.module or "")
                continue
            base = pkg if pkg != "." else ""
            parts = base.split(".") if base else []
            base = ".".join(parts[:len(parts) - (node.level - 1)]) if node.level > 1 else base
            out.append((base + "." + (node.module or "")).strip("."))
    return out


def test_purity():
    """★ 纯度自检：骨架零游戏包依赖（静态 AST + 运行期 sys.modules 双查）。"""
    files = list(_iter_py(_EXAMPLE))
    bad = []
    for p in files:
        rel = os.path.relpath(p, _EXAMPLE).replace("\\", "/")
        for mod in _imports_of(p):
            if any(mod == f or mod.startswith(f + ".") for f in FORBIDDEN):
                bad.append(f"{rel}: {mod}")
    check(f"AST 扫描 {len(files)} 个 .py：零 `game.*` import（不依赖任何其他游戏包）",
          not bad, "\n      " + "\n      ".join(bad))
    check("扫描到的文件数 ≥ 9（骨架文件都在）", len(files) >= 9, f"n={len(files)}")
    leaked = sorted(m for m in sys.modules
                    if any(m == f or m.startswith(f + ".") for f in FORBIDDEN))
    check("运行期 sys.modules 里也没有 `game.*`", not leaked, f"leaked={leaked}")


def main():
    print("== 《铆炉回声》冒烟测试 ==")
    for fn in (test_battle_runs_and_attack_damages, test_resource_channel,
               test_custom_mechanic, test_skill_consumes_resource,
               test_noun_to_verb_control, test_passive_proc,
               test_engine_mounts, test_purity):
        print(f"-- {fn.__name__}")
        fn()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
