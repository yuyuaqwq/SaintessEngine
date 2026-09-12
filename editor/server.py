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
    GET    /api/package/<id>/d/drop_pools/<key>/preview
                                          → 掉落池预览（引擎同一份 expand/audit 算结构/权重/审计）
    GET    /api/package/<id>/loot/audit   → 掉落池整表审计（596 池一次算；包内词汇声明参与判定）
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
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from editor import actions as AC     # noqa: E402
from editor import dist as DIST      # noqa: E402
from editor import glossary as GL    # noqa: E402
from editor import hints as HN       # noqa: E402
from editor import loot_view as LV   # noqa: E402
from editor import instance_view as IV  # noqa: E402
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

# ---------- 大包：校验结果缓存 ----------
# 为什么要有这一段
# ----------------
# `PK.domain_status()` 会把该域**每一条**都跑一遍 schema 校验，而它被三个高频接口各调一次：
# 包概览（GET /api/package/<id>）、条目列表（GET .../d/<dom>）、全包校验。实测 2000 条物品
# 单次 ~160ms（jsonschema），也就是每次打开包 / 切域 / 保存后刷列表都在做同样的重复劳动 ——
# 5000 条约 0.4s，1 万条约 0.8s，且**改一条要重算整包**。
# 这里做两件事（都不改语义，只去重复劳动）：
#   ① 按「条目内容」缓存单条校验结果：内容没变就直接复用（改一条 → 只重算那一条）。
#   ② 复用 jsonschema 的 validator（原先**每条**都新建 Draft202012Validator + RefResolver，
#      实测 2000 条 155ms → 52ms）；没有 jsonschema 时原样回退 VD.validate_entry。
# 输出与 packages.domain_status / validate_entry 逐字一致（同样的顺序、同样的错误文案）。
_VAL_CACHE: dict = {}                 # (域, key) -> (内容指纹, 错误列表)
_VAL_CACHE_MAX = 200_000              # 兜底上限（防无界增长）
_VALIDATORS: dict = {}                # 域 -> validator | None（None = 该域无 schema / 不可复用）
_STATUS_CACHE: dict = {}              # (包目录, 域) -> (文件签名, 域状态) —— 热调用主路径
_HINTS_CACHE: dict = {}               # 包目录 -> (全域文件签名, 联想数据)


def _file_sig(path: str):
    """域文件签名（mtime_ns + size）—— 文件没变，域状态就不用重算。"""
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _entry_stamp(data) -> str:
    """条目内容指纹（决定缓存是否可用；键序不影响结果）。"""
    try:
        return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return repr(data)


def _validate_fast(dom: str, data) -> list:
    """VD.validate_entry 的等价快路径（复用 validator）；不可用时原样回退。"""
    if VD._js is None:
        return VD.validate_entry(dom, data)
    if dom not in _VALIDATORS:
        v = None
        schema, name = VD.primary_def(dom)
        defs = (schema or {}).get("$defs") or {}
        target = defs.get(name) if name else None
        if target:
            sub = dict(schema)
            sub["$defs"] = defs
            sub.pop("$id", None)
            try:
                v = VD._js.Draft202012Validator(
                    target, resolver=VD._js.RefResolver.from_schema(sub))
            except Exception:                       # noqa: BLE001 —— 复用失败就回退
                v = None
        _VALIDATORS[dom] = v
    v = _VALIDATORS.get(dom)
    if v is None:
        return VD.validate_entry(dom, data)
    errs = sorted(v.iter_errors(data), key=lambda e: list(e.absolute_path))
    return [f"{VD._path_join(list(e.absolute_path))}: {e.message}" for e in errs]


def _validate_cached(dom: str, key: str, data) -> list:
    """带缓存的单条校验（内容没变 → 直接用上次结果）。"""
    stamp = _entry_stamp(data)
    ck = (dom, str(key))
    hit = _VAL_CACHE.get(ck)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    errs = _validate_fast(dom, data)
    if len(_VAL_CACHE) > _VAL_CACHE_MAX:
        _VAL_CACHE.clear()
    _VAL_CACHE[ck] = (stamp, errs)
    return errs


