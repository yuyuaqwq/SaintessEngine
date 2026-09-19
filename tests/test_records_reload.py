#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""records 显式重载门禁：生效 / 不自动检查 / 原子 / 全有或全无 / 幂等 / 顺序守卫 / 零知识。

跑法：python tests/test_records_reload.py
退出码：0 = 全绿；1 = 有失败。

钉住的都是「错了就半成品 / 静默丢数据 / 静默错值」的地方：
  ① **显式才生效**：改了文件不 reload 读到的仍是旧版（不做自动 mtime 检查）
  ② **变更摘要**：每个域一条 before → after，**没有变化的域也在**
  ③ **原子**：坏 JSON / 缺文件 / 顶层非映射 → `RecordsReloadError` 且旧表逐字节不变
  ④ **全有或全无**：`RecordsSet.reload_all()` 一份坏 → 一张也不换
  ⑤ **幂等**：同一份文件 reload 两次 → 摘要与内容一致
  ⑥ **顺序守卫**：域里多 / 少一条 → 抛错且不替换
  ⑦ **索引随表换**：reload 后旧索引缓存不得残留；drop / 键还原在重载路径同样生效
  ⑧ **零知识**：records 源码不得出现具体游戏词汇

语料全部建在一个临时语料根里（跑完删掉）：先试系统临时目录（正常机器），
沙箱 ACL 下 `%TEMP%` 建得出写不进 → 退到本仓 `_records_reload_tmp/`（同一 finally 里必删）。
"""
import json
import os
import re
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from saintess_engine.records import (Records, RecordsReloadError,   # noqa: E402
                                     RecordsOrderMismatch, RecordsSet)

passed = failed = 0


from _check import bind_check  # noqa: E402  P0-1 断言助手单源：tests/_check.py

check = bind_check(globals(), "passed", "failed")


# ---------------------------------------------------------------- 语料
ROSTER3 = {
    "1": {"name": "alice", "n": 1, "note": "one"},
    "2": {"name": "bob", "n": 2, "note": "two"},
    "3": {"name": "alice", "n": 3, "note": "three"},
}
ROSTER4 = dict(ROSTER3, **{"4": {"name": "carol", "n": 4, "note": "four"}})
ORDERED3 = {"1": {"v": 1}, "2": {"v": 2}, "3": {"v": 3}}


def _domain(root, domain, sub="data"):
    return os.path.join(root, sub, "%s.json" % domain)


def _dump(path, doc):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)


def _write_text(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ---------------------------------------------------------------- 1 生效 / 摘要
def t1_reload_effective(root):
    print("\n[1] 重载生效 + 变更摘要（含未变化项）+ 不做自动检查")
    path = _domain(root, "roster")
    _dump(path, ROSTER3)
    r = Records(root, "roster", key_type=int).load()
    check("初始读到 3 条", len(r.all()) == 3, repr(list(r.all())))

    _dump(path, ROSTER4)
    check("★ 改文件后**不** reload 读到的仍是旧版（不做自动 mtime 检查）",
          len(r.all()) == 3 and r.get(4) is None, repr(list(r.all())))

    summary = r.reload()
    check("★ reload() 摘要 == {'roster': {'before': 3, 'after': 4}}",
          summary == {"roster": {"before": 3, "after": 4}}, repr(summary))
    check("★ reload() 后读出新内容（第 4 条 + 字段值）",
          len(r.all()) == 4 and (r.get(4) or {}).get("note") == "four", repr(r.get(4)))
    check("reload() 后键型仍还原（get(4) 命中 / get('4') 不命中）",
          r.get("4") is None, repr(r.get("4")))

    again = r.reload()
    check("★ 同文件再 reload：摘要**含未变化项**（4 → 4）",
          again == {"roster": {"before": 4, "after": 4}}, repr(again))
    check("reload 后 problems 干净（无假留痕）", r.problems == [], repr(r.problems))


# ---------------------------------------------------------------- 2 原子性
def t2_atomicity(root):
    print("\n[2] 原子性：坏 JSON / 缺文件 / 顶层非映射 → 点名抛错且旧数据逐字节不变")
    e = RecordsReloadError("d", "why", problems=["p1"])
    check("RecordsReloadError(domain, reason, *, problems=) 字段与消息",
          e.domain == "d" and e.reason == "why" and e.problems == ["p1"]
          and isinstance(e, RuntimeError) and "why" in str(e), repr(str(e)))

    path = _domain(root, "roster")
    _dump(path, ROSTER3)
    r = Records(root, "roster", key_type=int).load()
    snapshot = json.dumps(r.all(), ensure_ascii=False)
    probs = list(r.problems)

    _write_text(path, '{"1": {"name": }')                      # 故意坏 JSON
    try:
        r.reload()
        check("★ 坏 JSON → RecordsReloadError", False, "没抛")
    except RecordsReloadError as exc:
        check("★ 坏 JSON → RecordsReloadError", True)
        check("★ 点名域 == 'roster'", exc.domain == "roster", repr(exc.domain))
        check("★ 原因人读（含「坏 JSON」）", "坏 JSON" in exc.reason, repr(exc.reason))
    except Exception as exc:                                   # noqa: BLE001
        check("★ 坏 JSON → RecordsReloadError", False, repr(exc))
    check("★ 旧表逐字节不变（json.dumps 相等）",
          json.dumps(r.all(), ensure_ascii=False) == snapshot, repr(r.all()))
    check("★ 旧条目仍可读（get(3).note == 'three'）",
          (r.get(3) or {}).get("note") == "three", repr(r.get(3)))
    check("★ 旧留痕不变（失败不污染状态）", r.problems == probs, repr(r.problems))

    os.remove(path)                                            # 域文件没了
    try:
        r.reload()
        check("★ 缺文件 → RecordsReloadError", False, "没抛")
    except RecordsReloadError as exc:
        check("★ 缺文件 → RecordsReloadError", True)
        check("★ 缺文件原因人读（含「不存在」）", "不存在" in exc.reason, repr(exc.reason))
    check("★ 缺文件失败后旧数据仍逐字节不变",
          json.dumps(r.all(), ensure_ascii=False) == snapshot, repr(r.all()))

    _dump(path, [1, 2, 3])                                     # 顶层不是映射
    try:
        r.reload()
        check("★ 顶层非映射 → RecordsReloadError", False, "没抛")
    except RecordsReloadError as exc:
        check("★ 顶层非映射 → RecordsReloadError", True)
        check("★ 顶层非映射原因人读（含「顶层不是」）",
              "顶层不是" in exc.reason, repr(exc.reason))
    check("★ 顶层非映射失败后旧数据仍逐字节不变",
          json.dumps(r.all(), ensure_ascii=False) == snapshot, repr(r.all()))


# ---------------------------------------------------------------- 3 全有或全无
def t3_reload_all_all_or_nothing(root):
    print("\n[3] 全有或全无：RecordsSet.reload_all() 一份坏 → 其余表也没被替换")
    _dump(_domain(root, "alpha"), {"1": {"n": 1}, "2": {"n": 2}})
    _dump(_domain(root, "beta"), {"1": {"n": 1}, "2": {"n": 2}})
    bag = RecordsSet(root, {"alpha": {"key_type": int}, "beta": {"key_type": int}})
    check("先读两张（各 2 条）",
          len(bag.alpha.all()) == 2 and len(bag.beta.all()) == 2)

    _dump(_domain(root, "alpha"), {"1": {"n": 1}, "2": {"n": 2}, "3": {"n": 3}})
    _write_text(_domain(root, "beta"), '{"1": ')               # beta 坏
    try:
        bag.reload_all()
        check("★ reload_all 一份坏 → RecordsReloadError", False, "没抛")
    except RecordsReloadError as exc:
        check("★ reload_all 一份坏 → RecordsReloadError", True)
        check("★ 点名坏的那张 == 'beta'", exc.domain == "beta", repr(exc.domain))
    except Exception as exc:                                   # noqa: BLE001
        check("★ reload_all 一份坏 → RecordsReloadError", False, repr(exc))
    check("★ alpha（已读好但未提交）也没被替换：仍 2 条",
          len(bag.alpha.all()) == 2 and bag.alpha.get(3) is None,
          repr(list(bag.alpha.all())))
    check("★ beta 旧数据不变：仍 2 条且内容可读",
          len(bag.beta.all()) == 2 and bag.beta.get(1)["n"] == 1, repr(bag.beta.all()))

    _dump(_domain(root, "beta"), {"1": {"n": 1}, "2": {"n": 2}})
    out = bag.reload_all()
    check("★ reload_all 成功：返回 {表名: 该表 reload() 结果}（含未变化项）",
          out == {"alpha": {"alpha": {"before": 2, "after": 3}},
                  "beta": {"beta": {"before": 2, "after": 2}}}, repr(out))
    check("reload_all 后两张都发布新版",
          len(bag.alpha.all()) == 3 and len(bag.beta.all()) == 2)

    _dump(_domain(root, "delta"), {"1": {"n": 1}})
    fresh = RecordsSet(root, {"delta": {"key_type": int}})
    fresh_out = fresh.reload_all()
    check("★ reload_all 会把**没读过的声明域**也读入",
          fresh_out == {"delta": {"delta": {"before": 0, "after": 1}}}
          and fresh.delta.get(1)["n"] == 1, repr(fresh_out))


# ---------------------------------------------------------------- 4 幂等
def t4_idempotent(root):
    print("\n[4] 幂等：同一份文件 reload 两次，摘要与内容一致")
    _dump(_domain(root, "roster"), ROSTER3)
    r = Records(root, "roster", key_type=int).load()
    s1 = r.reload()
    c1 = json.dumps(r.all(), ensure_ascii=False)
    s2 = r.reload()
    c2 = json.dumps(r.all(), ensure_ascii=False)
    check("★ 两次摘要一致（3 → 3）",
          s1 == s2 == {"roster": {"before": 3, "after": 3}}, repr((s1, s2)))
    check("★ 两次内容一致", c1 == c2, "%r vs %r" % (c1, c2))


# ---------------------------------------------------------------- 5 顺序守卫
def t5_order_guard(root):
    print("\n[5] 顺序守卫仍生效：域里多 / 少一条 → 抛错且不替换")
    _dump(_domain(root, "ordered"), ORDERED3)
    r = Records(root, "ordered", key_type=int, order=(1, 2, 3)).load()
    check("初始按声明序 [1, 2, 3]", list(r.all()) == [1, 2, 3], repr(list(r.all())))

    _dump(_domain(root, "ordered"),
          {"1": {"v": 1}, "2": {"v": 2}, "3": {"v": 3}, "4": {"v": 4}})
    try:
        r.reload()
        check("★ 域里多一条 → RecordsReloadError", False, "没抛")
    except RecordsReloadError as exc:
        check("★ 域里多一条 → RecordsReloadError", True)
        check("★ 点名域 + 原因含键集守卫",
              exc.domain == "ordered" and "键集" in exc.reason, repr(exc.reason))
    check("★ 多一条失败后旧表不变（仍 3 条、仍声明序）",
          list(r.all()) == [1, 2, 3], repr(list(r.all())))

    _dump(_domain(root, "ordered"), {"1": {"v": 1}, "2": {"v": 2}})
    try:
        r.reload()
        check("★ 域里少一条 → RecordsReloadError", False, "没抛")
    except RecordsReloadError:
        check("★ 域里少一条 → RecordsReloadError", True)
    check("★ 少一条失败后旧表仍不变",
          list(r.all()) == [1, 2, 3], repr(list(r.all())))

    _dump(_domain(root, "ordered"), ORDERED3)
    fixed = r.reload()
    check("★ 修好后 reload 成功且条数不变",
          fixed == {"ordered": {"before": 3, "after": 3}}
          and list(r.all()) == [1, 2, 3], repr(fixed))


# ---------------------------------------------------------------- 6 索引 / drop
def t6_index_swap_and_drop(root):
    print("\n[6] 索引随表换 + drop 在重载路径同样生效")
    _dump(_domain(root, "roster"), ROSTER3)
    r = Records(root, "roster", key_type=int).load()
    check("旧索引 {'alice': [1, 3], 'bob': [2]}",
          r.index_of("name") == {"alice": [1, 3], "bob": [2]}, repr(r.index_of("name")))
    _dump(_domain(root, "roster"), {"1": {"name": "zoe"}, "2": {"name": "zoe"}})
    r.reload()
    check("★ reload 后索引缓存不残留（按新表重建）",
          r.index_of("name") == {"zoe": [1, 2]}, repr(r.index_of("name")))
    check("★ reload 后旧 id 不在表里（3 消失）", 3 not in r.all(), repr(list(r.all())))

    _dump(_domain(root, "dropdom"),
          {"1": {"name": "a", "_injected": 1}, "2": {"_injected": 2}})
    d = Records(root, "dropdom", key_type=int, drop=("_injected",)).load()
    check("drop 首读：剥字段 + 剥空条目不留空壳（1 条）",
          d.all() == {1: {"name": "a"}},
          repr(d.all()))
    _dump(_domain(root, "dropdom"),
          {"1": {"name": "a", "_injected": 1}, "2": {"name": "b", "_injected": 2}})
    s = d.reload()
    check("★ reload 同样剥字段（新表 2 条、无 _injected）",
          d.all() == {1: {"name": "a"}, 2: {"name": "b"}}, repr(d.all()))
    check("★ drop 域摘要按**剥后**条数（1 → 2）",
          s == {"dropdom": {"before": 1, "after": 2}}, repr(s))
    check("★ reload 成功且新表无剥空条目 → 留痕清空",
          d.problems == [], repr(d.problems))

    _dump(_domain(root, "ordered"), ORDERED3)
    try:
        Records(root, "ordered", key_type=int, order=(1, 2)).load()
        check("（前置）顺序不符首读仍是 RecordsOrderMismatch", False, "没抛")
    except RecordsOrderMismatch:
        check("（前置）顺序不符首读仍是 RecordsOrderMismatch（既有行为未动）", True)


# ---------------------------------------------------------------- 7 零知识
_GAME_TERMS = (
    # 具体游戏 / 仓库名
    "奥兰迪亚", "余烬", "dragonfall",
    # 内容侧身份名词（引擎不得出现）
    "公会", "职业", "物品", "怪物", "装备", "技能", "任务", "地图",
    "guild", "monster", "npc", "quest", "sword", "potion",
    # 具体游戏的机制 id
    "zhan_yi", "randuin", "ice_vein", "melody", "faith", "fury",
)


def t7_zero_knowledge():
    print("\n[7] 零知识：records 源码不得出现具体游戏词汇")
    base = os.path.join(ROOT, "saintess_engine", "records")
    hits = []
    for dirpath, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            for i, line in enumerate(open(path, encoding="utf-8").read().splitlines(), 1):
                for t in _GAME_TERMS:
                    pat = (re.compile(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(t))
                           if t.isascii() else re.compile(re.escape(t)))
                    if pat.search(line):
                        hits.append("%s:%d [%s] %s" % (fn, i, t, line.strip()[:70]))
    check("★ 扫描 %d 个词零命中" % len(_GAME_TERMS), not hits,
          "\n      " + "\n      ".join(hits))
    print("      （扫描目录：saintess_engine/records/ · 命中 0）")


# ---------------------------------------------------------------- 语料根
def _writable(d):
    """这个目录建得出**子目录**、写得进文件吗（沙箱 ACL 下 %TEMP% 会假通过）。"""
    sub = os.path.join(d, "probe")
    try:
        os.makedirs(sub, exist_ok=True)
        with open(os.path.join(sub, "x"), "w", encoding="utf-8") as f:
            f.write("ok")
        shutil.rmtree(sub, ignore_errors=True)
        return True
    except OSError:
        return False


def _fixture_root():
    """语料根：系统临时目录优先；不可写 → 退到本仓 `_records_reload_tmp/`（finally 里删）。"""
    try:
        d = tempfile.mkdtemp(prefix="records_reload_")
    except OSError:
        d = ""
    if d and _writable(d):
        try:
            os.chmod(d, 0o755)                                 # 沙箱 ACL：0o700 会「建得出写不进」
        except OSError:
            pass
        return d
    if d:
        shutil.rmtree(d, ignore_errors=True)
    fallback = os.path.join(ROOT, "_records_reload_tmp")
    shutil.rmtree(fallback, ignore_errors=True)
    os.makedirs(fallback, exist_ok=True)
    print(f"  （系统临时目录不可写 → 语料根退到 {fallback}）")
    return fallback


def main():
    print("== records 显式重载门禁：生效 / 原子 / 全有或全无 / 幂等 / 顺序守卫 / 索引 / 零知识 ==")
    root = _fixture_root()
    try:
        os.makedirs(os.path.join(root, "data"), exist_ok=True)
        t1_reload_effective(root)
        t2_atomicity(root)
        t3_reload_all_all_or_nothing(root)
        t4_idempotent(root)
        t5_order_guard(root)
        t6_index_swap_and_drop(root)
        t7_zero_knowledge()
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print(f"\n===== 结果：通过 {passed} / {passed + failed} =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
