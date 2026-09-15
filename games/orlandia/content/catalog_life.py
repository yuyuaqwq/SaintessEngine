# -*- coding: utf-8 -*-
"""包内生活经济门面（`content/catalog_life.py`）—— 游戏仓聚合层 `C` 的「D-生活经济族」等价物。

为什么需要它
------------
宿主 `game/content.py` 是 19 行薄聚合层（`from .data import *` + `from .core import *`），
包内模块过去用宿主句柄（`_HostMod("content")` / `bind_host(content=C)`）读它的名字。
宿主 `game/data`（74,707 行 / 87 文件）要删，所以这些名字必须先在包内**由域 JSON 重建**——
本模块就是 D 单元（生活经济族，53 个数据名里可从域重建的 42 个）的那一层。

读口纪律（B14_BRIEF §3 / 计划 §9 I1·I2）
----------------------------------------
* 只读包内域数据：`content/data/<域>.json` · `content/rules/<域>.json`（缺文件/坏 JSON → 空，不抛，
  与 `content/tables.py:48 _read_json` 同款）。
* **不 import 宿主任何模块**、**不用 `_HostMod`/`_host_attr`** —— 宿主表删掉之后本模块仍能活。

域来源（真源 = 游戏仓；单向导出器 = 游戏仓 `scripts/export_*`）
--------------------------------------------------------------
    content/data/craft.json             ← derive_craft       426 条配方（含导出期注入的 `aliases`）
    content/data/alchemy.json           ← derive_alchemy      91 条炼金配方
    content/data/cooking.json           ← derive_cooking      59 条烹饪配方
    content/data/fishing_spots.json     ← derive_fishing_spots 11 个钓点
    content/data/fishing_pool.json      ← derive_fishing_pool  30 条渔获（带 `seq` = 源插入序）
    content/data/shop.json              ← derive_shop        89 条店铺合表（六张源表并集）
    content/data/pets.json              ← derive_pets        16 个品种（每品种挂 `egg_roll` 规则行）
    content/rules/game_config.json      ← derive_game_config 配置/常量归口（一条 = 一个源模块）

三处「类型还原」（JSON 只有 str 键 / 只有 array，不做还原就是静默错值）
----------------------------------------------------------------------
  ① **int 键**：`HOUSE_LEVELS` / `HOUSE_REFUND` / `RUNE_LEVEL_GATE` —— 源里是 int 键
     （`HOUSE_LEVELS[lv]`、`RUNE_LEVEL_GATE[gem_lv]`），不还原 = 查表恒空（与 `tables.py:ENHANCE_TABLE` 同族坑）。
  ② **tuple 值**：`PROF_TUTORS` / `PROF_WAIT_BASE` / `DAILY_PROF_TASKS` —— 源里是元组
     （消费端按 `(导师, 城市)` / `(低, 高, 名)` 解包），JSON 落成 array → 必须还原成 tuple，
     否则门禁深比较报「类型不同（tuple vs list）」。
  ③ **导出期注入字段要剥**：`craft.json` 条目的 `aliases`（= 真源 `CRAFT_RECIPE_ALIASES` 折进条目）
     → `CRAFT_RECIPES` 必须剥掉它、`CRAFT_RECIPE_ALIASES` 由它重建；
     `fishing_pool.json` 的 `seq`、`pets.json` 的 `egg_roll` 同理（`FISH_POOL` 剥 `seq`、`PET_POOL` 剥 `egg_roll`）。

键序（迭代序）：域落盘走导出契约 `sort_table`（字典序），真源是**手写插入序** ⇒ 序不可逆
--------------------------------------------------------------------------------------
本模块按 `content/quests_flow.py:SIDE_QUEST_ORDER` / `content/event_menu.py:MAP_ORDER` /
`content/tables.py:JOB_ORDER` 同一手法**显式声明真源插入序**（`_ORDER_*`，见「① 顺序声明」段），
带集合守卫：域里多一条/少一条就 `raise`（防「加了内容忘了改这里」= 静默改序）。
顺序字面量由 `overnight/_b14d_gen_orders.py` 从真源生成（本文件不手抄）。
更彻底的做法是**在域里补 `seq`/`order` 字段**（I3 反向可逆性）—— 已在 `overnight/W-B14-D.md` 登记给主 agent 裁。

⚠ 无域可依的名字（11 个）：本模块**不提供**（不许编数据），逐名缺口见 `overnight/W-B14-D.md`：
    PET_MAX_LEVEL · PET_SKILL_UNLOCK_LV                —— 宿主 `game/data/pets.py`（常量段，无域）
    FISH_COLLECT · FISH_EXP                            —— 宿主 `game/data/fishing.py`（导出器只导了 FISH_POOL）
    FACTIONS · FACTION_ORDER · REPUTATION_TIERS ·
    AREA_FACTION · CHRONICLES                          —— 宿主 `game/data/factions.py`（无域）
    HONOR_SHOP                                         —— 宿主 `game/data/honor_shop.py`（无域）
    GUILD_CONFIG                                       —— 宿主 `game/data/guild.py`（guild 域只导了 roles/shop_items/skills）
"""
from __future__ import annotations

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))          # <pkg>/content
_DATA_DIR = os.path.join(_HERE, "data")
_RULES_DIR = os.path.join(_HERE, "rules")


