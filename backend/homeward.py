"""Original v0.9 adventure. Only a main spine and one optional frontier are authored."""
from .rules_identity import RULESET_ID, LEGACY_PACKAGE
from .story_graph import parse_book

BOOK_ID = 'book-homeward-night'


def book():
    facts, nodes, edges = [], [], []

    def eq(ref, value):
        return dict(op='fact_equals', ref=ref, value=value)

    def done(ref):
        return dict(op='any', children=[eq(ref, 1), eq(ref, 2)])

    def scene(id, title, text, objective, *, check=None, monsters=None):
        row = dict(id=id, kind='scene', title=title, text=text, objective=objective,
                   main_path=True, place_id='homeward-'+id, monster_ids=monsters or [])
        if check:
            label, skills, dc, yes, no = check
            facts.append(dict(id=id, kind='state', value_type='integer', mutable=True,
                              visibility='public', initial=0, description=title+'：0未解决，1顺利，2付出代价'))
            row.update(kind='key', advancement_condition=done(id), failure_consequences=no,
                challenges=[dict(id='resolve-'+id, objective_key=id, question_id='approach',
                    label=label, description='先在交流频道商量方法，再由一位代表提交。全队同一问题共用一次检定，失败有后续路线。',
                    skill_ids=skills, dc=dc, condition=eq(id, 0),
                    success_effects=[dict(op='set_fact', ref=id, value=1)],
                    failure_effects=[dict(op='set_fact', ref=id, value=2)],
                    success_text=yes, failure_text=no)])
        nodes.append(row)

    def route(id, source, target, label, condition=None, outcome=''):
        edges.append(dict(id=id, **{'from':source}, to=target, label=label,
                          condition=condition, outcome=outcome, main_path=True))

    scene('dock', '第一幕 · 雨夜归船',
        '钟楼敲过午夜，灯塔却没有回应。三艘载着避难者的归船被困在外海，潮汐会在黎明前把它们推向暗礁。'
        '摆渡人阿苇把一把海关铜钥匙放到桌上：“救船用的透镜留在旧海关，守灯人却说再也不会替港口点灯。”'
        '她愿意引路，但要求先救船，不能把灯塔当作战利品。码头工头希望立刻起锚；一个孩子坚持母亲还在最后那艘船上。'
        '你们愿意替谁作出怎样的承诺？先介绍角色，约定遇到分歧由谁提交队伍路线，再询问钟声、归船和透镜各自出了什么事。',
        '商量救援承诺，向码头人收集可靠的潮汐与船位消息。',
        check=('向摆渡人与工人核实船位', ['persuasion','insight','perception'], 10,
               '阿苇画出三艘船的位置，并约定长短短三声钟代表安全水道。你们带着可靠情报动身。',
               '惊恐的人群互相打断。阿苇仍交出钥匙和旧海关地址，但只能确认归船都在北礁外；你们要到观潮台重新找船。'))
    scene('market', '第二幕 · 雨棚下的争执',
        '海关前的鱼市成了临时避难所。港务书记芮纱正要焚掉一袋受潮文件，搬运工米洛拦住她：里面有失踪船员的名单。'
        '芮纱承认透镜被扣押，却说是为了防止塔内“旧誓约”再次吞掉守夜人的生命。米洛只想取回父亲的姓名。'
        '两人都需要这袋文件。可以请芮纱朗读扣押令、让米洛指出父亲的签名，或检查纸页留下的水印。'
        '请让每位玩家说一件愿意保留或公开的东西。无论争执结果如何，钥匙都能打开海关；检定决定是否赢得他们的协作。',
        '处理证据与隐私的冲突，决定如何调查扣押令。',
        check=('保住文件并整理双方证词', ['persuasion','investigation','insight'], 12,
               '两人同意保留原件，抄本交给幸存家属。芮纱指出档案柜的双层夹板，米洛愿意帮你们搬运透镜。',
               '你们救下文件，但双方仍互不信任。芮纱写下档案柜位置后离开；米洛只留下去旧运道的地图。'))
    scene('customs', '第三幕 · 被涂去的名字',
        '旧海关的玻璃被盐打白。扣押柜里装着裂成两半的透镜，柜底的航海日志却比器材更受保护。'
        '名册每页都被划去一个守夜人的名字，最后一页只有“伊岚”。附页写着：灯火以自愿守夜者的记忆维持，誓约从未要求一人永远承担。'
        '另一张未寄出的信写着：“我不怕死，只怕有一天连他们为什么回家都不记得。”'
        '你们可以核对旧誓约与扣押日期，寻找谁改写了守夜制度，也可以沿外墙的新脚印追查送信人。'
        '追踪是可选 AI 支线；服务不可用时取消等待，留在这里继续修复透镜即可。',
        '从文件中辨认守夜制度的真相；决定要不要追查额外线索。',
        check=('对照日志、誓约与扣押记录', ['investigation','history','religion'], 12,
               '你们找齐带印章的完整原件，核对出港务官把轮值改成终身守夜的修订记录。原件包含解除旧誓约的完整步骤，能在塔顶立即使用。',
               '盐水毁掉了印章与解除步骤。你们知道“自愿、轮值”的真相，却没有可立即解除旧锁的完整原件；仍能以此交涉，陪伊岚救船后慢慢拆锁。'))
    scene('lens', '第四幕 · 透镜的裂口',
        '米洛留下的木箱里有铜箍、松脂和旧镜片。墙上装配图标明：镜片只能把已有火光送远，不能凭空制造火焰。'
        '裂口可以用铜箍稳住，若强行磨平会失去焦距。请商量由谁扶镜、谁看图、谁保护灯芯，再由代表处理最困难的一步。'
        '无论结果如何都能搬走透镜；失手时需要让伊岚和志愿者在塔顶持续校准，救援将多一份代价。',
        '修复并搬运透镜；说清如何分工。',
        check=('按照旧图稳定透镜裂口', ['investigation','sleight-of-hand','arcana'], 12,
               '铜箍正好固定住裂口，光斑在墙上清晰成形。透镜可在塔顶独立运转。',
               '透镜仍有重影，但没有报废。你们能把它带到塔顶，只是必须有人持续扶住校准杆直到归船通过。'))
    scene('council', '第五幕 · 两条进塔路',
        '风把钟声撕成碎片。去塔顶有两条路：旧运道经过绞盘和悬桥，较适合搬运透镜；盐雾小径经过废弃守卫站，路窄却能接近刻有原誓约的石碑。'
        '阿苇说：“别只问哪条更容易，也想想谁愿意跟你们一起走。”可以分配透镜、绳索和灯芯的搬运责任，讨论发现的制度应当如何公开。'
        '这里只需要领队提交路线；不要重复掷骰来争取更好的同一条线索。',
        '商量行进与搬运方案，选择运道或盐雾小径。')
    scene('winch', '第六幕甲 · 旧运道',
        '锈死的绞盘吊着一截倾斜栈桥。墙上的划痕显示最后一批守夜者曾试图从这里离开。'
        '可以用杠杆松开齿轮，也可以沿支架固定牵引绳。试着描述你们如何防止透镜坠落；失败不会让队伍掉入海里，但会迫使大家绕行长阶。'
        '当轮盘转动时，每个人听到一个自己差点遗忘的名字。你愿意告诉同伴这个名字吗？这只是角色扮演，不消耗资源。',
        '安全搬过透镜，并回应旧运道的记忆。',
        check=('固定绞盘或支架上的牵引绳', ['athletics','sleight-of-hand','investigation'], 12,
               '栈桥落回支柱，你们顺利把透镜推过去，还留下一条供避难者撤离的路。',
               '齿轮滑脱，安全绳保住了透镜。大家改走更长的石阶，抵达观潮台时衣服已被雨浸透。'))
    scene('saltpath', '第六幕乙 · 盐雾石碑',
        '小径尽头立着断碑，碑文的“自愿轮值”与海关文件一致。守卫站里传来铁器拖地声，一名盐壳守卫仍在执行“不许守夜人离塔”的旧命令。'
        '绕过它、从铃声空隙通过，或先观察它巡视的节奏，都有机会避免战斗。若被发现，你们仍可以退到石阶绕行；只有主动进入守卫站才会开始遭遇。',
        '寻找绕开旧守卫的通道；决定是否正面进入守卫站。',
        check=('观察巡逻并穿过盐雾小径', ['stealth','survival','perception'], 11,
               '你们带着碑文拓印通过小径，守卫仍在对空荡的雨幕报时。',
               '铁盔朝你们转来。你们退到安全转角，可绕行石阶，也可准备好再进入守卫站。'))
    scene('guard', '可选遭遇 · 仍未解除的命令',
        '盐壳守卫横起锈矛：“守夜人不得离塔。”盔甲内部空无一人，维持它的是失效的旧命令。'
        '你们选择了进入守卫站，遭遇开始。集中攻击、治疗与掩护请通过战斗框确认；队伍讨论不会消耗回合。'
        '打碎外壳后，这道命令将永久沉默，重访不会复活它。',
        '击败守卫，解除通道上的威胁。', monsters=['salt-warden'])
    scene('bridge', '第七幕 · 观潮台上的三盏光',
        '观潮台能看见三艘船。第一艘接近外礁，第二艘失去主帆，第三艘的灯忽明忽暗。阿苇递来遮光板，在这里向所有人重新讲明：长短短三声钟代表安全水道，可以用遮光板重复信号。'
        '请商量先向哪艘船发信号，以及如何避免让其他船误以为安全。可以辨认水流、船上灯位或旧航道标记。'
        '失败时船只仍会减速，但无法同时校准三艘；塔顶需要更久的人工引导。',
        '辨认船位并发出第一轮信号。',
        check=('判断航道并校准引航信号', ['survival','perception','nature'], 12,
               '三声钟得到三个回应。船只保持在外礁安全线，塔顶一旦点亮就能依次入港。',
               '雨幕让信号散开。归船停在外礁等待，但塔顶必须有人整夜逐船引导，不能只点灯离开。'))
    scene('shelter', '第八幕 · 台阶间的暖炉',
        '废弃值班室还留着一座暖炉、热水和写满姓名的换班牌。这里没有敌人。可以按当前房间规则使用休息或治疗，所有资源变化以行动记录为准。'
        '换班牌上最后一句是：“接班不是继承惩罚。”请每人决定一件事：愿意为救援留下多久，愿意公开哪一份证据，不愿接受哪一种交换。'
        '等大家确认后再去见伊岚；这段商量会影响你们如何扮演最终交涉，但不会由 AI 偷偷扣除生命或记忆。',
        '照顾伤员，拟定对伊岚的承诺，并确认全队准备好了。')
    scene('tower', '第九幕 · 伊岚守着最后一点火',
        '伊岚坐在熄灭的灯座旁，掌心握着一粒火。他已经忘记自己的家人，却记得每一艘船的名字。'
        '“每次点灯，我都会忘掉一点。港口需要我的时候就说这是荣耀，天亮后又把门锁上。”'
        '他愿意让归船靠岸，但拒绝再作一辈子的灯油。可以展示轮值誓约、解释芮纱扣押透镜的理由，或承认港口伤害了他。'
        '请先让不同角色提出方案，再推选代表回应他的条件。检定决定信任程度，不能抹去他拒绝永久服役的意愿。',
        '面对伊岚的条件，确认救船与守夜者自由如何同时实现。',
        check=('以证据或诚实的承诺争取伊岚信任', ['persuasion','insight','religion'], 13,
               '伊岚把火放进灯座：“一次，和你们一起。明天钥匙归所有愿意接班的人。”他同意放弃旧誓约。',
               '伊岚不相信新的制度，但仍愿救船一次。他要求你们留在校准杆旁，直到最后一艘靠岸，再亲手打开塔门。'))
    scene('decision', '第十幕 · 谁来接过这一夜',
        '透镜已经搬到灯座。现在有三种明确选择：修复灯光并安排轮值；解开旧誓约、用众人的信号送船回家；或停止冒险，用观潮台信号组织撤离。'
        '前两种都会继续进行一次最终检定。即使失败，大家仍能靠整夜守候完成有代价的救援。撤离会放弃救回全部船只，换取留在岸上的人安全。'
        '请分别说出愿意承担的责任，再由领队提交。不要把一个人的牺牲当作未经同意的队伍决定。',
        '共同决定救援方案；也可选择安全撤离。')
    scene('light', '终幕甲 · 将光送过暗礁',
        '火焰进入透镜，校准杆却在狂风中偏转。你们必须让第一束光落在水道入口，而不是礁石上。'
        '请描述固定透镜、读潮与发信号的分工；代表进行最后一次校准。此前修镜或观潮不顺利时，即使现在成功，也需要全队守到最后一艘船入港。',
        '完成最终校准；接受此前准备带来的结果。',
        check=('合力校准灯座与引航光束', ['arcana','investigation','survival'], 12,
               '光束稳住了。你们按先前讨论的轮值方案接过灯塔，不再要求一人永久守夜。',
               '光束不停偏移，但你们合力握住校准杆，一点点把归船带进水道；这一夜必须留下来守完。'))
    scene('oath', '终幕乙 · 打开塔门',
        '你们把原誓约摆在灯座前，让伊岚亲口读出“自愿”。众人以遮光板、钟声与剩余火焰接替那一道束缚他的命令。'
        '选择一个愿意留给未来守夜人的承诺，并说清明天由谁去港口公开轮值制度。检定决定能否立即拆掉旧束缚；失败时仍能等归船靠岸后再解除。',
        '解除终身守夜制度，完成共同引航。',
        check=('以原誓约和协同行动解除旧束缚', ['religion','arcana','persuasion'], 13,
               '旧锁自己落下。伊岚第一次走到窗外，灯火由众人的信号继续传递。解除誓约还不等于完成引航；此前文件、观潮或交涉准备不足时，你们仍须共同守到最后一艘船靠岸。',
               '旧锁仍在发热。伊岚同意再守到黎明；你们陪他完成引航，天亮后一起拆掉锁链。'))

    endings = [
        ('dawn', '结局 · 归航之光', '第一艘、第二艘、最后一艘归船依次进港。伊岚在日出前走下灯塔，阿苇把铜钥匙挂在新的换班牌旁。芮纱交出原始名册，米洛读出父亲的名字。你们没有替港口抹平过去，却让救援和自由在同一夜实现。请每人说一个归来的人会怎样记住你，以及你会把接班牌交给谁。'),
        ('vigil', '结局 · 众人守完的一夜', '最后一艘船靠岸时，所有人的手都冻僵了。透镜、信号或旧誓约没能顺利解决，你们便亲手扶着光束守到黎明。伊岚仍活着，塔门终于打开；港口欠他的债不会被一场救援抹掉。请每人说出付出的代价和明天要兑现的一件事。没人被要求永久留在塔内。'),
        ('evacuation', '结局 · 岸上的灯', '你们决定不再冒险启动灯塔，转而敲响撤离钟。两艘船循观潮台信号进入浅湾，最后一艘被潮水推向外海，生还者的搜寻将留到天明。岸上的人得到安全，伊岚也走出塔门。这不是全胜，但你们承担了选择。请每人说一个还会去寻找的人、一件愿意留下的证据。')]
    for id, title, text in endings:
        nodes.append(dict(id=id, kind='ending', title=title, text=text, objective='冒险结束：分享角色尾声，再查看成长奖励。'))

    route('dock-market','dock','market','带着约定前往雨棚鱼市',done('dock'))
    route('market-customs','market','customs','拿钥匙进入旧海关',done('market'))
    route('customs-lens','customs','lens','带上文件，处理裂开的透镜',done('customs'))
    route('lens-council','lens','council','搬出透镜，选择进塔路线',done('lens'))
    route('choose-winch','council','winch','选择适合搬运的旧运道')
    route('choose-saltpath','council','saltpath','选择刻有誓约的盐雾小径')
    route('winch-bridge','winch','bridge','带透镜前往观潮台',done('winch'))
    route('saltpath-bridge','saltpath','bridge','避开守卫，绕到观潮台',done('saltpath'))
    route('saltpath-guard','saltpath','guard','主动进入守卫站（可选战斗）',done('saltpath'))
    route('guard-bridge','guard','bridge','解除命令后前往观潮台')
    route('bridge-shelter','bridge','shelter','进入值班室，照顾同伴',done('bridge'))
    route('shelter-tower','shelter','tower','确认准备完毕，拜访伊岚')
    route('tower-decision','tower','decision','讨论最终救援方案',done('tower'))
    route('choose-light','decision','light','修复灯光，建立自愿轮值')
    route('choose-oath','decision','oath','解开旧誓约，共同引航')
    route('choose-evacuation','decision','evacuation','放弃启动灯塔，组织撤离')
    good_light = dict(op='all', children=[eq('light',1),eq('lens',1),eq('bridge',1),eq('tower',1)])
    good_oath = dict(op='all', children=[eq('oath',1),eq('customs',1),eq('bridge',1),eq('tower',1)])
    for source, good in [('light',good_light),('oath',good_oath)]:
        route(source+'-dawn',source,'dawn','送最后一艘船入港，迎接黎明',good)
        route(source+'-vigil',source,'vigil','承担代价，陪同伴守完这一夜',
              dict(op='all',children=[done(source),dict(op='not',children=[good])]))
    nodes.append(dict(id='courier-frontier',kind='frontier',title='可选支线 · 送信人的新脚印',
        continuation=dict(summary='玩家从旧海关沿新脚印追查送信人的身份；额外证据支线，不替代修复透镜主线。',
            confirmed_fact_ids=['customs'], unresolved_threads=['谁把伊岚未寄出的信送到海关？'],
            npc_goal_ids=['boatman','keeper'], allowed_monster_ids=[],candidate_milestone_ids=[],
            constraints=['保留三艘归船受困与伊岚拒绝永久守夜的前提。','不能声称透镜已修复或自动救船。',
                         '提供可调查的线索与回到旧海关的路线；不强制进入下一续写。'],fallback_scene_id='customs')))
    route('follow-courier','customs','courier-frontier','可选：沿新脚印追查送信人（AI 续写）',done('customs'))
    return parse_book(dict(id=BOOK_ID,name='雾港：归航之夜',schema_version=2,
        description='首个完整冒险 · 预计 2–4 小时 · 推荐 2–4 人，支持单人。调查旧誓约、选择进塔路线、共同决定三艘归船与守灯人的命运。AI 支线可跳过，离线仍能通关。',
        tags=['v0.9','完整冒险','2–4小时','调查','抉择'],ruleset_id=RULESET_ID,
        rules_package_version=LEGACY_PACKAGE,starting_level=3,
        outline='午夜三艘归船受困。调查海关→修复透镜→运道或盐径→观潮与准备→面对伊岚→修灯、解誓或撤离→三种尾声。'
                '预计150–210分钟，单人可更快。每幕先描述可见情境，询问各角色方法与关系，再结算代表检定。'
                '不连续代替玩家点击推进，不伪造资源、失败、牺牲或胜利。失败通过结果事实开放后续。'
                '盐径守卫为单个弱遭遇，可绕行，不是完整5e难度标定。可选送信人支线需回接海关；服务失败继续作者主线。',
        entry_node_id='dock',fact_definitions=facts,npc_goals=[
            dict(id='boatman',description='阿苇要三艘归船安全入港，反对把守夜人当耗材。'),
            dict(id='keeper',description='伊岚愿救船，但拒绝继续永久服役。')],
        ending_constraints=['任何结局都不强迫角色永久牺牲。','全胜需要实际准备成功；失败有守夜代价。','不能用叙述跳过最终检定或资源结算。'],
        skill_ids=['blade-strike','field-mending','take-cover'],monster_ids=['salt-warden'],nodes=nodes,edges=edges))
