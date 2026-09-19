# -*- coding: utf-8 -*-
"""表形状 / JSON 读取的**通用**小工具（`saintess_engine/records/shapes.py`）。

归属：**纯通用** —— 零游戏知识，也不带任何内容包约定（域 id / 表名 / 键名一律由调用方给）。
这批口原先单源住在内容包 `content/_domainio.py`（P0-4 收口）；按 W8「通用助手收进引擎」
搬到这里，包内**只再导出**（42 个调用点零改动）。

* `read_json` —— 最底层的 JSON 读（缺文件 / 坏 JSON → `default`，不抛）。
  引擎宿主装载口 `saintess_engine/host/package.py` 用的是**同一份**（两处实现原逐字相同，
  W8 去重：`host/package.py` 改为从本模块取）。
* `int_keys` —— JSON 字符串键 → int 键（非整数键**原样保留**，不静默丢）。
* `num_sorted` —— int 键表按**数值升序**（JSON 是字典序：`"10" < "2"` ⇒ 不排序 = 档位乱序）。
* `ordered` —— 按**调用方给的声明序**排外层键；键集与声明不一致 → `raise`（防静默改序）。
  报错措辞由调用方给（`who` / `subject` / `noun` / `hint`）。
* `seq_rows` —— 带 `seq` 注入字段的条目 → 按 `seq` 还原源插入序（顺手剥掉 `seq`）。
* `same_container` —— 同型可变容器（dict / list / set）：就地更新只对同型成立。

行为口径：与搬移前**逐字相同**（含 `raise` 分支与消息格式、非整数键保留、空表不抛）。
"""
from __future__ import annotations

import json

__all__ = ["read_json", "int_keys", "num_sorted", "ordered", "seq_rows", "same_container"]


def read_json(path, default=None):
    """读 JSON（缺文件 / 坏 JSON → default，不抛）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                        # noqa: BLE001
        return default

def int_keys(tbl) -> dict:
    """JSON 字符串键 → int 键（非整数键**原样保留**，不静默丢）。

    用途：`{int 档位: 值}` 这类表 —— 不还原 = `.get(3)` 恒 `None`（静默归零）。
    """
    out: dict = {}
    for k, v in (tbl or {}).items():
        try:
            out[int(k)] = v
        except (TypeError, ValueError):
            out[k] = v
    return out

def num_sorted(tbl) -> dict:
    """int 键表 → 按**数值升序**（JSON 是字典序：`"10" < "2"` ⇒ 不排序 = 阶位/等级乱序）。

    非整数键排在后面并保持相对序。
    """
    ints = {k: v for k, v in (tbl or {}).items() if isinstance(k, int) and not isinstance(k, bool)}
    rest = {k: v for k, v in (tbl or {}).items() if k not in ints}
    return {**{k: ints[k] for k in sorted(ints)}, **rest}

def ordered(tbl, order, where: str, *, who: str, subject: str, noun: str, hint: str) -> dict:
    """按**声明序**排外层键（域是字典序，真源是插入序）。域读不到 → `{}` 不抛；
    域在但键集与声明不一致 → `raise`（防「源改了、门面静默改序」）。

    `who` / `subject` / `noun` / `hint` 只进报错文案（各调用点措辞不同）。
    """
    if not isinstance(tbl, dict) or not tbl:
        return {}
    keys = list(order)
    if len(set(keys)) != len(keys):
        raise ValueError("%s：%s 的序声明有重复键 —— 拒绝静默取首个" % (who, where))
    have = set(tbl)
    miss = [k for k in keys if k not in have]
    extra = [k for k in have if k not in set(keys)]
    if miss or extra:
        raise ValueError(
            "%s：%s %s（%s缺 %d / 声明缺 %d）—— %s。%s缺 %s … 未声明 %s …"
            % (who, where, subject, noun, len(miss), len(extra), hint, noun, miss[:5],
               sorted(extra)[:5]))
    return {k: tbl[k] for k in keys}

def seq_rows(values) -> list:
    """域内「带 `seq` 注入字段」的条目 → 按 `seq` 还原源插入序的 list（顺手剥掉 `seq`）。"""
    return [{k: v for k, v in ent.items() if k != "seq"}
            for ent in sorted(values, key=lambda x: x["seq"])]

def same_container(a, b) -> bool:
    """同型可变容器（dict / list / set）—— 就地更新只对同型成立。"""
    return ((isinstance(a, dict) and isinstance(b, dict))
            or (isinstance(a, list) and isinstance(b, list))
            or (isinstance(a, set) and isinstance(b, set)))
