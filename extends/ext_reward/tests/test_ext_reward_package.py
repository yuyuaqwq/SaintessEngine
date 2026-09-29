# -*- coding: utf-8 -*-
"""`ext_reward` 扩展包门禁（B4a：流水采集半边从数据包抽进扩展包）。

钉四件事：

1. **包契约**：`game.json` 的 `id` / `kind` / `entry` 自洽，`install_engine()` 是**显式空实现**
   （纯形状库 —— 不留含糊空壳）。
2. **形状可用 + ★ 回放契约**：`from ext_reward.tlog_collect import BattleTLog, EVENT_KINDS, REPRO_KEYS`；另钉 `_uid()` 的「无 uid 回落 name」—— 那是**回放侧的既有契约**（内容侧 `content/tlog_replay.py` import 它建 `by_uid` 表），防被当死代码删
   三个名字都在，且 `EVENT_KINDS` 非空（映射表骨架）。
3. ★ **可拔插红线**：`BattleTLog(tlog=None)` ⇒ `attach()` 原样返回战斗对象、不挂任何属性、
   `flush()` 不碰 sink（**零行为**）；给了 sink ⇒ `flush()` 真的落到 sink（证明这条红线
   不是「两边都不动」的空断言）。
4. ★ **可换游戏**：本包（含子目录）的 `.py` **零 import 数据包**（`content` / `content.*`）——
   AST 扫描 + 一条反证（合成一段 `from content import x` 的源码 ⇒ 扫描器必须报红）。

跑法：python extends/ext_reward/tests/test_ext_reward_package.py
"""
from __future__ import annotations

import ast
import inspect
import io
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.dirname(HERE)                       # extends/ext_reward
FW_ROOT = os.path.dirname(os.path.dirname(PKG_DIR))   # 引擎仓根
for _p in (HERE, FW_ROOT, os.path.join(FW_ROOT, "extends")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _check import bind_check                          # noqa: E402

PASS = 0
FAILS: list = []
check = bind_check(globals(), "PASS", failures="FAILS")




# ---------------------------------------------------------------- 层级扫描（判据 ④）
def content_imports(src: str) -> list:
    """源码里所有「导入数据包」的模块名（`content` / `content.*`）。"""
    out = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return ["<语法错误>"]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names
                    if a.name == "content" or a.name.startswith("content.")]
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:                                # `from . import …` 相对导入：包内局部的活
                continue
            if mod == "content" or mod.startswith("content."):
                out.append(mod)
    return out


def pack_sources() -> list:
    out = []
    for dp, dn, fn in os.walk(PKG_DIR):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            if f.endswith(".py"):
                out.append(os.path.join(dp, f))
    return sorted(out)


