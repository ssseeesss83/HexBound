# P02 结构化资料核验台账

规则范围：2014 / SRD 5.1；官方原文哈希见 `backend/data/official/manifest.json`。状态是逐字段核验结果，不代表角色构筑或规则执行已经完成。生产候选仍未签收或激活。

## 已核对字段

- 12 职业生命骰、24 个豁免熟练引用、12 个标准技能选择数量及 95 条允许技能引用，逐名称对照一致。8 个施法职业的施法属性一致。
- 12 职业的 1–20 级熟练加值；7 个常规施法职业的 140 行戏法 / 已知数量及法术位；邪术师 20 行戏法、已知、契约位环级与数量。此前发现的祈唤、超魔、荒野形态和属性提升次数差异已单独勘误。
- 12 子职业归属；生命领域 10 条、大地结社七地形 56 条、奉献之誓 10 条、邪魔宗主 10 条法术关系。生命领域旧勘误保留；邪魔表按环级映射为职业等级 1/3/5/7/9，不能当作自动习得。
- 319 法术的头部参数已对照独立官方提取块，头部中的反应条件、范围、材料与持续时间差异已规范修正。5 项法术基础职业归属差异已修正。法术正文、伤害、豁免、目标及升环关系的全字段核验仍未完成。
- 317 个官方基础怪物的 AC 各配置、HP、生命骰、六属性和 XP 已对照；已确认差异在规范覆盖层修正。334 个候选怪物条目中还包含形态和扩展组合，不能把数量视作 334 个独立官方怪物。

## 职业起始选择复审

| 职业 | 官方页 | 修正 |
|---|---:|---|
| Paladin | 30 | 任意简易武器收窄为任意简易近战武器；同步修正嵌套选择器与描述 |
| Rogue | 39 | 短弓与 20 箭的组合补齐 1 个箭袋 |
| Monk | 26、70 | 工匠工具熟练分支移除伪装工具与文书伪造工具，保留 17 种工匠工具 |

以上为对照 39 个起始选择组及 18 个固定装备项后发现的差异。装备包内部内容、价格 / 重量、两个同型武器的选择语义及实际建角执行仍待核验。德鲁伊木盾与不穿戴金属护甲 / 使用金属盾的约束有完整官方原文，但未完整结构化或接入装备资格判定。

## 仍待逐项核验

- 完整施法准备、法术学习与子职业授予模式，大地地形选择的前提和互斥。
- 特性的全部资源、恢复时点、前置选择与依赖；段落存在性比对不等于所有参数已核验。
- 怪物传奇动作预算、重置 / 失能 / 惊讶限制、反应窗口、多段伤害的延迟、变形共享资源与动作权限。Night Hag 的额外物品段落来源待厘清。
- 所有装备与物品字段、范围规则，以及原型处理器对完整规则的覆盖。

历史快照独立冻结；上述修正只更新候选资料。`transcription-signoff.json` 不存在，不能由导入者重算摘要自行绕过签收。

## 后续职业语义复审

进一步修正 10 项规范来源字段，采集工具可离线复现：法师补齐第 53 页升级学习原文，以及第 54–55 页抄录 / 备份 / 遗失恢复的完整侧栏和关键时间金钱参数；恢复 Life 介绍中的官方神祇举例；恢复德鲁伊焦点的官方引用；伪装及文书伪造工具熟练改为 Other，避免分类查询重新混入工匠工具。

四个子职业显式保存法术授予模式：Life / Devotion 始终准备，Land 随地形始终准备，Fiend 扩展可选列表。Fiend 的第 50 页解释原文单独保留。此改动是资料语义修正，不代表历史人物原型已正确执行授予模式。

已知结构缺口仍包括：Land 的 3/5/7/9 级 Circle Spells 授予与首次地形选择不可达；原始地形别名标为 2 级，不能据此提前要求玩家选择。Favored Enemy 的选项把“两种类人生物种族”写成单个 humanoids 类型，尚需改成互斥选择结构，并绑定所选敌人的语言资格。上述缺口未解除前，不签收完整构筑关系。

## Land 与宿敌关系修正

以上两项的资料关系现已修正，人物实际选择与执行仍归 P09：

