# -*- coding: utf-8 -*-
"""内容侧技能表读取（包内版）—— 逐字搬自游戏仓 `game/content_rules/skills.py`（220 行）。

真源：`C:/Users/yuyu/qqbot/data/plugins/dragonfall/game/content_rules/skills.py`
包内改动面 = **本块说明 + 下面 4 行 import/数据层 + 末尾 2 行接线别名**，14 个函数体一字不改。
逐字证据 = `overnight/d3_skills_verify.py`（逐行 diff + 逐字段对拍，全绿）。

包内版说明（D3 技能批，2026-09-13）—— **逐字搬**，只改 import 段
--------------------------------------------------------------
| 真源 | 包内等价物 | 说明 |
|---|---|---|
| `from .. import content as C` | 下面 `class _ContentShim` + `C = _ContentShim()` | 游戏仓聚合层 `game/content.py` 只有 4 个符号被本模块读（`PLAYER_SKILLS` / `BRANCH_SKILLS` / `TUTOR_SKILLS` / `SKILL_UP`）+ `resolve`，包内 shim 就这 5 个 |
| （隐式）三张源表 | `_shape_three_tables(_T.SKILLS, _T.CLASSES)` | 包内 `content/data/skills.json` 是三表**扁平化**产物（305 条，条目带 `owner_class` / `source` / `tier` / `branch`，见游戏仓 `scripts/export_game_package.py:161 derive_skills`）→ 这里按导出器追加的 4 个字段**逆折回**真源形状（`{cls:{name,skills}}` / `{cls:{name,branches:{tier:{线:{名:info}}}}}` / `{cls:{sk:info}}`），并从条目里剥掉那 4 个追加字段 —— 于是 `skill_info` 返回的 info **与真源逐字段相等**（导出器只追加、不改值，`_put` 源码可查） |
| `from saintess_engine.battle.formulas import skill_max_level` | 同左（引擎侧纯公式，路径不变） | `skill_upgrade_cost` 用 |
| ✅ 包内新增：`SKILL_UP` 表 | 本文件内**逐字内嵌**（AST 切片自 `game/data/skill_up.py`，305 条） | 该域**尚未进包**（`content/data/skill_up.json` 不存在，导出器暂无 `derive_skill_up`），而 `_skill_up` 必须读它；包内数据「随代码走」口径同 `content/mech/params.py` / `content/mech/class_data.py`（后者也是程序 dump 内嵌）。建域后整块搬走即可 |

真源读的游戏仓表（4 张）↔ 包内域：

    C.PLAYER_SKILLS  ← content/data/skills.json（source == "player"）
    C.BRANCH_SKILLS  ← content/data/skills.json（source == "branch"；tier/branch 还原嵌套）
    C.TUTOR_SKILLS   ← content/data/skills.json（source == "tutor"）
    C.SKILL_UP       ← 本文件内嵌 `SKILL_UP`（真源 `game/data/skill_up.py`）
    C.resolve(...)   ← content/tables.py:resolve（= 游戏仓 `game/core/index.py:47`）

已知差异（逐条 + 证据见 `overnight/d3-skills-port.md`）
----------------------------------------------------
1. `TUTOR_SKILLS` 里**空表职业键**（真源 `cls_zhan_shi` / `cls_you_xia` = `{}`）在包内域里没有对应条目
   → 逆折出的 tutor 表少这两个键。**行为等价**：`skill_info` 的导师环是 `(C.TUTOR_SKILLS or {}).get(cls, {}).get(...)`，
   键缺失 = 空表，结果同为 `None`；`_build_skill_key_index` 遍历空表不产出条目。
2. `resolve("skills", …)`：真源索引只有 **67** 个名字（`PLAYER_SKILLS` 扁平 + `TUTOR`，`game/data/_assembly.py:166-180`），
   包内 `tables.resolve` 覆盖 **305** 个（含分支）。**语义等价**：分支技能 key 与 `name` 逐条相同（238/238），
   真源对分支名是「查不到原样返回」、包内是「查到 key」—— 两者返回同一个字符串。
3. 引擎 hook 受体名：真源私有名 `_skill_up`（`game/bootstrap.py` 直挂）；包内给公开别名 `skill_up`（末尾 2 行），
   `skill_level_of` / `branch_path_index` / `skills_for_level` 等非 hook 函数由调用方 import。
"""
from __future__ import annotations

from saintess_engine.battle.formulas import skill_max_level  # noqa: F401

from . import tables as _T

# ============================================================
# 数据层：包内扁平域 → 真源三表形状（原文 `from .. import content as C` 的等价物）
# ============================================================

# 导出器 `derive_skills` 追加的 4 个字段（不在真源 info 里，逆折时剥掉）
_ADDED_FIELDS = ("owner_class", "source", "tier", "branch")


def _shape_three_tables(skills: dict, classes: dict) -> tuple:
    """`content/data/skills.json`（305 条扁平）→ 真源三表 `(PLAYER, BRANCH, TUTOR)`。

    只按条目自带的 `source` 分表、`owner_class` 归职业、`tier`/`branch` 还原嵌套层级；
    条目里剥掉导出器追加的 4 个字段（`owner_class` / `source` / `tier` / `branch`），
    其余键值**原样带着** —— 于是 info dict 与真源逐字段相等（零默认值、零改写）。
    缺字段/形状不认识的条目**跳过**（不抛；坏域的调用方本来就 `if not info` 跳过）。
    """
    player: dict = {}
    branch: dict = {}
    tutor: dict = {}
    for key, entry in (skills or {}).items():
        if not isinstance(entry, dict):
            continue
        info = {k: v for k, v in entry.items() if k not in _ADDED_FIELDS}
        cls_id = entry.get("owner_class")
        if not cls_id:
            continue
        cls_name = classes.get(cls_id, {}).get("name") if isinstance(classes, dict) else None
        src = entry.get("source")
        if src == "player":
            player.setdefault(cls_id, {"name": cls_name, "skills": {}})["skills"][key] = info
        elif src == "branch":
            tier = entry.get("tier")
            line = entry.get("branch")
            if tier is None or line is None:
                continue
            tiers = branch.setdefault(cls_id, {"name": cls_name, "branches": {}})["branches"]
            tiers.setdefault(int(tier), {}).setdefault(line, {})[key] = info
        elif src == "tutor":
            tutor.setdefault(cls_id, {})[key] = info
    return player, branch, tutor


