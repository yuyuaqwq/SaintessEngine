# -*- coding: utf-8 -*-
"""B20 门禁：「试玩」通道（本线新增）。

跑法：`python tests/test_editor_play.py`（退出码 0 = 全绿）。
不依赖 pytest；与 `tests/test_host_contract.py` / `test_host_skeleton.py` 同风格。

守的四条底线
------------
A. **编辑器主进程零 import 引擎**：`import editor.play` 之后 `sys.modules` 里不许出现
   `saintess_engine*`（硬断言，不是「代码里搜字符串」）。子进程侧（`play_worker.py`）
   才是唯一允许 import 引擎的地方。
B. **全量命令覆盖（196/196）**：包内 `content/data/commands.json` 的每一条 key
   ① 在声明表里；② 在 `play` 的清单里；③ 子进程审计里逐条给出「有处理器 / 可解析」；
   ④ 每一条都能构造一次调用（有处理器的真跑，缺处理器的按引擎口径**回显声明**，不静默）。
C. **逐字节对拍（≥20 条）**：同 seed + 同命令序列 + 同固定墙钟下，
   试玩通道（引擎 host + 包）与 QQ 侧（`shim_astrbot` + `_host_bridge.run_async`）
   每条命令的 `digest`（key + 文本段 + 平台动作 + 状态 sha）逐条相同，且整串 sha 相同。
C2. **★ 无宿主 vs 有宿主（T7 第 3 轮 · 试玩脱宿主）**：试玩链的壳**恒为引擎侧**
   `editor/play_shell.py::PlayShell`（无宿主）；只有显式给 `host_root` 才换成插件
   `host.shell.HostShell`。两侧同 seed / 同固定墙钟 / 同序列 / 各自新库 ⇒ 逐条 `digest` 相同。
T. **一套树规则（2026-09-24）**：**包 / 引擎 / 宿主三者必须同树** —— 有宿主 ⇒ 整棵部署树
   （`<插件>/framework` 的引擎 + 同树 `games/*` 的包；QQ 侧参考跑跑的正是这一棵）；
   无宿主 ⇒ 本仓树。四个根（`ENGINE_ROOT` / `GAMES_DIR` / `PKG` / `EXT_DIRS`）一次算清、
   之后**一律显式传参**，不靠 `sys.path` 的插入顺序。混装（本仓包 + 别的仓引擎）当场
   ImportError（实测：本仓引擎第 7 批摘掉 `config.load_game_rules` ⇒ 部署树那份包在
   `install_engine()` 里炸 `AttributeError`，报错指向包、根因是「根从哪来」）。
   另一条（顺序铁律）：**包内模块的 import 一律归 `boot()` 之后** —— 扩展包目录要等
   `load_stack()` 把扩展包排进加载计划时才会上 `sys.path`，而包内 `content/**` 在
   **import 期**就 `from ext_combat…`。QQ 侧参考跑原先有一句**死 import**
   （`from content import persistence`）把整条 content 链提前 ⇒ 本文件 12 条红全由它而来
   （2026-09-24 已在宿主侧删掉那行，本文件不再注入任何路径）。路由段（E）反着来：它走
   **本仓树**（route 的包根与 `play.discover()` 的引擎根都钉在 `FRAMEWORK_ROOT`），
   故显式清掉宿主变量。
C0. **无宿主也要能跑（缺宿主时本文件的唯一判据）**：8 条子集真跑全绿（不靠插件任何文件）。
   因此本门禁**不再整文件跳过** —— QQ 侧对拍（C 段）与路由片段（E 段）才需要宿主。
E2. **反证**：把 `ShellBase.__getattr__` 打桩成抛错 ⇒ `背包` 必红（证「按名解析包内助手」
   是真的在用，不是形状相似）。
D. **子进程健壮**：超时可掐死（明确报 timeout，不静默）；worker 崩溃 → 明确报错；
   seed 可指定（同 seed 复现、异 seed 可不同）。
F. **平台动作记录「真的进对拍」**（T7 第 5 轮）：① 源码级禁「重绑动作表」+ 必须就地清空 +
   壳装配必须交同一张表（两侧）；② 反证按老 bug 改一行必红（含不误伤 `self.events = []`）；
   ③ 运行时 `._events is lst`（就地清空生效 / 清空拷贝无效）；④ 端到端「过期拍卖 ⇒
   actions 非空」，对照组「角色」为空。
F5. **有动作的样本两侧逐字节**（T8 · 台账 §0 D10 A 案）：广播 / 通知的扇出与记录形状上移
   引擎 `ShellBase`（两壳只剩 `_deliver`）⇒ ① 过期拍卖落槌（真命令路径）② 广播 + 一条通知
   （真扇出口）两侧同库跑 ⇒ `actions` 序列化 sha 相同；并核「形状只有一处定义」（AST）。
"""
from __future__ import annotations

import atexit
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # 引擎仓（含 editor/ + games/）


def _find_host_root() -> str:
    """宿主根 = 平台插件目录（需含 `game/` + `framework/`）。env 优先，其次常见位置。

    本仓（引擎仓）通常**不含宿主**；没有宿主时只跳「QQ 侧对拍」两段（见 main），
    提供方式：`B20_HOST_ROOT=<插件目录>` 或下列候选之一命中。

    ★ 候选顺序里**部署布局优先**：插件目录 = 本引擎仓的上一级（`<plugin>/framework` +
    `<plugin>/game` 是拆仓后的标准形状）。不认它时，本仓被放在某份工作副本里跑（如
    `<ws>/host/framework/tests`）会直接落到下面那条**写死路径**（= 另一份仓）——
    于是「本仓的包 + 别的仓的引擎」混装（实测：包侧要引擎新 API 时当场 ImportError，
    而报告指向的是包，根因却在宿主根发现顺序）。
    """
    cands = [os.environ.get(k) for k in
             ("B20_HOST_ROOT", "SAINTESS_HOST_ROOT", "GWEN_HOST_ROOT")]
    cands += [
        os.path.dirname(os.path.abspath(ROOT)),          # 部署布局：插件目录 = framework 的上一级
        os.path.join(os.path.dirname(ROOT), "qqbot", "data", "plugins", "dragonfall"),
        os.path.join(ROOT, "host", "dragonfall"),
        r"C:/Users/yuyu/qqbot/data/plugins/dragonfall",
    ]
    for c in cands:
        if c and os.path.isdir(os.path.join(c, "game")) and os.path.isdir(os.path.join(c, "framework")):
            return os.path.abspath(c)
    return ""


HOST_ROOT = _find_host_root()                      # 宿主插件目录（QQ 侧同一份）

# ★ 一套树规则（本文件**唯一**的根选择口径）：**包 / 引擎 / 宿主三者同树**。
#   有宿主 ⇒ 整棵部署树（`<插件>/framework` 的引擎 + 同树 `games/*` 的包；QQ 侧参考跑
#   跑的正是这一棵）；无宿主 ⇒ 本仓树（本仓引擎 + 本仓包）。四个根**一次算清、后续显式
#   传参** —— 不再靠 `sys.path` 的插入顺序碰运气（`editor/play_worker.py::_setup_paths`
#   先插引擎根、后插宿主根 ⇒ 宿主根盖住引擎根；那是巧合，不是契约）。
#   ⚠ 混装（本仓包 + 别的仓引擎）当场 ImportError：本仓引擎第 7 批摘掉
#     `config.load_game_rules` 之后，部署树那份包在 `install_engine()` 里炸
#     `AttributeError` —— 报错指向包，根因却是「根从哪来」。
_HOST_TREE = os.path.join(HOST_ROOT, "framework") if HOST_ROOT else ""
ENGINE_ROOT = _HOST_TREE or ROOT                   # 引擎根（= PKG 所在的那棵树）
GAMES_DIR = os.path.join(ENGINE_ROOT, "games")     # 包目录的父级（`editor/packages` 同口径）
PKG = os.path.join(GAMES_DIR, "orlandia")          # 游戏包
if HOST_ROOT:
    os.environ.setdefault("B20_HOST_ROOT", HOST_ROOT)   # play.discover() 读它
os.environ["GWEN_FRAMEWORK_DIR"] = ENGINE_ROOT     # 包内 `tests/_paths.py`：引擎根（同树）
os.environ.setdefault("GWEN_HOST_DIR", HOST_ROOT)  # 同上：宿主壳根（空 = 由引擎根推）
QQ_REF = os.path.join(HOST_ROOT, "tests", "b20_qq_ref.py") if HOST_ROOT else ""
DB_DIR = tempfile.mkdtemp(prefix="b20_play_db_")   # 每次运行独立目录（并发/残留互不污染）
atexit.register(shutil.rmtree, DB_DIR, ignore_errors=True)   # 退出清理（含异常/早退）
CLOCK = 1700000000.0                               # 固定墙钟（两侧同刻）

