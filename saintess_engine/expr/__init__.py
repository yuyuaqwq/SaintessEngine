# -*- coding: utf-8 -*-
"""v159 通用表达式数值公式——安全表达式解释器（预编译操作数栈）。

设计（鱼鱼拍板：数值公式任意自定义，伤害/治疗/增益/装备效果全支持）：
1. compile_expr(expr) → 操作数栈（token 化 + 转后缀，加载时编译一次，可缓存）
2. eval_expr(code, vars) → 数值（战斗时纯数字运算，无字符串解析，微秒级）

支持语法：
- 四则运算 + - * /
- 括号 ( )
- 一元负号 -x
- 数字字面量（含小数）
- 变量引用

安全：白名单 tokenizer（只认数字/变量/操作符/括号），不 eval 用户输入。

变量表（★ E4 2026-09-25：引擎**只留读口**，表本身归内容侧声明）
- 引擎侧只有两个读口：`declared_vars()`（问「有哪些变量、各自的值从哪来、显示名叫什么」）
  与 `variable_names()`（问「有哪些变量名」）。表由内容侧经 `config` 的 `expr_vars_fn` 声明
  （装配写法 `config.mount(expr_vars_fn=lambda: {...})`）。
- 未声明 ⇒ 沿用本模块的**默认表** `_DEFAULT_EXPR_VARS`（= 引擎历史那一份，逐条相同
  ⇒ 不装配时行为一字不变）。
- 声明口装了却给不出可用表 ⇒ 抛 `EngineNotConfigured`（fail-closed；**不**静默退回默认表）。
"""
import re

from ..config import EngineNotConfigured
from .. import config as _cfg

# ---------- 变量表：内容侧声明（★ E4）+ 默认表 ----------
#
# 声明口：`config.mount(expr_vars_fn=lambda: <表>)`（hook 名在 `config._HOOKS` 名单里）
#   形状 = `fn() -> dict`；键 = 变量名（表达式里直接写这个名字），值 = 一条声明：
#     {"label": <显示名（`translate_expr` 中文翻译用；可省，省了就保持变量名原样）>,
#      "source": <取值来源（必给）>}
#   取值来源三类 —— 引擎提供的**通用原语**（不含任何游戏语义）：
#     {"from": "stat",  "key": <k>}     ← 属性快照 `stats[k]`（缺 → 0）
#     {"from": "input", "key": <k>}     ← `build_vars` 的具名入参（键名 = 它的参数名）
#         可选 "else": <source>          ← 该入参为 None 时改读这条
#     {"from": "const", "value": <v>}   ← 固定值
#
#: 默认变量表：**引擎历史那一份**（旧 `VARIABLE_WHITELIST` 的 13 个名字 × 旧 `_VAR_CN`
#: 的显示名，逐条搬成同一张表；`crit_mult` 的 1.5 原写死在 `build_vars` 里）。内容侧一声明
#: 就**整表替换** —— 引擎不认识「某款游戏该有哪些变量」，只认识「去哪问这张表」。
_DEFAULT_EXPR_VARS = {
    "atk": {"label": "攻击", "source": {"from": "stat", "key": "atk"}},
    "matk": {"label": "魔法攻击", "source": {"from": "stat", "key": "matk"}},
    "def": {"label": "防御", "source": {"from": "stat", "key": "def"}},
    "mdef": {"label": "魔法防御", "source": {"from": "stat", "key": "mdef"}},
    "max_hp": {"label": "最大生命", "source": {"from": "stat", "key": "max_hp"}},
    "hp": {"label": "当前生命", "source": {"from": "stat", "key": "hp"}},
    "spd": {"label": "速度", "source": {"from": "stat", "key": "spd"}},
    "crit": {"label": "暴击", "source": {"from": "stat", "key": "crit"}},
    "player_lv": {"label": "玩家等级", "source": {"from": "input", "key": "player_lv"}},
    "skill_lv": {"label": "技能等级", "source": {"from": "input", "key": "skill_lv"}},
    "crit_mult": {"label": "暴击倍率", "source": {"from": "const", "value": 1.5}},
    "target_max_hp": {"label": "目标最大生命",
                      "source": {"from": "input", "key": "target_max_hp",
                                 "else": {"from": "stat", "key": "max_hp"}}},
    "base": {"label": "基础值", "source": {"from": "input", "key": "base"}},
}


#: 取值来源的**全部**合法类别（引擎提供的通用原语，均不含游戏语义）
_SOURCE_KINDS = ("stat", "input", "const")