PLAYER_SKILLS, BRANCH_SKILLS, TUTOR_SKILLS = _shape_three_tables(_T.SKILLS, _T.CLASSES)

# 技能升级成长表（每技能独立成长曲线 + 独立满级）—— 真源 `game/data/skill_up.py:SKILL_UP`
# 字段：p=每级伤害/治疗倍率 +x%；c=每级条件倍率 +c；m=每 m 级叠层 +1；l=每级吸血比例 +2%；max=满级
# key = 稳定 id（基础/导师技 = 技能表现存 sk_id；分支技 = sk_br_<pinyin>），每条带 name=中文名
SKILL_UP: dict = {
        # ============================================================
        # v181 P0B-C 根治（方案 C，docs/REFACTOR_P0B_skill_up_dedup.md §4 Step2）：
        #   key 从『技能显示中文名』改为『稳定 id』——中文名撞名不再互相污染配置：
        #     · 基础/导师技：key = 技能表现存 sk_id（sk_hui_kan…），与 PLAYER_SKILLS/TUTOR_SKILLS 键一致
        #     · 分支技：key = 生成的稳定 sk_br_<pinyin> id（与基础/导师 sk_ 前缀天然分域）
        #   · 每条带 name=中文名（显示/校验）；同中文名多段（未来）将显式撞出（构建期自检）
        #   · engine._skill_up 按 info 携带 id 单点查询，查不到回落中文名（防御/兼容）
        #   · 启动自检：SKILL_UP 每 key 必须反查到一个 live 技能，孤儿直接 ImportError
        #   · 本文件由脚本生成（scripts/gen_skill_up_p0bc.py 保留在仓内，勿手改数值）
        #
        #   · 撞车消解（§5.4 pinyin）：守歌(基础, 现存 sk_shou_ge) vs 收割(分支, pinyin 亦 shou_ge)
        #     → 分支统一 sk_br_ 前缀天然分域（sk_br_shou_ge），全 305 名复核无第二撞。
        # ============================================================

        # ---------------- 基础技 PLAYER_SKILLS（key=现存 sk_id） ----------------
        'sk_ci_ji': {'p': 12, 'max': 5, 'name': '刺击'},
        'sk_ge_lie': {'p': 12, 'max': 5, 'name': '割裂'},
        'sk_ji_ying': {'max': 3, 'name': '疾影'},
        'sk_qian_xing': {'max': 3, 'name': '潜行'},
        'sk_shuang_ren_luan_wu': {'p': 12, 'max': 5, 'name': '双刃乱舞'},
        'sk_yan_wu_dan': {'max': 3, 'name': '烟雾弹'},
        'sk_ying_xi': {'p': 12, 'max': 5, 'name': '影袭'},
        'sk_zhong_jie_ge_hou': {'p': 12, 'max': 5, 'name': '终结·割喉'},
        'sk_bing_zhui': {'p': 12, 'max': 5, 'name': '冰锥'},
        'sk_huo_qiu_shu': {'p': 12, 'max': 5, 'name': '火球术'},
        'sk_lei_ji': {'p': 12, 'max': 5, 'name': '雷击'},
        'sk_shan_xian': {'max': 3, 'name': '闪现'},
        'sk_shuang_jing_hu_ti': {'max': 3, 'name': '霜晶护体'},
        'sk_yuan_su_yin_bao': {'p': 12, 'max': 5, 'name': '元素引爆'},
        'sk_yun_shi_shu': {'p': 12, 'max': 5, 'name': '陨石术'},
        'sk_zhou_yu_dan_mu': {'p': 9, 'max': 5, 'name': '骤雨弹幕'},
        'sk_qun_ti_zhi_yu': {'p': 12, 'max': 5, 'name': '群体治愈'},
        'sk_sheng_guang_cheng_ji': {'p': 10, 'max': 5, 'name': '圣光惩击'},
        'sk_sheng_guang_cheng_jie': {'p': 12, 'max': 5, 'name': '圣光惩戒'},
        'sk_sheng_guang_dan': {'p': 10, 'max': 5, 'name': '圣光弹'},
        'sk_sheng_guang_hu_dun': {'max': 3, 'name': '圣光护盾'},
        'sk_sheng_guang_qu_san': {'p': 12, 'max': 5, 'name': '圣光驱散'},
        'sk_sheng_you': {'max': 3, 'name': '圣佑'},
        'sk_xie_fu': {'p': 12, 'max': 5, 'name': '卸负'},
        'sk_xin_yang_qi_dao': {'max': 3, 'name': '信仰祈祷'},
        'sk_zhi_yu_shu': {'p': 12, 'max': 5, 'name': '治愈术'},
        'sk_an_shen_qu': {'p': 12, 'max': 5, 'name': '安神曲'},
        'sk_bo_xian': {'max': 3, 'name': '拨弦'},
        'sk_gong_zhen': {'p': 10, 'max': 5, 'name': '共振'},
        'sk_he_sheng': {'max': 3, 'name': '和声'},
        'sk_ji_ge': {'max': 3, 'name': '疾歌'},
        'sk_ji_zou_yin': {'max': 3, 'name': '疾走音'},
        'sk_po_yin': {'p': 10, 'max': 5, 'name': '破音'},
        'sk_shou_ge': {'max': 3, 'name': '守歌'},
        'sk_suo_yin': {'p': 10, 'max': 5, 'name': '锁音'},
        'sk_yin_ren': {'p': 12, 'max': 5, 'name': '音刃'},
        'sk_zhan_ge': {'max': 3, 'name': '战歌'},
        'sk_ce_ti': {'p': 12, 'max': 5, 'name': '侧踢'},
        'sk_chong_quan': {'p': 12, 'max': 5, 'name': '冲拳'},
        'sk_gang_quan': {'p': 12, 'max': 5, 'name': '钢拳'},
        'sk_lian_zhao_san_lian': {'p': 9, 'max': 5, 'name': '连招三连'},
        'sk_ming_xiang': {'max': 3, 'name': '冥想'},
        'sk_tong_qiang': {'max': 3, 'name': '铜墙'},
        'sk_zhen_di_ji': {'p': 12, 'max': 5, 'name': '震地击'},
        'sk_zhi_quan': {'p': 12, 'max': 5, 'name': '直拳'},
        'sk_feng_zhi_ji_zou': {'max': 3, 'name': '风之疾走'},
        'sk_lian_she': {'p': 12, 'max': 5, 'name': '连射'},
        'sk_lie_wang_xian_jing': {'p': 12, 'max': 5, 'name': '猎网陷阱'},
        'sk_lie_yin_she_ji': {'p': 12, 'max': 5, 'name': '猎印射击'},
        'sk_miao_zhun_she_ji': {'p': 12, 'max': 5, 'name': '瞄准射击'},
        'sk_shan_bi_bu': {'max': 3, 'name': '闪避步'},
        'sk_ying_yan_suo_ding': {'max': 3, 'name': '鹰眼锁定'},
        'sk_zhi_ming_ju_ji': {'p': 12, 'max': 5, 'name': '致命狙击'},
        'sk_chong_feng': {'p': 12, 'max': 5, 'name': '冲锋'},
        'sk_hui_kan': {'p': 12, 'max': 5, 'name': '挥砍'},
        'sk_leng_jing': {'p': 12, 'max': 5, 'name': '冷静'},
        'sk_meng_ji': {'p': 12, 'max': 5, 'name': '猛击'},
        'sk_po_jia_zhan': {'p': 12, 'max': 5, 'name': '破甲斩'},
        'sk_tie_bi': {'max': 3, 'name': '铁壁'},
        'sk_xuan_feng_zhan': {'p': 12, 'max': 5, 'name': '旋风斩'},
        'sk_zhan_hou': {'max': 3, 'name': '战吼'},
        # ---------------- 分支技 BRANCH_SKILLS（key=sk_br_<pinyin>） ----------------
        'sk_br_huan_ying_lian_ci': {'p': 9, 'max': 5, 'name': '幻影连刺'},
        'sk_br_ying_ren': {'p': 12, 'max': 5, 'name': '影刃'},
        'sk_br_ying_fen_shen': {'max': 3, 'name': '影分身'},
        'sk_br_an_ying_bu': {'max': 3, 'name': '暗影步'},
        'sk_br_zhong_jie_chu_xing': {'p': 12, 'max': 5, 'name': '终结·处刑'},
        'sk_br_lian_wu': {'p': 12, 'max': 5, 'name': '链舞'},
        'sk_br_shuang_du_ren': {'p': 12, 'max': 5, 'name': '双毒刃'},
        'sk_br_si_wang_biao_ji': {'max': 3, 'name': '死亡标记'},
        'sk_br_du_ren': {'p': 12, 'max': 5, 'name': '毒刃'},
        'sk_br_du_bao': {'p': 12, 'max': 5, 'name': '毒爆'},
        'sk_br_cui_du_zhi_ren': {'p': 12, 'max': 5, 'name': '淬毒之刃'},
        'sk_br_shi_gu': {'max': 1, 'name': '蚀骨'},
        'sk_br_you_ying_lian_ci': {'p': 9, 'max': 5, 'name': '幽影连刺'},
        'sk_br_ying_dun': {'max': 3, 'name': '影遁'},
        'sk_br_shou_ge': {'p': 12, 'max': 5, 'name': '收割'},
        'sk_br_an_ying_zhi_xin': {'max': 1, 'name': '暗影之心'},
        'sk_br_an_ying_bu_ji': {'max': 1, 'name': '暗影步·极'},
        'sk_br_an_ying_tu_xi': {'p': 12, 'max': 5, 'name': '暗影突袭'},
        'sk_br_ju_du_zhi_chu': {'max': 1, 'name': '剧毒之触'},
        'sk_br_du_wu_cui': {'p': 12, 'max': 5, 'name': '毒雾·淬'},
        'sk_br_du_wu_zhang': {'max': 3, 'name': '毒雾·障'},
        'sk_br_cui_du_zhi_xin': {'max': 1, 'name': '淬毒之心'},
        'sk_br_cui_du_ci_sha': {'p': 12, 'max': 5, 'name': '淬毒刺杀'},
        'sk_br_fu_shi_zhi_ren': {'p': 10, 'max': 5, 'name': '腐蚀之刃'},
        'sk_br_wan_ying_gui_yi': {'p': 10, 'max': 4, 'name': '万影归一'},
        'sk_br_huan_ying_wu': {'p': 9, 'max': 5, 'name': '幻影舞'},
        'sk_br_ying_zhi_guo_du': {'max': 3, 'name': '影之国度'},
        'sk_br_ying_wu_wu_jian': {'max': 1, 'name': '影舞·无间'},
        'sk_br_zhong_jie_an_ying_jiao_sha': {'p': 12, 'max': 5, 'name': '终结·暗影绞杀'},
        'sk_br_wan_du_shi_xin': {'p': 10, 'max': 5, 'name': '万毒噬心'},
        'sk_br_wan_du_gui_zong': {'max': 1, 'name': '万毒归宗'},
        'sk_br_ju_du_feng_bao': {'p': 12, 'max': 5, 'name': '剧毒风暴'},
        'sk_br_du_ren_gong_ming': {'max': 1, 'name': '毒刃·共鸣'},
        'sk_br_fu_shi': {'p': 12, 'max': 5, 'name': '腐世'},
        'sk_br_yuan_su_qin_he': {'max': 1, 'name': '元素亲和'},
        'sk_br_yuan_su_yan_mie': {'p': 10, 'max': 4, 'name': '元素湮灭'},
        'sk_br_shuang_xi_lian_zhu': {'p': 12, 'max': 5, 'name': '双系连珠'},
        'sk_br_leng_jing_hu_ti': {'max': 3, 'name': '棱镜护体'},
        'sk_br_rong_lu_ming_xiang': {'max': 3, 'name': '熔炉冥想'},
        'sk_br_zhi_yan': {'p': 12, 'max': 5, 'name': '织焰'},
        'sk_br_ao_shu_dan_mu': {'p': 9, 'max': 5, 'name': '奥术弹幕'},
        'sk_br_ao_shu_bao_po': {'p': 12, 'max': 5, 'name': '奥术爆破'},
        'sk_br_ao_shu_zhi_jue': {'max': 1, 'name': '奥术直觉'},
        'sk_br_ao_shu_fei_dan': {'p': 12, 'max': 5, 'name': '奥术飞弹'},
        'sk_br_shen_du_ming_xiang': {'max': 3, 'name': '深度冥想'},
        'sk_br_xiang_wei_pian_zhe': {'max': 3, 'name': '相位偏折'},
        'sk_br_yuan_su_zhi_he': {'max': 1, 'name': '元素之核'},
        'sk_br_yuan_su_tong_diao': {'max': 1, 'name': '元素同调'},
        'sk_br_yuan_su_hong_liu': {'p': 12, 'max': 5, 'name': '元素洪流'},
        'sk_br_yuan_su_liu_zhuan': {'max': 3, 'name': '元素流转'},
        'sk_br_yuan_su_beng_fa': {'p': 12, 'max': 5, 'name': '元素迸发'},
        'sk_br_huan_huo': {'max': 3, 'name': '唤火'},
        'sk_br_ao_shu_gong_ming': {'max': 1, 'name': '奥术共鸣'},
        'sk_br_ao_shu_li_chang': {'max': 3, 'name': '奥术力场'},
        'sk_br_ao_shu_hong_liu': {'p': 10, 'max': 4, 'name': '奥术洪流'},
        'sk_br_ao_shu_ju_zhen': {'max': 3, 'name': '奥术矩阵'},
        'sk_br_ao_shu_mai_chong': {'p': 10, 'max': 4, 'name': '奥术脉冲'},
        'sk_br_fa_shu_fan_zhi': {'max': 3, 'name': '法术反制'},
        'sk_br_wan_xiang_tian_lei': {'p': 10, 'max': 3, 'name': '万象天雷'},
        'sk_br_wan_xiang_feng_bao': {'p': 10, 'max': 4, 'name': '万象风暴'},
        'sk_br_yuan_su_cai_jue': {'p': 10, 'max': 3, 'name': '元素裁决'},
        'sk_br_yuan_su_qi_yuan': {'max': 1, 'name': '元素起源'},
        'sk_br_huan_lei': {'max': 3, 'name': '唤雷'},
        'sk_br_ao_shu_heng_chang': {'max': 1, 'name': '奥术恒常'},
        'sk_br_ao_shu_yan_mie': {'p': 10, 'max': 3, 'name': '奥术湮灭'},
        'sk_br_ao_mi_zhu_zai': {'p': 10, 'max': 3, 'name': '奥秘主宰'},
        'sk_br_xing_jie_feng_bao': {'p': 10, 'max': 4, 'name': '星界风暴'},
        'sk_br_zhen_zhi': {'max': 1, 'name': '真知'},
        'sk_br_zhao_huan_ku_lou': {'max': 3, 'name': '召唤骷髅'},
        'sk_br_mu_xue_di_yu': {'p': 12, 'max': 5, 'name': '墓穴低语'},
        'sk_br_si_ge_dao': {'max': 3, 'name': '死歌·悼'},
        'sk_br_ling_hun_biao_ji': {'max': 3, 'name': '灵魂标记'},
        'sk_br_gu_shi_zu_zhou': {'p': 12, 'max': 5, 'name': '骨噬诅咒'},
        'sk_br_hai_gu_ji_yi': {'p': 12, 'max': 5, 'name': '骸骨祭仪'},
        'sk_br_guang_yu': {'p': 12, 'max': 5, 'name': '光愈'},
        'sk_br_sheng_guang_hui_xiang': {'max': 1, 'name': '圣光回响'},
        'sk_br_sheng_guang_qi_dao': {'p': 12, 'max': 5, 'name': '圣光祈祷'},
        'sk_br_sheng_yan_shu': {'p': 12, 'max': 5, 'name': '圣言术'},
        'sk_br_sheng_hui_di_jing': {'p': 12, 'max': 5, 'name': '圣辉涤净'},
        'sk_br_shen_en_jiang_lin': {'p': 12, 'max': 5, 'name': '神恩降临'},
        'sk_br_wang_ling_ji_yi': {'max': 1, 'name': '亡灵祭仪'},
        'sk_br_wang_hun_hu_jia': {'max': 3, 'name': '亡魂护甲'},
        'sk_br_si_wang_qi_yue': {'max': 1, 'name': '死亡契约'},
        'sk_br_ling_hun_shou_ge': {'p': 10, 'max': 4, 'name': '灵魂收割'},
        'sk_br_ku_lou_hai': {'max': 1, 'name': '骷髅海'},
        'sk_br_hai_gu_hong_liu': {'p': 12, 'max': 5, 'name': '骸骨洪流'},
        'sk_br_xin_nian_liu_zhuan': {'max': 1, 'name': '信念·流转'},
        'sk_br_sheng_guang_bi_hu': {'max': 3, 'name': '圣光庇护'},
        'sk_br_sheng_guang_zhu_fu': {'max': 3, 'name': '圣光祝福'},
        'sk_br_sheng_ming_zhi_quan': {'p': 12, 'max': 5, 'name': '生命之泉'},
        'sk_br_shen_sheng_en_dian': {'p': 12, 'max': 5, 'name': '神圣恩典'},
        'sk_br_shen_ji': {'p': 12, 'max': 5, 'name': '神迹'},
        'sk_br_wang_hun_zhu_zai': {'p': 10, 'max': 3, 'name': '亡魂主宰'},
        'sk_br_wang_hun_da_jun': {'max': 3, 'name': '亡魂大军'},
        'sk_br_si_ji_ling_yu': {'p': 12, 'max': 5, 'name': '死寂领域'},
        'sk_br_yong_heng_an_hun': {'p': 10, 'max': 3, 'name': '永恒安魂'},
        'sk_br_ling_hun_suo_lian': {'max': 1, 'name': '灵魂锁链'},
        'sk_br_xin_nian_sheng_hua': {'max': 1, 'name': '信念·圣化'},
        'sk_br_sheng_guang_zan_ge': {'p': 10, 'max': 4, 'name': '圣光赞歌'},
        'sk_br_shu_guang': {'p': 10, 'max': 4, 'name': '曙光'},
        'sk_br_sheng_ming_sheng_yu': {'p': 10, 'max': 4, 'name': '生命圣域'},
        'sk_br_shen_ji_zhong_sheng': {'p': 12, 'max': 5, 'name': '神迹·重生'},
        'sk_br_er_zhong_chang': {'max': 1, 'name': '二重唱'},
        'sk_br_kai_xuan_zhi_ge': {'max': 3, 'name': '凯旋之歌'},
        'sk_br_yong_tan_yu': {'p': 12, 'max': 5, 'name': '咏叹·愈'},
        'sk_br_yong_tan_diao': {'p': 12, 'max': 5, 'name': '咏叹调'},
        'sk_br_ji_ang_zhan_ge': {'max': 3, 'name': '激昂战歌'},
        'sk_br_ying_xiong_zan_ge': {'max': 3, 'name': '英雄赞歌'},
        'sk_br_ai_ge': {'p': 12, 'max': 5, 'name': '哀歌'},
        'sk_br_an_mian_qu': {'max': 3, 'name': '安眠曲'},
        'sk_br_bei_ming': {'p': 12, 'max': 5, 'name': '悲鸣'},
        'sk_br_wan_ge': {'max': 3, 'name': '挽歌'},
        'sk_br_po_sui_he_yin': {'p': 12, 'max': 5, 'name': '破碎和音'},
        'sk_br_zhen_hun_ge': {'max': 3, 'name': '镇魂歌'},
        'sk_br_gong_ming': {'max': 1, 'name': '共鸣'},
        'sk_br_he_xian': {'max': 3, 'name': '和弦'},
        'sk_br_yong_tan_sheng_yong': {'p': 12, 'max': 5, 'name': '咏叹·圣咏'},
        'sk_br_yong_tan_hui': {'max': 3, 'name': '咏叹·辉'},
        'sk_br_po_xiao_zhang_ge': {'p': 10, 'max': 4, 'name': '破晓长歌'},
        'sk_br_ying_xiong_xu_shi_shi': {'max': 3, 'name': '英雄叙事诗'},
        'sk_br_wang_zhe_wan_ge': {'p': 12, 'max': 5, 'name': '亡者挽歌'},
        'sk_br_ai_dao_zhi_yin': {'p': 12, 'max': 5, 'name': '哀悼之音'},
        'sk_br_an_hun_qu': {'max': 3, 'name': '安魂曲'},
        'sk_br_wan_ge_chen': {'max': 3, 'name': '挽歌·沉'},
        'sk_br_chen_mo_zhi_ge': {'max': 3, 'name': '沉默之歌'},
        'sk_br_zhen_hun_an_hun': {'max': 1, 'name': '镇魂安魂'},
        'sk_br_wan_lai_he_ming': {'max': 1, 'name': '万籁和鸣'},
        'sk_br_yong_tan_ji': {'max': 1, 'name': '咏叹·极'},
        'sk_br_tian_lai': {'p': 10, 'max': 3, 'name': '天籁'},
        'sk_br_yong_heng_zan_ge': {'max': 3, 'name': '永恒赞歌'},
        'sk_br_zhong_zhang_li_ming_song_ge': {'max': 3, 'name': '终章·黎明颂歌'},
        'sk_br_wan_lai_ju_ji': {'p': 12, 'max': 5, 'name': '万籁俱寂'},
        'sk_br_wan_ge_ji': {'max': 1, 'name': '挽歌·极'},
        'sk_br_si_ji': {'p': 10, 'max': 3, 'name': '死寂'},
        'sk_br_zhong_mo_an_hun': {'max': 3, 'name': '终末安魂'},
        'sk_br_zhong_yan_wan_ge': {'max': 3, 'name': '终焉挽歌'},
        'sk_br_beng_quan': {'p': 12, 'max': 5, 'name': '崩拳'},
        'sk_br_xuan_feng_ti': {'p': 12, 'max': 5, 'name': '旋风踢'},
        'sk_br_qi_li_bao_fa': {'p': 12, 'max': 5, 'name': '气力爆发'},
        'sk_br_ji_feng_quan': {'p': 12, 'max': 5, 'name': '疾风拳'},
        'sk_br_sui_lu_shi': {'p': 12, 'max': 5, 'name': '碎颅势'},
        'sk_br_tie_shan_kao': {'max': 3, 'name': '铁山靠'},
        'sk_br_yi_shou_wei_gong': {'max': 1, 'name': '以守为攻'},
        'sk_br_hou_tu': {'max': 3, 'name': '厚土'},
        'sk_br_fan_zhen': {'max': 1, 'name': '反震'},
        'sk_br_shou_yu_zi_tai': {'max': 3, 'name': '守御姿态'},
        'sk_br_pan_yan_shi_neng': {'p': 12, 'max': 5, 'name': '磐岩释能'},
        'sk_br_tie_bi_quan': {'p': 12, 'max': 5, 'name': '铁壁拳'},
        'sk_br_qi_li_zhi_xin': {'max': 1, 'name': '气力之心'},
        'sk_br_qi_li_lie_kong': {'p': 12, 'max': 5, 'name': '气力裂空'},
        'sk_br_po_zhan_gan_zhi': {'max': 1, 'name': '破绽感知'},
        'sk_br_lie_yue_lian_ji': {'p': 9, 'max': 5, 'name': '裂岳连击'},
        'sk_br_lian_huan_quan': {'p': 9, 'max': 5, 'name': '连环拳'},
        'sk_br_zhen_she_quan': {'p': 12, 'max': 5, 'name': '震慑拳'},
        'sk_br_fan_ji_zhi_wang': {'max': 1, 'name': '反击之王'},
        'sk_br_da_di_zhi_fu': {'max': 1, 'name': '大地之肤'},
        'sk_br_qi_li_shou_yu': {'max': 3, 'name': '气力守御'},
        'sk_br_pan_yan_jia': {'max': 3, 'name': '磐岩甲'},
        'sk_br_pan_he_bao_fa': {'p': 12, 'max': 5, 'name': '磐核爆发'},
        'sk_br_pan_shi_zhi_xin': {'max': 1, 'name': '磐石之心'},
        'sk_br_beng_shan': {'p': 10, 'max': 4, 'name': '崩山'},
        'sk_br_han_yue_zhong_yan': {'p': 10, 'max': 3, 'name': '撼岳·终焉'},
        'sk_br_wu_ying_lian_da': {'p': 9, 'max': 5, 'name': '无影连打'},
        'sk_br_qi_li_tong_tian': {'p': 10, 'max': 4, 'name': '气力通天'},
        'sk_br_po_zhan_ji': {'max': 1, 'name': '破绽·极'},
        'sk_br_bu_dong_ru_shan': {'max': 1, 'name': '不动如山'},
        'sk_br_da_di_shou_hu': {'max': 3, 'name': '大地守护'},
        'sk_br_qi_li_wan_fa': {'p': 12, 'max': 5, 'name': '气力万法'},
        'sk_br_pan_yan_zhen_shi': {'p': 10, 'max': 4, 'name': '磐岩·镇世'},
        'sk_br_pan_shi_zhi_qu': {'max': 1, 'name': '磐石之躯'},
        'sk_br_zhao_huan_teng_man_shou_wei': {'max': 3, 'name': '召唤藤蔓守卫'},
        'sk_br_sen_yu_yin_ji': {'max': 3, 'name': '森语印记'},
        'sk_br_cui_du_jian': {'p': 12, 'max': 5, 'name': '淬毒箭'},
        'sk_br_jing_ji_bao': {'p': 12, 'max': 5, 'name': '荆棘爆'},
        'sk_br_teng_man_chan_rao': {'p': 12, 'max': 5, 'name': '藤蔓缠绕'},
        'sk_br_zhui_lie': {'p': 12, 'max': 5, 'name': '追猎'},
        'sk_br_shuang_zhong_she_ji': {'p': 12, 'max': 5, 'name': '双重射击'},
        'sk_br_xing_gui_suo_ding': {'max': 3, 'name': '星轨锁定'},
        'sk_br_ji_feng_she_ji': {'p': 12, 'max': 5, 'name': '疾风射击'},
        'sk_br_ji_feng_bu': {'max': 3, 'name': '疾风步'},
        'sk_br_xu_li_she_ji': {'p': 12, 'max': 5, 'name': '蓄力射击'},
        'sk_br_feng_ren_luan_wu': {'p': 9, 'max': 5, 'name': '风刃乱舞'},
        'sk_br_ju_du_zhi_xin': {'max': 1, 'name': '剧毒之心'},
        'sk_br_lie_sha_kuang_yan': {'p': 12, 'max': 5, 'name': '猎杀狂宴'},
        'sk_br_chuan_xin_jian': {'p': 12, 'max': 5, 'name': '穿心箭'},
        'sk_br_zi_ran_zhi_yan': {'max': 1, 'name': '自然之眼'},
        'sk_br_zi_ran_hu_you': {'max': 3, 'name': '自然护佑'},
        'sk_br_zhui_lie_zhe': {'max': 1, 'name': '追猎者'},
        'sk_br_ji_su_she_ji': {'p': 9, 'max': 5, 'name': '急速射击'},
        'sk_br_ji_feng_zhi_xin': {'max': 1, 'name': '疾风之心'},
        'sk_br_chuan_yun_jian': {'p': 12, 'max': 5, 'name': '穿云箭'},
        'sk_br_chuan_jia_she_ji': {'p': 12, 'max': 5, 'name': '穿甲射击'},
        'sk_br_zhui_feng': {'max': 1, 'name': '追风'},
        'sk_br_feng_zhi_ping_zhang': {'max': 3, 'name': '风之屏障'},
        'sk_br_zhao_huan_gu_shu_shou_wei': {'max': 3, 'name': '召唤古树守卫'},
        'sk_br_sen_zhi_gong_ming': {'max': 1, 'name': '森之共鸣'},
        'sk_br_si_shen_zhi_jian': {'p': 10, 'max': 4, 'name': '死神之箭'},
        'sk_br_lie_sha_shi_ke': {'max': 3, 'name': '猎杀时刻'},
        'sk_br_zhi_ming_lian_she': {'p': 9, 'max': 5, 'name': '致命连射'},
        'sk_br_ji_feng_ji': {'max': 1, 'name': '疾风·极'},
        'sk_br_ji_feng_zhou_yu': {'p': 9, 'max': 5, 'name': '疾风骤雨'},
        'sk_br_guan_ri_jian': {'p': 10, 'max': 4, 'name': '贯日箭'},
        'sk_br_feng_bao_zhi_wu': {'p': 9, 'max': 5, 'name': '风暴之舞'},
        'sk_br_feng_shen_jiang_lin': {'max': 3, 'name': '风神降临'},
        'sk_br_shi_xue_zhan': {'p': 12, 'max': 5, 'name': '嗜血斩'},
        'sk_br_nu_zhan': {'p': 12, 'max': 5, 'name': '怒斩'},
        'sk_br_cui_xue': {'max': 1, 'name': '淬血'},
        'sk_br_kuang_zhan_nu_hou': {'max': 3, 'name': '狂战怒吼'},
        'sk_br_po_shi_zhan': {'p': 12, 'max': 5, 'name': '破势斩'},
        'sk_br_lie_di_zhan': {'p': 12, 'max': 5, 'name': '裂地斩'},
        'sk_br_chao_feng': {'max': 3, 'name': '嘲讽'},
        'sk_br_jian_dun_bi_lei': {'max': 3, 'name': '坚盾壁垒'},
        'sk_br_shou_hu_zi_tai': {'max': 3, 'name': '守护姿态'},
        'sk_br_dun_ji_shi': {'p': 12, 'max': 5, 'name': '盾击·誓'},
        'sk_br_tie_bi_shi': {'max': 3, 'name': '铁壁·誓'},
        'sk_br_dun_zu': {'p': 12, 'max': 5, 'name': '顿足'},
        'sk_br_nu_tao_lian_zhan': {'p': 9, 'max': 5, 'name': '怒涛连斩'},
        'sk_br_duan_jin': {'p': 10, 'max': 4, 'name': '断筋'},
        'sk_br_fen_tian_zhan': {'p': 12, 'max': 5, 'name': '焚天斩'},
        'sk_br_kuang_re': {'max': 1, 'name': '狂热'},
        'sk_br_xue_ji': {'max': 3, 'name': '血祭'},
        'sk_br_long_xi_zhi_nu': {'p': 10, 'max': 5, 'name': '龙息之怒'},
        'sk_br_sheng_dun': {'max': 3, 'name': '圣盾'},
        'sk_br_jian_ren': {'max': 1, 'name': '坚韧'},
        'sk_br_fu_chou': {'p': 12, 'max': 5, 'name': '复仇'},
        'sk_br_zhan_hou_shou': {'max': 3, 'name': '战吼·守'},
        'sk_br_po_cheng_chui': {'p': 10, 'max': 4, 'name': '破城锤'},
        'sk_br_shi_yue_zhi_dun': {'max': 3, 'name': '誓约之盾'},
        'sk_br_nu_tao_zhong_yan': {'p': 9, 'max': 5, 'name': '怒涛·终焉'},
        'sk_br_zhan_zheng_hua_shen': {'p': 10, 'max': 3, 'name': '战争化身'},
        'sk_br_zhan_yi_ji': {'p': 10, 'max': 3, 'name': '战意·极'},
        'sk_br_liao_yuan_zhi_nu': {'p': 10, 'max': 4, 'name': '燎原之怒'},
        'sk_br_xue_nu_bu_mie': {'max': 1, 'name': '血怒·不灭'},
        'sk_br_bu_po_bi_lei': {'max': 3, 'name': '不破壁垒'},
        'sk_br_jian_cheng_zhi_zi': {'max': 1, 'name': '坚城之姿'},
        'sk_br_shou_hu_sheng_yu': {'max': 3, 'name': '守护圣域'},
        'sk_br_shou_hu_shi_yan': {'max': 3, 'name': '守护誓言'},
        'sk_br_tie_shi_bu_dong': {'max': 1, 'name': '铁誓·不动'},
        # ---------------- 导师技 TUTOR_SKILLS（key=现存 sk_id） ----------------
        'sk_cui_du_zhi_ren': {'p': 12, 'max': 5, 'name': '淬毒秘术'},
        'sk_mo_li_mai_chong': {'p': 12, 'max': 5, 'name': '魔力脉冲'},
        'sk_jiu_shu_zhi_guang': {'p': 12, 'max': 3, 'name': '救赎之光'},
        'sk_sheng_guang_shen_pan': {'p': 12, 'max': 3, 'name': '圣光审判'},
        'sk_beng_quan_lie': {'p': 12, 'max': 4, 'name': '裂骨击'},
        'sk_jin_gang_ti': {'max': 3, 'name': '磐石之体'},
    }



