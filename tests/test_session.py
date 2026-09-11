# -*- coding: utf-8 -*-
"""会话骨架（`saintess_engine.session`）契约测试 —— **用假宿主端到端跑通一条命令**。

锁死的契约：
1. `PlainEvent` 满足命令层骨架用到的全部访问点（含可写 `message_str`）
2. `SessionAdapter`：群/发送者兜底 + `resolve_uid` 钩子（含异常容忍）
3. ★ **端到端**：用 `PlainEvent`（非 AstrBot 宿主）驱动一个命令基类，
   走通「守卫 → 剥参数 → 分页 → 回复」整条链
4. 零宿主 / 零游戏依赖

跑法：python tests/test_kit_session.py
"""
import asyncio
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
FW_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, FW_ROOT)

from saintess_engine.command import CommandBase, require_player  # noqa: E402
from saintess_engine.session import PlainEvent, PlainResult, SessionAdapter  # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        FAILURES.append(name)
        print(f"  ❌ {name}  {detail}")


print("== 1. PlainEvent 契约 ==")
ev = PlainEvent("背包 材料", group_id="g1", sender_id="u1")
check("get_message_str", ev.get_message_str() == "背包 材料")
check("get_group_id", ev.get_group_id() == "g1")
check("get_sender_id", ev.get_sender_id() == "u1")
check("plain_result 产出 PlainResult", isinstance(ev.plain_result("hi"), PlainResult)
      and ev.plain_result("hi").text == "hi")
check("stop_event 置位", (ev.stop_event() or ev.stopped) is True)
check("message_str 可写（快捷转发要用）", (setattr(ev, "message_str", "x") or ev.get_message_str()) == "x")
check("缺字段给 None（交给适配器兜底）",
      PlainEvent("x").get_group_id() is None and PlainEvent("x").get_sender_id() is None)
check("PlainResult 相等语义", PlainResult("a") == PlainResult("a") and PlainResult("a") != PlainResult("b"))

print("== 2. SessionAdapter ==")
ad = SessionAdapter()
check("空字段走兜底", ad.uid(PlainEvent("x")) == ("private", "unknown"), ad.uid(PlainEvent("x")))
check("正常取值", ad.uid(PlainEvent("x", group_id=1, sender_id=2)) == ("1", "2"))
check("默认不做标识换算（passthrough）", ad.resolve("openid_abc") == "openid_abc")

mapped = {"openid_abc": "10001"}
ad2 = SessionAdapter(resolve_uid=lambda raw: mapped.get(raw, raw))
check("resolve_uid 钩子生效", ad2.resolve("openid_abc") == "10001")
check("未命中 → 原样", ad2.resolve("其他") == "其他")


def _boom(raw):
    raise RuntimeError("映射表炸了")


ad3 = SessionAdapter(resolve_uid=_boom)
check("resolve 异常容忍（不影响主流程）", ad3.resolve("openid_x") == "openid_x")

ad4 = SessionAdapter(private_fallback="dm", unknown_fallback="anon")
check("可定制兜底值", ad4.uid(PlainEvent("x")) == ("dm", "anon"))


print("== 3. ★ 端到端：假宿主跑通一条命令 ==")


class Demo(CommandBase):
    """第三方视角的最小命令类：只覆盖钩子。"""
    register_hint = "请先注册"

    def __init__(self, players, adapter):
        self._players = players
        self._adapter = adapter
        self.log = []

    def _uid(self, event):
        return self._adapter.uid(event)          # ← 会话适配点

    def _player(self, group_id, qq_id):
        return self._players.get(qq_id)

    def _record_state(self, key, value):
        self.log.append((key, value))

    @classmethod
    def _build_static_handlers(cls):
        # 第三方宿主的静态兜底表（真实宿主会有注册表；这里演示最小用法）
        return [(re.compile(r"^背包"), "bag")]

    @require_player()
    async def bag(self, event):
        args = self._strip_cmd(event, "背包")
        items = ["木材", "矿石", "鱼干", "草药", "符文", "宝石", "布匹"]
        page_no = self._parse_page(args)
        page, pages, page_no = self._page_items(items, page_no, per_page=3)
        yield event.plain_result("、".join(page))
        self._record_list_state(event.get_sender_id(), "背包", page_no, pages)


async def _collect(agen):
    return [x async for x in agen]


def run(coro):
    return asyncio.run(coro)


adapter = SessionAdapter(resolve_uid=lambda raw: mapped.get(raw, raw))
cmd = Demo(players={"10001": {"name": "甲"}}, adapter=adapter)

# 3a. 未注册用户 → 守卫拦下（走 resolve_uid：openid → 账号 id，查不到玩家）
out = run(_collect(cmd.bag(PlainEvent("背包", group_id="g1", sender_id="openid_zzz"))))
check("★ 未注册被守卫拦下", [r.text for r in out] == ["请先注册"], out)

# 3b. 已注册用户（openid 经适配器翻译成 10001）→ 放行 + 分页
out = run(_collect(cmd.bag(PlainEvent("背包", group_id="g1", sender_id="openid_abc"))))
check("★ openid 经适配点翻译后放行", [r.text for r in out] == ["木材、矿石、鱼干"], out)
check("★ 分页状态已记录（key + 页码）",
      cmd.log and cmd.log[-1][0] == "last_list_openid_abc" and '"page": 1' in cmd.log[-1][1],
      cmd.log)

# 3c. 带页码的参数剥离 + 换页
out = run(_collect(cmd.bag(PlainEvent("背包 2", group_id="g1", sender_id="openid_abc"))))
check("★ 剥参数取页码 → 第二页", [r.text for r in out] == ["草药、符文、宝石"], out)

# 3d. 页码越界自动夹取（7 条目 / 每页 3 → 共 3 页，第 3 页只有 1 条）
out = run(_collect(cmd.bag(PlainEvent("背包 99", group_id="g1", sender_id="openid_abc"))))
check("★ 页码越界夹到末页", [r.text for r in out] == ["布匹"], out)

# 3e. 私聊（无 group_id）也能跑
out = run(_collect(cmd.bag(PlainEvent("背包", sender_id="openid_abc"))))
check("★ 私聊场景（group_id=None → 兜底）", [r.text for r in out] == ["木材、矿石、鱼干"], out)

# 3f. 快捷转发在假宿主上也能跑（换文本 + 恢复）
ev2 = PlainEvent("宝箱", group_id="g1", sender_id="openid_abc")
out = run(_collect(cmd._run_shortcut(ev2, "背包 2")))
check("★ 快捷转发（假宿主）产出第二页", [r.text for r in out] == ["草药、符文、宝石"], out)
check("★ 转发后恢复原文", ev2.message_str == "宝箱", ev2.message_str)


print("== 4. 零宿主 / 零游戏依赖 ==")
banned = []
src = os.path.join(FW_ROOT, "saintess_engine", "session")
for dirpath, dirs, fs in os.walk(src):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for f in fs:
        if not f.endswith(".py"):
            continue
        for line in open(os.path.join(dirpath, f), encoding="utf-8").read().splitlines():
            st = line.strip()
            if not st.startswith(("import ", "from ")):
                continue
            parts = st.split()
            mod = parts[1].split(".")[0] if len(parts) > 1 else ""
            if mod in ("game", "astrbot"):
                banned.append(f"{f}: {st}")
check("不 import 游戏包 / 宿主", not banned, banned)

print(f"\n=== 结果 PASS={PASS} FAIL={FAIL} ===")
if FAILURES:
    print("失败项：" + ", ".join(FAILURES))
sys.exit(1 if FAIL else 0)
