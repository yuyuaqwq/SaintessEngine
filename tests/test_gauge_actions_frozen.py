# -*- coding: utf-8 -*-
"""冻结门禁：敌身条族 4 动词 + 5 助手（U1-I1 从包内整块上移引擎 `saintess_engine/gauge/actions.py`）。

守什么
------
1. **旧实现逐字冻结在本文件里**（`_FROZEN_BLOCK` = 搬运前包内 `bar_procs.py:38-202` 的
   5 个模块级助手 + 4 个 `@register_action`，含装饰器行）。
2. **双 sha256 钉**：
   ① `sha256(冻结片段文本)` —— 钉住测试里的冻结副本（谁偷改冻结副本 = 红）；
   ② `sha256(inspect.getsource(新实现))` —— 钉住引擎里的活实现（函数体被偷改 = 红）。
   **只钉片段会漏「函数体被偷改」**；只钉活实现会漏「冻结副本被改成一致」。
3. **逐字相等**（唯一允许改写 = import 相对层级 + 登记在册的若干条改写，见 `_FROZEN_DIVERGENCE`）。
   双 sha 是「同一性」断言；等值断言才能定位「哪一行不同」，且能挡住「两边一起改坏」。
4. **注册名逐名相等**：本模块注册的 4 个动词名 == 冻结清单，差集点名。
5. **有牙反证**：临时猴补破坏 3 件事（改 1 条 `logs.append` 文案 / 改 1 个临界判断 /
   从注册表摘掉 1 个动词），断言门禁**必须变红**；跑完**不写盘**还原（源码经 linecache 在
   内存里喂给 `inspect`，仓库文件一个字节都不动）。

改写登记（4 个函数 / 6 处；为什么行为不变）
-------------------------------------------
**T2 第 1/2 轮**（内联 f-string → key + 兜底模板 + 槽位；注入表 `text=` 下传模块级函数）
**T3 / cue 解耦 B4（2026-09-27）**：这 5 条日志改走**表现事件**（`_cue(battle, logs, key, 槽位)`），
`bar_gain` / `bar_trigger` 的第一个参数从「文案表 `text=`」换成**战斗本体**
（总线 + 文案表都在它身上）—— 措辞真源在内容侧文案表，模块级函数手里没有模板可回落。

* **`_settle`（2 处）**
  ① 触发转发改传 `battle`（原 `text=text_of(battle)`）；
  ② `...被破绽震慑，无法行动！`（硬编码游戏名词）→ `_cue(... "battle.gauge.shaken" ...)`，
     条显示名由 `bd.get('name', key)` 供给。该条另有独立理由：作业书 §4 硬禁令 +
     引擎中立性门禁 `tests/test_no_game_vocabulary.py`（扫 `saintess_engine/**`，词表含该名词）
     ⇒ 引擎源码不得出现它。`bd` 来自内容侧 config（游戏侧
     `MECH_CFG["enemy_bar"]["shaken"]["name"]` 即该名词）⇒ 渲染逐字节相同；且该分支只在
     `bd["trigger_effect"]=="skip_turn"` 时可达（config 必在位，不存在「未装配 → 打印 bar key」）。
* **`bar_gain_act` / `passive_reflect_bar_act`**：调 `bar_gain(...)` 时改传 `battle`。
* **`bar_phase_preserve_act` / `passive_reflect_bar_act`**：两条日志改走 `_cue`。

**零回归的根据**：`test_log_render_equivalence()` 用**门禁夹具文案表**
（`tests/_cue_text_fixture.py`，逐字 = 搬运前那句）配上总线跑真实现，对 **5 条日志**逐行钉死；
并逐条反证「换表 ⇒ 该行必变」。**不配总线 ⇒ 只出一行坏数据**（不回落任何引擎措辞）——
这条也是判据（cue 解耦的解耦点）。
**活实现 sha 重钉**：B4 改了 4 个函数（`_settle` / `bar_gain_act` / `bar_phase_preserve_act` /
`passive_reflect_bar_act`）⇒ `PIN_NEW` 按同一算法（`_sha(inspect.getsource(fn))`）重钉；
`PIN_FROZEN`（冻结副本）**一字未动**。

跑法：python tests/test_gauge_actions_frozen.py（exit=0 全绿）
"""
import ast
import hashlib
import inspect
import linecache
import os
import sys

