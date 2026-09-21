# -*- coding: utf-8 -*-
"""掉落池预览（编辑器用）—— 用引擎**同一份** LootTable 代码算结构与权重。

为什么值得为它破一条纪律
------------------------
`editor/packages.py` 写着「编辑器主进程零引擎副作用，不 import `saintess_engine`」——
那条纪律针对的是**会挂 hook / 改全局状态**的战斗域。`saintess_engine.loot` 是**纯计算模块**
（池 + 策略注册表 + 展开 + 审计；零挂载、零全局副作用，与 `space` / `version` 同性质），
import 它不产生任何引擎副作用。

换来的东西是硬的：权重的算法、展开的规则、审计的判据**只有一份实现** ——
编辑器里看到的「这条多常见 / 子池能出什么 / 哪里断链」和游戏里跑的同一段代码。
若在前端用 JS 重写一遍（权重归一、cutoff 累计、展开递归），两处迟早漂移，
而且漂移时**没人会发现**（编辑器好看，游戏里不出货）。

引擎零知识 → 编辑器不许装懂
---------------------------
`LootTable` 在这里的 `resolver=None`（内容侧才持有引用解析）。因此预览**只**展示：
结构与权重、展开候选、结构审计。它**不假装知道**某个引用（`mat_a`）是哪件物品、
是哪个池 —— 需要解析才能回答的部分，一律写进 `warnings`，宁可让用户看到「这里要
内容侧 resolver」，也不编一个看起来合理的答案。

包内引用词汇声明（可选；不写 = 今天的行为）
------------------------------------------
引擎零知识 ⇒ 「哪些引用写法算解得开」只能由**内容侧**声明。内容侧把它写在包里 ——
就是框架的**声明表域** `loot_vocab`（`content/rules/loot_vocab.json`，一条 = 一个域）：

    {
      "drop_pools": {                        ← 外层键 = 它服务的**框架域 id**
        "version": 1,
        "inline_prefixes":   ["…"],          # 命中即「内容侧自管」，审计跳过；也参与 expand 外列
        "special_refs":      ["…"],          # 精确值特殊引用，同上
        "pool_key_prefixes": ["…"],          # 子池 key 可能带的前缀（查表时先剥）
        "external_prefixes": ["…"],          # 只影响审计（不判断链），**不**参与 expand 外列
        "ref_domains":       ["items"],      # 裸 ref 落在这些**域**里 → 才算解得开（见下）
        "ref_prefix_domains": {"mat:": "materials"}   # 带前缀的引用：剥前缀查那个**域**的主键（见下）
      }
    }

框架只认键、不认值：它对这份声明的处理是一句机械的话 ——「把它交给引擎的
`inline_prefixes` / `special_refs` / `pool_key_prefixes` / `resolvable`」，一个具体前缀、
一个具体池名都没进框架（`tests/test_no_game_vocabulary.py` 守这条）。

* 表/条缺少、JSON 坏、形状不对、键缺失 → 一律当**空声明**：不抛错、不 500，行为与
  没有这个功能时逐值一致（`load_vocab` 的容错是这功能的骨头：它是**可选增强**）。
* 只声明 `external_prefixes`（未声明 `ref_domains`）→ 命中该前缀的引用不问；其余引用照旧
  **不判**（`resolvable` 回 None）→ 与今天同结论。
* 声明了 `ref_domains` → 审计才**有意义**：裸 ref 拿去查**包自己**那些域的表主键，
  查不到就报断链（措辞由引擎给）。「哪些域装 ref」也是内容侧说的，框架不预设。
* 声明了 `ref_prefix_domains` → **带前缀的引用也能判**（`{"前缀": "域 id"}`）：命中该前缀的引用，
  剥掉前缀后的 id 要能在那个域的表主键里找到 —— 找到 `True`、找不到 `False`（真断链）。
  比 `external_prefixes` 严一档（后者一律不判「对不对」，只说「别喊断链」）；
  同一个前缀两处都声明时**以本键为准**（更严的赢，避免一份声明里两句话打架）。
  值允许写域 id 列表（任一域命中即算解得开）。它同样**不**参与 expand 外列（不猜权重）。

对外接口
--------
    build(entry, key="", pools=None, vocab=None) -> dict   # 单条池数据 → 预览（含 warnings）
    build_file(data, key, vocab=None) -> dict              # 表形态取一条（key 不存在 → {ok: False, error}）
    audit_file(data, vocab=None) -> dict                   # 整表结构审计（域级端点用）
    load_vocab(pkg_dir, entry="drop_pools") -> dict        # 读包内声明（坏/缺 → 空声明）
    normalize_vocab(raw, pkg_dir=None) -> dict              # 归一（也可直接喂原始 JSON 对象）

（`vocab` 可传 `load_vocab()` 的结果，也可传声明原文；两者都做一次幂等归一。）

返回（ok=True）：`{ok, key, type, strategy_uses, entries, rolls, expanded_count,
expanded_unique, audit: {ok, issues}, warnings}`；坏数据 / 池不存在 → `{ok: False, error, warnings}`。
"""
from __future__ import annotations

