# -*- coding: utf-8 -*-
"""编辑器「试玩」（父进程侧）—— 只起子进程，**绝不 import saintess_engine**。

与 `editor/simulate.py` 同款三条理由（装配副作用 / 隔离兜底 / 循环导入），另加一条：
试玩要在子进程里注入**宿主面**（`content/**` 的宿主替身口），那是进程级全局登记，
跑一次就污染编辑器进程。

提供给编辑器 / 测试的 API
------------------------
    discover(pkg_dir=None, host_root=None) -> dict
                                            # 三个根；host_root="" ⇒ 显式无宿主（试玩正常态）
    list_commands(pkg_dir, ...) -> dict     # 包内全部指令声明（194 条 key + 正则/描述/守卫）
    audit(pkg_dir, ...) -> dict             # 覆盖率审计：声明 / 处理器 / 可解析（不跑 handler）
    run(pkg_dir, commands, *, seed, uid, group_id, ...) -> dict
                                            # 跑一条命令序列（子进程），返回逐条结果 + 摘要
    stream(pkg_dir, commands, ...) -> iterator
                                            # 同上，但逐行 yield（UI 滚动区用）

子进程协议（见 `play_worker.py`）：stdin 一个 JSON、stdout 每行 `__B20_PLAY__` + JSON。
崩溃 → 明确报错（`stage="crash"`，带 stdout/stderr 尾巴）；超时 → 掐死并报 `stage="timeout"`。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FRAMEWORK_ROOT = os.path.dirname(HERE)
WORKER = os.path.join(HERE, "play_worker.py")
MARKER = "__B20_PLAY__"
TIMEOUT = int(os.environ.get("B20_PLAY_TIMEOUT", os.environ.get("FW_SIM_TIMEOUT", "120")))

#: QQ 宿主插件目录候选（B20 工作副本在 `<workspace>/work2`；真实部署是 qqbot 插件目录）
HOST_ROOT_ENVS = ("B20_HOST_ROOT", "GWEN_PLUGIN_ROOT", "DRAGONFALL_ROOT")


def discover(pkg_dir: str = "", host_root=None, engine_root: str = "") -> dict:
    """定位三个根：引擎（`saintess_engine` 所在）/ 宿主插件（`game/` 的父目录）/ 游戏包。

    包目录缺省在引擎仓的 `games/<id>` 里找第一个带 `game.json` 的；
    宿主目录缺省读环境变量，再退到「引擎仓同级的 `work2`」（B20 工作副本布局）。

    ★ `host_root` 三态（T7 第 3 轮 · 试玩脱宿主）：
      · `None`（缺省）→ 自动：环境变量 → `work2` 兜底；
      · `""` → **显式「无宿主」**（试玩链的正常态：壳 = 引擎 `PlayShell`）；
      · 非空 → 用给的目录（**只**为「与 QQ 侧逐字节对拍」）。
    """
    engine_root = engine_root or (FRAMEWORK_ROOT if os.path.isdir(
        os.path.join(FRAMEWORK_ROOT, "saintess_engine")) else "")
    if host_root is None:
        host_root = next((os.environ.get(k) for k in HOST_ROOT_ENVS
                          if os.environ.get(k)), "")
        if not host_root:
            cand = os.path.join(os.path.dirname(FRAMEWORK_ROOT), "work2")
            if os.path.isdir(os.path.join(cand, "game")):
                host_root = cand
    if not pkg_dir:
        games = os.path.join(engine_root or FRAMEWORK_ROOT, "games")
        cands = []
        if os.path.isdir(games):
            for name in sorted(os.listdir(games)):
                cand = os.path.join(games, name)
                if os.path.isfile(os.path.join(cand, "game.json")):
                    cands.append(cand)
        # 优先带**指令表**的包（试玩要跑命令；纯数据包没有 content/commands.py）
        with_cmds = [c for c in cands if os.path.isfile(os.path.join(c, "content", "commands.py"))]
        pkg_dir = (with_cmds or cands or [""])[0]
    return {"pkg_dir": pkg_dir, "host_root": host_root, "engine_root": engine_root,
            "worker": WORKER, "timeout": TIMEOUT}


def _invoke(payload: dict) -> dict:
    """把 payload 喂给 worker，解析 stdout 的 marker 行。**唯一**起子进程的地方。"""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
           "FW_FRAMEWORK_ROOT": payload.get("engine_root") or FRAMEWORK_ROOT,
           "FW_PKG_DIR": payload.get("pkg_dir") or "",
           "B20_HOST_ROOT": payload.get("host_root") or ""}
    try:
        pr = subprocess.run([sys.executable, WORKER], input=json.dumps(payload),
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", env=env, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"ok": False, "stage": "timeout",
                "message": "试玩超时（%ss）—— 命令序列太长或某条命令卡住" % TIMEOUT,
                "rows": []}
    rows = []
    tail = None
    for line in (pr.stdout or "").splitlines():
        if not line.startswith(MARKER):
            continue
        try:
            obj = json.loads(line[len(MARKER):])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("stage") in (
                "done", "audit", "load", "engine", "host", "version", "crash"):
            tail = obj
        else:
            rows.append(obj)
    if tail is None:
        return {"ok": False, "stage": "crash",
                "message": "试玩子进程未返回结果（worker 崩溃或 stdout 被吞）",
                "rows": rows, "stdout": (pr.stdout or "")[-3000:],
                "stderr": (pr.stderr or "")[-3000:]}
    tail = dict(tail)
    tail.setdefault("rows", rows)
    return tail


def list_commands(pkg_dir: str = "", **kw) -> dict:
    """包内全部指令**声明**（平台无关元数据）—— 不跑子进程也能列（只读 JSON）。

    返回 `{"ok":True,"count":194,"commands":[{"key","desc","category","usage","guards","patterns"}]}`。
    """
    cfg = discover(pkg_dir, kw.get("host_root"), kw.get("engine_root", ""))
    path = os.path.join(cfg["pkg_dir"] or "", "content", "data", "commands.json")
    if not os.path.isfile(path):
        return {"ok": False, "stage": "load", "message": "读不到指令声明：%s" % path,
                "commands": []}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for key, spec in sorted((data or {}).items()):
        spec = spec if isinstance(spec, dict) else {}
        out.append({"key": key, "desc": spec.get("desc") or "",
                    "category": spec.get("category") or "",
                    "usage": spec.get("usage") or "",
                    "guards": list(spec.get("guards") or []),
                    "patterns": list(spec.get("patterns") or [])})
    return {"ok": True, "stage": "list", "count": len(out), "pkg_dir": cfg["pkg_dir"],
            "commands": out}


def audit(pkg_dir: str = "", **kw) -> dict:
    """覆盖率审计（子进程）：逐 key 回报「有处理器 / 可解析」——不跑 handler。"""
    cfg = discover(pkg_dir, kw.get("host_root"), kw.get("engine_root", ""))
    payload = {**cfg, "audit": True, "db": kw.get("db") or ""}
    payload.pop("worker", None)
    payload.pop("timeout", None)
    return _invoke(payload)


def run(pkg_dir: str = "", commands=None, *, seed=1, uid="u1", group_id="g1",
        db="", clock=None, **kw) -> dict:
    """跑一条命令序列（子进程）。`commands` = 消息原文列表（含 @ 前缀/参数）。

    `clock`（unix 秒）给了就把包内墙钟读取点钉死到该时刻 —— 对拍/复现用（见 worker 头注）。
    """
    cfg = discover(pkg_dir, kw.get("host_root"), kw.get("engine_root", ""))
    payload = {**cfg, "commands": [str(c) for c in (commands or [])],
               "seed": seed, "uid": str(uid), "group_id": str(group_id), "db": db or "",
               "db_dir": kw.get("db_dir") or os.path.join(os.path.dirname(FRAMEWORK_ROOT), "db", "play")}
    if clock is not None:
        payload["clock"] = clock
    payload.pop("worker", None)
    payload.pop("timeout", None)
    payload["timeout"] = TIMEOUT
    return _invoke(payload)


def stream(pkg_dir: str = "", commands=None, **kw):
    """逐行 yield 的版本（UI 用）：先 `start`，再每条 `cmd`，最后 `done` / `error`。"""
    result = run(pkg_dir, commands, **kw)
    yield {"type": "start", "stage": result.get("stage"), "ok": result.get("ok")}
    for row in result.get("rows") or []:
        yield {"type": "cmd", **row}
    yield {"type": "done" if result.get("ok") else "error", **{
        k: v for k, v in result.items() if k != "rows"}}


def main(argv=None) -> int:
    """命令行入口（调试用）：`python editor/play.py 注册 试玩 男 角色 背包`。"""
    args = list(sys.argv[1:] if argv is None else argv)
    pkg = os.environ.get("B20_PKG_DIR", "")
    seed = 1
    if args and args[0].startswith("--pkg="):
        pkg = args.pop(0).split("=", 1)[1]
    if args and args[0].startswith("--seed="):
        seed = int(args.pop(0).split("=", 1)[1])
    if not args:
        print(json.dumps(discover(pkg), ensure_ascii=False, indent=2))
        return 0
    res = run(pkg, args, seed=seed)
    for row in res.get("rows") or []:
        print(">>> %s" % row.get("text"))
        for seg in row.get("segments") or []:
            print(seg)
        if not row.get("ok"):
            print("!! %s" % row.get("error"))
    print(json.dumps({k: v for k, v in res.items() if k != "rows"},
                     ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