sys.dont_write_bytecode = True        # 门禁只读：连 __pycache__ 都不落盘

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ext_combat.battle.effects import ACTION_HANDLERS, REGISTERED_OVERWRITES  # noqa: E402
from ext_combat.gauge import actions as A  # noqa: E402

# ---- 冻结片段：搬运前包内 `content/mech/bar_procs.py:38-202` 逐字（5 助手 + 4 动词）----
_FROZEN_BLOCK = r'''def _now_of(battle) -> float:
    return float(getattr(battle, "_now", 0.0) or 0.0)


def _host_of(caster, target, params) -> dict | None:
    """条宿主：命中目标优先（skill_hit）；无 target 取声明者（时钟事件自结算）。"""
    if isinstance(target, dict):
        return target
    own = params.get("_owner")
    if isinstance(own, dict):
        return own
    return caster if isinstance(caster, dict) else None


def _bar_keys_of(host: dict) -> list:
    """宿主身上所有条键（effects 里带前缀的条目 → 去前缀 bar key）。"""
    from saintess_engine.gauge import _state_prefix
    pfx = _state_prefix()
    out = []
    for k, v in (host.get("effects") or {}).items():
        if isinstance(k, str) and k.startswith(pfx) and isinstance(v, dict):
            out.append(k[len(pfx):])
    return out


def _ensure_tick(host: dict) -> None:
    """自安装订阅（首次挂条时；重复调用幂等）：

    - `time_advance` → `bar_time_settle`：时钟推进按 dt 结息（谁挂过条谁才订阅，零噪音）
    - `phase`        → `bar_phase_preserve`：阶段转换保留部分积蓄（进度遗产，配置定比例）
    """
    trig = host.setdefault("triggers", {})
    lst = trig.setdefault("time_advance", [])
    if not any(isinstance(e, dict) and e.get("action") == "bar_time_settle" for e in lst):
        lst.append({"action": "bar_time_settle"})
    lph = trig.setdefault("phase", [])
    if not any(isinstance(e, dict) and e.get("action") == "bar_phase_preserve" for e in lph):
        lph.append({"action": "bar_phase_preserve"})


def _settle(battle, host: dict, key: str, logs: list) -> bool:
    """阈值检查 → 触发 → 落地 trigger_effect。返回是否触发。"""
    from saintess_engine.gauge import bar_def, bar_should_trigger, bar_trigger
    now = _now_of(battle)
    if not host or not key or not bar_should_trigger(host, key, now):
        return False
    if not bar_trigger(host, key, logs, now):
        return False
    bd = bar_def(key) or {}
    if (bd.get("trigger_effect") or "") == "skip_turn":
        # 控制跳过：effects 容器 mode=skip（saintess_engine 统一控制消费点消费后自清）；
        # expire=None = 无墙钟到期 → 由「下一动」消费
        host.setdefault("effects", {})[f"bar_skip:{key}"] = {
            "mode": "skip", "expire": None}
        logs.append(f"💢 【{host.get('name', '目标')}】被破绽震慑，无法行动！")
    return True


@register_action("bar_gain")
def bar_gain_act(battle, caster, target, params, logs):
    """命中注入积蓄。

    amount 显式给则用；否则读事件技能字段 `params["field"]`（如 shaken_gain）——
    无字段/非正数 = 无此行为（静默跳过）。
    """
    key = params.get("key")
    if not key:
        return
    host = _host_of(caster, target, params)
    if not host:
        return
    amount = params.get("amount")
    if amount is None:
        field = params.get("field")
        if not field:
            return
        info = (getattr(battle, "_fire_ctx", None) or {}).get("info") or {}
        amount = info.get(field)
        # per_hit：字段值 = 每段量（v153 §六「多段 +3~+5/段」）→ 按本次施放段数合并
        # （skill_hit 每次施放只 fire 一次，段循环在 fire 之前——等价旧引擎逐段 settle）
        if params.get("per_hit"):
            try:
                amount = int(amount or 0) * int(info.get("hits") or info.get("multi") or 1)
            except Exception:
                pass
    try:
        amount = int(amount or 0)
    except Exception:
        return
    if amount <= 0:
        return
    from saintess_engine.gauge import bar_gain
    bar_gain(host, key, amount, logs, now=_now_of(battle))
    _ensure_tick(host)
    _settle(battle, host, key, logs)


@register_action("bar_time_settle")
def bar_time_settle_act(battle, caster, target, params, logs):
    """time_advance：宿主自身所有条结算到当刻（免疫到期 + 连续衰减）+ 触发检查。"""
    host = params.get("_owner") or _host_of(caster, target, params)
    if not isinstance(host, dict):
        return
    from saintess_engine.gauge import bar_settle
    now = _now_of(battle)
    for key in _bar_keys_of(host):
        bar_settle(host, key, now, logs)
        _settle(battle, host, key, logs)


@register_action("bar_phase_preserve")
def bar_phase_preserve_act(battle, caster, target, params, logs):
    """phase：宿主阶段转换 → 所有条保留配置比例积蓄（进度遗产；阶段不清零）。

    比例 = `ENEMY_BAR_CFG[key].phase_preserve_pct`（缺省 50%）——动作零数值，
    只是「阶段转换」这个通用时机的条侧消费端（事件由上层剧本导演广播）。
    """
    host = params.get("_owner") or _host_of(caster, target, params)
    if not isinstance(host, dict):
        return
    from saintess_engine.gauge import bar_def, bar_preserve, bar_state
    for key in _bar_keys_of(host):
        before = float((bar_state(host, key) or {}).get("val", 0.0) or 0.0)
        if before <= 0:
            continue
        bar_preserve(host, key)
        after = float((bar_state(host, key) or {}).get("val", 0.0) or 0.0)
        bd = bar_def(key) or {}
        pct = int(round(float(bd.get("phase_preserve_pct", 0.5) or 0.5) * 100))
        logs.append(f"💢【{host.get('name', '目标')}】阶段更迭："
                    f"{bd.get('name', key)}积蓄保留 {pct}%（{int(before)} → {int(after)}）")


@register_action("passive_reflect_bar")
def passive_reflect_bar_act(battle, caster, target, params, logs):
    """on_taken：受击反制（反震）——反弹 `reflect_pct` 伤害 + 反推攻击者条。

    - 反制者 = `params["_owner"]`（被动持有者 = 受击者；on_taken 主体过滤已保证）
    - 攻击者 = `_fire_ctx["source"]`；反弹基数 = `_fire_ctx["dmg"]`；
      无来源（DOT/环境伤）不反制（对齐 we_reflect 口径）
    - 反推条 = `params["key"]/["gain"]`（装配器按被动 `bar_field` 解析的技能字段量）
      → bar_gain + 触发检查（与命中注入同一条消费链）
    """
    from saintess_engine.battle.actors import actor_alive
    from saintess_engine.gauge import bar_gain
    deflector = params.get("_owner") or target
    if not isinstance(deflector, dict) or not actor_alive(deflector):
        return
    ctx = getattr(battle, "_fire_ctx", None) or {}
    attacker = ctx.get("source")
    if not isinstance(attacker, dict) or not actor_alive(attacker):
        return
    pct = float(params.get("reflect_pct", 0) or 0)
    if pct > 0:
        rd = max(1, int(int(ctx.get("dmg", 0) or 0) * pct))
        from saintess_engine.battle.landing import deal_damage
        deal_damage(battle, deflector, attacker, rd, logs)
        logs.append(f"🪨 反震：反弹 {rd} 点伤害！")
    key = params.get("key")
    gain = int(params.get("gain", 0) or 0)
    if key and gain > 0:
        now = _now_of(battle)
        bar_gain(attacker, key, gain, logs, now=now)
        _ensure_tick(attacker)
        _settle(battle, attacker, key, logs)'''