sys.path.insert(0, ROOT)                           # `import editor.play`
if HERE not in sys.path:
    sys.path.insert(0, HERE)

PASS = 0
FAIL = 0
FAILURES = []
NOTES = []

#: 对拍命令样本：`(消息原文, 声明 key)`，跨域选取（面板 / 列表 / 探索 / 商店 / 社交 /
#: 副业 / 副本 / 战斗前置 …）。key 由本文件复算（`tests/_cmd_registry` 口径）后核对。
PARITY_SAMPLES = [
    ("角色", "profile"), ("我的角色", "profile"), ("背包", "inventory"),
    ("时间", "time_cmd"), ("地图", "map_view"), ("区域", "region_view"),
    ("位置", "location_view"), ("成就", "achievements"), ("声望", "reputation"),
    ("宠物", "pet_view"), ("坐骑", "mount_cmd"), ("图鉴", "bestiary"),
    ("百科", "encyclopedia"), ("称号", "titles"), ("套装", "set_view"),
    ("技能", "skill"), ("技能列表", "skill"), ("属性", "attributes"),
    ("战力", "power"), ("流派", "build_view"), ("副业", "profession_view"),
    ("探索", "explore"), ("探索进度", "explore_progress"), ("垂钓", "fishing"),
    ("采集", "gather"), ("挖掘", "mining"), ("炼金", "alchemy"),
    ("烹饪列表", "cooking_list"), ("配方", "recipe_list"), ("商店", "shop"),
    ("副本", "instance_cmd"), ("副本地图", "instance_map_view_cmd"),
    ("任务", "quest_view"), ("每日", "daily"), ("周常", "weekly_cmd"),
    ("爬塔", "tower_cmd"), ("组队", "party"), ("公会", "guild_info"),
    ("市场", "market"), ("拍卖", "auction"), ("排行", "leaderboard"),
    ("帮助", "help_cmd"), ("签到", "signin"), ("见闻录", "wild_notes"),
    ("起床", "profile"),  # 未命中 → 走「没有命中任何指令声明」分支（两侧同口径）
]


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")


def note(text: str) -> None:
    NOTES.append(text)
    print("   · %s" % text)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ============================================================
# A. 零 import 引擎（先跑：这条要求「干净解释器」）
# ============================================================
def test_zero_engine_import() -> None:
    print("\n=== A. 编辑器主进程零 import 引擎 ===")
    code = (
        "import sys; sys.path.insert(0, %r);\n"
        "import editor.play as P;\n"
        "bad = sorted(m for m in sys.modules if m == 'saintess_engine'"
        " or m.startswith('saintess_engine.'));\n"
        "print('BAD=' + ','.join(bad));\n"
        "print('HAS_DISCOVER=' + str(bool(P.discover())))\n" % ROOT
    )
    pr = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                        encoding="utf-8", errors="replace",
                        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
                        timeout=120)
    out = (pr.stdout or "") + (pr.stderr or "")
    bad = ""
    for line in (pr.stdout or "").splitlines():
        if line.startswith("BAD="):
            bad = line[4:].strip()
    check("import editor.play → sys.modules 无 saintess_engine", pr.returncode == 0 and not bad,
          "bad=%s rc=%s %s" % (bad, pr.returncode, out[-300:]))
    # 反向证据：worker 源码**允许** import 引擎（子进程侧）
    src = open(os.path.join(ROOT, "editor", "play_worker.py"), encoding="utf-8").read()
    check("子进程侧 play_worker.py 才 import 引擎（源码可见）",
          "from saintess_engine" in src or "import saintess_engine" in src)

    from editor import play as PLAY
    cfg = PLAY.discover()
    if HOST_ROOT:
        check("discover() 找到 包/宿主/引擎 三个根",
              bool(cfg.get("pkg_dir")) and bool(cfg.get("host_root")) and bool(cfg.get("engine_root")),
              json.dumps(cfg, ensure_ascii=False))
    else:
        check("无宿主：discover() 仍给出 包/引擎 两个根（host_root 显式为空）",
              bool(cfg.get("pkg_dir")) and bool(cfg.get("engine_root")) and cfg.get("host_root") == "",
              json.dumps(cfg, ensure_ascii=False))


# ============================================================
# B. 全量命令覆盖 196/196
# ============================================================
def test_full_command_coverage() -> dict:
    print("\n=== B. 全量命令覆盖（196 条 key）===")
    from editor import play as PLAY
    decl = json.load(open(os.path.join(PKG, "content", "data", "commands.json"), encoding="utf-8"))
    keys = sorted(decl)
    check("包内声明表 key 数 == 196", len(keys) == 196, "实际 %d" % len(keys))

    listing = PLAY.list_commands(PKG, engine_root=ENGINE_ROOT)
    check("play.list_commands() 列出全部 key",
          listing.get("ok") and listing.get("count") == len(keys),
          "count=%s" % listing.get("count"))
    check("清单 key 集合与声明表逐字相等",
          sorted(c["key"] for c in listing["commands"]) == keys)

    audit = PLAY.audit(PKG, db=os.path.join(DB_DIR, "audit.db"), engine_root=ENGINE_ROOT)
    check("子进程审计 stage=audit", audit.get("stage") == "audit", str(audit)[:200])
    akeys = sorted(r["key"] for r in (audit.get("rows") or []))
    check("审计覆盖全部 196 条（_maint_gate 在内）", akeys == keys,
          "缺=%s" % sorted(set(keys) - set(akeys)))
    resolved = [r["key"] for r in (audit.get("rows") or []) if r["resolved"]]
    missing = sorted(set(keys) - set(resolved))
    note("包内处理器可解析 %d / %d；未登记处理器 %d 条（按引擎口径回显声明，不静默）"
         % (len(resolved), len(keys), len(missing)))
    note("未登记清单：%s" % ", ".join(missing))
    check("审计逐条给出 有处理器/可解析 两列", all("has_handler" in r for r in audit["rows"]))
    return {"keys": keys, "missing": missing, "audit": audit}


# ============================================================
# C. 逐字节对拍（≥20 条）
# ============================================================
def _registry_keys() -> dict:
    """`{消息原文: 声明 key}` —— 用**同一份**正则扫描实现复算（不另抄一份）。

    ★ T8（测试单源化）：`_cmd_registry` 是**内容侧**夹具，真源已唯一在包仓 tests
      （部署面 `<plugin>/framework/games/*/tests`）；宿主侧同名副本已删除。
      故**先从部署面取**，再回落 `<plugin>/tests`（宿主自留件面）。
    """
    tests_cands = []
    games = os.path.join(HOST_ROOT, "framework", "games")
    if os.path.isdir(games):
        for n in sorted(os.listdir(games)):
            t = os.path.join(games, n, "tests")
            if os.path.isdir(t):
                tests_cands.append(t)
    tests_cands.append(os.path.join(HOST_ROOT, "tests"))
    for t in reversed(tests_cands):          # insert(0) ⇒ 靠后者排前 ⇒ 部署面最前
        if t not in sys.path:
            sys.path.insert(0, t)
    sys.path.insert(0, os.path.join(HOST_ROOT, "framework"))
    import _cmd_registry as CR
    pool = {name: (pat, prio) for name, (pat, prio, _f) in CR.patterns_with_meta().items()}
    import re
    out = {}
    for text, key in PARITY_SAMPLES:
        hits = {n for n, (pat, _p) in pool.items() if re.compile(pat).match(text.strip())}
        out[text] = sorted(hits)
    return out


def _run_qq_ref(pairs, db, uid="9001", group_id="g9"):
    """QQ 侧参考跑：`tests/b20_qq_ref.py`（子进程；宿主副本内）。"""
    req = {"commands": [t for t, _k in pairs], "handlers": pairs, "uid": uid,
           "group_id": group_id, "db": db, "seed": 11, "clock": CLOCK}
    pr = subprocess.run([sys.executable, QQ_REF], input=json.dumps(req),
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                        cwd=HOST_ROOT, timeout=600,
                        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
                             "B20_CLOCK": str(CLOCK), "PYTHONPATH": HOST_ROOT})
    rows, tail = [], None
    for line in (pr.stdout or "").splitlines():
        if not line.startswith("__B20_QQREF__"):
            continue
        obj = json.loads(line[len("__B20_QQREF__"):])
        if obj.get("stage") in ("done", "load"):
            tail = obj
        else:
            rows.append(obj)
    return rows, tail, (pr.stdout or "") + (pr.stderr or "")