class _ContentShim:
    """`game/content.py` 聚合层的包内等价物 —— 只含本模块读的 5 个符号。"""

    PLAYER_SKILLS = PLAYER_SKILLS
    BRANCH_SKILLS = BRANCH_SKILLS
    TUTOR_SKILLS = TUTOR_SKILLS
    SKILL_UP = SKILL_UP

    @staticmethod
    def resolve(table_name: str, name_or_id: str):
        """名字或 id → id（找不到原样返回）—— `content/tables.py:resolve`（= `game/core/index.py:47`）。"""
        return _T.resolve(table_name, name_or_id)


C = _ContentShim()


# ============================================================
# 技能表读取
# ============================================================

# v48：职业/技能均用 ID 访问。表结构已变 {cls_id: {"name":.., "skills": {sk_id: def}}}
# 兼容 v48 前旧结构 {职业: {技能: def}} 的读取辅助。
def _sk_table(class_name: str) -> dict:
    class_name = C.resolve("classes", class_name)  # v48：统一转 ID
    t = C.PLAYER_SKILLS.get(class_name, {})
    if isinstance(t, dict) and "skills" in t:
        return t["skills"]
    return t


def _br_table(class_name: str) -> dict:
    class_name = C.resolve("classes", class_name)
    t = C.BRANCH_SKILLS.get(class_name, {})
    if isinstance(t, dict) and "branches" in t:
        return t["branches"]
    return t