# 允许的改写（除此之外逐字相等；见模块 docstring）
_REL_MAP = (
    ("from saintess_engine.gauge import ", "from . import "),
    ("from saintess_engine.battle.actors import ", "from ..battle.actors import "),
    ("from saintess_engine.battle.landing import ", "from ..battle.landing import "),
)
# 登记（有意差异）：名 → 若干 (冻结片段, 引擎侧应有) 替换对；顺序即应用顺序。
# T2 第 1 轮 = 日志条显示名转发；T2 第 2 轮 = 文案口（key + 兜底模板 + 槽位）+ 注入表下传。
_FROZEN_DIVERGENCE = {
    "_settle": (
        (r'''    if not bar_trigger(host, key, logs, now):''',
         r'''    if not bar_trigger(battle, host, key, logs, now):'''),
        (r'''        logs.append(f"💢 【{host.get('name', '目标')}】被破绽震慑，无法行动！")''',
         r'''        _cue(battle, logs, "battle.gauge.shaken",
             {"name": host.get('name', '目标'), "bar": bd.get('name', key)})'''),
    ),
    "bar_gain_act": (
        (r'''    bar_gain(host, key, amount, logs, now=_now_of(battle))''',
         r'''    bar_gain(battle, host, key, amount, logs, now=_now_of(battle))'''),
    ),
    "bar_phase_preserve_act": (
        (r'''        logs.append(f"💢【{host.get('name', '目标')}】阶段更迭："
                    f"{bd.get('name', key)}积蓄保留 {pct}%（{int(before)} → {int(after)}）")''',
         r'''        _cue(battle, logs, "battle.gauge.phase_preserve",
             {"name": host.get('name', '目标'), "bar": bd.get('name', key),
              "pct": pct, "before": int(before), "after": int(after)})'''),
    ),
    "passive_reflect_bar_act": (
        (r'''        logs.append(f"🪨 反震：反弹 {rd} 点伤害！")''',
         r'''        _cue(battle, logs, "battle.gauge.reflect", {"dmg": rd})'''),
        (r'''        bar_gain(attacker, key, gain, logs, now=now)''',
         r'''        bar_gain(battle, attacker, key, gain, logs, now=now)'''),
    ),
}

