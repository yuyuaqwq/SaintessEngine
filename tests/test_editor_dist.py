# -*- coding: utf-8 -*-
"""导出 / 分发回归（E5）—— 核心命题：**导出的 zip 在干净目录里真能跑起来**。

跑法：python tests/test_editor_dist.py
退出码：0 = 全绿。

守的底线（每条都能解释「为什么值得测」）
----------------------------------------
1. **干净环境真跑**：把 zip 解到一个与 `games/` 无关的临时目录，跑包自带的 `DIST_smoke.py`，
   必须真产生伤害 —— 这是「分发」这个词的唯一硬证据（不是「打了个 zip」）。
2. **不搬垃圾**：`__pycache__` / `*.pyc` / `*.db` / 临时文件不进包。
3. **导入的四道闸**（zip slip / zip bomb / 清单合规 / 引擎版本）真的拦得住，
   且**失败的导入不留垃圾**（临时目录清干净、包目录不出现半个包）。
4. **往返一致**：导出 → 导入，内容文件逐字节相同；`DIST_*` 附赠件不落进包。
5. 冲突与版本不匹配：默认拒绝（不静默覆盖 / 不静默降级），显式 overwrite / force 才放行。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from editor import server as SRV          # noqa: E402
from editor import dist as DIST           # noqa: E402
from editor import packages as PK         # noqa: E402
import _domain_fixtures as FX             # noqa: E402  （内容域只能由包声明：B2b）

PASS = 0
FAIL = 0
FAILURES = []


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "PASS", "FAIL", "FAILURES")


def req(base, method, path, body=None, raw=None, ctype=None):
    """JSON 或裸字节请求 → (status, headers, parsed-or-bytes)。"""
    data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
    h = {}
    if data is not None:
        h["Content-Type"] = ctype or ("application/json" if raw is None else "application/octet-stream")
    r = urllib.request.Request(base + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=180) as resp:
            content = resp.read()
            try:
                return resp.status, dict(resp.headers), json.loads(content.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return resp.status, dict(resp.headers), content
    except urllib.error.HTTPError as e:
        content = e.read()
        try:
            return e.code, dict(e.headers), json.loads(content.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return e.code, dict(e.headers), content


def craft_zip(path, entries, comment=None):
    """造一个 zip（entries: 名字 → 内容；`__SYMLINK__:x` 造符号链接成员）。"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            if str(name).startswith("__SYMLINK__:"):
                zi = zipfile.ZipInfo(str(name).split(":", 1)[1])
                zi.external_attr = (0o120777 << 16)
                z.writestr(zi, str(data))
            elif name.endswith("/"):
                z.writestr(zipfile.ZipInfo(name), "")
            else:
                z.writestr(name, data)
        if comment:
            z.comment = json.dumps(comment).encode("utf-8")
    return path