# v177 怪物引用玩家技能：技能 key 全局唯一 → 扫全表缓存 {sk_id: (cls_id, info)}
_SKILL_KEY_INDEX: dict | None = None


def _build_skill_key_index() -> dict:
    """全量玩家技能索引：{sk_id: (所属职业, info)}——覆盖基础职业 + 分支 + 导师。
    供怪物技能引用玩家技能（存储分离、解析一套）与全局技能 key 反查。"""
    idx = {}
    for cls_id, cls in (C.PLAYER_SKILLS or {}).items():
        if not isinstance(cls, dict):
            continue
        for sk, info in (cls.get("skills") or {}).items():
            if sk not in idx:
                idx[sk] = (cls_id, info)
    for cls_id, brs in (C.BRANCH_SKILLS or {}).items():
        if not isinstance(brs, dict):
            continue
        for tier, branches in (brs.get("branches") or {}).items():
            for bname, skills in (branches or {}).items():
                for sk, info in (skills or {}).items():
                    if sk not in idx:
                        idx[sk] = (cls_id, info)
    for cls_id, t_skills in (C.TUTOR_SKILLS or {}).items():
        for sk, info in (t_skills or {}).items():
            if sk not in idx:
                idx[sk] = (cls_id, info)
    return idx


def skill_by_key(key: str) -> dict | None:
    """v177 按技能 key 全局查玩家技能（怪物引用玩家技能用）。查不到返回 None。"""
    global _SKILL_KEY_INDEX
    if _SKILL_KEY_INDEX is None:
        _SKILL_KEY_INDEX = _build_skill_key_index()
    hit = _SKILL_KEY_INDEX.get(key)
    return hit[1] if hit else None


