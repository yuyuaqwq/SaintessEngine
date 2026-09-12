#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""框架编辑器 —— 后端（Python stdlib http.server，零第三方依赖）。

    python editor/server.py                 # 默认 http://127.0.0.1:8766
    python editor/server.py --port 9000
    python editor/server.py --games-dir /path/to/games

作用：**造游戏**（不是改某个游戏的数据）。选项卡式界面，一个模块一个 tab：
技能 / 职业 / 怪物 / 词条 / 物品 / 声明表 / 被动声明 / 试跑 / 包设置。

API
---
    GET    /                              → 单页应用
    GET    /api/domains                   → 域注册表（tab 列表用）
    GET    /api/packages                  → 游戏包列表
    POST   /api/packages                  → 新建包（脚手架）
    GET    /api/package/<id>              → 包概览（manifest + 各域条目数/校验状态）
    GET    /api/package/<id>/d/<dom>            → 条目列表
    GET    /api/package/<id>/d/<dom>/<key>      → 单条 + schema + 校验结果
    GET    /api/package/<id>/d/maps/<key>/graph  → 拓扑视图（引擎同一份派生代码算）
    PUT    /api/package/<id>/d/<dom>/<key>      → 保存（**先校验，过后才落盘**）
    DELETE /api/package/<id>/d/<dom>/<key>      → 删除
    POST   /api/package/<id>/validate           → 全包校验
    GET    /api/schema/<dom>              → 域 schema 原文
    GET    /api/actions                   → 机制动作清单（AST 扫源码；引擎内置 + 包内）
    GET    /api/actions?pkg=<id>          → 同上，额外扫该游戏包的动作
    GET    /api/actions?fresh=1           → 跳过缓存重扫（改了 mech/ 代码后立刻可见）
    GET    /api/glossary                  → 字段词典（中文名 / 注脚 / wiki 深链）
    GET    /api/package/<id>/hints        → 编辑提示（跨域引用候选 + 包内已有取值/键，供联想）
    GET    /api/wiki/tree                 → 文档页清单（左导航）
    GET    /api/wiki/page?path=<rel>      → 渲染后的文档页（md → html + 目录）
    GET    /api/wiki/search?q=<词>        → 跨页搜词（配字段时找语义）
    GET    /api/wiki/code?ref=x.py:NN     → 文档里的 `file.py:NNN` → 真实源码片段
    GET    /api/package/<id>/export       → 导出游戏包 zip（分发；附 DIST_README/DIST_smoke）
    GET    /api/dist/inspect?path=<zip>   → 看 zip 里有什么（不导入、不写盘）
    POST   /api/package/<id>/simulate     → 沙箱试跑（子进程跑引擎，见 simulate.py）
    POST   /api/package/<id>/d/<dom>/check → **只校验不写盘**（新建草稿用；带中文可读报错）
    POST   /api/packages/import?overwrite=1&force=1
                                          → 导入 zip（裸字节流；四道闸见 editor/dist.py）

安全：只绑 127.0.0.1；只读写游戏包目录；静态文件做路径逃逸防护。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from editor import actions as AC     # noqa: E402
from editor import dist as DIST      # noqa: E402
from editor import glossary as GL    # noqa: E402
from editor import hints as HN       # noqa: E402
from editor import packages as PK    # noqa: E402
from editor import space_view as SV  # noqa: E402
from editor import validate as VD    # noqa: E402
from editor import wiki as WK        # noqa: E402

EDITOR_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(EDITOR_DIR, "web")
GAMES_DIR = None                      # --games-dir 覆盖
MAX_UPLOAD = 64 * 1024 * 1024         # 导入 zip 上限（防 OOM）

_CT = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
       ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
       ".svg": "image/svg+xml", ".ico": "image/x-icon"}


