# -*- coding: utf-8 -*-
"""B20 待合并片段：编辑器「试玩」路由（**不改 `editor/server.py`**，靠类方法补丁挂载）。

合并方式（一句话）：把本文件整体放进 `editor/`（建议名 `editor/routes_play.py`），
在 `editor/server.py` 顶部 import 区加一行 `from editor import routes_play  # noqa: F401`，
并在 `if __name__ == "__main__":` 之前、`main()` 之后**任意位置**保留该 import 即可 ——
完整说明见 `MERGE_NOTES.md`（含插入位置与冲突面）。

本文件在 `server.py` 未改动的前提下可用（测试 `tests/test_editor_play.py` 的 HTTP 段即这样跑）：

    import editor.routes_play       # 打补丁（幂等）
    import editor.server as SRV
    ThreadingHTTPServer(("127.0.0.1", 0), SRV.H)     # 正常起服务即可

端点
----
    GET  /api/package/<id>/play/commands    → 本包指令清单（声明口径，194 条）
    GET  /api/package/<id>/play             → 同上 + 环境探测（discover：包/宿主/引擎根）
    POST /api/package/<id>/play             → 跑命令序列
                                              body: {"commands": [...], "seed": 1,
                                                     "uid": "u1", "group_id": "g1"}
                                              回：{"ok", "stage", "rows": [...], "digests_sha", ...}

零引擎 import：本文件只 import `editor.play`（父进程侧驱动），后者只起子进程。
"""
from __future__ import annotations

import traceback
from urllib.parse import unquote, urlparse

from editor import server as SRV

_orig_api_get = SRV.H._api_get
_orig_mutate = SRV.H._mutate


def _pkg_dir_for(handler, pkg_id: str):
    """包 id → 目录（与服务器同口径 `PK.resolve_package(id, GAMES_DIR)`）。"""
    try:
        return SRV.PK.resolve_package(pkg_id, SRV.GAMES_DIR)
    except Exception:                     # noqa: BLE001
        return None


def _play_list(handler, pkg_id: str):
    from editor import play as PLAY
    d = _pkg_dir_for(handler, pkg_id)
    if not d:
        return handler._err(404, "包不存在：%s" % pkg_id)
    res = PLAY.list_commands(d)
    if not res.get("ok"):
        return handler._err(400, res.get("message") or "读不到指令表")
    return handler._send(200, {"ok": True, "package": pkg_id,
                               "count": res["count"], "commands": res["commands"],
                               "env": PLAY.discover(d)})


# ============================================================
# B20_ROUTES_BEGIN
# ============================================================
def _api_get(self, parts: list):
    """GET 侧补丁：`/api/package/<id>/play[/commands]`。

    注意 `parts` 是**剥掉 `api` 之后**的段（见 `server.py::do_GET`：`parts[1:]` 传进来），
    所以这里匹配 `["package", <id>, "play"(, "commands")]`；`_mutate` 侧则是整路径。
    """
    if (len(parts) >= 3 and parts[0] == "package"
            and parts[2] in ("play", "play_commands")):
        try:
            if len(parts) == 3 or (len(parts) == 4 and parts[3] == "commands"):
                return _play_list(self, parts[1])
        except Exception:                 # noqa: BLE001
            return self._err(500, "试玩路由内部错误", traceback=traceback.format_exc())
    return _orig_api_get(self, parts)


def _mutate(self, method: str):
    """POST 侧补丁：POST /api/package/<id>/play（跑命令序列）。"""
    p = urlparse(self.path)
    parts = [unquote(x) for x in p.path.strip("/").split("/") if x]
    if (method == "POST" and len(parts) == 4 and parts[0] == "api"
            and parts[1] == "package" and parts[3] == "play"):
        try:
            body = self._body()
            from editor import play as PLAY
            d = _pkg_dir_for(self, parts[2])
            if not d:
                return self._err(404, "包不存在：%s" % parts[2])
            commands = body.get("commands") or []
            if isinstance(commands, str):
                commands = [ln.strip() for ln in commands.splitlines() if ln.strip()]
            if not isinstance(commands, list):
                return self._err(400, "commands 需为字符串数组或按行文本")
            if not commands:
                return self._err(400, "commands 不能为空")
            res = PLAY.run(d, commands,
                           seed=body.get("seed", 1),
                           uid=body.get("uid") or "u1",
                           group_id=body.get("group_id") or "g1",
                           clock=body.get("clock"),
                           db=body.get("db") or "")
            code = 200 if res.get("stage") in ("done", "audit") else 502
            return self._send(code, res)
        except Exception:                 # noqa: BLE001
            return self._err(500, "试玩路由内部错误", traceback=traceback.format_exc())
    return _orig_mutate(self, method)


SRV.H._api_get = _api_get
SRV.H._mutate = _mutate
# ============================================================
# B20_ROUTES_END
# ============================================================


__all__ = []