# 冻结清单：注册名 ↔ 函数名
FROZEN_ACTIONS = (
    ("bar_gain", "bar_gain_act"),
    ("bar_time_settle", "bar_time_settle_act"),
    ("bar_phase_preserve", "bar_phase_preserve_act"),
    ("passive_reflect_bar", "passive_reflect_bar_act"),
)
FROZEN_HELPERS = ("_now_of", "_host_of", "_bar_keys_of", "_ensure_tick", "_settle")
FROZEN_NAMES = FROZEN_HELPERS + tuple(fn for _k, fn in FROZEN_ACTIONS)

# 双 sha256 钉（由一次性脚本按磁盘/活实现算出；改冻结片段或改活实现都必须显式重钉）
PIN_FROZEN = {'__all__': '0e397a00d82be46025c0ed606213fbc551035e3efe34f32966a93ee60c26a808',
 '_bar_keys_of': '605c9f4379334a7d1e8f456e812588bc74abb73da23a820baff3e90ae09c781c',
 '_ensure_tick': '40e7e0530939dbca3df5ff01224128f1ba292215c0106abb7729b7de69f6c752',
 '_host_of': 'c7ed3a30e827d53b8293edc5400fc3a4cec4fa5192b2b3c25df7c4415146aba2',
 '_now_of': '8216c6a8826b3c3872289f88ac9d3572acc0865eb1d1f17a348d1f4b471801b2',
 '_settle': '693fcc30dfcf0cfb4e1ecd91a5a7bf9b8b5631cb817d071471137f3cfdf53344',
 'bar_gain_act': '8a93c77fe62e2271d0250766d105a2b95cd3b14a1787b991ffefe7ebf730ba26',
 'bar_phase_preserve_act': '7fac35f4c7e6b40096694bbc8527eabe26ae187de32dcb1040e768b608cd1be3',
 'bar_time_settle_act': '7dadc6b94cf9f507c2440129000c0c11b277e63946580f1accc426557fbf7b3a',
 'passive_reflect_bar_act': '289ee737989be603dd74f881549d0a64e34d6476dcc5cf61d83536b1a954d137'}
PIN_NEW = {
    '_bar_keys_of': '5a6315ed7c275acb89ce37d760d002fa1d9ec238300e588642caca9596f6b54b',
    '_ensure_tick': '40e7e0530939dbca3df5ff01224128f1ba292215c0106abb7729b7de69f6c752',
    '_host_of': 'c7ed3a30e827d53b8293edc5400fc3a4cec4fa5192b2b3c25df7c4415146aba2',
    '_now_of': '8216c6a8826b3c3872289f88ac9d3572acc0865eb1d1f17a348d1f4b471801b2',
    # ★ B4（2026-09-27）重钉：这 4 个函数改走 cue（`text=text_of(battle)` → 传 `battle`；
    #   `render_via` → `_cue`）。算法与旧值同源：`_sha(inspect.getsource(fn))`。
    '_settle': '8ff290c18aabb7ec00a9ef8c09ef5baefe4c9bee18c96970ada7a2a7b5ce967c',
    'bar_gain_act': '8ad6d5d58d1ecb2e2c44153d351cd06bacfae457005a2a4b2c5dae5a83417e14',
    'bar_phase_preserve_act': 'ff9f3e2c5fc920ea6e6b5b9e058ee92b6b40f8691ed9eccfbbaa1e451a59de7d',
    'bar_time_settle_act': 'bc9bf48679b0fc8aef3a1e29ec9d7574a511d8b98f91559b6b7c67a3eab390d6',
    'passive_reflect_bar_act': '17e17b36ebcd303091da276273fcf1baa879bf51de41877b4e7e64ef4402e64a',
}
PIN_REG_NAMES = ['bar_gain', 'bar_phase_preserve', 'bar_time_settle', 'passive_reflect_bar']

