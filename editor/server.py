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
    GET    /api/package/<id>/relations    → **包的引用/联动声明**（规范化后 + 可读告警）
    GET    /api/package/<id>/views        → **包的视图声明**（域 → 内置视图名 + 来源 + render 小节）
    GET    /api/package/<id>/render       → ★第 3 层**渲染声明面**（只读声明，不执行包代码、不读条目）
    GET    /api/package/<id>/d/<dom>/<key>/view   → 通用视图分派
                                          （`?view=` > render 声明 > views.json > 内置默认；坏声明降级）
    GET    /api/wiki/tree                 → 文档页清单（左导航）
    GET    /api/wiki/page?path=<rel>      → 渲染后的文档页（md → html + 目录）
    GET    /api/wiki/search?q=<词>        → 跨页搜词（配字段时找语义）
    GET    /api/wiki/code?ref=x.py:NN     → 文档里的 `file.py:NNN` → 真实源码片段
    ↑ 四条都接 `?pkg=<id>` → 该包自带的 `<pkg>/docs/wiki/**.md`（**包优先、框架兜底**）；
      不给包 = 历史行为逐字不变（包没有 docs/wiki 时输出与改造前逐项一致）
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

#: `/api/glossary` 响应缓存（内容戳 → payload）。
#  ★ 必须是**多档**：实测（2026-09-15）用户来回切 orlandia ↔ my_game 时，若只留最近一档，
#    每次都被对方顶掉 ⇒ 每次都在冷重建（glossary 冷态 2.9–4.1s）。留 8 档即可常驻热态。
_GLOSSARY_CACHE: dict = {}
_GLOSSARY_CACHE_MAX = 8


def _glossary_stamp(pkg_dir):
    """`/api/glossary` 的内容戳 =（受影响的文件数, 最新 mtime）。

    覆盖：① 包内 `editor/**` 声明面（glossary/<域>.json · relations.json · views.json ·
    domains.json · render/* 等）；② 框架侧参与拼装的源码（glossary / relations / render_decl）。
    改任何一处 ⇒ 戳变 ⇒ 立刻重拼（保证「编辑即刻可见」）；没改 ⇒ 复用整份 payload。
    """
    paths = []
    if pkg_dir:
        for sub in ("editor",):
            d = os.path.join(pkg_dir, sub)
            if os.path.isdir(d):
                for dp, dn, fn in os.walk(d):
                    dn[:] = [x for x in dn if x not in ("__pycache__", ".git")]
                    paths.extend(os.path.join(dp, f) for f in fn)
    here = os.path.dirname(os.path.abspath(__file__))
    for f in ("glossary.py", "relations.py", "render_decl.py"):
        p = os.path.join(here, f)
        if os.path.exists(p):
            paths.append(p)
    newest = 0.0
    for p in paths:
        try:
            mt = os.path.getmtime(p)
        except OSError:
            continue
        if mt > newest:
            newest = mt
    return (len(paths), round(newest, 3))
from editor import hints as HN       # noqa: E402
from editor import loot_view as LV   # noqa: E402
from editor import instance_view as IV  # noqa: E402
from editor import packages as PK    # noqa: E402
from editor import relations as REL  # noqa: E402
from editor import render as RENDER  # noqa: E402  （第 3 层·批 1：声明面；零引擎 import）
from editor import space_view as SV  # noqa: E402
from editor import table_view as TV  # noqa: E402
from editor import validate as VD    # noqa: E402
from editor import wiki as WK        # noqa: E402
from editor._util import file_sig as _file_sig  # noqa: E402  （P0-10 单源：文件签名）

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


def _entry_stamp(data) -> str:
    """条目内容指纹（决定缓存是否可用；键序不影响结果）。"""
    try:
        return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return repr(data)


def _validate_fast(dom: str, data, pkg_dir=None) -> list:
    """VD.validate_entry 的等价快路径（复用 validator）；不可用时原样回退。"""
    ck = (str(pkg_dir or ""), dom)
    if VD._js is None:
        return VD.validate_entry(dom, data, pkg_dir)
    if ck not in _VALIDATORS:
        v = None
        schema, name = VD.primary_def(dom, pkg_dir)
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
        _VALIDATORS[ck] = v
    v = _VALIDATORS.get(ck)
    if v is None:
        return VD.validate_entry(dom, data, pkg_dir)
    errs = sorted(v.iter_errors(data), key=lambda e: list(e.absolute_path))
    return [f"{VD._path_join(list(e.absolute_path))}: {e.message}" for e in errs]


def _validate_cached(dom: str, key: str, data, pkg_dir=None) -> list:
    """带缓存的单条校验（内容没变 → 直接用上次结果）。缓存键含包目录。"""
    stamp = _entry_stamp(data)
    ck = (str(pkg_dir or ""), dom, str(key))
    hit = _VAL_CACHE.get(ck)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    errs = _validate_fast(dom, data, pkg_dir)
    if len(_VAL_CACHE) > _VAL_CACHE_MAX:
        _VAL_CACHE.clear()
    _VAL_CACHE[ck] = (stamp, errs)
    return errs


def _domains_for(pkg_dir: str) -> dict:
    """该包的**有效域表**（内置 + 包自带 `editor/domains.json`）—— 所有域枚举/读写都走这里。"""
    domains, _warns = PK.effective_domains(pkg_dir)
    return domains


