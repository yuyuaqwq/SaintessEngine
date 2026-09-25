# -*- coding: utf-8 -*-
"""命令层骨架（`saintess_engine.command`）契约测试 —— 用**假宿主**驱动。

锁死的契约：
1. 分页/页码：越界夹取、空列表、非数字参数
2. 文本剥离：平台前缀（At/引用）+ 指令词 + 别名（含「别名==指令」跳过）
3. 提示抽取：两级回退（cat → common）+ emoji 条目不叠前缀
4. 守卫：无角色拦截并给文案；有角色放行；战斗守卫同理
5. 指令正则：零宽匹配默认跳过（防日常聊天全命中）
6. handler 路由：静态表命中 → `hit[0]` 是 **handler 名**（兼容契约）；
   宿主探测优先于静态表
7. 快捷转发：临时换消息文本、结束恢复；找不到给提示；执行异常不抛
8. 列表视图状态：key 格式 + JSON 内容 + 空 qq_id 跳过
9. 零宿主 / 零游戏依赖

跑法：python tests/test_kit_command.py
"""
import asyncio
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, FW_ROOT)

from saintess_engine.command import (  # noqa: E402
    CommandBase, HandlerHit, PatternSet, matches_any, page_items, parse_page,
    pick_tip, require_battle, require_player, strip_command,
)
from saintess_engine.command.text import strip_at_prefix  # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")


# ------------------------------------------------------------------ 假宿主
class FakeResult:
    def __init__(self, text):
        self.text = text

    def __repr__(self):
        return f"FakeResult({self.text!r})"


class FakeEvent:
    def __init__(self, msg=""):
        self.message_str = msg
        self._stopped = False

    def get_message_str(self):
        return self.message_str

    def plain_result(self, text):
        return FakeResult(text)

    def stop_event(self):
        self._stopped = True


class DemoCmds(CommandBase):
    """一个「游戏」用它来写自己的命令类：只覆盖钩子，方法名不动。"""
    register_hint = "NO_CHAR"
    battle_none_hint = "NO_ENEMY"
    command_aliases = ("我的角色", "位置")
    tip_fallback = ("兜底提示",)

    def __init__(self, player=None, in_battle=False):
        self._p = player
        self._b = in_battle
        self.records = []

    def _uid(self, event):
        return ("g1", "q1")

    def _player(self, group_id, qq_id):
        return self._p

    def _in_any_battle(self, group_id, qq_id):
        return self._b

    def _tip_pool_map(self):
        return {"move": ["去别处看看"], "common": ["看看『帮助』"], "emo": ["⚔️ 打怪去"]}

    def _record_state(self, key, value):
        self.records.append((key, value))

    @classmethod
    def _build_command_regex_strings(cls):
        # 末条是**真零宽**正则（空模式，能匹配任意文本但 group(0) 为空）——
        # 模拟「仅用于挂载」的正则；必须被 skip_empty 跳过，否则日常聊天全命中
        return [r"^背包", r"^技能列表", r""]

    @classmethod
    def _build_static_handlers(cls):
        return [(re.compile(r"^返回\s*(\S+)"), "back_cmd"),
                (re.compile(r"^问路\s*(\S+)"), "ask_way")]

    async def back_cmd(self, event, *a, **kw):
        yield event.plain_result(f"前往 {event.message_str}")

    async def ask_way(self, event, *a, **kw):
        yield event.plain_result(f"路线 {event.message_str}")


async def _collect(agen):
    return [x async for x in agen]


def run(coro):
    return asyncio.run(coro)


# ================================================================ 1. 分页
print("== 1. 分页 ==")
items = list(range(12))
page, pages, p = page_items(items, 2, per_page=5)
check("page_items 第二页切片", page == [5, 6, 7, 8, 9] and pages == 3 and p == 2, (page, pages, p))
page, pages, p = page_items(items, 99, per_page=5)
check("页码越界向上夹取", p == 3 and page == [10, 11], (page, pages, p))
page, pages, p = page_items(items, 0, per_page=5)
check("页码越界向下夹取", p == 1, (page, pages, p))
page, pages, p = page_items([], 3)
check("空列表 → 1 页且空切片", page == [] and pages == 1 and p == 1, (page, pages, p))
check("parse_page 数字", parse_page("7") == 7)
check("parse_page 非数字 → 1", parse_page("abc") == 1 and parse_page(None) == 1)


