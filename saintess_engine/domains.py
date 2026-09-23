# -*- coding: utf-8 -*-
"""引擎默认域集 + **唯一一份**「包声明 ∪ 引擎默认集」合并规则。

为什么它在引擎层
----------------
引擎自己的装载口（`records.read_domain_decl` / `resolve_domain` / `set_from_domains`）
必须与编辑器看到**同一份**有效域表。否则「域的声明搬到引擎（上移成引擎内置）」之后，
编辑器还能编，装载口却读不到（2026-09-20 T1 双向迁移演习实测：搬迁后 `records_from_domain`
报 `RecordsDeclarationError`）。合并规则因此只有这一份 ——
`editor/packages.py::effective_domains()` 只**委托**它，装载口用**同一份**结果兜底。
设计 + 干跑证据：`overnight/T1_DUAL_MIGRATION_DRILL.md` §六。

零游戏词汇
----------
下面 3 个域都是**引擎侧真有消费端代码**的形状（每个域在 `saintess_engine/` 里都能指到
消费它的模块，逐条见下）；某个具体游戏的内容域（技能 / 职业 / 怪物 / 词条 / 物品 …）
**一个都不在这里** —— 那只能由内容包自己声明。

★ 判据就一条：**域跟消费端走**。2026-09-23 包栈重构把游戏级形状搬进 `extends/` 扩展包后，
  原来挂在这里的 `effect_rules` / `passive_proc` / `maps` / `instances` / `drop_pools`
  的消费端（battle / space / run / loot）已经不在引擎里 ⇒ 这 5 个域也搬到扩展包
  （`extends/<包>/domains.json`）。引擎默认集只剩「通用件自己的 3 个表」。

字段（与包声明同形）
--------------------
    label    展示名（编辑器用）
    kind     `"data"`（内容数据表）| `"rules"`（声明表）；落点子目录由调用方映射
    schema   schema 文件名（**不是**路径；由调用方的 `schema_path()` 解析）
    primary  schema `$defs` 里「一条数据」的 def 名
    icon     展示图标
    owner / tier  可选的归属标注（`owner` = 形状/模块归属，`tier` = 可迁移等级）；
                  **只由包侧声明** —— 引擎默认集里不写（保证「包声明 == 生效域表」逐字段可比）

★ 这份常量是**回退默认集，不是真源**：域的真源永远是内容包自己的
  `<pkg>/editor/domains.json`。包声明了同名域 → 这份里的那一域不再参与取值。
"""
import io
import json
import os


BUILTIN_DEFAULT_DOMAINS = {
    # ── ① commands「指令」：引擎通用命令注册表。消费端 `command/registry.py:164`
    #    class CommandRegistry（`:206` from_data 直接吃这张表）；配套泛用件 `command/router.py`
    #    / `command/guards.py` / `command/text.py`。不填 = 无指令（零行为）。
    "commands": {"label": "指令", "kind": "data", "schema": "command.schema.json",
                 "primary": "command", "icon": "⌨️"},
    # ── ② texts「文案」：引擎通用文案表。消费端 `text/template.py:129` class TextTable
    #    （`:176` from_data）+ `safe_format` / `extract_params`（同文件）。不填 = 零行为。
    "texts": {"label": "文案", "kind": "data", "schema": "text.schema.json",
              "primary": "text_entry", "icon": "💬"},
    # ── ③ tlogs「流水声明」：引擎结构化流水。「哪个 kind 有哪些字段」的声明表。
    #    消费端 `tlog/record.py:115` class KindTable（`tlog/core.py:34` 再导出、
    #    `:47`/`:53` 由 TLog(kinds=KindTable) 吃）。不填 = 不做校验（零行为）。
    "tlogs": {"label": "流水声明", "kind": "data", "schema": "tlog.schema.json",
              "primary": "tlog_entry", "icon": "🧾"},
    # 注：以下 5 个原来也在这里，**2026-09-23 起随消费端搬进扩展包**（消费端代码搬哪儿，
    #     域就跟到哪儿 —— 这就是「域属不属于引擎」的判据）：
    #       effect_rules → extends/ext_combat/domains.json（消费端 battle/state_effects · effects · landing）
    #       passive_proc → extends/ext_combat/domains.json（消费端 battle/effect_triggers · effects）
    #       maps         → extends/ext_world/domains.json （消费端 space/graph.py）
    #       instances    → extends/ext_world/domains.json （消费端 run/progress.py）
    #       drop_pools   → extends/ext_loot/domains.json  （消费端 loot/pool.py）
    #     数据包要它们：在 `game.json` 的 `depends` 里装上对应扩展包即出现在有效域表里。
    # 注：以下 11 个是**内容域**（曾内置，2026-09-13 B2b 移出）—— 引擎侧指不到消费端，
    #     取值/结构都是某个具体游戏的词汇；现在只能由内容包声明（orlandia 在
    #     `games/orlandia/editor/domains.json` 里声明它们，schema 随包走）：
    #     skills · classes · monsters · affixes · items · loot_vocab · equip_roster ·
    #     pois · legendary_effects · pets · monster_roster
}


