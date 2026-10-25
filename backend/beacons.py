"""Eight Beacons: 32 authored encounters and 36 frozen SRD-derived presets."""
from functools import lru_cache
from copy import deepcopy
from .rules_identity import LEGACY_PACKAGE,RULESET_ID
from .story_graph import parse_book

BOOK_ID='book-eight-beacons'
PRESET_VERSION='beacons-v1'
# Each real source species is counted once, independently of its encounters.
SPECIES=[
 ('bandit','盗匪',1,30,[]),('guard','腐败守卫',1,5,['shield']),('scout','屋顶斥候',1,60,['skirmish']),('thug','码头暴徒',1,5,['pack']),('bandit-captain','封港匪首',1,5,['shield']),
 ('goblin','地精',2,30,['skirmish']),('hobgoblin','大地精',2,5,['pack']),('bugbear','熊地精',2,10,[]),('wolf','狼',2,5,['pack']),('dire-wolf','凶暴狼',2,5,['pack','charge']),('giant-spider','巨蜘蛛',2,30,['web','poison']),
 ('giant-rat','巨鼠',3,5,['pack']),('swarm-of-rats','鼠群',3,5,['pack']),('gray-ooze','灰泥怪',3,5,['drain']),('ochre-jelly','赭冻怪',3,5,['split']),('gelatinous-cube','胶质方块',3,5,['web']),('mimic','拟态怪',3,5,['web']),
 ('skeleton','骷髅',4,60,[]),('zombie','僵尸',4,5,['undead']),('ghoul','食尸鬼',4,5,['poison']),('ghast','妖鬼',4,5,['poison']),('wight','尸妖',4,30,['drain']),
 ('animated-armor','活化盔甲',5,5,['shield']),('flying-sword','飞剑',5,5,['skirmish']),('rug-of-smothering','扼杀之毯',5,5,['web']),('gargoyle','石像鬼',5,10,['shield']),('minotaur','牛头人',5,5,['charge']),
 ('sahuagin','沙华鱼人',6,5,['pack']),('merrow','海生魔人',6,10,['web']),('harpy','鹰身女妖',6,30,['web']),('sea-hag','海鬼婆',6,30,['poison','drain']),
 ('fire-elemental','火元素',7,10,['burn']),('air-elemental','气元素',7,30,['skirmish']),('earth-elemental','土元素',7,10,['shield']),('water-elemental','水元素',7,10,['web']),
 ('young-black-dragon','幼年黑龙',8,10,['breath'])]
BOSSES={'bandit-captain','bugbear','gelatinous-cube','wight','minotaur','sea-hag','water-elemental','young-black-dragon'}