# 纯计算模块：不挂 hook、不改全局（同 space / version 的性质）
from saintess_engine.loot import STRATEGIES, LootTable, UnknownStrategy, weigh

_ANCHOR = "__pool__"          # key 缺省时的锚点（只用于表内查找，不对外露出）

_NO_RESOLVER = ("引用解析需要内容侧提供 resolver —— 预览只显示结构与权重，"
                "不判断某个引用（如 mat_a）到底是什么东西、也不会替它编一个答案。")
_LEVEL_WINDOW = ("有条目带等级窗口（min_lv / max_lv）：实际会不会进候选取决于上下文等级"
                 "（player_level / monster_lv），预览没有上下文，占比是按**全量权重**算的。")

# ---------------- 包内引用词汇声明（见模块 docstring） ----------------
# 声明是**框架域** `loot_vocab`（content/rules/loot_vocab.json）里的一条：
#   {"drop_pools": {inline_prefixes/special_refs/pool_key_prefixes/external_prefixes/ref_domains}}
# 外层键 = 它服务的**框架域 id**（本视图服务的域 = VOCAB_ENTRY）。
VOCAB_DOMAIN = "loot_vocab"
VOCAB_ENTRY = "drop_pools"
# 声明里框架**认识**的键（其余键一律忽略：内容侧给自己加的字段不影响行为）
VOCAB_PREFIX_KEYS = ("inline_prefixes", "special_refs", "pool_key_prefixes", "external_prefixes")
VOCAB_DOMAIN_KEY = "ref_domains"
VOCAB_PREFIX_DOMAIN_KEY = "ref_prefix_domains"     # {"前缀": "域 id" | ["域 id", …]}：带前缀的引用也判
VOCAB_KEYS = VOCAB_PREFIX_KEYS + (VOCAB_DOMAIN_KEY, VOCAB_PREFIX_DOMAIN_KEY, "ref_keys", "version")

_VOCAB_NOTE = ("本包带引用词汇声明（{path}）：审计按包自己的说法判「哪些引用解得开」，"
               "框架不认识任何具体前缀 / 池名。声明里没提到的部分，照旧不猜。")


def _str_list(v) -> tuple:
    """只留非空字符串（声明里混进数字 / null / 嵌套对象都不该让预览崩）。"""
    if isinstance(v, (list, tuple, set, frozenset)):
        return tuple(x.strip() for x in v if isinstance(x, str) and x.strip())
    if isinstance(v, str) and v.strip():        # 单个字符串当一元列表收下（宽容，不报错）
        return (v.strip(),)
    return ()


