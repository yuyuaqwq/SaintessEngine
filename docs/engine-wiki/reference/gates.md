# `gates` · 数值预算门禁

> **归属**：`saintess_engine/gates/__init__.py`（E3，2026-09-21）· **纯函数，零 hook、零词汇**
> **为什么建**：旧项目**没有**这个能力 —— 装备 687 条靠人肉 + 十几个临时 `_audit_*.py` 检查，
> 所以会出现「同装等一件强三倍」。本模块让配平变成**一次跑完、报全部、给退出码**的批处理。

---

## 通用约定

- 签名 = `(被测数据…, *, <阈值>, label) -> list[str]`；**空列表 = 通过**，否则每条是**完整的中文可读句**。
- **点名到条目**是硬要求：每条报错含 `组标签 + 条目 id + 字段名 + 实测值 + 阈值 + 差多少`。
- 数值文案一律 `%.4g`；比值用 `%.1%`。
- **用法错抛异常**（`label` 空串/非 str ⇒ `TypeError`；`budget`/`tol`/`cap` 非法 ⇒ `ValueError`）；
  **数据错只给文案** —— 因为配平是"一次跑完、报全部"的批处理。

## 有意不做

**不算 PE**（公式在内容侧）· **不猜分组键**（哪些条目算同组由调用方给）· **不读文件/不建索引/不缓存** ·
**不做越权修正**（只报不改）。

---

## 六个校验器

| # | 名称 | 判据 | 落地判据 |
|---|---|---|---|
| 1 | `within_budget(value, *, budget, label)` | `value ≤ budget` 通过（**严格大于**才红） | 单件 PE ≤ `PE_base(L) × (1+0.08Q)` |
| 2 | `spread_within(rows, *, tol, label)` | `(max−min)/max ≤ tol`；`max ≤ 0` 时改用 `abs(min)` | 装备 5% / 技能 15% |
| 3 | `monotone_by(rows, *, keys, order_key="level", direction="nondecreasing", label)` | 返回 **`(errors, warns)`**；内部按 `order_key` **升序排序后**再比；缺字段 ⇒ 跳过该字段并记 warn | 升 1 级不许降 |
| 4 | `within_cap(value, *, cap, label)` | `cap is None` ⇒ **永远通过** | 属性 cap 表 |
| 5 | `share_within(parts, *, total, cap, label)` | 逐部件 `part/total ≤ cap`；`total ≤ 0` ⇒ `ValueError` | 主属性 ≤60% / 词条 ≤40% / 单源 ≤45% |
| 6 | `sum_within(parts, *, budget, label)` | `Σ parts ≤ budget` | 6 槽合计 = 35% |

### 三条容易踩的边界（都写进了 docstring）

1. **`spread_within` 允许负数**（全负组用 `|min|` 做分母）；**别的校验器不许负**（`nonneg=True`）。
   —— `_num` 默认**允许负数**是有意的，只在语义上不该为负处才收紧。
2. **`rows` 为空 ⇒ 抛 `ValueError`**（空组不能算通过，否则「没填 = 配平」）。
3. **`within_cap` 的 `cap=None` 是"无上限"，不是 0** —— `crit_dmg` 的上限 **1.5** 是**加算量**（上限 3.0 倍）
   不是比例；`haste` 是 `None`（自然递减）。**cap 表必须逐条照抄，不许把 `None` 写成 0。**

---

## 用法

```python
from saintess_engine.gates import within_budget, spread_within, monotone_by

errs = []
errs += within_budget(item["PE"], budget=item["PE预算"] * 1.05, label=f"装备[{item['名']}].pe")
errs += spread_within([(i["名"], i["PE"]) for i in same_group], tol=0.05, label="装备[5/粗制/武器]")
e, w = monotone_by(anchor_rows, keys=["max_hp", "atk", "def"], label="数值/锚点表")
```

**实测（艾瑟兰真实数据）**：44 件装备逐件 PE ≤ 预算×1.05 → **违规 0**；
4 个多件组极差 ≤5% → **违规 0**；反证（故意抬价 20%）→ **报红并点名到件**。

---

## 边界

引擎只给**纯函数**，由**两处消费**（都在内容侧）：
① 内容侧的建包/CI 脚本（跑一次、报全部、给退出码）；② 编辑器/门禁的调用方。
**引擎不注册命令、不自动调用** —— 配平是离线批处理，不是"一条指令一次回执"的会话模型。