def skill_owner_cls(key: str) -> str | None:
    """v177 技能 key 所属职业（怪物引用需知道怪物有没有该技能时用）。"""
    global _SKILL_KEY_INDEX
    if _SKILL_KEY_INDEX is None:
        _SKILL_KEY_INDEX = _build_skill_key_index()
    hit = _SKILL_KEY_INDEX.get(key)
    return hit[0] if hit else None


def skills_for_level(class_name: str, level: int) -> list[str]:
    """返回该职业当前等级已解锁的技能 id"""
    skills = _sk_table(class_name)
    return [name for name, info in skills.items() if info["lv"] <= level]


def is_skill_learned(class_name: str, level: int, skill_name: str, learned_skills: list | None = None) -> bool:
    """技能是否已学会(v12：必须『技能学习』花技能点学会才能使用，不再按等级自动解锁)"""
    info = skill_info(class_name, skill_name)
    if not info:
        return False
    # v48：learned_skills 是中文名（store 读回），skill_name 可能是 ID——统一 resolve 比较
    sid = C.resolve("skills", skill_name)
    return sid in [C.resolve("skills", s) for s in (learned_skills or []) if s]


def skill_info(class_name: str, skill_name: str):
    """技能详情：先查基础职业技能表，再查分支专属技能表（v26），最后查导师进阶技能（v95.23）
    v48：skill_name 接受中文名或 ID，统一 resolve 为 ID 再查（表 key 已是 sk_xxx）"""
    skill_name = C.resolve("skills", skill_name)
    info = _sk_table(class_name).get(skill_name)
    if info:
        return info
    for tier, branches in _br_table(class_name).items():
        for bname, skills in branches.items():
            if skill_name in skills:
                return skills[skill_name]
    # v95.23 职业导师进阶技能（TUTOR_SKILLS 并入查询链，battle/面板共用）
    t_info = (C.TUTOR_SKILLS or {}).get(class_name, {}).get(skill_name)
    if t_info:
        return t_info
    return None


