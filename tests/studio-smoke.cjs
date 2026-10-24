/* DOM integration, not a substitute for browser layout / accessibility review.
 * Run from repository root: node tests/studio-smoke.cjs
 * Requires jsdom and the project's Python dependencies. No external LLM calls.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const { randomUUID } = require('node:crypto');
const { spawn } = require('node:child_process');
const { JSDOM } = require('jsdom');

const project = path.resolve(__dirname, '..');
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'hexbound-studio-'));
const adminToken = `test-${randomUUID()}`;
let server;
let dom;
let serverErrors = '';

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function eventually(predicate, message, timeout = 7000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (await predicate()) return;
    await delay(30);
  }
  throw new Error(message);
}
async function unusedPort() {
  const reservation = net.createServer();
  await new Promise(resolve => reservation.listen(0, '127.0.0.1', resolve));
  const port = reservation.address().port;
  await new Promise(resolve => reservation.close(resolve));
  return port;
}

async function run() {
  const port = await unusedPort();
  const origin = `http://127.0.0.1:${port}`;
  server = spawn(process.env.PYTHON || 'python', [
    '-m', 'uvicorn', 'backend.app:app', '--host', '127.0.0.1', '--port', String(port),
  ], {
    cwd: project,
    env: {
      ...process.env,
      HEXBOUND_ALLOW_GUESTS: "1",
      HEXBOUND_LEGACY_ADMIN_TOKEN: "1",
      HEXBOUND_DB: path.join(temporary, 'studio.sqlite'),
      HEXBOUND_ADMIN_TOKEN: adminToken,
      LLM_API_KEY: '',
      LLM_MODEL: '',
    },
    stdio: ['ignore', 'ignore', 'pipe'],
  });
  server.on('error', error => { serverErrors += error.message; });
  server.stderr.on('data', data => { serverErrors += data.toString(); });
  await eventually(async () => {
    try { return (await fetch(`${origin}/api/health`)).ok; } catch { return false; }
  }, 'Python server did not start', 15000);

  dom = new JSDOM('<div id="studio"></div><div id="studio-toast" hidden></div>', {
    url: `${origin}/studio.html`, runScripts: 'outside-only',
  });
  const w = dom.window;
  const document = w.document;
  const q = selector => document.querySelector(selector);
  const click = selector => {
    const element = q(selector);
    assert.ok(element, `Missing control: ${selector}`);
    assert.ok(!element.disabled, `Disabled control: ${selector}`);
    element.click();
  };
  const field = (name, value) => {
    const element = q(`[data-field="${name}"]`);
    assert.ok(element, `Missing field: ${name}`);
    assert.ok(!element.disabled, `Disabled field: ${name}`);
    element.value = value;
    element.dispatchEvent(new w.Event(element.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));
  };
  const submit = selector => q(selector).dispatchEvent(new w.Event('submit', { bubbles: true, cancelable: true }));
  const saved = () => eventually(() => q('#save')?.disabled && !q('#save-indicator')?.textContent, 'Draft did not save');
  const published = () => eventually(() => q('.detail-header .badge')?.textContent === '已发布', 'Version did not publish');
  w.fetch = (url, options) => fetch(new URL(url, origin), options);
  w.confirm = () => true;
  w.scrollTo = () => {};
  let exportedBlob;
  w.URL.createObjectURL = blob => { exportedBlob = blob; return 'blob:test-export'; };
  w.URL.revokeObjectURL = () => {};
  w.HTMLAnchorElement.prototype.click = () => {};
  w.eval(fs.readFileSync(path.join(project, 'frontend/story-editor.js'), 'utf8'));
  w.eval(fs.readFileSync(path.join(project, 'frontend/studio.js'), 'utf8'));

  await eventually(() => q('#auth'), 'Public catalog did not render');
  assert.equal(document.querySelectorAll('[data-open]').length, 5);
  assert.equal(q('#new-item'), null, 'Public users must not see editing controls');
  click('#auth');
  q('[name=token]').value = 'incorrect-token';
  submit('#auth-form');
  await eventually(() => q('#auth-error')?.textContent, 'Invalid admin token was not rejected');
  q('[name=token]').value = adminToken;
  submit('#auth-form');
  await eventually(() => q('#new-item'), 'Admin authentication did not unlock studio');

  click('#new-item');
  field('name', 'DOM 测试技能');
  field('id', 'dom-test-check');
  click('#save');
  await saved();
  click('#validate');
  await eventually(() => q('.valid-status'), 'Skill validation failed');
  click('#publish');
  await published();
  click('#export');
  await eventually(() => exportedBlob, 'Export did not produce a downloadable bundle');
  click('#duplicate');
  await eventually(() => q('.detail-header h1')?.textContent.includes('副本'), 'Duplicate did not create a draft');
  assert.equal(q('.detail-header .badge').textContent, '草稿');
  click('#archive');
  await eventually(() => q('.detail-header .badge')?.textContent === '已归档', 'Archive failed');
  q('#status-filter').value = 'archived';
  q('#status-filter').dispatchEvent(new w.Event('change', { bubbles: true }));
  assert.equal(document.querySelectorAll('[data-open]').length, 1);

  // Imports always create drafts; an exported package must contain no credentials.
  const exported = await fetch(`${origin}/api/studio/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${adminToken}` },
    body: JSON.stringify({ ids: ['dom-test-check'] }),
  }).then(response => response.json());
  assert.equal(exported.format, 'hexbound-content-v1');
  assert.ok(!JSON.stringify(exported).includes(adminToken));
  exported.items[0].data.id = 'dom-imported-check';
  exported.items[0].data.name = '导入的测试技能';
  click('#import');
  const contents = JSON.stringify(exported);
  Object.defineProperty(q('[name=file]'), 'files', { value: [{ size: contents.length, text: async () => contents }] });
  submit('#import-form');
  await eventually(() => !q('#import-form'), 'Import failed');

  click('[data-kind=monster]');
  click('#new-item');
  field('name', 'DOM 测试守卫');
  field('id', 'dom-test-monster');
  field('hp', '18');
  click('#save');
  await saved();
  click('#publish');
  await published();

  click('[data-kind=scenario]');
  click('#new-item');
  field('id', 'dom-test-book');
  field('name', 'DOM 测试分支剧情');
  field('nodes.0.text', '你进入一座熄灭的灯塔。');
  field('nodes.1.text', '灯重新亮起，远处传来归船的汽笛。');
  field('nodes.0.actions.0.skill_id', 'dom-test-check');
  field('nodes.0.actions.0.success_node_id', 'ending');
  field('nodes.0.actions.0.failure_node_id', 'ending');
  assert.ok(q('[data-ref=skill_ids][value=dom-test-check]').checked, 'Referenced skill must be included in dependencies');
  click('#save');
  await saved();
  click('#validate');
  await eventually(() => q('.valid-status'), 'Branch graph validation failed');
  click('#publish');
  await published();
  assert.ok(q('a[href="/?scenario=dom-test-book"]'), 'Published book needs an adventure launch link');
  click('[data-tab=history]');
  await eventually(() => document.querySelectorAll('.history-row').length === 2, 'History did not include create and publish');
  click('[data-history="1"]');
  click('#restore-version');
  await eventually(() => q('.detail-header .badge')?.textContent === '已发布 · 有新草稿', 'Historical restore must create a new unpublished draft');

  const publicSkills = await fetch(`${origin}/api/content?kind=skill`).then(response => response.json());
  assert.ok(!publicSkills.items.some(item => item.id === 'dom-imported-check'), 'Imported draft leaked into public catalog');
  const publicBooks = await fetch(`${origin}/api/content?kind=scenario`).then(response => response.json());
  assert.ok(publicBooks.items.some(item => item.id === 'dom-test-book'));
  assert.ok(publicBooks.items.every(item => !item.nodes && !item.draft), 'Public summaries must not reveal scenario nodes');
  click('[data-tab=edit]');
  click('#graph-draft');
  await eventually(() => q('[data-g-field=outline]'), 'Independent graph draft did not render');
  assert.ok(!q('#publish').disabled, 'Validated graph drafts must be publishable');
  assert.ok(q('#preview').textContent.includes('作者预览'), 'Graph draft preview failed');
  q('[data-g-field=outline]').value = '沿主线探索，允许临场续写。';
  q('[data-g-field=outline]').dispatchEvent(new w.Event('input', {bubbles:true}));
  click('#save');
  await saved();
  click('#validate');
  await eventually(() => q('.valid-status'), 'Graph draft validation failed');
  const graphData = JSON.parse(q('#raw-json').value);
  assert.equal(graphData.schema_version, 2);
  assert.equal(graphData.outline, '沿主线探索，允许临场续写。');
  assert.equal(graphData.nodes[0].legacy_actions.length, 1);
  assert.equal(graphData.edges.filter(edge => edge.from === graphData.entry_node_id).length, 2);
  click('[data-tab=history]');
  await eventually(() => document.querySelectorAll('.history-row').length === 2, 'Graph history revisions missing');
  click('[data-diff="1"]');
  assert.ok(q('.graph-diff-entry').textContent.includes('outline'), 'Stable graph diff did not show outline change');
  assert.ok(q('[role=dialog]').textContent.includes('沿主线探索，允许临场续写。'));
  click('[data-close]');
  click('[data-tab=edit]');
  const badGraph=JSON.parse(JSON.stringify(graphData));
  badGraph.edges[0].to='not-created';
  q('#raw-json').value=JSON.stringify(badGraph);
  click('#apply-json');click('#save');await saved();
  click('#validate');
  await eventually(() => q('[data-issue="0"]'), 'Graph issue was not rendered');
  click('[data-issue="0"]');
  assert.equal(document.activeElement.dataset.gField,'edges.0.to','Validation issue did not focus its edge target');
  q('[data-g-field="edges.0.to"]').value=graphData.edges[0].to;
  q('[data-g-field="edges.0.to"]').dispatchEvent(new w.Event('change',{bubbles:true}));
  click('#save');await saved();click('#validate');
  await eventually(() => q('.valid-status'), 'Graph correction did not restore valid topology');
  const oldBook = await fetch(`${origin}/api/studio/items/dom-test-book`, {
    headers: {Authorization: `Bearer ${adminToken}`},
  }).then(response => response.json());
  assert.equal(oldBook.published.schema_version, undefined, 'Creating graph draft rewrote original publication');
  const normalFetch=w.fetch;
  let releaseHistory;
  w.fetch=async(url,options)=>{
    const response=await normalFetch(url,options);
    if(String(url).includes(`/api/studio/items/${graphData.id}/history`))
      await new Promise(resolve=>{releaseHistory=resolve;});
    return response;
  };
  click('[data-tab=history]');
  await eventually(()=>releaseHistory,'History response gate was not reached');
  click('[data-kind=skill]');
  releaseHistory();w.fetch=normalFetch;
  await delay(50);
  assert.equal(q('#history-list'),null,'Late graph history resurrected a stale detail panel');
  assert.equal(q('.history-row'),null,'Late history leaked into another item category');
  click('[data-kind=scenario]');
  click('#new-graph');
  const nativeGraph=JSON.parse(q('#raw-json').value);
  assert.equal(nativeGraph.schema_version,2);
  assert.equal(nativeGraph.nodes.length,2);
  assert.equal(nativeGraph.nodes[1].kind,'frontier');
  assert.ok(q('.graph-tree'));
  click('#save');await saved();click('#validate');
  await eventually(()=>q('.valid-status'),'Native sparse template did not validate');
  const generatedGraph={...nativeGraph,id:'model-graph-dom',name:'模型稀疏草稿'};
  let submittedGeneration;
  w.fetch=async(url,options)=>{
    if(String(url)==='/api/studio/generate') {
      submittedGeneration=JSON.parse(options.body);
      return new Response(JSON.stringify({kind:'scenario',data:generatedGraph,issues:[],saved:false,published:false}),
                          {status:200,headers:{'Content-Type':'application/json'}});
    }
    return normalFetch(url,options);
  };
  click('#generate');
  assert.equal(q('[name=schema_version]').value,'2');
  q('[name=prompt]').value='只准备主线与续写出口';submit('#generate-form');
  await eventually(()=>q('.detail-header h1')?.textContent==='模型稀疏草稿','Generated graph did not load as unsaved draft');
  assert.equal(submittedGeneration.schema_version,2);
  assert.equal(q('#save').disabled,false);
  assert.equal((await fetch(`${origin}/api/studio/items/model-graph-dom`,{headers:{Authorization:`Bearer ${adminToken}`}})).status,404);
  let releaseGeneration;
  w.fetch=async(url,options)=>{
    if(String(url)==='/api/studio/generate') {
      await new Promise(resolve=>{releaseGeneration=resolve;});
      return new Response(JSON.stringify({kind:'scenario',data:{...generatedGraph,name:'迟到模型'},issues:[],saved:false,published:false}),
                          {status:200,headers:{'Content-Type':'application/json'}});
    }
    return normalFetch(url,options);
  };
  click('#generate');q('[name=prompt]').value='迟到草稿';submit('#generate-form');
  await eventually(()=>releaseGeneration,'Generation response gate was not reached');
  click('[data-close]');click('#new-graph');
  const replacementId=JSON.parse(q('#raw-json').value).id;
  releaseGeneration();await delay(50);w.fetch=normalFetch;
  assert.equal(JSON.parse(q('#raw-json').value).id,replacementId,'Late cancelled generation replaced a newer draft');
  console.log('Studio DOM integration passed: public/admin auth, card CRUD, validation, publish, duplicate, archive, bundle import/export, branch editor, history restore.');
}

run().catch(error => {
  console.error(error);
  if (serverErrors) console.error(serverErrors);
  process.exitCode = 1;
}).finally(async () => {
  dom?.window.close();
  if (server && server.exitCode === null) {
    server.kill('SIGTERM');
    await Promise.race([new Promise(resolve => server.once('exit', resolve)), delay(2000)]);
    if (server.exitCode === null) server.kill('SIGKILL');
  }
  fs.rmSync(temporary, { recursive: true, force: true });
});
