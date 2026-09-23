# -*- coding: utf-8 -*-
"""准入链（Admission）—— 有序规则 → 首拒即返；副作用延迟到全过才执行。

**为什么有它**：一个「谁可以进来」的判定，在真实项目里总是被写成一段
`if …: 提示; return` 的长链，而且**同一批条件会被抄好几遍**（不同入口、不同阶段各一份）。
把条件本身拿掉，只剩三件通用的事 —— **有序**、**首拒即返**、**副作用延后**。

**用法**::

    from ext_world.run import Admission, Rule

    adm = Admission([
        Rule("size",  check=size_ok,  reason="人数不够"),
        Rule("key",   check=has_key,  reason=key_text, consume=deduct_key),
        Rule("place", check=here,     reason="位置不对"),
    ])
    v = adm.check(ctx)
    if not v.ok:
        show(v.reason)          # 措辞由内容侧给（引擎只搬运）
    # v.ok 时 consume 已按声明序执行过一次，v.ctx 是同一个对象

三条纪律：

1. **首拒即返**：第一条拒绝的规则之后的规则**不求值** —— `v.trace` 把他们记成 `skip`。
2. **副作用延迟**：`consume` 只在**全部规则通过后**按声明序各执行一次。
   「校验中段先把东西扣掉、后面又拒绝」这类白扣，从形状上不可能发生。
3. **判定与措辞分离**：`check` 只说通过与否，`reason` 负责怎么说 —— 换个游戏只换措辞。

**两种准入语义**（`mode=`）：

| mode | 含义 | 判定 |
|---|---|---|
| `"all"`（默认） | **全部满足才放行**（多重门槛：人数 + 钥匙 + 位置…） | 首拒即返 |
| `"any"` | **任一满足即放行**（多条放行通道：接了任务 / 有钥匙 / 已通关） | 首个通过即止 |

`any` 模式全不通过时，拒绝理由取链级 `reason`（给了就用），否则取**最后一条**规则的理由。

`check(ctx)` 的返回值约定：

| 返回 | 语义 |
|---|---|
| `None` / `True` | 通过 |
| `False` | 拒绝，用该规则的 `reason`（未给则 `未通过：<name>`） |
| `str` | 拒绝，**用这个字符串**（就地给措辞，覆盖 `reason`） |

`check` / `consume` 里抛异常**不吞**（内容侧 bug 当场暴露，与「自己写 if 链」的行为一致）。
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

__all__ = ["Rule", "Admission", "Verdict", "PASS", "DENY", "SKIP"]

PASS = "pass"
DENY = "deny"
SKIP = "skip"


class Rule:
    """一条命名的校验。

    :param name: 规则名（链内唯一，审计会查重名）
    :param check: `check(ctx) -> None/True 通过 | False 拒绝 | str 拒绝并给措辞`
    :param reason: 被 `False` 拒绝时的措辞；str 或 `callable(ctx) -> str`
    :param consume: 全过之后执行一次（按声明序）；`consume(ctx) -> Any`（返回值忽略）
    """

    __slots__ = ("name", "check", "reason", "consume")

    def __init__(self, name: str, check: Optional[Callable] = None, *, reason="",
                 consume: Optional[Callable] = None) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("规则名必须是非空字符串")
        self.name = name
        self.check = check
        self.reason = reason
        self.consume = consume

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"Rule({self.name!r})"

    def evaluate(self, ctx=None):
        """判定一次 → `(status, reason)`。"""
        if self.check is None:
            return PASS, ""
        out = self.check(ctx)
        if out is None or out is True:
            return PASS, ""
        if out is False:
            return DENY, self.reason_text(ctx)
        if isinstance(out, str):
            return DENY, out
        raise TypeError(
            f"规则 {self.name!r} 的 check 只能返回 None/True/False/str，"
            f"收到 {type(out).__name__}"
        )

    def reason_text(self, ctx=None) -> str:
        """`False` 拒绝时的措辞（callable 就地求值）。"""
        r = self.reason
        if callable(r):
            r = r(ctx)
        r = "" if r is None else str(r)
        return r or f"未通过：{self.name}"


class Verdict:
    """一次准入判定的结果。`bool(v)` == `v.ok`。"""

    __slots__ = ("ok", "rule", "reason", "ctx", "trace", "consumed")

    def __init__(self, ok: bool, rule, reason: str, ctx, trace, consumed: bool) -> None:
        self.ok = ok
        self.rule = rule            # 首个拒绝的规则名；通过时 None
        self.reason = reason        # 拒绝理由（内容侧措辞）；通过时 ""
        self.ctx = ctx              # 判定用的上下文（consume 就地改它）
        self.trace = trace          # ((rule_name, status, reason), …)
        self.consumed = consumed    # 是否执行过 consume

    def __bool__(self) -> bool:
        return bool(self.ok)

    @property
    def denied(self) -> bool:
        return not self.ok

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"Verdict(ok={self.ok}, rule={self.rule!r}, reason={self.reason!r})"


class Admission:
    """一条有序准入链。构造后规则表不可变（`rules` 是 tuple）。

    :param mode: `"all"`（默认，全过才放行，首拒即返）| `"any"`（任一通过即放行）
    :param reason: 链级拒绝措辞（主要给 `any` 模式用；str 或 `callable(ctx)`）
    """

    __slots__ = ("name", "rules", "on_pass", "mode", "reason")

    def __init__(self, rules: Sequence[Rule], *, name: str = "", on_pass=None,
                 mode: str = "all", reason="") -> None:
        if mode not in ("all", "any"):
            raise ValueError(f"mode 只能是 'all' 或 'any'，收到 {mode!r}")
        self.name = name
        self.rules = tuple(rules or ())
        self.on_pass = on_pass      # 全过（含 consume）之后调一次
        self.mode = mode
        self.reason = reason        # 链级措辞（any 模式全不过时用）

    def __len__(self) -> int:
        return len(self.rules)

    def rule_names(self):
        return tuple(r.name for r in self.rules)

    def check(self, ctx=None) -> Verdict:
        """跑一遍链。`all`：首拒即返、全过才执行 `consume`；`any`：首个通过即止。"""
        if self.mode == "any":
            return self._check_any(ctx)
        trace = []
        denied = None
        for i, rule in enumerate(self.rules):
            status, reason = rule.evaluate(ctx)
            trace.append((rule.name, status, reason))
            if status == DENY:
                denied = (rule, reason)
                trace.extend((r.name, SKIP, "") for r in self.rules[i + 1:])
                break
        if denied is not None:
            rule, reason = denied
            return Verdict(False, rule.name, reason, ctx, tuple(trace), False)
        for rule in self.rules:
            if rule.consume is not None:
                rule.consume(ctx)
        if self.on_pass is not None:
            self.on_pass(ctx)
        return Verdict(True, None, "", ctx, tuple(trace), True)

    def _check_any(self, ctx=None) -> Verdict:
        """任一通过即放行：按序判，首个通过即止；全不过 → 链级 reason / 末条规则 reason。"""
        trace = []
        last_reason = ""
        for i, rule in enumerate(self.rules):
            status, reason = rule.evaluate(ctx)
            trace.append((rule.name, status, reason))
            if status == PASS:
                trace.extend((r.name, SKIP, "") for r in self.rules[i + 1:])
                if rule.consume is not None:
                    rule.consume(ctx)
                if self.on_pass is not None:
                    self.on_pass(ctx)
                return Verdict(True, None, "", ctx, tuple(trace), rule.consume is not None)
            last_reason = reason or last_reason
        _r = self.reason
        if callable(_r):
            _r = _r(ctx)
        return Verdict(False, None, ("" if _r is None else str(_r)) or last_reason,
                       ctx, tuple(trace), False)

    def audit(self):
        """结构自检 → 问题列表（空列表 = 干净）。只报不改。"""
        problems = []
        if not self.rules:
            problems.append("空链（没有任何规则）")
        seen = set()
        for r in self.rules:
            if not isinstance(r, Rule):
                problems.append(f"非 Rule 成员：{r!r}")
                continue
            if r.name in seen:
                problems.append(f"规则名重复：{r.name}")
            seen.add(r.name)
            if r.check is None and r.consume is None:
                problems.append(f"规则 {r.name} 既无 check 也无 consume（空规则）")
        return problems