PASS = 0
FAIL = 0
FAILURES = []


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")


def _lf(s):
    """统一行尾 + 去首尾空行（hash / 等值比较都用它）。"""
    return s.replace("\r\n", "\n").strip("\n")


def _sha(s):
    return hashlib.sha256(_lf(s).encode("utf-8")).hexdigest()


def _frozen_funcs():
    """从冻结块切出「函数名 → 逐字源码（含 decorator 行）」。"""
    tree = ast.parse(_FROZEN_BLOCK)
    lines = _FROZEN_BLOCK.split("\n")
    out = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        out[node.name] = "\n".join(lines[start - 1:node.end_lineno])
    return out


_FROZEN_FUNCS = _frozen_funcs()


def expected_source(name):
    """冻结源码 → 引擎侧应有源码（只做白名单内登记过的改写）。"""
    src = _FROZEN_FUNCS[name]
    for a, b in _REL_MAP:
        src = src.replace(a, b)
    for a, b in _FROZEN_DIVERGENCE.get(name, ()):
        if a not in src:
            return src + "\n# <<冻结副本里找不到待改写片段 %r>>" % a
        src = src.replace(a, b, 1)
    return src


def _first_diff(a, b):
    la, lb = a.split("\n"), b.split("\n")
    for i in range(max(len(la), len(lb))):
        x = la[i] if i < len(la) else "<无>"
        y = lb[i] if i < len(lb) else "<无>"
        if x != y:
            return "第 %d 行 冻结=%r 实现=%r" % (i + 1, x.strip()[:70], y.strip()[:70])
    return ""


def collect_sources():
    """活实现：`inspect.getsource` 取引擎模块里 9 个对象的源码。"""
    out = {}
    for name in FROZEN_NAMES:
        fn = getattr(A, name, None)
        if fn is None:
            continue
        try:
            out[name] = inspect.getsource(fn)
        except Exception:                                        # noqa: BLE001
            out[name] = ""
    return out


def registered_map():
    """本模块注册的动词（按 `__module__` 归属过滤，不误伤其它族）。"""
    return {k: v for k, v in ACTION_HANDLERS.items()
            if getattr(v, "__module__", "") == A.__name__}


def evaluate(sources=None, reg=None):
    """跑全部断言，返回违规清单（空 = 绿）。有牙反证复用同一函数。"""
    bad = []
    srcs = collect_sources() if sources is None else sources
    rmap = registered_map() if reg is None else reg

    # ① 冻结块自身结构
    if set(_FROZEN_FUNCS) != set(FROZEN_NAMES):
        bad.append("冻结块函数集不等于冻结清单：多=%s 缺=%s"
                   % (sorted(set(_FROZEN_FUNCS) - set(FROZEN_NAMES)),
                      sorted(set(FROZEN_NAMES) - set(_FROZEN_FUNCS))))

    # ② 冻结片段 sha256（钉住测试里的拷贝）
    if _sha(_FROZEN_BLOCK) != PIN_FROZEN.get("__all__"):
        bad.append("冻结片段整体 sha256 不匹配（冻结副本被改）：%s != %s"
                   % (_sha(_FROZEN_BLOCK), PIN_FROZEN.get("__all__")))
    for name in FROZEN_NAMES:
        if name in _FROZEN_FUNCS and _sha(_FROZEN_FUNCS[name]) != PIN_FROZEN.get(name):
            bad.append("冻结片段 %s 的 sha256 不匹配" % name)

    # ③ 活实现：存在性 + sha256 + 逐字相等
    for name in FROZEN_NAMES:
        if not srcs.get(name):
            bad.append("活实现缺失：%s（引擎模块 %s 里取不到）" % (name, A.__name__))
            continue
        got = _lf(srcs[name])
        if _sha(got) != PIN_NEW.get(name):
            bad.append("活实现 %s 的 sha256 不匹配（函数体被偷改）：%s != %s"
                       % (name, _sha(got), PIN_NEW.get(name)))
        exp = expected_source(name)
        if got != exp:
            bad.append("活实现 %s != 冻结源码（%s）" % (name, _first_diff(exp, got)))

    # ④ 注册名逐名相等（差集点名）
    want = {k for k, _fn in FROZEN_ACTIONS}
    have = set(rmap)
    if have != want:
        bad.append("注册名集不相等：多=%s 缺=%s" % (sorted(have - want), sorted(want - have)))
    else:
        for key, fn_name in FROZEN_ACTIONS:
            real = getattr(rmap[key], "__name__", None)
            if real != fn_name:
                bad.append("注册名 %s 指向 %r，期望 %s" % (key, real, fn_name))
    if sorted(want) != list(PIN_REG_NAMES):
        bad.append("注册名集 != 冻结清单常量：%s != %s" % (sorted(want), PIN_REG_NAMES))

    # ⑤ 无覆盖式重注册（同名后注册者胜 ⇒ 覆盖 = 第二处注册）
    dup = sorted(set(REGISTERED_OVERWRITES) & want)
    if dup:
        bad.append("引擎动词名被重复注册（覆盖式）：%s" % dup)
    return bad