def branch_skill_owner(class_name: str, skill_name: str):
    """分支专属技能归属：(tier, 分支名)；非分支技能返回 None(v26)"""
    skill_name = C.resolve("skills", skill_name)
    for tier, branches in _br_table(class_name).items():
        for bname, skills in branches.items():
            if skill_name in skills:
                return tier, bname
    return None


def branch_path_index(class_name: str, tier: int, branch_key: str):
    """分支 key 在该 tier 分支组内的 index（0/1）；找不到返回 None。

    v174：显示层用——BRANCH_SKILLS 分支 key 保持 B1 名（系统约定，如牧师 B2 key 仍
    "神谕者"），需按 tier 内位置映射到 classes.evolve_branches 的档位名（大主教/圣光先知等）。
    """
    try:
        branches = _br_table(class_name)
        blist = list((branches.get(int(tier)) or {}).keys())
        for i, bk in enumerate(blist):
            if bk == branch_key:
                return i
    except Exception:
        return None
    return None


# ============================================================
# 技能升级配置（C.SKILL_UP 表读）
# ============================================================

# v181 P0B-C：SKILL_UP key 已改稳定 id（见 game/data/skill_up.py 头注）。中文名→id 反查索引，
# 懒构建缓存（SKILL_UP 条目 name 字段 = 技能中文名，构建期自检保证全局唯一）。
_SKILL_UP_NAME_INDEX: dict | None = None