def main() -> int:
    print("=== ext_reward 扩展包门禁（包契约 · 形状可用 · 零行为红线 · 零数据包依赖）===")

    # ------------------------------------------------------------ 1. 包契约
    with open(os.path.join(PKG_DIR, "game.json"), encoding="utf-8") as f:
        man = json.load(f)
    check("game.json id == ext_reward（目录名 = id = 命名空间）", man.get("id") == "ext_reward", man.get("id"))
    check("kind == extension（扩展包）", man.get("kind") == "extension", man.get("kind"))
    check("entry == apply.py（包根入口惯例）", man.get("entry") == "apply.py", man.get("entry"))

    from ext_reward.apply import install_engine
    check("install_engine() 存在（入口模块 = 包根 apply.py）", callable(install_engine), None)
    check("install_engine() 是显式空实现（返回 None，不往引擎塞东西）",
          install_engine() is None, None)

    # ------------------------------------------------------------ 2. 形状可用
    from ext_reward.tlog_collect import BattleTLog, EVENT_KINDS, REPRO_KEYS
    check("BattleTLog / EVENT_KINDS / REPRO_KEYS 三个名字都在",
          bool(BattleTLog) and bool(EVENT_KINDS) and bool(REPRO_KEYS),
          (type(EVENT_KINDS).__name__, type(REPRO_KEYS).__name__))
    check("EVENT_KINDS 是非空映射（映射表骨架在包里、具体键名由数据包给值）",
          isinstance(EVENT_KINDS, dict) and len(EVENT_KINDS) > 0, len(EVENT_KINDS or ()))

    # ------------------------------------------------------------ 2b. ★ 文档零过期导入路径（L1612）
    # 缺陷形态 = **文档指向一个不存在的模块**：数据包照 `apply.py` 头注 / README 的那行
    # `from ext_reward.tlog import …` 抄下来 ⇒ `ModuleNotFoundError`（本包只有
    # `tlog_collect.py` 一个模块，`git ls-files` 证实无 `tlog.py` / `tlog/` 目录）。
    # 而门禁此前**只从正确路径导入**、从不校验文档里写的那行 ⇒ 这条缺陷零阻力地活下来。
    # 判据 = 「本包文档里出现的每一处 `ext_reward.X` 导入路径，X 必须是真实可导入的模块」。
    _doc_bad = []
    _doc_files = ["README.md", "apply.py", "tlog_collect.py"]
    for _df in _doc_files:
        _dp = os.path.join(PKG_DIR, _df)
        if not os.path.exists(_dp):
            continue
        with io.open(_dp, encoding="utf-8") as _f:
            _dtxt = _f.read()
        for _m in re.findall(r"ext_reward\.([A-Za-z_][A-Za-z0-9_]*)", _dtxt):
            # `ext_reward.tlog_collect` 是真模块；日志器名 `ext_reward.tlog_collect` 同名不重复计
            _mod = "ext_reward." + _m
            if not os.path.exists(os.path.join(PKG_DIR, _m + ".py"))                     and not os.path.isdir(os.path.join(PKG_DIR, _m)):
                _doc_bad.append("%s: %s" % (_df, _mod))
    check("★ 入包文档零过期导入路径（README / apply.py / tlog_collect.py 里的 "
          "`ext_reward.X` 逐个可导入）", not _doc_bad, sorted(set(_doc_bad)))
    check("★ 扫描面确实读到了本包文档（3 个文件都在，别让判据空转恒绿）",
          all(os.path.exists(os.path.join(PKG_DIR, _d)) for _d in _doc_files), _doc_files)
    # ★ 有牙：造一处过期路径喂给扫描器，它必须报出来（否则上面那条恒绿）
    _probe_bad = [m for m in ("tlog",) if not os.path.exists(os.path.join(PKG_DIR, "tlog.py"))
                  and not os.path.isdir(os.path.join(PKG_DIR, "tlog"))]
    check("★ 反证：扫描器对不存在的 `ext_reward.tlog` 报红（判据有牙）",
          _probe_bad == ["tlog"], _probe_bad)

    # ★ 构造签名钉死（L1612 的另一半）：旧 README 写 `BattleTLog(battle, tlog, EVENT_KINDS)`
    #   —— 三个位置参数，真实签名只收一个。文档错了没人发现，是因为**门禁从不核对
    #   文档里写的构造签名**。这里钉「真实签名逐字」+「README 那行不得再声称三个位置参数」。
    import inspect as _insp
    #   ★ 比「参数名 + 位置/关键字形态」而不是逐字比 repr：本文件有 `from __future__ import
    #   annotations`，repr 里的注解是**字符串**（`tags: 'Iterable[str]'`），
    #   逐字比会假红；而「谁位置、谁关键字」才是「抄错即 TypeError」的那条契约本身。
    _params = list(_insp.signature(BattleTLog.__init__).parameters.values())
    _shape = [(p.name, p.kind.name) for p in _params]
    check("★ 构造签名钉死：`__init__` 只有 tlog 一个位置参数，tags/name 关键字（抄错即 TypeError）",
          _shape == [("self", "POSITIONAL_OR_KEYWORD"), ("tlog", "POSITIONAL_OR_KEYWORD"),
                     ("tags", "KEYWORD_ONLY"), ("name", "KEYWORD_ONLY")], _shape)
    with io.open(os.path.join(PKG_DIR, "README.md"), encoding="utf-8") as _f:
        _rd = _f.read()
    #   只看**围栏代码块内**的行 —— 说明文字里提「旧写法是错的」是文档该做的事，
    #   把那段也扫进去等于要求文档不许提起自己犯过的错。
    _fenced, _in = [], False
    for _l in _rd.splitlines():
        if _l.lstrip().startswith("```"):
            _in = not _in
            continue
        if _in:
            _fenced.append(_l)
    check("★ README 的可复制代码块里没有 `BattleTLog(battle, tlog, …)` 那种多位置参数写法",
          not [l for l in _fenced if "BattleTLog(battle," in l],
          [l.strip() for l in _fenced if "BattleTLog(battle," in l])
    check("★ README 代码块确实扫到了内容（别让上面那条恒绿）", len(_fenced) >= 8, len(_fenced))

    # ------------------------------------------------------------ 3. 零行为红线
    class _Sink:
        def __init__(self):
            self.emits = []
            self.flushes = 0

        def emit(self, kind, **fields):
            self.emits.append((kind, fields))

        def flush(self):
            self.flushes += 1

    class _Battle:
        """最小战斗替身：只提供 `attach()` 会碰的两处（其余一律 AttributeError）。"""

        def __init__(self):
            self.on_event = lambda *a, **k: None
            self.human_act = lambda *a, **k: None
            self._dispatch_pending = lambda *a, **k: None

    off = _Battle()
    col_off = BattleTLog(None)
    same = col_off.attach(off)
    check("tlog=None ⇒ enabled 为假", col_off.enabled is False, col_off.enabled)
    check("tlog=None ⇒ attach() 原样返回战斗对象（同一对象）", same is off, None)
    check("tlog=None ⇒ 不往战斗对象挂采集器", not hasattr(off, "_battle_tlog"),
          sorted(vars(off)))
    check("tlog=None ⇒ 不包 human_act（包装标记不存在）",
          not getattr(off.human_act, "_battle_tlog_wrapped", False), None)
    # 旧写法是字面态：``check(…, True, None)`` 的第二参数是常量，flush 怎么改都绿。
    # 不能换成运行期断言：``tlog=None`` 时**无 sink 可看**，「门控在」与
    # 「门控不在」两种实现的运行时可观测结果**逐字相同**（已实跑对拍），
    # 且若把门控抹掉、测试先跑 ``flush()`` 就是**崩溃**（AttributeError）而不是可归因的报红。
    # 接口不可观测时，唯一能证明它的形式是**源码结构** —— 故放在 ``flush()`` 之前。
    flush_src = inspect.getsource(BattleTLog.flush)
    check("tlog=None ⇒ flush() 空操作：实现存在 enabled 门控（接口不可观测，只能钉结构）",
          "if self.enabled" in flush_src and "self.tlog.flush()" in flush_src,
          flush_src.strip().splitlines())
    col_off.flush()

    sink = _Sink()
    col_on = BattleTLog(sink)
    ba = _Battle()
    col_on.attach(ba)
    col_on.flush()
    check("给了 sink ⇒ enabled 为真（插拔面真的通）", col_on.enabled is True, col_on.enabled)
    check("给了 sink ⇒ attach() 把采集器挂在战斗对象上", getattr(ba, "_battle_tlog", None) is col_on,
          None)
    check("给了 sink ⇒ flush() 真的落到 sink", sink.flushes == 1, sink.flushes)

    # ------------------------------------------------------------ 4. 可换游戏（零数据包依赖）
    bad = []
    for path in pack_sources():
        with open(path, encoding="utf-8") as f:
            hits = content_imports(f.read())
        if hits:
            bad.append((os.path.relpath(path, PKG_DIR), hits))
    check("本包 .py 里零 import 数据包（content / content.*）—— 换游戏不用改本包",
          not bad, bad)
    check("扫描面覆盖到本包全部 .py（≥3 个：apply / tlog/__init__ / tlog/collect）",
          len(pack_sources()) >= 3, [os.path.relpath(p, PKG_DIR) for p in pack_sources()])

    # 反证：合成一段「import 数据包」的源码 ⇒ 扫描器必须报红（判据有牙）
    proof = content_imports("from content import catalog_items\nimport content.texts\n")
    check("反证：扫描器对 `from content import …` / `import content.*` 报红",
          sorted(proof) == ["content", "content.texts"], proof)
    check("反证：包内相对导入（`from . import x`）不算数据包依赖",
          content_imports("from . import collect\n") == [], None)

    # ------------------------------- 5. 回放契约：_uid 的「无 uid 回落 name」
    # 台账 L1617：`_uid` 全仓仅本文件**定义**，但内容侧 `content/tlog_replay.py:34` 真的
    # import 它（并原样再导出），用它给重建后的战斗单位建 `by_uid` 表，
    # 随后 `by_uid.get(r.fields["uid"])` / `by_uid.get(r.fields["target_uid"])` 两处查表。
    # ⇒ 「拿不到 uid 就回落 name」不是静默兜底，是**回放侧的既有契约**；
    #   但此前**零门禁钉住** —— 下一个人看到「只被自己用」很容易当死代码删掉，
    #   删了之后回放整表查不到人（静默退化成 `b.focus()` 拿错人）或直接 KeyError。
    from ext_reward.tlog_collect import _uid

    # ① 契约本体：uid 在就取 uid；uid 缺（/ 空）回落 name；两个都缺 => 空串。
    check("回放契约：有 uid 取 uid（name 不参与）",
          _uid({"uid": "p1", "name": "史莱姆"}) == "p1",
          _uid({"uid": "p1", "name": "史莱姆"}))
    check("回放契约：无 uid 回落 name（★ 这条就是 L1617 要钉住的那条）",
          _uid({"name": "史莱姆"}) == "史莱姆", _uid({"name": "史莱姆"}))
    check("回放契约：uid 为空串时同样回落 name（空串不算「有 uid」）",
          _uid({"uid": "", "name": "史莱姆"}) == "史莱姆",
          _uid({"uid": "", "name": "史莱姆"}))
    check("回放契约：两者都缺 => 空串（不是 None、也不是抛错）",
          _uid({}) == "", repr(_uid({})))
    check("回放契约：非 dict（None / 列表）=> 空串（引擎侧不配合的可选路径）",
          _uid(None) == "" and _uid([1, 2]) == "",
          (_uid(None), _uid([1, 2])))

    # ② 端到端：复刻内容侧 `tlog_replay.py:97-110` 的建表 + 查表，
    #    证明「两种写法各自建一个键、都能查得到」—— 这是回放能对上人的前提。
    _hero = {"uid": "p1", "name": "勇者"}      # 玩家侧：带 uid
    _foe = {"name": "哥布林"}                    # 敌方替身：只有 name
    _by_uid = {}
    for _side in ([_hero], [_foe]):             # 两侧各一个单位（最小形状）
        for _a in _side:
            _by_uid[_uid(_a)] = _a
    check("回放契约：两种写法各建一个键（by_uid 键集 == {uid, name}）",
          sorted(_by_uid) == ["p1", "哥布林"], sorted(_by_uid))
    check("回放契约：两条流水各自查得到对应单位（回放不靠 b.focus() 瞎猜）",
          _by_uid.get("p1") is _hero and _by_uid.get("哥布林") is _foe,
          (_by_uid.get("p1") is _hero, _by_uid.get("哥布林") is _foe))

    # ③ 形状钉死（防「自己留一份、别处不用」这种绕法）：实现仍住本包。
    check("回放契约：_uid 仍在本包实现里（不是别处搬来的一份）",
          _uid.__module__ == "ext_reward.tlog_collect",
          getattr(_uid, "__module__", None))

    # ④ 反证（判据有牙）：把「无 uid 回落 name」那一半删掉（改回只认 uid）
    #    ⇒ 上面的契约三条必须转红。真跑：把包复制到一次性目录、在**副本**里变异，
    #    子进程带 AFIX4_UID_MUTANT_CHILD=1（防自举）跑副本门禁 ⇒ **真仓零写入**。
    with open(os.path.join(PKG_DIR, "tlog_collect.py"), encoding="utf-8") as f:
        _mod_src = f.read()
    _old_uid = '    return str(a.get("uid") or a.get("name") or "")'
    _new_uid = '    return str(a.get("uid") or "")'
    if os.environ.get("AFIX4_UID_MUTANT_CHILD") == "1":
        # 子进程自证：import 到的 tlog_collect 必须来自**副本**（否则变异不生效 ⇒ 假绿）
        _mod = sys.modules.get("ext_reward.tlog_collect")
        _f = getattr(_mod, "__file__", "") or ""
        check("反证分支：import 的是副本 tlog_collect（变异真生效，非真仓）",
              _f.startswith(os.path.join(os.environ.get("TEMP") or "", "afix4_uid_shadow")),
              _f)
        check("反证分支：副本确实被改掉了（拿不到 name 回落）",
              _uid({"name": "x"}) == "", _uid({"name": "x"}))
    elif _old_uid not in _mod_src:
        check("反证锚点：真仓 _uid 源码逐字含「回落 name」那一半（变异基线对得上）",
              False, repr(_old_uid))
    else:
        import shutil
        # ★ 影子树 = 只复制本包；`saintess_engine` 用**真实**那份（本包唯一的跨包依赖）。
        #   子进程必须**切断继承的 PYTHONPATH**：会话里 `PYTHONPATH` 指着真仓，
        #   不切断的话副本门禁 import 到的仍是真仓 `tlog_collect.py` ⇒ 变异不生效、
        #   rc 恒 0（实测踩过：上一版反证就是这么假绿的）。
        _shadow = os.path.join(os.environ.get("TEMP") or os.environ.get("TMP") or ".",
                             "afix4_uid_shadow")
        _mut = os.path.join(_shadow, "extends", "ext_reward")
        shutil.rmtree(_shadow, ignore_errors=True)
        os.makedirs(os.path.dirname(_mut), exist_ok=True)
        shutil.copytree(PKG_DIR, _mut)
        _mp = os.path.join(_mut, "tlog_collect.py")
        with io.open(_mp, encoding="utf-8", newline="") as f:
            _ms = f.read()
        with io.open(_mp, "w", encoding="utf-8", newline="") as f:
            f.write(_ms.replace(_old_uid, _new_uid, 1))
        #   子进程 PYTHONPATH 顺序 = **影子在前、真仓在后**：
        #     `ext_reward` 命中影子（变异生效）；`saintess_engine` 只在真仓有 → 回落到真仓
        #     （本包唯一的跨包依赖）。切掉真仓会让子进程 ModuleNotFoundError，
        #     那样 rc≠0 是**巧合报错**而不是契约被咬住 —— 故真仓必须留在末尾。
        _child_env = dict(os.environ, AFIX4_UID_MUTANT_CHILD="1",
                         PYTHONPATH=os.pathsep.join([_shadow,
                                                     os.path.join(_shadow, "extends"),
                                                     FW_ROOT]),
                         GWEN_FRAMEWORK_DIR=FW_ROOT)
        _rc = subprocess.run(
            [sys.executable, os.path.join(_mut, "tests", "test_ext_reward_package.py")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=_child_env, cwd=FW_ROOT)
        _out = (_rc.stdout or "") + (_rc.stderr or "")
        # ★ 判「真的报红」看 **❌ 行**而不是「文本里出现过这句话」——
        #   子进程 rc=0 时它的 ✅ 行里同样含这句，照旧写法就是一条**恒绿废判据**。
        _red = [l for l in _out.splitlines() if l.strip().startswith("❌")]
        check("反证：副本里删掉「回落 name」那一半 ⇒ 子进程必须 rc!=0（有牙）",
              _rc.returncode != 0, "rc=%d %s" % (_rc.returncode, _out.strip().splitlines()[-3:]))
        check("反证：报红的正是「无 uid 回落 name」那条契约（不是别的巧合报错）",
              any("无 uid 回落 name" in l for l in _red), _red[-4:])
        shutil.rmtree(_shadow, ignore_errors=True)

    print("\n通过 %d / 失败 %d" % (PASS, len(FAILS)))
    if FAILS:
        for line in FAILS:
            print("❌ %s" % line)
        return 1
    print("✅ ext_reward 包门禁全绿")
    return 0


if __name__ == "__main__":
    sys.exit(main())