def _validate_source(source, var_name: str, path: str) -> None:
    """校验一条来源声明；不合法 ⇒ 抛 `EngineNotConfigured`（fail-closed）。

    校验在**读表时**做（不是用到才做）：一个没被任何表达式引用的坏条目也要当场现形 ——
    否则它会静静躺在表里，等某天有人写了引用它的公式才炸。
    """
    kind = source.get("from") if isinstance(source, dict) else None
    if kind not in _SOURCE_KINDS:
        raise EngineNotConfigured(
            "expr_vars_fn 变量 %r 的 %s 来源类别 %r 引擎不认（只认 %s）—— "
            "形状见 saintess_engine.expr 模块头"
            % (var_name, path, kind, " / ".join(_SOURCE_KINDS)))
    if source.get("else") is not None:
        _validate_source(source["else"], var_name, path + ".else")


def declared_vars() -> dict:
    """**当前生效**的变量表（内容侧声明优先；未声明 ⇒ 默认表 `_DEFAULT_EXPR_VARS`）。

    引擎唯一的变量表读口：「有哪些变量、值从哪来、显示名叫什么」全在表里，表由内容侧给
    （`config.mount(expr_vars_fn=...)`，形状见模块头）。

    ★ fail-closed：装了声明口却给不出可用表（`None` / 空 / 不是 dict / 有条目缺 `source` /
      来源类别不认）⇒ 抛 `EngineNotConfigured`，**不**静默退回默认表（写错的声明不许无声无息）。
      注：这是**「没声明」（走默认表，与历史逐字一致）**与**「声明了但坏」（抛）**两态的分界。
    """
    fn = _cfg.get_hook("expr_vars_fn")
    if fn is None:
        return _DEFAULT_EXPR_VARS
    table = fn()
    if not isinstance(table, dict) or not table:
        raise EngineNotConfigured(
            "expr_vars_fn 声明无效：要是**非空 dict**（键 = 变量名，"
            "值 = {'label': …, 'source': …}）—— 形状见 saintess_engine.expr 模块头")
    for _name, _spec in table.items():
        if not isinstance(_spec, dict) or not isinstance(_spec.get("source"), dict):
            raise EngineNotConfigured(
                "expr_vars_fn 变量 %r 的声明缺 `source`（取值来源）—— "
                "形状见 saintess_engine.expr 模块头" % (_name,))
        _validate_source(_spec["source"], _name, "source")
    return table


def variable_names() -> tuple:
    """当前生效的**变量名**（按声明顺序）—— 旧 `VARIABLE_WHITELIST` 的读口。"""
    return tuple(declared_vars())


_TOKEN_RE = re.compile(r"""
    \s*(?:
        (?P<num>\d+\.?\d*|\.\d+)   # 数字
      | (?P<var>[A-Za-z_][A-Za-z0-9_]*)  # 变量
      | (?P<op>[+\-*/()^])         # 操作符/括号（★ `^` = 幂，2026-09-21 新增）
    )
""", re.VERBOSE)

# 操作符优先级（★ `^` 最高 —— 幂高于乘除，且**右结合**：a^b^c = a^(b^c)）
_PREC = {"+": 1, "-": 1, "*": 2, "/": 2, "^": 4}
#: 右结合的二元操作符。★ 为什么单独一张表：现行 shunting-yard 对同优先级一律弹栈
#: （左结合）；`^` 必须反过来（不弹同优先级）才能得到 a^(b^c)。
#: 不含 `^` 的表达式走不到这条分支 ⇒ 编译产物与新增前**逐项相同**（零回归）。
_RIGHT_ASSOC = {"^"}
_UNARY = {"-": 3}  # 一元负号优先级最高

#: 编译缓存：表达式串 → 操作数栈。串来自数据表（技能/装备/食物公式），取值集合有限
#: 且稳定；预编译产物是**纯数据**（eval_expr 只读遍历，不改写）⇒ 同串复用同一份。
_COMPILE_CACHE: dict = {}
#: 缓存上界：防内容侧动态拼串把内存顶爆（超界整体清空，不做 LRU 记账）。
_COMPILE_CACHE_MAX = 8192


class ExprError(ValueError):
    """表达式语法错误。"""


