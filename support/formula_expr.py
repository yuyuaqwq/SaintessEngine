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
- 变量引用（白名单，见 VARIABLE_WHITELIST）

安全：白名单 tokenizer（只认数字/变量/操作符/括号），不 eval 用户输入。
"""
import re

# 可用变量白名单（引擎注入值；未知变量 → 0）
VARIABLE_WHITELIST = {
    "atk", "matk", "def", "mdef", "max_hp", "hp", "spd", "crit",
    "player_lv", "skill_lv", "crit_mult", "target_max_hp", "base",
}

_TOKEN_RE = re.compile(r"""
    \s*(?:
        (?P<num>\d+\.?\d*|\.\d+)   # 数字
      | (?P<var>[A-Za-z_][A-Za-z0-9_]*)  # 变量
      | (?P<op>[+\-*/()])          # 操作符/括号
    )
""", re.VERBOSE)

# 操作符优先级
_PREC = {"+": 1, "-": 1, "*": 2, "/": 2}
_UNARY = {"-": 3}  # 一元负号优先级最高


class ExprError(ValueError):
    """表达式语法错误。"""


def compile_expr(expr: str):
    """解析表达式字符串 → 操作数栈（逆波兰/后缀）。

    返回 list，每项：
      ("num", float)          数字字面量
      ("var", str)            变量名（求值时从 vars 取）
      ("op", str)             二元操作符 + - * /
      ("neg",)                一元负号（作用于栈顶）
    预编译一次，战斗时 eval_expr 反复求值（无字符串解析）。
    """
    if expr is None:
        return None
    expr = str(expr).strip()
    if not expr:
        return None

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
            elif op in "+-*/":
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
                elif ops[-1][0] == "op" and p <= _PREC[ops[-1][1]]:
                    out.append(ops.pop())
                else:
                    break
            ops.append(tok)
    while ops:
        if ops[-1][0] == "lparen":
            raise ExprError(f"括号不匹配 '{expr}'")
        out.append(ops.pop())
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
    if len(stack) != 1:
        raise ExprError("表达式求值异常（栈不归约到单值）")
    return stack[0]


# ---------- 内置变量解析辅助（战斗/结算层用） ----------

def build_vars(stats: dict, player_lv: int = 0, skill_lv: int = 0,
               target_max_hp: float | None = None, base: float = 0.0) -> dict:
    """从属性快照构建表达式变量 dict。

    stats: 属性 dict（atk/matk/def/mdef/max_hp/hp/spd/crit…）
    player_lv: 玩家等级
    skill_lv: 技能等级
    target_max_hp: 目标最大生命（敌方，可选）
    base: 技能基础值（skill_flat 注入后，可选）
    """
    s = stats or {}
    vars_ = {
        "atk": float(s.get("atk", 0) or 0),
        "matk": float(s.get("matk", 0) or 0),
        "def": float(s.get("def", 0) or 0),
        "mdef": float(s.get("mdef", 0) or 0),
        "max_hp": float(s.get("max_hp", 0) or 0),
        "hp": float(s.get("hp", 0) or 0),
        "spd": float(s.get("spd", 0) or 0),
        "crit": float(s.get("crit", 0) or 0),
        "player_lv": float(player_lv or 0),
        "skill_lv": float(skill_lv or 0),
        "crit_mult": 1.5,
        "target_max_hp": float(target_max_hp or 0) if target_max_hp is not None else float(s.get("max_hp", 0) or 0),
        "base": float(base or 0),
    }
    return vars_


def expr_or(value, fallback):
    """工具：取表达式（字符串）或旧格式（dict 段），返回可传给 eval_expr 的代码。"""
    if isinstance(value, str):
        return compile_expr(value)
    return fallback


# ---------- 表达式 → 中文公式翻译（技能详情展示用） ----------

# 变量名 → 中文名（v160 技能详情展示；顺序无关，最具体的放前面避免子串误替换）
_VAR_CN = {
    "player_lv": "玩家等级",
    "skill_lv": "技能等级",
    "target_max_hp": "目标最大生命",
    "crit_mult": "暴击倍率",
    "max_hp": "最大生命",
    "matk": "魔法攻击",
    "mdef": "魔法防御",
    "atk": "攻击",
    "def": "防御",
    "spd": "速度",
    "crit": "暴击",
    "hp": "当前生命",
    "base": "基础值",
}


def translate_expr(expr: str) -> str:
    """把表达式字符串翻译成人类可读中文公式（技能详情展示用）。

    例：'(atk*0.8 + player_lv*5) * (1 + skill_lv*0.1)'
      → '(攻击×0.8 + 玩家等级×5) × (1 + 技能等级×0.1)'

    - 变量名替换为中文（最长词优先，避免 player_lv 被 lv 之类误切）
    - * → ×、/ → ÷（只替换非注释部分；表达式不含注释，直接全量替换）
    - 未知变量保持原样（不 panic）
    """
    if not expr:
        return ""
    out = str(expr)
    # 变量替换：按中文名长度降序（player_lv > skill_lv > max_hp > hp），
    # 用正则 \b 词边界避免 'atk' 误中 'matk' 等子串。
    import re as _re
    for _var in sorted(_VAR_CN, key=len, reverse=True):
        out = _re.sub(rf"\b{_var}\b", _VAR_CN[_var], out)
    out = out.replace("*", "×").replace("/", "÷")
    return out