- 依据第 21–22 页补入四条规范化 Land 授予记录，分别对应 3/5/7/9 级的 Circle Spells。3 级绑定首次且仅一次的七选一地形选择，后续沿用已选地形。
- 地形父项与七个子项显式标记派生选择别名，规范选择等级为 3；原始 `level=2` 保留为 archive_level，原始文件不变。别名不额外授予机械收益。
- 规范候选记录数变为 **2,321**，比原始 2,317 多四条有官方来源的授予记录；历史包仍固定为 2,317。安装校验按各自版本的库存核对，不用新库存否定旧快照。
- 407 项特性均能从等级授予和显式选择图达到；新增可达性、授予职业 / 子职业 / 等级以及嵌套等级引用检查。可达不代表完整执行。
- 宿敌的非类人生物类型与“两种不同类人生物种族”分为互斥选择；后者要求世界种族目录，语言资格绑定实际宿敌。由于完整选择执行仍未接入，继续标记 reference，禁止据 `humanoids` 一词获得对全部类人生物的收益。

## 法术数值复审与首批修正

已按官方页码修复五张逐环表：Disintegrate 135–136、Freezing Sphere 147–148、Phantasmal Killer 167、Wall of Fire 190、Flame Blade 145。Sleep 第 180 页是生命值预算而非伤害，规范记录新增派生预算分类及完整升环表，damage 置空，原始归档和冻结历史包均不变。

Flame Blade / Scorching Ray 的近战 / 远程攻击类别补齐；Call Lightning、Flaming Sphere、Levitate、Spirit Guardians、Web、Zone of Truth 补入主豁免属性及成功结果。顶层摘要不表达条件性、重复触发、目标排除或持续限制。Web 脱离仍是 Strength check。Arcane Hand / Dispel Evil and Good 的攻击属于特定效果分支，不草率设整个法术为攻击。

另核对一致的范围：19 个简单逐环伤害表、9 个伤害戏法的 1/5/11/17 级骰表、6 个直接治疗升环表；53 项材料头中的金额及显式消耗词未丢失。只签这些字段，不据此签收完整法术。材料消耗不得统一为单个布尔值，Clone / Legend Lore 为部分消耗，Forbiddance 有正文条件。

明确待补效果分支：Acid Arrow 延迟伤害，Fire Shield 冷伤选项，Wall of Ice 寒气 CON / 5d6，Wall of Thorns 后续挥砍，Storm of Vengeance 后续轮次，Spirit Guardians 伤害类型与排除，Magic Missile 逐弹分配。Aid / False Life 不能按普通治疗解释。上述缺口继续阻止总签收。

## 六个复杂法术阶段资料

候选资料新增六项阶段引用，绑定官方法术块 SHA-256，原始 PDF / 抽取资料均不变。已核验数值及显式触发，未签运行时：Acid Arrow 命中与未命中及延迟；Fire Shield 暖 / 冷互斥与生物近战命中反伤；Wall of Ice 初始 DEX、破墙段、寒气 CON；Wall of Thorns 初始穿刺与后续挥砍；Storm 各轮不同对象 / 类型 / 豁免；Spirit Guardians 排除、速度、首次进入与自身回合开始。

明确不臆造：盾型切换原文规则未提供；冰墙原文十块面板能否减少未明确；风暴后续 on your turn 不固定为起止、第三轮物件未擅配 DEX、目标不足六个不擅裁；守护灵没有施法出现伤害，也没有全体友军自动免疫。Acid Arrow 延迟暴击、区域移动的进入事件等仍列 interpretation_pending。

## 319 法术正文比对

`official/spell-body-review.json` 固定本轮比对证据：280 项去排版后的字母数字流相同；39 项有差异，34 项已按完整官方法术块修复，共 41 个正文 / 升环字段。`tools/normalize_spell_bodies.py` 可重建覆盖层，原始归档和冻结历史包不变。

修复包括：Heroism 升环整段、Conjure Animals 九环四倍、Dominate Beast 目标及升环时长、Create or Destroy Water 灭火、Polymorph / True Polymorph 零 HP 限制、True Polymorph 直到驱散、Phantasmal Killer / Weird 自身回合结束触发、Find Familiar 的 attack modifier、Moonbeam 的 1d10 及 Spike Growth 的强制检定措辞。四个表格法术不从扁平提取结果重排。

Animal Friendship 第 115 页原始 PDF 自身存在 `additional beast t level` 缺字，保留审计阻塞，不从记忆修正文。正文相同不代表结构参数齐全；Weird 条件伤害、Phantasmal Killer 分阶段、Dominate Beast 目标过滤和时长表、Heroism 临时 HP / 升环目标仍待结构化与执行验证。