def _domain_keys(pkg_dir: str, domains) -> set:
    """声明里那批**域**的表主键集合（`ref_domains` 的落地）。

    零知识的关键：查的是**包自己**的表、按的是框架**域注册表**（`editor/packages.py`），
    框架没有硬编码任何 ref 取值。域不认识 / 表读不出来 → 空集（声明降级，不抛）。
    """
    if not domains or not pkg_dir:
        return set()
    try:
        from editor import packages as PK      # 同目录模块（延迟导入：避免 import 期耦合）
    except Exception:                          # noqa: BLE001
        return set()
    keys: set = set()
    domains_eff, _w = PK.effective_domains(pkg_dir)     # 有效域表：内置 + 包自带声明
    for d in domains:
        if d not in domains_eff:
            continue
        try:
            tbl = PK.read_json(PK.domain_path(pkg_dir, d, domains_eff), {})
        except Exception:                      # noqa: BLE001
            continue
        if isinstance(tbl, dict):
            keys.update(k for k in tbl if isinstance(k, str))
    return keys


def _prefix_domain_keys(raw, pkg_dir: str) -> dict:
    """`ref_prefix_domains`（{"前缀": "域 id" | ["域 id", …]}）→ {"前缀": frozenset(域主键)}。

    与 `ref_domains` 同一条纪律：**域不认识 / 表读不出来 → 这个前缀就当没说**（丢掉，
    不拿空集去判 —— 那会把整族引用全报成断链，是假红）。畸形输入一律丢掉，不抛。
    """
    out: dict = {}
    if not isinstance(raw, dict):
        return out
    for pref, doms in raw.items():
        if not isinstance(pref, str) or not pref:
            continue
        if isinstance(doms, str):
            doms = [doms]
        if not isinstance(doms, (list, tuple)):
            continue
        keys = _domain_keys(pkg_dir, [d for d in doms if isinstance(d, str) and d])
        if keys:
            out[pref] = frozenset(keys)
    return out


def normalize_vocab(raw=None, pkg_dir: str | None = None) -> dict:
    """把「声明」（包内 JSON 对象 / `load_vocab()` 的结果 / None）归一成内部形状。

    * 未知键忽略；坏值忽略；**任何**畸形输入都得到「空声明」而不是异常
    * `ref_domains` 声明的域 → 展开成 `ref_keys`（包内那些表的主键；`pkg_dir` 缺省则不展开）
    * `declared` = 这份声明**真的能改变判定吗**（有前缀声明，或至少查到了 ref 主键）。
      只声明了一个域、而包内没有那张表（或域名根本不认识）→ `declared=False`：
      等于什么都没说，行为必须与「没有这个文件」逐值相同。
    """
    src = raw if isinstance(raw, dict) else {}
    out = {k: _str_list(src.get(k)) for k in VOCAB_PREFIX_KEYS}
    out[VOCAB_DOMAIN_KEY] = _str_list(src.get(VOCAB_DOMAIN_KEY))
    keys = set(_str_list(src.get("ref_keys")))
    keys |= _domain_keys(pkg_dir or "", out[VOCAB_DOMAIN_KEY])
    out["ref_keys"] = frozenset(keys)
    raw_prefix_domains = src.get(VOCAB_PREFIX_DOMAIN_KEY)
    out[VOCAB_PREFIX_DOMAIN_KEY] = raw_prefix_domains if isinstance(raw_prefix_domains, dict) else {}
    pre = _prefix_domain_keys(out[VOCAB_PREFIX_DOMAIN_KEY], pkg_dir or "")
    if not pre:
        # 幂等：喂进来的本来就是**归一过的**内部形状（`load_vocab()` 的结果再进 `audit_file()`），
        # 而这次没给 pkg_dir（拿不到包内表主键）→ 别把已经展开好的丢掉（丢了 = 整族引用假红）。
        src_pre = src.get("ref_prefix_keys")
        if isinstance(src_pre, dict):
            pre = {k: frozenset(v) for k, v in src_pre.items()
                   if isinstance(k, str) and k and isinstance(v, (list, tuple, set, frozenset))}
    out["ref_prefix_keys"] = pre
    out["declared"] = bool(any(out[k] for k in VOCAB_PREFIX_KEYS) or out["ref_keys"]
                           or out["ref_prefix_keys"])
    return out