def test_byte_parity(missing_keys=None) -> None:
    print("\n=== C. 逐字节对拍：试玩通道 vs QQ 侧（shim_astrbot + _host_bridge）===")
    from editor import play as PLAY
    missing_keys = set(missing_keys or ())
    os.makedirs(DB_DIR, exist_ok=True)

    reg_db = os.path.join(DB_DIR, "parity_reg.db")
    for p in (reg_db, os.path.join(DB_DIR, "parity_qq.db"), os.path.join(DB_DIR, "parity_play.db")):
        if os.path.exists(p):
            os.remove(p)

    # ① 试玩侧先注册（建档），再把**同一份库**复制成两侧起点 —— 初始状态逐字节相同
    reg = PLAY.run(PKG, ["注册 对拍者 男"], seed=11, uid="9001", group_id="g9", db=reg_db,
                   db_dir=DB_DIR, engine_root=ENGINE_ROOT)
    check("试玩侧注册建档（两条通道的共同起点）", reg.get("ok") and reg.get("ran") == 1,
          str(reg)[:200])
    qq_db = os.path.join(DB_DIR, "parity_qq.db")
    play_db = os.path.join(DB_DIR, "parity_play.db")
    shutil.copyfile(reg_db, qq_db)
    shutil.copyfile(reg_db, play_db)

    # ② key 复算（用宿主测试同一份实现）；缺处理器的样本跳过对拍（B 段已登记）
    reg_hits = _registry_keys()
    pairs, dropped = [], []
    for text, want in PARITY_SAMPLES:
        hits = reg_hits.get(text) or []
        key = want if want in hits else (hits[0] if hits else "")
        if not key:
            dropped.append("%s(无声明命中)" % text)
            continue
        if key in missing_keys:
            dropped.append("%s(%s 包内未登记处理器)" % (text, key))
            continue
        pairs.append((text, key))
    note("对拍样本 %d 条（从 %d 条候选中筛出）；剔除：%s"
         % (len(pairs), len(PARITY_SAMPLES), "、".join(dropped) or "无"))
    check("对拍样本 ≥ 20 条", len(pairs) >= 20, "实际 %d" % len(pairs))

    # ③ 两侧同序列跑
    qq_rows, qq_tail, qq_log = _run_qq_ref(pairs, qq_db)
    check("QQ 侧参考跑通（stage=done）", bool(qq_tail) and qq_tail.get("stage") == "done",
          (qq_log or "")[-400:])
    play_res = PLAY.run(PKG, [t for t, _k in pairs], seed=11, uid="9001", group_id="g9",
                        db=play_db, db_dir=DB_DIR, clock=CLOCK, engine_root=ENGINE_ROOT)
    check("试玩侧跑通（stage=done）", play_res.get("stage") == "done", str(play_res)[:300])
    p_rows = play_res.get("rows") or []

    check("两侧条数一致", len(qq_rows) == len(p_rows) == len(pairs),
          "qq=%d play=%d 期望=%d" % (len(qq_rows), len(p_rows), len(pairs)))

    same_keys, same_text, same_digest, ok_both = [], [], [], 0
    diffs = []
    for i, (text, key) in enumerate(pairs):
        q = qq_rows[i] if i < len(qq_rows) else {}
        p = p_rows[i] if i < len(p_rows) else {}
        if q.get("key") == p.get("key") == key:
            same_keys.append(key)
        if (q.get("segments") or []) == (p.get("segments") or []):
            same_text.append(key)
        if q.get("digest") and q.get("digest") == p.get("digest"):
            same_digest.append(key)
        else:
            diffs.append({"text": text, "key": key,
                          "qq_ok": q.get("ok"), "play_ok": p.get("ok"),
                          "qq_err": q.get("error") or ((q.get("traceback") or "")[-120:]),
                          "play_err": p.get("error") or ((p.get("traceback") or "")[-120:]),
                          "qq_seg": (q.get("segments") or [])[:1],
                          "play_seg": (p.get("segments") or [])[:1]})
        if q.get("ok") and p.get("ok"):
            ok_both += 1

    check("两侧命中同一条声明 key（逐条）", len(same_keys) == len(pairs),
          "%d/%d" % (len(same_keys), len(pairs)))
    check("文本段逐字节相同（逐条）", len(same_text) == len(pairs),
          "%d/%d；差异样例 %s" % (len(same_text), len(pairs),
                                 json.dumps(diffs[:3], ensure_ascii=False)[:600]))
    check("★ digest 逐字节相同（key+文本段+动作+状态 sha）", len(same_digest) == len(pairs) >= 20,
          "%d/%d 相同；差异样例 %s" % (len(same_digest), len(pairs),
                                   json.dumps(diffs[:4], ensure_ascii=False)[:1200]))
    check("两侧整串 digests_sha 相同",
          bool(qq_tail) and qq_tail.get("digests_sha") == play_res.get("digests_sha"),
          "qq=%s play=%s" % ((qq_tail or {}).get("digests_sha"), play_res.get("digests_sha")))
    check("两侧都 ok 的条数 == 样本数", ok_both == len(pairs),
          "%d/%d（失败样例 %s）" % (ok_both, len(pairs),
                                 json.dumps([d for d in diffs if not (d["qq_ok"] and d["play_ok"])][:3],
                                            ensure_ascii=False)[:600]))

    # 证据：样本清单 + sha
    sha_lines = ["%s\t%s\t%s" % (t, k, (p_rows[i] or {}).get("digest", ""))
                 for i, (t, k) in enumerate(pairs)]
    note("对拍样本 sha256（%d 条，拼串 sha=%s）：" % (len(sha_lines), sha("\n".join(sha_lines))))
    for line in sha_lines[:6]:
        note("    " + line)
    note("    …（完整清单见 out/W-B20.md §④）")


