# -*- coding: utf-8 -*-
"""框架编辑器 API 回归：包管理 / 域 CRUD / 校验拦截 / 沙箱试跑（端到端，真起 HTTP）。"""
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from editor import server as SRV          # noqa: E402
from editor import packages as PK         # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name} {detail}")
        print(f"  ❌ {name} {detail}")


def req(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method,
                               headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw}


def main():
    import tempfile
    gd = tempfile.mkdtemp(prefix="fw_editor_games_")
    SRV.GAMES_DIR = gd
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SRV.H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    print(f"== 框架编辑器 API 回归（临时包目录 {gd}）==")

    # 1. 域注册表 / 静态页
    st, j = req(base, "GET", "/api/domains")
    check("GET /api/domains 200", st == 200 and j.get("ok"), f"{st} {j}")
    check(f"域齐全（{len(j.get('domains') or [])} 个）", len(j.get("domains") or []) >= 7)
    r = urllib.request.urlopen(base + "/", timeout=10)
    html = r.read().decode("utf-8")
    # 单页应用外壳：域栏（工作台导航）+ 命令面板 + 样式表接线
    check("GET / 返回单页应用（工作台外壳）",
          r.status == 200 and 'id="rail"' in html and 'id="paletteOverlay"' in html
          and "/app.css" in html)

    # 2. 建档（脚手架）
    st, j = req(base, "POST", "/api/packages", {"id": "t_game", "name": "测试游戏",
                                                "desc": "回归用"})
    check("POST /api/packages 建包", st == 200 and j.get("ok"), f"{st} {j}")
    pkg_dir = j.get("dir")
    check("脚手架落了 content/apply.py", os.path.exists(os.path.join(pkg_dir, "content", "apply.py")))
    check("脚手架落了 7 个域的 JSON", all(
        os.path.exists(PK.domain_path(pkg_dir, d)) for d in PK.DOMAINS))

    # 3. 非法 id 被拒
    st, j = req(base, "POST", "/api/packages", {"id": "Bad-ID!", "name": "x"})
    check("非法包 id → 400", st == 400 and not j.get("ok"), f"{st}")

    # 4. 条目：新建（合法）→ 读回 → 列表
    good = {"name": "火焰球", "kind": "魔法", "lv": 1, "mp": 8, "power": 1.4,
            "exprs": ["matk*1.4 + player_lv*3"], "desc": "砸出一颗火球。"}
    st, j = req(base, "PUT", "/api/package/t_game/d/skills/sk_fire_ball", {"data": good})
    check("PUT 合法技能 → 200", st == 200 and j.get("ok"), f"{st} {j}")
    st, j = req(base, "GET", "/api/package/t_game/d/skills/sk_fire_ball")
    check("GET 单条读回一致", st == 200 and j["data"]["name"] == "火焰球", f"{st}")
    st, j = req(base, "GET", "/api/package/t_game/d/skills")
    check("GET 条目列表含新条目", j.get("count") == 1, f"{j}")
    check("域状态无违规", (j.get("status") or {}).get("ok") is True)

    # 5. 脏数据被校验拦下（占位符占位：用 schema 强制字段）
    st, jb = req(base, "PUT", "/api/package/t_game/d/skills/sk_bad", {"data": {"kind": "魔法"}})
    check("缺必填字段 → 422 且未写入", st == 422 and not jb.get("ok"), f"{st} {jb}")
    check("422 带字段级定位", bool(((jb.get("validation") or {}).get("errors"))), f"{jb}")
    st, j = req(base, "GET", "/api/package/t_game/d/skills/sk_bad")
    check("被拦的条目确实没落盘", st == 404, f"{st}")

    # 6. 全包校验
    st, j = req(base, "POST", "/api/package/t_game/validate")
    check("全包校验（当前无违规）", st == 200 and j.get("ok") is True, f"{st} {j}")

    # 7. 包清单
    st, j = req(base, "PUT", "/api/package/t_game/manifest",
                {"manifest": {"name": "改名了", "desc": "d", "engine": ">=0.1"}})
    check("PUT manifest → 200", st == 200 and j["manifest"]["name"] == "改名了", f"{st}")
    st, j = req(base, "GET", "/api/package/t_game")
    check("包概览反映改名", j["manifest"]["name"] == "改名了")

    # 8. 沙箱试跑：真起引擎（子进程）
    st, j = req(base, "POST", "/api/package/t_game/simulate", {
        "skill": good, "skill_lv": 1, "seed": 1,
        "attacker": {"class_name": "法师", "level": 20},
        "defender": {"def": 60, "mdef": 60, "hp": 10_000_000},
    })
    ok = st == 200 and j.get("ok")
    check("沙箱试跑成功（子进程跑引擎）", ok, f"{st} {j.get('message') or j.get('stage')}")
    if ok:
        check(f"产生真实伤害（{j.get('damage')}）", (j.get("damage") or 0) > 0)
        check("返回战斗日志", len(j.get("logs") or []) > 0)
        check("返回事件", len(j.get("events") or []) > 0)
        check("目标确实掉血", j["hp"]["target_after"] < j["hp"]["target_before"])

    # 9. 删除
    st, j = req(base, "DELETE", "/api/package/t_game/d/skills/sk_fire_ball")
    check("DELETE 条目 → 200", st == 200 and j.get("ok"), f"{st}")
    st, j = req(base, "GET", "/api/package/t_game/d/skills")
    check("删除后条目数归零", j.get("count") == 0, f"{j}")

    # 10. 路径逃逸防护
    st, j = req(base, "GET", "/api/../server.py")
    check("静态路径逃逸被拦", st in (403, 404), f"{st}")

    httpd.shutdown()
    print(f"\n{'-' * 46}\n通过 {PASS} / 失败 {FAIL}")
    for f in FAILURES:
        print("  ❌", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