def load_vocab(pkg_dir: str, entry: str = VOCAB_ENTRY) -> dict:
    """读包内声明表 `content/rules/loot_vocab.json` 里 `entry` 那条；**缺表/缺条/坏 JSON/形状错 → 空声明**。

    为什么不抛错：这是**可选增强**。内容包没有它（绝大多数包）时，编辑器必须与加这功能
    之前逐格一致 —— 一个坏的声明文件不该让预览 500，只该让它退回「不猜」。

    路径不硬编码：走框架域注册表 `editor/packages.py:domain_path()`（kind=rules），
    与其它域同一条约定。
    """
    raw = None
    if pkg_dir:
        try:
            from editor import packages as PK      # 同目录模块（延迟导入）
            tbl = PK.read_json(PK.domain_path(pkg_dir, VOCAB_DOMAIN), {})
            raw = tbl.get(entry) if isinstance(tbl, dict) else None
        except Exception:                          # noqa: BLE001
            raw = None
    return normalize_vocab(raw, pkg_dir)


def _make_resolvable(v: dict):
    """声明 → 引擎审计要的 `resolvable(ref, pool)` 回调（`True`/`False`/`str`/`None`）。

    * 命中 `ref_prefix_domains`（前缀 → 域）→ **真判**：剥掉前缀查那个域的主键，
      在 → `True`；不在 → `False`（引擎给通用措辞，断链）。这一条优先于 `external_prefixes`：
      同一前缀两处都声明时，更严的那句说了算。长前缀优先匹配（`a:` 与 `ab:` 并存时不误判）。
    * 命中 `external_prefixes` → `True`（内容侧自管的引用，框架不判）。
      与 `inline_prefixes` 刻意分开：后者会被引擎 `expand()` 当成候选前缀**外列**，
      这里只要「审计别喊断链」，不想动展开语义。
    * 声明了 `ref_keys`（来自 `ref_domains`）→ 裸 ref 查包内那些域的主键：在 → `True`；
      不在 → `False`（引擎给通用措辞，断链）—— 这正是「声明之后审计才有意义」。
    * 只有 `external_prefixes`、没有 `ref_domains` → 其余引用回 `None`（不判），
      与「完全没有声明」时的结论一致（不留新假红）。
    * 两者都没有 → 回 `None`（= 不传回调，引擎的 entries 一律不判）。
    """
    ext = v["external_prefixes"]
    keys = v["ref_keys"]
    pre = v.get("ref_prefix_keys") or {}
    if not ext and not keys and not pre:
        return None
    by_len = sorted(pre, key=len, reverse=True)      # 长前缀先比，避免 "a:" 抢走 "ab:x"

    def resolvable(ref, pool):                 # noqa: ARG001（pool 是引擎契约的一部分）
        if not isinstance(ref, str):
            return False
        for p in by_len:
            if ref.startswith(p):
                return ref[len(p):] in pre[p]
        if ext and ref.startswith(ext):
            return True
        if not keys:
            return None
        return True if ref in keys else False

    # 「内联前缀」默认是「内容侧自管、审计跳过」；但内容侧**同时**声明了「前缀→域」时，
    # 这族内联引用其实是有落点的 → 给回调挂上引擎认的属性，让它们**照判**（更严）。
    # 不挂 = 完全旧行为（对没声明的包零影响）。
    inline = tuple(v["inline_prefixes"])
    judged = tuple(p for p in pre if any(p.startswith(ip) or ip.startswith(p) for ip in inline))
    if judged:
        resolvable.judged_inline_prefixes = judged
    return resolvable


def _make_table(pools: dict, v: dict) -> LootTable:
    """起表：**唯一**差别是词汇声明（resolver 恒为 None —— 见模块 docstring「不装懂」）。"""
    return LootTable(pools, resolver=None,
                     inline_prefixes=v["inline_prefixes"],
                     special_refs=v["special_refs"],
                     pool_key_prefixes=v["pool_key_prefixes"])