# ================================================================ 2. 文本剥离
print("== 2. 文本剥离 ==")
check("剥 At 前缀", strip_at_prefix("[At:某人] 背包") == "背包")
check("剥 全体成员 前缀", strip_at_prefix("[At:全体成员] 背包") == "背包")
check("剥 引用消息 前缀", strip_at_prefix("[引用消息 你好] 背包") == "背包")
check("剥指令词取参数", strip_command("背包 材料", "背包") == "材料")
check("剥别名", strip_command("我的角色 属性", "角色", ("我的角色",)) == "属性")
check("别名==指令时跳过（不自己剥自己）",
      strip_command("我的角色 x", "我的角色", ("我的角色",)) == "x")
check("先剥前缀再剥指令", strip_command("[At:某人] 背包 材料", "背包") == "材料")
check("都不命中 → 原样", strip_command("随便聊聊", "背包") == "随便聊聊")


# ================================================================ 3. 提示
print("== 3. 提示抽取 ==")
pool = {"move": ["去别处看看"], "common": ["看看『帮助』"], "emo": ["⚔️ 打怪去"]}
check("命中分类", pick_tip(pool, "move") == "💡 去别处看看")
check("分类缺失 → common 回退", pick_tip(pool, "nope") == "💡 看看『帮助』")
check("emoji 条目不加前缀", pick_tip(pool, "emo") == "⚔️ 打怪去")
check("全空 → 兜底文案", pick_tip({}, "x", fallback=("兜底",)) == "💡 兜底")
check("全空且无兜底 → **空串**（引擎不带玩家文案；调用方据此跳过该行）",
      pick_tip({}, "x") == "")


# ================================================================ 4. 守卫
print("== 4. 守卫装饰器 ==")


class _Cmds(DemoCmds):
    @require_player()
    async def need_char(self, event, *a, **kw):
        yield event.plain_result("ok-char")

    @require_battle(hint="（技能列表查看）")
    async def need_battle(self, event, *a, **kw):
        yield event.plain_result("ok-battle")


m = _Cmds(player=None)
out = run(_collect(m.need_char(FakeEvent("x"))))
check("无角色被拦 + 用 register_hint 文案", [r.text for r in out] == ["NO_CHAR"], out)
m._p = {"name": "甲"}
out = run(_collect(m.need_char(FakeEvent("x"))))
check("有角色放行", [r.text for r in out] == ["ok-char"], out)

m2 = _Cmds(player={"name": "甲"}, in_battle=False)
out = run(_collect(m2.need_battle(FakeEvent("x"))))
check("无战斗被拦 + battle_none_hint + hint 追加",
      [r.text for r in out] == ["NO_ENEMY（技能列表查看）"], out)
m2._b = True
out = run(_collect(m2.need_battle(FakeEvent("x"))))
check("战斗放行", [r.text for r in out] == ["ok-battle"], out)


# ================================================================ 5. 指令正则
print("== 5. 指令正则集合 ==")
ps = DemoCmds.command_patterns()
check("PatternSet 编译命中", ps.matches("背包"))
check("零宽/仅挂载正则不命中纯文本", not ps.matches("随便聊聊"))
check("skip_empty=False 时零宽正则会命中（反证 skip_empty 生效）",
      ps.matches("随便聊聊", skip_empty=False))
check("matches_any 直调", matches_any("技能列表", ps.patterns()))
check("reset 后仍可编译", (ps.reset() or ps.matches("背包")))


# ================================================================ 6. handler 路由
print("== 6. handler 路由 ==")
m3 = _Cmds()
hit = m3._find_handler("返回 橡木镇")
check("静态表命中", hit is not None and hit.handler_name == "back_cmd", hit)
check("★ hit[0] 是 handler 名字符串（兼容契约）", hit[0] == "back_cmd", hit[0])
check("★ 既有测试写法可用（getattr(hit[0],'handler_name',hit[0])）",
      getattr(hit[0], "handler_name", hit[0]) == "back_cmd")
