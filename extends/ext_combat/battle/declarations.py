# -*- coding: utf-8 -*-
"""battle/declarations —— 数据行 → `actor["triggers"]` 的**声明编译器**（生产端形状）。

形状
====
一条声明 = **事件名（契约词汇，取自 `EVENTS`）** + **不透明载荷（原对象）**。
编译器只做三件事：把行表分桶到事件名、按去重键幂等写入宿主容器、对照 `EVENTS` 校验事件名。
翻译（数据行 → 载荷）、动词分发（`effects`）、触发（`fire()`）都不在它这里。

  行表两形态：
    · mapping `{事件名: [载荷, …]}` —— **主形态**（E5-4 实测：8 个内容文件构造编译器、
      23 处调用点用此形态；键就是引擎事件名）
    · list `[{"event": 事件名, "action": 动词, …}]` 或 `[Declaration(事件名, 载荷)]`
  两种形态的行键都**必须是引擎事件名**：旧事件名 → 引擎事件名的翻译是内容协议，
  放在内容侧展开（2026-09-26「E5-4 收口 2c」起本模块**不再收** `map_event` 注入面）；
  收口经过见文末「E5-4 登记」。
  宿主容器：`actor[host_key]`（默认契约词 `triggers`），与 `fire()` 的读法对齐。

对外：`Declaration` / `Compiler`（`compile` / `validate` / `unknown_name` / `mount` /
`purge` / `events_of`）· `compile_rows` · `mount`。**不进 battle 门面**（子模块直取：
`from ext_combat.battle.declarations import Compiler`），与设计稿「本稿拍板不加导出」一致。

口径分歧（照 `U1-D2_DESIGN.md` §4.3 逐条；**故意不统一**）
========================================================
① 去重键五种：`(action,key)` / `key` / `action` / `type` / 无。键的语义是「同一效果的身份由
   什么决定」，统一成一个键 = 改行为（重复挂 or 误合并）。引擎只接 `key_of` 回调。
② 写策略四种：`replace`（命中就地浅盖）/ `keep`（命中保留既有）/ `append`（命中留旧再追加）/
   `prepend`（未命中前插桶首 = 执行序；命中不重排）。前插与就地浅盖是执行序 / 参数语义，不可统一。
③ `_owner` 两处注入：挂载期（`owner` + `owner_key`，`setdefault` 幂等）与消费期（`fire()` 兜底）。
   两处都留：挂载期那份让装配后、开战前的读者也能拿到归属；消费期那份是兜底。
④ 事件名校验统一给到全部调用点（含内容侧做过旧名迁移的那一层），且**只告警不改行为**。
⑤ 未知事件名：告警 + 放行，不抛。fail-closed 会当场炸掉整场装配（外层逐步吞异常更糟）。
   与消费端 `fire()` 的「静默忽略」配套（生产端留痕 + 消费端静默）。
⑥ `compile` 不排序事件桶（dict 插入序）；但桶内**列表序**是执行序，必须保序。
⑦ 两输入形态并存：mapping 是现状数据形态（改它 = 改数据表），list 是更通用的新形态；两种都收。
⑧ `action_key` 只用于读动词字段（`action_of`）与去重键，**不用于分发** —— 分发是 `effects` 的事。

为什么不改 fire()
=================
消费端已经在位且口径是刻意的：`fire()` 对不在 `EVENTS` 的事件名**静默 return**（防拼写漂移），
本批只补**生产端**校验。改 `fire()`（例如未知名抛错）会让「装错一个事件名」从静默变成断链，
且会动 `effect_triggers.py`（共享冻结面）。生产端告警 + 消费端静默 = 配套，不是遗漏。

为什么默认不去重
================
`key_of` 默认 `None`（= 不去重）是最保守的默认：默认行为必须是「明确不合并」。
若默认 `(action,key)`，会把现状里**有意非幂等**的装配由幂等悄悄改写（装备三流合并靠外层
保险丝只跑一次）—— 那是改行为。去重键是内容侧取值，必须显式给。

明确不做
========
· 数据行 → 载荷的翻译（`_translate_*` 族）—— 取值，留内容侧
· 旧事件名迁移表（12 键 / 5 键）—— 内容协议，内容侧自己展开（**引擎无注入面**）
· `EVENTS` 的定义改造与 `fire()` / `apply_effects` 的改造 —— 消费端已在位，一字节不动
· 效果动词实现（各族 `we_*` / `team_*` / 乘区动词 …）—— 取值，留内容侧
· 「倍率回落撤声明」这类业务语义 —— 编译器只提供 `purge`，语义留在内容侧
· 动词分发（`type` 优先还是 `action` 优先）—— `effects` 的事
· 与 `conditions` 的 fail-closed 校验合并 —— 两者校验对象与失败语义都不同


E5-4 登记（2026-09-26 · **已收口**：`map_event` 注入面删除）
=========================================================
E5 批次原计划「迁内容 → 删 `map_event`（参数 + 校验 + 注释 + wiki 一起清）」，2026-09-26 一度
**撤回**（前提失准 + 冻结线卡点），随后按五步收口到位：

① 前提纠偏：注入 `map_event` 的只有 **2 个**内容文件（`content/mech/equip.py` /
   `content/mech/food_proc.py`）；mapping 形态本身是 **8 个文件 / 23 处调用点**的主形态
   （键已是引擎事件名）—— 该删的是**注入面**，不是 mapping 形态。
② 冻结线先退场：包内 `tests/test_u1d2_triggers_frozen.py` / `test_u1d2_triggers_extra_frozen.py`
   把这一层当不变量钉住 ⇒ 先宣告 `equip.map_event` 段退出冻结（SEGMENTS 12→11、E 栏 6→5、
   旧名网格改「表声明锚定」），动内容之前先把线划出来。
③ 内容侧收口（包 `448d990`）：old→engine 展开搬进内容侧单点（翻译器出口 / 装配路径），
   未知名告警改挂 `Compiler(on_unknown=…)`（反静默失效保住）—— 包内产品码再无一处
   `map_event=` 注入。
④ 引擎侧删面（本批）：`map_event` 形参 + 类型校验 + `_map_event` 槽 + `_targets()` 展开口
   一并删除；`_payloads()` 的 mapping 桶值校验**保留**（mapping 行表是主形态，与旧名无关）。
⑤ 重生成门禁：包侧生成器重采 aux（引擎侧 aux 读活引擎）＋两处补丁/断言签名跟新形参。

⟹ 收口后**唯一**的旧名通道 = `翻译器（写旧名） → 内容侧展开 → 本模块（只收引擎名）`。
删面的判据不是「少一个功能」，而是**单一真源**：旧名映射的真源在内容侧（数据表
`content/data/equip_event_map.json` + 翻译器出口），引擎侧不再有第二个入口，
也就不会再出现「两边口径各自漂移」这类连环账。
"""
from .effect_triggers import EVENTS