def _is_declared_ref(ref, v: dict) -> bool:
    """这条引用是否被包内声明解释过（内联 / 特殊值 / 外部自管 / 前缀→域）。

    「前缀→域」声明的引用算**被解释过**：它由包自己的表判对错（审计会给结论），
    预览不必再补一句「这里要内容侧 resolver」。
    """
    pre = v.get("ref_prefix_keys") or {}
    return (ref in v["special_refs"]
            or ref.startswith(v["inline_prefixes"])
            or any(ref.startswith(p) for p in pre)
            or (bool(v["external_prefixes"]) and ref.startswith(v["external_prefixes"])))


def _fail(msg: str, warnings=None) -> dict:
    return {"ok": False, "error": msg, "warnings": list(warnings or [])}


_CYCLE = "池之间疑似循环引用（子池展开递归不收敛）—— 检查 rolls 的 pool 是否绕回了自己。"


def _safe_expand(table: LootTable, ref):
    """引擎 `expand()` 的守卫：坏数据**报出来**而不是崩。返回 `(展开结果, 硬错, 软警告)`。

    | 情形 | 返回 | 上层处置 |
    |---|---|---|
    | 池互相引用 ⇒ 递归不收敛（`RecursionError`） | 硬错 | `_fail`（预览整体不可信） |
    | 子池 `type` 未注册（`UnknownStrategy`） | **软警告** | 只 `_add(warnings)` |
    | 正常 | `(列表, None, None)` | —— |

    ★ 为什么未知策略是**软**警告而不是硬错：本池自己的 `type` 非法时，上层已经加过一条
      点名警告了；若这里再当硬错，预览就会整个失败 —— 而预览面的口径是
      「坏数据要能看见」，不是「看到坏数据就崩」。
    """
    try:
        return table.expand(ref), None, None
    except RecursionError:
        return [], _CYCLE, None
    except UnknownStrategy as e:
        return [], None, f"子池展开时命中未知策略（运行期会抛）：{e}"


def _add(warnings: list, msg: str) -> None:
    """去重追加（同一个原因不用刷屏）。"""
    if msg not in warnings:
        warnings.append(msg)


def _ratio(w, total):
    """占比（0~1，四位小数）；算不了 → None。"""
    if total is None or total <= 0:
        return None
    return round(float(w) / float(total), 4)


def _pct(w, total):
    r = _ratio(w, total)
    return None if r is None else round(r * 100, 2)


def _n_of(raw):
    """份数原样带回（int 或 [a,b]）——引擎的 `roll_range` 才解释它，预览不改写。"""
    return raw


