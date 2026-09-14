# -*- coding: utf-8 -*-
"""包内世界域命令（`content/cmds_world.py`）—— 36 条世界命令的守卫/取参/业务/**渲染**。

终态形状（真源 = `overnight/B18_TERMINAL_SHAPE.md` §1.2；B18-L1）：宿主
`game/commands/world.py` 每条命令只剩 `@declared("<key>")` + `_BRIDGE.run(self, "<key>", event)`
一行转发；守卫声明（`hook:player` = 包侧 `content/guards.py::GUARDS["player"]`）、
`hook:no_prof_waiting`（本线追加，见 §②）、取参、分支业务、面板行序与**渲染**全在本模块。
宿主里**零** 文案调用点（目标 `grep -c 'T\.text\|T\.static' game/commands/world.py` = 0）。

本模块与既有实现体的关系（搬家不是重写）
----------------------------------------
`content/world_cmds.py`（4207 行，B9 线2 已逐字搬包，**本线一字未改**）持有 103 个历史形状的
async generator（`yield event.plain_result(...)`）；本模块提供**过渡期适配件**把它们的产出收成
终态要的 `list[str]`（实现体改成同步直返后适配件一并删除）：

    _Say     平台事件最小替身：`plain_result(文本)` → 已渲染行；`message_str` 读写落在替身自身
             （裸数字转投『物品详情』『前往』依赖这一语义），其余属性/方法原样代理真事件
             （`stop_event()` 等副作用照旧）。形状 = `content/cmds_player.py::_Say`（L4 定形）。
    _resume  驱动一个协程到「本次产出」；`await` 出去的协程**递归驱动后回送**（本线必须：
             `world_cmds.talk_choice` 会 `await self._apply_talk_action_async(...)`）。
             真挂起（I/O await）→ `RuntimeError`（fail-closed，不静默吞）。
    _drain   同步取空 async generator → 产出（已渲染行）列表。

⚠️ 一个**不在本模块**的宿主侧真相源（宿主源码级门禁钉住，非遗漏）
  * `_instance_gate_block` —— 留宿主：`tests/test_v185_instance_admission.py:1131` 要求
    宿主 world.py 源码出现 `instance_gate.walk_admission`（徒步进图三档判定）。
    （`quest_view` 已搬入本模块 —— `daily.*` 渲染点随之进包，`tests/test_texts_table.py`
    的 WIRED 表按「周常」先例补上包内文件。）

包内不 import 宿主（I2）：宿主壳对象经 `env.state["shell"]` 取（桥接层透传），
`content/world_cmds.py` 侧既有的「宿主替身口」（`_host_attr` / `_HostMod` / `C` / `db`）一字未动。

行为逐字节不变；证据 = `overnight/W-B18-L1.md` 的 174 项三分支快照（sha256 改前 = 改后）。
"""
from __future__ import annotations

import inspect
import time

from . import catalog_life as _cat_life
from . import texts as T
from . import world_cmds as _WC
# B14 口径：数据面走包内门面（不新增 `C.<数据名>` 读点；实测与宿主 `C` 逐对象同一）
from .catalog_quests import MAIN_QUESTS, NPCS, SIDE_QUESTS
from .catalog_space import MAP_BY_ID
from .commands import register
from .guards import GUARDS as _GUARDS
from .wild import ALL_WILD
from .world_cmds import db, _DAILY_META_KEYS   # B2-W2：清死 import（C/_host_attr 全仓零调用点）


# ============================================================
# ① 过渡期适配件（见模块头注：只服务「实现体仍是 async generator」这一件事）
# ============================================================

class _Say:
    """`env.raw`（平台事件）的最小替身：`plain_result` → 已渲染行；其余原样代理。"""

    def __init__(self, ev):
        object.__setattr__(self, "_ev", ev)
        object.__setattr__(self, "lines", [])
        object.__setattr__(self, "message_str", getattr(ev, "message_str", "") or "")

    def plain_result(self, text):
        """把「一行文本」收起来 —— 玩家可见文案的落点由包内决定（此处只有行内容）。"""
        self.lines.append(text)
        return text

    def get_message_str(self):
        """改写后的消息以本替身为准（裸数字转投下一跳：物品详情 / 前往）。"""
        return self.message_str

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_ev"), name)

    def __setattr__(self, name, value):
        if name in ("message_str", "lines"):
            object.__setattr__(self, name, value)
        else:                                   # 转发期 `message_str` 等语义逐字保留
            setattr(object.__getattribute__(self, "_ev"), name, value)