def _skill_up_name_index() -> dict:
    global _SKILL_UP_NAME_INDEX
    if _SKILL_UP_NAME_INDEX is None:
        _idx = {}
        for _sid, _cfg in (C.SKILL_UP or {}).items():
            _nm = _cfg.get("name") if isinstance(_cfg, dict) else None
            if _nm and _nm not in _idx:  # 首个赢（自检已保证 name 唯一，防御性 setdefault）
                _idx[_nm] = _sid
        _SKILL_UP_NAME_INDEX = _idx
    return _SKILL_UP_NAME_INDEX


def _skill_up(info: dict | None) -> dict:
    """按技能 info 查升级配置（v181 P0B-C：key 用稳定 id，不再用中文显示名）。

    v180 隔离：仅玩家可升级技能（带 lv 学习等级字段）参与 SKILL_UP 查表——
    怪技能（MONSTER_SKILLS，无 lv）即使 name 与玩家技能撞名（圣光弹/雷击/龙爪等 14 个）
    也不会误配玩家成长曲线（v180 P4 删默认成长后，撞名怪技能曾吃到玩家同名配置 p=10~12）。

    v181 P0B-C（方案 C，docs/REFACTOR_P0B_skill_up_dedup.md §4 Step2）：
    SKILL_UP key 已从中文名改为稳定 id（基础/导师 = 技能表现存 sk_id；分支 = sk_br_<pinyin>），
    每条条目带 name=中文名。skill_info 返回的 info 不带 id 字段（三表查询链只给 info dict），
    故在此用 info['name'] 经『中文名→id』索引反查稳定 id 后按 id 查表；查不到（无配置/防御）
    再回落 SKILL_UP.get(name)——data 层当前无中文 key，此处为兼容历史语义（将来若有人
    把旧中文名当 key 塞回 SKILL_UP 不至于静默失效）。"""
    if not info:
        return {}
    if info.get("lv") is None:
        return {}
    _name = info.get("name", "")
    _sid = _skill_up_name_index().get(_name)
    if _sid:
        _hit = C.SKILL_UP.get(_sid)
        if _hit is not None:
            return _hit
    return C.SKILL_UP.get(_name) or {}