check("prebound=True（静态表取绑定方法）", hit.prebound is True)
check("未命中 → None", m3._find_handler("无关文本") is None)
check("空白输入 → None", m3._find_handler("   ") is None)


class WithHost(_Cmds):
    """模拟宿主注册表探测：优先于静态表。"""

    def _host_handler_finder(self):
        def finder(text):
            if text.startswith("宿主"):
                return HandlerHit("host_cmd", lambda ev: None, False, raw="md")
            return None
        return finder


m4 = WithHost()
check("宿主探测优先", m4._find_handler("宿主指令").handler_name == "host_cmd")
check("宿主未命中 → 回退静态表", m4._find_handler("返回 X").handler_name == "back_cmd")


# ================================================================ 7. 快捷转发
print("== 7. 快捷转发 ==")
ev = FakeEvent("返回 铁港城")
out = run(_collect(m3._run_shortcut(ev, "返回 铁港城")))
check("转发命中并产出", [r.text for r in out] == ["前往 返回 铁港城"], out)
check("★ 转发后恢复原消息文本", ev.message_str == "返回 铁港城", ev.message_str)

ev2 = FakeEvent("原文本")
out = run(_collect(m3._run_shortcut(ev2, "无法识别的东西")))
check("未命中给提示", out and "无法识别" in out[0].text, out)
check("未命中也恢复文本", ev2.message_str == "原文本", ev2.message_str)


class Boom(_Cmds):
    async def back_cmd(self, event, *a, **kw):
        raise RuntimeError("炸了")
        yield  # pragma: no cover


out = run(_collect(Boom()._run_shortcut(FakeEvent("x"), "返回 X")))
check("执行异常不抛、给错误提示", out and "执行出错" in out[0].text, out)


class Coro(_Cmds):
    async def back_cmd(self, event, *a, **kw):
        return event.plain_result("协程结果")


out = run(_collect(Coro()._run_shortcut(FakeEvent("x"), "返回 X")))
check("兼容 coroutine handler", [r.text for r in out] == ["协程结果"], out)


# ================================================================ 8. 列表状态
print("== 8. 列表视图状态 ==")
m5 = _Cmds()
m5._record_list_state("q9", "背包 材料", 2, 5)
key, val = m5.records[0]
check("key 格式", key == "last_list_q9", key)
check("内容为 JSON {cmd,page,pages}",
      json.loads(val) == {"cmd": "背包 材料", "page": 2, "pages": 5}, val)
m5._record_list_state("", "背包", 1, 1)
check("空 qq_id 跳过", len(m5.records) == 1, m5.records)


class BoomStore(_Cmds):
    def _record_state(self, key, value):
        raise RuntimeError("存储炸了")


try:
    BoomStore()._record_list_state("q1", "x", 1, 1)
    store_ok = True
except Exception:                                            # noqa: BLE001
    store_ok = False
check("存储失败静默（附加功能不阻断）", store_ok)


# ================================================================ 9. 事件小工具
print("== 9. 宿主事件小工具 ==")
ev3 = FakeEvent()
CommandBase._stop_event_safe(ev3)
check("stop_event 正常调用", ev3._stopped)


class NoStop:
    pass


CommandBase._stop_event_safe(NoStop())      # 不应抛
check("无 stop_event 属性不抛", True)


# ================================================================ 10. 零依赖
print("== 10. 零宿主 / 零游戏依赖 ==")
banned = []
src = os.path.join(FW_ROOT, "saintess_engine", "command")
for dirpath, dirs, fs in os.walk(src):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for f in fs:
        if not f.endswith(".py"):
            continue
        for line in open(os.path.join(dirpath, f), encoding="utf-8").read().splitlines():
            s = line.strip()
            if not s.startswith(("import ", "from ")):
                continue
            parts = s.split()
            mod = parts[1].split(".")[0] if len(parts) > 1 else ""
            if mod in ("game", "astrbot"):
                banned.append(f"{f}: {s}")
check("不 import 游戏包 / 宿主", not banned, banned)

print(f"\n=== 结果 PASS={PASS} FAIL={FAIL} ===")
if FAILURES:
    print("失败项：" + ", ".join(FAILURES))
sys.exit(1 if FAIL else 0)