def _resume(coro):
    """驱动一个协程到「本次产出」，返回其 yield 值。

    * `await <协程>` → 递归驱动内层后把结果回送（本线 `talk_choice` 需要）；
    * 内层异常按 await 语义注入回外层；
    * 真挂起（`yield` 出非可等待对象 / 需要事件循环的 Future）→ `RuntimeError`。
    """
    to_send, to_throw = None, None
    while True:
        try:
            item = coro.throw(to_throw) if to_throw is not None else coro.send(to_send)
        except StopIteration as si:             # 本次产出（async generator 的 yield 值）
            return si.value
        if not inspect.isawaitable(item):
            raise RuntimeError("cmds_world：实现体真挂起（yield %r）——本驱动器只跑纯协程链" % (item,))
        if not hasattr(item, "send"):
            raise RuntimeError("cmds_world：实现体 await 了需要事件循环的对象（%s）" % type(item).__name__)
        try:
            to_send, to_throw = _resume(item), None
        except BaseException as exc:            # noqa: BLE001（按 await 语义回注）
            to_send, to_throw = None, exc


def _drain(agen) -> list:
    """同步取空「纯协程链的 async generator」→ 产出（已渲染行）列表。"""
    out = []
    while True:
        try:
            out.append(_resume(agen.__anext__()))
        except StopAsyncIteration:
            return out


def _shell(env):
    """宿主壳对象（桥接层经 `env.state["shell"]` 注入）——包内取宿主面的**唯一**口。"""
    return (env.state or {}).get("shell")


def _run(env, fn, *args) -> list:
    """跑一条既有实现体（`content/world_cmds.<fn>`）并同步取空 → 已渲染行。"""
    say = _Say(env.raw)
    out = _drain(fn(_shell(env), say, *args))
    return out or say.lines


def _svc(name):
    """宿主 `services.quests` 上的常量/函数（真源写法 `from ..services.quests import X`）。"""
    from . import profession_quests as _pq
    return getattr(_pq, name)


# ============================================================
# ② 包侧守卫：等待型副业互斥（本线自己的段；`content/guards.py` 别人段一字未改）
# ============================================================
def _no_prof_waiting(env, player=None):
    """等待型副业（垂钓/采集/挖掘）进行中 → 拦截（判定 + 措辞逐字 = 宿主旧
    `game/commands/base.py::no_prof_waiting` 装饰器）。返回非空 = 拦截并当作回话。"""
    shell = _shell(env)
    st = shell._prof_wait_state(env.group_id, env.uid) if shell is not None else None
    if st and st["finish"] > int(time.time()):
        left = st["finish"] - int(time.time())
        tname = _cat_life.PROF_WAIT_BASE.get(st["type"], (0, 0, "副业"))[2]
        return ("⏳ 你还在%s呢，再有 %d 秒完成！(完成后自动入包)\n"
                "💡 等待期间可以『背包』『属性』『任务』，但移动/探索/战斗要等%s结束～"
                % (tname, left, tname))
    return None


_GUARDS.setdefault("no_prof_waiting", _no_prof_waiting)


# ============================================================
# ③ 『任务』面板口径（原宿主 world.py 模块级两处，随 quest_view 一起进包）
# ============================================================
def _kill_prog_count(obj, prog):
    """v105 M19 P2：击杀进度聚合读——兼容旧存档老 key（v95.7 之前进度记
    monster['name'] 而非 obj['kill']，如『精英森林狼』），面板不再显示 0/N 孤儿计数。
    目标 key 有值用目标 key；为 0 时汇总其余包含目标名的历史 key。"""
    v = prog.get(obj["kill"], 0)
    if v == 0:
        v = sum(c for k, c in prog.items() if k != obj["kill"] and obj["kill"] in k)
    return v