def _read_json(path: str, default):
    """读一个 JSON 文件（缺文件 / 坏 JSON / 权限 → default，不抛）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                        # noqa: BLE001
        return default


def _read_domain(domain: str, sub: str, default):
    """读包内 `content/<sub>/<domain>.json`（`sub` = data|rules）。"""
    return _read_json(os.path.join(_HERE, sub, f"{domain}.json"), default)


def _int_keys(tbl) -> dict:
    """字符串键 → int 键（JSON 只有 str 键；非整数键**原样保留**，不静默丢）。"""
    out: dict = {}
    for k, v in (tbl or {}).items():
        try:
            out[int(k)] = v
        except (TypeError, ValueError):
            out[k] = v
    return out


def _tupled(tbl) -> dict:
    """值是 array 的条目 → tuple（源侧是元组，消费端按位解包）。**键序原样**。"""
    return {k: tuple(v) for k, v in (tbl or {}).items()}


def _pick(tbl, field: str) -> dict:
    """从「合表」里取某一列：`{键: 条目[field]}`（条目没这列 → 该键不出现，不补空）。"""
    return {k: v[field] for k, v in (tbl or {}).items() if field in v}


# ============================================================
# ① 顺序声明 —— 真源插入序（域落盘是字典序，序只能显式带出）
#    字面量由 `overnight/_b14d_gen_orders.py` 从真源生成；本文件不手抄。
# ============================================================
# __B14D_ORDERS_BEGIN__
_ORDER_CRAFT_RECIPES = """
rec_ao_la_sheng_yin rec_ao_lan_zhi_zhu rec_bai_lu_pi_jia rec_bei_feng_zhang_gong rec_cang_qiong_hu_tui rec_cang_qiong_tou_kui rec_cang_qiong_xiang_lian rec_cang_qiong_zhi_qiang
rec_chao_xi_fa_zhang rec_chen_xi_fa_zhang rec_chen_xi_zhi_guan rec_chuan_zhang_mao rec_gu_lu_de_huang_guan rec_di_di_zhang_xue rec_fu_wen_jie_zhi rec_gu_wang_jian
rec_hai_dao_xue rec_hai_feng_zhang_gong rec_hai_shen_hu_tui rec_hai_shen_jie_zhi rec_hai_shen_san_cha_ji rec_hai_shen_xiang_lian rec_hai_shen_zhang_xue rec_he_er_jia_de_ji_qi
rec_hei_yao_hu_tui rec_hei_yao_xiong_jia rec_jin_gou_wan_dao rec_jing_ling_lian_jia rec_jiu_pi_xue rec_lan_ge_zhi_lei rec_lie_gong rec_lie_lu_gong
rec_long_ji_da_jian rec_long_lin_hai_jia rec_long_lin_hu_tui rec_long_lin_tou_kui rec_long_lin_xiong_jia rec_long_yan_xiang_lian rec_long_yu_fa_zhang rec_long_yu_sheng_jian
rec_long_zhao_shou_tao rec_mao_xing_jie_zhi rec_mo_luo_zhi_guan rec_mu_ying_zhi_ren rec_pi_jia rec_qi_shi_tou_kui rec_qi_shi_zhang_xue rec_rong_lu_xiang_lian
rec_rong_yan_fa_zhang rec_shen_pan_zhi_lian rec_shen_yuan_tou_kui rec_shen_yuan_xiang_lian rec_shen_yuan_zhan_ren rec_sheng_dian_zhan_chui rec_sheng_guang_hu_fu rec_sheng_guang_hu_tui
rec_sheng_guang_xiong_jia rec_sheng_guang_zhang_jian rec_sheng_cai_chang_jian rec_sheng_guang_fa_zhang rec_sheng_guang_lie_gong rec_sheng_guang_zhan_chui rec_sheng_guang_zhan_kui rec_sheng_guang_zhan_tui
rec_sheng_guang_zhong_jia rec_sheng_guang_zhong_xue rec_shuang_lang_hu_tui rec_shuang_lang_tou_kui rec_shuang_lang_zhang_jian rec_shuang_yuan_zhang_xue rec_shui_shou_duan_ren rec_shui_shou_hu_tui
rec_shui_shou_jia_ke rec_tie_jian rec_tie_zhen_xiong_jia rec_tie_zhen_zhan_chui rec_wan_dao rec_wang_dou_zhang_gong rec_wang_guo_hui_jie rec_xiang_mu_duan_gun
rec_xiang_mu_dun rec_xiang_mu_hu_tui rec_xing_chen_zhi_jie rec_xing_chen_zhui_shi rec_xing_chen_hu_tui rec_xing_chen_chang_pao rec_xing_chen_fa_zhang rec_hui_jin_zhi_kui
rec_hui_jin_zhan_xue rec_hui_jin_hu_tui rec_hui_jin_kai_jia rec_hui_jin_chang_jian rec_hui_jin_zhi_dun rec_xing_guang_fa_zhang rec_xing_hui_zhang_xue rec_xing_yu_xiang_lian
rec_xue_tu_fa_zhang rec_xue_tu_zhi_zhang rec_yin_ye_fa_zhang rec_yue_guan_tou_kui rec_yue_guang_duan_ren rec_yue_hua_jie_zhi rec_yue_yu_hu_tui rec_yue_yu_zhang_gong
rec_yue_zhi_xue rec_yun_wen_xiong_jia rec_zhen_zhu_tou_guan rec_zhen_zhu_xiang_lian rec_yin_ling_tou_kui rec_yin_ling_xiong_jia rec_yin_ling_zhan_xue rec_yin_ling_xiang_lian
rec_yin_ling_hu_tui rec_yin_ling_zhang rec_yin_ling_duan_ren rec_shi_yue_quan_zhang rec_shi_yue_sheng_guan rec_shi_yue_fa_yi rec_shi_yue_sheng_xue rec_fei_cui_pi_jia
rec_fei_cui_hu_tui rec_fei_cui_tou_kui rec_fei_cui_zhan_xue rec_fei_cui_xiang_lian rec_mi_wu_xiong_jia rec_mi_wu_zhan_xue rec_mi_wu_dou_mao rec_mi_wu_xiang_lian
rec_lie_feng_chang_gong rec_ji_feng_chang_gong rec_lie_zong_liao_ya rec_tie_ya_lang_pi_jia rec_lei_ming_long_lin_dun rec_jin_he_zhi_xin_zhang rec_mu_ying_long_hun_jian rec_he_er_jia_jing_zhu
rec_lan_ge_lei_zheng rec_gu_wang_jian_zhen rec_lei_ming_jin_shou rec_feng_bao_cang_qiong rec_yong_dong_shuang_hui rec_hui_ai_tie_zhen rec_hei_yuan_zhan_ren rec_long_gong_yuan_xiang
rec_sheng_guang_yue_jia rec_lan_ge_hai_xiang rec_yao_sai_bei_feng rec_long_yu_chuan_jian rec_ye_xing_pi_feng rec_rong_lu_zhi_xin rec_xue_shi_zhan_jian rec_xue_shi_zhan_jia
rec_yu_jin_jun_tuan_jian rec_yu_jin_jun_tuan_kui rec_yu_jin_jun_tuan_jia rec_yu_jin_jun_tuan_xue rec_yuan_su_shi_tu_fa_zhang rec_yuan_su_shi_tu_zhi_guan rec_yuan_su_shi_tu_chang_pao rec_yuan_su_shi_tu_zhui_shi
rec_shi_zhi_ling_zhu_mi_yi rec_shi_zhi_ling_zhu_shi_jie rec_xun_lin_chang_pi_feng rec_xun_lin_chang_gong rec_lie_shou_chang_gong rec_lie_shou_pi_mao rec_lie_shou_pi_jia rec_lie_shou_chang_xue
rec_ri_mian_quan_zhang rec_ri_mian_sheng_guan rec_ri_mian_fa_yi rec_ri_mian_sheng_xue rec_ye_dao_quan_zhang rec_ye_dao_dou_mao rec_ye_dao_fa_yi rec_ye_dao_zhi_jie
rec_ying_sha_zhi_ren rec_ying_sha_mian_jin rec_ying_sha_pi_yi rec_ying_sha_hu_tui rec_ying_sha_qing_xue rec_xu_shi_quan_tao rec_xu_shi_shu_dai rec_po_zhu_quan_tao
rec_po_zhu_wu_pao rec_po_zhu_hu_tui rec_po_zhu_bu_xue rec_tiepichangjian rec_tiepitoukui rec_tiepixiongjia rec_tiepihutui rec_tiepizhanxue
rec_jingtiezhanjian rec_jingtietoukui rec_jingtiexiongjia rec_jingtiehutui rec_jingtiezhanxue rec_bailianchangjian rec_bailiantoukui rec_bailianxiongjia
rec_bailianhutui rec_bailianzhanxue rec_jianxifazhang rec_xuetufamao rec_xuetuchangpao rec_xuetuhutui rec_xuetufaxue rec_fuwenfazhang
rec_fuwenfamao rec_fuwenchangpao rec_fuwenhutui rec_fuwenfaxue rec_mifafazhang rec_mifafamao rec_mifachangpao rec_mifahutui
rec_mifafaxue rec_buyiquanzhang rec_buyishengguan rec_buyifayi rec_buyihutui rec_buyishengxue rec_zhufuquanzhang rec_zhufushengguan
rec_zhufufayi rec_zhufuhutui rec_zhufushengxue rec_shengtangquanzhang rec_shengtangshengguan rec_shengtangfayi rec_shengtanghutui rec_shengtangshengxue
rec_lie_shou_duan_gong rec_lie_shou_xin_pi_mao rec_lie_shou_xin_pi_jia rec_lie_shou_hu_tui rec_lie_shou_xin_chang_xue rec_feng_xing_chang_gong30 rec_feng_xing_pi_mao rec_feng_xing_pi_jia
rec_feng_xing_hu_tui rec_feng_xing_chang_xue rec_an_ye_chang_gong rec_an_ye_pi_mao rec_an_ye_pi_jia rec_an_ye_hu_tui rec_an_ye_chang_xue rec_qing_ying_bi_shou
rec_qing_ying_mian_jin rec_qing_ying_pi_yi rec_qing_ying_hu_tui rec_qing_ying_qing_xue rec_ye_xing_bi_shou rec_ye_xing_mian_jin rec_ye_xing_pi_yi rec_ye_xing_hu_tui
rec_ye_xing_qing_xue rec_yin_ying_bi_shou rec_yin_ying_mian_jin rec_yin_ying_pi_yi rec_yin_ying_hu_tui rec_yin_ying_qing_xue rec_xing_zhe_quan_tao rec_xing_zhe_shu_fa_dai
rec_xing_zhe_wu_dou_pao rec_xing_zhe_hu_tui rec_xing_zhe_bu_xue rec_shi_quan_quan_tao rec_shi_quan_shu_fa_dai rec_shi_quan_wu_dou_pao rec_shi_quan_hu_tui rec_shi_quan_bu_xue
rec_bi_chui_quan_tao rec_bi_chui_shu_fa_dai rec_bi_chui_wu_dou_pao rec_bi_chui_hu_tui rec_bi_chui_bu_xue rec_hu_lin_bai_lu_xiong_jia rec_hu_lin_bai_lu_hu_tui rec_hu_lin_bai_lu_zhi_xue
rec_du_kou_chen_xi_xiong_jia rec_du_kou_chen_xi_hu_tui rec_du_kou_chen_xi_zhi_xue rec_xun_lin_yue_yu_xiong_jia rec_xun_lin_yue_yu_hu_tui rec_xun_lin_yue_yu_zhi_xue rec_shuang_lie_long_ji_xiong_jia rec_shuang_lie_long_ji_hu_tui
rec_shuang_lie_long_ji_zhi_xue rec_long_yi_feng_yi_xiong_jia rec_long_yi_feng_yi_hu_tui rec_long_yi_feng_yi_zhi_xue rec_lie_feng_pi_feng rec_lie_feng_hu_tui rec_lie_feng_zhi_xue rec_chen_lu_jie_zhi
rec_chen_lu_xiang_lian rec_lie_hu_dou_mao rec_lie_hu_jia_ke rec_lie_hu_chang_xue rec_xiang_mu_fu_ji rec_bai_lu_hu_fu rec_chun_cao_shou_huan rec_ye_ying_xiong_zhen
rec_chao_xi_zhi_huan rec_chao_xi_diao_zhui rec_mao_lian_hu_wan rec_chuan_zhang_de_wang_yuan_jing rec_hai_dao_yan_zhao rec_hang_hai_dou_peng rec_shen_yuan_zhi_mao rec_deng_ta_zhi_guang
rec_shui_shou_jie_jie_zhi rec_chao_xi_zhi_xue rec_tie_gang_hui_zhang rec_chen_xi_zhi_jie rec_rong_yan_hu_shou rec_rong_yan_hu_tui rec_rong_yan_zhi_xue rec_yue_ying_dou_peng
rec_xing_hui_jie_zhi rec_xing_hui_diao_zhui rec_fei_cui_zhi_xin rec_fei_cui_hu_fu rec_ji_feng_hu_shou rec_ji_feng_zhi_xue rec_yue_yu_zhi_jie rec_jing_ling_pi_feng
rec_shuang_jiao_zhan_huan rec_shuang_jiao_diao_zhui rec_shuang_jiao_pi_feng rec_han_shuang_zhi_jie rec_bei_feng_hu_fu rec_long_lin_shou_huan rec_long_ji_hui_ji rec_lie_shou_dou_peng
rec_lie_shou_zhi_xue rec_tie_bi_hu_fu rec_xing_huo_jie_zhi rec_cang_lang_zhi_zhua rec_feng_bao_zhi_yan rec_feng_bao_diao_zhui rec_cang_qiong_zhi_yi rec_cang_qiong_zhi_xue
rec_long_yi_hu_fu rec_long_yi_jie_zhi rec_tian_qiong_zhi_guan rec_xing_guang_xiang_lian rec_feng_shen_zhi_huan rec_lei_guang_hui_zhang rec_mi_yin_shou_zhuo rec_shou_wang_zhe_hu_fu
rec_lv_ren_zhi_dun rec_xing_huo_fa_zhang rec_xue_tu_zhi_xue_ren rec_lie_ying_zhi_ya rec_cui_feng_zhi_gong rec_mi_wu_hu_tui rec_tie_bi_xiong_jia rec_tie_gang_zhan_ren
rec_lei_ting_zhi_huan rec_zhu_feng_chang_gong rec_mi_guang_diao_zhui rec_tie_gang_yuan_dun rec_shuang_yu_fa_zhang rec_shi_xin_quan_tao rec_mi_fa_dian_ji_zhi_zhang rec_xue_chao_duan_ren
rec_zhu_huo_tou_kui rec_sui_bing_chang_gong rec_ye_xiao_shuang_bi rec_sheng_guang_zhu_fu_zhi_huan rec_sheng_guang_bi_hu_zhi_dun rec_sheng_guang_xun_li_zhan_xue rec_sheng_guang_zhi_wo rec_sheng_guang_shao_bing_tou_kui
rec_sheng_guang_shen_pan_zhi_ren rec_sheng_guang_zhui_lie_chang_gong rec_sheng_guang_yuan_zheng_hu_tui rec_sheng_guang_qi_dao_fa_zhang rec_yue_yu_feng_xing_zhe_zhi_xue rec_sheng_guang_xun_dao_zhe_xiong_jia rec_yue_yu_ying_xi_xiong_jia rec_hui_jin_quan_tao
rec_tie_bi_zhong_zhuang_zhan_xue rec_yue_yu_ci_ke_bi_shou rec_yue_yu_ye_xiao_tou_kui rec_yue_yu_yue_ying_hu_tui rec_yue_yu_yue_hua_zhi_jie rec_xue_hen_shuang_ci rec_tie_bi_zhan_jia rec_tie_bi_wei_shu_tou_kui
rec_tie_bi_bi_lei_zhi_dun rec_tie_bi_jun_tuan_tui_jia rec_yue_yu_yin_yue_chang_gong rec_yue_yu_mi_yi_fa_zhang rec_yue_yu_hui_yue_xiang_lian rec_tie_bi_jun_tuan_jian rec_shuang_lang_xue_xue rec_hai_shen_bo_wen_jia
rec_shuang_lang_zhan_ren rec_yan_quan_lie_ji rec_xing_hui_fa_zhang rec_hai_shen_zhi_dun rec_hai_shen_zhen_zhu_lian rec_shuang_lang_tui_jia rec_shuang_yu_chang_gong rec_shuang_lang_lie_gong
rec_xing_hui_fa_guan rec_shuang_lang_bing_jia rec_xing_hui_chang_pao rec_po_yue_ju_jian rec_sui_yue_quan rec_lie_yu_chang_gong rec_shi_long_quan_tao rec_you_ying_duan_ren
rec_xing_chen_zhi_xue rec_jing_lei_zhan_gong rec_sheng_hui_fa_yi rec_huan_ying_chang_gong rec_cang_qiong_hu_jia rec_han_yue_quan_tao rec_cui_du_han_ren rec_lie_kong_zhan_gong
rec_sheng_yu_quan_zhang rec_da_xian_zhe_hu_tui
"""
_ORDER_CRAFT_RECIPE_ALIASES = """
rec_tie_jian rec_xue_tu_fa_zhang rec_lie_gong
"""
_ORDER_ALCHEMY_RECIPES = """
al_zhi_liao_yao_shui al_mo_li_yao_shui al_qiang_hua_shi al_hui_cheng_juan_zhou al_qiang_xiao_zhi_liao al_qiang_xiao_mo_li al_xing_yun_hu_fu al_jing_lian_qiang_hua_shi
al_zhu_fu_fu_shi al_gao_ji_qiang_hua_shi al_purify_jing_xu_cao al_purify_hai_zao al_purify_zhen_zhu_bei al_purify_lang_pi al_purify_yue_lang_mao_pi al_purify_xue_lang_pi
al_gong_ji_yao_shui al_fang_yu_yao_shui al_chao_ji_zhi_liao_yao_shui al_chao_ji_mo_li_yao_shui al_su_du_yao_shui al_bao_ji_yao_shui al_jiao_ren_zhi_lei al_long_xian_yao_ji
al_yue_lu_jing_hua al_shen_yuan_yao_ji al_xing_tie_qiang_hua_ji al_zhen_zhu_ming_mu al_shen_yuan_hui_xiang al_cai_hong_yao_ji al_lei_jing_yao_ji al_long_gu_yao_ji
al_ying_guang_yu_er al_jin_he_qiang_hua al_long_gong_jing_lian al_feng_bao_lei_yao al_yun_nu_bao_ji al_long_lin_tie_bi al_ji_qi_shen_yuan al_shi_lu_qiang_hua
al_shi_lian_ji_feng al_lan_ge_ming_mu al_hei_yuan_fu_wen_xiang al_long_gong_fu_wen_xiang al_yue_guang_an_shen_ji al_bai_shi_sheng_hui_yao_ji al_wei_xiao_zhi_liao al_qing_xiao_zhi_liao
al_quan_xiao_yao_shui al_ao_shu_yao_ji al_man_li_yao_ji al_feng_ling_yao_ji al_xue_tu_he_ji al_long_xue_yao_shui al_zhi_yu_juan_zhou al_po_jia_yao_ji
al_yan_bi_yao_ji al_chuan_jia_yao_ji al_rui_mu_yao_ji al_xun_jie_yao_ji al_jing_ji_yao_ji al_mao_xian_zhe_he_ji al_gao_ji_quan_xiao al_sheng_guang_yao_shui
al_kuang_bao_yao_ji al_zhan_hou_yao_ji al_shi_xue_yao_ji al_xing_yun_yao_ji al_kuang_nu_yao_ji al_zhi_ming_yao_ji al_yan_dun_yao_ji al_ying_bu_yao_ji
al_zhan_dou_he_ji al_man_xue_lie_jiu al_chao_ji_quan_xiao al_sheng_hui_zhi_liao al_sheng_dun_yao_ji al_bu_dong_yao_ji al_kuang_zhan_shi_yao_ji al_xing_huo_yao_ji
al_mi_fa_yao_ji al_po_fa_yao_ji al_long_li_yao_ji al_sheng_xian_yao_ji al_yuan_zheng_he_ji al_shen_yu_yao_shui al_zhan_shen_yao_ji al_si_shen_yao_ji
al_xu_kong_yao_ji al_zhan_sheng_yao_ji al_sheng_xian_da_yao
"""
_ORDER_COOKING_RECIPES = """
cook_slime_jelly cook_skewer cook_gold_feast cook_snake_soup cook_wolf_jerky cook_eagle_egg cook_ash_pancake cook_sacred_bread
cook_deer_cheese cook_pirate_stew cook_moon_cake cook_seafood_chowder cook_snowwolf_steak cook_royal_roast cook_royal_soup cook_dragon_egg_pancake
cook_night_mushroom_soup cook_moon_tea cook_aurora_honey cook_dragon_blood_hotpot cook_thunder_skewer cook_storm_chowder cook_glow_shark_soup cook_dough_bait
cook_blood_bait cook_v117_dragon_relic_pancake cook_v117_storm_eye_chowder cook_v117_permafrost_steak cook_v117_helga_royal_roast cook_v117_ghost_ship_stew cook_v117_dwarf_stone_ale cook_v117_ember_ash_pancake
cook_xiang_cao_kao_shou_rou cook_jin_guo_ye_zhu_pai_pai cook_yin_ling_li_er cook_tie_lu_mian_bao cook_cao_yao_cha cook_feng_mi_bing cook_shu_mi_tang cook_ye_feng_mi
cook_yang_mai_zhou cook_yin_yue_guo_dong cook_jing_ling_guo_jiang cook_feng_mi_cha cook_yue_gui_cha cook_jin_bo_tian_dian cook_xun_lu_gan cook_kao_niao_rou
cook_yan_ju_kao_yu cook_rong_yan_dan cook_kuang_gong_dun_rou cook_mo_gu_tang cook_jin_huo_la_jiao cook_bing_shuang_jiang_guo cook_zhang_yu_shao cook_hua_mi_jiu
cook_wu_gang_ka_fei cook_sheng_tang_jing_shui cook_xing_jun_liang
"""
_ORDER_FISHING_SPOTS = """
oak_plain starlake harbor_docks silver_river misty_swamp frost_horn mist_trench whale_domain
storm_sea deep_lake rainbow_cloud
"""
_ORDER_SHOP_WEAPONS = """
oak_town maple_village white_deer ironharbor silver_brook dawn_city ironshield_town jade_port
shell_town moon_gate star_song moon_court nameless_harbor pearl_city frost_horn anvil_fort
cold_ridge aurora_town deep_tunnel under_market dragon_pass dragon_kin ember_camp wind_city
"""
_ORDER_SHOP_EQUIP = """
oak_town white_deer ironharbor dawn_city jade_port ironshield_town
"""
_ORDER_SHOP_SMITH_MATERIALS = """
oak_town white_deer ironharbor ironshield_town dawn_city anvil_fort
"""
_ORDER_SHOP_SUBAREA_ITEMS = """
oak_town_5 oak_town_4 oak_town_3 white_deer_6 white_deer_5 white_deer_7 white_deer_8 white_deer_3
white_deer_4 ironharbor_5 ironharbor_6 ironharbor_8 ironharbor_4 ironharbor_9 ironharbor_10 silver_brook_3
silver_brook_4 silver_brook_2 maple_village_4 dawn_city_3 dawn_city_5 ironshield_town_3 ironshield_town_2 moon_gate_2
moon_gate_3 moon_court_3 star_song_2 star_song_3 frost_horn_3 frost_horn_5 anvil_fort_2 anvil_fort_3
cold_ridge_1 cold_ridge_2 cold_ridge_3 aurora_town_4 dragon_pass_2 dragon_kin_3 jade_port_2 jade_port_3
shell_town_1 shell_town_2 shell_town_3 nameless_harbor_2 nameless_harbor_3 pearl_city_2 pearl_city_3 pearl_city_4
pearl_city_5 deep_tunnel_2 deep_tunnel_3 under_market_1 under_market_2 under_market_3 ember_camp_2 ember_camp_1
ember_camp_4 wind_city_2
"""
_ORDER_SUBAREA_KIND = """
anvil_fort_2 anvil_fort_3 aurora_town_4 black_forest_4 cold_ridge_1 cold_ridge_2 cold_ridge_3 dawn_city_3
dawn_city_5 deep_tunnel_2 deep_tunnel_3 dragon_kin_3 dragon_pass_2 dwarf_long_gallery_5 ember_camp_1 ember_camp_2
ember_camp_4 frost_horn_3 frost_horn_5 harbor_docks_1 ironharbor_4 ironharbor_5 ironharbor_6 ironharbor_8
ironharbor_9 ironharbor_10 ironshield_town_2 ironshield_town_3 jade_port_2 jade_port_3 jade_port_dock maple_village_4
moon_court_3 moon_gate_2 moon_gate_3 nameless_harbor_2 nameless_harbor_3 oak_plain_5 oak_town_3 oak_town_4
oak_town_5 pearl_city_2 pearl_city_3 pearl_city_4 pearl_city_5 shell_town_1 shell_town_2 shell_town_3
silver_brook_2 silver_brook_3 silver_brook_4 star_song_2 star_song_3 under_market_1 under_market_2 under_market_3
under_market_mouth white_deer_3 white_deer_4 white_deer_5 white_deer_6 white_deer_7 white_deer_8 wind_city_2
"""
_ORDER_PET_POOL = """
pet_wolf pet_turtle pet_cat pet_rabbit pet_dove pet_fox pet_salamander pet_panther
pet_starswift pet_drake pet_bat pet_armadillo pet_thunderbird pet_griffin pet_starbutterfly pet_moonfox
"""
_ORDER_PET_EGG_ROLL = """
pet_wolf pet_salamander pet_fox pet_cat pet_panther pet_bat pet_armadillo pet_drake
pet_thunderbird pet_griffin
"""
# __B14D_ORDERS_END__


def _order_list(block: str) -> list:
    """顺序声明块 → 键列表（空白分隔；`#` 起头到行尾为注释）。"""
    out: list = []
    for line in (block or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.extend(line.split())
    return out


def _ordered(raw: dict, block: str, where: str) -> dict:
    """按声明序重排 `{键: 条目}`；域/声明键集不一致 → `raise`（静默漏条目的防线）。

    与 `content/catalog_items.py:_ordered` 同款（带重复键守卫与差集报错）。
    """
    keys = _order_list(block)
    if not keys:
        return dict(raw or {})
    if len(set(keys)) != len(keys):
        raise ValueError(f"catalog_life：{where} 的序声明有重复键 —— 拒绝静默取首个")
    if set(raw or {}) != set(keys):
        miss = sorted(set(raw or {}) - set(keys))
        extra = sorted(set(keys) - set(raw or {}))
        raise ValueError(
            f"catalog_life：{where} 域与序声明不一致（域多 {len(miss)} / 声明多 {len(extra)}）"
            f"—— 请重跑 overnight/_b14d_gen_orders.py 同步序声明。域多 {miss[:5]} … 声明多 {extra[:5]} …")
    return {k: raw[k] for k in keys}


# ============================================================
# ② 配置归口域 `game_config`（rules）—— 一个组 = 一个宿主源模块的常量组
# ============================================================
_GAME_CONFIG: dict = _read_domain("game_config", "rules", {}) or {}


def _cfg(group: str) -> dict:
    """取 `game_config` 的一个组（缺组 → 空 dict；键序原样，导出期未排序）。"""
    g = _GAME_CONFIG.get(group)
    return dict(g) if isinstance(g, dict) else {}


# ---- econ_config 组（真源 game/data/econ_config.py）----
ECON_CONFIG: dict = _cfg("econ_config").get("ECON_CONFIG") or {}

# ---- prof_config 组（真源 game/data/prof_config.py，15 个常量）----
_PROF: dict = _cfg("prof_config")
PROF_TUTORS: dict = _tupled(_PROF.get("PROF_TUTORS"))              # {副业: (导师, 城市)}
PROF_WAIT_BASE: dict = _tupled(_PROF.get("PROF_WAIT_BASE"))        # {副业: (低秒, 高秒, 名)}
DAILY_PROF_TASKS: dict = _tupled(_PROF.get("DAILY_PROF_TASKS"))    # {副业: (任务名, 次数, 金币)}
BAG_FILTER_TYPES: list = list(_PROF.get("BAG_FILTER_TYPES") or [])
PROF_STAMINA_COST: dict = dict(_PROF.get("PROF_STAMINA_COST") or {})
PROF_WAIT_DECAY: float = _PROF.get("PROF_WAIT_DECAY", 0.0)
PROF_WAIT_FLOOR: int = _PROF.get("PROF_WAIT_FLOOR", 0)
MINING_KEYWORDS: list = list(_PROF.get("MINING_KEYWORDS") or [])
PAWN_RATES: dict = dict(_PROF.get("PAWN_RATES") or {})
ENCHANT_SLOT_UNLOCK: dict = dict(_PROF.get("ENCHANT_SLOT_UNLOCK") or {})
RUNE_LEVEL_GATE: dict = _int_keys(_PROF.get("RUNE_LEVEL_GATE"))     # {符文等级: 附魔副业等级}
DAILY_PROF_EXP: int = _PROF.get("DAILY_PROF_EXP", 0)
RARE_MATERIAL_PRICE: int = _PROF.get("RARE_MATERIAL_PRICE", 0)
# （同组的 PRICE_BAND / GATHER_MAP_MIN_LV 属函数侧常量，E 单元与 `content/profession.py` 各自消费）

# ---- housing 组（真源 game/data/housing.py）----
_HOUSING: dict = _cfg("housing")
PROPERTIES: dict = dict(_HOUSING.get("PROPERTIES") or {})
HOUSE_LEVELS: dict = {k: dict(v) for k, v in _int_keys(_HOUSING.get("HOUSE_LEVELS")).items()}
HOUSE_MAX_LEVEL: int = _HOUSING.get("HOUSE_MAX_LEVEL", 0)
HOUSE_REFUND: dict = _int_keys(_HOUSING.get("HOUSE_REFUND"))

# ---- gather 组（真源 game/data/gather.py；采集/挖掘点池在 gather_pools/子域别处）----
_GATHER: dict = _cfg("gather")
CAMP_SPOTS: dict = dict(_GATHER.get("CAMP_SPOTS") or {})
MINE_SPOTS: dict = {k: dict(v) for k, v in (_GATHER.get("MINE_SPOTS") or {}).items()}

# ---- calamity 组（真源 game/data/calamity.py，v136 怪异炼成）----
_CALAMITY: dict = _cfg("calamity")
CALAMITY_MAX: int = _CALAMITY.get("CALAMITY_MAX", 0)
CALAMITY_COST: dict = dict(_CALAMITY.get("CALAMITY_COST") or {})
CALAMITY_STATS: list = list(_CALAMITY.get("CALAMITY_STATS") or [])
CALAMITY_BONUS: float = _CALAMITY.get("CALAMITY_BONUS", 0.0)
CALAMITY_MALUS: float = _CALAMITY.get("CALAMITY_MALUS", 0.0)
CALAMITY_POSITIVE_CHANCE: float = _CALAMITY.get("CALAMITY_POSITIVE_CHANCE", 0.0)

# ---- mounts 组（真源 game/data/mounts.py；`MOUNT_BY_KEY` 是派生索引）----
MOUNT_POOL: list = list(_cfg("mounts").get("MOUNT_POOL") or [])
# 真源 `mounts.py:70 MOUNT_BY_KEY = {m["key"]: m for m in MOUNT_POOL}` —— 键序 = MOUNT_POOL 序
MOUNT_BY_KEY: dict = {m["key"]: m for m in MOUNT_POOL}


# ============================================================
# ③ 副业配方域 `craft` / `alchemy` / `cooking`（data）
# ============================================================
_CRAFT: dict = _read_domain("craft", "data", {}) or {}

# 配方条目剥掉导出期注入的 `aliases`（= 真源 CRAFT_RECIPE_ALIASES 折进条目）
_CRAFT_STRIPPED: dict = {
    rid: {k: v for k, v in ent.items() if k != "aliases"}
    for rid, ent in _CRAFT.items()
}
CRAFT_RECIPES: dict = _ordered(_CRAFT_STRIPPED, _ORDER_CRAFT_RECIPES, "craft 配方")

# 别名表：真源 `CRAFT_RECIPE_ALIASES`={配方 id: [名字…]}，导出期折进条目 `aliases`
CRAFT_RECIPE_ALIASES: dict = _ordered(
    {rid: list(ent["aliases"]) for rid, ent in _CRAFT.items() if ent.get("aliases")},
    _ORDER_CRAFT_RECIPE_ALIASES, "craft 配方别名")

ALCHEMY_RECIPES: dict = _ordered(
    {k: dict(v) for k, v in (_read_domain("alchemy", "data", {}) or {}).items()},
    _ORDER_ALCHEMY_RECIPES, "alchemy 配方")
COOKING_RECIPES: dict = _ordered(
    {k: dict(v) for k, v in (_read_domain("cooking", "data", {}) or {}).items()},
    _ORDER_COOKING_RECIPES, "cooking 配方")


# ============================================================
# ④ 垂钓域 `fishing_spots` / `fishing_pool`（data）
# ============================================================
FISHING_SPOTS: dict = _ordered(
    {k: dict(v) for k, v in (_read_domain("fishing_spots", "data", {}) or {}).items()},
    _ORDER_FISHING_SPOTS, "fishing_spots")

# 渔获池 = 源 list 的等价物：域 = {鱼名: 条目 + seq}，按 `seq` 还原成 list 并剥掉 `seq`
# （源 `FISH_POOL` 是 list、插入序参与 `random.choices` 抽样 → 必须保序；域里已有 `seq`，不需要序声明）
FISH_POOL: list = [
    {k: v for k, v in ent.items() if k != "seq"}
    for ent in sorted((_read_domain("fishing_pool", "data", {}) or {}).values(),
                      key=lambda x: x["seq"])
]


# ============================================================
# ⑤ 商店域 `shop`（data）—— 89 条「六张源表并集」合表，按列拆回各表
#    ⚠ 合表里五列是**五张源表**，各有各的插入序 → 每列一个序声明
# ============================================================
_SHOP: dict = _read_domain("shop", "data", {}) or {}

SHOP_WEAPONS: dict = _ordered(_pick(_SHOP, "weapons"), _ORDER_SHOP_WEAPONS,
                              "shop.weapons")               # 真源 game/data/shop.py:83
SHOP_EQUIP: dict = _ordered(_pick(_SHOP, "equip"), _ORDER_SHOP_EQUIP,
                            "shop.equip")                   # 真源 game/data/shop.py:293
SHOP_SMITH_MATERIALS: dict = _ordered(_pick(_SHOP, "materials"), _ORDER_SHOP_SMITH_MATERIALS,
                                      "shop.materials")     # 真源 game/data/shop.py:232
# 子区域配货：合表里唯一非店铺条目是保留键 `wild_trade`（行商货单），要从本表排除
SHOP_SUBAREA_ITEMS: dict = _ordered(
    {k: v["items"] for k, v in _SHOP.items() if "items" in v and k != "wild_trade"},
    _ORDER_SHOP_SUBAREA_ITEMS, "shop.items")                # 真源 shop.py:22
SHOP_WILD_TRADE: list = list((_SHOP.get("wild_trade") or {}).get("items") or [])  # 真源 shop.py:13
# 设施类别表（真源 game/data/shop.py:417）
SUBAREA_KIND: dict = _ordered(_pick(_SHOP, "kind"), _ORDER_SUBAREA_KIND, "shop.kind")


# ============================================================
# ⑥ 宠物域 `pets`（data）—— 一条 = 一个品种，规则行挂在条目 `egg_roll`
# ============================================================
_PETS: dict = _read_domain("pets", "data", {}) or {}
# 品种池：剥掉导出期注入的 `egg_roll`（= 该品种的掷蛋规则行）
_PET_POOL_BY_KEY: dict = _ordered(
    {k: {kk: vv for kk, vv in ent.items() if kk != "egg_roll"} for k, ent in _PETS.items()},
    _ORDER_PET_POOL, "pets 品种")
PET_POOL: list = list(_PET_POOL_BY_KEY.values())
# 掷蛋规则表：源 `PET_EGG_ROLL` 是 list，导出期按 `key` 连接进品种条目 → 这里按键取回（序由声明给出）
PET_EGG_ROLL: list = list(_ordered(
    {k: dict(ent["egg_roll"]) for k, ent in _PETS.items() if ent.get("egg_roll")},
    _ORDER_PET_EGG_ROLL, "pets 掷蛋规则").values())


# ============================================================
# ⑦ 缺域检出 —— 「静默变空洞」比报错难查得多（同 tables.py:missing_domains 口径）
# ============================================================
REQUIRED_DOMAINS = ("game_config", "craft", "alchemy", "cooking",
                    "fishing_spots", "fishing_pool", "shop", "pets")


def missing_domains() -> list:
    """缺哪张源域（文件不在 / 坏 JSON / 空表）→ 域名清单（空 = 全在）。"""
    return [d for d in REQUIRED_DOMAINS
            if not _read_domain(d, "rules" if d == "game_config" else "data", {})]


# 本模块**不做**的名字（无域可依，禁编数据；详见报告「缺口」表）：
#   PET_MAX_LEVEL · PET_SKILL_UNLOCK_LV · FISH_COLLECT · FISH_EXP · FACTIONS · FACTION_ORDER ·
#   REPUTATION_TIERS · AREA_FACTION · CHRONICLES · HONOR_SHOP · GUILD_CONFIG
__all__ = [
    "ECON_CONFIG", "PROF_TUTORS", "PROF_WAIT_BASE", "DAILY_PROF_TASKS", "BAG_FILTER_TYPES",
    "PROF_STAMINA_COST", "PROF_WAIT_DECAY", "PROF_WAIT_FLOOR", "MINING_KEYWORDS", "PAWN_RATES",
    "ENCHANT_SLOT_UNLOCK", "RUNE_LEVEL_GATE", "DAILY_PROF_EXP", "RARE_MATERIAL_PRICE",
    "PROPERTIES", "HOUSE_LEVELS", "HOUSE_MAX_LEVEL", "HOUSE_REFUND",
    "CAMP_SPOTS", "MINE_SPOTS",
    "CALAMITY_MAX", "CALAMITY_COST", "CALAMITY_STATS", "CALAMITY_BONUS", "CALAMITY_MALUS",
    "CALAMITY_POSITIVE_CHANCE",
    "MOUNT_POOL", "MOUNT_BY_KEY",
    "CRAFT_RECIPES", "CRAFT_RECIPE_ALIASES", "ALCHEMY_RECIPES", "COOKING_RECIPES",
    "FISHING_SPOTS", "FISH_POOL",
    "SHOP_WEAPONS", "SHOP_EQUIP", "SHOP_SMITH_MATERIALS", "SHOP_SUBAREA_ITEMS",
    "SHOP_WILD_TRADE", "SUBAREA_KIND",
    "PET_POOL", "PET_EGG_ROLL",
    "REQUIRED_DOMAINS", "missing_domains",
]
