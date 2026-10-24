/* Public route-wait UI states; backend authority is covered by real HTTP tests. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const dom = new JSDOM('<main id="app"></main>',{url:'http://localhost',runScripts:'outside-only'});
const w=dom.window;
w.fetch=()=>new Promise(()=>{});
const source=fs.readFileSync('frontend/app.js','utf8');
w.eval(source+`
window.routeFixture = (status, combat=false) => {
  room={status:'playing',route_wait:status?{status}:null,combat:combat?{active:true,turn_actor_id:'other'}:null,director_proposals:[],free_actions:{}};
  session={member_id:'leader'};catalog={};connected=true;busy=false;
  app.innerHTML='<div class="composer"><div class="actions"><button id="existing-check">现有行动</button></div></div>';
  installActionEntries();
};
window.routeDisabled = id => actionDisabledReason({id});
`);
const texts={waiting:'路线正在准备中',ready_for_review:'路线已准备好',review_required:'路线条件已变化'};
for(const [status,text] of Object.entries(texts)){
  w.routeFixture(status);
  assert(w.document.querySelector('.route-wait[role=status]').textContent.includes(text));
  assert(w.document.querySelector('#existing-check'),'Waiting must keep current actions');
  assert(!w.document.querySelector('#existing-check').disabled);
}
w.routeFixture(null);assert(!w.document.querySelector('.route-wait'));
w.routeFixture('<script>hidden-contract</script>');assert(!w.document.querySelector('.route-wait'));
w.routeFixture('waiting',true);
assert.equal(w.routeDisabled('story-cancel'),'');
assert(w.routeDisabled('attack').includes('等待你的回合'));
console.log('Route wait DOM passed: waiting/ready/review states, current actions preserved, cancel outside turn, unknown status hidden.');
dom.window.close();