# 任务目标类型 → 进度展示行（v101.3：加新目标类型 = 加一行，quest_view 零改动）
_OBJ_PROGRESS_LINES = {
    "kill":    lambda obj, prog: f"  进度：{_kill_prog_count(obj, prog)}/{obj['count']}",
    "collect": lambda obj, prog: f"  收集：{prog.get(obj['collect'], 0)}/{obj['count']}",
    "explore": lambda obj, prog: f"  前往：{MAP_BY_ID.get(obj['explore'], {}).get('name', '？')}",
    "talk":    lambda obj, prog: f"  交谈：与 {NPCS.get(obj['talk'], {}).get('name', '？')} 对话",
}


# ============================================================
# ④ 『任务』面板（原宿主 world.py:390-580 **逐字搬入**；渲染点 = 包内 T.text/T.static）
# ============================================================
@register("quest_view", guards=("hook:player",), params=("cmd=任务", "page"))
def quest_view(env) -> list:
    """『任务』：冒险日志（主线 + 支线分页 + 每日进度 + 师门考验 + 底部提示）。"""
    shell = _shell(env)
    group_id, qq_id = env.group_id, env.uid
    player = env.player
    if shell._is_redname(qq_id):
        return ["☠️ 你是红名！守卫不让你靠近任务板……(等红名消退再来)"]
    quests = db.get_quests(group_id, qq_id)
    lines = ["📜 【冒险日志】", "━━━━━━━━━━━━"]
    # 主线
    main_id = quests.get("main_quest")
    if main_id:
        mq = next((q for q in MAIN_QUESTS if q["id"] == main_id), None)
        # v104 M19：旧存档 main_quest 指向已下线 id（如 "q1"）→ 面板主线空白。
        # 与 _take_main_quest 同样的存档容错：重置回主线起点并落库。
        if not mq:
            quests["main_quest"] = "q1_1"
            quests["main_status"] = "pending"
            quests["main_progress"] = {}
            main_id = "q1_1"
            mq = next((q for q in MAIN_QUESTS if q["id"] == main_id), None)
            db.save_quests(group_id, qq_id, quests)
        if mq:
            _ginfo = NPCS.get(mq["giver"]) or ALL_WILD.get(mq["giver"]) or {}
            giver = _ginfo.get("name", "？")
            giver_map = _ginfo.get("map", "")
            giver_map_name = MAP_BY_ID.get(giver_map, {}).get("name", "？")
            lines.append(f"【主线】『{mq['name']}』")
            lines.append(f"  {mq['desc']}")
            st = quests.get("main_status", "pending")
            if st == "pending":
                lines.append(f"  ⏳ 未接取：去找 {giver}(在{giver_map_name})对话接取")
            elif st == "ready":
                # v95.25 #47b：主线交付=找 NPC 自动触发（与『交付任务』指令并存），不写死交付方式
                lines.append(f"  ✅ 目标达成！回去找 {giver} 交付")
            else:
                prog = quests.get("main_progress", {})
                obj = mq["objective"]
                # v101.3：目标类型展示查表化（kill/collect/explore/talk，顺序与原 if-elif 一致）
                # v169.9：主线 collect 面板实时查背包（对齐支线口径）——此前只读 main_progress
                # 存档，玩家采到材料但没对话过 NPC 时面板仍显示 0/N，误以为物品对不上（#143）
                if obj.get("collect"):
                    have = db.count_item(group_id, qq_id, obj["collect"])
                    need = obj.get("count", 1)
                    if have >= need:
                        lines.append(f"  ✅ 材料已齐：{obj['collect']} {have}/{need}（回去找 {giver} 交付）")
                    else:
                        lines.append(f"  收集：{have}/{need}")
                else:
                    for _k, _fn in _OBJ_PROGRESS_LINES.items():
                        if obj.get(_k):
                            lines.append(_fn(obj, prog))
                            break
    else:
        lines.append("【主线】已全部完成！🎊")
    # 支线（v101.25i3：已完成任务不进面板，鱼鱼：交了还显示）
    side = quests.get("side", {})
    side_items = [(sid, sq) for sid, sq in side.items() if sq.get("status", "active") != "done"]
    if side_items:
        lines.append("")
        lines.append("【支线】")
        raw = env.arg_text("任务")
        page = env.page(raw)
        page_items, pages, page = env.page_items(side_items, page, per_page=5)
        for i, (sid, sq) in enumerate(page_items, (page - 1) * 5 + 1):
            sqd = next((q for q in SIDE_QUESTS if q["id"] == sid), None)
            if not sqd:
                continue
            giver = (NPCS.get(sqd["giver"]) or ALL_WILD.get(sqd["giver"]) or {}).get("name", "？")
            st = sq.get("status", "active")
            obj = sqd["objective"]
            # v95.12：已交付支线显示已完成（不占可交付位）
            if st == "done":
                lines.append(f"{i:>2}. 『{sqd['name']}』[✅ 已完成]")
                continue
            # v127.7 排版：任务名单独一行（名字+状态），描述缩进下一行，目标进度行统一再缩进
            # v116 §3.4：进行中支线可放弃（主线不可弃），放弃提示统一放面板底部（v123e 去行尾冗余）
            # 收集型：实时按背包材料判断（v104 补测：复合目标同时显示击杀进度防误导）
            if obj.get("collect"):
                have = db.count_item(group_id, qq_id, obj["collect"])
                need = obj.get("collect_count") or obj.get("count", 1)  # v125.1 P2：s64 等 collect_count 无 count 的复合目标不再 KeyError
                prog = sq.get("progress", {})
                kill_txt = ""
                if obj.get("kill"):
                    kv = _kill_prog_count(obj, prog)  # v105 M19 P2：兼容旧档老 key 聚合
                    kill_txt = f"｜击杀：{kv}/{obj.get('count', 0)}"
                if have >= need:
                    lines.append(f"{i:>2}. 『{sqd['name']}』[✅ 可交{kill_txt}]")
                    lines.append(f"    {sqd['desc']}")
                    lines.append(f"    材料已齐！回去找 {giver} {_WC._deliver_hint(shell, sqd['giver'])}")
                else:
                    lines.append(f"{i:>2}. 『{sqd['name']}』[⏳{kill_txt}]")
                    lines.append(f"    {sqd['desc']}")
                    lines.append(f"    收集：{obj['collect']} {have}/{need}{kill_txt}")
                # v125.1 P2：复合目标（collect+use/find/explore，如 s53/s56/s64/s105）
                # 补显其余目标行，与 find/use 分支的 _obj_text_lines 展示口径一致
                # （收集/击杀行已在上方展示，过滤避免重复）
                for _t in _WC._obj_text_lines(shell, obj, st):
                    if _t.startswith(("收集", "击败")):
                        continue
                    lines.append(f"    {_t}")
                continue
            # v104 M20 P2：find 型（告示委托等）面板提示机制——在 XX 探索有概率遇到
            # （此前走通用兜底只显示 desc+[⏳]，玩家不知如何推进）
            if obj.get("find"):
                lines.append(f"{i:>2}. 『{sqd['name']}』[{'✅ 可交' if st == 'ready' else '⏳'}]")
                lines.append(f"    {sqd['desc']}")
                # v124.2 复合目标逐行显示（s18 kill+find 两行都展示）
                for _t in _WC._obj_text_lines(shell, obj, st):
                    lines.append(f"    {_t}")
                if st == "ready":
                    lines.append(f"    回去找 {giver} {_WC._deliver_hint(shell, sqd['giver'])}")
                continue
            # v124 use 型（使用指定物品达成）——同 find 处理
            if obj.get("use"):
                lines.append(f"{i:>2}. 『{sqd['name']}』[{'✅ 可交' if st == 'ready' else '⏳'}]")
                lines.append(f"    {sqd['desc']}")
                for _t in _WC._obj_text_lines(shell, obj, st):
                    lines.append(f"    {_t}")
                if st == "ready":
                    lines.append(f"    回去找 {giver} {_WC._deliver_hint(shell, sqd['giver'])}")
                continue
            mark = "✅ 可交" if st == "ready" else "⏳"
            lines.append(f"{i:>2}. 『{sqd['name']}』[{mark}]")
            lines.append(f"    {sqd['desc']}")
            if st == "ready":
                lines.append(f"    回去找 {giver} {_WC._deliver_hint(shell, sqd['giver'])}")
        # v127.7 翻页提示补全：上一页/下一页 + 总页数（此前只有下一页）
        if pages > 1:
            _nav = []
            if page > 1:
                _nav.append(f"『任务 {page-1}』上一页")
            if page < pages:
                _nav.append(f"『任务 {page+1}』下一页")
            lines.append(f"💡 {' | '.join(_nav)}(共 {pages} 页)")
        shell._record_list_state(qq_id, "任务", page, pages)
    else:
        lines.append("")
        lines.append("【支线】暂无——找镇上的 NPC 聊聊可能有意外收获")
    # 每日
    # v116 §3.4：daily 含 _completed/_repeat 元数据（active 任务清空后仍在）——
    # 只剩元数据 = 今日全部完成，按"已完成"分支展示；_completed 超额时给出计数。
    # v127.7：玩家从未领取（daily 为空）→ 提示『每日』领取，不再误报"已完成"。
    daily = quests.get("daily", {})
    active_keys = [k for k in daily if k not in _DAILY_META_KEYS]
    if active_keys:
        lines.append("")
        lines.append(T.static("daily.section"))
        _daily_n = 0  # v116 每日任务序号（仅计实际任务，跨元数据）
        for dkey, dq in daily.items():
            if dkey in _DAILY_META_KEYS:  # 跨天/计数元数据，跳过
                continue
            _daily_n += 1
            # v125.1 P2：序号用 _daily_n（仅计实际任务）——原用 enumerate 的 i 会把
            # _date/_completed/_repeat 元数据占位算进去（面板显示 4./5.，『放弃』按 1..N 对不上）
            need = _svc("daily_need")(dq)
            # v127.7 排版：每日任务名单独一行，描述缩进下一行
            if need is None:
                # v125.1 P2：无达标数定义时只显示实际进度，不再兜底假 99
                lines.append(T.text("daily.item", n=_daily_n, name=dq["name"]))
                lines.append(T.text("daily.item_plain", desc=dq["desc"],
                                    prog=dq.get("progress", 0)))
            else:
                lines.append(T.text("daily.item", n=_daily_n, name=dq["name"]))
                lines.append(T.text("daily.item_progress", desc=dq["desc"],
                                    prog=dq.get("progress", 0), need=need))
    else:
        lines.append("")
        if not daily:
            # v127.7 修复：从未领取（新号/跨天清空）→ 引导领取，不显示"已完成"
            lines.append(T.static("daily.never"))
        else:
            _done = int(daily.get("_completed", 0) or 0)
            if _done >= _svc("DAILY_LIMIT"):
                lines.append(T.text("daily.done_full", done=_done, limit=_svc("DAILY_LIMIT")))
            else:
                lines.append(T.text("daily.done_part", done=_done))
    # v101.30d #O1：师门考验追踪——对话树进行中时面板显示（playtest 小红：考验无面板条目）
    _MASTER_IDS = ("npc_herb_master", "npc_mine_master", "npc_fish_master", "npc_cook_master",
                   "npc_alchemy_master", "npc_craft_master", "npc_enhance_master", "npc_rune_master")
    ts = db.get_talk_state(group_id, qq_id)
    if ts and ts.get("npc") in _MASTER_IDS:
        _tnpc = NPCS.get(ts["npc"]) or {}
        lines.append("")
        lines.append("【师门考验】")
        lines.append(f"  ⏳ 正在接受【{_tnpc.get('name', '导师')}】的拜师考验，回复『继续』接着进行")
    lines.append("")
    # v127.1 每面板只抽 1 条随机提示（v123e 放弃/接取引导并入随机池）
    lines.append(shell._tip("quest"))
    return lines