def compile_expr(expr: str):
    """解析表达式字符串 → 操作数栈（逆波兰/后缀）。

    返回 list，每项：
      ("num", float)          数字字面量
      ("var", str)            变量名（求值时从 vars 取）
      ("op", str)             二元操作符 + - * /
      ("neg",)                一元负号（作用于栈顶）
    预编译一次，战斗时 eval_expr 反复求值（无字符串解析）；同串命中 _COMPILE_CACHE，不重复解析。
    """
    if expr is None:
        return None
    expr = str(expr).strip()
    if not expr:
        return None

    cached = _COMPILE_CACHE.get(expr)
    if cached is not None:
        return cached

    tokens = []
    pos = 0
    prev_token = None  # 判断一元/二元（表达式开头或操作符/左括号后 = 一元）
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if not m:
            # 跳过空白
            if expr[pos].isspace():
                pos += 1
                continue
            raise ExprError(f"无法解析字符 {expr[pos]!r} @{pos} in '{expr}'")
        pos = m.end()
        if m.group("num") is not None:
            tokens.append(("num", float(m.group("num"))))
            prev_token = "num"
        elif m.group("var") is not None:
            tokens.append(("var", m.group("var")))
            prev_token = "var"
        else:
            op = m.group("op")
            if op in "(":
                tokens.append(("lparen",))
                prev_token = "("
            elif op == ")":
                tokens.append(("rparen",))
                prev_token = ")"
            # ★ 2026-09-21：`^` 必须进这张分派名单 —— 否则令牌会被**静默丢弃**
            #   （实测：漏了这一处 ⇒ `2^3` 编译成 `[num 2, num 3]`，报「栈不归约到单值」而**不是**语法错，
            #    报错类型误导，很难查）。这是 P3 的**第 4 个改动点**。
            elif op in "+-*/^":
                # 一元负号：表达式开头 / 操作符后 / 左括号后
                unary = (prev_token is None or prev_token in "+-*/( ")
                if unary and op == "-":
                    tokens.append(("neg",))
                elif unary:
                    # 一元正号 + 直接忽略
                    pass
                else:
                    tokens.append(("op", op))
                prev_token = op
    if pos != len(expr):
        raise ExprError(f"表达式不完整 '{expr}'")

    # 中缀 → 后缀（Shunting-yard）
    out = []
    ops = []
    for tok in tokens:
        t = tok[0]
        if t == "num":
            out.append(tok)
        elif t == "var":
            out.append(tok)
        elif t == "lparen":
            ops.append(tok)
        elif t == "rparen":
            while ops and ops[-1][0] != "lparen":
                out.append(ops.pop())
            if not ops:
                raise ExprError(f"括号不匹配 '{expr}'")
            ops.pop()
        elif t == "neg":
            # 一元负号压栈（优先级高于二元）
            ops.append(("neg",))
        elif t == "op":
            p = _PREC[tok[1]]
            while ops and ops[-1][0] in ("op", "neg"):
                if ops[-1][0] == "neg" and p <= _UNARY["-"]:
                    out.append(ops.pop())
                elif ops[-1][0] == "op" and (
                        p < _PREC[ops[-1][1]]
                        or (p == _PREC[ops[-1][1]] and tok[1] not in _RIGHT_ASSOC)):
                    # ★ 左结合：同优先级弹栈（原行为不变）；右结合（`^`）：同优先级**不弹**
                    out.append(ops.pop())
                else:
                    break
            ops.append(tok)
    while ops:
        if ops[-1][0] == "lparen":
            raise ExprError(f"括号不匹配 '{expr}'")
        out.append(ops.pop())
    if len(_COMPILE_CACHE) >= _COMPILE_CACHE_MAX:
        _COMPILE_CACHE.clear()
    _COMPILE_CACHE[expr] = out
    return out


def eval_expr(code, vars_: dict | None = None) -> float:
    """对预编译操作数栈求值。vars：变量 → 数值 dict（缺失变量取 0）。

    code 为 compile_expr 的输出；直接传入原始字符串时自动编译（方便测试/单次调用）。
    """
    if code is None:
        return 0.0
    if isinstance(code, str):
        code = compile_expr(code)
    if code is None:
        return 0.0
    v = vars_ or {}
    stack = []
    for tok in code:
        t = tok[0]
        if t == "num":
            stack.append(tok[1])
        elif t == "var":
            stack.append(float(v.get(tok[1], 0.0) or 0.0))
        elif t == "neg":
            if not stack:
                raise ExprError("一元负号缺少操作数")
            stack.append(-stack.pop())
        elif t == "op":
            if len(stack) < 2:
                raise ExprError("表达式缺少操作数")
            b = stack.pop()
            a = stack.pop()
            o = tok[1]
            if o == "+":
                stack.append(a + b)
            elif o == "-":
                stack.append(a - b)
            elif o == "*":
                stack.append(a * b)
            elif o == "/":
                stack.append(a / b if b != 0 else 0.0)
            elif o == "^":
                # ★ `^` = 幂（2026-09-21 新增，用于 F5 的 `(SPD_REF/spd)^α`）
                try:
                    _r = a ** b
                except (OverflowError, ZeroDivisionError, ValueError):
                    _r = 0.0
                # 负底数 + 分数指数 ⇒ Python 返回复数（`float()` 会 TypeError）
                # ⇒ 按引擎既有「不抛、退化为 0」的口径处理（同除零）
                stack.append(float(_r) if not isinstance(_r, complex) else 0.0)
    if len(stack) != 1:
        raise ExprError("表达式求值异常（栈不归约到单值）")
    return stack[0]


