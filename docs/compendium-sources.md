# 规则资料来源、版本与许可

本资料库固定使用 **2014 规则 / SRD 5.1**。数据完整收录与规则自动化是两个不同的覆盖范围：能够查看某项法术或职业特性，不表示服务器已经实现其所有效果。法术和特性详情的 `automation_status`、`automation_reason` 由当前实际注册的规则处理器提供，未实现内容明确标为 `reference`。

## 可复现的上游快照

| 项目 | 固定值 |
|---|---|
| 上游项目 | [5e-bits/5e-database](https://github.com/5e-bits/5e-database) |
| Commit | [`a6212beb4b278917c2cff41c2b04c4ef4f3e0d6f`](https://github.com/5e-bits/5e-database/tree/a6212beb4b278917c2cff41c2b04c4ef4f3e0d6f) |
| 上游提交时间 | 2026-10-02T21:40:55Z |
| 选用目录 | [`src/2014/en`](https://github.com/5e-bits/5e-database/tree/a6212beb4b278917c2cff41c2b04c4ef4f3e0d6f/src/2014/en) |
| 本地目录 | `backend/data/srd2014/` |
| 获取日期 | 2026-10-23 |
| 完整性清单 | `backend/data/source-manifest.json`，逐文件原始 URL、SHA-256、字节数与条目数 |

共保存 **25 个 JSON 文件、2,317 条记录、3,876,974 字节**。本地原始 JSON 与上游固定 commit 的下载内容逐字节一致，没有缩短描述、删除高等级内容或只保存示例。运行时从仓库中的本地文件读取，不访问在线 API，也不依赖上游服务可用性。没有下载或混入上游 `2024` 目录。

主要表规模：

| 内容 | 条目数 |
|---|---:|
| 核心职业 | 12 |
| 职业等级表 | 240（每职业 1–20 级） |
| 子职业等级记录 | 50（按各自实际获得特性的等级） |
| SRD 子职业 | 12 |
| 属性技能 | 18 |
| 法术 | 319 |
| 职业／子职业特性及选择项 | 407 |
| 怪物 | 334 |
| 装备 | 237 |
| 魔法物品 | 362 |

其余原始表也一并保存：属性、阵营、背景、状态、伤害类型、装备分类、专长、语言、魔法学派、熟练项、种族、亚种、种族特性、武器属性、规则分类与规则正文。**SRD 并不等于完整商业出版物**：例如此版本每职业提供一个开放子职业，背景与专长范围有限；不包含未授权的商业扩展内容。

## 许可核验与归属声明

结构化上游项目的 [LICENSE.md](https://github.com/5e-bits/5e-database/blob/a6212beb4b278917c2cff41c2b04c4ef4f3e0d6f/LICENSE.md) 为 MIT。其完整许可正文与版权声明原样保存于 [`backend/data/5e-database-LICENSE.md`](../backend/data/5e-database-LICENSE.md)：Copyright (c) [2018-2020] [Adrian Padua, Christopher Ward]。分发这些数据时需保留该文件。

上游 README 仍提及 OGL 1.0a。本项目对 underlying SRD 5.1 规则文本使用其另行开放的 **CC BY 4.0** 许可，而不是将上游 MIT 许可误认为涵盖所有原始规则文本。许可依据是 [官方 SRD 页面](https://www.dndbeyond.com/srd) 与 [SRD 5.1 CC PDF 第 1 页](https://media.wizards.com/2023/downloads/dnd/SRD_CC_v5.1.pdf#page=1)。官方页面明确区分 SRD 5.1 与后续规则版本；本项目没有借用 SRD 5.2 的新增内容来补充 2014 数据。

供根目录 `NOTICE.md` 合并的必要声明：

> This work includes material taken from the System Reference Document 5.1 (“SRD 5.1”) by Wizards of the Coast LLC and available at https://dnd.wizards.com/resources/systems-reference-document. The SRD 5.1 is licensed under the Creative Commons Attribution 4.0 International License available at https://creativecommons.org/licenses/by/4.0/legalcode.

> Structured data is adapted from 5e-bits/5e-database, commit a6212beb4b278917c2cff41c2b04c4ef4f3e0d6f, under the MIT License. Copyright (c) [2018-2020] [Adrian Padua, Christopher Ward]. The complete upstream MIT license is included at backend/data/5e-database-LICENSE.md. HexBound adds Chinese display labels, local indexes, explicit correction overlays, and automation metadata; these additions do not alter the licenses applicable to the underlying material.

## 本项目适配及可追溯修正

原始 JSON 不做修改。`backend/compendium.py` 在运行时增加 `id`、`display_name`、`edition`、`srd_version`；为 12 职业、18 技能、12 子职业及 138 个常用法术增加中文显示名称。中文名称是本项目界面标签，不宣称是官方中文 SRD；未建立译名的条目保留英文原名和完整英文规则。没有截短英文描述或以生成文本替代原文。

法术原始 `damage` 在本快照中为数组；所有伤害分项、升环表、豁免、射程、施法时间、材料、持续时间、专注、仪式、职业列表与描述原样保留。原始条目没有 `higher_level` 时，运行时视图补空数组，表示没有单独的升环说明；不凭空推断额外效果。

经官方原文复核的修正单独保存在 [`backend/data/errata-overlay.json`](../backend/data/errata-overlay.json)：

- **生命领域 7 级法术**：上游 `life.spells` 遗漏 `guardian-of-faith`。官方 SRD 5.1 第 17 页的 Life Domain Spells 表包含 `death ward` 与 `guardian of faith` 两项。运行时追加缺失引用，并记录 `source_corrections`；原始快照仍保留上游原样，便于对比。
- **升级经验表**：`XP_THRESHOLDS` 逐项依据官方 SRD 5.1 第 56 页 Character Advancement 表录入，采用级别 1–20 作为字典键。此表未出现在本次上游 Rule Sections JSON 中，因此明确记录独立出处。

上游是社区转录而非无误保证。已发现的问题只做有来源的显式修正，不静默修改原始文件。新增修正必须附来源页码及测试。

## 稳定的程序接口

```python
from backend.compendium import (
    CLASSES, CLASS_LEVELS, SUBCLASS_LEVELS, SKILLS, SPELLS,
    FEATURES, SUBCLASSES, CLASS_CASTING_ABILITIES, XP_THRESHOLDS,
    get_catalog, lookup, class_level, verify_source_integrity,
)

wizard_level_5 = class_level("wizard", 5)
spell = lookup("spells", "fireball")  # 完整来源字段 + 实际自动化标记
result = get_catalog("spells", class_id="wizard", level=3, limit=100)
assert verify_source_integrity() == []
```

`CLASS_LEVELS[class_id][level]` 包含每个职业的 20 条完整记录；`SUBCLASS_LEVELS[subclass_id][level]` 只包含上游实际存在的子职业获得等级。原字段 `ability_score_bonuses` 是累计次数，不能直接当作当级新获得的属性点。

常量字典供规则模块只读使用。`lookup()`、`class_level()`、`get_catalog()` 返回深拷贝，调用方修改返回值不会改变规则档案。目录搜索支持中文／英文名称、ID、正文、职业、准确等级和魔法学派；结果记录不截断，分页最多 500 项。