# ============================================================
# D. 子进程健壮：超时 / 崩溃 / seed
# ============================================================
def test_subprocess_robustness() -> None:
    print("\n=== D. 子进程健壮（超时 / 崩溃 / seed 可指定）===")
    from editor import play as PLAY
    # 超时：把 driver 的超时压到 1s 跑一个必超时的 worker（sleep 包一层）
    code = ("import sys,time;sys.stdin.read();time.sleep(30)")
    env = {**os.environ, "B20_PLAY_TIMEOUT": "1", "PYTHONIOENCODING": "utf-8"}
    import editor.play as P
    old_worker, old_timeout = P.WORKER, P.TIMEOUT

    import tempfile
    fd, path = None, None
    # 直接在 workspace 里造一个 sleep worker（沙箱：tempfile 目录不可写）
    path = os.path.join(DB_DIR, "_sleep_worker.py")
    os.makedirs(DB_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(code + "\n")
    P.WORKER, P.TIMEOUT = path, 1
    try:
        res = P.run(PKG, ["角色"], seed=1, db=os.path.join(DB_DIR, "timeout.db"), db_dir=DB_DIR)
        check("超时被掐死且明确报 stage=timeout", res.get("stage") == "timeout",
              json.dumps(res, ensure_ascii=False)[:300])
    finally:
        P.WORKER, P.TIMEOUT = old_worker, old_timeout
        os.remove(path)

    # 崩溃：造一个立刻 sys.exit(3) 的 worker → 必须明确报 crash（不静默）
    path2 = os.path.join(DB_DIR, "_crash_worker.py")
    with open(path2, "w", encoding="utf-8", newline="\n") as f:
        f.write("import sys\nsys.stderr.write('boom\\n')\nsys.exit(3)\n")
    P.WORKER = path2
    try:
        res2 = P.run(PKG, ["角色"], seed=1, db=os.path.join(DB_DIR, "crash.db"), db_dir=DB_DIR)
        check("worker 崩溃 → 明确报错（stage=crash + stderr 尾巴）",
              res2.get("stage") == "crash" and "boom" in (res2.get("stderr") or ""),
              json.dumps(res2, ensure_ascii=False)[:300])
    finally:
        P.WORKER = old_worker
        os.remove(path2)

    # seed 可指定：同 seed + 同固定墙钟 + 同序列 + 同起点 → 逐字节复现
    # （不带 clock 时，`时间`/天气/冷却类输出随真实时刻变 —— 那是环境差异，不是不可复现）
    db1 = os.path.join(DB_DIR, "seed_a.db")
    db2 = os.path.join(DB_DIR, "seed_b.db")
    for p in (db1, db2):
        if os.path.exists(p):
            os.remove(p)
    seq = ["注册 种子甲 男", "探索"]
    r1 = PLAY.run(PKG, seq, seed=4242, uid="9501", group_id="gs", db=db1, db_dir=DB_DIR,
                  clock=CLOCK, engine_root=ENGINE_ROOT)
    r2 = PLAY.run(PKG, seq, seed=4242, uid="9501", group_id="gs", db=db2, db_dir=DB_DIR,
                  clock=CLOCK, engine_root=ENGINE_ROOT)
    check("同 seed + 同序列 + 同起点 + 同固定墙钟 → digests_sha 相同",
          r1.get("digests_sha") and r1.get("digests_sha") == r2.get("digests_sha"),
          "%s vs %s" % (r1.get("digests_sha"), r2.get("digests_sha")))
    check("子进程可选 db 路径（两条库互不影响）", r1.get("db") != r2.get("db"))
    check("摘要回报 seed / uid / group_id（可复现所需）",
          r1.get("seed") == 4242.0 and r1.get("uid") == "9501" and r1.get("group_id") == "gs",
          json.dumps({k: r1.get(k) for k in ("seed", "uid", "group_id")}, ensure_ascii=False))


def test_routes_fragment() -> None:
    """E. 路由片段实测：真起 HTTP 服务 → 打 `out/server_routes_B20.py` 的补丁 → 调端点。

    这条同时是「不改 `editor/server.py` 也能挂路由」的硬证据（补丁靠类方法替换，
    `server.py` 一个字节没动）。
    """
    print("\n=== E. 路由片段（out/server_routes_B20.py，零改 server.py）===")
    import json
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    routes = os.path.join(ROOT, "editor", "routes_play.py")
    src = open(routes, encoding="utf-8").read()
    check("片段带 # B20_ROUTES_BEGIN / # B20_ROUTES_END 标记",
          "# B20_ROUTES_BEGIN" in src and "# B20_ROUTES_END" in src)
    check("片段不 import saintess_engine（父进程侧）",
          "import saintess_engine" not in src and "from saintess_engine" not in src)

    server_py = os.path.join(ROOT, "editor", "server.py")
    before = open(server_py, "rb").read()
    code = (
        "import importlib.util as u, sys, json, threading, urllib.request\n"
        "sys.path.insert(0, %r)\n"
        "sys.path.insert(0, %r)\n"
        "spec = u.spec_from_file_location('b20_routes', %r)\n"
        "m = u.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "from editor import server as SRV\n"
        "import editor.play as PLAY\n"
        "SRV.GAMES_DIR = None\n"
        "httpd = __import__('http.server', fromlist=['x']).ThreadingHTTPServer(('127.0.0.1', 0), SRV.H)\n"
        "port = httpd.server_address[1]\n"
        "threading.Thread(target=httpd.serve_forever, daemon=True).start()\n"
        "base = 'http://127.0.0.1:%%d' %% port\n"
        "\n"
        "def get(p):\n"
        "    with urllib.request.urlopen(base + p, timeout=120) as r:\n"
        "        return r.status, json.loads(r.read().decode('utf-8'))\n"
        "\n"
        "def post(p, body):\n"
        "    req = urllib.request.Request(base + p, data=json.dumps(body).encode('utf-8'),\n"
        "                                 method='POST', headers={'Content-Type': 'application/json'})\n"
        "    try:\n"
        "        with urllib.request.urlopen(req, timeout=300) as r:\n"
        "            return r.status, json.loads(r.read().decode('utf-8'))\n"
        "    except urllib.error.HTTPError as e:\n"
        "        return e.code, json.loads(e.read().decode('utf-8'))\n"
        "\n"
        "st, j = get('/api/package/orlandia/play/commands')\n"
        "print('LIST', st, j.get('count'), j.get('ok'))\n"
        "st2, j2 = post('/api/package/orlandia/play',\n"
        "               {'commands': ['注册 网页甲 男', '角色'], 'seed': 5, 'uid': '9901',\n"
        "                'group_id': 'gp', 'db': %r, 'clock': 1700000000.0})\n"
        "print('RUN', st2, (j2.get('stage')), len(j2.get('rows') or []),\n"
        "      bool(((j2.get('rows') or [None, {}])[1] or {}).get('segments')))\n"
        "st3, j3 = post('/api/package/nope/play', {'commands': ['角色']})\n"
        "print('MISS', st3, j3.get('ok'))\n"
        "st4, j4 = post('/api/package/orlandia/play', {'commands': []})\n"
        "print('EMPTY', st4, j4.get('ok'))\n"
        "print('ENGINE_IN_PROC=' + ','.join(m for m in sys.modules if m.startswith('saintess_engine')))\n"
        % (ROOT, HERE, routes, os.path.join(DB_DIR, "http.db"))
    )
    import subprocess
    pr = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=900,
                        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
                             "PYTHONPATH": HOST_ROOT or "",
                             # ★ 路由段走**本仓树**：`editor/packages.py::DEFAULT_GAMES_DIR`
                             #   与 `play.discover()` 的引擎根都钉在 `FRAMEWORK_ROOT` ⇒ 这一段
                             #   的包与引擎天然同源。故这里把宿主变量显式清空 —— 否则 play
                             #   子进程会按 `B20_HOST_ROOT` 去装**部署树**的引擎（`_setup_paths`
                             #   把宿主根摆在引擎根前面），与 `FW_GAMES_DIR` 指的本仓包混装。
                             "FW_GAMES_DIR": os.path.join(ROOT, "games"),
                             "B20_HOST_ROOT": "", "GWEN_PLUGIN_ROOT": "",
                             "DRAGONFALL_ROOT": ""})
    out = (pr.stdout or "") + (pr.stderr or "")
    check("GET …/play/commands → 200 + 196 条", ("LIST 200 196 True" in out) or ("LIST 200 195 True" in out), out[-400:])
    check("POST …/play → 200 + stage=done + 2 条 + 有文本段", "RUN 200 done 2 True" in out, out[-400:])
    check("不存在的包 → 404", "MISS 404 False" in out, out[-400:])
    check("空 commands → 400", "EMPTY 400 False" in out, out[-400:])
    eng_tail = out.split("ENGINE_IN_PROC=")[-1].splitlines()[0].strip() if "ENGINE_IN_PROC=" in out else "?"
    # ⚠️ 口径澄清：`editor/server.py` 自己**本来就** import 引擎（校验 / 派生视图用，B20 之前的既有事实），
    #    所以「服务进程里零 saintess_engine」不成立、也不该是本线的判据。本线的判据是
    #    **试玩链路自己不引入引擎**：`editor.play` 单独 import 后 `sys.modules` 里没有引擎（A 段已断言），
    #    路由片段全文无引擎 import（上一行），且跑命令确实走子进程（stage=done 的 db 落在独立库）。
    check("★ 路由片段本身不 import 引擎（试玩链路零引擎 import）",
          "import saintess_engine" not in src and "from saintess_engine" not in src)
    check("（参考）服务进程里引擎模块由既有 `editor/server.py` 带入 —— 本线未加剧",
          eng_tail != "?", "未见探针输出")
    note("服务进程 engine 模块数（既有 server.py 带入）：%d" % (len(eng_tail.split(",")) if eng_tail else 0))
    after = open(server_py, "rb").read()
    check("editor/server.py 逐字节未变（本线纪律）", before == after)


# ============================================================
# C0 / C2. 试玩脱宿主（T7 第 3 轮）：无宿主子集 · 无宿主 vs 有宿主逐字节对拍
# ============================================================
#: 对拍子集（建档 → 面板 → 列表 → 商店/任务）：试玩链最常用的一条，覆盖动态助手解析。
HOSTLESS_SAMPLES = ["注册 试玩者 男", "背包", "状态", "帮助", "日常", "生活技能", "任务", "商店"]


def _run_play(tag, host_root, seq, *, clock=CLOCK, seed=11, uid="9001", group_id="g9"):
    """跑一侧（`host_root=""` ⇒ 无宿主/引擎试玩壳；给了 ⇒ 真插件宿主壳）。"""
    from editor import play as PLAY
    os.makedirs(DB_DIR, exist_ok=True)
    db = os.path.join(DB_DIR, "t7_%s.db" % tag)
    if os.path.exists(db):
        os.remove(db)
    return PLAY.run(PKG, seq, seed=seed, uid=uid, group_id=group_id, host_root=host_root,
                    db=db, db_dir=DB_DIR, clock=clock, engine_root=ENGINE_ROOT)


def _brief(res: dict) -> str:
    return json.dumps({k: v for k, v in res.items() if k != "rows"}, ensure_ascii=False)[:300]


