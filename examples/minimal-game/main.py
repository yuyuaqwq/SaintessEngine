# -*- coding: utf-8 -*-
"""《铆炉回声》最小示例 —— 跑完一场战斗并打印日志。"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                                                  # import content
_REPO = os.path.dirname(os.path.dirname(_HERE))                            # 框架根（saintess_engine 所在）
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "extends"))                 # 扩展包目录（ext_combat / ext_economy 的家）

# ★ 自举说明：上面三行是**自包含**的 —— 本示例不靠 PYTHONPATH、不靠仓根 conftest/.pth，
# 照抄这个文件的第三方拿到的是同一个可运行骨架。门禁曾经给测试进程注入 extends/
# 才让它绿，那是门禁替示例兜了底，掩盖了「文档里写的命令跑不通」。

from ext_combat import Battle                                  # noqa: E402
from content import apply_game_content                           # noqa: E402
from content.data.classes import build_player                    # noqa: E402
from content.data.monsters import build_monster                  # noqa: E402


def main():
    hero = build_player("cls_kiln", "p1", "铆炉匠·阿铆", level=6)
    foes = [build_monster("rustmite", "e1"), build_monster("ironbuoy", "e2")]
    for actor in [hero] + foes:
        apply_game_content(actor)              # ← 内容装配入口（幂等）
    battle = Battle(btype="monster", sides={"player": [hero], "enemy": foes})
    logs = [f"⚔ 战斗开始：{hero['name']} VS {'、'.join(f['name'] for f in foes)}"]
    battle.auto_run(logs)                      # 全自动跑到胜负判定
    print("\n".join(logs))
    print(f"\n🏁 {battle.result} —— {hero['name']} 剩余 {hero['hp']}/{hero['max_hp']}")
    return 0 if battle.result == "victory" else 1


if __name__ == "__main__":
    raise SystemExit(main())