def _domain_status(pkg_dir: str, dom: str, domains: dict | None = None) -> dict:
    """`PK.domain_status` 的缓存版（结构 / 顺序 / 文案一致）。

    两级缓存：①**域文件签名**（mtime_ns + size）命中 → 连条目都不用碰（一次 `stat`），
    这是列表/概览热调用的主路径；②文件变了才逐条走 `_validate_cached`（按内容指纹，
    只重算真改过的那几条）。缓存键含包目录（同一进程里有多个包）。

    第 2 层（2026-09-13）：该域若被包**声明了引用关系**（`editor/relations.json`），
    校验结果里还要加上**引用校验**（`REL.ref_errors`）—— 它依赖**目标域**的表，签名
    只看本域文件会读到旧结论，所以这种情况**绕过缓存**（只在真声明了 ref 的域上付代价；
    没声明的包逐项等于改造前）。
    """
    st = {"domain": dom, "count": 0, "invalid": [], "ok": True}
    if domains is None:
        domains = _domains_for(pkg_dir)
    if dom not in domains:
        return st
    has_refs = any(r.get("ref") for r in
                   (REL.package_relations(pkg_dir).get(dom) or {}).values())
    path = PK.domain_path(pkg_dir, dom, domains)
    sig = _file_sig(path)
    ck = (pkg_dir, dom)
    hit = _STATUS_CACHE.get(ck)
    if not has_refs and sig is not None and hit is not None and hit[0] == sig:
        return hit[1]
    table = PK.read_json(path, {})
    if not isinstance(table, dict):
        table = {}
    for k, v in table.items():
        if not PK.is_entry_key(k):
            continue                      # 私有 / 文件级元信息键不是条目 —— 与 PK.domain_status 同口径
        if not isinstance(v, dict):
            continue
        st["count"] += 1
        errs = _validate_cached(dom, k, v, pkg_dir)
        if has_refs:
            errs = errs + REL.ref_errors(pkg_dir, dom, v)
        if errs:
            st["invalid"].append({"key": k, "errors": errs})
    st["ok"] = not st["invalid"]
    if sig is not None and not has_refs:
        if len(_STATUS_CACHE) > 500:
            _STATUS_CACHE.clear()
        _STATUS_CACHE[ck] = (sig, st)
    return st


def _hints_cached(pkg_dir: str) -> dict:
    """`HN.build` + `flatten_for_ui` 的缓存版：按**全部域文件的签名**失效。

    为什么值得缓存：`hints` 要扫全包（13 域 / 5 千条实测 ~52ms），而它每次「选包 / 保存」
    都会被调一次；签名只是 13 次 `stat`。域表 = 该包的有效域表（含包自带的新域）。
    第 2 层（2026-09-13）：`editor/relations.json` / `editor/views.json` 的签名也进缓存键
    —— 声明改了就立刻重算（`ref_names` 是随关系声明用的）。
    """
    domains = _domains_for(pkg_dir)
    sig = tuple([tuple(sorted(domains))] +
                [(d, _file_sig(PK.domain_path(pkg_dir, d, domains))) for d in domains] +
                [(_file_sig(REL.relations_decl_path(pkg_dir)),),
                 (_file_sig(REL.views_decl_path(pkg_dir)),)])
    hit = _HINTS_CACHE.get(pkg_dir)
    if hit is not None and hit[0] == sig:
        return hit[1]
    out = HN.flatten_for_ui(HN.build(pkg_dir))
    if len(_HINTS_CACHE) > 200:
        _HINTS_CACHE.clear()
    _HINTS_CACHE[pkg_dir] = (sig, out)
    return out