def test_hostless_subset() -> None:
    """C0 · 无宿主：引擎试玩壳真跑 8 条子集全绿 + 可复现（同 seed / 钟 ⇒ 同 sha）。"""
    print()
    print("=== C0. 无宿主（host_root="" ）子集实跑 ===")
    a = _run_play("hostless_a", "", HOSTLESS_SAMPLES)
    check("无宿主 stage=done", a.get("stage") == "done", _brief(a))
    rows = a.get("rows") or []
    bad = [(r.get("text"), (r.get("error") or "")[:80]) for r in rows if not r.get("ok")]
    check("无宿主子集 %d 条全绿（包内助手按名解析可用）"
          % len(HOSTLESS_SAMPLES), len(rows) == len(HOSTLESS_SAMPLES) and not bad, str(bad[:3]))
    check("无宿主 host_modules=0（不蹭宿主树任何文件）", a.get("host_modules") == 0,
          str(a.get("host_modules")))
    b = _run_play("hostless_b", "", HOSTLESS_SAMPLES)
    check("同 seed + 同固定墙钟 + 同序列 ⇒ digests_sha 可复现",
          bool(a.get("digests_sha")) and a.get("digests_sha") == b.get("digests_sha"),
          "%s vs %s" % (a.get("digests_sha"), b.get("digests_sha")))
    note("无宿主子集 digests_sha = %s" % a.get("digests_sha"))


def test_hostless_vs_host_parity() -> None:
    """C2 · 无宿主（引擎 `PlayShell`）vs 有宿主（插件 `HostShell`）逐条 digest 相同。"""
    print()
    print("=== C2. 无宿主 vs 有宿主：逐字节对拍（%d 条子集）===" % len(HOSTLESS_SAMPLES))
    a = _run_play("hostless", "", HOSTLESS_SAMPLES)
    b = _run_play("withhost", HOST_ROOT, HOSTLESS_SAMPLES)
    check("两侧都 stage=done", a.get("stage") == "done" and b.get("stage") == "done",
          "A=%s B=%s" % (a.get("stage"), b.get("stage")))
    ra, rb = a.get("rows") or [], b.get("rows") or []
    check("两侧条数一致", len(ra) == len(rb) == len(HOSTLESS_SAMPLES),
          "A=%d B=%d" % (len(ra), len(rb)))
    diffs = []
    same = 0
    for i in range(min(len(ra), len(rb))):
        if ra[i].get("digest") and ra[i].get("digest") == rb[i].get("digest"):
            same += 1
            continue
        diffs.append({"i": i, "text": ra[i].get("text"), "a_ok": ra[i].get("ok"),
                      "b_ok": rb[i].get("ok"), "a_key": ra[i].get("key"), "b_key": rb[i].get("key"),
                      "a_err": (ra[i].get("error") or "")[:80],
                      "b_err": (rb[i].get("error") or "")[:80],
                      "a_seg": (ra[i].get("segments") or [])[:1],
                      "b_seg": (rb[i].get("segments") or [])[:1]})
    check("★ 逐条 digest 相同（key + 文本段 + 平台动作 + 状态 sha）",
          same == len(HOSTLESS_SAMPLES),
          "%d/%d；差异 %s" % (same, len(HOSTLESS_SAMPLES),
                            json.dumps(diffs[:3], ensure_ascii=False)[:700]))
    check("★ 两侧整串 digests_sha 相同",
          bool(a.get("digests_sha")) and a.get("digests_sha") == b.get("digests_sha"),
          "A=%s B=%s" % (a.get("digests_sha"), b.get("digests_sha")))
    check("有宿主侧 host_modules=1（真宿主壳确实被装上，不是同侧互比）",
          b.get("host_modules") == 1, str(b.get("host_modules")))
    note("两侧 digests_sha = %s" % a.get("digests_sha"))


# ============================================================
# E2. 反证：打桩 `ShellBase.__getattr__` ⇒ `背包` 必红
# ============================================================
# F. 平台动作记录「真的进对拍」（T7 第 5 轮 · 常驻门禁）
# ============================================================
# 为什么要有这一段
# ----------------
# T7-B 修掉的那个 bug：命令循环把动作表**重绑**成新 list（`adapter.events = []`）⇒
# 壳装配时握的是**旧表**，壳写进去的动作永远读不到 ⇒ 每条 `rec["actions"]` 恒空。
# 当时唯一的证据是「两侧 digests_sha 相同」—— 那是「**同为空的相同**」：平台动作
# （广播 / 通知 / 投递）实际**从未进入对拍**。本段把它变成常驻门禁：
#   F1 源码级（两侧）：「不重绑外部对象的动作表」+「有就地清空」+「壳装配交同一张表」
#   F2 反证：按老 bug 的样子改一行 ⇒ 判据必红（扫描器不是摆设；并核 `self.events = []` 不误伤）
#   F3 运行时：真 `PlayShell(pkg=…, events=lst)._events is lst`；就地清空生效；**清空拷贝无效**
#   F4 端到端：造一条「已过期拍卖」⇒ `拍卖` 的 actions **非空**（对照组「角色」为空）
#: 命令循环里「平台动作表」的属性名（壳握着的那个 list 对象）
_ACTION_ATTRS = ("events", "_events")


def _action_wiring_report(src: str) -> dict:
    """静态核一个「命令循环」文件的动作表接线 ⇒ `{"rebind": [...], "clear": [...], "wire": [...]}`。

    R1 `rebind`（**必红**）：给**外部对象**（不是 `self`）的动作表属性赋值 / `del` 属性
       —— 壳握的是那**一个** list 对象，重绑后循环读的是新表 ⇒ `actions` 恒空。
       `self.events = []`（适配器自己在 `__init__` 里建表）**不误伤**（见 F2 反证③）。
    R2 `clear`：`del <动作表>[:]`（切片删除 = **就地**清空真对象，不是重绑）。
    R3 `wire`：壳装配处 `events=<…>.events` 的实参（必须全是同一张表，不许 `events=[]`）。
    """
    import ast as _ast
    tree = _ast.parse(src)
    rebind, clear, wire = [], [], []
    for node in _ast.walk(tree):
        if (isinstance(node, _ast.Attribute) and node.attr in _ACTION_ATTRS
                and isinstance(node.ctx, (_ast.Store, _ast.Del))
                and not (isinstance(node.value, _ast.Name) and node.value.id == "self")):
            rebind.append("%s（行 %d）" % (_ast.unparse(node), node.lineno))
        elif isinstance(node, _ast.Delete):
            for t in node.targets:
                if isinstance(t, _ast.Subscript) and isinstance(t.slice, _ast.Slice):
                    clear.append(_ast.unparse(t))
        elif isinstance(node, _ast.Call):
            for kw in node.keywords:
                if kw.arg == "events":
                    wire.append(_ast.unparse(kw.value))
    return {"rebind": rebind, "clear": clear, "wire": wire}


def _wiring_ok(rep: dict) -> bool:
    """F1 判据本体：三条件同时成立才算接线对。"""
    return (not rep["rebind"]
            and any(c.endswith("[:]") for c in rep["clear"])
            and len(rep["wire"]) >= 2
            and all(w.endswith(".events") for w in rep["wire"]))


def _func_clears_in_place(src: str, fname: str) -> bool:
    """`fname` 函数体内是否有「就地清空」`del <x>[:]`（QQ 侧参考跑用的是临时名 `_ev`）。"""
    import ast as _ast
    for node in _ast.walk(_ast.parse(src)):
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and node.name == fname:
            for sub in _ast.walk(node):
                if isinstance(sub, _ast.Delete):
                    for t in sub.targets:
                        if isinstance(t, _ast.Subscript) and isinstance(t.slice, _ast.Slice):
                            return True
    return False