# ============================================================
# 断言
# ============================================================

def test_frozen_contract():
    print("【冻结契约：9 对象双 sha256 + 逐字相等 + 注册名逐名相等】")
    bad = evaluate()
    check("冻结门禁全绿（5 助手 + 4 动词）", not bad, "；".join(bad[:4]))
    check("冻结块 = 5 助手 + 4 动词（不是空转）",
          len(_FROZEN_FUNCS) == len(FROZEN_NAMES) == 9, "n=%d" % len(_FROZEN_FUNCS))
    check("活实现取自引擎模块 %s" % A.__name__,
          all(getattr(getattr(A, n, None), "__module__", "") == A.__name__
              for n in FROZEN_NAMES))


class _StubText:
    """假文案表（`render_or` + 命中判定 `in`）：key 在册 → 返回标记；否则标记缺 key。

    ★ B4：cue 的 `kind=text` 渲染是「**必须命中**」口（`render_required`）⇒ 假表也要能
    回答「有没有这个 key」（原先只实现 `render_or` 的替身现在推不动已迁移点位）。
    """

    def __init__(self, mapping=None):
        self.mapping = dict(mapping or {})

    def __contains__(self, key):
        return key in self.mapping

    def render_or(self, key, default, **slots):
        return self.mapping.get(key, "[缺]%s" % key)


class _Holder:
    """带 `text` / `cues`（+ 可选 `_fire_ctx`）的 Battle 替身（= 注入面形状）。

    ★ B4：这 5 条日志走 cue ⇒ 表现要 `cues`（总线）**和** `text`（总线里的措辞表）两样。
    """

    def __init__(self, text=None, fire_ctx=None, cues=None):
        self.text = text
        self.cues = cues
        if fire_ctx is not None:
            self._fire_ctx = fire_ctx


def _cue_bus(table):
    """按 5 条 gauge 日志的 cue 名建一条总线（`table` = 文案表）。"""
    from saintess_engine.cues import CueBus
    names = ("battle.gauge.shaken", "battle.gauge.gain", "battle.gauge.trigger",
             "battle.gauge.phase_preserve", "battle.gauge.reflect")
    return CueBus({n: ({"kind": "text", "key": n},) for n in names}, table=table)


_FIX_BUS = None


def _fix_holder(fire_ctx=None):
    """夹具表 + 总线 的 Battle 替身（逐字 = 搬运前那句）。"""
    global _FIX_BUS
    if _FIX_BUS is None:
        from _cue_text_fixture import TEXT as _FIX_TEXT
        _FIX_BUS = _cue_bus(_FIX_TEXT)
    return _Holder(None, fire_ctx=fire_ctx, cues=_FIX_BUS)