__all__ = ["Declaration", "Compiler", "compile_rows", "mount"]

# 四种写策略词（引擎自己的协议词，不含任何内容取值）
_MERGE_WORDS = ("replace", "append", "prepend", "keep")


def _name(value, label):
    """注入的名字类形参：必须是非空 str（fail-closed，不猜默认）。"""
    if not isinstance(value, str):
        raise TypeError(f"{label} 必须是非空 str")
    if not value:
        raise ValueError(f"{label} 必须是非空 str")
    return value


class Declaration:
    """一条声明：事件名（契约词汇）+ 不透明载荷（原对象）+ 可选的逐条写策略。

    逐条写策略（`key_of` / `merge` / `match`）留空 = 用 `Compiler` 那一层或不注入。
    载荷**完全不透明**：引擎不读它的键，也不拷贝它（`payload` 属性就是传入的那个对象）。
    """

    __slots__ = ("_event", "_payload", "key_of", "merge", "match")

    def __init__(self, event, payload, *, key_of=None, merge=None, match=None):
        if not isinstance(event, str):
            raise TypeError("event 必须是非空 str")
        if not event:
            raise ValueError("event 必须是非空 str")
        if key_of is not None and not callable(key_of):
            raise TypeError("key_of 必须可调用或 None")
        if merge is not None and merge not in _MERGE_WORDS:
            raise ValueError(f"merge 未登记：{merge!r}")
        if match is not None and not callable(match):
            raise TypeError("match 必须可调用或 None")
        self._event = event
        self._payload = payload
        self.key_of = key_of
        self.merge = merge
        self.match = match

    @property
    def event(self):
        """事件名（契约词汇，取自引擎事件全集）。"""
        return self._event

    @property
    def payload(self):
        """不透明载荷（原对象，不拷贝）。"""
        return self._payload

    def __repr__(self):
        return f"Declaration({self._event!r}, {self._payload!r})"