def skill_upgrade_cost(cur_lv: int, info: dict | None = None) -> int:
    """升级消耗（递增）：Lv.1→2 花1点，2→3 花2点，3→4 花3点，4→5 花4点
    v56.4：达到该技能独立满级（max）后返回 0"""
    mx = skill_max_level(info)
    if cur_lv < 1 or cur_lv >= mx:
        return 0
    return cur_lv


# ============================================================
# 技能等级查询（玩家档 + 技能 id resolve）
# ============================================================

def skill_level_of(player: dict, skill_name: str) -> int:
    """技能等级查询（v46+ 兼容）：store 读库后 skill_levels 的 key 是中文名（players.py:113 display 转换），
    入参可能是 ID 或中文名——统一 resolve 后匹配，查不到按未升级 Lv.1。
    修复 #259：技能列表/详情/战斗内此前用 ID 直接查 key 恒 fallback Lv.1（战斗内实际按 Lv.1 计算）。"""
    levels = player.get("skill_levels") or {}
    if not levels:
        return 1
    sid = C.resolve("skills", skill_name)
    for k, v in levels.items():
        if k and C.resolve("skills", k) == sid:
            return int(v or 1)
    return 1


# ============================================================
# 接线别名（**非**真源内容；真源由 `game/bootstrap.py` 直挂 hook，包内由 `content/apply.py` 挂）
# 引擎 `skill_up_fn` 受体就是这里这个函数（`fn(info) -> dict`），真源私有名 `_skill_up`，
# 包内给公开别名以免 apply.py 引私有名。逐字搬以外的**唯一**新增（2 行）。
# ============================================================
skill_up = _skill_up


__all__ = [
    "PLAYER_SKILLS", "BRANCH_SKILLS", "TUTOR_SKILLS", "SKILL_UP",
    "skill_info", "skill_by_key", "skill_owner_cls", "skills_for_level",
    "is_skill_learned", "branch_skill_owner", "branch_path_index",
    "skill_up", "skill_upgrade_cost", "skill_level_of",
]