def ext_domain_decls(pkg_root: str = "", *, depends: list | None = None) -> list:
    """该包 `depends` 的扩展包带来的**域声明**（按声明序，浅 → 深）。

    域跟消费端走（2026-09-23 包栈重构）：`instances` 的消费端在 `run/`（已搬进 `ext_world`），
    所以「装了 ext_world 的包，编辑器与装载口就认得 instances 域」。

    只读扩展包的 `domains.json`（纯数据）—— **不加载扩展包代码、不跑依赖拓扑**；
    目录发现复用包栈那套约定搜索路径（`package.default_ext_dirs`）。读不到就跳过（不抛）。
    """
    out = []
    if not pkg_root:
        return out
    try:
        import json as _json
        from .package import default_ext_dirs
        mf = os.path.join(pkg_root, "game.json")
        if not os.path.isfile(mf):
            return out
        with io.open(mf, encoding="utf-8") as f:
            manifest = _json.load(f)
        # `depends` 显式给了就用它 —— 编辑器「能力开关」要**试算另一组 depends**
        # 会得到什么域表（关掉某扩展包前先看清代价），而试算**必须共用这一份口径**，
        # 不能另写一个拼装器（两边口径漂 = 2026-09-20 踩过的坑）。
        deps = ([str(x) for x in depends] if depends is not None
                else [str(x) for x in ((manifest or {}).get("depends") or [])])
        if not deps:
            return out
        found: dict = {}
        for base in default_ext_dirs(pkg_root):
            try:
                names = sorted(os.listdir(base))
            except OSError:
                continue
            for name in names:
                d = os.path.join(base, name)
                if os.path.isdir(d) and name not in found:
                    found[name] = d
        for dep in deps:
            root = found.get(dep)
            if not root:
                continue
            fp = os.path.join(root, "domains.json")
            if not os.path.isfile(fp):
                continue
            with io.open(fp, encoding="utf-8") as f:
                raw = _json.load(f)
            if isinstance(raw, dict):
                out.append(raw)
    except Exception:                                              # noqa: BLE001
        return out
    return out


def layered_decls(pkg_root: str = "", pkg_decls: dict | None = None, *,
                  use_builtin: bool = True, builtin: dict | None = None,
                  depends: list | None = None) -> dict:
    """**唯一一份**分层合并 —— 编辑器与装载口都走它（别再各写一套）。

        ① 引擎默认集（通用件自己的表）
        ② 该包 `depends` 的扩展包声明（域跟消费端走）
        ③ 该包自己的声明（整体覆盖前层）

    `use_builtin=False`（包声明里写 `\"$builtin\": false`）**只关掉 ①**：
    它说的是「不要引擎默认集兜底」，与「我依赖的扩展包带来的域」无关 —— 后者照旧生效。
    """
    base = BUILTIN_DEFAULT_DOMAINS if builtin is None else builtin
    out = merge_decls({}, builtin=base, use_builtin=use_builtin)
    for d in ext_domain_decls(pkg_root, depends=depends):
        out = merge_decls(d, builtin=out)
    if pkg_decls:
        out = merge_decls(pkg_decls, builtin=out)
    return out


def builtin_default_domains() -> dict:
    """引擎默认集（回退用）**副本** —— 别改它：要加域/改域请改内容包自己的声明表。"""
    return {k: dict(v) for k, v in BUILTIN_DEFAULT_DOMAINS.items()}


def merge_decls(decls, *, builtin=None, use_builtin: bool = True) -> dict:
    """「包声明 ∪ 引擎默认集」的**唯一一份**合并规则 → 有效域表。

    * `use_builtin=False` ⇒ 只用 `decls`（对应包声明里写的 `"$builtin": false`）。
    * 同名域**整体以 `decls` 为准**（不做字段级补缺 —— 逐字段补缺是编辑器
      `_read_package_domains()` 的活：它要在**读声明时**就能报「哪个字段写坏了」）。
    * 顺序 = 引擎默认集序 + 包新增域（追加在末尾）⇒ 编辑器 tab 位置不跳。
    * `builtin` 是注入点（缺省 = 本模块那份）：编辑器把它传成**自己模块里的那个名字**，
      好让「把内置默认集整体置空」的反证门禁照旧生效。

    只做合并与拷贝，**不校验、不产 warning**（校验口径与告警文案归各自的调用方）。
    """
    base = BUILTIN_DEFAULT_DOMAINS if builtin is None else builtin
    out: dict = {}
    if use_builtin:
        for did, meta in base.items():
            out[did] = dict(meta) if isinstance(meta, dict) else meta
    for did, meta in (decls or {}).items():
        out[did] = dict(meta) if isinstance(meta, dict) else meta
    return out


def decl_switch(raw) -> tuple:
    """拆一份**包域声明** → `(声明表, 用不用引擎默认集)`。

    容忍两种写法（与编辑器 `_read_package_domains()` 同一口径）：

        {"域": {...}, "$builtin": false}
        {"domains": {"域": {...}}, "$builtin": false}      # 包装层同样认

    开关名 `$builtin` / `$builtin_defaults`（顶层与包装层都认；非布尔 ⇒ 按 `True`，
    编辑器侧对非布尔另发一条 warning —— 这里只认口径，不产告警）。
    开关键**从结果里剥掉**（它不是域，不许漏进域表）。
    """
    if not isinstance(raw, dict):
        return {}, True
    raw = dict(raw)                                    # 纯函数：不改入参
    holds = [raw]
    inner = raw.get("domains")
    if isinstance(inner, dict):
        inner = dict(inner)
        raw["domains"] = inner
        holds.append(inner)
    use_builtin = True
    for holder in holds:
        for opt in ("$builtin", "$builtin_defaults"):
            if opt in holder:
                v = holder.pop(opt)
                if isinstance(v, bool):
                    use_builtin = v
    return (inner if inner is not None else raw), use_builtin