# ============================================================
# ⑤ 其余 35 条：既有实现在 `content/world_cmds.py`，本模块只做「守卫 + 取参 + 登记」
# ============================================================
# 形参口径 = 宿主改造前逐条调用点（`_WC.<名>(self, event[, group_id, qq_id[, player]])`）。

@register("deed_view", guards=("hook:player",), params=("cmd=地契",))
def deed_view(env) -> list:
    """『地契』：房产查看 / 升级入口。"""
    return _run(env, _WC.deed_view, env.group_id, env.uid, env.player)


@register("deed_buy", guards=("hook:player",), params=("cmd=买房",))
def deed_buy(env) -> list:
    """『买房 <编号>』：购入地皮。"""
    return _run(env, _WC.deed_buy, env.group_id, env.uid, env.player)


@register("deed_sell", guards=("hook:player",), params=("cmd=卖房",))
def deed_sell(env) -> list:
    """『卖房』：退契返还。"""
    return _run(env, _WC.deed_sell, env.group_id, env.uid, env.player)


@register("go_home", guards=("hook:player", "hook:no_prof_waiting"), params=("cmd=回家",))
def go_home(env) -> list:
    """『回家』：进入自己的宅邸。"""
    return _run(env, _WC.go_home, env.group_id, env.uid, env.player)