class Compiler:
    """数据行 → `actor[host_key]` 的声明编译器（幂等写入 + 事件名校验）。

    构造 O(1)：只校验注入面 + 存引用，**不遍历行表、不建索引、不缓存**。
    引擎零取值：事件名、去重键、写策略、载荷、未知名策略全部由调用方给。
    """

    __slots__ = ("_events", "_key_of", "_on_unknown",
                 "_host_key", "_owner_key", "_event_key", "_action_key")

    def __init__(self, *, events=None, key_of=None, on_unknown=None,
                 host_key="triggers", owner_key=None, event_key="event",
                 action_key="action"):
        if events is None:
            self._events = frozenset(EVENTS)          # 引擎自己的协议：可默认取
        else:
            if isinstance(events, str) or not hasattr(events, "__iter__"):
                raise TypeError("events 必须是非 str 的字符串序列")
            got = tuple(events)
            for one in got:
                if not isinstance(one, str) or not one:
                    raise TypeError("events 每一项必须是非空 str")
            self._events = frozenset(got)             # 给空序列 = 不做未知名校验
        if key_of is not None and not callable(key_of):
            raise TypeError("key_of 必须可调用或 None")
        if on_unknown is not None and not callable(on_unknown):
            raise TypeError("on_unknown 必须可调用或 None")
        self._key_of = key_of
        self._on_unknown = on_unknown
        self._host_key = _name(host_key, "host_key")
        self._owner_key = None if owner_key is None else _name(owner_key, "owner_key")
        self._event_key = _name(event_key, "event_key")
        self._action_key = _name(action_key, "action_key")

    # ---- 只读注入面（诊断 / 内容侧自检）----------------------------------
    @property
    def events(self):
        """引擎认的事件全集（frozenset；空 = 不做未知名校验）。"""
        return self._events

    @property
    def host_key(self):
        """宿主容器键（默认契约词 `triggers`）。"""
        return self._host_key

    @property
    def owner_key(self):
        """挂载期归属字段名（None = 不注入）。"""
        return self._owner_key

    @property
    def event_key(self):
        """list 形态行的事件名字段名。"""
        return self._event_key

    @property
    def action_key(self):
        """动词字段名（只给 `action_of` 与去重键用，不分发）。"""
        return self._action_key

    # ---- 事件名判定 ------------------------------------------------------
    def unknown_name(self, event):
        """事件名不在引擎全集里 → True。**全集为空 → 恒 False**（取不到 = 不告警）。"""
        if not self._events:
            return False
        return event not in self._events

    # ---- 行表展开（保序：外层行表序 → 桶内追加序）------------------------
    def _payloads(self, payloads, event):
        if isinstance(payloads, (list, tuple)):
            return payloads
        raise TypeError(f"mapping 形态的桶值必须是 list/tuple：{event!r}")

    def _pairs(self, rows):
        """行表 → `(事件名, 载荷, Declaration|None)` 保序流。"""
        if isinstance(rows, dict):
            for event, payloads in rows.items():
                for payload in self._payloads(payloads, event):
                    yield event, payload, None
            return
        if isinstance(rows, (list, tuple)):
            for row in rows:
                if isinstance(row, Declaration):
                    yield row.event, row.payload, row
                    continue
                if not isinstance(row, dict):
                    raise TypeError("行必须是 Declaration 或 dict")
                event = row[self._event_key]        # 缺登记键 → KeyError（fail-closed）
                if not isinstance(event, str) or not event:
                    raise TypeError("行登记键必须是非空 str")
                yield event, row, None
            return
        raise TypeError("rows 必须是 mapping 或行序列")

    # ---- 编译 / 校验（纯函数；不碰宿主）----------------------------------
    def compile(self, rows, *, allow_unknown=False):
        """行表 → `{事件名: [载荷, …]}`。**两种输入形态**；载荷原对象、桶内保序。

        `allow_unknown=False`（默认）：每个未知名经 `on_unknown` 告警一次（保序去重），
        但**照常入桶**（告警 + 放行，不抛）。
        """
        out = {}
        names = []
        for event, payload, _decl in self._pairs(rows):
            out.setdefault(event, []).append(payload)
            if not allow_unknown and self.unknown_name(event) and event not in names:
                names.append(event)
        for one in names:
            if self._on_unknown is not None:
                self._on_unknown(one)
        return out

    def validate(self, rows):
        """行表 → 未知名清单（**保序去重**、**不抛**；每个未知名 `on_unknown` 调一次）。"""
        names = []
        for event, _payload, _decl in self._pairs(rows):
            if self.unknown_name(event) and event not in names:
                names.append(event)
        for one in names:
            if self._on_unknown is not None:
                self._on_unknown(one)
        return names

    def action_of(self, payload):
        """按注入的 `action_key` 读动词字段（分发仍是 `effects` 的事）。非 mapping → None。"""
        if isinstance(payload, dict):
            return payload.get(self._action_key)
        return None

    # ---- 挂载（写宿主容器）----------------------------------------------
    def _inject_owner(self, payload, owner):
        if self._owner_key is None or owner is None:
            return
        if isinstance(payload, dict):
            payload.setdefault(self._owner_key, owner)

    def _key_of_entry(self, kf, item):
        """一条载荷/条目的去重键；没有键回调、或载荷不是 mapping → None（= 不去重）。"""
        if kf is None or not isinstance(item, dict):
            return None
        return kf(item)

    def _place(self, bucket, payload, front):
        if front:
            bucket.insert(0, payload)
        else:
            bucket.append(payload)

    def _find_hit(self, bucket, kf, key):
        for idx, item in enumerate(bucket):
            if self._key_of_entry(kf, item) == key:
                return idx
        return -1

    def mount(self, actor, rows, *, owner=None, merge=None):
        """把 `compile(rows)` 挂进 `actor[host_key]`，返回**新挂条数**（幂等命中的不计）。

        · `key_of` 缺省 / 返回 `None` / 载荷非 mapping → **不去重**（一律落格）
        · 命中已有声明：`replace` 原地浅盖 · `keep` 保留既有 · `append` 留旧再追加 ·
          `prepend` 不重排；未命中：`prepend` 前插桶首，其余追加桶尾
        · `owner` 给了 + `owner_key` 给了 → 每条 mapping 载荷 `setdefault(owner_key, owner)`
        """
        if not isinstance(actor, dict):
            raise TypeError("actor 必须是 dict")
        if merge is not None and merge not in _MERGE_WORDS:
            raise ValueError(f"merge 未登记：{merge!r}")
        added = 0
        host = None
        for event, payload, decl in self._pairs(rows):
            if host is None:
                host = actor.get(self._host_key)
                if host is None:
                    host = actor[self._host_key] = {}
                elif not isinstance(host, dict):
                    raise TypeError(f"{self._host_key!r} 处已存在非 dict 容器")
            bucket = host.get(event)
            if bucket is None:
                bucket = host[event] = []
            elif not isinstance(bucket, list):
                raise TypeError(f"{event!r} 桶必须是 list")
            mg = (decl.merge if decl is not None and decl.merge else merge) or "replace"
            if mg not in _MERGE_WORDS:
                raise ValueError(f"merge 未登记：{mg!r}")
            kf = decl.key_of if decl is not None and decl.key_of is not None else self._key_of
            self._inject_owner(payload, owner)
            key = self._key_of_entry(kf, payload)
            if key is None:
                self._place(bucket, payload, mg == "prepend")
                added += 1
                continue
            idx = self._find_hit(bucket, kf, key)
            if idx < 0:
                self._place(bucket, payload, mg == "prepend")
                added += 1
            elif mg == "replace":
                bucket[idx].update(payload)           # 命中就地浅盖
            elif mg == "append":
                bucket.append(payload)                # 命中留旧再追加
                added += 1
            # keep / prepend：命中保留既有条目（幂等命中，不重排、不计数）

        return added

    # ---- 撤除（现状「倍率回落」的承载口）--------------------------------
    def purge(self, actor, *, event=None, match=None, drop_empty=False):
        """按 `event` + `match` 撤条目，返回撤掉条数。

        · `event=None` → 扫宿主容器全部桶；桶不存在 → 0（不抛、不建键）
        · `match=None` → 撤该桶全部；`match(payload)` 为真 → 撤
        · `match` 也可给 `Declaration`：用它自己的 `match` 谓词（`event` 缺省取它的 `event`）
        · 撤空桶后键**默认保留**（空列表）；`drop_empty=True` 才删键
        """
        if not isinstance(actor, dict):
            raise TypeError("actor 必须是 dict")
        host = actor.get(self._host_key)
        if host is None:
            return 0
        if not isinstance(host, dict):
            raise TypeError(f"{self._host_key!r} 处已存在非 dict 容器")
        if match is None:
            pred = None
        elif isinstance(match, Declaration):
            if event is None:
                event = match.event
            pred = match.match
            if pred is None:
                raise ValueError("Declaration.match 没有可调用的谓词")
        elif callable(match):
            pred = match
        else:
            raise TypeError("match 必须可调用或 Declaration")
        if event is None:
            events = list(host)
        else:
            if not isinstance(event, str) or not event:
                raise TypeError("event 必须是非空 str 或 None")
            events = [event]
        removed = 0
        for ev in events:
            bucket = host.get(ev)
            if bucket is None:
                continue
            if not isinstance(bucket, list):
                raise TypeError(f"{ev!r} 桶必须是 list")
            kept = [item for item in bucket if pred is not None and not pred(item)]
            hit = len(bucket) - len(kept)
            if not hit:
                continue
            removed += hit
            if kept:
                bucket[:] = kept
            elif drop_empty:
                del host[ev]
            else:
                bucket[:] = []                        # 空桶键默认保留（空列表）
        return removed

    def events_of(self, actor):
        """宿主容器**原对象**（缺失 → `{}`，**不建键**、不拷贝、不归一）。"""
        if not isinstance(actor, dict):
            raise TypeError("actor 必须是 dict")
        host = actor.get(self._host_key)
        if host is None:
            return {}
        if not isinstance(host, dict):
            raise TypeError(f"{self._host_key!r} 处已存在非 dict 容器")
        return host


def compile_rows(rows, *, compiler):
    """`Compiler.compile` 的模块级入口（供只需编译、不挂载的调用点）。"""
    if not isinstance(compiler, Compiler):
        raise TypeError("compiler 必须是 Compiler")
    return compiler.compile(rows)


def mount(actor, rows, *, compiler, owner=None, merge=None):
    """`Compiler.mount` 的模块级入口（供只挂载、不持实例的调用点）。"""
    if not isinstance(compiler, Compiler):
        raise TypeError("compiler 必须是 Compiler")
    return compiler.mount(actor, rows, owner=owner, merge=merge)
