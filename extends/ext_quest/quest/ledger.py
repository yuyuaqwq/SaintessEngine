# -*- coding: utf-8 -*-
"""任务账本形状（ledger）—— 一份账本的**只读外壳** + **状态迁移**（引擎零知识）。

**为什么有它**：参考实现里「主线一条链 / 支线多条 / 每日多条」三套状态机各自手写，
字段名（`main_quest` / `main_status` / `main_progress` / `completed_main` / `side` / `daily`）
与状态词（`pending` / `active` / `ready` / `done`）全部焊在流程代码里。把那些**取值**拿掉，
剩下的只有一件形状：**一个 mapping + 四条读口 + 六个迁移动作**。

**引擎只认结构字段名，一切取值由注入面给**::

    QuestLog(raw, *, fields, states, lanes=(), unknown=None)

    fields    角色键 → 帐本里的**字段名**（调用方给；引擎不内置任何内容字段名）
              必需角色：current（当前条目）· status（状态）· progress（进度）·
                        archive（完成历史，保序 list）· lanes（默认子账本名）
    states    角色键 → **状态词**（调用方给）
              引擎只读三个：todo（未开始 / 归属默认态）· live（进行中，accept 默认）·
                            ended（终态，用于 is_open 判定）
    lanes     子账本声明：((名字, {"progress": dict | int}), ...)；名字即 raw 里的键
              引擎只读声明里的 `progress` 一格（**进度容器形态**）；其余键（内容侧自己的
              元数据清单一类）引擎**不解释**
    unknown   未声明子账本名的策略：`unknown(名字, 值) -> 真值`；真 = 按 dict 口径当子账本读

**读口（全部零遍历、零缓存）**::

    raw / current / status / progress / done / lane(名) / entry(lane, key) /
    status_of(lane, key=None) / is_open(lane, key)

**迁移（一律返回新 mapping，**绝不**改原 raw；落库由调用方自己做）**::

    accept(*, lane, key, status=None, progress=None, entry=None)   接取 / 建条目
    set_status(status, *, lane, key=None)                          改状态
    bump(patch, *, lane, key=None)                                 推进度（mapping 合并 / int 覆盖）
    deliver(*, lane, key=None, next_of=None)                       交付（主线四步 / 子账本置终态）
    abandon(*, lane, key)                                          删条目
    require(key, *, lane, status)                                  造最小条目
    snapshot() / QuestLog.restore(raw, **kw)                       回写 / 还原

**两个进度容器口径**（见包 docstring 口径③）：mapping 口径按目标值分桶；int 口径是
「整格计数」（每日任务那种 lane），`deliver` / `accept` 清空时分别写 `{}` / `0`。

**line 的缺省语义**：本模块的**状态迁移与状态读**里 `lane=None` ⇒ **主 lane**（顶层账本）；
`lane(名)` / `entry(...)` 是**子账本读口**，`名=None` ⇒ **默认子账本**（`fields["lanes"]`
指的那个）。主 lane 没有条目，所以条目读口缺省只能落到子账本 —— 这是刻意的，不是笔误。

**不变量（门禁逐条钉住）**
--------------------------
* **构造 O(1)、零遍历**：只校验注入面 + 存引用；不读账本、不建索引、不补默认值。
* **不可变**：迁移返回新 mapping；未改动的嵌套对象按浅拷贝共享（不做深拷、不写回原 raw）。
* **异常不吞**：注入回调与校验错误原样上抛。
* **顺序即语义**：`snapshot()` 的键名与键序逐字保留；`archive` 追加**不去重**。
* **只有标准库 + 相对导入**：不落库、不读环境变量、不推导路径、不读任何钟。

**明确不做的事**
----------------
* ❌ 不做落库（连接 / SQL / 事务边界全在内容侧；本模块只搬值）。
* ❌ 不认状态词、不认目标类型词、不认字段名（全部注入）。
* ❌ 不做跨天清理 / 每日刷新（那是内容侧的钟与口径，见包 docstring ⑪）。
* ❌ 不做可接清单过滤 / 门槛 / 奖励发放（取值 + 信息设计，落内容侧）。
* ❌ 不做全表扫描 / 悬空链校验（导出器职责；读路径零遍历）。

**为什么不复用 `run.Progress` 与 `collect`**：见包 docstring（`ext_quest.quest`）。
"""
from __future__ import annotations

from collections.abc import Mapping

__all__ = ["QuestLog"]