@register("go_out", guards=("hook:player", "hook:no_prof_waiting"), params=("cmd=出门",))
def go_out(env) -> list:
    """『出门』：从宅邸返回城镇。"""
    return _run(env, _WC.go_out, env.group_id, env.uid, env.player)


@register("visit_home", guards=("hook:player", "hook:no_prof_waiting"), params=("cmd=拜访",))
def visit_home(env) -> list:
    """『拜访 <玩家>』：串门（对方宅邸）。"""
    return _run(env, _WC.visit_home, env.group_id, env.uid, env.player)


@register("home_storage", guards=("hook:player",), params=("cmd=仓库",))
def home_storage(env) -> list:
    """『仓库』：宅邸仓库（存/取）。"""
    return _run(env, _WC.home_storage, env.group_id, env.uid, env.player)


@register("home_storage_take", guards=("hook:player",), params=("cmd=取出",))
def home_storage_take(env) -> list:
    """『取出 <物品>』：从仓库取回。"""
    return _run(env, _WC.home_storage_take, env.group_id, env.uid, env.player)


@register("map_view", guards=("hook:player",), params=("cmd=地图",))
def map_view(env) -> list:
    """『地图』：当前地图总览（可前往 / 设施 / NPC）。"""
    return _run(env, _WC.map_view, env.group_id, env.uid, env.player)


