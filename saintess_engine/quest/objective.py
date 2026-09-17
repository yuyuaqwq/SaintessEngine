# -*- coding: utf-8 -*-
"""目标类型注册表形状（objective）—— 一个目标类型 = 契约键名 + 四个回调（引擎零知识）。

**为什么有它**：参考实现里「一个任务的目标是什么、达成没有、出一行什么文案」被写了三份
（接取通知单行版 / 交付面板多行版 / 任务面板进度版），而每一份都在内部硬编码目标类型词
（击败 / 收集 / 前往 / 寻找 / 使用 / 交谈 …）。把那些**取值**拿掉，剩下的只有两件形状：

| 形状 | 一件什么事 | 谁给 |
|---|---|---|
| `Objective` | 一个目标类型：契约键名 + 四个回调（命中 / 需求数 / 折叠进度 / 出行文） | 类型名与四个回调全在内容侧 |
| `Objectives` | **有序**注册表：声明序 = 判定序 = 展示序；复合目标逐型全出 | 注册顺序由内容侧定 |

**引擎一个取值都不认**：目标类型词、状态词、修饰键名、进度键、需求数口径、行文模板
全部经**注入面**给。引擎源码的字符串常量里没有任何一个取值（零知识静态扫描把这条钉住）。

**字段级契约（引擎只按下列结构读调用方的 mapping）**::

    目标 mapping   {类型键: 任意, 修饰键: 任意, ...}   引擎按**插入序**逐个看；键序即行序
    类型键         内容侧注册过的 `Objective.key`
    修饰键         某个类型在 `modifiers` 里声明过的名字（如数量/上限修饰）；**不单独出行**
    进度 mapping   {进度键: 任意}；进度键由内容侧 `fold` 回调决定，引擎只搬运、不解释
    进度 int       单键目标的「整格计数」（每日任务那种 lane），与 need 直接比
    event          任意；引擎一个字段都不读，整体透传给注入的回调

**四个回调（引擎只认签名，不认语义）**::

    match(value, event) -> 真值          本类型是否命中本事件
    need(objective, engine) -> int       需求数（`engine` 就是本注册表，供内容侧复用查询）
    fold(objective, progress, event) -> mapping | 假值   折叠一次，返回**补丁**（引擎不就地改）
    text(objective, progress, ctx) -> str | None         出一行；None = 不出行

**注入面（引擎零默认取值）**::

    unknown(key, value) -> 任意   未注册键的策略；**默认（未注入）= 返回 None（不出行）**
    need_of(objective, key) -> int  类型没自带 need 回调时的需求数口径（§2.3 口径分歧 ④）

**不变量（门禁逐条钉住）**
--------------------------
* **构造 O(1)、零遍历**：只校验注册项与注入面，不读任何目标 mapping、不建索引。
* **不可变**：注册表与类型都不写；`fold` 只返回补丁，绝不就地改进度。
* **异常不吞**：四个回调抛出的异常**原样上抛**。
* **顺序即语义**：注册声明序 = `keys()` 序 = `hits()` 序；目标 mapping 插入序 = `parts()` 序 = `lines()` 序。
* **只有标准库 + 相对导入**：不 import 内容侧任何模块。

**12 条口径分歧**见包 docstring（`saintest_engine.quest`）；与本模块直接相关的是
②（三份渲染不合并：本模块只出骨架，行文由 `text_of` 注入）· ④（需求数两口径）·
⑤（`unknown` 三出口）· ⑦（进度键由内容侧 `fold` 决定，引擎不翻译）· ⑧（三门槛失败语义）
· ⑫（行序 = 信息序）。

**明确不做的事**
----------------
* ❌ 不做目标类型词表（类型名由内容侧注册）。
* ❌ 不做状态词、不做需求数默认取值（口径交 `need_of`）。
* ❌ 不做成品文案（`lines` 只出骨架；行文 = 各出口自己的 `text_of`）。
* ❌ 不做进度键翻译（含目标名的历史键聚合是内容侧刻意兼容，引擎不许统一）。
* ❌ 不做列表过滤 / 门槛（可接清单的过滤集合与短路序是内容侧的信息设计）。
* ❌ 不做奖励发放、声望、剧情文案（取值 + 副作用，落命令层）。

**为什么不复用 `conditions.Conditions`**
----------------------------------------
`Conditions` 是「条件名 → **单参**谓词」的只读判定表；目标类型需要的是
**match / need / fold / text 四件**（含**写**进度），形状不同。硬塞会让 `Conditions`
长出「fold」这种不属于它的方法。这里只借「有序注册 + 按名查表」一个动作，且自带修饰键概念。
"""
from __future__ import annotations