# ── 契约角色键（**字段名**不是取值；引擎只按这些名字读调用方的 mapping）──────────
_F_CURRENT = "current"
_F_STATUS = "status"
_F_PROGRESS = "progress"
_F_ARCHIVE = "archive"
_F_LANES = "lanes"
_S_TODO = "todo"
_S_LIVE = "live"
_S_ENDED = "ended"
_SPEC_PROGRESS = "progress"

_FIELD_ROLES = (_F_CURRENT, _F_STATUS, _F_PROGRESS, _F_ARCHIVE, _F_LANES)
_STATE_ROLES = (_S_TODO, _S_LIVE, _S_ENDED)

_MISSING = object()


# ───────────────────────────────────────────────────────── 校验口（fail-closed）
def _fields_map(fields):
    if not isinstance(fields, Mapping):
        raise TypeError("fields 必须是 mapping（角色键 → 字段名）")
    out = {}
    for role in _FIELD_ROLES:
        name = fields.get(role)
        if not isinstance(name, str) or not name:
            raise ValueError("fields 缺角色键或值不是非空字符串：" + repr(role))
        out[role] = name
    return out


def _states_map(states):
    if not isinstance(states, Mapping):
        raise TypeError("状态词映射必须是 mapping（角色键 → 状态词）")
    out = {}
    for role in _STATE_ROLES:
        if role not in states:
            raise ValueError("状态词映射缺角色键：" + repr(role))
        out[role] = states[role]
    return out


def _lanes_map(lanes):
    if isinstance(lanes, (str, bytes)) or not isinstance(lanes, (list, tuple)):
        raise TypeError("lanes 必须是 ((名字, 声明), ...) 序列")
    specs = {}
    for item in lanes:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise TypeError("lanes 的每一项必须是 (名字, 声明) 二元组")
        name, spec = item
        if not isinstance(name, str) or not name:
            raise ValueError("lanes 的名字必须是非空字符串")
        if name in specs:
            raise ValueError("lanes 名字重复：" + repr(name))
        if not isinstance(spec, Mapping):
            raise TypeError("lanes 的声明必须是 mapping")
        kind = spec.get(_SPEC_PROGRESS, dict)
        if kind not in (dict, int):
            raise ValueError("lanes 声明的 " + _SPEC_PROGRESS + " 只能是 dict 或 int")
        specs[name] = {_SPEC_PROGRESS: kind}
    return specs


def _blank(kind):
    """按声明清空进度：mapping 口径 → `{}`；int 口径 → `0`。"""
    return {} if kind is dict else 0


def _bumped(old, patch):
    """推进度：`patch` 是 mapping → 合并；否则**覆盖**（现状两种口径都保留）。"""
    if isinstance(patch, Mapping):
        base = dict(old) if isinstance(old, Mapping) else {}
        base.update(patch)
        return base
    return patch