class H(BaseHTTPRequestHandler):
    server_version = "FrameworkEditor/0.1"

    # ---------- 基础 ----------
    def log_message(self, fmt, *a):
        sys.stderr.write("  · " + (fmt % a) + "\n")

    def _send(self, code: int, body, ctype="application/json; charset=utf-8", headers=None):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionError, OSError):
            # 客户端提前断开（刷新 / 超时 / 下载取消 / 导入中途取消）—— 不是服务器错误，
            # 否则会在日志里冒成 500 噪声，也会掩盖真正的异常。
            pass

    def _err(self, code: int, msg: str, **extra):
        self._send(code, {"ok": False, "message": msg, **extra})

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _raw_body(self, limit: int = MAX_UPLOAD):
        """裸字节流请求体（导入 zip 用）。超限 / 空体 → None。"""
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > limit:
            return None
        buf, left = b"", n
        while left > 0:
            chunk = self.rfile.read(min(left, 1 << 16))
            if not chunk:
                break
            buf += chunk
            left -= len(chunk)
        return buf or None

    # ---------- 路由 ----------
    def do_GET(self):
        p = urlparse(self.path)
        self._query = p.query                      # 供 _api_get 读查询串
        parts = [unquote(x) for x in p.path.strip("/").split("/") if x]
        try:
            if not parts:
                return self._static("index.html")
            if parts[0] != "api":
                return self._static("/".join(parts))
            return self._api_get(parts[1:])
        except Exception:
            return self._err(500, "服务器内部错误", traceback=traceback.format_exc())

    def do_POST(self):
        return self._mutate("POST")

    def do_PUT(self):
        return self._mutate("PUT")

    def do_DELETE(self):
        return self._mutate("DELETE")

    def _api_get(self, parts: list):
        if parts == ["domains"]:
            return self._send(200, {"ok": True, "domains": [
                {"id": k, **{x: v[x] for x in ("label", "icon", "kind")},
                 "has_schema": bool(v.get("schema"))}
                for k, v in PK.DOMAINS.items()]})
        if parts == ["packages"]:
            return self._send(200, {"ok": True, "packages": PK.list_packages(GAMES_DIR),
                                    "games_dir": PK.ensure_games_dir(GAMES_DIR)})
        if len(parts) == 2 and parts[0] == "package":
            d = PK.resolve_package(parts[1], GAMES_DIR)
            if not d:
                return self._err(404, f"包不存在：{parts[1]}")
            return self._send(200, {"ok": True, "dir": d, **PK.package_overview(d)})
        # 导出 zip（分发用；浏览器直接下载）
        if len(parts) == 3 and parts[0] == "package" and parts[2] == "export":
            d = PK.resolve_package(parts[1], GAMES_DIR)
            if not d:
                return self._err(404, f"包不存在：{parts[1]}")
            data, fn = DIST.export_bytes(d)
            if data is None:
                return self._err(500, fn)
            return self._send(200, data, "application/zip",
                              {"Content-Disposition": f'attachment; filename="{fn}"',
                               "X-Export-Bytes": str(len(data))})
        # 看一眼 zip 里有什么（不导入、不写盘）
        # ⚠ 用 /api/dist/inspect 而不是 /api/package/inspect —— 后者会和「把 inspect 当包 id」
        #   的 /api/package/<id> 路由撞车（包名是合法的，不能占）。
        if len(parts) == 2 and parts[0] == "dist" and parts[1] == "inspect":
            from urllib.parse import parse_qs
            q = parse_qs(getattr(self, "_query", ""))
            return self._send(200, {"ok": True, **DIST.inspect_zip((q.get("path") or [""])[0])})
        # 编辑提示：跨域引用候选 + 包内已有取值/键（联想数据源，内容驱动、无框架词汇）
        if len(parts) == 3 and parts[0] == "package" and parts[2] == "hints":
            d = PK.resolve_package(parts[1], GAMES_DIR)
            if not d:
                return self._err(404, f"包不存在：{parts[1]}")
            return self._send(200, {"ok": True, **HN.flatten_for_ui(HN.build(d))})
        if len(parts) in (2, 3) and parts[0] == "schema":
            # GET /api/schema/<dom>  （历史上这里写成 `len(parts)==3` → 该路由**从未匹配上**，
            # 因为没人调用所以一直没暴露；新建草稿要按 domain 取 schema，故修成 2 段可达）
            s = VD.load_schema(parts[1])
            return self._send(200, {"ok": bool(s), "schema": s})
        if parts == ["actions"]:
            from urllib.parse import parse_qs
            q = parse_qs(getattr(self, "_query", ""))
            pkg_id = (q.get("pkg") or [""])[0]
            fresh = (q.get("fresh") or ["0"])[0] not in ("", "0", "false")
            pkg_dir = PK.resolve_package(pkg_id, GAMES_DIR) if pkg_id else None
            return self._send(200, AC.inventory(pkg_dir, use_cache=not fresh))
        if parts == ["glossary"]:
            return self._send(200, {"ok": True, "domains": GL.all_entries(),
                                    "groups": GL.all_groups(),
                                    "widgets": GL.all_widgets(),
                                    "panel_keys": GL.PANEL_KEYS})
        if len(parts) >= 2 and parts[0] == "wiki":
            from urllib.parse import parse_qs
            q = parse_qs(getattr(self, "_query", ""))
            if parts[1] == "tree":
                return self._send(200, {"ok": True, "pages": WK.tree(),
                                        "groups": [{"id": g, "label": l} for g, l in WK.GROUPS]})
            if parts[1] == "page":
                rel = (q.get("path") or [""])[0]
                pg = WK.page(rel)
                if not pg:
                    return self._err(404, f"文档不存在：{rel}")
                return self._send(200, {"ok": True, **pg})
            if parts[1] == "search":
                return self._send(200, {"ok": True, "hits": WK.search((q.get("q") or [""])[0])})
            if parts[1] == "code":
                return self._send(200, {"ok": True, **WK.code_ref((q.get("ref") or [""])[0])})
            return self._err(404, "未知 wiki 接口")
        # maps 域的拓扑视图：节点/连边/深度/审计由**引擎同一份派生代码**算（editor/space_view.py）
        if (len(parts) == 6 and parts[0] == "package" and parts[2] == "d"
                and parts[5] == "graph"):
            d = PK.resolve_package(parts[1], GAMES_DIR)
            if not d:
                return self._err(404, f"包不存在：{parts[1]}")
            dom = parts[3]
            if dom not in PK.DOMAINS:
                return self._err(404, f"未知域：{dom}")
            data = PK.read_json(PK.domain_path(d, dom), {})
            out = SV.build_file(data if isinstance(data, dict) else {}, parts[4])
            return self._send(200 if out.get("ok") else 422, out)
        if len(parts) >= 4 and parts[0] == "package" and parts[2] == "d":
            d = PK.resolve_package(parts[1], GAMES_DIR)
            if not d:
                return self._err(404, f"包不存在：{parts[1]}")
            dom = parts[3]
            if dom not in PK.DOMAINS:
                return self._err(404, f"未知域：{dom}")
            if len(parts) == 4:
                return self._send(200, {"ok": True, **PK.list_entries(d, dom),
                                        "status": PK.domain_status(d, dom)})
            if len(parts) == 5:
                key = parts[4]
                e = PK.get_entry(d, dom, key)
                if e is None:
                    return self._err(404, f"条目不存在：{key}")
                return self._send(200, {"ok": True, "key": key, "data": e,
                                        "errors": VD.validate_entry(dom, e),
                                        "schema": VD.load_schema(dom)})
        return self._err(404, "未知接口")

    def _mutate(self, method: str):
        p = urlparse(self.path)
        self._query = p.query                      # 供查询串（overwrite / force）
        parts = [unquote(x) for x in p.path.strip("/").split("/") if x]
        try:
            # ⚠️ 导入是**裸字节流**端点，必须在 `_body()` 之前处理 ——
            #    `_body()` 会按 Content-Length 把请求体读空，之后 `_raw_body()` 永远等不到数据
            #    （实测：不这么写，导入请求会挂到客户端超时）。
            #    四道闸见 editor/dist.py：zip slip / zip bomb / 清单合规 / 引擎版本。
            if method == "POST" and parts == ["api", "packages", "import"]:
                from urllib.parse import parse_qs
                import tempfile
                q = parse_qs(self._query or "")
                raw = self._raw_body()
                if not raw:
                    return self._err(400, "请求体需为 zip 字节流（Content-Type: application/zip，"
                                          f"且不超过 {MAX_UPLOAD // 1048576}MB）")
                fd, tmp = tempfile.mkstemp(prefix="fw_import_", suffix=".zip")
                try:
                    with os.fdopen(fd, "wb") as f:
                        f.write(raw)
                    rep = DIST.import_zip(
                        tmp, GAMES_DIR,
                        overwrite=(q.get("overwrite") or ["0"])[0] not in ("", "0", "false"),
                        force=(q.get("force") or ["0"])[0] not in ("", "0", "false"))
                finally:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                if rep.get("ok"):
                    return self._send(200, rep)
                code = {"exists": 409, "engine_mismatch": 422,
                        "bad_zip": 400, "no_manifest": 400,
                        "bad_manifest": 400, "bad_id": 400, "unsafe": 400}.get(rep.get("code"), 400)
                return self._send(code, rep)
            body = self._body()
            if method == "POST" and parts == ["api", "packages"]:
                try:
                    r = PK.create_package(body.get("id", ""), body.get("name", ""),
                                          body.get("desc", ""), body.get("domains"),
                                          GAMES_DIR)
                except ValueError as e:
                    return self._err(400, str(e))
                return self._send(200, {"ok": True, **r})
            if len(parts) >= 3 and parts[0] == "api" and parts[1] == "package":
                d = PK.resolve_package(parts[2], GAMES_DIR)
                if not d:
                    return self._err(404, f"包不存在：{parts[2]}")
                # /api/package/<id>/manifest  （PUT：改包清单）
                if len(parts) == 4 and parts[3] == "manifest" and method == "PUT":
                    m = body.get("manifest")
                    if not isinstance(m, dict):
                        return self._err(400, "请求体需为 {\"manifest\": {...}}")
                    cur = PK.load_manifest(d)
                    cur.update({k: m[k] for k in ("name", "desc", "engine") if k in m})
                    PK.save_manifest(d, cur)
                    return self._send(200, {"ok": True, "manifest": cur})
                # /api/package/<id>/validate
                if len(parts) == 4 and parts[3] == "validate" and method == "POST":
                    rep = []
                    for dom in PK.load_manifest(d).get("domains") or list(PK.DOMAINS):
                        st = PK.domain_status(d, dom)
                        if not st["ok"]:
                            rep.append({"domain": dom, "invalid": st["invalid"]})
                    return self._send(200, {"ok": not rep, "problems": rep})
                # /api/package/<id>/simulate
                if len(parts) == 4 and parts[3] == "simulate" and method == "POST":
                    from editor import simulate as SIM
                    return self._send(200, SIM.run(d, body))
                # /api/package/<id>/d/<dom>/[<key>]/check  —— 只校验、不写盘（新建草稿用）
                if len(parts) in (6, 7) and parts[3] == "d" and parts[-1] == "check" and method == "POST":
                    dom = parts[4]
                    if dom not in PK.DOMAINS:
                        return self._err(404, f"未知域：{dom}")
                    data = body.get("data")
                    if not isinstance(data, dict):
                        return self._err(400, "请求体需为 {\"data\": {...}}")
                    rep = _check_report(dom, data)
                    if len(parts) == 7:
                        rep["key"] = parts[5]
                    return self._send(200, rep)
                # /api/package/<id>/d/<dom>/[key]
                if len(parts) >= 5 and parts[3] == "d":
                    dom = parts[4]
                    if dom not in PK.DOMAINS:
                        return self._err(404, f"未知域：{dom}")
                    if len(parts) == 5 and method == "PUT":
                        return self._err(405, "缺少条目 key")
                    if len(parts) == 6 and method == "PUT":
                        key = parts[5]
                        data = body.get("data")
                        if not isinstance(data, dict):
                            return self._err(400, "请求体需为 {\"data\": {...}}")
                        errs = VD.validate_entry(dom, data)
                        if errs:
                            return self._err(422, "校验未通过，未写入",
                                             validation={"key": key, "errors": errs,
                                                         "friendly": GL.friendly(dom, errs),
                                                         "missing": _missing(dom, data)})
                        PK.put_entry(d, dom, key, data)
                        return self._send(200, {"ok": True, "key": key,
                                                "domain": dom,
                                                "count": PK.list_entries(d, dom)["count"]})
                    if len(parts) == 6 and method == "DELETE":
                        ok = PK.delete_entry(d, dom, parts[5])
                        return self._send(200 if ok else 404,
                                          {"ok": ok, "key": parts[5], "domain": dom})
            return self._err(404, "未知接口")
        except Exception:
            return self._err(500, "服务器内部错误", traceback=traceback.format_exc())

    # ---------- 静态文件 ----------
    def _static(self, rel: str):
        rel = rel.replace("\\", "/").lstrip("/")
        path = os.path.normpath(os.path.join(WEB_DIR, rel))
        if not path.startswith(os.path.normpath(WEB_DIR)):
            return self._err(403, "路径越界")
        if not os.path.isfile(path):
            return self._err(404, f"未找到：{rel}")
        ct = _CT.get(os.path.splitext(path)[1], "application/octet-stream")
        with open(path, "rb") as f:
            self._send(200, f.read(), ct)


