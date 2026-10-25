/* Pure view: highlighted tiles are hints; the server validates every intent. */
(() => {
  let mode='move', ability='attack';
  const escape = value => String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const key=p=>`${p.x},${p.y}`;
  function render(room,actor,selected){
    const b=room.battlefield;if(!b)return '';
    const actors=[...room.party,...room.combat.enemies];
    const enemies=new Set(room.combat.enemies.map(x=>x.id));
    const byCell=new Map(Object.entries(b.positions).map(([id,p])=>[key(p),actors.find(a=>a.id===id)]));
    const reachable=new Map(b.reachable.map(p=>[key(p),p.cost]));
    const walls=new Set(b.walls.map(key)), difficult=new Set(b.difficult.map(key)), visible=new Set(b.visible_cells.map(key));
    const warnings=new Set(b.telegraphs.flatMap(w=>w.cells.map(key)));
    const actions=[{id:'attack',label:'武器攻击'},...(room.combat_capabilities||[]).filter(a=>a.supported&&b.ranges[a.id]!=null)];
    if(!actions.some(a=>a.id===ability))ability='attack';
    const origin=b.positions[actor],range=b.ranges[ability]||0;
    let cells='';
    for(let y=0;y<b.height;y++)for(let x=0;x<b.width;x++){
      const k=`${x},${y}`,unit=byCell.get(k),seal=b.switches.find(s=>s.x===x&&s.y===y),reach=origin&&5*Math.max(Math.abs(x-origin.x),Math.abs(y-origin.y))<=range&&visible.has(k);
      const classes=['grid-tile',walls.has(k)?'wall':'',difficult.has(k)?'difficult':'',warnings.has(k)?'warning':'',mode==='move'&&reachable.has(k)?'reachable':'',mode==='act'&&reach?'in-range':'',unit?.id===actor?'self':enemies.has(unit?.id)?'hostile':unit?'friendly':'',unit?.id===selected?'selected':''];
      const label=`第${x+1}列第${y+1}行${unit?'，'+unit.name+' HP '+unit.hp+'/'+unit.max_hp:''}${walls.has(k)?'，墙体':''}${warnings.has(k)?'，下轮危险':''}${seal?'，装置'+(seal.active?'运转':'已关闭'):''}${reachable.has(k)?'，移动'+reachable.get(k)+'尺':''}`;
      cells+=`<button class="${classes.join(' ')}" data-grid-x="${x}" data-grid-y="${y}" data-grid-unit="${escape(unit?.id||'')}" aria-label="${escape(label)}" title="${escape(label)}" ${walls.has(k)?'disabled':''}><span>${unit?escape(unit.name.slice(0,2)):seal?(seal.active?'◈':'◇'):walls.has(k)?'▪':difficult.has(k)?'≈':''}</span>${unit?`<small>${unit.hp}</small>`:''}</button>`;
    }
    return `<section class="tactical-panel" aria-label="战棋场地"><div class="row between"><h2>战棋场地 · 每格5尺</h2><span>剩余移动 ${b.movement_remaining} 尺 · 阶段 ${b.phase}</span></div><p class="helper">${escape(b.briefing||'蓝色格可移动，金色格为当前能力射程。点击单位选目标；所有操作先审核确认。')}</p><div class="grid-toolbar"><button data-grid-mode="move" aria-pressed="${mode==='move'}">移动</button><button data-grid-mode="act" aria-pressed="${mode==='act'}">选择目标 / 施放</button><label>预览能力<select id="grid-ability">${actions.map(a=>`<option value="${escape(a.id)}" ${a.id===ability?'selected':''}>${escape(a.label)} · ${b.ranges[a.id]}尺</option>`).join('')}</select></label></div><div class="tactical-scroll"><div class="tactical-grid" style="--grid-columns:${b.width}" role="group" aria-label="位置与攻击范围">${cells}</div></div><p class="grid-legend">蓝：可移动　金：射程/视线　红：敌人　闪红：下轮危险　◈：可关闭装置</p><p class="helper">同一平面、单格单位；对角5尺，不穿墙角，无机会攻击。范围预览不保证命中；群体法术还须满足共同区域。</p></section>`;
  }
  function bind(root,room,actor,callbacks){
    if(!room.battlefield)return;
    root.querySelectorAll('[data-grid-mode]').forEach(b=>b.onclick=()=>{mode=b.dataset.gridMode;callbacks.render();});
    root.querySelector('#grid-ability').onchange=e=>{ability=e.target.value;mode='act';callbacks.render();};
    root.querySelectorAll('[data-grid-x]').forEach(b=>b.onclick=()=>{
      const p={x:Number(b.dataset.gridX),y:Number(b.dataset.gridY)},unit=b.dataset.gridUnit;
      if(room.combat.turn_actor_id!==actor||room.status!=='playing'){callbacks.select(unit);return;}
      const seal=room.battlefield.switches.find(s=>s.x===p.x&&s.y===p.y&&s.active);
      if(mode==='move'&&seal&&!unit){callbacks.intent('grid:'+seal.id);return;}
      if(mode==='move'&&!unit){callbacks.move(p);return;}
      if(unit){callbacks.select(unit);if(mode==='act')callbacks.ability(ability,unit);else callbacks.render();}
    });
  }
  window.HexBoundTactical={render,bind};
})();