# ───────────────────────────────────────────────────────── 账本外壳
class QuestLog:
    """一份任务账本的**只读外壳 + 状态迁移**：构造 O(1)，不遍历账本、不缓存、不落库。"""

    __slots__ = ("_raw", "_fields", "_words", "_specs", "_unknown_fn", "_default_lane")

    def __init__(self, raw=None, *, fields, states, lanes=(), unknown=None) -> None:
        self._fields = _fields_map(fields)
        self._words = _states_map(states)
        self._specs = _lanes_map(lanes)
        default = self._fields[_F_LANES]
        if default not in self._specs:
            raise ValueError("默认子账本名没有在 lanes 里声明：" + repr(default))
        if unknown is not None and not callable(unknown):
            raise TypeError("unknown 必须可调用（unknown(名字, 值)）")
        if raw is not None and not isinstance(raw, Mapping):
            raise TypeError("raw 必须是 mapping 或 None，收到 " + type(raw).__name__)
        # 构造期**不读账本**：只存引用（零遍历 → 大账本与空账本同量级）。
        self._raw = raw
        self._unknown_fn = unknown
        self._default_lane = default

    # ---------------------------------------------------------------- 读口
    @property
    def raw(self):
        """调用方的**原对象**（不拷贝、不归一、不补默认值）；没给 → `None`。"""
        return self._raw

    @property
    def current(self):
        """当前条目（注入字段名的取值）；缺失 / `None` → `None`（不回落）。"""
        return self._m().get(self._fields[_F_CURRENT])

    @property
    def status(self):
        """主 lane 状态；缺失 / `None` → 注入的 todo 状态词（现状「缺省即未接取」）。"""
        got = self._m().get(self._fields[_F_STATUS], _MISSING)
        if got is _MISSING or got is None:
            return self._words[_S_TODO]
        return got

    @property
    def progress(self):
        """主 lane 进度**原对象**；缺失 → `{}`（**不建**默认值）。"""
        got = self._m().get(self._fields[_F_PROGRESS], _MISSING)
        return {} if got is _MISSING else got

    @property
    def done(self):
        """完成历史**原对象**（保序 list）；缺失 → `[]`。追加**不去重**（现状如此）。"""
        got = self._m().get(self._fields[_F_ARCHIVE], _MISSING)
        return [] if got is _MISSING else got

    def lane(self, name=None) -> dict:
        """子账本**原对象**；`name=None` → 默认子账本；缺失 / 未声明 → `{}`（不建默认值）。"""
        lane_name = self._default_lane if name is None else name
        if self._spec(lane_name) is None:
            return {}
        got = self._m().get(lane_name)
        return got if isinstance(got, Mapping) else {}

    def entry(self, lane, key):
        """子账本里的条目**原对象**；缺失 → `None`。`lane=None` → 默认子账本。"""
        return self.lane(lane).get(key)

    def status_of(self, lane, key=None):
        """单 lane 状态：`lane=None` → 主 lane；`key=None` → 把 lane 自己当条目读。"""
        if lane is None:
            return self.status
        got = self.lane(lane) if key is None else self.lane(lane).get(key)
        if not isinstance(got, Mapping):
            return self._words[_S_TODO]
        value = got.get(self._fields[_F_STATUS], _MISSING)
        if value is _MISSING or value is None:
            return self._words[_S_TODO]
        return value

    def is_open(self, lane, key=None) -> bool:
        """`键在 lane 里` **且** `状态 != ended`；主 lane（`lane=None`）看 `current`。"""
        if lane is None:
            return (self.current is not None
                    and self.status != self._words[_S_ENDED])
        if key is None:
            got = self.lane(lane)
            if not got:
                return False
            return self.status_of(lane) != self._words[_S_ENDED]
        if key not in self.lane(lane):
            return False
        return self.status_of(lane, key) != self._words[_S_ENDED]

    # ---------------------------------------------------------------- 迁移
    def accept(self, *, lane, key, status=None, progress=None, entry=None) -> dict:
        """接取 / 建条目：`status` 缺省 = live、`progress` 缺省 = 按声明清空。

        `entry` 是基底（给了就基于它补两格）。主 lane（`lane=None`）时把结果合并进顶层。
        """
        if entry is not None and not isinstance(entry, Mapping):
            raise TypeError("entry 必须是 mapping 或 None")
        kind = self._kind(lane)
        base = dict(entry) if entry is not None else {}
        if status is not None:
            base[self._fields[_F_STATUS]] = status
        else:
            base.setdefault(self._fields[_F_STATUS], self._words[_S_LIVE])
        if progress is not None:
            base[self._fields[_F_PROGRESS]] = progress
        else:
            base.setdefault(self._fields[_F_PROGRESS], _blank(kind))
        new = self._copy()
        if lane is None:
            new.update(base)
            return new
        lane_map = dict(self.lane(lane))
        lane_map[key] = base
        new[lane] = lane_map
        return new

    def set_status(self, status, *, lane, key=None) -> dict:
        """改状态：主 lane 改顶层；子账本 `key=None` 改 lane 自己；否则改条目（缺失 → KeyError）。"""
        new = self._copy()
        if lane is None:
            new[self._fields[_F_STATUS]] = status
            return new
        self._kind(lane)
        lane_map = dict(self.lane(lane))
        if key is None:
            lane_map[self._fields[_F_STATUS]] = status
        else:
            lane_map[key] = self._patched(lane_map.get(key, _MISSING), key,
                                          self._fields[_F_STATUS], status)
        new[lane] = lane_map
        return new

    def bump(self, patch, *, lane, key=None) -> dict:
        """推进度：`patch` 是 mapping → 合并；否则覆盖。目标缺失 → KeyError。"""
        field = self._fields[_F_PROGRESS]
        new = self._copy()
        if lane is None:
            new[field] = _bumped(self._m().get(field, _MISSING), patch)
            return new
        self._kind(lane)
        lane_map = dict(self.lane(lane))
        if key is None:
            lane_map[field] = _bumped(lane_map.get(field, _MISSING), patch)
        else:
            got = self._existing(lane_map, key)
            if not isinstance(got, Mapping):
                raise TypeError("条目不是 mapping：" + repr(key))
            lane_map[key] = self._patched(got, key, field,
                                          _bumped(got.get(field, _MISSING), patch))
        new[lane] = lane_map
        return new

    def deliver(self, *, lane, key=None, next_of=None) -> dict:
        """交付。**主 lane** 四步（现状逐字）：历史追加 current → current 换 `next_of(current)`
        → status 归 todo → 进度清空。**子账本**：条目置**最小终态**（只有 status 一格，
        现状 `{"status": "done"}` 的口径），**不**追加历史、**不**认 `next_of`。
        """
        if next_of is not None and not callable(next_of):
            raise TypeError("下一环回调必须可调用（收当前条目、出下一环）")
        field_status = self._fields[_F_STATUS]
        field_progress = self._fields[_F_PROGRESS]
        new = self._copy()
        if lane is None:
            current = self.current
            got = self._m().get(self._fields[_F_ARCHIVE], _MISSING)
            items = list(got) if isinstance(got, (list, tuple)) else []
            items.append(current)
            new[self._fields[_F_ARCHIVE]] = items
            new[self._fields[_F_CURRENT]] = next_of(current) if next_of is not None else None
            new[field_status] = self._words[_S_TODO]
            new[field_progress] = _blank(dict)
            return new
        kind = self._kind(lane)
        lane_map = dict(self.lane(lane))
        if key is None:
            lane_map[field_status] = self._words[_S_ENDED]
            lane_map[field_progress] = _blank(kind)
        else:
            self._existing(lane_map, key)
            lane_map[key] = {field_status: self._words[_S_ENDED]}
        new[lane] = lane_map
        return new

    def abandon(self, *, lane, key) -> dict:
        """删条目（返回新 mapping）；键不存在 → 幂等。主 lane 不可放弃 → ValueError。"""
        if lane is None:
            raise ValueError("主 lane 不可放弃（撤离是子账本条目的动作）")
        self._kind(lane)
        new = self._copy()
        lane_map = dict(self.lane(lane))
        lane_map.pop(key, None)
        new[lane] = lane_map
        return new

    def require(self, key, *, lane, status) -> dict:
        """造一个**最小条目**（只有 status 一格）；主 lane → ValueError。"""
        if lane is None:
            raise ValueError("require 造的是子账本条目")
        self._kind(lane)
        new = self._copy()
        lane_map = dict(self.lane(lane))
        lane_map[key] = {self._fields[_F_STATUS]: status}
        new[lane] = lane_map
        return new

    def snapshot(self) -> dict:
        """回写成**原形态**：键名与键序逐字保留的浅拷贝（嵌套对象仍是原对象）。"""
        return dict(self._m())

    @classmethod
    def restore(cls, raw, **kw) -> "QuestLog":
        """从存档 mapping 还原一个外壳（与构造同参数；O(1)）。"""
        return cls(raw, **kw)

    # ---------------------------------------------------------------- 内部
    def _m(self):
        """读口用的顶层 mapping：没给账本 → 空 mapping。"""
        return self._raw if isinstance(self._raw, Mapping) else {}

    def _copy(self):
        """迁移的起点：顶层浅拷贝（键序保留）；嵌套对象按需再拷。"""
        return dict(self._m())

    def _spec(self, name):
        """子账本声明；未声明的名字交给 `unknown` 策略（真 = 按 dict 口径认它）。"""
        if name in self._specs:
            return self._specs[name]
        if self._unknown_fn is not None and self._unknown_fn(name, self._m().get(name)):
            return {_SPEC_PROGRESS: dict}
        return None

    def _kind(self, lane):
        """lane 的进度容器形态；未声明且策略不认 → KeyError（fail-closed）。"""
        if lane is None:
            return dict
        spec = self._spec(lane)
        if spec is None:
            raise KeyError("未声明的子账本：" + repr(lane))
        return spec[_SPEC_PROGRESS]

    @staticmethod
    def _existing(lane_map, key):
        if key not in lane_map:
            raise KeyError("条目不存在：" + repr(key))
        return lane_map[key]

    def _patched(self, got, key, field, value):
        """把条目里的一格换成新值：条目缺失 → KeyError；条目不是 mapping → TypeError。"""
        if got is _MISSING:
            raise KeyError("条目不存在：" + repr(key))
        if not isinstance(got, Mapping):
            raise TypeError("条目不是 mapping：" + repr(key))
        ent = dict(got)
        ent[field] = value
        return ent

    def __repr__(self) -> str:
        return f"QuestLog(current={self.current!r}, status={self.status!r})"