## 背景 / 种族 / 怪物来源补丁

`official/character-source-review.json` 保存运动技能 p79 完整段落、侍僧 p60–61 介绍与装备及矮人 p3 重甲速度例外。祈祷物和香支是无官方价重的叙事授予，不复用香块或普通书价重；法衣只复用身份引用，其社区零价重未获官方签收。

`official/monster-source-review.json` 保存七条带 expected 断言的修正和原段隔离凭据：鼠人鼠形 / 虎人虎形大小的命名兽形跨页来源、三种成年龙变形、巫妖 Disrupt Life 目标与成功减半及 Night Hag Items 非 SRD 段落。官方心石 / 灵魂袋动作前提保留。传奇动作预算与时机通则 p260 已收集，完整结构和实际执行仍待后续批次。

## Animal Friendship 缺字后续核对

原始 PDF 与初次审计均保留。2026-10-24 读取 [D&D Beyond 官方旧版条目](https://www.dndbeyond.com/spells/1993-animal-friendship)，其明确标注 Legacy、Basic Rules (2014), pg. 212，确认缺字处为 “beast for each slot level”。`official/animal-friendship-source-resolution.json` 固定同版证据、最小替换及原始法术块摘要；候选补入缺失升环段。此处仅修复 SRD 已选条目的文字，不扩大资料范围，不签收多目标魅惑执行。

## 职业成长与特性正文初审

`tools/audit_class_growth.py` 可复现 `official/class-growth-review.json`。固定官方 PDF / pages 摘要，2601 项数值零差异，覆盖240行熟练、160行施法表、240行ASI累计及现有职业成长字段；候选初始化将漂移或未审字段作为错误。显式公式是人工核对的来源转录，非从候选反推；grant_matrix 仅列证据，machine_approved_grant_rows 为0。

`official/feature-body-review.json` 记录407特性初审和完整局限。Holy Nimbus p33缺失长休恢复句已补；其余子串 / 段落匹配不能证明来源块无遗漏，不能据本次初审签收全部特性、前置或执行。

## 护甲 / 盾牌与穿脱时间来源

P02n逐行提取p63–64完整横表，13条117字段零差异，保留原始行和严格字段 / AC键集 / 库存比较。盾牌+2是加值；轻甲使用完整敏捷修正、包括负值，中甲仅上限+2不把负值归零，重甲不计敏捷；本批只核数据，不签处理器。

p64完整穿脱段及四类时间保存到现有护甲分类的timing_reference。协助只标doff减半，半动作计时未臆造，runtime_verified=false。原始及legacy不变，候选仍2,322条，资料总签收和启用门禁保留。来源比较可运行tools/audit_armor.py；保存的armor-source-review.json是补结构字段前快照。

## 普通装备剩余187条的测量字段

`tools/audit_equipment.py`从固定PDF的p69–72逐行提取161行数值；驴/骡共享行拆为两映射，治疗药水行显式映射既有魔法物品，12马铠按p71及已审护甲派生，另取7装备包标题价格、7仅在包正文提及的小物件，覆盖187条346字段。

候选修正铁蒺藜整包1gp/20枚、铁钉整包1gp/10枚、异种鞍40lb、铁环甲马铠120gp。不得将单枚价格搭配整包重量。箭矢等原有quantity也按来源包规格核对。水袋5lb为装满状态；破折号或仅有名称的条目标记not_stated，不宣称精确零重量/免费，当前社区零值仍不属于已签收测量值。

`official/equipment-measurements-review.json`保留修正前6字段差异；重跑当前候选346字段零差异。原始社区文件与冻结legacy均未修改。这是有限数值批次，未签收特殊规则正文、容积说明或装备包66内容关系，也没有启用候选资料包。

治疗药水依据p68普通恢复2d4+2及p234表，跨表目标限定Common变体并检查母项关系；不会为Varies母项及更高品级赋上50gp/½lb。历史报告仅修订此引用并附说明，预修测量差异保留。

`tools/audit_equipment_packs.py`独立消费p70七包清单全部短语，66关系及7库存检查零差异。`official/equipment-pack-contents-review.json`保存完整来源正文、每条短语及包装数量转换。未知短语或非整份直接拒绝，不能默默跳过。此证据只覆盖包内容资料，不签收角色授予及负重处理。

`tools/audit_equipment_bodies.py`比较102条已有规则正文与7包来源清单；修正圣徽三条附录措辞、补全七包desc。另保存三类一般规则引用、十三容器容量及背包附注，七件包内小物件明确为衍生caption并附原文。109正文与10引用当前零差异，历史正文快照保留预修差异。

来源未定义表内破折号为精确零重量，也未给七件包内小物件单独价重；43空缺维度要求null/缺字段。只清空未知维度，保留已知售价；`equipment-source-absence-review.json`保留先前占位零证据。运行时购买或负重不得把未知量默认为零，此批不提供相关执行器。候选尚未启用，raw及legacy不变。

## 魔法盾牌家族补录

官方p242的Shield,+1/+2/+3没有社区对应条目；按一个官方母项、三个规范派生变体补入候选。`tools/normalize_magic_shields.py`只写overlay，`tools/audit_magic_shields.py`校验完整字段、固定来源、母子关系及参考状态。稀有度分别Uncommon/Rare/Very Rare，holding时在普通盾牌AC加值之外额外增加，不套用Armor家族稀有度或wearing条件。

`official/magic-shields-review.json`记录当前零差异；candidate为2,326条（magic-items366），raw及legacy原样保留。此补录不签收魔法物品全集或装备AC执行。

`tools/audit_magic_inventory.py`先独立读取官方字体标题与14项明确处分，合并Detection and / Location跨行标题，核定240独立标题，再与候选母项映射；126规范变体须有唯一母项和完整引用。`official/magic-inventory-review.json`保留全部标题位置、处分理由及关系，当前零差异。目录验收不代替正文、稀有度或效果验收，嵌套统计卡仍须在所属条目中完整保存。

240魔法物品母项完整正文现由tools/extract_magic_bodies.py从固定PDF按官方标题坐标提取，magic-item-blocks.json保留原始分段、坐标与跨页正文。tools/audit_magic_bodies.py独立映射稳定ID，校验240正文及240完整source reference。46条候选正文改用官方完整文本，包含资料与Markdown格式差异，预修快照保留；符号比较保留倍乘、脚注标记及分数，不能以排版清洗丢失规则。Deck的Avatar of Death、Figurine的Giant Fly保留在条目中；Wings与Orb之间的sentient通则不混入正文。此批不签126变体、独立结构稀有度 / 类别字段、通则或机械执行。candidate 2,326、raw及legacy仍冻结。

母项header后续审计tools/audit_magic_headers.py覆盖240项720检查，独立解析完整跨行类型 / 稀有度 / 同调原句，保存reference_pending_execution证据。虫群法杖Rare、蟒蛇法杖Uncommon两处结构稀有度纠正。水晶球的header是家族两档，正文明确普通型Very Rare；现有记录兼任普通型，保留原值并注typical_item及正文证据，避免把建模迁移误报为转录错误。完整同调限定仅引用、不执行。预修快照magic-base-header-review.json保留两差异与缺引用证据。

tools/audit_magic_bonus_variants.py核五类15条+1/+2/+3变体，先从来源header独立解析稀有度与数值，再核派生正文及类型 / 名称 / 来源归属。完整母项原文、明确bonus选择、source_text_kind与未执行标记保留；39处补注释，既有数值与正文无需修改。Shield延续既有完整来源门禁，Armor不同稀有度表不套错，Wand不加豁免DC。其余111变体与装备效果执行继续待验收。

tools/audit_magic_consumable_variants.py独立消费四药水、十卷轴官方选择行，校验14变体112字段。卷轴child原uninterrupted条件反转与缺抄录段已更正，保留职业表、材料成分豁免、正常时间、被打断不损失、高阶检定失败消失、Wizard Arcana检定及无论成功失败销毁。药水恢复量与正文无差异；选择参数保留为reference，不宣称已接施法、治疗或消耗执行。

tools/audit_magic_giant_variants.py按两张原表核十二腰带 / 药水变体，Stone/Frost共享行双映射、不同稀有度、完整力量不降低条件与药水1小时均保留。36缺派生说明 / 引用补齐、两处多余冠词清理；数值无需改动。未接Strength或计时执行。

tools/audit_magic_affinity_variants.py核四表34变体272字段，完整消费双列、d10面、宝石与元素类型；源绑定保留动作、佩戴 / 同调、持续 / 恢复、感应范围及消耗条件，既有数值 / 正文无差异。102缺派生注释及完整来源引用补齐，不升级效果执行状态。