def test_log_render_equivalence():
    print("【gauge 5 条日志：配夹具表 ⇒ 逐字 == 搬运前文案；换表 ⇒ 必变；不配总线 ⇒ 一行坏数据】")
    import ext_combat.gauge as G
    from ext_combat.battle import landing as L
    from saintess_engine.cues import MISS_LINE
    saved = (G.bar_def, G.bar_should_trigger, G.bar_trigger, L.deal_damage)
    G.bar_def = lambda k: {"trigger_effect": "skip_turn", "name": "破绽",
                           "max": 100, "threshold_base": 10}
    try:
        # ① _settle：skip_turn 控制跳过（配夹具表 / 换表 / 不配总线）
        G.bar_should_trigger = lambda h, k, now: True
        G.bar_trigger = lambda b, h, k, logs, now: True
        host0 = {"name": "目标", "effects": {}}
        logs = []
        ok = A._settle(_fix_holder(), host0, "shaken", logs)
        check("① skip_turn 日志逐字节 == 搬运前文案（B4：措辞取自内容侧夹具表）",
              bool(ok) and logs == ["💢 【目标】被破绽震慑，无法行动！"], repr(logs))
        check("skip 落地条目仍在（mode=skip / expire=None）",
              host0["effects"].get("bar_skip:shaken") == {"mode": "skip", "expire": None},
              repr(host0["effects"]))
        host0b = {"name": "目标", "effects": {}}
        logs = []
        A._settle(_Holder(cues=_cue_bus(_StubText({"battle.gauge.shaken": "X"}))),
                  host0b, "shaken", logs)
        check("①' 换表 → 该行输出变（措辞真源在内容侧表）", logs == ["X"], repr(logs))
        host0c = {"name": "目标", "effects": {}}
        logs = []
        A._settle(_Holder(), host0c, "shaken", logs)
        check("①'' 不配总线 / 不配表 ⇒ 一行坏数据（**不**回落引擎模板）",
              logs == [MISS_LINE], repr(logs))

        # ② bar_gain / ③ bar_trigger：模块级函数（B4 起第一个参数 = 战斗本体）
        G.bar_should_trigger = saved[1]
        G.bar_trigger = saved[2]
        e = {"effects": {}}
        logs = []
        G.bar_gain(_fix_holder(), e, "shaken", 5, logs, now=0.0)
        check("② 积蓄行逐字节 == 搬运前文案",
              logs == ["💥 shaken 积蓄 +5（5/100）"], repr(logs))
        logs = []
        G.bar_gain(_Holder(cues=_cue_bus(_StubText({"battle.gauge.gain": "Y"}))),
                   e, "shaken", 5, logs, now=0.0)
        check("②' 换表 → 该行输出变", logs == ["Y"], repr(logs))
        e2 = {"effects": {}}
        logs = []
        G.bar_gain(_fix_holder(), e2, "shaken", 15, logs, now=0.0)
        G.bar_trigger(_fix_holder(), e2, "shaken", logs, now=0.0)
        check("③ 触发行逐字节 == 搬运前文案",
              logs[-1] == "💢 【破绽】触发！(第 1 次)", repr(logs))
        e3 = {"effects": {}}
        logs = []
        _bus3 = _cue_bus(_StubText({"battle.gauge.gain": "Y", "battle.gauge.trigger": "Z"}))
        G.bar_gain(_Holder(cues=_bus3), e3, "shaken", 15, logs, now=0.0)
        G.bar_trigger(_Holder(cues=_bus3), e3, "shaken", logs, now=0.0)
        check("③' 换表 → 触发行输出变", logs[-1] == "Z", repr(logs))

        # ④ 阶段更迭（配表 / 换表）
        host = {"name": "目标", "effects": {"bar:shaken": {"val": 40.0}}}
        logs = []
        A.bar_phase_preserve_act(_fix_holder(), None, None, {"_owner": host}, logs)
        check("④ 阶段更迭行逐字节 == 搬运前文案",
              logs == ["💢【目标】阶段更迭：破绽积蓄保留 50%（40 → 20）"], repr(logs))
        host2 = {"name": "目标", "effects": {"bar:shaken": {"val": 40.0}}}
        logs = []
        A.bar_phase_preserve_act(
            _Holder(cues=_cue_bus(_StubText({"battle.gauge.phase_preserve": "P"}))),
            None, None, {"_owner": host2}, logs)
        check("④' 换表 → 该行输出变", logs == ["P"], repr(logs))

        # ⑤ 反震（配表 / 换表）；deal_damage 猴补 no-op，隔离它自己的日志
        L.deal_damage = lambda *a, **kw: None
        atk = {"name": "甲", "hp": 100, "max_hp": 100}
        dfd = {"name": "乙", "hp": 100, "max_hp": 100}
        logs = []
        A.passive_reflect_bar_act(
            _fix_holder(fire_ctx={"source": atk, "dmg": 30}), None, dfd,
            {"_owner": dfd, "reflect_pct": 0.5, "key": "shaken", "gain": 3}, logs)
        check("⑤ 反震行（+ 反推条积蓄行）逐字节 == 搬运前文案",
              logs == ["🪨 反震：反弹 15 点伤害！", "💥 shaken 积蓄 +3（3/100）"], repr(logs))
        atk2 = {"name": "甲", "hp": 100, "max_hp": 100}
        dfd2 = {"name": "乙", "hp": 100, "max_hp": 100}
        stub = _cue_bus(_StubText({"battle.gauge.reflect": "R", "battle.gauge.gain": "G"}))
        logs = []
        A.passive_reflect_bar_act(
            _Holder(cues=stub, fire_ctx={"source": atk2, "dmg": 30}), None, dfd2,
            {"_owner": dfd2, "reflect_pct": 0.5, "key": "shaken", "gain": 3}, logs)
        check("⑤' 注入表换串 → 两行都取自表", logs == ["R", "G"], repr(logs))
    finally:
        G.bar_def, G.bar_should_trigger, G.bar_trigger, L.deal_damage = saved