def _domain_status(pkg_dir: str, dom: str) -> dict:
    """`PK.domain_status` 的缓存版（结构 / 顺序 / 文案一致）。

    两级缓存：①**域文件签名**（mtime_ns + size）命中 → 连条目都不用碰（一次 `stat`），
    这是列表/概览热调用的主路径；②文件变了才逐条走 `_validate_cached`（按内容指纹，
    只重算真改过的那几条）。缓存键含包目录（同一进程里有多个包）。
    """
    st = {"domain": dom, "count": 0, "invalid": [], "ok": True}
    if dom not in PK.DOMAINS:
        return st
    path = PK.domain_path(pkg_dir, dom)
    sig = _file_sig(path)
    ck = (pkg_dir, dom)
    hit = _STATUS_CACHE.get(ck)
    if sig is not None and hit is not None and hit[0] == sig:
        return hit[1]
    table = PK.read_json(path, {})
    if not isinstance(table, dict):
        table = {}
    for k, v in table.items():
        if not isinstance(v, dict):
            continue
        st["count"] += 1
        errs = _validate_cached(dom, k, v)
        if errs:
            st["invalid"].append({"key": k, "errors": errs})
    st["ok"] = not st["invalid"]
    if sig is not None:
        if len(_STATUS_CACHE) > 500:
            _STATUS_CACHE.clear()
        _STATUS_CACHE[ck] = (sig, st)
    return st


def _hints_cached(pkg_dir: str) -> dict:
    """`HN.build` + `flatten_for_ui` 的缓存版：按**全部域文件的签名**失效。

    为什么值得缓存：`hints` 要扫全包（13 域 / 5 千条实测 ~52ms），而它每次「选包 / 保存」
    都会被调一次；签名只是 13 次 `stat`。
    """
    sig = tuple((d, _file_sig(PK.domain_path(pkg_dir, d))) for d in PK.DOMAINS)
    hit = _HINTS_CACHE.get(pkg_dir)
    if hit is not None and hit[0] == sig:
        return hit[1]
    out = HN.flatten_for_ui(HN.build(pkg_dir))
    if len(_HINTS_CACHE) > 200:
        _HINTS_CACHE.clear()
    _HINTS_CACHE[pkg_dir] = (sig, out)
    return out


def _package_overview(pkg_dir: str) -> dict:
    """`PK.package_overview` 的缓存版（把每域的全量校验换成增量缓存）。"""
    m = PK.load_manifest(pkg_dir)
    doms = m.get("domains") or list(PK.DOMAINS)
    return {
        "manifest": m,
        "engine_check": PK.engine_check(m),
        "domains": [{"id": d, **{k: PK.DOMAINS[d][k] for k in ("label", "icon", "kind")},
                     **_domain_status(pkg_dir, d)}
                    for d in doms if d in PK.DOMAINS],
    }