@lru_cache(maxsize=1)
def _presets():
    from .rules_context import resolve
    source=resolve(LEGACY_PACKAGE).MONSTERS
    result=[]
    for id,name,chapter,reach,behaviors in SPECIES:
        row=source[id];boss=id in BOSSES
        actions=[a for a in row.get('actions',[]) if isinstance(a.get('attack_bonus'),int) and a.get('damage')]
        selected=actions[0] if actions else {}
        hp=(70+chapter*18) if boss else max(8,min(row['hit_points'],14+chapter*6))
        ac=row['armor_class'][0]['value'] if isinstance(row['armor_class'],list) else row['armor_class']
        result.append(dict(id='beacon-'+id,name=name,description=f"{row['name']} · 第{chapter}章战役预设。",
            source_id=id,source_note=f"来源 {RULESET_ID} / {LEGACY_PACKAGE}，SRD {row['name']}。预设{PRESET_VERSION}。"
                f"原HP {row['hit_points']}、原AC {ac}；本战役调校HP/AC/伤害与动作。登记行为：{','.join(behaviors) or '基础攻击'}。"
                '本预设不执行完整原怪物的全部特性；束缚/毒/坚韧/分裂/吐息为公开的有限配方，无飞行高度、吞没、永久减最大生命、死亡凝视或传奇动作。',
            tags=['SRD来源','战役预设','Boss' if boss else '普通'],hp=hp,ac=max(10,min(16,ac)),
            attack_bonus=min(7,max(2,selected.get('attack_bonus',2))),damage_dice='2d6' if chapter>=4 else '1d6',
            damage_bonus=min(4,1+chapter//3),initiative_bonus=min(3,(row['dexterity']-10)//2),
            speed=30,attack_range=reach,attack_count=2 if boss else 1,
            damage_type=selected.get('damage',[{}])[0].get('damage_type',{}).get('index','bludgeoning'),
            behaviors=behaviors,abilities={short:row.get(full,10) for short,full in [('str','strength'),('dex','dexterity'),('con','constitution'),('int','intelligence'),('wis','wisdom'),('cha','charisma')]},
            damage_resistances=[v for v in row.get('damage_resistances',[]) if isinstance(v,str)],
            damage_immunities=[v for v in row.get('damage_immunities',[]) if isinstance(v,str)]))
    return result


def presets():return deepcopy(_presets())


# Four separately authored encounters per chapter, with different terrain/tasks.
CHAPTERS=[
 ('封港钥匙','阿苇发现归船被封锁在海湾之外。夺回四处码头设施，让救援船能出港。',
  [('雨棚仓库',['bandit','thug'],'货箱之间留下窄道。先把近战引到通道，防止弩手隔箱集火。'),
   ('收费栅门',['guard','bandit'],'守卫据守栅门，斥候射击通路。可以从侧翼接近。'),
   ('屋顶绳桥',['scout','thug'],'远处斥候覆盖绳桥。使用掩墙绕行，不要站在整个火线里。'),
   ('封港匪首',['bandit-captain','guard'],'匪首的两座护盾锚减半所有伤害。派人绕侧翼关闭两锚，再集中攻击。')],
  ('仓门铜牌','装船单依次写着：第一批是粮食，第二批是药箱，第三批是灯油。铜锁只接受第二批货物的印记。门边三个纹章分别是麦穗、药叶、火焰。',{'grain':'按麦穗纹章','medicine':'按药叶纹章','oil':'按火焰纹章'},'medicine')),
 ('林间运道','伊岚需要林间运道运送备用镜片。清理四个路障，恢复物资线。',
  [('地精路障',['goblin','hobgoblin'],'弓手和持盾战士封住路口。石柱可以阻断远程视线。'),
   ('狼群岔路',['wolf','dire-wolf'],'狼群相邻夹击会获得优势。分散牵制，避免多人挤在同一角落。'),
   ('蛛巢救援',['giant-spider','goblin'],'巨蛛首次行动发射束缚网。保留治疗与移动，先救出被网住的队友。'),
   ('熊地精营地',['bugbear','hobgoblin'],'营地预告整行弩箭火线。离开红格并关闭两座绞盘，争取安全通道。')],
  ('林间风铃','三岔路上北铃无声、东铃响两次、西铃响一次。护林人刻下：安全之路随归港船的两声短笛回应。地上东侧脚印新鲜且向外延伸。',{'north':'走向北侧无声路','east':'沿东侧双响路','west':'沿西侧单响路'},'east')),
 ('旧海关排水','失控的水闸淹没海关，镜片图纸被困在地下。恢复排水，不需要追查复杂的阴谋。',
  [('粮仓鼠患',['giant-rat','swarm-of-rats'],'鼠群利用近邻协攻。借窄门逐个处理，避免被围。'),
   ('腐蚀排水渠',['gray-ooze','ochre-jelly'],'泥怪可汲取生命，冻怪受首次斩击/闪电时会分裂形成3点修复护体，改变伤害类型更有效。'),
   ('拟态档案柜',['mimic','gray-ooze'],'靠近柜体会遭首次黏附束缚；用远程和同伴支援解围。'),
   ('方块蓄水厅',['gelatinous-cube','ochre-jelly'],'汲取泵为敌方恢复生命。关闭两泵，避免持续耗战。方块的首次束缚有明确豁免。')],
  ('排水闸顺序','水位牌从高到低标着：上池、中池、下池。工匠笔记说：先让最低水池通向外海，再向上游逐级开启。闸门上画着由下向上的箭头。',{'down':'下池→中池→上池','up':'上池→中池→下池','middle':'中池→上池→下池'},'down')),
 ('守夜人墓地','亡灵占据旧引航员墓地。夺回换班名册，为下一段航程找到安全航道。',
  [('骷髅射击场',['skeleton','zombie'],'骷髅从远处射击，僵尸挡路。每个僵尸在非光耀致死时可挣扎站起一次，留意剩余1HP。'),
   ('停尸间',['zombie','ghoul'],'狭窄过道限制围攻。食尸鬼的毒性爪击要求体质豁免，失败中毒一轮。'),
   ('钟声墓穴',['ghoul','ghast'],'两种尸怪从侧面接近；先集中处理一个，防止多次中毒判定。'),
   ('尸妖指挥所',['wight','skeleton'],'指挥所的汲取装置不断修复尸妖。关闭装置，再阻止它借伤害恢复生命。')],
  ('值班名册','碑文写：阿岚在晨班，贝洛在午班，塞恩在夜班。钥匙刻着第一声钟响时交班，晨钟在日出响起。请找第一位接班者的姓名。',{'aran':'把阿岚的名牌放入晨钟槽','belo':'把贝洛的名牌放入晨钟槽','sain':'把塞恩的名牌放入晨钟槽'},'aran')),
 ('山顶机械站','伊岚需要恢复绞盘与升降桥。机关守卫只执行旧命令，击破控制回路即可继续。',
  [('飞剑装配厅',['flying-sword','animated-armor'],'飞剑速度战术与盔甲近战互补。别让前排挡住队友进路。'),
   ('盔甲巡廊',['animated-armor','flying-sword'],'中央墙体挡住直线射击。沿两侧行进，保持治疗者的视线。'),
   ('织物库房',['rug-of-smothering','gargoyle'],'扼杀之毯首次缠绕束缚，石像鬼触及更远。不要同时进入两者的近战区。'),
   ('牛头人绞盘厅',['minotaur','animated-armor'],'牛头人移动至少15尺命中后可撞倒目标；场地电流提前预警。关闭装置可熄灭后续电流。')],
  ('三轮齿轮','图纸写着：相邻齿轮反向转动。第一轮已固定顺时针，第三轮必须带动顺时针升降绳。只有中轮可由你们设置。',{'clockwise':'中轮顺时针','counter':'中轮逆时针','stop':'锁死中轮'},'counter')),
 ('潮汐祭坛','潮汐祭坛放大了敌人的号令。取回航标石，切断召唤元素井的通道。',
  [('沙华登陆点',['sahuagin','merrow'],'鱼人利用同伴近邻夹击；海生魔人的钩网有首次束缚豁免。'),
   ('歌声暗礁',['harpy','sahuagin'],'鹰身女妖的首次歌声在本预设中表现为一轮束缚，打断靠近路线后寻找安全射击位。'),
   ('拖船吊架',['merrow','harpy'],'狭窄吊架附近两类敌人互相掩护。利用墙角分隔它们的视线。'),
   ('海鬼婆祭坛',['sea-hag','sahuagin'],'祭坛两锚维持护体，海鬼婆还会汲取伤害。绕行关闭两锚，别在护体下耗尽资源。')],
  ('真实航标','三盏灯中红灯闪三次、白灯闪两次、绿灯常亮。船长手册写：雾中真实引航信号是白色双闪；持续亮光不是引航信号。',{'red':'回应红灯三闪','white':'回应白灯双闪','green':'回应绿色常亮'},'white')),
 ('四座元素井','失控的四座元素井维持海湾屏障。逐井关闭引导装置，阻断黑龙的能量。',
  [('燃料火井',['fire-elemental','gargoyle'],'火元素免疫火焰，命中附加2点灼热伤害。关闭燃料装置可以停止场地火线。'),
   ('遮蔽风井',['air-elemental','flying-sword'],'气元素进行远程打击并短距离撤位。绕墙逼近，让同伴互相保持视线。'),
   ('碎石土井',['earth-elemental','animated-armor'],'土元素坚硬护体，困难地形限制接近。使用合适伤害与安全侧道。'),
   ('排水水井',['water-elemental','merrow'],'水井每轮修复敌方。先关闭两座回流泵，避开首次束缚后完成清理。')],
  ('元素封印','封印上火、风、土、水四符环绕。铭文说：以水灭火，以土挡风。被点亮的是火符，旁边的水槽仍有清水。',{'water':'将清水引向火符','wind':'吹动风符助燃','fire':'向火符添加灯油'},'water')),
 ('归航核心','八处航标已经连成航道。黑龙在最后的灯塔核心阻拦归船，夺回控制权后让船只回家。',
  [('黑龙前哨',['gargoyle','sahuagin'],'守卫占据两侧入口，先打开一个突破口，别让治疗者被隔在墙后。'),
   ('失控灯塔',['animated-armor','air-elemental'],'线路交叉产生整行预警；关闭装置可停止火线，照顾受伤的队友。'),
   ('仪式守军',['wight','earth-elemental'],'坚硬前排与汲取者协同防守。分散牵制，利用装置与治疗轮换准备终战。'),
   ('黑龙核心战',['young-black-dragon','gargoyle'],'黑龙蓄积酸息时先标记直线，下轮爆发；腾出通道离开危险格。关闭两处锚能解除护体；半血后第二阶段强化攻击，无传奇动作。')],
  ('归航密码','从此前记录知道：白色双闪是真航标，接班从晨钟开始，封印用水制火。核心要求先确认航标、再接班、最后冷却。',{'correct':'白色双闪→晨钟→引水冷却','wrong-order':'引水冷却→红灯三闪→夜钟','wrong-light':'绿灯常亮→午钟→添加灯油'},'correct'))]


def book():
    nodes=[];edges=[];facts=[];checkpoints={}
    def route(id,source,to,label,condition=None):edges.append(dict(id=id,**{'from':source},to=to,label=label,condition=condition,main_path=True))
    nodes.append(dict(id='opening',kind='scene',title='八座航标 · 战役开场',text='阿苇把海湾地图铺在桌上：归船被黑龙和失控的元素核心困在湾外。伊岚只提出一个清晰的办法——恢复八处航标，把航道重新连起来。每章四场独立遭遇，章中和章末都有安全补给。先完成角色构筑，商量前后排与治疗分工；战场每格5尺，敌方由DM的战术代理行动。此战役跨多次游玩自动保存，不是此前2–4小时短篇。',objective='夺回第一处封港钥匙。'))
    previous='opening'
    xp=[900,1800,2700,4500,6500,9000,12000,12000]
    mechanics=['anchors','crossfire','drain','drain','storm','anchors','drain','anchors']
    for c,(title,intro,encounters,puzzle) in enumerate(CHAPTERS,1):
        gate=f'chapter-{c}';fact=f'gate-{c}';facts.append(dict(id=fact,kind='state',value_type='boolean',mutable=True,visibility='public',initial=False,description='本章机关已正确解开'))
        name,clues,choices,correct=puzzle
        nodes.append(dict(id=gate,kind='scene',title=f'第{c}章 · {title}',text=intro+' '+clues+' 先在队内交流中推理，再由领队选择装置操作（领队阵亡时由首位存活队员代行）。正确答案直接打开道路；错误只造成一次轻微擦伤，并给出提示。',objective=name,
            puzzles=[dict(id=f'puzzle-{c}',question=name,choices=choices,correct=correct,solved_fact=fact,success_text='机关按你们的推理打开，前方的航标设施可以进入。',failure_text='机关未响应。重新核对现场记载的顺序、颜色或因果关系；线索仍完整保留。')]))
        route(f'next-chapter-{c}',previous,gate,'前往下一处航标')
        previous=gate
        for e,(name,monsters,briefing) in enumerate(encounters,1):
            id=f'encounter-{c}-{e}';boss=e==4
            layouts=[[(5,y) for y in [2,3,5,6]],[(x,4) for x in [3,4,6,7]],[(4,3),(4,4),(7,5),(7,6)],[(x,y) for x in [4,7] for y in [3,6]],[(5,y) for y in [1,2,6,7]],[(3,3),(4,3),(7,6),(8,6)],[(x,5) for x in [3,4,7,8]],[(5,3),(6,3),(5,6),(6,6)]]
            walls=[dict(x=x,y=y) for x,y in layouts[c-1]]
            if e%2==0:walls=[dict(x=p['x'],y=9-p['y']) for p in walls]
            nodes.append(dict(id=id,kind='scene',title=f'{c}-{e} · {name}'+(' · Boss' if boss else ''),
                text=f'{intro} 现在来到{name}。{briefing} 这场战斗有独立的敌人、出生位置和完成记录；刷新不会复活敌人。战场装置每次关闭消耗一个动作，位置和回合均以场地图为准。',
                objective='控制装置与通道，击败守军，取得这一处航标部件。',monster_ids=['beacon-'+m for m in monsters],
                battlefield=dict(walls=walls,difficult=[dict(x=3,y=5),dict(x=4,y=5),dict(x=7,y=3)],
                    mechanic=mechanics[c-1] if boss else ('crossfire' if (c,e) in {(8,2),(7,1)} else 'none'),briefing=briefing)))
            route(f'enter-{c}-{e}',previous,id,'进入下一处守军阵地',dict(op='fact_equals',ref=fact,value=True) if e==1 else None)
            previous=id
            if e in {2,4}:
                camp=f'camp-{c}-{e}'
                nodes.append(dict(id=camp,kind='scene',title=f'第{c}章 · '+('中途补给站' if e==2 else '航标恢复与章末休整'),
                    text='阿苇的救援队接应你们。队伍在安全据点停留一天，恢复生命和职业资源；已经阵亡的角色不会凭空复活。已打通的阵地、谜题和装置保持原状。'+('这处航标重新点亮，伊岚在地图上画出下一段水道。领取成长资格后可在人物卡中逐级升级，再出发。' if e==4 else '整理战术、治疗分工与装备，然后继续本章后半段。'),objective='确认队伍状态，管理法术与成长，再继续。'))
                checkpoints[camp]=dict(xp=xp[c-1] if e==4 else 0,rest=True)
                route(f'return-{c}-{e}',previous,camp,'返回安全补给站（首次恢复）');previous=camp
    nodes.extend([dict(id='decision',kind='scene',title='最后的选择 · 核心归谁',text='黑龙倒下，八座航标重新回应归船。阿苇只等你们发出最后一个信号。可以修复核心交给自愿轮值的守夜人，也可以封存危险核心，改用众人的航标共同引航。两种选择都允许归船回家，不要求永久牺牲任何角色。',objective='选择修复或封存核心，并分享角色尾声。'),
        dict(id='restored',kind='ending',title='结局 · 八灯归航',text='八束光汇成安全水道，所有归船循光入港。伊岚把钥匙交给自愿轮值的人，阿苇念出获救船员的名字。你们修复了核心，也把守夜的责任交还整个港口。'),
        dict(id='sealed',kind='ending',title='结局 · 众人的航道',text='核心被封存在石匣中，八座独立航标仍然闪亮。归船依照众人的信号安全回港，再没有谁必须独自维持那一点火。你们留下可以接力维护的航道，下一次故事由新的航海者启程。')])
    route('final-decision',previous,'decision','走向最后的核心控制台')
    route('restore-core','decision','restored','修复核心，建立自愿轮值')
    route('seal-core','decision','sealed','封存核心，共同维护航标')
    return parse_book(dict(id=BOOK_ID,name='雾港八灯 · 归航战役',description='八章长篇战役 · 32场独立战斗 · 36种SRD来源敌人 · 8场机制Boss · 每章推理解谜。3级起步，推荐4人，支持1–6人；多次游玩自动存档。',
        schema_version=2,ruleset_id=RULESET_ID,rules_package_version=LEGACY_PACKAGE,starting_level=3,tags=['长篇战役','战棋','32场战斗','36种敌人','解谜'],
        outline='恢复八座航标，打通归船水道，击败占据核心的黑龙。每章机关→两场战斗→补给→两场战斗→章末恢复/成长。角色关系保持简单：阿苇救援、伊岚修复、敌方封锁。',
        entry_node_id='opening',monster_ids=['beacon-'+s[0] for s in SPECIES],skill_ids=['blade-strike','field-mending','take-cover','beacon-hammer'],
        checkpoints=checkpoints,fact_definitions=facts,nodes=nodes,edges=edges))
