# -*- coding: utf-8 -*-
"""文案模板表 —— 「输出文案」的声明与渲染（形状侧）。

与 `command/text.py` 的分工
---------------------------
* `command/text.py` 是**输入**侧：从宿主消息剥前缀、取参数。
* 本模块是**输出**侧：把 `key → 模板串` 渲染成给玩家看的文本。

为什么要它
----------
文案散在两种地方：数据表内联（技能 desc）与代码 f-string（结算日志）。
于是「改一句话要动代码」「多语言无从下手」「语气/格式各自漂移」「编辑器覆盖不到文本」。
本模块给一张**可装载、可渲染、可自检**的文案表：

* **装载**：数据（dict/JSON 友好）→ 模板；编辑器可写
* **渲染**：`render(key, **slots)` —— 未知占位符**原样保留**（不炸玩家输出）
* **自检**：`missing()` 请求过但没定义；`unused()` 定义了但没请求过；`validate()`
* **可拔插**：不装载 = 渲染走兜底（返回 key 或 fallback），**行为零变化**

设计取舍（有意为之）
--------------------
* **不做多语言切换**：本表只管「key → 模板」。要几套语言就建几张表，各自装载。
* **不做格式化 DSL**：就用 `str.format` 的 `{slot}`；复杂逻辑写在使用方。
* **不猜**：模板缺槽时保留 `{slot}` 原文而不是填空 —— 让问题可见，别静默丢字。

两个渲染口的分工（★ 2026-09-27 B2–B4 走完后定稿：引擎侧「措辞」只剩一条路）
----------------------------------------------------------------------------
* `render_or(text, key, default, **slots)` = **表优先、缺 key 回落调用点现给的模板**。
  引擎自己的 60 个玩家可见点位**全部**走 cue（`render_required`）了 ⇒ 这个口现在的使用者是
  「内容侧/第三方自己的调用点」与鸭子表内部（`render_required` 拿它做真正的渲染）。
* `render_required(text, key, **slots)` = **必须命中**：表不在 / 表里没这个 key ⇒ **抛**。
  引擎的 cue 渲染走它 —— 引擎手里没有任何模板可回落（措辞真源在内容侧文案表），
  缺表/缺 key 就是内容侧漏声明，不许静默补齐。

★ B5（2026-09-27 收口）：`render_via(holder, …)` / `text_of(holder)` 两个「从持有者取表」
  的辅助已**删除** —— 引擎侧最后一个调用点随 B4 迁进 cue 后就没人用了，留着 = 兼容壳。
  要在普通函数里拿表，直接 `render_or(text_of_holder, ...)` 或把表自己传进来。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from string import Formatter
from typing import Callable, Iterable, Mapping, Optional

__all__ = ["TextSpec", "TextTable", "safe_format", "extract_params",
           "render_or", "render_required", "text_hit"]


class _KeepUnknown(dict):
    """`format_map` 用：未知占位符 → 原样返回 `{name}`（不抛 KeyError）。"""

    def __missing__(self, key):
        return "{" + str(key) + "}"


def safe_format(template: str, slots: Optional[Mapping] = None) -> str:
    """安全格式化：未知占位符原样保留；格式非法 → 原样返回模板（绝不抛）。

    玩家可见文案不该因为一个错占位符就整条丢失 —— 宁可露出 `{name}` 让人发现。
    """
    tpl = "" if template is None else str(template)
    if not slots:
        return tpl
    # ★ 只有**一支**（2026-09-29，审计 L1452）：原实现是「format_map 失败 → 退回
    #   `format(**slots)` → 再失败 → 原样吐回」。后两支是**恒不可达的死分支** ——
    #   `_KeepUnknown` 把所有 KeyError 换成 `{name}` 字面量，而 `format` 与
    #   `format_map` 的失败集合**完全相同**（都来自 `str.format` 本身：
    #   坏格式符、类型说明不匹配、属性/下标取不到）。
    #   实测 1680 组（24 个模板 × 7 个槽名 × 10 种取值）逐组对拍：
    #   「第一支失败且第二支成功」= **0 组** ⇒ 第二支从不改变任何一次输出。
    #   留着它有两个坏处：① 它读起来像「还有一条更宽松的退路」，实际从没有过；
    #   ② `except Exception: pass` 是一块判据 #2 明确禁掉的静默吞，
    #   而删掉死分支后整条路径只剩一次 try —— 坏模板直接原样吐回，语义更直白。
    try:
        return tpl.format_map(_KeepUnknown(dict(slots)))
    except Exception:
        return tpl


def render_or(text, key: str, default: str, /, **slots) -> str:
    """渲染口（渐进迁移用）：表里有 `key` 按表渲染，否则用调用方现给的 `default` 模板。

    * `text` = 注入的文案表（鸭子类型，需有 `render_or(key, default, **slots)`）；
      `None` = **未注入** ⇒ 只用 `default` 渲染（= 调用点内联文案的原样输出）。
    * 两条路径都走 `safe_format`（未知槽原样保留），所以「表缺 key」与「未注入」
      的输出逐字节相同 —— 这是「不装载 = 现状」的根据。
    """
    if text is None:
        return safe_format(default, slots)
    return text.render_or(key, default, **slots)


def text_hit(text, key: str) -> bool:
    """表里**有没有**这个 key（`render_required` 的 fail-closed 判定）。

    * 表不在（未注入）⇒ `False`；
    * 表有 `__contains__`（`TextTable` / `Mapping` / 计数鸭子表）⇒ 按它判；
    * 表**答不出**有没有（只实现了 `render_or` 的手写替身）⇒ `False` ——
      「答不出」不许当成「有」（那正是静默兜底）。
    """
    if text is None:
        return False
    try:
        return bool(key in text)
    except TypeError:
        return False


def render_required(text, key: str, /, **slots) -> str:
    """**必须命中**的渲染口（已迁移点位专用）：表不在 / 表里没这个 key ⇒ 抛 `KeyError`。

    为什么要有它：迁移一个点位 = 把那个点位的模板从引擎删掉 ⇒ 引擎手里**没有**任何
    可回落的措辞（回落 = 影子真源复活，正是解耦要拆掉的东西）。所以这条路上「表缺 key」
    只能**现形**：调用方（`CueBus`）把 `KeyError` 转成「诊断 + 一行可读坏数据」，
    既不静默丢行，也不替内容侧编一句。
    """
    if not text_hit(text, key):
        raise KeyError("文案表%s里没有 %r" % ("（未注入）" if text is None else "", key))
    return render_or(text, key, "", **slots)


def extract_params(template: str) -> tuple:
    """抽出模板里的占位符名（去重保序）—— 编辑器提示 & 自检用。

    兼容 `{a}` / `{a.b}` / `{a[0]}`（取首个字段名）与 `{{转义}}`（跳过）。
    """
    out, seen = [], set()
    try:
        for _literal, name, _spec, _conv in Formatter().parse(str(template or "")):
            if not name:
                continue
            root = re.split(r"[.\[]", name, 1)[0]
            if root and root not in seen:
                seen.add(root)
                out.append(root)
    except Exception:
        return tuple(out)
    return tuple(out)


@dataclass
class TextSpec:
    """一条文案模板的声明（全为通用形状字段）。

    * `key`      —— 文案标识（使用方定的命名，框架不解释）
    * `value`    —— 模板串，`{slot}` 占位
    * `desc`     —— 说明（编辑器/帮助）
    * `category` —— 分类（编辑器分组）
    * `params`   —— 声明的占位符名（缺省由模板自动抽取）
    """
    key: str
    value: str = ""
    desc: str = ""
    category: str = ""
    params: tuple = ()

    @classmethod
    def from_dict(cls, data: Mapping) -> "TextSpec":
        if not isinstance(data, Mapping):
            return cls(key=str(data), value=str(data))
        key = data.get("key", data.get("name", data.get("id", "")))
        value = data.get("value", data.get("text", data.get("template", "")))
        p = data.get("params", ())
        params = (p,) if isinstance(p, str) and p else tuple(p or ())
        return cls(key=str(key or ""), value="" if value is None else str(value),
                   desc=str(data.get("desc", "") or ""),
                   category=str(data.get("category", "") or ""),
                   params=params)

    def to_dict(self) -> dict:
        out = {"key": self.key, "value": self.value}
        for k in ("desc", "category"):
            v = getattr(self, k)
            if v:
                out[k] = v
        p = self.params or extract_params(self.value)
        if p:
            out["params"] = list(p)
        return out

    @property
    def slots(self) -> tuple:
        """生效占位符名（声明优先，缺省自动抽取）。"""
        return self.params or extract_params(self.value)

    def render(self, **slots) -> str:
        return safe_format(self.value, slots)


class TextTable:
    """文案表：装载 / 查询 / 渲染 / 自检。**不装载 = 零行为**。"""

    def __init__(self, entries=None, *, name: str = "", fallback: str = "",
                 strict: bool = False, on_miss: Optional[Callable] = None) -> None:
        self.name = name
        self.fallback = fallback or ""
        self.strict = bool(strict)
        self.on_miss = on_miss
        self._specs: dict = {}
        self._order: list = []
        self._requested: list = []
        self._missed: list = []
        if entries:
            self.load(entries)

    # ============================================================ 装载
    def register(self, spec: TextSpec, *, replace: bool = False) -> TextSpec:
        if not isinstance(spec, TextSpec):
            spec = TextSpec.from_dict(spec)
        if spec.key in self._specs and not replace:
            raise ValueError("文案 key 重复：%r（要覆盖请 replace=True）" % spec.key)
        if spec.key not in self._specs:
            self._order.append(spec.key)
        self._specs[spec.key] = spec
        return spec

    def extend(self, items: Iterable, *, replace: bool = False) -> "TextTable":
        for it in items or ():
            self.register(it if isinstance(it, TextSpec) else TextSpec.from_dict(it),
                          replace=replace)
        return self

    def load(self, items) -> "TextTable":
        """装载文案；`{key: "模板"}` 或 `{key: {...}}` 或 `[{...}, ...]` 都认。"""
        if isinstance(items, Mapping):
            for k, v in items.items():
                if isinstance(v, Mapping):
                    d = dict(v)
                    d.setdefault("key", k)
                    self.register(TextSpec.from_dict(d))
                else:
                    self.register(TextSpec(key=str(k), value="" if v is None else str(v)))
            return self
        return self.extend(items)

    @classmethod
    def from_data(cls, items, **kw) -> "TextTable":
        return cls(items, **kw)

    # ============================================================ 查询
    def get(self, key: str, default=None):
        spec = self._specs.get(key)
        return spec.value if spec is not None else default

    def spec(self, key: str) -> Optional[TextSpec]:
        return self._specs.get(key)

    def keys(self) -> tuple:
        return tuple(self._order)

    def __len__(self) -> int:
        return len(self._order)

    def __contains__(self, key) -> bool:
        return key in self._specs

    def __iter__(self):
        return (self._specs[k] for k in self._order)

    def by_category(self) -> dict:
        out: dict = {}
        for s in self:
            out.setdefault(s.category, []).append(s)
        return {k: tuple(v) for k, v in out.items()}

    # ============================================================ 渲染
    def render(self, key: str, /, **slots) -> str:
        """渲染一条文案。

        命中 → 按模板插槽渲染（未知槽**原样保留**）。
        未命中 → `strict` 抛 `KeyError`；否则 `on_miss` 回调 > `fallback` > 返回 key。
        每次调用都记账（`missing()` / `unused()` 自检靠它）。
        """
        if key not in self._requested:
            self._requested.append(key)
        spec = self._specs.get(key)
        if spec is not None:
            return spec.render(**slots)
        if key not in self._missed:
            self._missed.append(key)
        if self.strict:
            raise KeyError("文案未定义：%r（表 %s）" % (key, self.name or "<匿名>"))
        if self.on_miss is not None:
            try:
                got = self.on_miss(key, slots)
                if got is not None:
                    return str(got)
            except Exception:
                pass
        if self.fallback:
            return safe_format(self.fallback, slots)
        return key

    def render_or(self, key: str, default: str, /, **slots) -> str:
        """未定义时用调用方现给的 `default` 模板（渐进迁移：新文案走表、旧的先内联）。"""
        if key in self._specs:
            return self.render(key, **slots)
        if key not in self._requested:
            self._requested.append(key)
        if key not in self._missed:
            self._missed.append(key)
        return safe_format(default, slots)

    # ============================================================ 自检
    def missing(self) -> tuple:
        """被请求过但表里没有的 key（按首次请求序）—— 迁移待办清单。"""
        return tuple(self._missed)

    def unused(self) -> tuple:
        """表里有但从未被请求过的 key（按注册序）—— 疑似死文案。"""
        return tuple(k for k in self._order if k not in self._requested)

    def validate(self) -> list:
        """查表自身问题（空 key/空值/语法非法/占位符与声明不一致）。**只报告不抛。**"""
        problems = []
        for s in self:
            if not s.key:
                problems.append("存在空 key 的文案")
                continue
            if s.value == "":
                problems.append("%s：模板为空" % s.key)
            try:
                # ⚠️ `parse()` 是**生成器**：必须消费才触发语法异常（不 list 就永远不报）
                list(Formatter().parse(s.value))
            except Exception as e:
                problems.append("%s：模板语法非法（%s）" % (s.key, e))
            if s.params:
                auto = set(extract_params(s.value))
                declared = set(s.params)
                extra = sorted(auto - declared)
                lack = sorted(declared - auto)
                if extra:
                    problems.append("%s：模板用了未声明的占位符 %s" % (s.key, extra))
                if lack:
                    problems.append("%s：声明了模板里没有的占位符 %s" % (s.key, lack))
        return problems

    def audit(self) -> dict:
        """自检汇总（CI/编辑器用）。"""
        return {
            "total": len(self._order),
            "requested": len(self._requested),
            "missing": list(self.missing()),
            "unused": list(self.unused()),
            "problems": self.validate(),
        }

    def to_data(self) -> list:
        return [s.to_dict() for s in self]

    def reset_stats(self) -> None:
        """清空请求/缺失记账（长驻进程按轮次统计用）。"""
        self._requested = []
        self._missed = []