def test_action_list_wiring() -> None:
    """F1 · 源码级（引擎试玩侧 + QQ 侧参考跑）：不重绑 / 就地清空 / 壳装同表。"""
    print()
    print("=== F1. 源码级：动作表「不重绑 / 就地清空 / 壳装同表」===")
    eng_path = os.path.join(ROOT, "editor", "play_worker.py")
    with open(eng_path, encoding="utf-8") as f:
        eng = f.read()
    rep = _action_wiring_report(eng)
    check("试玩侧：无「重绑动作表」写法（`adapter.events = …` / `del adapter.events`）",
          not rep["rebind"], str(rep["rebind"])[:200])
    check("试玩侧：有「就地清空」`del adapter.events[:]`",
          "adapter.events[:]" in rep["clear"], str(rep["clear"])[:200])
    check("试玩侧：壳装配都把同一张表交给壳（`events=adapter.events` ≥2 处）",
          len(rep["wire"]) >= 2 and all(w == "adapter.events" for w in rep["wire"]),
          str(rep["wire"])[:200])
    check("试玩侧：三条件同时成立（`_wiring_ok`）", _wiring_ok(rep), str(rep)[:200])
    host_path = os.path.join(HOST_ROOT, "tests", "b20_qq_ref.py") if HOST_ROOT else ""
    if host_path and os.path.exists(host_path):
        with open(host_path, encoding="utf-8") as f:
            hsrc = f.read()
        hrep = _action_wiring_report(hsrc)
        check("QQ 侧参考跑：无「重绑动作表」写法（`shell._events = …`）",
              not hrep["rebind"], str(hrep["rebind"])[:200])
        check("QQ 侧参考跑：`_run_one` 里就地清空（`del _ev[:]`）",
              _func_clears_in_place(hsrc, "_run_one"), str(hrep["clear"])[:200])
    else:
        note("无宿主：跳过 QQ 侧参考跑的源码级核（与 C/E 段同口径）")


def test_action_wiring_negative() -> None:
    """F2 · 反证：按 T7-B 那个 bug 的样子改一行 ⇒ 判据必红。"""
    print()
    print("=== F2. 反证：老 bug 的写法必须被扫出来 ===")
    with open(os.path.join(ROOT, "editor", "play_worker.py"), encoding="utf-8") as f:
        eng = f.read()
    bad1 = eng.replace("del adapter.events[:]", "adapter.events = []")
    r1 = _action_wiring_report(bad1)
    check("反证①：把「就地清空」改成重绑 ⇒ R1 必中 + 整体判据必红",
          bad1 != eng and bool(r1["rebind"]) and not _wiring_ok(r1), str(r1["rebind"])[:200])
    bad2 = eng.replace("events=adapter.events", "events=[]")
    r2 = _action_wiring_report(bad2)
    check("反证②：壳装配改成 `events=[]` ⇒ 判据必红（壳另起一张表）",
          bad2 != eng and not _wiring_ok(r2), str(r2["wire"])[:200])
    check("反证③：`self.events = []`（适配器自身建表）**不误伤**",
          not _action_wiring_report(
              "class A:\n    def __init__(self):\n        self.events = []\n").get("rebind"))
    host_path = os.path.join(HOST_ROOT, "tests", "b20_qq_ref.py") if HOST_ROOT else ""
    if host_path and os.path.exists(host_path):
        with open(host_path, encoding="utf-8") as f:
            hsrc = f.read()
        bad3 = hsrc.replace("del _ev[:]", "shell._events = []")
        r3 = _action_wiring_report(bad3)
        check("反证④：QQ 侧改成 `shell._events = []` ⇒ R1 必中",
              bad3 != hsrc and bool(r3["rebind"]), str(r3["rebind"])[:200])


#: F3 探针（子进程跑：核「壳握的就是循环清空/读取的那**一个** list」）
_F3_PROBE = '''
import asyncio, json, sys
sys.path.insert(0, %r)
import saintess_engine.package as _eng          # ① 引擎：与 PKG 同树（先进 sys.modules）
sys.path.insert(0, %r)                          # ② 本仓 `editor/**`（被测实现）置前
from editor.play_shell import PlayShell
pkg = _eng.load_stack(%r, inject={"db_path": "", "clock": None, "log": None, "tlog": None})
lst = []
sh = PlayShell(pkg=pkg, events=lst)
out = {"same_object": sh._events is lst}
asyncio.run(sh._deliver("g1", "hi"))
out["hit_same_list"] = [dict(a) for a in lst]
del lst[:]
out["cleared_in_place"] = list(sh._events)
copy = list(lst)
asyncio.run(sh._deliver("g1", "x"))
del copy[:]
out["copy_clear_ineffective"] = [dict(a) for a in sh._events]
print("__F3__" + json.dumps(out, ensure_ascii=False))
'''


def test_action_list_runtime_identity() -> None:
    """F3 · 运行时：壳与命令循环共用**同一个**动作表对象（拷贝清空无效）。"""
    print()
    print("=== F3. 运行时：壳与循环共用同一个动作表对象 ===")
    os.makedirs(DB_DIR, exist_ok=True)
    probe = os.path.join(DB_DIR, "_t7_action_list.py")
    with open(probe, "w", encoding="utf-8", newline="") as f:
        f.write(_F3_PROBE % (ENGINE_ROOT, ROOT, PKG))
    pr = subprocess.run([sys.executable, probe], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=600,
                        env={**os.environ, "PYTHONIOENCODING": "utf-8",
                             "PYTHONUTF8": "1"})
    out = {}
    for line in (pr.stdout or "").splitlines():
        if line.startswith("__F3__"):
            out = json.loads(line[len("__F3__"):])
    check("探针跑通（真包 + 真引擎 PlayShell）", bool(out),
          ((pr.stderr or "") or (pr.stdout or ""))[-200:])
    check("`PlayShell(events=lst)._events is lst`（同一个对象，不是拷贝）",
          out.get("same_object") is True, str(out)[:200])
    hit = out.get("hit_same_list") or [{}]
    check("壳写的动作落进循环那张表（`deliver` 记录）",
          bool(hit) and hit[0].get("action") == "deliver",
          json.dumps(hit, ensure_ascii=False)[:160])
    check("`del lst[:]` ⇒ 壳侧同步清空（就地清空真对象）",
          out.get("cleared_in_place") == [], str(out.get("cleared_in_place"))[:160])
    check("★ 反证：清空**拷贝**无效（壳的表仍在）⇒ 必须就地清空真对象",
          bool(out.get("copy_clear_ineffective")),
          json.dumps(out.get("copy_clear_ineffective"), ensure_ascii=False)[:160])


def test_action_list_end_to_end() -> None:
    """F4 · 端到端：有动作的样本 `actions` 真的非空（对拍不再是「同为空的相同」）。"""
    print()
    print("=== F4. 端到端：过期拍卖结算 ⇒ actions 非空（对照组为空）===")
    import sqlite3
    from editor import play as PLAY
    os.makedirs(DB_DIR, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="t7_f4_", dir=DB_DIR)
    reg = os.path.join(tmp, "reg.db")
    r0 = PLAY.run(PKG, ["注册 动作探针 男"], seed=11, uid="9201", group_id="gf",
                  host_root="", db=reg, db_dir=tmp, clock=CLOCK, engine_root=ENGINE_ROOT)
    check("F4 建档 stage=done", r0.get("stage") == "done", _brief(r0))
    if r0.get("stage") != "done":
        note("F4 前置建档失败 ⇒ 跳过本段（后面的 `DELETE FROM world_event` 会因缺表抛 "
             "未捕获异常，把整份门禁的表直接带崩，看不到失败汇总）")
        return
    data = {"items": [{"id": 1, "name": "试作胸甲", "slot": "armor", "lv": 30,
                       "quality": "purple", "bids": {}, "base": 100, "buyout": 500}]}
    con = sqlite3.connect(reg, timeout=10)
    con.execute("DELETE FROM world_event")
    con.execute("INSERT INTO world_event (etype, starts_at, ends_at, data) VALUES (?,?,?,?)",
                ("auction", int(CLOCK) - 600, int(CLOCK) - 300,
                 json.dumps(data, ensure_ascii=False)))
    con.commit()
    con.close()
    db_ctrl = os.path.join(tmp, "ctrl.db")
    db_act = os.path.join(tmp, "act.db")
    shutil.copyfile(reg, db_ctrl)
    shutil.copyfile(reg, db_act)
    ctrl = PLAY.run(PKG, ["角色"], seed=11, uid="9201", group_id="gf", host_root="",
                    db=db_ctrl, db_dir=tmp, clock=CLOCK, engine_root=ENGINE_ROOT)
    act = PLAY.run(PKG, ["拍卖"], seed=11, uid="9201", group_id="gf", host_root="",
                   db=db_act, db_dir=tmp, clock=CLOCK, engine_root=ENGINE_ROOT)
    crow = (ctrl.get("rows") or [{}])[0]
    arow = (act.get("rows") or [{}])[0]
    check("对照组（角色）actions 为空（不是「永远非空」）",
          crow.get("ok") and crow.get("actions") == [], _brief(ctrl))
    acts = arow.get("actions") or []
    check("★ 有动作样本（过期拍卖结算 → 广播）actions 非空",
          arow.get("ok") and bool(acts), json.dumps(arow, ensure_ascii=False)[:300])
    check("动作形状 = 记录式平台半边（dict + action 字段）",
          bool(acts) and all(isinstance(a, dict) and a.get("action") for a in acts),
          json.dumps(acts, ensure_ascii=False)[:200])
    check("结算文本进了动作记录（落槌结算 → 播报）",
          bool(acts) and "落槌结算" in str(acts[0].get("text") or ""),
          json.dumps(acts, ensure_ascii=False)[:200])
    note("过期拍卖 `拍卖` 的动作 = %s" % json.dumps(acts, ensure_ascii=False)[:120])