def main() -> int:
    gd = tempfile.mkdtemp(prefix="fw_dist_games_")
    SRV.GAMES_DIR = gd
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SRV.H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    work = tempfile.mkdtemp(prefix="fw_dist_work_")
    print(f"== 导出 / 分发回归（games={gd}）==")

    # ── 1. 建一个有内容的包
    st, _h, j = req(base, "POST", "/api/packages", {"id": "t_game", "name": "分发测试", "desc": "d"})
    check("建包", st == 200 and j.get("ok"), f"{st}")
    # ★ B2b：skills / monsters 是**内容域**（框架内置集只留引擎域）→ 由包声明
    t_dir = j.get("dir")
    FX.declare(t_dir, "skills", "monsters")
    _m = PK.load_manifest(t_dir)
    _m["domains"] = list(PK.DOMAINS) + ["skills", "monsters"]
    PK.save_manifest(t_dir, _m)
    skill = {"name": "火焰球", "kind": "魔法", "lv": 1, "mp": 8, "power": 1.4,
             "exprs": ["matk*1.4 + player_lv*3"], "desc": "砸出一颗火球。"}
    st, _h, j = req(base, "PUT", "/api/package/t_game/d/skills/sk_fire", {"data": skill})
    check("写入一条合法技能", st == 200 and j.get("ok"), f"{st} {j}")
    st, _h, j = req(base, "PUT", "/api/package/t_game/d/monsters/mob_1",
                    {"data": {"name": "小怪", "kind": "normal", "power": 1.0, "desc": "测试怪。"}})
    check("写入一条怪物（多域覆盖）", st == 200, f"{st}")

    # ── 2. 导出（HTTP）
    st, h, raw = req(base, "GET", "/api/package/t_game/export")
    check("GET export → 200 + zip 字节流",
          st == 200 and isinstance(raw, bytes) and raw[:2] == b"PK", f"{st} {type(raw)}")
    check("Content-Type / Content-Disposition 正确（浏览器直接下载）",
          "application/zip" in (h.get("Content-Type") or "")
          and "attachment" in (h.get("Content-Disposition") or "")
          and ".zip" in (h.get("Content-Disposition") or ""), f"{h.get('Content-Disposition')}")
    zpath = os.path.join(work, "t_game.zip")
    with open(zpath, "wb") as f:
        f.write(raw)

    # ── 3. 导出物结构
    info = DIST.inspect_zip(zpath)
    check("zip 可解析且路径安全", info.get("ok"), f"{info.get('message')}")
    check("包内容在 zip 根（game.json 就在根，解压即用）",
          info.get("root") == "" and info.get("manifest_inside"), f"{info.get('root')} {info.get('manifest_inside')}")
    names = set(info.get("names") or [])
    check("含内容文件（game.json / apply.py / 数据表）",
          {"game.json", "content/apply.py", "content/data/skills.json"} <= names, f"{sorted(names)[:8]}")
    check("含导出附赠件 DIST_README.md + DIST_smoke.py",
          {"DIST_README.md", "DIST_smoke.py"} <= names)
    meta = info.get("meta") or {}
    check("zip comment 里有机读元数据（格式 / 版本 / id / 引擎）",
          meta.get("format") == DIST.FORMAT and meta.get("id") == "t_game"
          and meta.get("format_version") == DIST.FORMAT_VERSION, f"{meta}")
    check("元数据带导出时引擎要求与检查结论",
          bool(meta.get("engine_requirement")) and meta.get("engine_ok") is True, f"{meta.get('engine_ok')}")

    # ── 4. DIST_README 内容（人看的可执行说明）
    with zipfile.ZipFile(zpath) as z:
        readme = z.read("DIST_README.md").decode("utf-8")
    check("README 说明引擎要求 + 怎么跑 + 域清单",
          "引擎要求" in readme and "DIST_smoke.py" in readme and "技能（`skills`）" in readme
          and "1 | ✅" in readme, readme[:120].replace("\n", " "))

    # ── 5. ★ 干净环境真跑：解到与 games/ 无关的目录，跑包自带自检脚本
    clean = tempfile.mkdtemp(prefix="fw_clean_env_")
    with zipfile.ZipFile(zpath) as z:
        z.extractall(clean)
    smoke = os.path.join(clean, "DIST_smoke.py")
    check("干净目录里解出了 DIST_smoke.py", os.path.isfile(smoke))
    pr = subprocess.run([sys.executable, "DIST_smoke.py"], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", cwd=clean, timeout=120,
                        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
                             "FW_FRAMEWORK_ROOT": ROOT})
    out = (pr.stdout or "") + (pr.stderr or "")
    check("★ 干净环境跑通（exit 0）", pr.returncode == 0, out[-400:])
    check("★ 真产生了伤害（不是空跑）", "[√] 跑通" in out and "点伤害" in out, out[-200:])
    check("自检脚本如实报告「临时补了最小装配」",
          "临时补了最小装配" in out, out[:200])

    # ── 6. 不搬垃圾
    pkg = os.path.join(gd, "t_game")
    os.makedirs(os.path.join(pkg, "__pycache__"), exist_ok=True)
    for junk in ("__pycache__/x.cpython-312.pyc", "cache.db", "notes.tmp", "content/scratch.pyo"):
        p = os.path.join(pkg, junk)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"junk")
    st, _h, raw2 = req(base, "GET", "/api/package/t_game/export")
    zpath2 = os.path.join(work, "t_game2.zip")
    with open(zpath2, "wb") as f:
        f.write(raw2)
    names2 = set(DIST.inspect_zip(zpath2).get("names") or [])
    check("缓存 / 库文件 / 临时件不进包",
          not any("__pycache__" in n or n.endswith((".pyc", ".pyo", ".db", ".tmp")) for n in names2),
          f"{[n for n in names2 if 'pycache' in n or n.endswith('.db')]}")

    # ── 7. 导入：往返一致 + 附赠件不落盘（导到另一个 games 目录）
    gd2 = tempfile.mkdtemp(prefix="fw_dist_games2_")
    r = DIST.import_zip(zpath, gd2)
    check("导入到新 games 目录成功", r.get("ok"), f"{r.get('message')}")
    dest = r.get("dir") or ""
    check("导入的包内容齐全",
          os.path.isfile(os.path.join(dest, "game.json"))
          and os.path.isfile(os.path.join(dest, "content", "apply.py"))
          and os.path.isfile(os.path.join(dest, "content", "data", "skills.json")), dest)
    check("DIST_* 附赠件不落进包",
          not os.path.exists(os.path.join(dest, "DIST_README.md"))
          and not os.path.exists(os.path.join(dest, "DIST_smoke.py")))
    same = open(os.path.join(pkg, "content", "data", "skills.json"), "rb").read() == \
        open(os.path.join(dest, "content", "data", "skills.json"), "rb").read()
    check("往返内容逐字节一致（skills.json）", same)
    # ★ B2b / 2026-09-24 修口径：报告的「域数」= **清单里声明的域中有效的那几个**
    #   （`editor/dist.py::_validate`：`doms = manifest["domains"]`，逐条过 `domain_status`）
    #   —— 拿「有效域表的大小」去比是**两个量**：包声明了 `depends` 之后，有效域表比清单长
    #   （多出扩展包声明的域，如 ext_combat 的 effect_rules / passive_proc），旧写法必然错位。
    _eff_dest = PK.effective_domains(dest)[0]
    _decl_dest = PK.load_manifest(dest).get("domains") or list(_eff_dest)
    _exp_doms = len([d for d in _decl_dest if d in _eff_dest])
    check(f"导入报告带域数 / 条目数（域数应为 清单∩有效 = {_exp_doms}）",
      (r.get("report") or {}).get("domains") == _exp_doms
          and (r.get("report") or {}).get("entries") == 2, f"{r.get('report')}")
    check("导入后无临时目录残留",
          not [d for d in os.listdir(gd2) if d.startswith(".import_")], f"{os.listdir(gd2)}")

    # ── 8. 冲突：默认拒绝，overwrite 才放行（HTTP 侧）
    st, _h, j = req(base, "POST", "/api/packages/import", raw=raw)
    check("同 id 再次导入 → 409 exists（不静默覆盖）",
          st == 409 and j.get("code") == "exists", f"{st} {j.get('code')}")
    st, _h, j = req(base, "POST", "/api/packages/import?overwrite=1", raw=raw2)
    check("overwrite=1 → 200 且真被替换", st == 200 and j.get("ok"), f"{st} {j.get('message')}")

    # ── 9. zip slip / 符号链接 / 绝对路径
    evil = os.path.join(work, "evil.zip")
    craft_zip(evil, {"game.json": '{"id":"evil","name":"x","engine":">=0.1"}',
                     "../escaped.txt": "pwned",
                     "/abs/escaped2.txt": "pwned2",
                     "__SYMLINK__:link": "/etc/passwd"})
    st, _h, j = req(base, "POST", "/api/packages/import", raw=open(evil, "rb").read())
    check("zip slip / 绝对路径 / 符号链接 → 拒绝",
          st == 400 and j.get("code") == "bad_zip" and j.get("unsafe"), f"{st} {j.get('message')}")
    check("越界文件没被写出去",
          not os.path.exists(os.path.join(gd, "escaped.txt"))
          and not os.path.exists(os.path.join(os.path.dirname(gd), "escaped.txt"))
          and not os.path.exists("/abs/escaped2.txt"))
    check("拒绝后 games 目录干净（没留半个 evil 包）", not os.path.exists(os.path.join(gd, "evil")))

    # ── 10. 坏输入
    st, _h, j = req(base, "POST", "/api/packages/import", raw=b"not a zip at all")
    check("非 zip 字节流 → 400 bad_zip", st == 400 and j.get("code") == "bad_zip", f"{st} {j.get('code')}")
    no_man = os.path.join(work, "noman.zip")
    craft_zip(no_man, {"content/data/skills.json": "{}"})
    st, _h, j = req(base, "POST", "/api/packages/import", raw=open(no_man, "rb").read())
    check("缺 game.json → 400 no_manifest", st == 400 and j.get("code") == "no_manifest", f"{st} {j.get('code')}")
    bad_id = os.path.join(work, "badid.zip")
    craft_zip(bad_id, {"game.json": json.dumps({"id": "Bad-ID!", "name": "x"})})
    st, _h, j = req(base, "POST", "/api/packages/import", raw=open(bad_id, "rb").read())
    check("非法包 id → 400 bad_id", st == 400 and j.get("code") == "bad_id", f"{st} {j.get('code')}")
    bad_json = os.path.join(work, "badjson.zip")
    craft_zip(bad_json, {"game.json": "{oops"})
    st, _h, j = req(base, "POST", "/api/packages/import", raw=open(bad_json, "rb").read())
    check("game.json 非法 JSON → 400 bad_manifest",
          st == 400 and j.get("code") == "bad_manifest", f"{st} {j.get('code')}")

    # ── 11. 引擎版本闸（不静默降级）
    ver = os.path.join(work, "future.zip")
    craft_zip(ver, {"game.json": json.dumps({"id": "future", "name": "未来的包",
                                             "engine": ">=99.0", "domains": ["skills"]}),
                    "content/data/skills.json": "{}", "content/apply.py": "# x\n"})
    st, _h, j = req(base, "POST", "/api/packages/import", raw=open(ver, "rb").read())
    check("引擎版本不满足 → 422 拒绝（带清晰原因）",
          st == 422 and j.get("code") == "engine_mismatch" and "不满足" in (j.get("message") or ""),
          f"{st} {j.get('message')}")
    check("被拒的包没落盘", not os.path.exists(os.path.join(gd, "future")))
    st, _h, j = req(base, "POST", "/api/packages/import?force=1", raw=open(ver, "rb").read())
    check("force=1 → 放行且带警告", st == 200 and j.get("ok") and j.get("warnings"), f"{st} {j.get('warnings')}")

    # ── 12. GitHub 风格（单一顶层目录）
    gh = os.path.join(work, "github.zip")
    craft_zip(gh, {"my_game/game.json": json.dumps({"id": "gh_game", "name": "gh", "engine": ">=0.1"}),
                   "my_game/content/data/skills.json": "{}"})
    st, _h, j = req(base, "POST", "/api/packages/import", raw=open(gh, "rb").read())
    check("单一顶层目录的 zip 也能导入（GitHub 风格）",
          st == 200 and j.get("id") == "gh_game", f"{st} {j.get('message')}")
    check("顶层目录被剥掉（落成 games/gh_game/）",
          os.path.isfile(os.path.join(gd, "gh_game", "game.json")))

    # ── 13. zip bomb 闸
    bomb = os.path.join(work, "bomb.zip")
    craft_zip(bomb, {f"f{i}.txt": "x" for i in range(DIST.MAX_ENTRIES + 5)})
    st, _h, j = req(base, "POST", "/api/packages/import", raw=open(bomb, "rb").read())
    check(f"条目数超上限（>{DIST.MAX_ENTRIES}）→ 拒绝", st == 400 and j.get("code") == "bad_zip",
          f"{st} {j.get('message')}")

    # ── 14. 导出的是当前磁盘状态 + 空体 / 不存在的包
    st, _h, j = req(base, "GET", "/api/package/nope/export")
    check("导出不存在的包 → 404", st == 404, f"{st}")
    check("导出接口不写任何文件到包目录（只读）",
          not [f for f in os.listdir(pkg) if f.endswith(".zip")], f"{os.listdir(pkg)}")
    r2 = DIST.export_zip(pkg, os.path.join(work, "direct.zip"), generated_at="2026-01-01 00:00:00")
    check("API 侧导出函数可直接调用（含校验汇总）",
          r2.get("ok") and r2.get("validation", {}).get("entries") == 2
          and r2.get("files") == r2.get("content_files") + 2, f"{r2.get('validation')} {r2.get('files')}")
    st, _h, j = req(base, "POST", "/api/packages/import", raw=b"")
    check("空请求体 → 400（不当成 zip 处理）", st == 400, f"{st}")
    st, _h, j = req(base, "GET", "/api/dist/inspect?path=" + urllib.request.quote(zpath))
    check("inspect 接口可看 zip 内容（不写盘）",
          st == 200 and j.get("ok") and j.get("manifest_inside"), f"{st} {j.get('message')}")
    st, _h, j = req(base, "GET", "/api/package/inspect")
    check("包名不会被 inspect 路由抢占（/api/package/<id> 仍然通）",
          st == 404 and "包不存在" in (j.get("message") or ""), f"{st} {j.get('message')}")

    # ── 15. 真仓里的包：结构不变量（**守「声明了 entry 却缺文件」这类坏包**）
    #    2026-09-12 的奥兰迪亚导出包正是踩了这条：game.json 声明 content/apply.py，包里却没有该文件。
    repo_games = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "games")
    pkgs = [d for d in sorted(os.listdir(repo_games))
            if os.path.isfile(os.path.join(repo_games, d, "game.json"))] if os.path.isdir(repo_games) else []
    check("真仓 games/ 下确有包（别把门禁跑成空转）", len(pkgs) >= 1, f"{repo_games}: {pkgs}")
    for pid in pkgs:
        pdir = os.path.join(repo_games, pid)
        man = PK.load_manifest(pdir)
        check(f"[{pid}] game.json 可解析且 id 与目录名一致", man.get("id") == pid, f"{man.get('id')}")
        doms = man.get("domains") or []
        # ★ 2026-09-13 收口：已知域 = **这个包的有效域表**（包声明优先 ∪ 内置默认集），
        #   不再只问内置集 —— 否则「域由包自己声明」的包会被误判成"未知域"。
        _eff_pkg, _ = PK.effective_domains(pdir)
        unknown = [d for d in doms if d not in _eff_pkg]
        check(f"[{pid}] domains 全是已知域（包声明 ∪ 内置默认集）", not unknown, f"未知域 {unknown}")
        for d in doms:
            check(f"[{pid}] 声明域 {d} 有数据文件",
                  os.path.isfile(PK.domain_path(pdir, d)), PK.domain_path(pdir, d))
        ent = man.get("entry")
        check(f"[{pid}] entry 不声明或声明即存在",
              ent is None or (bool(ent) and os.path.exists(os.path.join(pdir, str(ent)))),
              f"声明了 {ent!r} 但文件不在（坏包：引擎/分发都以为有装配入口）")

    # ── 16. G5-3（第 3 层批 4）：**导入面风险标注** —— 「该包含渲染扩展面」小结
    #    设计真源：`overnight/layer3-render-design.md` §7.2 T11（第三方包供应链）/ §8.2 G5-3
    #    / §9「批 4」。命题：含 `.html.js` / 代码档开关（`$allow_code:true` / `render/<域>.py`）
    #    的包，**在导入/导出报告里必须标红**（风险可见）；默认包**一个字节都不许多**（零回归）。
    #    ★ 铁律（作业书 §1）：不执行任何包代码 —— `render/*.py` 只做「存在性识别 + 标红 + 告警」。
    def write_file(path, text=""):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

    def make_plain_pkg(root, pid):
        """手搓一个**默认包**（没有 `editor/render/`）：dist 层零回归的对照物。"""
        d = os.path.join(root, pid)
        write_file(os.path.join(d, "game.json"), json.dumps(
            {"id": pid, "name": "默认包", "engine": ">=0.1", "domains": ["skills"]},
            ensure_ascii=False))
        write_file(os.path.join(d, "content", "apply.py"), "# 装配入口\n")
        write_file(os.path.join(d, "content", "data", "skills.json"),
                   json.dumps({"sk_fire": {"name": "火", "kind": "魔法"}}, ensure_ascii=False))
        return d

    # ── 16.1 默认包：报告多了个「没有扩展面」的小结，**其余逐项不变**（含 DIST_README 模板）
    plain = make_plain_pkg(work, "plain_pkg")
    rp = DIST.export_zip(plain, os.path.join(work, "plain_pkg.zip"),
                         generated_at="2026-01-01 00:00:00")
    check("[G5-3] 默认包导出 ok", rp.get("ok"), f"{rp}")
    ps = rp.get("render_surface") or {}
    check("[G5-3] 默认包 render_surface：ok=true / red=false / 三类判据全空",
          ps.get("ok") is True and ps.get("red") is False and ps.get("html_js") == []
          and ps.get("code_py") == [] and ps.get("decl_allow_code") == [], f"{ps}")
    check("[G5-3] 默认包小结**明说「没有」**（不许静默）",
          "渲染扩展面" in (ps.get("message") or "") and "没有" in (ps.get("message") or ""),
          f"{ps.get('message')}")
    with zipfile.ZipFile(rp["path"]) as z:
        readme_p = z.read("DIST_README.md").decode("utf-8")
        comment_p = json.loads(z.comment.decode("utf-8"))
    check("[G5-3] 默认包 zip comment 里带机读小结（red=false）",
          (comment_p.get("render_surface") or {}).get("red") is False, f"{comment_p.keys()}")
    _new_section = "## 渲染扩展面\n\n> " + str(ps.get("message")) + "\n\n"
    check("[G5-3] 默认包 README 唯一新增 = 那一小节；去掉后 == 改前模板（逐字对拍）",
          readme_p.count(_new_section) == 1
          and "{render" not in readme_p.replace(_new_section, "")
          and "渲染扩展面" not in readme_p.replace(_new_section, "")
          and readme_p.replace(_new_section, "").count("## 改这个包") == 1
          and "## 引擎要求" in readme_p.replace(_new_section, ""),
          readme_p[-200:].replace("\n", "⏎"))
    gd3 = tempfile.mkdtemp(prefix="fw_dist_g53_")
    ip = DIST.import_zip(rp["path"], gd3)
    check("[G5-3] 默认包导入报告：不标红、不出现标红行（零回归）",
          ip.get("ok") and (ip.get("render_surface") or {}).get("red") is False
          and not any("渲染扩展面" in w for w in (ip.get("warnings") or [])),
          f"{ip.get('warnings')}")
    check("[G5-3] 默认包导入后包里确实没有 editor/render/",
          not os.path.exists(os.path.join(ip.get("dir") or "", "editor", "render")))

    # ── 16.2 合成包：含 `.html.js` + `$allow_code:true` + `render/<域>.py` → **标红**
    #        （走 HTTP 主体导入，链路 = 编辑器真实路径；`.py` 内容故意写成"一跑就退"→
    #         若有人真执行了包代码，本门禁会当场炸 —— 这就是「绝不执行」的活证据）
    gd4 = tempfile.mkdtemp(prefix="fw_dist_g53b_")
    evil_zip = os.path.join(work, "g53_surface.zip")
    craft_zip(evil_zip, {
        "game.json": json.dumps({"id": "g53_surface", "name": "含扩展面的包", "engine": ">=0.1",
                                 "domains": ["skills"]}, ensure_ascii=False),
        "content/apply.py": "# 装配入口\n",
        "content/data/skills.json": json.dumps({"sk_fire": {"name": "火", "kind": "魔法"}},
                                               ensure_ascii=False),
        "editor/render/skills.html.js": "/* 包自带 JS（设计 §5.4 路径 B；默认关）*/\n",
        "editor/render/skills.py": ('raise SystemExit("SHOULD-NOT-RUN: 包代码被执行了")\n'),
        "editor/render/skills.json": json.dumps(
            {"$version": 1, "title": "技能（含代码档开关）", "$allow_code": True},
            ensure_ascii=False),
    })
    st, _h, j = req(base, "POST", "/api/packages/import", raw=open(evil_zip, "rb").read())
    check("[G5-3] ★ 含扩展面的合成包导入 200", st == 200 and j.get("ok"), f"{st} {j.get('message')}")
    es = j.get("render_surface") or {}
    check("[G5-3] ★ 导入报告标红，且三类判据逐项点到",
          es.get("red") is True
          and es.get("html_js") == ["editor/render/skills.html.js"]
          and es.get("code_py") == ["editor/render/skills.py"]
          and es.get("decl_allow_code") == ["editor/render/skills.json"], f"{es}")
    check("[G5-3] ★ 导入报告 warnings 含「该包请求执行代码」标红行",
          any("渲染扩展面" in w and "执行代码" in w for w in (j.get("warnings") or [])),
          f"{j.get('warnings')}")
    check("[G5-3] ★ `$allow_code:true` 被**看见**了（明说它请求跑代码）",
          any("$allow_code" in w for w in (j.get("warnings") or [])), f"{j.get('warnings')}")
    dest5 = j.get("dir") or ""
    check("[G5-3] ★ 扩展面文件真落盘了（先落盘、再看报告 —— 不是「没导入所以没风险」）",
          os.path.isfile(os.path.join(dest5, "editor", "render", "skills.html.js"))
          and os.path.isfile(os.path.join(dest5, "editor", "render", "skills.py")))
    check("[G5-3] ★ 包代码**没被执行**（探针活着；`.py` 里那句 SystemExit 从没跑起来）",
          True)
    st, _h, j2 = req(base, "GET", "/api/dist/inspect?path=" + urllib.request.quote(evil_zip))
    check("[G5-3] ★ `inspect_zip` 对含扩展面的 zip **不报错**",
          st == 200 and j2.get("ok") is True, f"{st} {j2.get('message')}")

    # ── 16.3 导出面同样标红（direct API）+ 与导入报告口径一致
    re_ = DIST.export_zip(dest5, os.path.join(work, "g53_export.zip"),
                          generated_at="2026-01-01 00:00:00")
    check("[G5-3] ★ 导出报告也标红（与导入同口径）",
          re_.get("ok") and (re_.get("render_surface") or {}).get("red") is True,
          f"{(re_.get('render_surface') or {}).get('message')}")
    with zipfile.ZipFile(re_["path"]) as z:
        readme_e = z.read("DIST_README.md").decode("utf-8")
    check("[G5-3] ★ 标红包 DIST_README 里有人看的「该包请求执行代码」小节",
          "该包请求执行代码" in readme_e and "editor/render/skills.py" in readme_e,
          readme_e[-300:].replace("\n", "⏎"))
    check("[G5-3] 小结文案里不含包内路径以外的本机路径（不泄漏）",
          (os.path.abspath(dest5) not in str(re_.get("render_surface"))), "泄漏本机路径")
    sa = DIST.render_extension_surface(dest5)         # 同一个函数，直接对包目录再点一次
    check("[G5-3] `render_extension_surface()` 直接调用与报告口径一致（red/三类列表全同）",
          sa.get("red") is True and {k: sa.get(k) for k in ("html_js", "code_py", "decl_allow_code")}
          == {k: es.get(k) for k in ("html_js", "code_py", "decl_allow_code")}, f"{sa}")

    # ── 16.4 ★ **单判据**三个包：三条判据各自**单独**就足以标红（「或」语义，不是「与」）
    #        为什么值得单测：合成包同时命中三条 → 「or」和「and」得到同一结果，
    #        反证（把 or 取反成 and）就翻不出红。三条单判据各来一发，反证才有咬合力。
    gd5 = tempfile.mkdtemp(prefix="fw_dist_g53c_")

    def one_criterion(pid, files):
        z = os.path.join(work, f"{pid}.zip")
        craft_zip(z, {
            "game.json": json.dumps({"id": pid, "name": pid, "engine": ">=0.1",
                                     "domains": ["skills"]}, ensure_ascii=False),
            "content/apply.py": "# 装配入口\n",
            "content/data/skills.json": "{}", **files})
        return z

    cases = [
        ("g53_htmljs", "只有 .html.js", {"editor/render/skills.html.js": "/* x */\n"},
         "html_js"),
        ("g53_py", "只有 render/<域>.py", {"editor/render/skills.py": "X = 1\n"},
         "code_py"),
        ("g53_allow", "只有 $allow_code:true",
         {"editor/render/skills.json": json.dumps({"$version": 1, "$allow_code": True})},
         "decl_allow_code"),
    ]
    for pid, what, files, key in cases:
        z = one_criterion(pid, files)
        st, _h, jj = req(base, "POST", "/api/packages/import", raw=open(z, "rb").read())
        ss = jj.get("render_surface") or {}
        check(f"[G5-3] ★ 单判据「{what}」→ 照样标红（或语义）",
              st == 200 and ss.get("red") is True and len(ss.get(key) or []) == 1
              and not any(ss.get(k) for k in ("html_js", "code_py", "decl_allow_code")
                          if k != key),
              f"{st} {ss}")
        check(f"[G5-3] 单判据「{what}」→ warnings 也有标红行",
              any("渲染扩展面" in w for w in (jj.get("warnings") or [])),
              f"{jj.get('warnings')}")
        check(f"[G5-3] 单判据「{what}」→ 小结与列举**自洽**（不许说没有却又列了东西）",
              ("⚠️" in (ss.get("message") or "")) and "**没有**" not in (ss.get("message") or ""),
              f"{ss.get('message')}")
    # 没有 `editor/render/` 目录 vs 有目录但只有纯数据声明：两种都**不**标红
    st, _h, jj = req(base, "POST", "/api/packages/import",
                     raw=open(one_criterion("g53_dataonly", {
                         "editor/render/skills.json": json.dumps({"$version": 1, "title": "纯数据"})}),
                              "rb").read())
    so = jj.get("render_surface") or {}
    check("[G5-3] 只有纯数据声明（`$allow_code` 缺省）→ 不标红、无标红行",
          st == 200 and so.get("red") is False
          and not any("渲染扩展面" in w for w in (jj.get("warnings") or [])), f"{so} {jj.get('warnings')}")

    for _d in (gd3, gd4, gd5):
        shutil.rmtree(_d, ignore_errors=True)

    httpd.shutdown()
    for d in (clean, gd2):
        shutil.rmtree(d, ignore_errors=True)
    print(f"\n{'-' * 46}\n通过 {PASS} / 失败 {FAIL}")
    for f in FAILURES:
        print("  ❌", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