@register("region_view", guards=("hook:player",), params=("cmd=区域",))
def region_view(env) -> list:
    """『区域』：当前区域可前往总览（v167.1）。"""
    return _run(env, _WC.region_view, env.group_id, env.uid, env.player)


@register("location_view", guards=("hook:player",), params=("cmd=位置",))
def location_view(env) -> list:
    """『位置』：精简位置面板（v128）。"""
    return _run(env, _WC.location_view, env.group_id, env.uid, env.player)


@register("hurry_view", guards=("hook:player", "hook:no_prof_waiting"), params=("cmd=赶路",))
def hurry_view(env) -> list:
    """『赶路』：赶路模式（v128）。"""
    return _run(env, _WC.hurry_view, env.group_id, env.uid, env.player)


@register("back_cmd", guards=("hook:player",), params=("cmd=返回",))
def back_cmd(env) -> list:
    """『返回 <地名>』：O74 返回提示。"""
    return _run(env, _WC.back_cmd, env.group_id, env.uid)


@register("ask_way", guards=("hook:player",), params=("cmd=问路",))
def ask_way(env) -> list:
    """『问路 <地名>』：O115 路线指引。"""
    return _run(env, _WC.ask_way, env.group_id, env.uid, env.player)


@register("move", guards=("hook:player", "hook:no_prof_waiting"), params=("cmd=前往", "page"))
def move(env) -> list:
    """『前往 <地名/序号>』『移动 <地名>』：移动 / 跨图 / 撞怪开战。"""
    return _run(env, _WC.move, env.group_id, env.uid)


@register("portal_view", guards=("hook:player",), params=("cmd=祭坛",))
def portal_view(env) -> list:
    """『祭坛』『方碑』：旅者方碑面板。"""
    return _run(env, _WC.portal_view, env.group_id, env.uid, env.player)


@register("portal_activate", guards=("hook:player",), params=("cmd=激活祭坛",))
def portal_activate(env) -> list:
    """『激活祭坛 [地名]』『激活』：激活方碑。"""
    return _run(env, _WC.portal_activate, env.group_id, env.uid, env.player)


@register("portal_travel", guards=("hook:player", "hook:no_prof_waiting"), params=("cmd=传送",))
def portal_travel(env) -> list:
    """『传送 <地名>』：付费传送（未激活则激活）。"""
    return _run(env, _WC.portal_travel, env.group_id, env.uid)


@register("quest_accept", guards=("hook:player",), params=("cmd=接取",))
def quest_accept(env) -> list:
    """『接取 [任务名/序号]』：主线/支线接取。"""
    return _run(env, _WC.quest_accept, env.group_id, env.uid)