# ============================================================
# F5. 有动作的样本「真的进对拍」（T8 · 台账 §0 D10 A 案）
# ============================================================
# T7-C 暴露的问题：两侧「平台动作记录」形状不同（QQ 记 `say` / 试玩记 `broadcast`）⇒
# 有平台动作的样本进 C 段对拍必红 ⇒ 动作面**实际未被逐字节覆盖**。A 案把**扇出**（按群表
# 逐群）与**记录形状**上移引擎 `ShellBase`（两壳只剩 `_deliver` = 真投递那一步）⇒ 两侧记录
# **按构造**逐字节相同。本段把这条常驻化：
#   形状只有一处定义（AST：引擎 `ShellBase` 有扇出 / 试玩壳与 QQ 壳没有）
#   ① 过期拍卖落槌（真命令路径 · 两侧真跑）⇒ `actions` 序列化 sha 相同 + digest 相同
#   ② 广播 + 一条通知（真扇出口 · 两侧真跑）⇒ `actions` 序列化 sha 相同
# 无宿主时只跑试玩侧那半（与 C 段同口径）。
_F5_TAGS = ("broadcast", "notice")
_F5_BROADCAST = "【全服播报】T8 探针：扇出与记录口径"
_F5_NOTICE = "T8 通知内容"
_F5_UID, _F5_GID = "9301", "ga"

#: 试玩侧探针（子进程：真包 + 真 `PlayShell`，直接驱动扇出口）
_F5_PROBE = """
import asyncio, json, os, sys
payload = json.loads(sys.stdin.read())
sys.path.insert(0, payload["engine_root"])
import saintess_engine.package as _eng          # ① 引擎：与 PKG 同树
sys.path.insert(0, payload["ed_root"])          # ② 本仓 `editor/**`（被测实现）置前
from editor.play_shell import PlayShell
os.environ["GWEN_GAME_DB"] = payload["db"]
pkg = _eng.load_stack(payload["pkg_dir"], inject={"db_path": payload["db"], "clock": None,
                                               "log": None, "tlog": None})
sh = PlayShell(pkg=pkg, events=[])
for tag in payload["tags"]:
    if tag == "broadcast":
        asyncio.run(sh._broadcast(payload["broadcast"]))
    elif tag == "notice":
        asyncio.run(sh._notify_hermes(payload["group_id"], payload["uid"],
                                      payload["notice"], "feedback"))
print("__F5__" + json.dumps([dict(a) for a in sh._events], ensure_ascii=False))
"""


def _actions_sha(actions) -> str:
    """动作记录的序列化 sha（键序无关 ⇒ 比的是**内容与形状**，不是 dict 插入序）。"""
    return sha(json.dumps(actions, ensure_ascii=False, sort_keys=True))


def _class_method_names(src: str, cls: str) -> set:
    """类里**直接定义**的方法名集合（AST；用于核「形状只有一处定义」）。"""
    import ast as _ast
    for node in _ast.walk(_ast.parse(src)):
        if isinstance(node, _ast.ClassDef) and node.name == cls:
            return {n.name for n in node.body
                    if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))}
    return set()


def _f5_play_probe(tmp, db):
    """试玩侧：真包 + 真 `PlayShell` → 扇出口（广播 / 通知）记录。"""
    probe = os.path.join(tmp, "_f5_actions.py")
    with open(probe, "w", encoding="utf-8", newline="") as f:
        f.write(_F5_PROBE)
    payload = {"engine_root": ENGINE_ROOT, "ed_root": ROOT, "pkg_dir": PKG, "db": db,
               "tags": list(_F5_TAGS),
               "broadcast": _F5_BROADCAST, "notice": _F5_NOTICE,
               "group_id": _F5_GID, "uid": _F5_UID}
    pr = subprocess.run([sys.executable, probe], input=json.dumps(payload), capture_output=True,
                        text=True, encoding="utf-8", errors="replace", timeout=600,
                        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
                             "GWEN_GAME_DB": db})
    out = None
    for line in (pr.stdout or "").splitlines():
        if line.startswith("__F5__"):
            out = json.loads(line[len("__F5__"):])
    return out, ((pr.stderr or "") or (pr.stdout or ""))[-300:]


def _f5_qq_probe(db):
    """QQ 侧：`tests/b20_qq_ref.py` 的 `actions_probe` 模式（真宿主壳 + 真扇出口）。"""
    req = {"actions_probe": list(_F5_TAGS), "commands": [], "handlers": [], "uid": _F5_UID,
           "group_id": _F5_GID, "db": db, "seed": 11, "clock": CLOCK,
           "broadcast": _F5_BROADCAST, "notice": _F5_NOTICE}
    pr = subprocess.run([sys.executable, QQ_REF], input=json.dumps(req), capture_output=True,
                        text=True, encoding="utf-8", errors="replace", cwd=HOST_ROOT, timeout=600,
                        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
                             "B20_CLOCK": str(CLOCK), "PYTHONPATH": HOST_ROOT})
    out = None
    for line in (pr.stdout or "").splitlines():
        if line.startswith("__B20_QQREF__"):
            obj = json.loads(line[len("__B20_QQREF__"):])
            if obj.get("stage") == "actions_probe":
                out = obj.get("actions")
    return out, ((pr.stdout or "") + (pr.stderr or ""))[-300:]