from collections.abc import Mapping

__all__ = ["Objective", "Objectives", "parse_needs"]

# ── 契约角色键（**字段名**不是取值；引擎只按这些名字读调用方的结构）──────────────
_F_NEED = "need"
_F_MODS = "mods"
_F_PROGRESS = "progress"


# ───────────────────────────────────────────────────────── 校验口（fail-closed）
def _as_str(value, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{label} 必须是非空字符串，收到 {type(value).__name__}")
    return value


def _as_callable(value, label: str):
    """可选项：`None` 合法；给了就必须可调用（不合法当场报错）。"""
    if value is None:
        return None
    if not callable(value):
        raise TypeError(f"{label} 必须可调用，收到 {type(value).__name__}")
    return value


def _as_names(values, label: str) -> tuple:
    """一串名字：字符串会被逐字符迭代（经典笔误）→ 显式拒绝。"""
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{label} 必须是一串名字（不是单个字符串），收到 {values!r}")
    return tuple(_as_str(v, label) for v in values)


def _met(have, need) -> bool:
    """进度值够不够：只有真数值算数（字符串 / None / 布尔 都算「不达标」，不谎报）。"""
    if isinstance(have, bool) or not isinstance(have, (int, float)):
        return False
    return have >= need


def _first_positive(objective, mods) -> int:
    """默认需求数口径：按 `mods` 声明序取**首个正整数**修饰键值；都没有 → 1。"""
    for name in mods:
        got = objective.get(name)
        if isinstance(got, bool) or not isinstance(got, int):
            continue
        if got > 0:
            return got
    return 1


# ───────────────────────────────────────────────────────── 一个目标类型
class Objective:
    """一个目标类型：契约键名 + 四个回调。**引擎零知识**（四个回调都由内容侧注入）。

    不可变（`__slots__`，无 setter）：要换回调就新建一个 `Objective`。
    """

    __slots__ = ("_key", "_match", "_need", "_fold", "_text", "_multi", "_mods")

    def __init__(self, key: str, *, match=None, need=None, fold=None,
                 text=None, multi=False, modifiers=()) -> None:
        self._key = _as_str(key, "key（目标类型名）")
        self._match = _as_callable(match, "match")
        self._need = _as_callable(need, "need")
        self._fold = _as_callable(fold, "fold")
        self._text = _as_callable(text, "text")
        self._multi = bool(multi)
        self._mods = _as_names(modifiers, "modifiers")

    @property
    def key(self) -> str:
        """目标类型键名（内容侧的取值；引擎只拿它当查表键）。"""
        return self._key

    @property
    def match(self):
        """`match(value, event) -> 真值`；`None` = 本类型永不命中。"""
        return self._match

    @property
    def need(self):
        """`need(objective, engine) -> int`；`None` 时由注册表的 `need_of` 口径兜。"""
        return self._need

    @property
    def fold(self):
        """`fold(objective, progress, event) -> mapping | 假值`；`None` = 不折叠进度。"""
        return self._fold

    @property
    def text(self):
        """`text(objective, progress, ctx) -> str | None`；`None` = 本类型不出行文。"""
        return self._text

    @property
    def multi(self) -> bool:
        """复合目标里本类型是否**可以只有值、没有需求数**（现状 探索/寻找/使用 这类）。"""
        return self._multi

    @property
    def modifiers(self) -> tuple:
        """本类型可消费的修饰键名（声明序即「首个正整数」的优先序）。"""
        return self._mods

    def __repr__(self) -> str:
        return (f"Objective({self._key!r}, multi={self._multi}, "
                f"modifiers={self._mods!r})")


# ───────────────────────────────────────────────────────── 有序注册表
class Objectives:
    """**有序**目标类型注册表：声明序 = 判定序 = 展示序（**不重排**）。

    构造 O(1)：只校验注册项与注入面，不读目标数据、不建索引、不缓存判定。
    """

    __slots__ = ("_order", "_by_key", "_mods", "_unknown_fn", "_need_of")

    def __init__(self, *types, unknown=None, need_of=None) -> None:
        order, by_key, mods = [], {}, set()
        for t in types:
            if not isinstance(t, Objective):
                raise TypeError("注册项必须是 Objective 实例，收到 " + type(t).__name__)
            if t.key in by_key:
                raise ValueError("目标类型名重复：" + repr(t.key))
            by_key[t.key] = t
            order.append(t.key)
            mods.update(t.modifiers)
        if unknown is not None and not callable(unknown):
            raise TypeError("unknown 必须可调用（unknown(key, value)）")
        if need_of is not None and not callable(need_of):
            raise TypeError("need_of 必须可调用（收目标与类型键）")
        # fail-closed：类型没自带 need 回调、又没注入口径 → 当场报错（不许悄悄退某个默认数）。
        bare = [k for k in order if by_key[k].need is None]
        if bare and need_of is None:
            raise TypeError("这些目标类型没有 need 回调，且没注入 need_of：" + ", ".join(bare))
        self._order = tuple(order)
        self._by_key = by_key
        self._mods = mods
        self._unknown_fn = unknown
        self._need_of = need_of

    # ---------------------------------------------------------------- 注册面
    def keys(self) -> list:
        """注册表**声明序**的类型键名。"""
        return list(self._order)

    def unknown(self, key, value):
        """未注册键的策略出口：未注入 → **返回 None**（= 不出行）；注入 → 原样调它。"""
        if self._unknown_fn is None:
            return None
        return self._unknown_fn(key, value)

    # ---------------------------------------------------------------- parts
    def parts(self, objective) -> list:
        """`[(类型键, 值, 需求数, 修饰键 mapping)]`，**按目标 mapping 的插入序**。

        * 修饰键归**离它最近的在它之前**的那个 part；出现在任何 part 之前的前导修饰键
          归**下一个** part（不丢）。
        * 未注册且非修饰键的键**不进 parts**（`lines` 走 `unknown` 策略）。
        """
        if not isinstance(objective, Mapping):
            raise TypeError("目标必须是 mapping，收到 " + type(objective).__name__)
        rows, pending = [], {}
        for key, value in objective.items():
            if key in self._by_key:
                rows.append([key, value, dict(pending)])
                pending.clear()
            elif key in self._mods:
                if rows:
                    rows[-1][2][key] = value
                else:
                    pending[key] = value
        return [(type_key, value, self.need_of(objective, type_key), dict(mods))
                for type_key, value, mods in rows]

    def need_of(self, objective, type_key=None) -> int:
        """需求数：类型自带 `need` 回调优先；否则用注入的 `need_of`。

        `type_key` 缺省 = **首个 part 的型**（现状所有判定都只对单目标用）。
        未注册类型：有注入 `need_of` 就交给它，否则 `KeyError`（fail-closed）。
        """
        if type_key is None:
            rows = self.parts(objective)
            if not rows:
                return 0
            type_key = rows[0][0]
        t = self._by_key.get(type_key)
        if t is None:
            if self._need_of is None:
                raise KeyError("未注册的目标类型：" + repr(type_key))
            return int(self._need_of(objective, type_key))
        if t.need is not None:
            return int(t.need(objective, self))
        return int(self._need_of(objective, type_key))

    # ---------------------------------------------------------------- 判定 / 折叠
    def hits(self, objective, event) -> list:
        """本次事件命中哪几型（**保序**）；`match=None` 的型永不命中。"""
        out = []
        for type_key, value, _need, _mods in self.parts(objective):
            cb = self._by_key[type_key].match
            if cb is not None and cb(value, event):
                out.append(type_key)
        return out

    def fold(self, objective, progress, event) -> dict:
        """逐命中型调 `fold` 并把返回的补丁合并（保序 `update`）；**不就地改** `progress`。"""
        patch = {}
        for type_key in self.hits(objective, event):
            cb = self._by_key[type_key].fold
            if cb is None:
                continue
            got = cb(objective, progress, event)
            if got:
                patch.update(got)
        return patch

    def satisfied(self, objective, progress) -> bool:
        """达成判定（**两个进度容器口径**）：

        * `progress` 是 mapping → 每个 `need > 0` 的 part 都要 `progress[值] >= need`
          （进度键 = 目标**值**，这是引擎唯一认的口径；键口径分歧见包 docstring ⑦）。
        * `progress` 不是 mapping（整格计数）→ 整格与每个 `need > 0` 的 part 的 need 比。
        * `need <= 0` 的 part **不拦**（现状 寻找/使用 这类 multi 型由内容侧另行置位）。
        * 空目标 → **False**（现状 `or {}` 之后没有键 → 永不达成）。
        """
        rows = self.parts(objective)
        if not rows:
            return False
        if isinstance(progress, Mapping):
            for _type_key, value, need, _mods in rows:
                if need <= 0:
                    continue
                if not _met(progress.get(value, 0), need):
                    return False
            return True
        for _type_key, _value, need, _mods in rows:
            if need <= 0:
                continue
            if not _met(progress, need):
                return False
        return True

    def complete(self, objective) -> bool:
        """**结构**判定：目标里至少有**一个已注册类型**（空目标 → False）。

        与 `satisfied` 是两个口径：`complete` 不看进度，`satisfied` 看进度。
        """
        return bool(self.parts(objective))

    # ---------------------------------------------------------------- 行文骨架
    def lines(self, objective, *, progress=None, state=None, text_of=None) -> list:
        """逐行目标文案**骨架**：`list[str]`，行序 = 目标 mapping 插入序（复合全出）。

        * `text_of(类型键, objective, progress, state) -> str | None`：**各出口自己的模板**
          （现状三份渲染行文不同）；给了就优先用它。
        * 否则用类型自己的 `text(objective, progress, state)`（`state` 原样当 ctx）。
        * 未注册的非修饰键 → 未注册且非修饰键 → 交给 `unknown(key, value)`；返回非 `None` 才出行。
        * 任何回调返回 `None` → 该型/该键不出行（引擎不产成品文案）。
        """
        if not isinstance(objective, Mapping):
            raise TypeError("目标必须是 mapping，收到 " + type(objective).__name__)
        if text_of is not None and not callable(text_of):
            raise TypeError("text_of 必须可调用（收类型键、目标、进度、阶段标量）")
        out = []
        for key, value in objective.items():
            t = self._by_key.get(key)
            if t is not None:
                if text_of is not None:
                    line = text_of(key, objective, progress, state)
                elif t.text is not None:
                    line = t.text(objective, progress, state)
                else:
                    line = None
            elif key in self._mods:
                continue
            else:
                line = self.unknown(key, value)
            if line is not None:
                out.append(line)
        return out

    def __repr__(self) -> str:
        return f"Objectives({list(self._order)!r})"


# ───────────────────────────────────────────────────────── 需求数批量提取
def parse_needs(objective, *, need_of=None, modifiers=()) -> dict:
    """目标 mapping → `{类型键: 需求数}`。

    把现状「`数量修饰 or 基础数`」与「只看基础数」两种口径**收敛到一个函数**，
    **取值由 `need_of` 注入**（引擎不替内容侧选一个）：

    * 注入了 `need_of(objective, key)` → 逐键调它。
    * 没注入 → 默认口径：按 `modifiers` 声明序取**首个正整数**修饰键值；都没有 → 1。
      ⚠️ 默认口径的修饰键名**必须由调用方给**（`count` / `数量` 这类都是取值，引擎不内置）。
    """
    if not isinstance(objective, Mapping):
        raise TypeError("目标必须是 mapping，收到 " + type(objective).__name__)
    mods = _as_names(modifiers, "modifiers")
    if need_of is not None and not callable(need_of):
        raise TypeError("need_of 必须可调用（收目标与类型键）")
    out = {}
    for key in objective:
        if key in mods:
            continue
        out[key] = (int(need_of(objective, key)) if need_of is not None
                    else _first_positive(objective, mods))
    return out