def _missing(dom: str, data: dict) -> list:
    """必填项体检（schema.required + 空值；与业务规则无关）。"""
    schema, name = VD.primary_def(dom)
    if not schema or not name:
        return []
    target = (schema.get("$defs") or {}).get(name) or {}
    return GL.missing_required(dom, data, target)


def _check_report(dom: str, data: dict) -> dict:
    """只校验不写盘：原始报错 + 中文可读 + 必填体检。"""
    errs = VD.validate_entry(dom, data)
    return {"ok": not errs, "domain": dom, "errors": errs,
            "friendly": GL.friendly(dom, errs), "missing": _missing(dom, data)}


def main(argv=None):
    global GAMES_DIR
    ap = argparse.ArgumentParser(description="框架编辑器（造游戏包）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--games-dir", default=None, help="游戏包根目录（默认 framework/games/）")
    args = ap.parse_args(argv)
    GAMES_DIR = args.games_dir

    gd = PK.ensure_games_dir(GAMES_DIR)
    pkgs = PK.list_packages(GAMES_DIR)
    print("=" * 68)
    print("  框架编辑器 · saintess_engine —— 选项卡式「造游戏」工具")
    print("=" * 68)
    print(f"  本地地址   : http://{args.host}:{args.port}/")
    print(f"  游戏包目录 : {gd}")
    print(f"  已有包     : {len(pkgs)} 个" + (f"（{', '.join(p['id'] for p in pkgs)}）" if pkgs else ""))
    print(f"  可配置域   : {', '.join(k for k in PK.DOMAINS)}")
    print(f"  校验器     : {'jsonschema' if VD._js is not None else '内置最小校验器'}")
    print("  Ctrl+C 停止")
    print("=" * 68)
    srv = ThreadingHTTPServer((args.host, args.port), H)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