def _package_overview(pkg_dir: str) -> dict:
    """`PK.package_overview` 的缓存版（把每域的全量校验换成增量缓存；域表走有效域表）。"""
    m = PK.load_manifest(pkg_dir)
    domains, warns = PK.effective_domains(pkg_dir)
    doms = m.get("domains") or list(domains)
    return {
        "manifest": m,
        "engine_check": PK.engine_check(m),
        "domains": [{"id": d, **{k: domains[d][k] for k in ("label", "icon", "kind")},
                     **_domain_status(pkg_dir, d, domains)}
                    for d in doms if d in domains],
        # 包声明面的告警（域声明 ∪ 引用/联动 ∪ 视图 ∪ 词汇表 ∪ 渲染声明）—— 前端照此提示，不静默
        "domain_warnings": (warns + REL.all_warnings(pkg_dir) + GL.glossary_warnings(pkg_dir)
                            + RENDER.render_warnings(pkg_dir, domains)),
        # 该包**自己新增**（内置默认集里没有）的域 id（声明口径见 `/api/domains` 的 from_package）
        "package_domains": [d for d in domains if d not in PK.DOMAINS],
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

    #: 压缩门槛：>1KB 且客户端声明支持 gzip 才压（小响应压了没意义，反多一层开销）
    GZIP_MIN = 1024

    def _send(self, code: int, body, ctype="application/json; charset=utf-8", headers=None):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        # ★ gzip（2026-09-15 实测优化）：切包要过 `/api/package/<id>/hints` **1.46 MB**、
        #   `/api/glossary` 527 KB、`app.js` 142 KB …——服务端只要 20–60ms，慢在浏览器
        #   「下载 + JSON.parse + 建索引」。开 gzip 后实测降到约 1/8～1/10（见提交说明的对照表）。
        extra = {}
        try:
            if len(body) >= self.GZIP_MIN and "gzip" in (self.headers.get("Accept-Encoding") or "").lower():
                import gzip as _gzip
                body = _gzip.compress(bytes(body), 6)
                extra["Content-Encoding"] = "gzip"
                extra["Vary"] = "Accept-Encoding"
        except Exception:                                       # noqa: BLE001
            pass                                                # 压不了就按原样发，不影响功能
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in extra.items():
                self.send_header(k, v)
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
            # 域注册表（tab 列表）。`?pkg=<id>` → **该包的有效域表**（内置 + 包自带声明），
            # 不带 = 内置那份（历史行为逐字不变）。
            q = parse_qs(getattr(self, "_query", ""))
            pkg_id = (q.get("pkg") or [""])[0]
            pkg_dir = PK.resolve_package(pkg_id, GAMES_DIR) if pkg_id else None
            if pkg_id and not pkg_dir:
                return self._err(404, f"包不存在：{pkg_id}")
            domains, warns = PK.effective_domains(pkg_dir)
            decl = PK.package_domains(pkg_dir) if pkg_dir else {}
            return self._send(200, {"ok": True, "domains": [
                {"id": k, **{x: v[x] for x in ("label", "icon", "kind")},
                 "primary": v.get("primary"),
                 "has_schema": bool(v.get("schema")),
                 "from_package": k in decl}
                for k, v in domains.items()],
                "warnings": warns})
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
        # 第 2 层（2026-09-13）：包的**声明面**照实回前端（规范化结果 + 下拉候选 + 可读告警）
        if len(parts) == 3 and parts[0] == "package" and parts[2] == "relations":
            d = PK.resolve_package(parts[1], GAMES_DIR)
            if not d:
                return self._err(404, f"包不存在：{parts[1]}")
            rel = REL.package_relations(d)
            cand: dict = {}
            for dom, rules in rel.items():
                for field, rule in rules.items():
                    if rule.get("ref"):
                        t = rule["ref"]
                        cand[f"{dom}.{field}"] = {
                            "domain": t["domain"], "by": t["by"],
                            "candidates": REL.ref_candidates(d, t["domain"], t["by"])}
            link: dict = {}
            for dom in list(_domains_for(d)) + (["*"] if "*" in rel else []):
                L = REL.linkage_for(d, dom)
                if L:
                    link[dom] = L
            return self._send(200, {"ok": True, "relations": rel, "candidates": cand,
                                    "linkage": link,
                                    "warnings": REL.relation_warnings(d)})
        # ★ 第 3 层·批 1（声明面）：**只读声明**的 render 接口 —— 不执行任何包代码、不读条目数据。
        #   契约 §3.1：`{ok, package, code_enabled, domains, effective, limits, warnings}`，响应 ≤ 64 KB。
        if len(parts) == 3 and parts[0] == "package" and parts[2] == "render":
            d = PK.resolve_package(parts[1], GAMES_DIR)
            if not d:
                return self._err(404, f"包不存在：{parts[1]}")
            domains = _domains_for(d)
            decls = RENDER.declarations(d, domains)
            eff: dict = {}
            for dom in domains:
                name, src, _w = REL.resolve_view(d, dom)
                info = decls["domains"].get(dom)
                if info and info.get("active"):
                    eff[dom] = {"render": True, "extends": info.get("extends"),
                                "active": True, "source": "render"}
                else:
                    eff[dom] = {"render": bool(info),
                                "extends": (info or {}).get("extends"),
                                "active": False,
                                "source": {"package": "views", "builtin": "builtin"}.get(src, "none")}
            body = {"ok": True, "package": parts[1], "code_enabled": decls["code_enabled"],
                    "domains": decls["domains"], "effective": eff, "limits": decls["limits"],
                    "warnings": decls["warnings"]}
            if len(json.dumps(body, ensure_ascii=False).encode("utf-8")) > 64 * 1024:
                # 契约 §3.1 的「响应 ≤ 64 KB」：裁剪 effective（只留有 render 分派的域），**不静默**
                body["effective"] = {k: v for k, v in eff.items() if v["render"]}
                body["warnings"] = list(body["warnings"]) + ["响应超过 64 KB：effective 已裁剪"]
            return self._send(200, body)
        if len(parts) == 3 and parts[0] == "package" and parts[2] == "views":
            d = PK.resolve_package(parts[1], GAMES_DIR)
            if not d:
                return self._err(404, f"包不存在：{parts[1]}")
            eff: dict = {}
            for dom in _domains_for(d):
                name, src, _w = REL.resolve_view(d, dom)
                if name:
                    eff[dom] = {"view": name, "source": src,
                                "route": REL.VIEW_ROUTES.get(REL.resolved_name(name), "view")}
            # ★ 第 3 层·批 1：**render 小节**（该域有没有声明过、活没活、要不要跑代码）——
            #   前端第 5 档的显隐判据；没声明 = `declared: []`（既有键一个不动，零回归）
            _rd = RENDER.declarations(d, _domains_for(d))
            return self._send(200, {"ok": True, "views": REL.package_views(d),
                                    "effective": eff,
                                    "builtin": dict(REL.BUILTIN_DEFAULT_VIEWS),
                                    "names": list(REL.VIEW_NAMES),
                                    "render": {
                                        "declared": sorted(_rd["domains"]),
                                        "active": sorted(k for k, v in _rd["domains"].items()
                                                         if v.get("active")),
                                        "code_enabled": _rd["code_enabled"],
                                        "warnings": _rd["warnings"]},
                                    "warnings": REL.view_warnings(d)})
        if len(parts) in (2, 3) and parts[0] == "schema":
            # GET /api/schema/<dom>  （历史上这里写成 `len(parts)==3` → 该路由**从未匹配上**，
            # 因为没人调用所以一直没暴露；新建草稿要按 domain 取 schema，故修成 2 段可达）
            # `?pkg=<id>` → 优先用该包的有效域表（包自带域声明可以带自己的 schema）
            q = parse_qs(getattr(self, "_query", ""))
            pkg_id = (q.get("pkg") or [""])[0]
            pkg_dir = PK.resolve_package(pkg_id, GAMES_DIR) if pkg_id else None
            s = VD.load_schema(parts[1], pkg_dir)
            # `schema_path()` 的解析顺序是**包内优先 → 框架回退**；包自带那份读不了时
            # `validate._resolve_schema()` 会降级回退框架 + 给一条可读告警 —— 照实送前端
            # （容错但**不静默**）。正常情况 `warnings` 恒为 `[]`。
            return self._send(200, {"ok": bool(s), "schema": s,
                                    "warnings": VD.schema_warnings(parts[1], pkg_dir)})
        if parts == ["actions"]:
            q = parse_qs(getattr(self, "_query", ""))
            pkg_id = (q.get("pkg") or [""])[0]
            fresh = (q.get("fresh") or ["0"])[0] not in ("", "0", "false")
            pkg_dir = PK.resolve_package(pkg_id, GAMES_DIR) if pkg_id else None
            return self._send(200, AC.inventory(pkg_dir, use_cache=not fresh))
        if parts == ["_perf"]:
            # 前端计时探针回传（诊断「切包慢」用，见 web/app.js 的 withPerf）。
            # 只写一行到服务端 stderr（= 编辑器日志），返回 204 —— 目的就是让诊断者能读到
            # **真实浏览器**里每步的耗时，而不是靠猜服务端。定位完即可移除。
            q = parse_qs(getattr(self, "_query", ""))
            label = (q.get("l") or [""])[0]
            ms = (q.get("ms") or [""])[0]
            total = (q.get("t") or [""])[0]
            sys.stderr.write("  [perf] %-22s %8s ms%s\n" % (
                label, ms, ("   (总 %s ms)" % total) if total else ""))
            return self._send(204, b"")
        if parts == ["glossary"]:
            # `?pkg=<id>` → **包声明优先**的控件/引用/词汇表（第 2 层：包内 `editor/relations.json`
            # 改「哪个字段引用哪个域」；包自带词汇表 `editor/glossary/<域>.json` 改
            # 「字段中文名/注脚/分组/控件」；坏声明降级 + warnings，不静默。不给包 = 旧行为逐字不变）
            #
            # ★ 性能（2026-09-15 实测）：本接口**首次**要现拼 8 份数据（71 域 entries + 65 groups +
            #   73 widgets + 关系/视图/告警/渲染面），冷态实测 **5.4s**（切包时必打 ⇒ 用户感觉「加载半天」）。
            #   改为**按内容戳缓存整份 payload**（戳 = 包内 `editor/**` 声明面 + 框架侧 glossary/relations/
            #   render_decl 源码的 文件数+最新 mtime）：改任何声明文件 ⇒ 戳变 ⇒ 立刻重拼（原意保留：
            #   编辑即刻可见）；没改 ⇒ 直接复用。只留最近一档，防增长。
            q = parse_qs(getattr(self, "_query", ""))
            pkg_id = (q.get("pkg") or [""])[0]
            pkg_dir = PK.resolve_package(pkg_id, GAMES_DIR) if pkg_id else None
            if pkg_id and not pkg_dir:
                return self._err(404, f"包不存在：{pkg_id}")
            gkey = (pkg_id, _glossary_stamp(pkg_dir))
            hit = _GLOSSARY_CACHE.get(gkey)
            if hit is not None:
                return self._send(200, hit)
            payload = _build_glossary_payload(pkg_dir)
            _GLOSSARY_CACHE[gkey] = payload
            if len(_GLOSSARY_CACHE) > _GLOSSARY_CACHE_MAX:
                for k in list(_GLOSSARY_CACHE)[:-_GLOSSARY_CACHE_MAX // 2]:
                    _GLOSSARY_CACHE.pop(k, None)
            return self._send(200, payload)
        if len(parts) >= 2 and parts[0] == "wiki":
            q = parse_qs(getattr(self, "_query", ""))
            # `?pkg=<id>` → 该包自带的 wiki（`<pkg>/docs/wiki/**.md`）；解析口径是
            # **包优先、框架兜底**：包内同名页胜、包内没有的页回退框架页、两边都没有 = 404/None。
            # 不给包 / 包没有 docs/wiki = 历史行为逐字不变（零回归硬约束）。
            pkg_id = (q.get("pkg") or [""])[0]
            pkg_dir = PK.resolve_package(pkg_id, GAMES_DIR) if pkg_id else None
            if pkg_id and not pkg_dir:
                return self._err(404, f"包不存在：{pkg_id}")
            if parts[1] == "tree":
                return self._send(200, {"ok": True, "pages": WK.tree(pkg_dir),
                                        "groups": [{"id": g, "label": l} for g, l in WK.GROUPS]})
            if parts[1] == "page":
                rel = (q.get("path") or [""])[0]
                pg = WK.page(rel, pkg_dir)
                if not pg:
                    return self._err(404, f"文档不存在：{rel}")
                return self._send(200, {"ok": True, **pg})
            if parts[1] == "search":
                return self._send(200, {"ok": True,
                                        "hits": WK.search((q.get("q") or [""])[0], pkg_dir=pkg_dir)})
            if parts[1] == "code":
                return self._send(200, {"ok": True,
                                        **WK.code_ref((q.get("ref") or [""])[0], pkg_dir=pkg_dir)})
            return self._err(404, "未知 wiki 接口")
        # maps 域的拓扑视图：节点/连边/深度/审计由**引擎同一份派生代码**算（editor/space_view.py）
        if (len(parts) == 6 and parts[0] == "package" and parts[2] == "d"
                and parts[5] == "graph"):
            d = PK.resolve_package(parts[1], GAMES_DIR)
            if not d:
                return self._err(404, f"包不存在：{parts[1]}")
            dom = parts[3]
            domains = _domains_for(d)
            if dom not in domains:
                return self._err(404, f"未知域：{dom}")
            data = PK.read_json(PK.domain_path(d, dom, domains), {})
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
            domains = _domains_for(d)
            if dom not in domains:
                return self._err(404, f"未知域：{dom}")
            # ★ 第 2 层（2026-09-13）：域门槛从**写死的 `dom != "drop_pools"`** 降级为
            #   「**视图分派**是不是 loot_view」（包声明 > 框架默认）。包不声明时逐项不变：
            #   drop_pools 的默认就是 loot_view → 照旧 200；其它域 → 照旧 404。
            _vn, _vs, _vw = REL.resolve_view(d, dom)
            if REL.resolved_name(_vn or "") != "loot_view":
                return self._err(404, f"该域没有池预览：{dom}")
            data = PK.read_json(PK.domain_path(d, dom, domains), {})
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
            domains = _domains_for(d)
            if dom not in domains:
                return self._err(404, f"未知域：{dom}")
            # ★ 同上：`dom != "instances"` → 「视图分派是不是 instance_view」。
            #   不声明时 instances 的默认就是 instance_view → 逐项不变。
            _vn, _vs, _vw = REL.resolve_view(d, dom)
            if REL.resolved_name(_vn or "") != "instance_view":
                return self._err(404, f"该域没有进度视图：{dom}")
            data = PK.read_json(PK.domain_path(d, dom, domains), {})
            out = IV.build_file(data if isinstance(data, dict) else {}, parts[4])
            return self._send(200 if out.get("ok") else 422, out)
        # ★ 通用视图分派（第 2 层）：按包内 `editor/views.json`（**包声明 > 框架默认**）选
        #   **内置**视图（包不写新代码）：loot_view / instance_view / space_view / table / graph。
        #   `?view=<名>` 可临时指定（不落盘）。没声明 → 404（照旧语义：这个域没有专属视图）。
        if (len(parts) == 6 and parts[0] == "package" and parts[2] == "d"
                and parts[5] == "view"):
            d = PK.resolve_package(parts[1], GAMES_DIR)
            if not d:
                return self._err(404, f"包不存在：{parts[1]}")
            dom = parts[3]
            domains = _domains_for(d)
            if dom not in domains:
                return self._err(404, f"未知域：{dom}")
            q = parse_qs(getattr(self, "_query", ""))
            forced = (q.get("view") or [""])[0]
            name, src, warns = REL.resolve_view(d, dom)
            if forced:
                if forced not in REL.VIEW_NAMES:
                    return self._err(400, f"未知视图：{forced}（内置视图只有 "
                                          f"{' / '.join(REL.VIEW_NAMES)}）")
                name, src = forced, "query"
            # ★ 第 3 层·批 1（声明面）：分派优先级 = `?view=`（既有，最高）> **render 声明**
            #   > `views.json` > `BUILTIN_DEFAULT_VIEWS`。声明**坏** / `when` 不满足 / 树建不出
            #   → **仍然 200**（回退可渲染态 + 黄条，`view_warnings` 带 `{stage, message}`），
            #   **不 500、不白屏**。
            _info = (RENDER.declarations(d, domains)["domains"] or {}).get(dom) or {}
            _declared = bool(_info)
            _decl_warns = list(_info.get("warnings") or [])
            if not forced and _declared and _info.get("active"):
                data = PK.read_json(PK.domain_path(d, dom, domains), {})
                _tree = _run_view(d, dom, "package-render",
                                  data if isinstance(data, dict) else {}, parts[4],
                                  domains=domains)
                if _tree.get("ok"):
                    _extra = []
                    if name:
                        _decl, _ = RENDER.declared(d, dom, domains)
                        _extra.append(f"该域 `editor/views.json` 的视图声明（{name}）被 render 声明"
                                      f"覆盖 —— 以 render 为准（$extends="
                                      f"{(_decl or {}).get('extends') or 'form'}）")
                    return self._send(200, {
                        "ok": True, "view_name": "package-render", "view_source": "package-render",
                        "view_warnings": (list(warns) + _extra
                                          + [w for w in (_tree.get("warnings") or [])]),
                        # 契约 §3.2：`view` = 受限渲染树（前端只做白名单渲染 + esc()，不 eval）
                        "view": _tree})
                # L3：树建不出 → 回退第 2 层（仍然 200）；第 2 层也没分派 → `view: null` + 黄条
                _stage = {"stage": _tree.get("stage") or "decl",
                          "message": _tree.get("message") or "自定义渲染失败 —— 已回退内置视图"}
                _tw = list(warns) + list(_tree.get("warnings") or []) + [_stage]
                if not name:
                    return self._send(200, {"ok": True, "view_name": None, "view_source": "none",
                                            "view_warnings": _tw, "view": None,
                                            "render_stage": _stage["stage"]})
                data = PK.read_json(PK.domain_path(d, dom, domains), {})
                out = _run_view(d, dom, name, data if isinstance(data, dict) else {}, parts[4])
                return self._send(200 if out.get("ok") else 422,
                                  {**out, "view_name": name, "view_source": src,
                                   "view_warnings": _tw, "render_stage": _stage["stage"]})
            # L1：声明了但**读不出 / 不合法**（active=false）→ 走第 2 层 + 黄条（不静默）
            _decl_stage = [{"stage": "decl",
                            "message": "该域的 render 声明本次不可用（声明坏了 / 不合法）"
                                       " —— 已回退第 2 层视图"}] if _declared else []
            if not name:
                if _declared:
                    return self._err(404, f"该域没有可用的视图分派：{dom}"
                                          "（render 声明本次不可用，第 2 层也没有视图）",
                                     view_warnings=_decl_warns + _decl_stage,
                                     render_stage="decl")
                return self._err(404, "该域没有声明视图：%s（在包内 editor/views.json 里写 "
                                      "{\"域\": {\"view\": \"…\"}}）" % dom)
            data = PK.read_json(PK.domain_path(d, dom, domains), {})
            out = _run_view(d, dom, name, data if isinstance(data, dict) else {}, parts[4])
            return self._send(200 if out.get("ok") else 422,
                              {**out, "view_name": name, "view_source": src,
                               "view_warnings": list(warns) + _decl_warns + _decl_stage})
        if len(parts) >= 4 and parts[0] == "package" and parts[2] == "d":
            d = PK.resolve_package(parts[1], GAMES_DIR)
            if not d:
                return self._err(404, f"包不存在：{parts[1]}")
            dom = parts[3]
            domains = _domains_for(d)
            if dom not in domains:
                return self._err(404, f"未知域：{dom}")
            if len(parts) == 4:
                out = PK.list_entries(d, dom, domains)
                q = parse_qs(getattr(self, "_query", ""))
                page = _page(out, q)
                return self._send(200, {"ok": True, **page,
                                        "status": _domain_status(d, dom, domains)})
            if len(parts) == 5:
                key = parts[4]
                e = PK.get_entry(d, dom, key)
                if e is None:
                    return self._err(404, f"条目不存在：{key}")
                return self._send(200, {"ok": True, "key": key, "data": e,
                                        "errors": VD.validate_entry(dom, e, d),
                                        "schema": VD.load_schema(dom, d)})
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
                    domains = _domains_for(d)
                    for dom in PK.load_manifest(d).get("domains") or list(domains):
                        if dom not in domains:
                            continue
                        st = _domain_status(d, dom, domains)
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
                    if dom not in _domains_for(d):
                        return self._err(404, f"未知域：{dom}")
                    data = body.get("data")
                    if not isinstance(data, dict):
                        return self._err(400, "请求体需为 {\"data\": {...}}")
                    rep = _check_report(dom, data, d)
                    if len(parts) == 7:
                        rep["key"] = parts[5]
                    return self._send(200, rep)
                # /api/package/<id>/d/<dom>/[key]
                if len(parts) >= 5 and parts[3] == "d":
                    dom = parts[4]
                    domains = _domains_for(d)
                    if dom not in domains:
                        return self._err(404, f"未知域：{dom}")
                    if len(parts) == 5 and method == "PUT":
                        return self._err(405, "缺少条目 key")
                    if len(parts) == 6 and method == "PUT":
                        key = parts[5]
                        data = body.get("data")
                        if not isinstance(data, dict):
                            return self._err(400, "请求体需为 {\"data\": {...}}")
                        # schema 校验 + （第 2 层）**包声明的引用校验** —— 包没声明 ref
                        # 时 `ref_errors` 恒为 []（既有包零回归）。
                        errs = _validate_cached(dom, key, data, d) + REL.ref_errors(d, dom, data)
                        if errs:
                            return self._err(422, "校验未通过，未写入",
                                             validation={"key": key, "errors": errs,
                                                         "friendly": GL.friendly(dom, errs, d),
                                                         "missing": _missing(dom, data, d)})
                        PK.put_entry(d, dom, key, data)
                        return self._send(200, {"ok": True, "key": key,
                                                "domain": dom,
                                                "count": PK.list_entries(d, dom, domains)["count"]})
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


def _missing(dom: str, data: dict, pkg_dir=None) -> list:
    """必填项体检（schema.required + 空值；与业务规则无关）。

    第 3 面（2026-09-13）：字段中文名/注脚取**包自带词汇表**
    （`<pkg>/editor/glossary/<域>.json`，包声明优先）；包没声明 = 逐项等于改造前。
    """
    schema, name = VD.primary_def(dom, pkg_dir)
    if not schema or not name:
        return []
    target = (schema.get("$defs") or {}).get(name) or {}
    return GL.missing_required(dom, data, target, pkg_dir)


def _check_report(dom: str, data: dict, pkg_dir=None) -> dict:
    """只校验不写盘：原始报错 + 中文可读 + 必填体检。

    第 2 层（2026-09-13）：如果包**声明了引用关系**（`editor/relations.json`），引用校验
    也在这里跑（草稿阶段就能发现填错的引用）。没声明 → 逐项等于改造前。
    报错里的字段中文名/注脚同样**包声明优先**（包自带词汇表）。
    """
    errs = VD.validate_entry(dom, data, pkg_dir)
    if pkg_dir:
        errs = errs + REL.ref_errors(pkg_dir, dom, data)
    return {"ok": not errs, "domain": dom, "errors": errs,
            "friendly": GL.friendly(dom, errs, pkg_dir), "missing": _missing(dom, data, pkg_dir)}


def _render_ref_values(pkg_dir, decl) -> dict:
    """`lookup_label` 的**候选值**（父进程预读 → 放进 payload；子进程不读盘，契约 §1.9/§4.1）。

    只认「`ref` 是常量字符串」的那种写法（运行时才知道的引用值无法预读 —— 子进程就回原值）。
    读盘**只读**（渲染链路零写盘）；目标域读不到 → 空表（不判红、不报错）。
    """
    out: dict = {}
    for _name, spec in ((decl or {}).get("derives") or {}).items():
        if not isinstance(spec, dict) or spec.get("fn") != "lookup_label":
            continue
        args = spec.get("args") or {}
        dom2, ref = args.get("domain"), args.get("ref")
        if not (isinstance(dom2, str) and dom2 and isinstance(ref, str) and ref):
            continue
        if ref in out:
            continue
        by = args.get("by") if args.get("by") in ("key", "name") else "key"
        try:
            vals = REL.ref_candidates(pkg_dir, dom2, by)
        except Exception:                                    # noqa: BLE001 —— 预读失败不拦渲染
            vals = []
        if vals:
            out[ref] = [str(v) for v in vals][:RENDER.MAX_VALUE_ITEMS]
    return out


def _run_view(pkg_dir, dom: str, name: str, data: dict, key: str,
              domains: dict | None = None) -> dict:
    """把 (域, 视图名) 落到**框架内置**实现上 → 视图 JSON（坏数据 → `ok=False`，不炸）。

    内置视图只有 `REL.VIEW_NAMES` 那 5 个（`graph` = `space_view` 别名）；包**不写新代码**。

    ★ 第 3 层·批 1（声明面）：新增 `name="package-render"` 分支 —— 走**纯声明**渲染树
    （`editor/render.py`，不执行任何包代码）。声明坏 / 树建不出 → 返回 `ok=False` + `stage`，
    由调用方按 L3 回退第 2 层（**永远不是 500**）。

    ★ 第 3 层·批 2（派生值）：先走 `RENDER.derived()`（**一次性子进程** + 白名单函数）拿派生值，
    再把这些值交给 `RENDER.build(..., derived=…)` 落树（父侧做回程硬判 + 限额截断）。
    派生期失败（超时/崩/输出超限）→ `ok=False` + `stage` → 仍走 L3 降级（不是 500）。
    没有派生声明 → **不起子进程**（零冷启动；与批 1 逐字节同行为）。
    """
    if name == "package-render":
        # ★批 2 修批 1 的遗留缺陷：HTTP 路由把**整份域文件**（`{key: 条目}` 的映射）当条目数据
        #   喂给树，于是 `{字段}` 插值恒空（直连 `RENDER.build()` 一直是**条目级**，所以批 1
        #   的两条门禁都没测到这条）。这里按 `key` 取**该条目**——契约 §4.1 的 `data` 明写
        #   「**该条目**的数据快照」。取不到 → 空对象（树照建 + 告警，不 500）。
        _e = PK.get_entry(pkg_dir, dom, key)
        data = _e if isinstance(_e, dict) else {}
        decl, decl_w = RENDER.declared(pkg_dir, dom, domains)
        dv = RENDER.derived(pkg_dir, dom, key, data, domains=domains, decl=decl,
                            ref_values=_render_ref_values(pkg_dir, decl))
        if not dv.get("ok"):
            return {"ok": False, "stage": dv.get("stage") or "derive",
                    "message": dv.get("message") or "派生沙箱失败 —— 已回退内置视图",
                    "warnings": list(decl_w) + list(dv.get("warnings") or []),
                    "view": None, "domain": dom, "key": key}
        tree = RENDER.build(pkg_dir, dom, key, data, domains=domains, decl=decl,
                            derived=dv.get("values"))
        if tree.get("ok"):
            merged = list(tree.get("warnings") or [])
            for w in RENDER.tree_problems(tree):        # ★父侧树校验（H1 / 顶层形状；只报不改）
                if w not in merged:
                    merged.append(f"渲染树校验：{w}")
            for w in (dv.get("warnings") or []):
                if w not in merged:
                    merged.append(w)
            tree["warnings"] = merged[:RENDER.MAX_WARNINGS]
            if dv.get("elapsed_ms") is not None:
                tree["derive_elapsed_ms"] = int(dv["elapsed_ms"])
        return tree
    impl = REL.resolved_name(name)
    if impl == "loot_view":
        return LV.build_file(data, key, LV.load_vocab(pkg_dir))
    if impl == "instance_view":
        return IV.build_file(data, key)
    if impl == "space_view":
        return SV.build_file(data, key)
    if impl == "table":
        return TV.build_file(data, key)
    return {"ok": False, "error": f"未知视图：{name}", "warnings": []}


def _warm_caches():
    """启动后**后台预热**：把每个包的「包概览 + 词典 + 动作清单」缓存先建好。

    ★ 由来（2026-09-15 实测，用户反馈「切包要等半天」）：这三条**冷态**各 ~3s
      （`/api/package/orlandia` 2.89s · `/api/glossary?pkg=orlandia` 3.18s · `/api/actions` 6.0s），
      热态都是 0.02s 级。冷态只出现在**服务刚启动后的第一次**切包 —— 后台预热把它挪到
      启动时（用户看不见的地方）。失败静默：预热不成功只是第一次仍旧慢，不影响功能。
    """
    try:
        for p in PK.list_packages(GAMES_DIR):
            pid_ = p.get("id") if isinstance(p, dict) else p
            d = PK.resolve_package(pid_, GAMES_DIR) if pid_ else None
            if not d:
                continue
            try:
                _package_overview(d)
            except Exception:                                   # noqa: BLE001
                pass
            try:
                gkey = (pid_, _glossary_stamp(d))
                if gkey not in _GLOSSARY_CACHE:
                    _GLOSSARY_CACHE[gkey] = _build_glossary_payload(d)
            except Exception:                                   # noqa: BLE001
                pass
            try:
                AC.inventory(d)                                     # 动作清单（自带内容戳缓存）
            except Exception:                                   # noqa: BLE001
                pass
    except Exception:                                           # noqa: BLE001
        pass


def _build_glossary_payload(pkg_dir):
    """`/api/glossary` 的响应体（路由与启动预热共用一份，避免两处漂移）。"""
    return {"ok": True, "domains": GL.all_entries(pkg_dir),
            "groups": GL.all_groups(pkg_dir),
            "widgets": GL.all_widgets(pkg_dir),
            "relations": REL.package_relations(pkg_dir) if pkg_dir else {},
            "views": REL.package_views(pkg_dir) if pkg_dir else {},
            "warnings": (REL.all_warnings(pkg_dir) if pkg_dir else [])
                        + GL.glossary_warnings(pkg_dir)
                        + (RENDER.render_warnings(pkg_dir) if pkg_dir else []),
            "panel_keys": GL.PANEL_KEYS}


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
    print(f"  内置默认集 : {len(PK.DOMAINS)} 个域（**回退用**，包没声明时才兜底）")
    print("  域的真源   : 包内 editor/domains.json（与内置默认集合并；同名以包声明为准）")
    print("  包扩展面   : editor/{domains,relations,views}.json + editor/glossary/<域>.json"
          "（包声明 > 框架默认；坏声明降级不炸）")
    print(f"  校验器     : {'jsonschema' if VD._js is not None else '内置最小校验器'}")
    print("  Ctrl+C 停止")
    print("=" * 68)
    srv = ThreadingHTTPServer((args.host, args.port), H)
    # ★ 启动后**后台预热**（不阻塞起服务）：把各包的「包概览 / 词典 / 动作清单」缓存先建好，
    #   免得用户第一次切包撞上 ~6s 的冷态（实测：冷 2.9s+3.2s+6.0s，热 0.02s 级）。
    try:
        import threading as _th
        _th.Thread(target=_warm_caches, name="warm-caches", daemon=True).start()
    except Exception:                                           # noqa: BLE001
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止")
    finally:
        srv.server_close()
    return 0

# ★ 补丁生效的关键前提（2026-09-15 实测踩坑，症状：试玩接口一律 404「未知接口」）：
#   用 `python editor/server.py` 启动时，本模块的 __name__ 是 `__main__`；
#   而补丁文件 `routes_play.py` 里写的是 `from editor import server as SRV` ——
#   这会**再导入一份** `editor.server`（另一个模块对象）⇒ `SRV.H._api_get = ...` 打在副本的类上，
#   正在服务的那份 `__main__.H` 毫发无损 ⇒ 补丁静默失效。
#   （测试里不暴露：测试是 `import editor.server` 模块式导入，两边是同一个模块 ⇒ 补丁生效 ⇒ 全绿。）
#   修法：显式把 `editor.server` 指向正在运行的 `__main__`，使补丁落到同一个类。
if __name__ == "__main__":
    sys.modules.setdefault("editor.server", sys.modules[__name__])

# B20「试玩」路由（类方法补丁）：必须在 `class H` 定义**之后**导入
from editor import routes_play as _routes_play  # noqa: F401,E402


if __name__ == "__main__":
    sys.exit(main())
