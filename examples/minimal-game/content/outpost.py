# -*- coding: utf-8 -*-
"""《铆炉回声》——据点勘探：**只写数据 + 声明**的小闭环。

做数据包的人在这里只做五件事，通用机制全由引擎给：

    据点资料表   records.Records    读 content/data/sites.json（键型 / 顺序自己声明）
    访问记录表   store.declare      一份 TableSpec 声明建表 → 拿回 Repository 读写
    派/到点/收   produce.Jobs       计时、到点判定、清槽都在引擎，本文件零比较
    取句柄      wire.Wire           db / clock / jobs / log 四个句柄，取不到即报错
    据点加成     bonus.Bonus        按来源标签幂等回写，跨据点、跨档域自动合并

本文件不解析原始资料文件、不拼 SQL 字面量、不读环境变量、不写死路径、不接队列 ——
换一款游戏只换 sites.json 与本文件的字段名。
"""
from __future__ import annotations

from saintess_engine.bonus import Bonus
from saintess_engine.clock import wall
from saintess_engine.produce import Job, Jobs
from saintess_engine.records import Records
from saintess_engine.store import Column, TableSpec, declare
from saintess_engine.wire import Wire

DAY = 86400
SITE_ORDER = ("bottle_reef", "kiln_wreck", "salt_vein", "tide_mill")
VISIT_SPEC = TableSpec("outpost_visits", [
    Column("member", "TEXT", pk=True),
    Column("site_id", "TEXT", pk=True),
    Column("visits", "INTEGER", notnull=True, default=0),
    Column("last_day", "TEXT", notnull=True, default=""),
])


class Outpost:
    """据点勘探闭环：派队员 → 到点收取 → 记访问次数/日期 → 据点加成生效。"""

    def __init__(self, pack_dir, wire: Wire) -> None:
        self.clock = wire.handle("clock")
        self.log = wire.log
        self.db = wire.handle("db")
        self.sites = Records(pack_dir, "sites", sub="content/data",
                             key_type=str, order=SITE_ORDER)
        self.visits = declare(self.db, VISIT_SPEC)
        self.jobs = Jobs(wire.handle("jobs"), self.clock, max_slots=1,
                         key=lambda member: "outpost:jobs:%s" % (member,))
        self.bonus = Bonus()

    def site(self, site_id):
        """据点资料一条；查不到 → 显式报错（不静默给默认值）。"""
        row = self.sites.get(site_id)
        if row is None:
            raise KeyError("没有这个据点：%r（表里：%s）" % (site_id, sorted(self.sites.all())))
        return row

    def dispatch(self, member, site_id, *, now=None):
        """派队员去据点：开一条计时作业（已在跑 → 引擎 AlreadyBusy，不顶掉旧的）。"""
        site = self.site(site_id)
        at = int(self.clock() if now is None else now)
        ends_at = at + int(site["days"]) * DAY
        self.jobs.begin(member, Job("outpost", at, ends_at, {"site_id": site_id}))
        return {"member": member, "site": site_id, "ends_at": ends_at,
                "remaining": ends_at - at}

    def collect(self, member, *, now=None):
        """到点收取：未到点 → None（作业原样不动）；到点 → 记访问 + 更新据点加成。"""
        job = self.jobs.settle(member, now=now)
        if job is None:
            return None
        site_id = job.payload["site_id"]
        site = self.site(site_id)
        day = wall.day_key()
        visits = self._bump(member, site_id, day)
        value = min(visits, int(site["bonus_max_visits"])) * int(site["bonus_per_visit"])
        self.bonus.add(site["bonus_domain"], "site:%s" % (site_id,), value)
        self.log.info("据点收取：%s 到 %s 第 %d 次（%s）", member, site_id, visits, day)
        return {"member": member, "site": site_id, "visits": visits, "day": day,
                "find": site.get("find"),
                "bonus": self.bonus.resolve(site["bonus_domain"])}

    def record(self, member, site_id):
        """读访问记录（没去过 → None）；读写都在 Repository 上，本文件不拼 SQL。"""
        with self.db.readonly() as conn:
            return self.visits.get(conn, member, site_id)

    def _bump(self, member, site_id, day):
        """访问次数 +1、记下当天（读改写全走 Repository，一行 SQL 都没有）。"""
        with self.db.session() as conn:
            row = self.visits.get(conn, member, site_id) or {}
            visits = int(row.get("visits", 0)) + 1
            self.visits.upsert(conn, {"member": member, "site_id": site_id,
                                      "visits": visits, "last_day": day})
        return visits
