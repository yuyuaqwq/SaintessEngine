# -*- coding: utf-8 -*-
"""编辑器「试玩」壳（`PlayShell`）—— 引擎**通用半边** + 试玩平台的**记录式半边**。

它是什么
--------
包内 `content/**` 的实现体需要一个「平台能力面」对象（一律经 `env.state["shell"]` 取），
该对象的**通用半边**（取件管道 / 包内内容半边转发 / 环境位）住在引擎
`saintess_engine.host.shell.ShellBase`。本文件只补**试玩这一侧**剩下的那一小层：

| 面 | 落点 |
|---|---|
| 取件管道 · 包内转发 · `_gm_whitelist` / `_is_gm` / `_server_down*` | 引擎 `ShellBase`（父类） |
| 平台动作 `_broadcast` / `_notify_hermes` / `_deliver` | **本文件**：落 `events` 记录，零网络副作用 |
| 平台身份 `_identity_ops` · 窥探投递 `_spy_ops` | **本文件**：fail-closed 点名报错（见下） |

为什么身份面是 fail-closed 而不是本地兜底
------------------------------------------
编辑器里**没有 openid 来源**（那是 QQ 平台的映射件）。给一个本地替身 = 第二份实现，
与 P0-7 已判「不留兜底」的口径相左，且会让「编辑器里能跑」与「线上能跑」混为一谈。
故 `/绑定身份` 与 `gm_窥探` 在试玩里**大声失败**（点名报错，不静默、不假装成功）；
QQ 侧一字未动（`host/shell.py::HostShell` 才是这两条的真落点）。
（该口径已登记在台账 §5 T7-A 待鱼鱼一句确认；不确认也按 fail-closed 落地。）

零平台 / 零包名
----------------
本文件零平台 import（无 astrbot / 无 openid / 无发送面）、零包名：所有内容侧取值都经
父类 `_sub(<半边名>)` 走包契约。写死的内容 = 0。
"""
from __future__ import annotations

from saintess_engine.host.shell import ShellBase

__all__ = ["PlayShell"]


class PlayShell(ShellBase):
    """试玩壳：`env.state["shell"]`（装配处注入 `pkg` 与 `events`）。"""

    logger_name = "editor.play"

    # ============================================================
    # 平台动作（记录，不外发）
    # ============================================================
    async def _broadcast(self, text, exclude_group=None):
        """全服广播 → 试玩里只落记录（无网络副作用）。"""
        self._events.append({"action": "broadcast", "text": str(text),
                             "exclude": str(exclude_group or "")})

    async def _notify_hermes(self, group_id, qq_id, content, msg_type):
        """Hermes webhook 通知 → 试玩里只落记录。"""
        self._events.append({"action": "hermes", "content": str(content),
                             "msg_type": str(msg_type)})

    async def _deliver(self, group_id, text):
        """单群投递（`_broadcast` 的底层口）→ 试玩里只落记录。"""
        self._events.append({"action": "deliver", "group_id": str(group_id),
                             "text": str(text)})

    # ============================================================
    # 平台能力口（编辑器无平台身份 / 无投递面 ⇒ fail-closed）
    # ============================================================
    def _identity_ops(self):
        raise RuntimeError(
            "试玩通道没有平台身份映射面（`_identity_ops`）：编辑器里没有 openid 来源，"
            "该命令在试玩里停用（QQ 侧不受影响）")

    def _spy_ops(self):
        raise RuntimeError(
            "试玩通道没有窥探投递平台面（`_spy_ops`）：编辑器里没有实录目录 / 合并转发件，"
            "该命令在试玩里停用（QQ 侧不受影响）")