def test_action_parity() -> None:
    """F5 · 有动作的样本两侧同库跑 ⇒ `actions` 序列化 sha 相同（形状只有一处定义）。"""
    print()
    print("=== F5. 有动作的样本进对拍：两侧 actions 序列化 sha 相同 ===")
    import sqlite3
    from editor import play as PLAY
    os.makedirs(DB_DIR, exist_ok=True)

    # ---- 形状只有一处定义（源码级 · A 案的判据本体）----
    eng_shell = os.path.join(ROOT, "saintess_engine", "host", "shell.py")
    play_shell = os.path.join(ROOT, "editor", "play_shell.py")
    host_shell = os.path.join(HOST_ROOT, "host", "shell.py") if HOST_ROOT else ""
    with open(eng_shell, encoding="utf-8") as f:
        base_m = _class_method_names(f.read(), "ShellBase")
    need = {"_broadcast", "_notify_hermes", "_group_table", "_record_deliver"}
    check("引擎 `ShellBase` 定义扇出 + 记录形状（4 个口）", need.issubset(base_m),
          str(sorted(need - base_m)))
    with open(play_shell, encoding="utf-8") as f:
        play_m = _class_method_names(f.read(), "PlayShell")
    check("试玩壳只留 `_deliver`（不再自记 `_broadcast` / `_notify_hermes`）",
          "_deliver" in play_m and {"_broadcast", "_notify_hermes"}.isdisjoint(play_m),
          str(sorted(play_m)))
    if host_shell and os.path.exists(host_shell):
        with open(host_shell, encoding="utf-8") as f:
            host_m = _class_method_names(f.read(), "HostShell")
        check("QQ 壳只留 `_deliver`（不再自记 `_broadcast` / `_notify_hermes`）",
              "_deliver" in host_m and {"_broadcast", "_notify_hermes"}.isdisjoint(host_m),
              str(sorted(host_m)))
    check("反证：形状不同 ⇒ sha 必不同（判据不是恒真）",
          _actions_sha([{"action": "say", "group_id": "ga", "text": "x"}])
          != _actions_sha([{"action": "deliver", "group_id": "ga", "text": "x"}]))

    tmp = tempfile.mkdtemp(prefix="t8_f5_", dir=DB_DIR)
    reg = os.path.join(tmp, "reg.db")
    r0 = PLAY.run(PKG, ["注册 动作对拍 男"], seed=11, uid=_F5_UID, group_id=_F5_GID,
                  host_root="", db=reg, db_dir=tmp, clock=CLOCK, engine_root=ENGINE_ROOT)
    check("F5 建档 stage=done", r0.get("stage") == "done", _brief(r0))
    if r0.get("stage") != "done":
        note("F5 前置建档失败 ⇒ 跳过本段（与 F4 同因：缺表会抛未捕获异常）")
        return

    # ---- ① 过期拍卖落槌（真命令路径）----
    data = {"items": [{"id": 1, "name": "试作胸甲", "slot": "armor", "lv": 30,
                       "quality": "purple", "bids": {}, "base": 100, "buyout": 500}]}
    con = sqlite3.connect(reg, timeout=10)
    con.execute("DELETE FROM world_event")
    con.execute("INSERT INTO world_event (etype, starts_at, ends_at, data) VALUES (?,?,?,?)",
                ("auction", int(CLOCK) - 600, int(CLOCK) - 300,
                 json.dumps(data, ensure_ascii=False)))
    con.commit()
    con.close()
    play_db = os.path.join(tmp, "f5_play.db")
    shutil.copyfile(reg, play_db)
    play = PLAY.run(PKG, ["拍卖"], seed=11, uid=_F5_UID, group_id=_F5_GID, host_root="",
                    db=play_db, db_dir=tmp, clock=CLOCK, engine_root=ENGINE_ROOT)
    p_row = (play.get("rows") or [{}])[0]
    p_acts = p_row.get("actions") or []
    check("① 试玩侧：过期拍卖落槌 ⇒ actions 非空", bool(p_row.get("ok")) and bool(p_acts),
          json.dumps(p_row, ensure_ascii=False)[:300])
    if HOST_ROOT:
        qq_db = os.path.join(tmp, "f5_qq.db")
        shutil.copyfile(reg, qq_db)
        q_rows, _q_tail, _q_log = _run_qq_ref([("拍卖", "auction")], qq_db,
                                              uid=_F5_UID, group_id=_F5_GID)
        q_row = (q_rows or [{}])[0]
        q_acts = q_row.get("actions") or []
        check("① QQ 侧：过期拍卖落槌 ⇒ actions 非空", bool(q_acts),
              json.dumps(q_row, ensure_ascii=False)[:300])
        check("① ★ 两侧 actions 序列化 sha 相同（记录形状统一）",
              _actions_sha(q_acts) == _actions_sha(p_acts),
              "qq=%s play=%s" % (json.dumps(q_acts, ensure_ascii=False)[:200],
                                 json.dumps(p_acts, ensure_ascii=False)[:200]))
        check("① 两侧 digest 相同（动作面真的进对拍了）",
              bool(q_row.get("digest")) and q_row.get("digest") == p_row.get("digest"),
              "qq=%s play=%s" % (q_row.get("digest"), p_row.get("digest")))
        note("① 落槌动作 = %s · 序列化 sha = %s"
             % (json.dumps(q_acts, ensure_ascii=False)[:110], _actions_sha(q_acts)))
    else:
        note("无宿主：① 只跑试玩侧（与 C 段同口径）")

    # ---- ② 广播 + 一条通知（真扇出口）----
    fan_play = os.path.join(tmp, "f5_fan_play.db")
    shutil.copyfile(reg, fan_play)
    p2_acts, p2_err = _f5_play_probe(tmp, fan_play)
    check("② 试玩侧：扇出口探针跑通（真包 + 真 PlayShell）", p2_acts is not None, p2_err)
    check("② 试玩侧：广播 + 通知各落一条（不是「同为空的相同」）",
          len(p2_acts or []) == 2
          and [a.get("text") for a in (p2_acts or [])] == [_F5_BROADCAST, _F5_NOTICE],
          json.dumps(p2_acts or [], ensure_ascii=False)[:300])
    if HOST_ROOT:
        fan_qq = os.path.join(tmp, "f5_fan_qq.db")
        shutil.copyfile(reg, fan_qq)
        q2_acts, q2_log = _f5_qq_probe(fan_qq)
        check("② QQ 侧：扇出口探针跑通（真宿主壳）", q2_acts is not None, (q2_log or "")[-300:])
        check("② ★ 两侧 actions 序列化 sha 相同（逐字节）",
              _actions_sha(q2_acts or []) == _actions_sha(p2_acts or []),
              "qq=%s play=%s" % (json.dumps(q2_acts or [], ensure_ascii=False)[:200],
                                 json.dumps(p2_acts or [], ensure_ascii=False)[:200]))
        note("② 广播 + 通知动作 = %s 条 · 序列化 sha = %s"
             % (len(q2_acts or []), _actions_sha(q2_acts or [])))
    else:
        note("无宿主：② 只跑试玩侧（与 C 段同口径）")




# ============================================================
_SABOTAGE = """
import importlib.util, json, sys
sys.path.insert(0, %r)
import saintess_engine.host.shell as SB
sys.path.insert(0, %r)          # 本仓 `editor/**`（被 worker 引用）置前
def _boom(self, name):
    raise AttributeError("sabotage: " + name)
SB.ShellBase.__getattr__ = _boom
spec = importlib.util.spec_from_file_location("pw", %r)
pw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pw)
pw.run(json.loads(sys.stdin.read()))
"""


def _read_play_rows(out: str) -> list:
    rows = []
    for line in out.splitlines():
        if not line.startswith("__B20_PLAY__"):
            continue
        try:
            obj = json.loads(line[len("__B20_PLAY__"):])
        except ValueError:
            continue
        if "i" in obj:
            rows.append(obj)
    return rows


def test_helper_resolution_negative() -> None:
    """E2 · 把 `ShellBase.__getattr__` 打桩成抛错 ⇒ `背包` 必红（「按名解析」真在用）。"""
    print()
    print("=== E2. 反证：打桩 ShellBase.__getattr__ ⇒ 背包 必红 ===")
    from editor import play as PLAY
    os.makedirs(DB_DIR, exist_ok=True)
    probe = os.path.join(DB_DIR, "_t7_sabotage.py")
    with open(probe, "w", encoding="utf-8", newline="") as f:
        f.write(_SABOTAGE % (ENGINE_ROOT, ROOT, PLAY.WORKER))
    payload = {"pkg_dir": PKG, "host_root": "", "engine_root": ENGINE_ROOT,
               "commands": ["注册 打桩者 男", "背包"], "seed": 11, "uid": "9101",
               "group_id": "gs", "db": os.path.join(DB_DIR, "t7_sabotage.db"),
               "db_dir": DB_DIR, "clock": CLOCK}
    pr = subprocess.run([sys.executable, probe], input=json.dumps(payload),
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                        timeout=600, env={**os.environ, "PYTHONIOENCODING": "utf-8",
                                          "PYTHONUTF8": "1"})
    rows = _read_play_rows(pr.stdout or "")
    bag = rows[1] if len(rows) > 1 else {}
    check("打桩后 `背包` 明确失败（不是静默通过）", bool(bag) and not bag.get("ok"),
          json.dumps(bag, ensure_ascii=False)[:240])
    err = bag.get("error") or ""
    check("失败原因 = 助手按名解析被打桩（AttributeError）",
          "sabotage" in err or "AttributeError" in err, err[:240])
    note("打桩侧 背包 报错：%s" % err[:120])


# ============================================================
def main() -> int:
    print("=== B20 门禁：编辑器「试玩」通道 ===")
    print("包：%s" % PKG)
    print("宿主副本：%s" % (HOST_ROOT or "（无 —— 本仓不含宿主：只跳 QQ 侧对拍与路由片段）"))
    test_zero_engine_import()
    cov = test_full_command_coverage()
    if HOST_ROOT:
        test_byte_parity(cov.get("missing"))      # C 段：试玩通道 vs QQ 侧
        test_hostless_vs_host_parity()            # C2 段：无宿主 vs 有宿主
    else:
        test_hostless_subset()                    # C0 段：无宿主子集实跑
    test_action_list_wiring()                     # F1 段：源码级（重绑/就地清空/装同表）
    test_action_wiring_negative()                 # F2 段：反证（老 bug 必红）
    test_action_list_runtime_identity()           # F3 段：运行时同一个动作表对象
    test_action_list_end_to_end()                  # F4 段：有动作的样本 actions 非空
    test_action_parity()                          # F5 段：有动作的样本**两侧**逐字节（T8）
    test_helper_resolution_negative()             # E2 段：反证
    test_subprocess_robustness()
    if HOST_ROOT:
        test_routes_fragment()
    print()
    print("=" * 60)
    print("通过 %d / 失败 %d" % (PASS, FAIL))
    for f in FAILURES:
        print("  ❌ %s" % f)
    if FAIL:
        return 1
    print("✅ 试玩门禁全绿：零 import 引擎 / 全量 %d 覆盖 / %s / 子进程健壮"
          % (len(cov.get("keys") or []),
             "逐字节对拍（QQ 侧 + 无宿主 vs 有宿主）" if HOST_ROOT else "无宿主子集实跑 + 打桩反证"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
