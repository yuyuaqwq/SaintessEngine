# -*- coding: utf-8 -*-
"""框架编辑器 API 回归：包管理 / 域 CRUD / 校验拦截 / 沙箱试跑（端到端，真起 HTTP）。"""
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
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

    # 2b. ★ 脚手架产出的 apply.py **真的能装配**（不只是"文件存在"）——
    #     往 content/rules/effect_rules.json 写一条，再在子进程里 import + install_engine()，
    #     断言引擎侧规则表非空。为什么必须真跑：`config.set_hook` 对不认识的名字**静默忽略**，
    #     脚手架曾用 `mount(effect_rules=…)` 挂声明表 → "装配看起来成功"但表是空的（效果全不生效且不报错）。
    with open(PK.domain_path(pkg_dir, "effect_rules"), "w", encoding="utf-8") as f:
        json.dump({"sk_probe": {"name": "探针", "period": {"turns": 1}}}, f, ensure_ascii=False)
    probe = ("import json, sys\n"
             f"sys.path.insert(0, {ROOT!r})\n"
             f"sys.path.insert(0, {pkg_dir!r})\n"
             "import content.apply as A\n"
             "A.install_engine()\n"
             "import saintess_engine.config as C\n"
             "print(json.dumps({'rules': len(C.get_effect_rules() or {})}))\n")
    pr = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=180)
    got = {}
    try:
        got = json.loads((pr.stdout or "").strip().splitlines()[-1]) if pr.stdout.strip() else {}
    except Exception:                                     # noqa: BLE001
        got = {}
    check("★ 脚手架 apply.py 装配后引擎规则表非空（声明表不能走 mount，要走 load_game_rules）",
          pr.returncode == 0 and got.get("rules", 0) >= 1,
          f"rc={pr.returncode} got={got} err={(pr.stderr or '')[-200:]}")

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

    # 10. 字段词典（翻译 / 注脚 / 文档深链的数据源）
    st, j = req(base, "GET", "/api/schema/skills")
    check("GET /api/schema/<dom> 可达（该路由历史上写成 3 段，2 段永不匹配 → 修掉）",
          st == 200 and j.get("ok") and bool((j.get("schema") or {}).get("$defs", {}).get("skill")),
          f"{st}")
    st, j = req(base, "GET", "/api/glossary")
    doms = j.get("domains") or {}
    check("GET /api/glossary 200", st == 200 and j.get("ok"), f"{st}")
    check("词典覆盖 7 域 + 通用（含 effect_rules 死字段标注）",
          {"*", "skills", "effect_rules", "passive_proc"} <= set(doms)
          # 断言改为「词典能给死字段打标注」的存在性检查：debuff_scale/dmg_type 已于
          # 2026-09-11 接线（标注变 ✅），挂在具体字段上会随接线再次变红。
          and any("无消费者" in (v.get("note") or "")
                  for v in (doms.get("effect_rules") or {}).values()
                  if isinstance(v, dict)),
          f"{sorted(doms)[:9]}")
    check("词典条目带中文名 + wiki 深链",
          bool(doms["effect_rules"]["cap"]["zh"]) and doms["effect_rules"]["cap"]["wiki"].startswith("wiki:"))
    wid = j.get("widgets") or {}
    check("词典带控件形态（desc → textarea / mech_chance → pct）",
          (wid.get("skills") or {}).get("desc", {}).get("widget") == "textarea"
          and (wid.get("skills") or {}).get("mech_chance", {}).get("widget") == "pct",
          f"{wid.get('skills', {}).get('desc')}")
    check("词典带面板键候选（框架协议）", bool(j.get("panel_keys")), f"{j.get('panel_keys')}")

    # 11. 编辑器内文档（wiki 页 / 搜索 / 源码直链）
    #     先写一条探针（前面几步把条目删干净了，联想需要有数据才有意义）
    req(base, "PUT", "/api/package/t_game/d/skills/sk_hint_probe",
        {"data": {"name": "探针技", "kind": "魔法", "lv": 1, "desc": "联想用。"}})
    st, j = req(base, "GET", "/api/package/t_game/hints")
    check("GET hints（联想数据源）200", st == 200 and j.get("ok"), f"{st}")
    check("hints.refs 给跨域真 key（skills 里有刚写的 sk_hint_probe）",
          "sk_hint_probe" in ((j.get("refs") or {}).get("skills") or []), f"{(j.get('refs') or {}).get('skills')}")
    check("hints.fields 给包内已有取值（skills.kind = 魔法）",
          ((j.get("fields") or {}).get("skills") or {}).get("kind", {}).get("v") == ["魔法"],
          f"{((j.get('fields') or {}).get('skills') or {}).get('kind')}")
    st, j2 = req(base, "GET", "/api/package/nope/hints")
    check("hints：包不存在 → 404", st == 404, f"{st}")
    req(base, "DELETE", "/api/package/t_game/d/skills/sk_hint_probe")

    st, j = req(base, "GET", "/api/wiki/tree")
    check(f"GET /api/wiki/tree 页清单（{len(j.get('pages') or [])} 页）",
          st == 200 and len(j.get("pages") or []) >= 30, f"{st}")
    st, j = req(base, "GET", "/api/wiki/page?path=reference/effect-rules.md")
    check("渲染文档页（表格 + 目录 + 标题）",
          st == 200 and "<h1" in j.get("html", "") and "<table" in j.get("html", "") and len(j.get("toc") or []) > 3,
          f"{st}")
    check("文档里 `file.py:NNN` 变成可点源码链接", 'class="ref-code"' in j.get("html", ""))
    st, j = req(base, "GET", "/api/wiki/search?q=debuff_scale")
    check("文档搜词命中", st == 200 and any(h["path"] == "reference/effect-rules.md" for h in j.get("hits") or []))
    st, j = req(base, "GET", "/api/wiki/code?ref=effects.py:270")
    check("源码直链 → 真实片段", st == 200 and j.get("ok") and j.get("line") == 270, f"{j.get('reason')}")
    st, j = req(base, "GET", "/api/wiki/code?ref=class_mech_proc.py:1895")
    check("跨仓引用明确说「读不到」（不编源码）", st == 200 and not j.get("ok") and j.get("crossrepo"))
    st, j = req(base, "GET", "/api/wiki/page?path=" + urllib.parse.quote("../README.md"))
    check("文档路径逃逸被拦", st == 404 and not j.get("ok"), f"{st}")

    # 12. 只校验不写盘（新建草稿的真实判据）+ 报错中文可读
    st, j = req(base, "POST", "/api/package/t_game/d/skills/sk_draft/check",
                {"data": {"name": "草稿", "kind": "魔法", "lv": 1, "desc": ""}})
    check("check 接口拦下空 desc", st == 200 and not j.get("ok"), f"{st} {j}")
    check("check 报错中文可读（带字段中文名与原因）",
          "不能为空" in ((j.get("friendly") or [{}])[0].get("message") or "")
          and "描述" in ((j.get("friendly") or [{}])[0].get("display") or ""),
          f"{j.get('friendly')}")
    check("check 同时给必填体检（missing 非空）", bool(j.get("missing")), f"{j.get('missing')}")
    st, j = req(base, "GET", "/api/package/t_game/d/skills")
    check("check **不写盘**（域里没多出条目）", j.get("count") == 0, f"{j.get('count')}")
    st, jb = req(base, "PUT", "/api/package/t_game/d/skills/sk_bad2", {"data": {"kind": "魔法"}})
    check("PUT 被拦时也带 friendly（前端不再只弹一句「失败」）",
          st == 422 and bool((jb.get("validation") or {}).get("friendly")), f"{st}")

    # 13. 路径逃逸防护
    st, j = req(base, "GET", "/api/../server.py")
    check("静态路径逃逸被拦", st in (403, 404), f"{st}")

    httpd.shutdown()
    print(f"\n{'-' * 46}\n通过 {PASS} / 失败 {FAIL}")
    for f in FAILURES:
        print("  ❌", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