def _tamper(name, old, new):
    """猴补素材：把 A.<name> 的源码改一行、注册进 linecache，`inspect` 能读到（不写盘）。"""
    src = _lf(inspect.getsource(getattr(A, name)))
    lines = src.split("\n")
    while lines and lines[0].lstrip().startswith("@"):     # 去装饰器：避免 exec 时重复注册
        lines.pop(0)
    body = "\n".join(lines)
    if old not in body:
        raise AssertionError("猴补目标片段不在 %s：%r" % (name, old))
    body = body.replace(old, new, 1)
    filename = "<tamper:%s>" % name
    ns = {"__name__": A.__name__, "register_action": lambda k: (lambda f: f)}
    exec(compile(body, filename, "exec"), ns)              # noqa: S102 测试用内存猴补
    linecache.cache[filename] = (len(body), None, body.splitlines(True), filename)
    return ns[name]


def test_teeth():
    print("【有牙反证：猴补破坏 3 件事 → 门禁必须变红；跑完不写盘还原】")
    check("基线：门禁本来是绿的", not evaluate(), "；".join(evaluate()[:3]))

    # M1 —— 改一个 cue key（B4 起引擎侧**不再有**内联文案可改 ⇒ 措辞路由被偷改就是这一档的牙）
    orig = A.bar_phase_preserve_act
    A.bar_phase_preserve_act = _tamper("bar_phase_preserve_act",
                                       "battle.gauge.phase_preserve",
                                       "battle.gauge.phase_preserve_typo")
    try:
        bad = evaluate()
        check("M1 改 cue key（措辞路由）→ 门禁变红", bool(bad),
              "（没红说明这行没被门禁看到）")
    finally:
        A.bar_phase_preserve_act = orig

    # M2 —— 改一个临界判断
    orig2 = A.bar_gain_act
    A.bar_gain_act = _tamper("bar_gain_act", "if amount <= 0:", "if amount < 0:")
    try:
        bad = evaluate()
        check("M2 改临界判断 → 门禁变红", bool(bad),
              "（没红说明函数体没被门禁看到）")
    finally:
        A.bar_gain_act = orig2

    # M3 —— 从注册表摘掉一个动词
    popped = ACTION_HANDLERS.pop("bar_phase_preserve")
    try:
        bad = evaluate()
        check("M3 从注册表摘掉一个动词 → 门禁变红", bool(bad),
              "（没红说明注册名没被门禁看到）")
    finally:
        ACTION_HANDLERS["bar_phase_preserve"] = popped

    check("三处猴补全部还原后门禁复绿", not evaluate(), "；".join(evaluate()[:3]))


if __name__ == "__main__":
    test_frozen_contract()
    test_log_render_equivalence()
    test_teeth()
    print(f"\n== 结果：通过 {PASS} / 共 {PASS + FAIL} ==")
    if FAILURES:
        for f in FAILURES:
            print("  FAIL:", f)
        sys.exit(1)
    print("全绿 ✅")
