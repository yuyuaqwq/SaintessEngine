# -*- coding: utf-8 -*-
"""官方宿主骨架 —— **命令行适配器**（真能玩：输入一行 = 一条消息）。

这是"接一个平台"的最小实例，也是骨架的冒烟入口：

    python adapter_cli.py --package ../../games/orlandia --db /tmp/demo.db \
        --scenario /tmp/demo-scenario.json --seed 12345

    > /help            # 宿主命令 + 包内声明条数 + 当前生效的可选钩子
    > /battle          # 跑一场演示战斗（示例处理器；正式形态由包内指令声明驱动）
    > /quit            # 收工

三函数就在下面（`recv` / `load_player` / `save_player` / `say`）—— 接自己的平台时，
把 `recv` 换成"从平台事件队列取一条"，把 `say` 换成"发给平台"，其余照抄。

场景文件（`--scenario`）是这场战斗的**输入数据**：玩家档 + 敌组 + 可选掉落池请求，
形状见 `main.Scenario`。为什么让调用方给：挑怪/算数值/选池都是**内容策略**，
不该长在宿主里（包内构造器补齐后，骨架改为问包要，见 README「待接点」）。
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from main import Host, Scenario                          # noqa: E402
from store_sqlite import SQLiteStore                     # noqa: E402

DEFAULT_PACKAGE = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "games", "orlandia")


class CLIAdapter:
    """命令行适配器：三函数 + 可选钩子（`clock` / `rng` / `on_tlog`）。

    `stream` 缺省 = 真 stdin；测试/验证脚本可以塞一个可迭代对象（每项一行）。
    """

    def __init__(self, store, *, stream=None, out=None, seed=None, echo_tlog=True):
        self.store = store
        self.stream = stream if stream is not None else sys.stdin
        self.out = out if out is not None else sys.stdout
        self.seed = seed
        self.echo_tlog = bool(echo_tlog)
        self._eof = False
        self.log_lines: list = []          # 本次会话的 tlog 报文（报告用）
        self.said: list = []               # 本次会话的全部回话

    # ------------------------------------------------------------ ① 收消息 / 认人
    def recv(self):
        """取一条待处理消息；None = 没有新消息（骨架自旋）。

        ctx 的 7 个字段：uid / text / group_id / is_group / at / ts / raw。
        命令行没有群、没有 @，所以 `group_id=None`、`at=[]`、`raw` = 原始行。
        """
        if self._eof:
            return None
        try:
            line = self.stream.readline()
        except (EOFError, KeyboardInterrupt):
            line = ""
        if not line:
            self._eof = True
            return None
        text = line.rstrip("\r\n")
        return {"uid": "cli-1", "text": text, "group_id": None, "is_group": False,
                "at": [], "ts": time.time(), "raw": line}

    # ------------------------------------------------------------ ② 存档读写
    def load_player(self, uid: str):
        return self.store.load_player(uid)

    def save_player(self, uid: str, data: dict) -> None:
        self.store.save_player(uid, data)

    # ------------------------------------------------------------ ③ 回话出口
    def say(self, to: dict, text: str) -> None:
        """**text 已是玩家可见字符串**（渲染属内容，投递属宿主）。"""
        self.said.append(text)
        print(text, file=self.out, flush=True)

    # ------------------------------------------------------------ 可选钩子
    def clock(self) -> float:
        return time.time()

    def rng(self) -> random.Random:
        return random.Random(self.seed)

    def on_tlog(self, record: dict) -> None:
        """流水出口（包只产报文，落库属宿主）。这里打到 stdout + 收进内存。"""
        self.log_lines.append(record)
        if self.echo_tlog:
            fields = ",".join("%s=%s" % (k, v) for k, v in sorted((record.get("fields") or {}).items()))
            print("[tlog] %s actor=%s %s" % (record.get("kind"), record.get("actor"), fields),
                  file=self.out, flush=True)

    def should_stop(self) -> bool:
        """骨架扩展面：EOF / `<ctl>d` → 优雅停机。"""
        return self._eof

    # ------------------------------------------------------------ 存储钩子（可选）
    def load_blob(self, key):
        return self.store.load_blob(key)

    def save_blob(self, key, value):
        self.store.save_blob(key, value)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="宿主骨架 · 命令行适配器")
    p.add_argument("--package", default=DEFAULT_PACKAGE, help="包目录（含 game.json）")
    p.add_argument("--db", default="host-skeleton.db", help="存档库路径（默认当前目录）")
    p.add_argument("--scenario", default="", help="战斗场景 JSON（缺省 = 没有演示战斗）")
    p.add_argument("--seed", type=float, default=None, help="固定随机种子（同种子可复现）")
    p.add_argument("--example-command", default="", help="绑定示例处理器的包内声明 key")
    p.add_argument("--max-messages", type=int, default=None)
    p.add_argument("--idle-timeout", type=float, default=None, help="秒；无新消息则退出")
    p.add_argument("--quiet", action="store_true", help="不回显 battlefield 日志与 tlog")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    scenario = Scenario.from_file(args.scenario) if args.scenario else Scenario()
    store = SQLiteStore(args.db)
    adapter = CLIAdapter(store, seed=args.seed, echo_tlog=not args.quiet)
    host = Host(adapter, args.package, scenario=scenario, seed=args.seed,
                example_command=args.example_command or None, echo_battle=not args.quiet)
    pkg = host.boot()
    print("== 宿主骨架 · CLI ==", flush=True)
    print("包：%s（%d 域，entry=%s，引擎门槛=%s）" % (pkg.id, len(pkg.domains), pkg.entry, pkg.check_engine()),
          flush=True)
    print("声明：%d 条指令（可见 %d）；示例处理器绑定 = %s"
          % (len(host.commands), len(host.commands.visible()), host.example_command or "(无)"), flush=True)
    print("场景：玩家 %d 字段 / 敌组 %d / 掉落请求 %d；存库 = %s"
          % (len(scenario.player), len(scenario.enemies), len(scenario.rewards),
             os.path.abspath(args.db)), flush=True)
    print("输入一行 = 一条消息；%shelp 看命令、%squit 退出。" % (host.prefix, host.prefix), flush=True)
    handled = host.serve_forever(max_messages=args.max_messages, idle_timeout=args.idle_timeout)
    print("-- 会话结束：处理 %d 条消息；回话 %d 段；tlog 报文 %d 条；存档 %d 档"
          % (handled, len(adapter.said), len(adapter.log_lines), store.count()), flush=True)
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