@register("quest_abandon", params=("cmd=放弃",))
def quest_abandon(env) -> list:
    """『放弃 <序号>』：放弃支线/每日任务（主线不可弃）。"""
    return _run(env, _WC.quest_abandon, env.group_id, env.uid)


@register("daily", guards=("hook:player",), params=("cmd=每日",))
def daily(env) -> list:
    """『每日』：每日任务面板（含红名守卫）。"""
    return _run(env, _WC.daily, env.group_id, env.uid, env.player)


@register("time_cmd", guards=("hook:player",), params=("cmd=时间",))
def time_cmd(env) -> list:
    """『时间』：游戏内时段/天气。"""
    return _run(env, _WC.time_cmd, env.group_id, env.uid, env.player)


@register("wild_notes", guards=("hook:player",), params=("cmd=见闻录",))
def wild_notes(env) -> list:
    """『见闻录』：野外 NPC 见闻记录。"""
    return _run(env, _WC.wild_notes, env.group_id, env.uid, env.player)


@register("npc_quick_dialog", params=("cmd=<裸数字>",))
def npc_quick_dialog(env) -> list:
    """裸数字消费链：对话树选项 > 物品查看 > 移动模式 > 放行快捷指令（priority=100 在宿主声明）。"""
    return _run(env, _WC.npc_quick_dialog, env.group_id, env.uid)


@register("interact_prop", guards=("hook:player", "hook:no_prof_waiting"), params=("cmd=交互",))
def interact_prop(env) -> list:
    """『交互 [目标]』：场景可互动物。"""
    return _run(env, _WC.interact_prop, env.group_id, env.uid)


@register("talk_choice", guards=("hook:player",), params=("cmd=对话",))
def talk_choice(env) -> list:
    """『对话 [NPC/序号]』『找 <NPC>』：对话树（含异步动作链）。"""
    return _run(env, _WC.talk_choice, env.group_id, env.uid, env.player)


@register("turn_in", guards=("hook:player",), params=("cmd=交付任务",))
def turn_in(env) -> list:
    """『交付任务 [任务名]』：交任务结算。"""
    return _run(env, _WC.turn_in, env.group_id, env.uid, env.player)


@register("rest_camp", guards=("hook:player",), params=("cmd=休息",))
def rest_camp(env) -> list:
    """『休息』：篝火/野外休息。"""
    return _run(env, _WC.rest_camp, env.group_id, env.uid, env.player)


@register("rest", guards=("hook:player",), params=("cmd=住宿",))
def rest(env) -> list:
    """『住宿』：旅店恢复。"""
    return _run(env, _WC.rest, env.group_id, env.uid, env.player)


@register("reputation", guards=("hook:player",), params=("cmd=声望",))
def reputation(env) -> list:
    """『声望』：声望面板。"""
    return _run(env, _WC.reputation, env.group_id, env.uid, env.player)


@register("rep_shop", guards=("hook:player",), params=("cmd=声望商店",))
def rep_shop(env) -> list:
    """『声望商店 [页] [序号]』：声望兑换。"""
    return _run(env, _WC.rep_shop)


@register("camp_join", guards=("hook:player",), params=("cmd=加入阵营",))
def camp_join(env) -> list:
    """『加入阵营 <编号>』：阵营国战。"""
    return _run(env, _WC.camp_join)


@register("camp_task", guards=("hook:player",), params=("cmd=阵营任务",))
def camp_task(env) -> list:
    """『阵营任务』：阵营日常。"""
    return _run(env, _WC.camp_task)


@register("camp_shop", guards=("hook:player",), params=("cmd=阵营商店",))
def camp_shop(env) -> list:
    """『阵营商店 <编号>』：阵营商店。"""
    return _run(env, _WC.camp_shop)


@register("camp_rank", guards=("hook:player",), params=("cmd=阵营排行",))
def camp_rank(env) -> list:
    """『阵营排行』：阵营战功榜。"""
    return _run(env, _WC.camp_rank)


@register("chronicle", guards=("hook:player",), params=("cmd=编年史",))
def chronicle(env) -> list:
    """『编年史』：主线章节回顾。"""
    return _run(env, _WC.chronicle, env.group_id, env.uid, env.player)
