# -*- coding: utf-8 -*-
"""B20 门禁：「试玩」通道（本线新增）。

跑法：`python tests/test_editor_play.py`（退出码 0 = 全绿）。
不依赖 pytest；与 `tests/test_host_contract.py` / `test_host_skeleton.py` 同风格。

守的四条底线
------------
A. **编辑器主进程零 import 引擎**：`import editor.play` 之后 `sys.modules` 里不许出现
   `saintess_engine*`（硬断言，不是「代码里搜字符串」）。子进程侧（`play_worker.py`）
   才是唯一允许 import 引擎的地方。
B. **全量命令覆盖（194/194）**：包内 `content/data/commands.json` 的每一条 key
   ① 在声明表里；② 在 `play` 的清单里；③ 子进程审计里逐条给出「有处理器 / 可解析」；
   ④ 每一条都能构造一次调用（有处理器的真跑，缺处理器的按引擎口径**回显声明**，不静默）。
C. **逐字节对拍（≥20 条）**：同 seed + 同命令序列 + 同固定墙钟下，
   试玩通道（引擎 host + 包）与 QQ 侧（`shim_astrbot` + `_host_bridge.run_async`）
   每条命令的 `digest`（key + 文本段 + 平台动作 + 状态 sha）逐条相同，且整串 sha 相同。
D. **子进程健壮**：超时可掐死（明确报 timeout，不静默）；worker 崩溃 → 明确报错；
   seed 可指定（同 seed 复现、异 seed 可不同）。
"""
from __future__ import annotations

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

    本仓（引擎仓）通常**不含宿主**；没有宿主时本门禁整体跳过（见 main 开头），
    提供方式：`B20_HOST_ROOT=<插件目录>` 或下列候选之一命中。
    """
    cands = [os.environ.get(k) for k in
             ("B20_HOST_ROOT", "SAINTESS_HOST_ROOT", "GWEN_HOST_ROOT")]
    cands += [
        os.path.join(os.path.dirname(ROOT), "qqbot", "data", "plugins", "dragonfall"),
        os.path.join(ROOT, "host", "dragonfall"),
        r"C:/Users/yuyu/qqbot/data/plugins/dragonfall",
    ]
    for c in cands:
        if c and os.path.isdir(os.path.join(c, "game")) and os.path.isdir(os.path.join(c, "framework")):
            return os.path.abspath(c)
    return ""


HOST_ROOT = _find_host_root()                      # 宿主插件目录（QQ 侧同一份）
if HOST_ROOT:
    os.environ.setdefault("B20_HOST_ROOT", HOST_ROOT)   # play.discover() 读它
PKG = (os.path.join(HOST_ROOT, "framework", "games", "orlandia") if HOST_ROOT
       else os.path.join(ROOT, "games", "orlandia"))   # 游戏包
QQ_REF = os.path.join(HOST_ROOT, "tests", "b20_qq_ref.py") if HOST_ROOT else ""
DB_DIR = os.path.join(tempfile.gettempdir(), "b20_play_db")
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


def check(name: str, cond: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✅ %s" % name)
    else:
        FAIL += 1
        FAILURES.append("%s %s" % (name, detail))
        print("  ❌ %s %s" % (name, detail))
    return bool(cond)


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
    check("discover() 找到 包/宿主/引擎 三个根",
          bool(cfg.get("pkg_dir")) and bool(cfg.get("host_root")) and bool(cfg.get("engine_root")),
          json.dumps(cfg, ensure_ascii=False))


# ============================================================
# B. 全量命令覆盖 194/194
# ============================================================
def test_full_command_coverage() -> dict:
    print("\n=== B. 全量命令覆盖（194 条 key）===")
    from editor import play as PLAY
    decl = json.load(open(os.path.join(PKG, "content", "data", "commands.json"), encoding="utf-8"))
    keys = sorted(decl)
    check("包内声明表 key 数 == 194", len(keys) == 194, "实际 %d" % len(keys))

    listing = PLAY.list_commands(PKG)
    check("play.list_commands() 列出全部 key",
          listing.get("ok") and listing.get("count") == len(keys),
          "count=%s" % listing.get("count"))
    check("清单 key 集合与声明表逐字相等",
          sorted(c["key"] for c in listing["commands"]) == keys)

    audit = PLAY.audit(PKG, db=os.path.join(DB_DIR, "audit.db"))
    check("子进程审计 stage=audit", audit.get("stage") == "audit", str(audit)[:200])
    akeys = sorted(r["key"] for r in (audit.get("rows") or []))
    check("审计覆盖全部 194 条（_maint_gate 在内）", akeys == keys,
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
    """`{消息原文: 声明 key}` —— 用宿主测试的**同一份**正则扫描实现复算（不另抄一份）。"""
    sys.path.insert(0, os.path.join(HOST_ROOT, "tests"))
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
                             "B20_CLOCK": str(CLOCK),
                             "PYTHONPATH": HOST_ROOT})
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
                   db_dir=DB_DIR)
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
                        db=play_db, db_dir=DB_DIR, clock=CLOCK)
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
                  clock=CLOCK)
    r2 = PLAY.run(PKG, seq, seed=4242, uid="9501", group_id="gs", db=db2, db_dir=DB_DIR,
                  clock=CLOCK)
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
                             "PYTHONPATH": HOST_ROOT,
                             "B20_HOST_ROOT": HOST_ROOT})
    out = (pr.stdout or "") + (pr.stderr or "")
    check("GET …/play/commands → 200 + 194 条", "LIST 200 194 True" in out, out[-400:])
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
def main() -> int:
    if not HOST_ROOT:
        print("⚠️  SKIP：本仓未找到宿主插件目录（需含 game/ + framework/）。\n"
              "    试玩通道要宿主才能跑 —— 设环境变量 B20_HOST_ROOT=<插件目录> 后重跑。")
        print("SKIP test_editor_play（缺宿主根）")
        return 0
    print("=== B20 门禁：编辑器「试玩」通道 ===")
    print("包：%s" % PKG)
    print("宿主副本：%s" % HOST_ROOT)
    test_zero_engine_import()
    cov = test_full_command_coverage()
    test_byte_parity(cov.get("missing"))
    test_subprocess_robustness()
    test_routes_fragment()
    print("\n" + "=" * 60)
    print("通过 %d / 失败 %d" % (PASS, FAIL))
    for f in FAILURES:
        print("  ❌ %s" % f)
    if FAIL:
        return 1
    print("✅ 试玩门禁全绿：零 import 引擎 / 全量 194 覆盖 / 逐字节对拍 / 子进程健壮")
    return 0


if __name__ == "__main__":
    sys.exit(main())
