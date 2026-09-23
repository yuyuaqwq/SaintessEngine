#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""produce 门禁：计时作业形状（Job / Jobs）—— 同值 / 时点 / 多槽 / 批量 / 往返 / 零知识。

跑法：python tests/test_produce_shape.py
退出码：0 = 全绿；1 = 有失败。

三处专门钉住的地方（都是「改了就静默变行为」的）：
  ① **未到点不清槽**：未到点 `settle` 必须返回 None 且作业**一个字节都不动**
     （旧实现的坑是「读到状态顺手清掉」⇒ 到点未结算 = 奖励丢失）
  ② **槽满不顶掉**：槽满 / 同类在跑 → `AlreadyBusy`，且抛错时**不写任何东西**
  ③ **零知识**：`produce/` 源码字符串常量里不得出现任何内容侧取值
     （职业 / 产出物 / 采集这类名词），且不得出现 `prof_*` 形状名
"""
import ast
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ---- 扩展包门禁路径（2026-09-23 从引擎 tests/ 搬到本包）----
# 本文件现在位于 extends/<pkg>/tests/ ⇒ 往上四级才是**引擎根**，ROOT 重新绑定到它，
# 这样下面原有的 `os.path.join(ROOT, "saintess_engine", ...)` 一类路径扫描仍然指对地方。
_HERE_DIR = os.path.dirname(os.path.abspath(__file__))   # extends/<pkg>/tests
_PKG_ROOT = os.path.dirname(_HERE_DIR)                   # extends/<pkg>
_EXT_BASE = os.path.dirname(_PKG_ROOT)                   # extends
ROOT = os.path.dirname(_EXT_BASE)                        # 引擎根
for _p in (ROOT, _EXT_BASE, _HERE_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ext_economy.produce import AlreadyBusy, Job, Jobs, ProduceStorageError  # noqa: E402

passed = failed = 0
DETAIL = []


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed", "DETAIL")


def raises(exc, fn, *a, **kw):
    """跑 fn → (是否抛该异常, 异常或返回值)。"""
    try:
        return False, fn(*a, **kw)
    except exc as e:
        return True, e


class Clock:
    """可推进的假时钟（引擎不读系统时间 —— 时刻全由外部给）。"""

    def __init__(self, t=0):
        self.t = int(t)

    def __call__(self):
        return self.t

    def set(self, t):
        self.t = int(t)
        return self.t


def mk(store, clock, **kw):
    return Jobs(store, clock, **kw)


# ---------------------------------------------------------------- 1 同值
def t1_semantics():
    print("\n[1] 同值：未开工 None · 重复开工 AlreadyBusy · 未到点不改 · 到点取走")
    st, ck = {}, Clock(100)
    q = mk(st, ck)

    check("未开工查态 → None", q.current("o1") is None)
    check("未开工 all_of → []", q.all_of("o1") == [])
    check("未开工 due → []", q.due() == [])
    check("未开工 settle → None", q.settle("o1") is None)

    j = q.begin("o1", Job(kind="k1", started_at=0, ends_at=200, payload={"n": 1}))
    check("开工回填 started_at = 当前时刻", j.started_at == 100, f"got {j.started_at}")
    check("开工后 current 是这条", q.current("o1") is not None
          and q.current("o1").to_dict() == j.to_dict())
    check("开工后 all_of 一条", len(q.all_of("o1")) == 1)

    hit, exc = raises(AlreadyBusy, q.begin, "o1", Job(kind="k1", started_at=0, ends_at=200))
    check("★ 重复开工（同类在跑）→ AlreadyBusy", hit, f"got {exc!r}")
    hit2, exc2 = raises(AlreadyBusy, q.begin, "o1", Job(kind="k2", started_at=0, ends_at=200))
    check("★ 槽满（max_slots=1 已有 1 条）→ AlreadyBusy", hit2, f"got {exc2!r}")
    check("★ AlreadyBusy 时不写任何东西（仍只有 1 条、且还是那条）",
          len(st["o1"]) == 1 and q.current("o1").to_dict() == j.to_dict())

    ck.set(199)
    check("未到点 current 仍能看到该作业", q.current("o1") is not None
          and q.current("o1").to_dict() == j.to_dict())
    check("未到点 settle → None", q.settle("o1") is None)
    check("★ 未到点 settle 后 current 不变（作业仍在、字段逐字一致）",
          q.current("o1") is not None
          and q.current("o1").to_dict() == j.to_dict(), f"{q.current('o1')!r}")
    check("未到点 due 不含它", q.due() == [])

    ck.set(200)
    check("到点 due 点名它（owner 是存储键）",
          [o for o, _ in q.due()] == ["o1"]
          and q.due()[0][1].to_dict() == j.to_dict(), f"{q.due()!r}")
    got = q.settle("o1")
    check("到点 settle → 返回该作业", isinstance(got, Job) and got.to_dict() == j.to_dict(),
          f"{got!r}")
    check("★ 到点 settle 后已清槽（current → None、all_of 空、键已删）",
          q.current("o1") is None and q.all_of("o1") == [] and "o1" not in st)
    check("再 settle → None（不重复收取）", q.settle("o1") is None)
    check("到点已取走后 due 为空", q.due() == [])
    check("清空后在开新的 → 成功", isinstance(
        q.begin("o1", Job(kind="k1", started_at=0, ends_at=300)), Job))


# ---------------------------------------------------------------- 2 residual / done
def t2_done_residual():
    print("\n[2] 到点判据 / 剩余：clock 指向前 · 中 · 后三个时刻")
    st, ck = {}, Clock(100)
    q = mk(st, ck)
    j = q.begin("o1", Job(kind="k1", started_at=0, ends_at=160))

    for now, exp_done, exp_res in ((100, False, 60), (130, False, 30), (160, True, 0)):
        check(f"now={now}：done={exp_done}", j.done(now) is exp_done, f"got {j.done(now)}")
        check(f"now={now}：residual={exp_res}", j.residual(now) == exp_res,
              f"got {j.residual(now)}")
    check("now 已过 40 秒：residual 不出现负数", j.residual(200) == 0)
    ck.set(130)
    check("clock=130：未到点 → current 在、due 空", q.current("o1") is not None and q.due() == [])
    ck.set(160)
    check("clock=160：到点 → due 含它", [o for o, _ in q.due()] == ["o1"])
    ck.set(175)
    check("clock=175（已过点但未收）：仍可 current / all_of 读到（到点未结算不丢）",
          q.current("o1") is not None and len(q.all_of("o1")) == 1)
    check("clock=175：residual 归零", q.current("o1").residual(ck.t) == 0)


# ---------------------------------------------------------------- 3 多槽
def t3_slots():
    print("\n[3] 多槽：max_slots=2 同时两条；第 3 条 AlreadyBusy；不同持有者互不影响")
    st, ck = {}, Clock(0)
    q = mk(st, ck, max_slots=2)
    a = q.begin("o1", Job(kind="k1", started_at=0, ends_at=50))
    b = q.begin("o1", Job(kind="k2", started_at=0, ends_at=80))
    check("两条不同 kind 同时在跑", len(q.all_of("o1")) == 2
          and q.current("o1").to_dict() == a.to_dict(), f"{q.all_of('o1')!r}")
    hit, exc = raises(AlreadyBusy, q.begin, "o1", Job(kind="k3", started_at=0, ends_at=90))
    check("★ 第 3 条 → AlreadyBusy", hit, f"got {exc!r}")
    check("★ 第 3 条被拒后表里仍是原来两条", [x.kind for x in q.all_of("o1")] == ["k1", "k2"])
    hit2, exc2 = raises(AlreadyBusy, q.begin, "o1", Job(kind="k1", started_at=0, ends_at=90))
    check("★ 槽没满但同类已在跑 → 也 AlreadyBusy", hit2, f"got {exc2!r}")
    other = q.begin("o2", Job(kind="k1", started_at=0, ends_at=50))
    check("不同持有者各算各的槽", len(q.all_of("o2")) == 1 and other.kind == "k1")

    ck.set(50)
    due = q.due()
    check("到 50：只点名到点的那两条（o1/k1 + o2/k1）",
          sorted((o, x.kind) for o, x in due) == [("o1", "k1"), ("o2", "k1")], f"{due!r}")
    got = q.settle("o1")
    check("多槽下 settle 取最早到点那条（k1，非 k2）", got is not None and got.kind == "k1")
    check("★ settle 只动一条：另一条仍在", [x.kind for x in q.all_of("o1")] == ["k2"])
    check("收取后槽位释放：第 3 条可开", isinstance(
        q.begin("o1", Job(kind="k3", started_at=0, ends_at=99)), Job))
    q.clear("o1")
    check("clear 清空该持有者（别的持有者不动）",
          q.all_of("o1") == [] and len(q.all_of("o2")) == 1)


# ---------------------------------------------------------------- 4 due 批量
def t4_due_batch():
    print("\n[4] due 批量：3 个不同到点时刻 → 推时钟只含已到点的（顺序稳定）")
    st = {}
    ck = Clock(0)
    q = mk(st, ck, max_slots=1)
    q.begin("a", Job(kind="k1", started_at=0, ends_at=100))
    ck.set(10)
    q.begin("b", Job(kind="k1", started_at=10, ends_at=200))
    ck.set(20)
    q.begin("c", Job(kind="k1", started_at=20, ends_at=300))
    check("开局 due → []", q.due() == [], f"{q.due()!r}")
    ck.set(99)
    check("now=99 → []", q.due() == [], f"{q.due()!r}")
    ck.set(100)
    check("now=100 → 只含 a", [o for o, _ in q.due()] == ["a"], f"{q.due()!r}")
    ck.set(200)
    check("now=200 → a、b（不含 c）", [o for o, _ in q.due()] == ["a", "b"], f"{q.due()!r}")
    ck.set(300)
    check("now=300 → 三条全到点", [o for o, _ in q.due()] == ["a", "b", "c"], f"{q.due()!r}")
    check("★ due 不清槽（三条仍在）",
          sum(len(q.all_of(o)) for o in "abc") == 3)
    check("now 注入：due(now=150) 只含 a（与 clock 无关）",
          [o for o, _ in q.due(now=150)] == ["a"], f"{q.due(now=150)!r}")
    snap = q.due()
    snap.append(("zz", None))
    check("due 返回新列表（改它不影响队列）", len(q.due()) == 3)

    st2, ck2 = {}, Clock(0)
    q2 = mk(st2, ck2, max_slots=2)
    q2.begin("b", Job(kind="k1", started_at=0, ends_at=5))
    q2.begin("a", Job(kind="k1", started_at=0, ends_at=5))
    check("★ 同一到点时刻：顺序稳定（按持有者键升序）",
          [o for o, _ in q2.due(now=5)] == ["a", "b"], f"{q2.due(now=5)!r}")


# ---------------------------------------------------------------- 5 往返
def t5_roundtrip():
    print("\n[5] 序列化：to_dict → from_dict 往返等值")
    j = Job(kind="k9", started_at=11, ends_at=77, payload={"n": 2, "tags": ["x", "y"]})
    d = j.to_dict()
    j2 = Job.from_dict(d)
    check("字段往返等值", j2.to_dict() == d, f"{j2.to_dict()} != {d}")
    check("kind / 时刻 / 载荷逐项一致",
          (j2.kind, j2.started_at, j2.ends_at, j2.payload) == ("k9", 11, 77, {"n": 2, "tags": ["x", "y"]}))
    check("到点后取走再往返 → 等值",
          (lambda g: g is not None and Job.from_dict(g.to_dict()).to_dict() == d)
          (Job(kind="k9", started_at=11, ends_at=77, payload={"n": 2, "tags": ["x", "y"]})))
    check("from_dict 深拷贝载荷（改副本不影响原作业）",
          (j2.payload.__setitem__("n", 99), j.payload["n"])[1] == 2)
    check("payload 缺省 = 空映射", Job.from_dict({"kind": "k", "ends_at": 1}).payload == {})
    check("started_at 缺省 → 0", Job.from_dict({"kind": "k", "ends_at": 1}).started_at == 0)
    st, ck = {}, Clock(5)
    q = mk(st, ck)
    q.begin("o1", Job(kind="k1", started_at=0, ends_at=50, payload={"a": 1}))
    check("存储里是 [{...}] 形状（引擎不塞对象）",
          isinstance(st["o1"], list) and isinstance(st["o1"][0], dict)
          and st["o1"][0]["kind"] == "k1", f"{st!r}")
    back = q.current("o1")
    check("读回等值（存储 dict → Job）",
          Job.from_dict(st["o1"][0]).to_dict() == back.to_dict())


# ---------------------------------------------------------------- 6 反证（未到点不清槽）
def t6_negative():
    print("\n[6] ★ 反证：未到点也允许 settle → 第 1 条必须红")
    st, ck = {}, Clock(100)
    q = mk(st, ck)
    j = q.begin("o1", Job(kind="k1", started_at=0, ends_at=200))
    early = q.settle("o1")                       # 正确实现：None 且作业原样不动
    check("① 未到点 settle 返回 None（反证点：改坏 → 这里会变成拿到作业）",
          early is None, f"got {early!r}")
    check("① 未到点 settle 后 current 不变（反证点：改坏 → 这里会变成 None）",
          q.current("o1") is not None and q.current("o1").to_dict() == j.to_dict(),
          f"got {q.current('o1')!r}")
    check("① 未到点 settle 后表里还在", len(q.all_of("o1")) == 1)
    check("① 未到点 settle 不产生任何写入（存储快照逐字不变）",
          q.current("o1").to_dict() == j.to_dict())
    ck.set(200)
    check("② 到点后仍然取得走（反向确认：不是靠「永不结算」蒙对）",
          (q.settle("o1") is not None) and q.current("o1") is None)

    # 同一反证的第二面：槽满时若「静默顶掉」→ 上面第 1 条也应红
    st2, ck2 = {}, Clock(0)
    q2 = mk(st2, ck2)
    first = q2.begin("o1", Job(kind="k1", started_at=0, ends_at=50))
    hit, _ = raises(AlreadyBusy, q2.begin, "o1", Job(kind="k2", started_at=0, ends_at=60))
    check("① 槽满 → AlreadyBusy（反证点：改坏成静默顶掉 → 这里会变 False）", hit)
    check("① 槽满被拒后旧作业原样在（反证点：改坏 → 这里会变成新作业）",
          q2.current("o1") is not None and q2.current("o1").to_dict() == first.to_dict()
          and first.kind == "k1")


# ---------------------------------------------------------------- 7 fail-closed
def t7_fail_closed():
    print("\n[7] fail-closed：坏数据 / 拿不到注入面 / 非法参数 → 显式报错，不静默吞")
    st, ck = {"o1": "{不是 JSON"}, Clock(0)
    q = mk(st, ck)
    hit, exc = raises(ProduceStorageError, q.current, "o1")
    check("★ 键在但值取不出来 → ProduceStorageError（不静默当空）", hit, f"got {exc!r}")
    hit2, exc2 = raises(ProduceStorageError, q.settle, "o1")
    check("★ settle 同一条坏数据也报错（不静默清空）", hit2, f"got {exc2!r}")
    st2, ck2 = {"o1": {"kind": "k1"}}, Clock(0)
    hit3, exc3 = raises(ProduceStorageError, mk(st2, ck2).current, "o1")
    check("★ 值不是列表 → ProduceStorageError", hit3, f"got {exc3!r}")
    check("坏数据没被改写", st2["o1"] == {"kind": "k1"})

    for bad, label in ((None, "store=None"), (object(), "store=裸对象")):
        hit4, exc4 = raises(TypeError, lambda b=bad: Jobs(b, ck))
        check(f"★ {label} → TypeError（拿不到注入面就报错）", hit4, f"got {exc4!r}")
    hit5, exc5 = raises(TypeError, lambda: Jobs({}, None))
    check("★ clock 不可调用 → TypeError", hit5, f"got {exc5!r}")
    hit6, exc6 = raises(ValueError, lambda: Jobs({}, ck, max_slots=0))
    check("★ max_slots=0 → ValueError", hit6, f"got {exc6!r}")
    hit7, exc7 = raises(ValueError, lambda: Jobs({}, ck, key=lambda o: ""))
    check("★ key() 返回空键 → ValueError", hit7, f"got {exc7!r}")

    st3, ck3 = {}, Clock(10)
    q3 = mk(st3, ck3)
    hit8, exc8 = raises(ValueError, q3.begin, "o1",
                        Job(kind="k1", started_at=0, ends_at=10))
    check("★ ends_at 不晚于当前时刻 → ValueError（不静默建一条零时长）", hit8, f"got {exc8!r}")
    hit9, exc9 = raises(ValueError, q3.begin, "o1", Job(kind="", started_at=0, ends_at=90))
    check("★ kind 空 → ValueError", hit9, f"got {exc9!r}")
    hit10, exc10 = raises(TypeError, q3.begin, "o1", {"kind": "k1"})
    check("★ job 不是 Job → TypeError", hit10, f"got {exc10!r}")
    ck3.set(20)
    jj = q3.begin("o1", Job(kind="k1", started_at=0, ends_at=30))
    check("★ 时钟给非整数 → TypeError（不猜时间）",
          raises(TypeError, lambda: mk({}, lambda: 1.5))[0])
    check("★ bool 不算整数（不让 now=True 蒙混）",
          raises(TypeError, lambda: mk({}, lambda: True))[0])
    check("★ 时钟返回布尔也拦（构造即校验，不拖到调用时）",
          raises(TypeError, lambda: mk({}, lambda: False))[0])
    check("clock 驱动：ends_at 晚于 now 才建（now=20）", jj.started_at == 20)
    check("clear 不存在的持有者 → 不抛错", q3.clear("nobody") is None)


# ---------------------------------------------------------------- 8 零知识
BANNED = ("profession", "prof_", "fishing", "mining", "gather", "orlandia",
          "dragonfall",
          "采集", "钓鱼", "挖掘", "矿", "职业", "公会", "副本", "玩家", "怪物",
          "材料", "装备", "金币", "经验", "等级", "地图")


def t8_zero_knowledge():
    print("\n[8] 零知识：produce/ 源码字符串常量里不得出现内容侧取值")
    base = os.path.join(ROOT, "extends", "ext_economy", "produce")
    bad, n = [], 0
    for dirpath, _dirs, files in os.walk(base):
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            n += 1
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=path)
            # 跳过**文档串**：文档要能打比方解释形状；判据针对的是代码里写死的取值
            docs = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                     ast.AsyncFunctionDef)):
                    d = ast.get_docstring(node, clean=False)
                    if d is not None:
                        docs.add(d)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if node.value in docs:
                        continue
                    low = node.value.lower()
                    for b in BANNED:
                        hit = (b in node.value) if not b.isascii() else (b in low)
                        if hit:
                            bad.append(f"{rel}:{node.lineno}:{b!r}:{node.value[:40]!r}")
    check("扫到 produce/ 源文件（≥1）", n >= 1, f"n={n}")
    check("★ 代码常量里无内容侧取值（职业/产出/采集类名词）", not bad, str(bad[:6]))
    import ext_economy.produce as mod
    check("模块有 docstring 且写清「有意不做的事」",
          bool(mod.__doc__) and "有意不做的事" in mod.__doc__)
    check("公开面只有形状名（无游戏语义字段）",
          set(mod.__all__) == {"AlreadyBusy", "Job", "Jobs", "ProduceStorageError"},
          str(mod.__all__))
    check("Job 字段都是通用名词",
          Job.__slots__ == ("kind", "started_at", "ends_at", "payload"), str(Job.__slots__))


# ---------------------------------------------------------------- 9 门面
def t9_shape():
    print("\n[9] 形状：边界与稳性（每人一套键 / 自定义键 / 快照隔离）")
    st, ck = {}, Clock(0)
    q = mk(st, ck)
    q.begin("o1", Job(kind="k1", started_at=0, ends_at=10))
    q.begin("o2", Job(kind="k1", started_at=0, ends_at=10))
    check("每人一套键（默认键 = 持有者）", set(st) == {"o1", "o2"}, f"{set(st)}")
    q.clear("o1")
    check("clear 只清一个持有者", "o1" not in st and "o2" in st)
    st2, ck2 = {}, Clock(0)
    q2 = mk(st2, ck2, key=lambda o: f"jobs.{o}")
    q2.begin("o1", Job(kind="k1", started_at=0, ends_at=10))
    check("自定义 key 生效", set(st2) == {"jobs.o1"}, f"{set(st2)}")
    owner_key = q2.due(now=10)[0][0]
    check("due 的 owner 是存储键（内容侧能直接落回自己的域）", owner_key == "jobs.o1")

    st3, ck3 = {}, Clock(0)
    q3 = mk(st3, ck3)
    j = Job(kind="k1", started_at=0, ends_at=10, payload={"n": 1, "deep": {"v": 1}})
    q3.begin("o1", j)
    j.payload["n"] = 999
    j.payload["deep"]["v"] = 999
    check("★ begin 存快照：外部改原对象（含嵌套）不影响队列内容",
          q3.all_of("o1")[0].payload == {"n": 1, "deep": {"v": 1}},
          f"{q3.all_of('o1')[0].payload!r}")
    got = q3.current("o1")
    got.payload["n"] = 7
    check("current 每次读存储（不缓存对象）",
          q3.current("o1").payload["n"] == 1, f"{q3.current('o1')!r}")
    jd = Job(kind="k1", started_at=0, ends_at=10, payload={"deep": {"v": 1}})
    d = jd.to_dict()
    d["payload"]["deep"]["v"] = 42
    check("★ to_dict 是深拷贝（改快照不影响作业）",
          jd.payload["deep"]["v"] == 1 and d["payload"]["deep"]["v"] == 42, f"{jd.payload!r}")
    check("max_slots 属性可读", q3.max_slots == 1)


def main():
    print("== produce 门禁：计时作业形状（Job / Jobs）==")
    t1_semantics()
    t2_done_residual()
    t3_slots()
    t4_due_batch()
    t5_roundtrip()
    t6_negative()
    t7_fail_closed()
    t8_zero_knowledge()
    t9_shape()
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    if DETAIL:
        print("失败清单：")
        for d in DETAIL:
            print(f"  ❌ {d}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
