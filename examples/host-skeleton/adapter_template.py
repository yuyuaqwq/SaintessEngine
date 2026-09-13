# -*- coding: utf-8 -*-
"""官方宿主骨架 —— **接你自己的 IM**：把平台事件映射成契约那 7 个字段（模板，非可运行）。

照这个文件抄三件事：
  ① `recv()`   平台事件 → `ctx`（7 个字段，多给的字段骨架忽略）
  ② `load_player` / `save_player`  换成你的存储（SQLite/Redis/MySQL 都行；形状仍是普通 dict）
  ③ `say()`    把已渲染文本投递回平台（群 → group_id，私聊 → None）

    from main import Host
    from adapter_template import PlatformAdapter          # 你的实现
    from store_sqlite import SQLiteStore
    host = Host(PlatformAdapter(bot=..., store=SQLiteStore("players.db")),
                package_dir="<包目录>", scenario=..., seed=None)
    host.boot(); host.serve_forever()                     # 或在你的事件回调里调 host.handle(ctx)

平台给的常见差异（都在适配器里吸收，骨架不感知）
------------------------------------------------
* **@ 标记**：平台的 `[At:123]` / `<at id=...>` 一律剥掉后放 `text`，被 @ 的 id 放 `at`。
* **群 vs 私聊**：群消息给 `group_id`（字符串），私聊给 `None`；`is_group` 自己判。
* **消息时间**：平台时间戳放 `ts`（墙上时间秒）；没有就用 `clock()` 钩子补。
* **原始事件**：整条原始对象塞 `raw`（骨架不解释，只透传给需要的扩展）。
* **多段回话**：`say()` 一次一段，调用方自己拼；图片/语音走可选钩子（契约 §二）。
"""
from __future__ import annotations

import random
import re
import time

_AT = re.compile(r"\[At:[^\]]+\]|<at[^>]*>")        # 平台 @ 标记（按你的平台改）


class PlatformAdapter:
    """示例骨架：把平台事件队列翻译成契约字段（真实接入时替换 TODO 三处）。"""

    def __init__(self, bot, store, *, seed=None):
        self.bot = bot                  # 你的平台客户端（发消息用）
        self.store = store              # 宿主自己的存储（store_sqlite.SQLiteStore 或你的）
        self.seed = seed
        self._stop = False

    # ------------------------------------------------------------ ① 收消息 / 认人
    def recv(self):
        event = None                    # TODO：从平台事件队列取一条（阻塞或非阻塞都行）
        if event is None:
            return None                 # None = 没有新消息（骨架自旋，稍后再问）
        raw_text = getattr(event, "message", "") or ""
        return {
            "uid": str(getattr(event, "sender_id", "")),          # 平台用户唯一 id
            "text": _AT.sub("", raw_text).strip(),                # 已去平台标记的纯文本
            "group_id": str(getattr(event, "group_id", "") or "") or None,
            "is_group": bool(getattr(event, "group_id", None)),
            "at": [str(x) for x in (getattr(event, "at_ids", None) or [])],
            "ts": float(getattr(event, "ts", 0) or time.time()),
            "raw": event,                                         # 平台原始事件对象
        }

    # ------------------------------------------------------------ ② 存档读写
    def load_player(self, uid: str):
        return self.store.load_player(uid)                        # dict | None（None = 新玩家）

    def save_player(self, uid: str, data: dict) -> None:
        self.store.save_player(uid, data)                         # 改完必存

    # ------------------------------------------------------------ ③ 回话出口
    def say(self, to: dict, text: str) -> None:
        if not text:
            return
        if to.get("group_id"):                                    # TODO：调你的平台 SDK
            self.bot.send_group(str(to["group_id"]), text)
        else:
            self.bot.send_private(str(to["uid"]), text)

    # ------------------------------------------------------------ 可选钩子（契约 §二）
    def clock(self) -> float:
        return time.time()                                        # 没有平台时间就用自己的

    def rng(self) -> random.Random:
        return random.Random(self.seed)                            # 给了就能"同种子复现一场"

    def on_tlog(self, record: dict) -> None:
        self.store.save_blob("tlog:%s" % record.get("ts"), record)  # 落库属宿主（换成你的表）

    def load_blob(self, key):
        return self.store.load_blob(key)

    def save_blob(self, key, value):
        self.store.save_blob(key, value)

    def should_stop(self) -> bool:
        return self._stop                                          # 平台断开/收到停机信号
