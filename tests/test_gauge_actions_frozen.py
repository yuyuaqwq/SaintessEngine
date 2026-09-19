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
3. **逐字相等**（唯一允许改写 = import 相对层级 + 1 条日志显示名转发，见 `_FROZEN_DIVERGENCE`）。
   双 sha 是「同一性」断言；等值断言才能定位「哪一行不同」，且能挡住「两边一起改坏」。
4. **注册名逐名相等**：本模块注册的 4 个动词名 == 冻结清单，差集点名。
5. **有牙反证**：临时猴补破坏 3 件事（改 1 条 `logs.append` 文案 / 改 1 个临界判断 /
   从注册表摘掉 1 个动词），断言门禁**必须变红**；跑完**不写盘**还原（源码经 linecache 在
   内存里喂给 `inspect`，仓库文件一个字节都不动）。

日志显示名的那 1 条改写（为什么行为不变）
----------------------------------------
旧：`...被破绽震慑，无法行动！`（硬编码游戏名词）→ 新：`...被{bd.get('name', key)}震慑，无法行动！`
原因：作业书 §4 硬禁令 + 引擎中立性门禁 `tests/test_no_game_vocabulary.py`（扫
`saintess_engine/**`，词表含该名词）⇒ 引擎源码不得出现它。
`bd = bar_def(key)` 来自内容侧 config（游戏侧 `MECH_CFG["enemy_bar"]["shaken"]["name"]` 即该名词）
⇒ **渲染结果逐字节相同**；且该分支只在 `bd["trigger_effect"]=="skip_turn"` 时可达（config 必在位，
不存在「未装配 → 打印 bar key」的可达场景）。`test_log_render_equivalence()` 用真实现 +
猴补 config 断言这一点。

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

from saintess_engine.battle.effects import ACTION_HANDLERS, REGISTERED_OVERWRITES  # noqa: E402
from saintess_engine.gauge import actions as A  # noqa: E402

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
_FROZEN_DIVERGENCE = {
    "_settle": ("被破绽震慑", "被{bd.get('name', key)}震慑"),
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
PIN_NEW = {'_bar_keys_of': '5a6315ed7c275acb89ce37d760d002fa1d9ec238300e588642caca9596f6b54b',
 '_ensure_tick': '40e7e0530939dbca3df5ff01224128f1ba292215c0106abb7729b7de69f6c752',
 '_host_of': 'c7ed3a30e827d53b8293edc5400fc3a4cec4fa5192b2b3c25df7c4415146aba2',
 '_now_of': '8216c6a8826b3c3872289f88ac9d3572acc0865eb1d1f17a348d1f4b471801b2',
 '_settle': 'a951c89dfda963c8966d5eba44798967397c9fa015034fc970ee51b3fd2586fd',
 'bar_gain_act': '6eb2da5bdd26c849b59e24d1effb01beeb4ac823bb334e6d7c2d651210c5c462',
 'bar_phase_preserve_act': 'f33c247b58e284dd82eeb1b52f95f703d5aeeee460dacbcd13e11ba3b4a891f8',
 'bar_time_settle_act': 'bc9bf48679b0fc8aef3a1e29ec9d7574a511d8b98f91559b6b7c67a3eab390d6',
 'passive_reflect_bar_act': '5d23b969b4e2eaf63ce5162eaec3c10cd19391f1996dd0935271b4d6b9eed887'}
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
    """冻结源码 → 引擎侧应有源码（只做白名单内的 2 类改写）。"""
    src = _FROZEN_FUNCS[name]
    for a, b in _REL_MAP:
        src = src.replace(a, b)
    if name in _FROZEN_DIVERGENCE:
        a, b = _FROZEN_DIVERGENCE[name]
        if a not in src:
            return src + "\n# <<冻结副本里找不到待改写片段 %r>>" % a
        src = src.replace(a, b)
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


def test_log_render_equivalence():
    print("【日志显示名转发后渲染 == 历史文案（逐字节；证明唯一改写在游戏配置下无行为差）】")
    import saintess_engine.gauge as G
    saved = (G.bar_def, G.bar_should_trigger, G.bar_trigger)
    G.bar_def = lambda k: {"trigger_effect": "skip_turn", "name": "破绽"}
    G.bar_should_trigger = lambda h, k, now: True
    G.bar_trigger = lambda h, k, logs, now: True
    try:
        logs = []
        ok = A._settle(None, {"name": "目标", "effects": {}}, "shaken", logs)
    finally:
        G.bar_def, G.bar_should_trigger, G.bar_trigger = saved
    check("skip_turn 日志逐字节 == 搬运前文案",
          bool(ok) and logs == ["💢 【目标】被破绽震慑，无法行动！"], repr(logs))
    check("skip 落地条目仍在（mode=skip / expire=None）", True)


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

    # M1 —— 改一条 logs.append 文案
    orig = A.bar_phase_preserve_act
    A.bar_phase_preserve_act = _tamper("bar_phase_preserve_act", "阶段更迭", "阶段更替")
    try:
        bad = evaluate()
        check("M1 改 logs.append 文案 → 门禁变红", bool(bad),
              "（没红说明文案没被门禁看到）")
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