# ---------- 内置变量解析辅助（战斗/结算层用） ----------

def _value_of(source: dict, stats: dict, inputs: dict) -> float:
    """按**来源声明**取一个变量的值（三类通用原语，见模块头）。

    未知来源类别 ⇒ 抛 `EngineNotConfigured`（fail-closed：不静默当 0，
    否则声明里写错一个来源名就会「变量恒 0」而没人发现）。
    """
    kind = (source or {}).get("from")
    if kind == "stat":
        return float(stats.get(source.get("key"), 0) or 0)
    if kind == "input":
        val = inputs.get(source.get("key"))
        if val is None:
            _else = source.get("else")
            if _else is None:
                return 0.0
            return _value_of(_else, stats, inputs)
        return float(val or 0)
    if kind == "const":
        return float(source.get("value") or 0)
    raise EngineNotConfigured(
        "表达式变量取值来源 %r 引擎不认（只认 stat / input / const）—— "
        "形状见 saintess_engine.expr 模块头" % (kind,))


def build_vars(stats: dict, player_lv: int = 0, skill_lv: int = 0,
               target_max_hp: float | None = None, base: float = 0.0) -> dict:
    """从属性快照构建表达式变量 dict。

    ★ E4：键集合**不再写死** —— 按**当前生效的变量表**（`declared_vars()`，内容侧声明；
      未声明 ⇒ 默认表 = 历史那一份）逐条按声明的来源取值 ⇒ 换一张表 = 换一套变量，
      引擎代码零改动。

    stats: 属性 dict（供 `{"from": "stat", "key": ...}` 读）
    四个具名入参（供 `{"from": "input", "key": ...}` 读，键名 = 本函数参数名）：
      player_lv: 玩家等级 / skill_lv: 技能等级 /
      target_max_hp: 目标最大生命（敌方，可选；None = 没给 ⇒ 可声明 `else` 回落）/
      base: 技能基础值（skill_flat 注入后，可选）
    """
    s = stats or {}
    inputs = {"player_lv": player_lv, "skill_lv": skill_lv,
              "target_max_hp": target_max_hp, "base": base}
    return {_n: _value_of(_sp.get("source"), s, inputs)
            for _n, _sp in declared_vars().items()}


def expr_or(value, fallback):
    """工具：取表达式（字符串）或旧格式（dict 段），返回可传给 eval_expr 的代码。"""
    if isinstance(value, str):
        return compile_expr(value)
    return fallback


# ---------- 表达式 → 中文公式翻译（技能详情展示用） ----------

def labels_of() -> dict:
    """变量名 → **显示名**（只含当前变量表里**声明了 `label`** 的那些）。

    显示名属内容：引擎不认识「某个变量该显示成什么中文」——表由内容侧声明（见模块头）。
    未声明 ⇒ 默认表里那一份（历史显示名，逐条相同）。
    """
    return {_n: _sp["label"] for _n, _sp in declared_vars().items()
            if _sp.get("label")}


def translate_expr(expr: str) -> str:
    """把表达式字符串翻译成人类可读中文公式（技能详情展示用）。

    例：'(atk*0.8 + player_lv*5) * (1 + skill_lv*0.1)'
      → '(攻击×0.8 + 玩家等级×5) × (1 + 技能等级×0.1)'

    - 变量名替换为**当前变量表里声明的显示名**（最长词优先，避免 player_lv 被 lv 之类误切）
    - * → ×、/ → ÷（只替换非注释部分；表达式不含注释，直接全量替换）
    - 表里没 label / 不在表里的变量保持原样（不 panic）
    """
    if not expr:
        return ""
    out = str(expr)
    # 变量替换：按**变量名长度**降序（player_lv > skill_lv > max_hp > hp），
    # 用正则 \b 词边界避免 'atk' 误中 'matk' 等子串。
    import re as _re
    _labels = labels_of()
    for _var in sorted(_labels, key=len, reverse=True):
        out = _re.sub(rf"\b{_var}\b", _labels[_var], out)
    out = out.replace("*", "×").replace("/", "÷")
    return out