def build(entry: dict, key: str = "", pools=None, vocab=None) -> dict:
    """把一条池数据算成预览：`{ok, ...}`（纯 JSON，可直接发前端）。

    `vocab` = 包内引用词汇声明（`load_vocab()` 的结果或声明原文；None/空 = 与过去一致）。
    """
    warnings: list = []
    if not isinstance(entry, dict):
        return _fail("数据不是对象（一个池应当是一个 JSON 对象）", warnings)

    v = normalize_vocab(vocab)
    anchor = str(key or _ANCHOR)
    tbl_pools = dict(pools) if isinstance(pools, dict) else {}
    tbl_pools.setdefault(anchor, entry)
    table = _make_table(tbl_pools, v)       # ← 不做引用解析（见模块 docstring）

    ptype = entry.get("type")
    if not isinstance(ptype, str) or not ptype.strip():
        return _fail("缺少 type（策略名）：内置 weighted / fixed / table / table_choice，"
                     "内容侧也能注册自己的策略名", warnings)
    ptype = ptype.strip()

    # ★ 未知策略：**预览面不崩**，渲染成"坏数据"警告（对齐本文件既有口径：
    #   坏数据要报出来，不是 500/异常外泄）。运行期 `roll_pool` 则会抛 `UnknownStrategy`。
    try:
        spec = table.strategy_of(entry)
    except UnknownStrategy:
        _add(warnings, f"策略名 {ptype!r} 不在内置策略表里（内置：{', '.join(sorted(STRATEGIES))}）——"
                       "★ 运行期 `roll_pool` 会抛 `UnknownStrategy`（**不再静默回落 weighted**）。"
                       "本预览按 weighted 展示结构，仅供看形状；要「每项按 chance 独立掷」请改用 `table`。")
        spec = table.strategy_of({**entry, "type": "weighted"})
    uses = spec.get("uses", "entries")
    if v["declared"]:
        _add(warnings, _VOCAB_NOTE.format(path="content/rules/loot_vocab.json"))
    else:
        _add(warnings, _NO_RESOLVER)
    if ptype not in STRATEGIES:
        _add(warnings, f"策略名 {ptype!r} 未注册 —— 内容侧可注册自己的策略；"
                       "未注册时运行期会抛 `UnknownStrategy`，**不再按 weighted 兜底**。")

    rows: list = []
    rolls: list = []

    if uses == "entries":
        raw = entry.get("entries")
        if raw is None:
            raw = []
        if not isinstance(raw, list):
            return _fail("entries 必须是条目数组", warnings)
        for i, e in enumerate(raw):
            if not isinstance(e, dict):
                return _fail(f"entries 第 {i + 1} 项不是对象（每条至少要有 item）", warnings)
            if not str(e.get("item") or "").strip():
                return _fail(f"entries 第 {i + 1} 项缺 item（产出引用）", warnings)
        weights = weigh(raw)                          # ← 引擎同一份权重算法
        total = sum(weights)
        needs_weights = bool(spec.get("needs_weights"))
        if needs_weights and total <= 0:
            return _fail("权重和 ≤ 0：这批条目谁都抽不到（检查 w 字段）", warnings)
        if not raw:
            _add(warnings, "entries 为空：这个池什么都出不来（审计会报「空池」）。")
        if any((e.get("min_lv") is not None or e.get("max_lv") is not None) for e in raw):
            _add(warnings, _LEVEL_WINDOW)
        for e, w in zip(raw, weights):
            w_out = int(w) if needs_weights else None      # fixed：w 不参与抽取 → 不给数（防误导）
            share = _ratio(w, total) if needs_weights else None
            rows.append({
                "ref": str(e.get("item")),
                "w": w_out,
                "n": _n_of(e.get("n")),
                "min_lv": e.get("min_lv"),
                "max_lv": e.get("max_lv"),
                "share": share,                        # 0~1；fixed 型 = None（占比不适用）
                "share_pct": (_pct(w, total) if needs_weights else None),
            })
        if needs_weights:                              # 占比降序（非程序员先看最常见的）
            rows.sort(key=lambda r: (-(r["w"] or 0), r["ref"]))

    elif uses == "rolls":
        raw = entry.get("rolls")
        if raw is None:
            raw = []
        if not isinstance(raw, list):
            return _fail("rolls 必须是数组（每行至少要有 pool）", warnings)
        for i, rc in enumerate(raw):
            if not isinstance(rc, dict):
                return _fail(f"rolls 第 {i + 1} 项不是对象（每行至少要有 pool）", warnings)
            if not str(rc.get("pool") or "").strip():
                return _fail(f"rolls 第 {i + 1} 项缺 pool（子池 key 或内容侧引用）", warnings)
        if not raw:
            _add(warnings, "rolls 为空：这个池什么都出不来（审计会报「空池」）。")
        cutoffs = [rc.get("cutoff") for rc in raw if rc.get("cutoff") is not None]
        if cutoffs:
            acc = sum(float(c or 0) for c in cutoffs)
            if abs(acc - 1.0) > 1e-9:
                _add(warnings, f"cutoff 累计 = {round(acc, 4)}（≠ 1.0）：互斥档按累计选择，"
                               f"末档会兜底吃掉剩余概率（引擎容错，不报错）。")
        for rc in raw:
            sub = str(rc.get("pool")).strip()
            is_sub_pool = table.pool(sub) is not None   # 引擎查表（含前缀剥离规则）
            _se, _sh, _ss = _safe_expand(table, sub) if is_sub_pool else ([], None, None)
            if _ss:
                _add(warnings, _ss)
            sub_expanded = _se
            if _sh:
                return _fail(_sh, warnings)
            if not is_sub_pool:
                if _is_declared_ref(sub, v):
                    _add(warnings, f"rolls 里的 {sub} 是包内声明过的引用（不是本域的池 key）——"
                                   f"「它是什么」由内容侧解析，审计按声明不判它为断链。")
                else:
                    _add(warnings, f"rolls 里的 {sub} 不在本域数据里：子池前缀 / 引用写法由内容侧"
                                   f"注册（inline_prefixes 等），预览不猜 —— 引擎审计对此报「断链」。")
            rolls.append({
                "pool": sub,
                "chance": rc.get("chance"),
                "cutoff": rc.get("cutoff"),
                "n": _n_of(rc.get("n")),
                "fallback": rc.get("fallback"),
                "fallback_n": rc.get("fallback_n"),
                "is_sub_pool": is_sub_pool,
                "expanded_count": len(sub_expanded),
                "expanded_unique": len(set(sub_expanded)),
                "expanded": sub_expanded[:40],          # 子池展开结果（引擎同一份 expand）
            })
    else:
        _add(warnings, f"策略 {ptype!r} 声明 uses={uses!r}：参数表既不是 entries 也不是 rolls，"
                       f"预览只给展开结果（内容侧策略自己解释数据）。")

    expanded, _hard, _soft = _safe_expand(table, anchor)     # ← 引擎同一份展开
    if _soft:
        _add(warnings, _soft)
    if _hard:
        return _fail(_hard, warnings)
    audit_rep = table.audit(resolvable=_make_resolvable(v))   # ← 引擎同一份审计（声明参与判定）
    issues = [{"level": lvl, "pool": pk, "message": msg}
              for (lvl, pk, msg) in audit_rep["issues"] if pk == anchor]

    return {
        "ok": True,
        "key": key or "",
        "type": ptype,
        "strategy_uses": uses,
        "entries": rows,
        "rolls": rolls,
        "expanded_count": len(expanded),
        "expanded_unique": len(set(expanded)),
        "audit": {"ok": not issues, "issues": issues},
        "vocab_declared": v["declared"],
        "warnings": warnings,
    }


