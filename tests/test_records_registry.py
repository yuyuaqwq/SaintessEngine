#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁：资料表集合的**弱引用注册表** —— 登记序 / 弱引用回收 / 跨集合全有或全无。

跑法：`python tests/test_records_registry.py`（退出码 0 = 全绿）。

守的判据
--------
  ① 自动登记：`RecordsSet(...)` 造出来就进注册表；`sets()` 按**构建序**返回，且返回的是**副本**
     （改返回值不动注册表）。
  ② 弱引用：集合被回收 → 登记随之消失（`del` + `gc.collect()` 后 `sets()` 不含它）；
     零集合时 `reload_all_sets()` 返回 `{}`（不是报错）。
  ③ 跨集合全有或全无（成功面）：多个集合一起换引用，`{集合标识: {域: before/after}}` 结构对得上，
     换完读到的就是新值。
  ④ **一坏全不换**（反证面）：一张表坏 → 抛 `RecordsReloadError` 点名该域；**另一张已备好的表
     也不替换**（读到的仍是旧值）。
"""
from __future__ import annotations

import atexit
import gc
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.records import (                                    # noqa: E402
    RecordsReloadError, RecordsSet, reload_all_sets, sets,
)

PASS = 0
FAIL = 0
TMP = tempfile.mkdtemp(prefix="records_registry_")
atexit.register(shutil.rmtree, TMP, ignore_errors=True)


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "PASS", "FAIL")


def _write(root, sub, domain, table):
    """落一个域文件（缺目录就建；外层是 `{id: 条目}` 映射）。"""
    folder = os.path.join(root, sub)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, domain + ".json"), "w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False)
    return os.path.join(folder, domain + ".json")


def _make(root, spec):
    """造一个集合（放函数里返回：调用方一 `del`，注册表就只剩弱引用）。"""
    return RecordsSet(root, spec)


# ============================================================ ① 零集合 + 空注册表
def t0_empty():
    print("\n【① 零集合：sets() == [] · reload_all_sets() == {}（不是报错）】")
    check("起点注册表为空", sets() == [], sets())
    got = reload_all_sets()
    check("零集合 reload_all_sets() 返回 {}（不是抛错）", got == {}, got)
    check("sets() 返回的是副本（改返回值不动注册表）", _mutates_registry() is False)


def _mutates_registry():
    out = sets()
    out.append("污染")
    return "污染" in sets()


# ============================================================ ② 登记序 + 弱引用
def t1_register_and_weakref():
    print("\n【② 自动登记（构建序）+ 弱引用真会消失】")
    root = os.path.join(TMP, "weak")
    _write(root, "data", "alpha", {"1": {"v": "a"}})
    _write(root, "data", "beta", {"1": {"v": "b"}})

    a = _make(root, {"alpha": {"key_type": int}})
    ghost = _make(root, {"beta": {"key_type": int}})
    c = _make(root, {"alpha": {"key_type": int}, "beta": {"key_type": int}})

    live = sets()
    check("三个集合都自动登记了", len(live) == 3, len(live))
    check("登记序 = 构建序（a → ghost → c）", live == [a, ghost, c],
          [id(x) for x in live])
    check("未读过的集合也在注册表里（不靠 load 触发登记）", c in live)

    ghost_id = id(ghost)
    del live                                    # 别用测试自己的列表强引用住被测对象
    del ghost
    gc.collect()
    after = sets()
    check("回收后 sets() 不含它（弱引用，不是强引用）",
          all(id(x) != ghost_id for x in after) and len(after) == 2, len(after))
    check("存活的集合一个不少（a / c 仍在）", after == [a, c], [id(x) for x in after])

    # 返回副本的再确认（此时注册表非空）
    snapshot = sets()
    snapshot.pop()
    check("sets() 每次返回新列表（弹出不影响注册表）", len(sets()) == len(snapshot) + 1)
    return root, a, c


# ============================================================ ③ 跨集合全有或全无（成功面）
def t2_all_or_nothing_ok(root, a, c):
    print("\n【③ 跨集合一起换：先全部读好，再一起换（成功面）】")
    check("换前 a.alpha 是旧值", a.alpha.get(1)["v"] == "a", a.alpha.get(1))
    check("换前 c.alpha 是旧值", c.alpha.get(1)["v"] == "a", c.alpha.get(1))
    check("换前 c.beta 是旧值", c.beta.get(1)["v"] == "b", c.beta.get(1))

    _write(root, "data", "alpha", {"1": {"v": "a2"}, "2": {"v": "a2b"}})
    _write(root, "data", "beta", {"1": {"v": "b2"}})
    got = reload_all_sets()

    check("结果按集合标识分组（%d 个集合）" % len(sets()), len(got) == len(sets()), got)
    labels = list(got)
    check("每个集合都有自己那张摘要", all(isinstance(v, dict) and v for v in got.values()), got)
    alpha_rows = [v["alpha"] for v in got.values() if "alpha" in v]
    check("alpha 摘要条数 1 → 2（before/after 都是实测值）",
          all(r == {"before": 1, "after": 2} for r in alpha_rows), alpha_rows)
    beta_rows = [v["beta"] for v in got.values() if "beta" in v]
    check("beta 摘要条数 1 → 1", all(r == {"before": 1, "after": 1} for r in beta_rows), beta_rows)
    check("换完 a.alpha 读到新值（2 条）", a.alpha.get(1)["v"] == "a2" and len(a.alpha.all()) == 2,
          a.alpha.all())
    check("换完 c.beta 读到新值", c.beta.get(1)["v"] == "b2", c.beta.get(1))
    check("未变化域也在摘要里（beta 不缺席）", bool(beta_rows), labels)
    return got


# ============================================================ ④ 一坏全不换（反证面）
def t3_one_bad_none_replaced(root, a, c):
    print("\n【④ 反证：一张坏 → 抛错点名该域，**另一张也不换**】")
    before_a = dict(a.alpha.all())
    before_c_beta = dict(c.beta.all())
    # alpha（注册序在前）是好的且换了盘；beta 坏 JSON
    _write(root, "data", "alpha", {"1": {"v": "a3"}})
    with open(os.path.join(root, "data", "beta.json"), "w", encoding="utf-8") as f:
        f.write("{ not json")

    err = None
    try:
        reload_all_sets()
    except RecordsReloadError as exc:                          # noqa: BLE001
        err = exc
    check("坏数据 → 抛 RecordsReloadError", err is not None)
    check("报错点名坏的那个域（beta）", err is not None and err.domain == "beta",
          getattr(err, "domain", None))
    check("报错文本含域与原因", err is not None and "beta" in str(err) and "重载失败" in str(err),
          str(err)[:120])
    check("★ 好的那张（alpha）也没被替换 —— 读到的还是旧值",
          a.alpha.get(1)["v"] == "a2" and dict(a.alpha.all()) == before_a,
          a.alpha.all())
    check("★ 另一集合的 beta 也没被替换", dict(c.beta.all()) == before_c_beta, c.beta.all())
    check("报错后仍可读（旧数据继续可用，进程没崩）", a.alpha.get(1) is not None
          and c.beta.get(1) is not None)


# ============================================================ ⑤ 全回收 → 回到零集合
def t4_release_all():
    print("\n【⑤ 集合全回收 → 注册表回到零（登记不泄漏）】")
    check("回收后 sets() == []", sets() == [], [type(x).__name__ for x in sets()])
    check("回收后 reload_all_sets() 仍返回 {}（不是报错）", reload_all_sets() == {})


def t5_overrides_shape(root):
    """★ set_from_domains 的 overrides 形状守卫（2026-09-29 批次 4 真修的那条）。

    立项依据 = 实跑：原写法 `dict(overrides.pop(name, None) or {})` 的 or 链把
    **falsy 非 dict**（0 / "" / [] / 0.0 / False）静默当成"这个域没有 overrides" ——
    构造照样成功、内容侧把 overrides 写坏在装配期零报错地过去；
    truthy 非 dict（5）则是裸 `TypeError: 'int' object is not iterable`，**不点名是哪个域**。
    两种退化都违反本模块「坏声明装配期即点名抛」的 fail-closed 契约。
    ★ 本节此前**零覆盖**（全门禁 grep 不到 overrides）。
    """
    print(chr(10) + "【⑥ set_from_domains 的 overrides 形状（回落只认 None）】")
    from saintess_engine.records import (                                       # noqa: E402
        RecordsDeclarationError, set_from_domains,
    )

    # 自建一个**完整的包根**（域声明 + 落点表）——上面那个 root 是裸目录，
    # 只够直接造 RecordsSet，走不了 set_from_domains 的声明面。
    pkg = os.path.join(TMP, "ovr")
    os.makedirs(os.path.join(pkg, "editor"), exist_ok=True)
    with open(os.path.join(pkg, "editor", "domains.json"), "w", encoding="utf-8") as f:
        json.dump({"items": {"kind": "data", "order": ["id"]}}, f, ensure_ascii=False)
    _write(pkg, "content/data", "items", {"1": {"id": 1}})

    def _probe(ov):
        try:
            set_from_domains(pkg, ("items",), overrides=ov)
            return None
        except RecordsDeclarationError as e:
            return str(e)
        except Exception as e:                                                 # noqa: BLE001
            return "!!裸" + type(e).__name__ + ":" + str(e)

    # (a) falsy 非 dict 逐个点名（改前这五种全部**静默通过**）
    for nm, v in [("0", 0), ("空串", ""), ("空数组", []), ("0.0", 0.0), ("False", False)]:
        m = _probe({"items": v})
        check("overrides[items]=" + nm + " → 点名 RecordsDeclarationError（不许静默当空）",
              m is not None and not m.startswith("!!"), "静默通过 / 退化: " + repr(m))
        check("overrides[items]=" + nm + " 文案点名域 items",
              m is not None and "items" in m, "没点名域: " + repr(m))
    # (b) truthy 非 dict 也不许退化成裸 TypeError
    m = _probe({"items": 5})
    check("overrides[items]=5 → 点名 RecordsDeclarationError（不许裸 TypeError）",
          m is not None and not m.startswith("!!"), "退化: " + repr(m))
    check("overrides[items]=5 文案点名域 items", m is not None and "items" in m,
          "没点名域: " + repr(m))
    # (c) ★ 合法面钉「不许放松成见谁都抛」—— 这一组最关键
    check("overrides 缺省(None) 仍合法",
          _probe(None) is None, "被误伤: " + repr(_probe(None)))
    check("overrides={} 仍合法", _probe({}) is None, "被误伤: " + repr(_probe({})))
    check("overrides[items]={'order':['id']} 仍合法",
          _probe({"items": {"order": ["id"]}}) is None, "被误伤")
    check("overrides[items]={} （显式空对象）仍合法",
          _probe({"items": {}}) is None, "被误伤: " + repr(_probe({"items": {}})))
    # (d) 既有的两条 fail-closed 语义不许被这次改动碰坏
    m = _probe({"items": {"sub": "x"}})
    check("overrides 里手抄 sub 仍被点名拒绝",
          m is not None and "sub" in m, "退化: " + repr(m))
    m = _probe({"未请求的域": {"order": ["id"]}})
    check("overrides 里有未请求的域 仍被点名拒绝（不静默忽略）",
          m is not None and not m.startswith("!!"), "退化: " + repr(m))


def main() -> int:
    print("== 门禁：资料表集合弱引用注册表 ==")
    t0_empty()
    root, a, c = t1_register_and_weakref()
    t2_all_or_nothing_ok(root, a, c)
    t3_one_bad_none_replaced(root, a, c)
    del a, c
    gc.collect()
    t4_release_all()
    t5_overrides_shape(root)
    print("-" * 56)
    print("通过 %d · 失败 %d" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
