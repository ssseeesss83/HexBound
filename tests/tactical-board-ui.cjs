const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const dom=new JSDOM('<main id="root"></main>',{runScripts:'outside-only'}),w=dom.window,d=w.document;
w.eval(fs.readFileSync('frontend/tactical-board.js','utf8'));
const room={status:'playing',party:[{id:'p',name:'旅人',hp:20,max_hp:25}],combat:{turn_actor_id:'p',enemies:[{id:'e',name:'地精',hp:8,max_hp:8}]},combat_capabilities:[],battlefield:{width:8,height:8,positions:{p:{x:1,y:1},e:{x:4,y:1}},walls:[{x:3,y:3}],difficult:[{x:2,y:4}],switches:[{id:'seal-a',x:2,y:1,active:true}],telegraphs:[{cells:[{x:4,y:1}],due:2}],reachable:[{x:2,y:2,cost:5}],visible_cells:[{x:4,y:1}],ranges:{attack:5},movement_remaining:30,phase:1}};
let moved=null,acted=null,selected=null;
const callbacks={render,move:p=>moved=p,intent:a=>acted=a,select:id=>selected=id,ability:(a,t)=>acted=[a,t]};
function render(){d.querySelector('#root').innerHTML=w.HexBoundTactical.render(room,'p','e');w.HexBoundTactical.bind(d,room,'p',callbacks);}
render();assert.equal(d.querySelectorAll('[data-grid-x]').length,64);assert(d.querySelector('.wall').disabled);assert(d.querySelector('.warning.hostile'));assert(d.querySelector('.reachable'));
d.querySelector('[data-grid-x="2"][data-grid-y="2"]').click();assert.equal(moved.x,2);assert.equal(moved.y,2);
d.querySelector('[data-grid-mode="act"]').click();d.querySelector('[data-grid-unit="e"]').click();assert.equal(selected,'e');assert.deepEqual(acted,['attack','e']);
assert(d.querySelector('button[aria-label*="下轮危险"]'));console.log('PASS tactical board: positions, walls, movement, selected target, attack intent and warnings');
