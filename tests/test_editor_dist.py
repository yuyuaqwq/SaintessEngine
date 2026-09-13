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


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name} {detail}")
        print(f"  ❌ {name} {detail}")


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
    # ★ B2b：域数 = **该包的有效域表**（内置 8 引擎域 ∪ 包声明的内容域），不再等于内置集
    check(f"导入报告带域数 / 条目数（域数应为 {len(PK.effective_domains(dest)[0])}）",
      (r.get("report") or {}).get("domains") == len(PK.effective_domains(dest)[0])
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

    httpd.shutdown()
    for d in (clean, gd2):
        shutil.rmtree(d, ignore_errors=True)
    print(f"\n{'-' * 46}\n通过 {PASS} / 失败 {FAIL}")
    for f in FAILURES:
        print("  ❌", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