# ---------- 大包：列表分页 ----------
# 为什么：单域一万条时列表响应 ~1.9MB，而首屏（左栏）必须等它到齐才能画。
# `?limit=&offset=` 让编辑器先画第一段、其余后台续取；**不带参数 = 全量**，旧调用方零影响。
# `count` 始终是**该域总数**（不是本页条数）—— 前端据此知道还剩多少没取。
def _page(out: dict, q: dict) -> dict:
    entries = out.get("entries") or []
    total = out.get("count", len(entries))

    def _int(name: str, default: int = 0) -> int:
        try:
            return int((q.get(name) or [""])[0])
        except (TypeError, ValueError):
            return default

    limit = _int("limit", 0)
    offset = max(0, _int("offset", 0))
    if limit <= 0:                       # 不传 / 非法 / ≤0 → 全量（与历史行为逐字一致）
        return out
    return {**out, "entries": entries[offset:offset + limit], "count": total,
            "offset": offset, "limit": limit}


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
            return self._send(200, {"ok": True, "dir": d, **_package_overview(d)})
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
            q = parse_qs(getattr(self, "_query", ""))
            return self._send(200, {"ok": True, **DIST.inspect_zip((q.get("path") or [""])[0])})
        # 编辑提示：跨域引用候选 + 包内已有取值/键（联想数据源，内容驱动、无框架词汇）
        if len(parts) == 3 and parts[0] == "package" and parts[2] == "hints":
            d = PK.resolve_package(parts[1], GAMES_DIR)
            if not d:
                return self._err(404, f"包不存在：{parts[1]}")
            return self._send(200, {"ok": True, **_hints_cached(d)})
        if len(parts) in (2, 3) and parts[0] == "schema":
            # GET /api/schema/<dom>  （历史上这里写成 `len(parts)==3` → 该路由**从未匹配上**，
            # 因为没人调用所以一直没暴露；新建草稿要按 domain 取 schema，故修成 2 段可达）
            s = VD.load_schema(parts[1])
            return self._send(200, {"ok": bool(s), "schema": s})
        if parts == ["actions"]:
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
        # drop_pools 域级审计：596 池一次算（引擎同一份 LootTable.audit）。
        # 包内 `content/rules/loot_vocab.json` 是**内容侧**的引用词汇声明（引擎零知识）——
        # 有它 → 审计按包自己的说法判；没有它 / 声明坏 → 与没有这功能时逐格一致。
        if len(parts) == 4 and parts[0] == "package" and parts[2] == "loot" and parts[3] == "audit":
            d = PK.resolve_package(parts[1], GAMES_DIR)
            if not d:
                return self._err(404, f"包不存在：{parts[1]}")
            data = PK.read_json(PK.domain_path(d, "drop_pools"), {})
            out = LV.audit_file(data if isinstance(data, dict) else {}, LV.load_vocab(d))
            return self._send(200 if out.get("ok") else 422, out)
        # drop_pools 域的池预览：权重占比 / 展开候选 / 结构审计由**引擎同一份代码**算
        # （editor/loot_view.py；LootTable 在这里 resolver=None —— 预览不假装认识引用）。
        if (len(parts) == 6 and parts[0] == "package" and parts[2] == "d"
                and parts[5] == "preview"):
            d = PK.resolve_package(parts[1], GAMES_DIR)
            if not d:
                return self._err(404, f"包不存在：{parts[1]}")
            dom = parts[3]
            if dom not in PK.DOMAINS:
                return self._err(404, f"未知域：{dom}")
            if dom != "drop_pools":
                return self._err(404, f"该域没有池预览：{dom}")
            data = PK.read_json(PK.domain_path(d, dom), {})
            out = LV.build_file(data if isinstance(data, dict) else {}, parts[4],
                                LV.load_vocab(d))
            return self._send(200 if out.get("ok") else 422, out)
        # instances 域的进度视图：节点序 / 每层剩余 / 末层（is_last）由**引擎同一份 Progress** 算
        # （editor/instance_view.py；怪名/Boss/钥匙/地图全是内容侧词汇 —— 预览不假装认识它们）。
        if (len(parts) == 6 and parts[0] == "package" and parts[2] == "d"
                and parts[5] == "run"):
            d = PK.resolve_package(parts[1], GAMES_DIR)
            if not d:
                return self._err(404, f"包不存在：{parts[1]}")
            dom = parts[3]
            if dom not in PK.DOMAINS:
                return self._err(404, f"未知域：{dom}")
            if dom != "instances":
                return self._err(404, f"该域没有进度视图：{dom}")
            data = PK.read_json(PK.domain_path(d, dom), {})
            out = IV.build_file(data if isinstance(data, dict) else {}, parts[4])
            return self._send(200 if out.get("ok") else 422, out)
        if len(parts) >= 4 and parts[0] == "package" and parts[2] == "d":
            d = PK.resolve_package(parts[1], GAMES_DIR)
            if not d:
                return self._err(404, f"包不存在：{parts[1]}")
            dom = parts[3]
            if dom not in PK.DOMAINS:
                return self._err(404, f"未知域：{dom}")
            if len(parts) == 4:
                out = PK.list_entries(d, dom)
                q = parse_qs(getattr(self, "_query", ""))
                page = _page(out, q)
                return self._send(200, {"ok": True, **page,
                                        "status": _domain_status(d, dom)})
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
                        st = _domain_status(d, dom)
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
                        errs = _validate_cached(dom, key, data)
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
