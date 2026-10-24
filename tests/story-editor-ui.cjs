/* Interactive author graph controls use the same backend contract for acceptance. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {spawnSync} = require('node:child_process');
const {JSDOM} = require('jsdom');
const python = process.env.PYTHON || 'python';
const env = {...process.env,PYTHONUTF8:'1'};
const fixture = spawnSync(python,['-c',
  "import json,runpy; from backend.story_graph import parse_book; print(json.dumps(parse_book(runpy.run_path('tests/test_story_graph.py')['sparse']())))"],{encoding:'utf8',env});
assert.equal(fixture.status,0,fixture.stderr);
const book = JSON.parse(fixture.stdout);
const dom = new JSDOM('<main id="editor"></main>',{runScripts:'outside-only'});
const w = dom.window, root = w.document.querySelector('main');
w.confirm = ()=>true; w.alert = text=>{throw new Error(text);};
w.eval(fs.readFileSync('frontend/story-editor.js','utf8'));
const editor = w.HexboundStoryEditor;
let modifications = 0;
function render() {
  root.innerHTML = editor.render(book,{guard:'Guard',wolf:'Wolf'});
  editor.bind(root,book,(redraw,modified=true)=>{if(modified)modifications++;if(redraw)render();});
}
const q = selector=>{const node=root.querySelector(selector);assert.ok(node,selector);return node;};
const click = selector=>q(selector).click();
function field(path,value,event='change') {
  const node=q(`[data-g-field="${path}"]`);
  if(node.type==='checkbox')node.checked=value;else node.value=value;
  node.dispatchEvent(new w.Event(event,{bubbles:true}));
}
function lines(path,value){const node=q(`[data-g-lines="${path}"]`);node.value=value;node.dispatchEvent(new w.Event('input',{bubbles:true}));}
render();
const before=modifications;
click('[data-g-select="follow"]');
assert.equal(modifications,before,'Navigating must not mark draft dirty');
field('nodes.1.continuation.summary','Players follow the courier down the side street.','input');
lines('nodes.1.continuation.unresolved_threads','Who hired the courier?\nWhere is the lens?');
assert.equal(book.nodes[1].continuation.unresolved_threads.length,2);
click('[data-g-list="nodes.1.continuation.allowed_monster_ids"][value="wolf"]');
assert.ok(book.monster_ids.includes('wolf'),'Selected monster must enter package dependencies');
q('[data-g-open="declarations"]').open=true;
field('fact_definitions.0.id','lens-recovered');
assert.ok(q('[data-g-open="declarations"]').open,'Editing a declaration must preserve expanded panel');
assert.deepEqual(book.nodes[1].continuation.confirmed_fact_ids,['lens-recovered']);
assert.equal(book.nodes[0].advancement_condition.children[0].ref,'lens-recovered');
click('[data-g-add-declaration="fact_definitions"]');
field('fact_definitions.1.value_type','integer');
field('fact_definitions.1.initial',7,'input');
assert.equal(book.fact_definitions[1].initial,7);
assert.equal(typeof book.fact_definitions[1].initial,'number');
field('fact_definitions.1.visibility','dm_secret');
assert.equal(book.fact_definitions[1].visibility,'dm_secret');
click('[data-g-select="dock"]');
field('nodes.0.id','harbor');
assert.equal(book.entry_node_id,'harbor');
assert.equal(book.edges[0].from,'harbor');
assert.equal(book.nodes[1].continuation.fallback_scene_id,'harbor');
field('nodes.0.advancement_condition.children.0.value','false');
assert.equal(book.nodes[0].advancement_condition.children[0].value,false);
// A rejected intermediate ID must not change any existing route or dirty state.
const identitySnapshot=JSON.stringify(book),dirtySnapshot=modifications;
field('nodes.0.id','follow');
assert.equal(JSON.stringify(book),identitySnapshot);
assert.equal(modifications,dirtySnapshot);
assert.ok(root.textContent.includes('不能与同类条目重复'));
field('nodes.0.id','harbor-fixed');
assert.equal(book.edges[0].to,'follow');
assert.equal(book.edges[0].from,'harbor-fixed');
const factSnapshot=JSON.stringify(book);
field('fact_definitions.0.id',book.fact_definitions[1].id);
assert.equal(JSON.stringify(book),factSnapshot);
field('fact_definitions.0.value_type','integer');
assert.equal(book.nodes[0].advancement_condition.children[0].value,false,'Type change must not silently reinterpret old comparison');
assert.ok(root.textContent.includes('比较值与事实的新类型不符'));
field('nodes.0.advancement_condition.children.0.value','7','input');
assert.equal(book.nodes[0].advancement_condition.children[0].value,7);
// Add a scene, connect it, then turn its empty terminal into an ending.
click('#graph-add-node');
const added=book.nodes.at(-1);
field(`nodes.2.kind`,'ending');
field('nodes.2.text','Dawn breaks.','input');
click('[data-g-select="harbor-fixed"]');
click('#graph-add-edge');
field('edges.1.to',added.id);
const conditionSelect=q('[data-g-op="edges.1.condition"]');
conditionSelect.value='milestone_state';conditionSelect.dispatchEvent(new w.Event('change',{bubbles:true}));
field('edges.1.condition.state','failed');
assert.equal(book.edges[1].condition.state,'failed');
// All author edits above must still pass the independent server contract.
const accepted=spawnSync(python,['-c',
  'import json,sys; from backend.story_graph import parse_book; parse_book(json.load(sys.stdin)); print("accepted")'],
  {encoding:'utf8',input:JSON.stringify(book),env});
assert.equal(accepted.status,0,accepted.stderr);
// Finite navigation for a merge and a cycle; all injected text remains escaped.
book.edges.push({...book.edges[1],id:'merge',condition:null});
book.edges.push({...book.edges[1],id:'loop',to:'harbor-fixed',condition:null});
book.nodes[0].title='<img src=x onerror="throw 1">';
render();
assert.equal(root.querySelector('img'),null);
assert.ok(root.textContent.includes('汇合引用'));
assert.ok(root.textContent.includes('返回引用'));
assert.ok(root.querySelectorAll('[data-g-select]').length<15);
const originalBeforeDiff=JSON.stringify(book),reordered=JSON.parse(JSON.stringify(book));
reordered.nodes.reverse();
const onlyOrder=editor.diff(book,reordered);
assert.equal(onlyOrder.changes.length,1);
assert.equal(onlyOrder.changes[0].kind,'order_changed');
const mixedOrder=editor.diff({nodes:[{id:'a'},{id:'b'}]},{nodes:[{id:'b'},{id:'a'},{id:'c'}]});
assert.deepEqual(Array.from(mixedOrder.changes,c=>c.kind),['order_changed','added']);
const removeAndOrder=editor.diff({nodes:[{id:'a'},{id:'b'},{id:'c'}]},{nodes:[{id:'c'},{id:'b'}]});
assert.deepEqual(Array.from(removeAndOrder.changes,c=>c.kind),['order_changed','removed']);
reordered.nodes.find(node=>node.id===book.nodes[0].id).text='Changed prose <script>bad()</script>';
const compared=editor.diff(book,reordered);
assert.ok(compared.changes.some(change=>change.path.join('/')===`nodes/${book.nodes[0].id}/text`));
assert.equal(JSON.stringify(book),originalBeforeDiff,'Read-only diff must not mutate draft');
const diffRoot=w.document.createElement('div');diffRoot.innerHTML=editor.diffHtml(book,reordered);
assert.equal(diffRoot.querySelector('script'),null);
assert.ok(diffRoot.textContent.includes('<script>bad()</script>'));
const bounded=editor.diff({values:[]},{values:Array.from({length:20},(_,i)=>i)},3);
assert.equal(bounded.changes.length,3);assert.ok(bounded.truncated);
book.nodes.push({...book.nodes[0],id:'harbor-fixed-side',title:'Specific node',legacy_actions:[]});
const location=editor.locate(book,'节点 harbor-fixed-side 无法到达结局或续写出口');
assert.equal(location,`nodes.${book.nodes.length-1}.title`,'Prefix IDs must not select another node');
render();assert.ok(editor.focus(root,location));
assert.equal(w.document.activeElement.dataset.gField,location);
book.nodes.pop();click('[data-g-select="follow"]');
const previewRoot=w.document.createElement('div');previewRoot.innerHTML=editor.preview(book,{guard:'Guard',wolf:'Wolf'});
assert.ok(previewRoot.textContent.includes('待续写出口，不作为空场景进入'));
assert.ok(previewRoot.textContent.includes('Who hired the courier?'));
assert.equal(previewRoot.querySelector('img'),null);
const legacyFixture=spawnSync(python,['-c',
  "import json; from backend.studio import seed_items; from backend.story_graph import migrate_legacy; print(json.dumps(migrate_legacy(next(c for k,c in seed_items() if k=='scenario'))))"],{encoding:'utf8',env});
assert.equal(legacyFixture.status,0,legacyFixture.stderr);
for(const key of Object.keys(book))delete book[key];
Object.assign(book,JSON.parse(legacyFixture.stdout));render();
click('[data-g-select="dock"]');
field('edges.0.to','stairs');
assert.equal(book.nodes[0].legacy_actions[0].success_node_id,'stairs');
const legacySnapshot=JSON.stringify(book);
w.confirm=()=>false;click('[data-g-convert="0"]');
assert.equal(JSON.stringify(book),legacySnapshot,'Cancel must preserve original action and both outlets');
w.confirm=()=>true;click('[data-g-convert="0"]');
assert.equal(book.nodes[0].legacy_actions.length,1);
assert.equal(book.edges[0].legacy_action_id,null);
assert.equal(book.edges[1].legacy_action_id,null);
assert.equal(book.edges[2].legacy_action_id,'ask-boatman');
const converted=spawnSync(python,['-c',
  'import json,sys; from backend.story_graph import parse_book; parse_book(json.load(sys.stdin))'],{encoding:'utf8',input:JSON.stringify(book),env});
assert.equal(converted.status,0,converted.stderr);
const challengeFixture=spawnSync(python,['-c',
  "import json,runpy,sys; sys.path.insert(0,'tests'); from backend.story_graph import parse_book; print(json.dumps(parse_book(runpy.run_path('tests/test_story_challenges.py')['authored']())))"],{encoding:'utf8',env});
assert.equal(challengeFixture.status,0,challengeFixture.stderr);
const authored=JSON.parse(challengeFixture.stdout);
function renderChallenges(){root.innerHTML=editor.render(authored,{guard:'Guard'});editor.bind(root,authored,redraw=>{if(redraw)renderChallenges();});}
renderChallenges();
field('nodes.0.place_id','shared-wharf','input');
assert.equal(authored.nodes[0].place_id,'shared-wharf');
field('fact_definitions.1.id','weather-new');
assert.deepEqual(authored.nodes[0].challenges[0].evidence_fact_ids,['weather-new']);
field('fact_definitions.0.id','lens-new');
assert.equal(authored.nodes[0].challenges[0].success_effects[0].ref,'lens-new');
field('milestones.0.id','recover-new');
assert.equal(authored.nodes[0].challenges[0].success_effects[1].ref,'recover-new');
let warned=false;w.alert=()=>warned=true;
field('nodes.0.place_id','','input');
assert.equal(authored.nodes[0].place_id,null);
field('nodes.0.kind','frontier');
assert(warned && authored.nodes[0].kind==='key' && authored.nodes[0].challenges.length===1,'terminal conversion cannot drop native challenges');
field('nodes.0.place_id','shared-wharf','input');
const challengeAccepted=spawnSync(python,['-c',
  'import json,sys; from backend.story_graph import parse_book; parse_book(json.load(sys.stdin))'],{encoding:'utf8',input:JSON.stringify(authored),env});
assert.equal(challengeAccepted.status,0,challengeAccepted.stderr);
// A place-only scene must not become an invalid frontier with an invisible field.
authored.nodes[0].challenges=[];authored.nodes[0].kind='scene';authored.nodes[0].advancement_condition=null;authored.nodes[0].failure_consequences='';
authored.edges=authored.edges.filter(edge=>edge.from!==authored.nodes[0].id);
renderChallenges();warned=false;
field('nodes.0.kind','frontier');
assert(warned && authored.nodes[0].kind==='scene' && authored.nodes[0].place_id==='shared-wharf');
assert(root.querySelector('[data-g-field="nodes.0.place_id"]'),'rejected conversion retains visible place control');
console.log('Story editor DOM passed: sparse frontier, declaration scope, typed conditions, references, node/edge editing, finite tree and backend acceptance.');
dom.window.close();