def build_file(data: dict, key: str, vocab=None) -> dict:
    """表形态 `{池key: 池对象}` 里取一条算预览（key 不存在 → ok=False + 中文原因）。"""
    if not isinstance(data, dict):
        return _fail("整表不是对象（应当是 {池key: 池对象}）")
    entry = data.get(key)
    if entry is None:
        return _fail(f"没有这条池：{key}")
    return build(entry, key, pools=data, vocab=vocab)


def audit_file(data: dict, vocab=None) -> dict:
    """整表结构审计（域级）：引擎同一份 `LootTable.audit()`，包内声明参与引用判定。

    为什么要有它：单条预览的 `audit` 只答「这一个池有没有结构问题」；「这一批池整体
    有多少断链」需要一次全表审计（596 池逐个 preview 打 596 次请求不是办法）。

    返回（纯 JSON）：
        `{ok, pool_count, entry_count, issue_count, by_kind, issues, vocab_declared}`
    每个 issue = `{level, pool, message}`（level ∈ 断链 / 空池，措辞由引擎给）。
    """
    v = normalize_vocab(vocab)
    pools = dict(data) if isinstance(data, dict) else {}
    rep = _make_table(pools, v).audit(resolvable=_make_resolvable(v))
    issues = [{"level": lvl, "pool": pk, "message": msg} for (lvl, pk, msg) in rep["issues"]]
    by_kind: dict = {}
    for i in issues:
        by_kind[i["level"]] = by_kind.get(i["level"], 0) + 1
    return {
        "ok": rep["ok"],
        "pool_count": rep["pool_count"],
        "entry_count": rep["entry_count"],
        "issue_count": len(issues),
        "by_kind": by_kind,
        "issues": issues,
        "vocab_declared": v["declared"],
    }
