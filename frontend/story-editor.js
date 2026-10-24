/* Author graph editor. Data only: never evaluates conditions or runs a scene. */
(() => {
  const selections = new WeakMap();
  const expansions = new WeakMap();
  const notices = new WeakMap();
  const isOpen = (book,key,fallback=false) => expansions.get(book)?.get(key) ?? fallback;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const kinds = {key:'关键节点', scene:'场景', frontier:'待续写出口', ending:'结局'};
  const ops = {none:'无附加条件', all:'全部成立', any:'任一成立', not:'条件不成立', fact_equals:'事实等于', has_item:'持有物品', event_occurred:'事件已发生', milestone_state:'里程碑状态'};
  const states = {pending:'待完成', achieved:'已达成', failed:'失败', bypassed:'绕行'};
  const get = (object, path) => path.split('.').reduce((value,key) => value?.[key], object);
  function set(object, path, value) {
    const keys = path.split('.');
    let target = object;
    for (const key of keys.slice(0,-1)) target = target[key];
    target[keys.at(-1)] = value;
  }
  function options(values, value) {
    const result = {...values};
    if (value && !Object.hasOwn(result,value)) result[value] = `${value}（引用待修复）`;
    return Object.entries(result).map(([id,label]) => `<option value="${esc(id)}" ${String(value??'')===id?'selected':''}>${esc(label)}</option>`).join('');
  }
  const field = (label,path,value,type='text') => `<label>${esc(label)}<input data-g-field="${path}" type="${type}" ${type==='checkbox'?(value?'checked':''):`value="${esc(value)}"`}></label>`;
  const area = (label,path,value) => `<label>${esc(label)}<textarea rows="3" data-g-field="${path}">${esc(value)}</textarea></label>`;
  const select = (label,path,value,values) => `<label>${esc(label)}<select data-g-field="${path}">${options(values,value)}</select></label>`;
  const lines = (label,path,values) => `<label>${esc(label)}<textarea rows="3" data-g-lines="${path}">${esc((values||[]).join('\n'))}</textarea></label>`;
  const ids = rows => Object.fromEntries((rows||[]).map(row => [row.id,row.description || row.id]));
  const nodeOptions = book => Object.fromEntries(book.nodes.map(node => [node.id,`${node.title} · ${node.id}`]));
  function choices(label,path,values,available) {
    const all = {...available};
    for (const value of values || []) if (!Object.hasOwn(all,value)) all[value] = `${value}（引用待修复）`;
    return `<fieldset><legend>${esc(label)}</legend>${Object.entries(all).map(([id,name]) => `<label class="graph-check"><input type="checkbox" data-g-list="${path}" value="${esc(id)}" ${(values||[]).includes(id)?'checked':''}>${esc(name)}</label>`).join('') || '<p class="helper">尚无声明项</p>'}</fieldset>`;
  }
  function condition(book, expression, path, depth=0, optional=true) {
    if (depth>=12) return '<p class="helper">条件嵌套超过编辑上限，请简化后校验。</p>';
    const op = expression?.op || 'none';
    const available = {...ops};
    if (!optional) delete available.none;
    let body = `<select aria-label="条件类型" data-g-op="${path}">${options(available,op)}</select>`;
    if (['all','any','not'].includes(op)) {
      body += (expression.children||[]).map((child,index) => `<div class="graph-condition-child">${condition(book,child,`${path}.children.${index}`,depth+1,false)}${op!=='not'?`<button type="button" data-g-remove-condition="${path}:${index}">移除子条件</button>`:''}</div>`).join('');
      if (op!=='not') body += `<button type="button" data-g-add-condition="${path}" ${(expression.children||[]).length>=32?'disabled':''}>添加子条件</button>`;
    } else if (op!=='none') {
      const refs = op==='fact_equals'?ids(book.fact_definitions):op==='milestone_state'?ids(book.milestones):Object.fromEntries((book[op==='has_item'?'item_ids':'event_ids']||[]).map(id=>[id,id]));
      body += `<label>引用<select data-g-cond-ref="${path}">${options({'':'请选择声明项',...refs},expression.ref)}</select></label>`;
      if (op==='fact_equals') {
        const fact = book.fact_definitions.find(row=>row.id===expression.ref);
        if (fact && typeof expression.value !== {boolean:'boolean',integer:'number',string:'string'}[fact.value_type])
          body += '<p class="graph-missing">比较值与事实的新类型不符，请重新填写。</p>';
        body += fact?.value_type==='boolean'
          ? select('值',`${path}.value`,String(expression.value),{true:'是',false:'否'})
          : field('值',`${path}.value`,expression.value,fact?.value_type==='integer'?'number':'text');
      }
      if (op==='milestone_state') body += select('状态',`${path}.state`,expression.state,states);
    }
    return `<div class="graph-condition" data-g-condition="${path}">${body}</div>`;
  }
  function defaultCondition(book,op) {
    if (op==='none') return null;
    if (['all','any','not'].includes(op)) return {op,children:[defaultCondition(book,'fact_equals')]};
    const ref = op==='fact_equals'?book.fact_definitions[0]?.id:op==='milestone_state'?book.milestones[0]?.id:book[op==='has_item'?'item_ids':'event_ids'][0];
    const value = {op,ref:ref||''};
    if (op==='fact_equals') value.value = book.fact_definitions[0]?.initial ?? false;
    if (op==='milestone_state') value.state = 'pending';
    return value;
  }
  function navigation(book, selected) {
    const nodes = new Map(book.nodes.map(node=>[node.id,node]));
    const seen = new Set();
    function branch(id,ancestors=[],via=null) {
      const node = nodes.get(id);
      if (!node) return `<li class="graph-missing">缺少节点 ${esc(id)}</li>`;
      const reference = ancestors.includes(id)?'返回引用':seen.has(id)?'汇合引用':null;
      const button = `<button type="button" data-g-select="${esc(id)}" class="${selected===id?'selected':''}">${esc(node.title)} <small>${reference||kinds[node.kind]}</small></button>`;
      if (reference) return `<li>${button}</li>`;
      seen.add(id);
      const next = book.edges.filter(edge=>edge.from===id).sort((a,b)=>Number(b.main_path)-Number(a.main_path)||b.priority-a.priority||a.id.localeCompare(b.id));
      if (!next.length) return `<li>${button}</li>`;
      const open = isOpen(book,`node:${id}`,!ancestors.length || node.main_path || via?.main_path);
      return `<li><details data-g-open="${esc(`node:${id}`)}" ${open?'open':''}><summary>${button}</summary><ul>${next.map(edge=>branch(edge.to,[...ancestors,id],edge)).join('')}</ul></details></li>`;
    }
    let html = branch(book.entry_node_id);
    for (const node of book.nodes) if (!seen.has(node.id)) html += `<li class="graph-missing">未连接节点</li>${branch(node.id)}`;
    return `<nav class="graph-tree" aria-label="剧情树"><ul>${html}</ul></nav>`;
  }
  function declarations(book) {
    const facts = book.fact_definitions.map((fact,index) => {
      const path = `fact_definitions.${index}`;
      return `<div class="node-action">${field('事实 ID',`${path}.id`,fact.id)}${area('说明',`${path}.description`,fact.description)}${select('类别',`${path}.kind`,fact.kind,{premise:'世界前提',state:'世界状态',knowledge:'知识',secret:'秘密'})}${select('值类型',`${path}.value_type`,fact.value_type,{boolean:'是 / 否',integer:'整数',string:'文本'})}${fact.value_type==='boolean'?select('初值',`${path}.initial`,String(fact.initial),{true:'是',false:'否'}):field('初值',`${path}.initial`,fact.initial,fact.value_type==='integer'?'number':'text')}${field('允许改变',`${path}.mutable`,fact.mutable,'checkbox')}${select('可见范围',`${path}.visibility`,fact.visibility,{public:'公开',scoped:'按角色知识范围',dm_secret:'仅 DM'})}<button data-g-remove-declaration="fact_definitions:${index}">删除事实</button></div>`;
    }).join('');
    const groups = [['milestones','里程碑'],['npc_goals','NPC 目标']].map(([key,label])=>`<h4>${label}</h4>${book[key].map((row,index)=>`<div class="node-action">${field('ID',`${key}.${index}.id`,row.id)}${area('说明',`${key}.${index}.description`,row.description)}${key==='milestones'?select('初始状态',`${key}.${index}.initial_state`,row.initial_state,states):''}<button data-g-remove-declaration="${key}:${index}">删除</button></div>`).join('')}<button data-g-add-declaration="${key}">添加${label}</button>`).join('');
    return `<details class="graph-declarations" data-g-open="declarations" ${isOpen(book,'declarations')?'open':''}><summary>世界事实、里程碑与续写引用</summary><h4>事实</h4>${facts}<button data-g-add-declaration="fact_definitions">添加事实</button>${groups}${lines('可引用物品 ID · 每行一个','item_ids',book.item_ids)}${lines('可引用事件 ID · 每行一个','event_ids',book.event_ids)}${lines('结局约束 · 每行一项','ending_constraints',book.ending_constraints)}</details>`;
  }
  function nodePanel(book,node,index,monsters) {
    const path = `nodes.${index}`;
    let body = `<div class="field-grid">${field('节点名称',`${path}.title`,node.title)}${field('节点 ID',`${path}.id`,node.id)}${select('节点类型',`${path}.kind`,node.kind,kinds)}${field('主路径标记',`${path}.main_path`,node.main_path,'checkbox')}</div>${area('场景正文',`${path}.text`,node.text)}${field('冲突 / 当前目标',`${path}.objective`,node.objective)}`;
    if (node.kind==='key') body += area('失败后果',`${path}.failure_consequences`,node.failure_consequences)+`<h4>推进条件</h4>${condition(book,node.advancement_condition,`${path}.advancement_condition`)}`;
    if (node.kind==='ending') body += `<h4>结局适用条件</h4>${condition(book,node.ending_condition,`${path}.ending_condition`)}`;
    if (['key','scene'].includes(node.kind)) body += choices('预设怪兽卡',`${path}.monster_ids`,node.monster_ids,monsters);
    if (node.objects?.length) body += `<p class="helper">保留 ${node.objects.length} 个环境对象：${node.objects.map(obj=>esc(obj.name)).join('、')}。可在原始数据区编辑详情。</p>`;
    if (node.kind==='frontier') {
      const c = node.continuation || {};
      const cp = `${path}.continuation`;
      const playable = Object.fromEntries(book.nodes.filter(n=>['key','scene'].includes(n.kind)).map(n=>[n.id,n.title]));
      body += `<h4>续写信息</h4>${area('当前摘要',`${cp}.summary`,c.summary)}${lines('未解线索 · 每行一项',`${cp}.unresolved_threads`,c.unresolved_threads)}${lines('续写约束 · 每行一项',`${cp}.constraints`,c.constraints)}${choices('已确认事实引用',`${cp}.confirmed_fact_ids`,c.confirmed_fact_ids,ids(book.fact_definitions))}${choices('NPC 目标',`${cp}.npc_goal_ids`,c.npc_goal_ids,ids(book.npc_goals))}${choices('可用怪兽',`${cp}.allowed_monster_ids`,c.allowed_monster_ids,monsters)}${choices('候选里程碑',`${cp}.candidate_milestone_ids`,c.candidate_milestone_ids,ids(book.milestones))}${select('续写失败时的可玩场景',`${cp}.fallback_scene_id`,c.fallback_scene_id||'',{'':'留在原场景',...playable})}`;
    }
    const edges = book.edges.map((edge,ei)=>({edge,ei})).filter(row=>row.edge.from===node.id);
    body += edges.map(({edge,ei}) => {
      const p = `edges.${ei}`;
      return `<section class="node-action"><h4>连接 ${esc(edge.id)}</h4>${select('前往',`${p}.to`,edge.to,nodeOptions(book))}${area('结果说明',`${p}.outcome`,edge.outcome)}${select('可见范围',`${p}.visibility`,edge.visibility,{public:'公开',known:'知情者可见',secret:'仅 DM'})}${field('优先级',`${p}.priority`,edge.priority,'number')}${field('主路径',`${p}.main_path`,edge.main_path,'checkbox')}${edge.legacy_action_id?`<p class="helper">原行动 ${esc(edge.legacy_action_id)} · ${esc(edge.legacy_result)}，保留原检定出口。</p><button data-g-convert="${ei}">转换为普通连接</button>`:`<h4>进入条件</h4>${condition(book,edge.condition,`${p}.condition`)}<button data-g-remove-edge="${ei}">移除连接</button>`}</section>`;
    }).join('');
    if (['key','scene'].includes(node.kind)) body += `<button id="graph-add-edge">添加连接</button>`;
    const linked = book.edges.some(e=>e.from===node.id||e.to===node.id);
    body += `<button id="graph-remove-node" ${linked||node.id===book.entry_node_id?'disabled':''} title="先移除相关连接；入口节点不能删除">删除节点</button>`;
    return body;
  }
  function render(book,monsters={}) {
    const selected = selections.get(book) || book.entry_node_id;
    const index = Math.max(0,book.nodes.findIndex(node=>node.id===selected));
    const node = book.nodes[index];
    return `<p role="status" class="graph-missing">${esc(notices.get(book)||'')}</p>${area('剧本大纲','outline',book.outline)}${select('入口节点','entry_node_id',book.entry_node_id,Object.fromEntries(book.nodes.filter(n=>['key','scene'].includes(n.kind)).map(n=>[n.id,n.title])))}${declarations(book)}<section class="graph-workspace">${navigation(book,node?.id)}<div class="graph-node-panel">${node?nodePanel(book,node,index,monsters):'<p>请添加节点</p>'}</div></section><button id="graph-add-node">添加场景节点</button><p class="helper">主路径用于导航。未展开的支路和待续写出口不会因此失效；校验检查结构与引用，剧情仍需作者审阅。</p>`;
  }
  function rename(book,collection,before,after) {
    if (collection==='nodes') {
      if (book.entry_node_id===before) book.entry_node_id=after;
      for (const edge of book.edges) for (const field of ['from','to']) if (edge[field]===before) edge[field]=after;
      for (const node of book.nodes) {
        if (node.continuation?.fallback_scene_id===before) node.continuation.fallback_scene_id=after;
        for (const action of node.legacy_actions||[]) for (const field of ['next_node_id','success_node_id','failure_node_id']) if(action[field]===before)action[field]=after;
      }
      selections.set(book,after);
    } else {
      const op = collection==='fact_definitions'?'fact_equals':collection==='milestones'?'milestone_state':null;
      function walk(condition) {
        if (!condition) return;
        if (op && condition.op===op && condition.ref===before)condition.ref=after;
        for (const child of condition.children||[])walk(child);
      }
      book.edges.forEach(edge=>walk(edge.condition));
      book.nodes.forEach(node=>{
        walk(node.advancement_condition);walk(node.ending_condition);
        const key={fact_definitions:'confirmed_fact_ids',milestones:'candidate_milestone_ids',npc_goals:'npc_goal_ids'}[collection];
        if(node.continuation&&key)node.continuation[key]=node.continuation[key].map(id=>id===before?after:id);
      });
    }
  }
  function unique(prefix,rows) {let n=1;while(rows.some(row=>row.id===`${prefix}-${n}`))n++;return `${prefix}-${n}`;}
  function bind(root,book,changed) {
    function refresh(modified=true) {
      const open = expansions.get(book)||new Map();
      root.querySelectorAll('[data-g-open]').forEach(details=>open.set(details.dataset.gOpen,details.open));
      expansions.set(book,open);changed(true,modified);
    }
    const redraw=()=>refresh(),touch=()=>changed(false);
    root.querySelectorAll('[data-g-select]').forEach(button=>button.onclick=()=>{selections.set(book,button.dataset.gSelect);refresh(false);});
    root.querySelectorAll('[data-g-field]').forEach(input=>input.addEventListener(input.tagName==='SELECT'||input.type==='checkbox'||input.dataset.gField.endsWith('.id')?'change':'input',()=>{
      const path=input.dataset.gField,before=get(book,path);
      let value=input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value;
      if(path.endsWith('.id')) {
        const collection=book[path.split('.')[0]];
        if(!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(value)||collection.some(row=>row.id===value&&row.id!==before)) {
          notices.set(book,'ID 必须合法且不能与同类条目重复；名称和引用保持原值。');
          refresh(false);return;
        }
      }
      if(path.endsWith('.initial')) {
        const fact=get(book,path.split('.').slice(0,-1).join('.'));
        value=fact.value_type==='boolean'?input.value==='true':fact.value_type==='integer'?Number(input.value):input.value;
      }
      if(path.endsWith('.value')) {
        const expression=get(book,path.split('.').slice(0,-1).join('.'));
        const fact=book.fact_definitions.find(row=>row.id===expression.ref);
        value=fact?.value_type==='boolean'?input.value==='true':fact?.value_type==='integer'?Number(input.value):input.value;
      }
      if(path.endsWith('.fallback_scene_id'))value=value||null;
      if(path.endsWith('.kind')&&path.startsWith('nodes.')) {
        const node=get(book,path.split('.').slice(0,-1).join('.'));
        if(['frontier','ending'].includes(value)&&(node.objects?.length||node.legacy_actions?.length||book.edges.some(e=>e.from===node.id))) {
          window.alert('请先移除遭遇、对象和旧行动连接，再改为末端节点。');input.value=before;return;
        }
        if(['frontier','ending'].includes(value)&&node.monster_ids?.length){window.alert('请先移除此节点的怪兽。');input.value=before;return;}
        node.advancement_condition=null;node.failure_consequences='';node.ending_condition=null;
        node.continuation=value==='frontier'?{summary:'',confirmed_fact_ids:[],unresolved_threads:[],npc_goal_ids:[],allowed_monster_ids:[],candidate_milestone_ids:[],constraints:[],fallback_scene_id:null}:null;
      }
      set(book,path,value);
      if(path.endsWith('.id'))rename(book,path.split('.')[0],before,value);
      if(path.endsWith('.to')&&path.startsWith('edges.')) {
        const edge=get(book,path.split('.').slice(0,-1).join('.'));
        if(edge.legacy_action_id) {
          const action=book.nodes.find(n=>n.id===edge.from)?.legacy_actions.find(a=>a.id===edge.legacy_action_id);
          if(action)action[{direct:'next_node_id',success:'success_node_id',failure:'failure_node_id'}[edge.legacy_result]]=value;
        }
      }
      if(path.endsWith('.value_type')) {
        const fact=get(book,path.split('.').slice(0,-1).join('.'));
        fact.initial={boolean:false,integer:0,string:''}[value];
        notices.set(book,'事实类型已改变；已有比较值保持原样，请核对并修复所有引用条件。');
      }
      if(input.tagName==='SELECT'||path.endsWith('.id')||path.endsWith('.main_path'))redraw();else touch();
    }));
    root.querySelectorAll('[data-g-lines]').forEach(input=>input.oninput=()=>{set(book,input.dataset.gLines,input.value.split('\n').map(v=>v.trim()).filter(Boolean));touch();});
    root.querySelectorAll('[data-g-list]').forEach(input=>input.onchange=()=>{
      const path=input.dataset.gList,values=get(book,path)||[];
      set(book,path,input.checked?[...new Set([...values,input.value])]:values.filter(v=>v!==input.value));
      if(input.checked&&(path.endsWith('.monster_ids')||path.endsWith('.allowed_monster_ids'))&&!book.monster_ids.includes(input.value))book.monster_ids.push(input.value);
      touch();
    });
    root.querySelectorAll('[data-g-op]').forEach(input=>input.onchange=()=>{set(book,input.dataset.gOp,defaultCondition(book,input.value));redraw();});
    root.querySelectorAll('[data-g-cond-ref]').forEach(input=>input.onchange=()=>{
      const expr=get(book,input.dataset.gCondRef);expr.ref=input.value;
      if(expr.op==='fact_equals')expr.value=book.fact_definitions.find(f=>f.id===input.value)?.initial??false;
      redraw();
    });
    root.querySelectorAll('[data-g-add-condition]').forEach(button=>button.onclick=()=>{get(book,button.dataset.gAddCondition).children.push(defaultCondition(book,'fact_equals'));redraw();});
    root.querySelectorAll('[data-g-remove-condition]').forEach(button=>button.onclick=()=>{const [path,index]=button.dataset.gRemoveCondition.split(':');get(book,path).children.splice(Number(index),1);redraw();});
    root.querySelectorAll('[data-g-convert]').forEach(button=>button.onclick=()=>{
      const edge=book.edges[Number(button.dataset.gConvert)];
      if(!window.confirm('转换原行动的全部出口为普通连接？原检定将不再控制这些连接，请重新配置条件。'))return;
      const node=book.nodes.find(n=>n.id===edge.from),id=edge.legacy_action_id;
      node.legacy_actions=node.legacy_actions.filter(action=>action.id!==id);
      for(const row of book.edges)if(row.from===edge.from&&row.legacy_action_id===id){row.legacy_action_id=null;row.legacy_result=null;}
      redraw();
    });
    root.querySelectorAll('[data-g-remove-edge]').forEach(button=>button.onclick=()=>{book.edges.splice(Number(button.dataset.gRemoveEdge),1);redraw();});
    root.querySelectorAll('[data-g-add-declaration]').forEach(button=>button.onclick=()=>{
      const key=button.dataset.gAddDeclaration,row={id:unique(key==='fact_definitions'?'fact':key==='milestones'?'milestone':'goal',book[key]),description:'待填写'};
      if(key==='fact_definitions')Object.assign(row,{kind:'state',value_type:'boolean',initial:false,mutable:true,visibility:'scoped'});
      if(key==='milestones')row.initial_state='pending';
      book[key].push(row);redraw();
    });
    root.querySelectorAll('[data-g-remove-declaration]').forEach(button=>button.onclick=()=>{const [key,index]=button.dataset.gRemoveDeclaration.split(':');book[key].splice(Number(index),1);redraw();});
    root.querySelector('#graph-add-node')?.addEventListener('click',()=>{
      if(book.nodes.length>=200)return;
      const node={id:unique('node',book.nodes),kind:'scene',title:'新场景',text:'待填写场景正文',objective:'',main_path:false,monster_ids:[],objects:[],legacy_actions:[],advancement_condition:null,failure_consequences:'',ending_condition:null,continuation:null};
      book.nodes.push(node);selections.set(book,node.id);redraw();
    });
    const selected=selections.get(book)||book.entry_node_id,node=book.nodes.find(n=>n.id===selected)||book.nodes[0];
    root.querySelector('#graph-add-edge')?.addEventListener('click',()=>{
      if(book.edges.length>=1200)return;
      book.edges.push({id:unique('edge',book.edges),from:node.id,to:book.nodes.find(n=>n.id!==node.id)?.id||node.id,condition:null,outcome:'',visibility:'public',priority:0,main_path:false,legacy_action_id:null,legacy_result:null});redraw();
    });
    root.querySelector('#graph-remove-node')?.addEventListener('click',()=>{
      if(node.id===book.entry_node_id||book.edges.some(e=>e.from===node.id||e.to===node.id))return;
      book.nodes.splice(book.nodes.indexOf(node),1);selections.set(book,book.entry_node_id);redraw();
    });
  }
  function conditionText(book,expr,depth=0) {
    if(!expr)return '无需附加条件';
    if(depth>=12)return '条件过深，请校验';
    if(['all','any'].includes(expr.op))return `（${(expr.children||[]).map(child=>conditionText(book,child,depth+1)).join(expr.op==='all'?' 且 ':' 或 ')}）`;
    if(expr.op==='not')return `不满足：${conditionText(book,expr.children?.[0],depth+1)}`;
    if(expr.op==='fact_equals')return `${expr.ref} 等于 ${JSON.stringify(expr.value)}`;
    if(expr.op==='milestone_state')return `${expr.ref} 为 ${states[expr.state]||expr.state}`;
    return `${expr.op==='has_item'?'持有物品':'已发生事件'}：${expr.ref}`;
  }
  function preview(book,monsters={}) {
    const node=book.nodes.find(n=>n.id===(selections.get(book)||book.entry_node_id))||book.nodes[0];
    if(!node)return '<p>尚无可预览节点</p>';
    let text=`<div class="preview-card"><p class="helper">作者预览 · 包含完整分支与秘密，不会推进冒险</p><h2>${esc(node.title)}</h2><p>${esc(kinds[node.kind])}</p>`;
    if(node.kind==='frontier') {
      const c=node.continuation||{};
      text+=`<p>待续写出口，不作为空场景进入。</p><p>${esc(c.summary)}</p><h4>未解线索</h4>${(c.unresolved_threads||[]).map(t=>`<p>${esc(t)}</p>`).join('')}<h4>续写约束</h4>${(c.constraints||[]).map(t=>`<p>${esc(t)}</p>`).join('')}<p>续写失败：${esc(book.nodes.find(n=>n.id===c.fallback_scene_id)?.title||'留在原场景')}</p>`;
    } else text+=`<p class="graph-preview-prose">${esc(node.text)}</p><p>${esc(node.objective)}</p>`;
    if(node.kind==='key')text+=`<h4>推进条件</h4><p>${esc(conditionText(book,node.advancement_condition))}</p><h4>失败后果</h4><p>${esc(node.failure_consequences)}</p>`;
    if(node.kind==='ending')text+=`<p>适用条件：${esc(conditionText(book,node.ending_condition))}</p>`;
    if(node.monster_ids?.length)text+=`<p>预设怪兽：${node.monster_ids.map(id=>esc(monsters[id]||id)).join('、')}</p>`;
    for(const edge of book.edges.filter(e=>e.from===node.id))text+=`<div class="preview-scene"><strong>→ ${esc(book.nodes.find(n=>n.id===edge.to)?.title||edge.to)}</strong><p>${esc(edge.outcome)}</p><p>${esc(edge.legacy_action_id?`原行动 ${edge.legacy_action_id} · ${{success:'成功',failure:'失败',direct:'直接'}[edge.legacy_result]}`:conditionText(book,edge.condition))}</p><p>${esc({public:'公开',known:'知情者可见',secret:'仅 DM'}[edge.visibility])}</p></div>`;
    return text+'</div>';
  }
  function diff(before,after,limit=200) {
    const changes=[];let truncated=false;
    function add(path,kind,left,right) {
      if(changes.length>=limit){truncated=true;return;}
      changes.push({path,kind,before:left,after:right});
    }
    function walk(left,right,path=[],depth=0) {
      if(truncated||Object.is(left,right))return;
      if(depth>40){add(path,'changed',left,right);return;}
      if(left===undefined){add(path,'added',undefined,right);return;}
      if(right===undefined){add(path,'removed',left,undefined);return;}
      if(Array.isArray(left)&&Array.isArray(right)) {
        const identified=rows=>rows.every(row=>row&&typeof row==='object'&&typeof row.id==='string')&&new Set(rows.map(r=>r.id)).size===rows.length;
        if((left.length||right.length)&&identified(left)&&identified(right)) {
          const oldIds=left.map(r=>r.id),newIds=right.map(r=>r.id);
          const oldCommon=oldIds.filter(id=>newIds.includes(id)),newCommon=newIds.filter(id=>oldIds.includes(id));
          if(oldCommon.some((id,i)=>id!==newCommon[i]))add([...path,'顺序'],'order_changed',oldIds,newIds);
          const oldMap=new Map(left.map(r=>[r.id,r])),newMap=new Map(right.map(r=>[r.id,r]));
          for(const id of new Set([...oldMap.keys(),...newMap.keys()]))walk(oldMap.get(id),newMap.get(id),[...path,id],depth+1);
        } else for(let i=0;i<Math.max(left.length,right.length);i++)walk(left[i],right[i],[...path,i],depth+1);
      } else if(left&&right&&!Array.isArray(left)&&!Array.isArray(right)&&typeof left==='object'&&typeof right==='object') {
        for(const key of [...new Set([...Object.keys(left),...Object.keys(right)])].sort())walk(left[key],right[key],[...path,key],depth+1);
      } else add(path,'changed',left,right);
    }
    walk(before,after);return {changes,truncated};
  }
  function diffHtml(before,after) {
    const result=diff(before,after);
    const display=value=>value===undefined?'—':JSON.stringify(value,null,2);
    return `<p>${result.changes.length} 项差异${result.truncated?'（已达显示上限，请同时核对原始数据）':''}</p>${result.changes.map(change=>`<section class="graph-diff-entry"><h4>${esc(change.path.join(' / '))} · ${esc({added:'新增',removed:'移除',changed:'修改',order_changed:'调整顺序'}[change.kind])}</h4><div class="graph-diff-values"><div><strong>历史版本</strong><pre>${esc(display(change.before))}</pre></div><div><strong>当前草稿</strong><pre>${esc(display(change.after))}</pre></div></div></section>`).join('')||'<p>内容相同。</p>'}`;
  }
  function locate(book,issue) {
    let path=issue.match(/(?:nodes|edges|fact_definitions|milestones|npc_goals)\.\d+(?:\.[a-z_]+|\.\d+)*/)?.[0];
    let index=-1;
    if(path?.startsWith('nodes.'))index=Number(path.split('.')[1]);
    if(path?.startsWith('edges.'))index=book.nodes.findIndex(n=>n.id===book.edges[Number(path.split('.')[1])]?.from);
    if(!path) {
      const boundary=(word,id)=>new RegExp(`${word} ${id.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')}(?![A-Za-z0-9_-])`).test(issue);
      index=book.nodes.findIndex(n=>boundary('节点',n.id)||boundary('末端',n.id)||issue.startsWith(n.id+' '));
      if(index>=0)path=`nodes.${index}.title`;
      else {
        const ei=book.edges.findIndex(e=>boundary('边',e.id)||issue.startsWith(e.id+' '));
        if(ei>=0){path=`edges.${ei}.to`;index=book.nodes.findIndex(n=>n.id===book.edges[ei].from);}
      }
    }
    if(index>=0&&book.nodes[index])selections.set(book,book.nodes[index].id);
    if(path&&/^nodes\.\d+$/.test(path))path+='.title';
    if(path&&/^edges\.\d+$/.test(path))path+='.to';
    if(path&&/^(?:fact_definitions|milestones|npc_goals)\.\d+$/.test(path))path+='.id';
    if(!path&&issue.includes('入口'))path='entry_node_id';
    return path||null;
  }
  function focus(root,path) {
    if(!path)return false;
    const control=[...root.querySelectorAll('[data-g-field],[data-g-op],[data-g-cond-ref]')].find(el=>el.dataset.gField===path||el.dataset.gOp===path||el.dataset.gCondRef===path.replace(/\.ref$/,''));
    if(!control)return false;
    for(let parent=control.parentElement;parent;parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;
    control.scrollIntoView?.({behavior:'smooth',block:'center'});control.focus();return true;
  }
  window.HexboundStoryEditor={render,bind,navigation,preview,diff,diffHtml,locate,focus};
})();
