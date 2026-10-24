/* Real account cookies, DOM and WebSocket party controls on a disposable server. */
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os'), net = require('node:net');
const {spawn} = require('node:child_process');
const {JSDOM} = require('jsdom'), WebSocket = require('ws');
const root = path.resolve(__dirname,'..'), temporary = fs.mkdtempSync(path.join(os.tmpdir(),'hexbound-groups-'));
const windows=[], sockets=[], commits=[], heldWindows=new Set();
let server, base, logs='', dropCommits=0, truncateCommit=false, user=0;
let heldCharacterFor=null, releaseCharacter=null, characterCaptured=false;
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(check,label) {
  for(let n=0;n<250;n++) { if(await check()) return; await sleep(30); }
  throw Error(label+'\n'+windows.map(w=>w.document.querySelector('#toast')?.textContent).join('\n')+'\n'+logs);
}
async function page() {
  const registered=await fetch(base+'/api/auth/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'groupuser'+user++,password:'Group-controls-test-123!',display_name:'Adventurer'})});
  assert.equal(registered.status,201,await registered.clone().text());
  const cookie=registered.headers.get('set-cookie').split(';')[0];
  const dom=new JSDOM('<div id="app"></div><div id="toast" hidden></div>',{url:base,runScripts:'outside-only',pretendToBeVisual:true});
  const w=dom.window; windows.push(w);
  w.fetch=async(url,options={})=>{
    if(String(url).endsWith('/groups/commit')) commits.push(JSON.parse(options.body));
    const response=await fetch(new URL(url,base),{...options,headers:{...options.headers,Cookie:cookie}});
    if(heldCharacterFor===w && /\/api\/rooms\/[^/]+\/characters\//.test(String(url))) {
      characterCaptured=true; await new Promise(resolve=>releaseCharacter=resolve);
    }
    if(dropCommits > 0 && String(url).endsWith('/groups/commit')) {
      dropCommits--; await response.arrayBuffer(); throw new w.TypeError('Simulated lost commit response');
    }
    if(truncateCommit && String(url).endsWith('/groups/commit')) {
      truncateCommit=false; await response.arrayBuffer(); return new Response('{', {status:200});
    }
    return response;
  };
  w.WebSocket=class extends WebSocket {
    constructor(url) {super(url,{headers:{Cookie:cookie,Origin:base}});sockets.push(this);}
    set onmessage(handler) {super.onmessage=handler ? event=>{if(!heldWindows.has(w)) handler(event);} : null;}
  };
  w.eval(fs.readFileSync(path.join(root,'frontend/live-log.js'),'utf8'));
  w.eval(fs.readFileSync(path.join(root,'frontend/app.js'),'utf8'));
  await until(()=>w.document.querySelector('#create'),'home');
  return w;
}
function click(w,selector) {const node=w.document.querySelector(selector);assert(node,selector);assert(!node.disabled,selector+' disabled');node.click();}
function fill(w,name,value) {w.document.querySelector(`[name="${name}"]`).value=value;}
function submit(w,selector) {w.document.querySelector(selector).dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));}
async function groupDialog(w) {
  click(w,'#room-menu');click(w,'#party-groups');
  await until(()=>w.document.querySelector('#group-form'),'group form');
}
async function main() {
  const listener=net.createServer();await new Promise(resolve=>listener.listen(0,'127.0.0.1',resolve));
  const port=listener.address().port;await new Promise(resolve=>listener.close(resolve));base=`http://127.0.0.1:${port}`;
  server=spawn(process.env.PYTHON||'python',['-m','uvicorn','backend.app:app','--port',String(port)],{cwd:root,env:{...process.env,HEXBOUND_DB:path.join(temporary,'groups.sqlite3'),HEXBOUND_ALLOW_GUESTS:'0',HEXBOUND_ALLOW_REGISTRATION:'1',LLM_API_KEY:'',LLM_MODEL:''},stdio:['ignore','ignore','pipe']});
  server.stderr.on('data',chunk=>logs+=chunk);
  await until(async()=>{try{return(await fetch(base+'/api/health')).ok;}catch{return false;}},'server');
  const host=await page();click(host,'#create');fill(host,'player_name','Host');fill(host,'starting_level','1');submit(host,'#entry-form');
  await until(()=>host.document.querySelector('#start:not(:disabled)'),'created');
  const identity=JSON.parse(host.sessionStorage.getItem('hexbound-session'));
  const guest=await page();click(guest,'#join');fill(guest,'invite_code',identity.invite_code);fill(guest,'player_name','Guest');submit(guest,'#entry-form');
  await until(()=>host.document.querySelectorAll('.party-member').length===2 && guest.document.querySelector('.table-shell'),'joined');
  click(host,'#start');await until(()=>host.document.querySelector('[data-action="investigate"]:not(:disabled)'),'started');
  const guestId=JSON.parse(guest.sessionStorage.getItem('hexbound-session')).member_id;
  await groupDialog(host);
  click(host,`[name="member"][value="${guestId}"]`);submit(host,'#group-form');
  await until(()=>host.document.querySelector('#group-confirm'),'preview');
  assert.equal(host.document.querySelectorAll('.party-member').length,2,'prepare must not move members');
  assert(host.document.querySelector('#group-content').textContent.includes('Guest'));
  click(host,'#group-content [data-close]');
  assert.equal(host.document.querySelectorAll('.party-member').length,2,'cancel must not move members');
  await groupDialog(host);click(host,`[name="member"][value="${guestId}"]`);submit(host,'#group-form');
  await until(()=>host.document.querySelector('#group-confirm'),'second preview');
  click(guest,'[data-action="investigate"]');
  await until(()=>host.document.querySelector('[data-action="advance"]:not(:disabled)'),'gameplay changes prepared plan');
  click(host,'#group-confirm');
  await until(()=>host.document.querySelector('#group-form') && host.document.querySelector('#group-error')?.textContent.includes('过期'),'stale plan recovery');
  assert.equal(host.document.querySelectorAll('.party-member').length,2,'stale plan cannot move members');
  click(host,`[name="member"][value="${guestId}"]`);submit(host,'#group-form');
  await until(()=>host.document.querySelector('#group-confirm'),'fresh preview');
  guest.document.querySelector('#intent').value='UNSENT_OLD_SCOPE';
  click(guest,'[data-action-entry="free"]');
  guest.document.querySelector('#free-action-intent').value='OLD_ACTION_DRAFT';
  guest.document.querySelector('#free-action-intent').dispatchEvent(new guest.Event('input'));
  heldCharacterFor=guest;click(guest,`[data-sheet="${identity.member_id}"]`);
  await until(()=>characterCaptured,'old-scope character response held');
  const retryStart=commits.length;
  dropCommits=1;click(host,'#group-confirm');
  await until(()=>host.document.querySelectorAll('.party-member').length===1 && guest.document.querySelectorAll('.party-member').length===1,'split synchronized');
  await until(()=>commits.length===retryStart+2 && !host.document.querySelector('[data-group-dialog]'),'retry complete');
  assert.deepEqual(commits[retryStart],commits[retryStart+1],'retry uses exactly the same command and plan');
  assert.equal(guest.document.querySelector('#intent').value,'','scope change clears old draft');
  assert.equal(guest.document.querySelector('#free-action-intent').value,'','scope change clears action draft');
  assert(!guest.document.querySelector('#character-sheet'),'scope change closes character controls');
  heldCharacterFor=null;releaseCharacter();await sleep(30);
  assert(!guest.document.querySelector('#character-sheet'),'late character response cannot resurrect old scope');
  click(guest,'#room-menu');assert(!guest.document.querySelector('#party-groups'),'table control remains host only');click(guest,'[data-close]');
  guest.document.querySelector('#intent').value='PRIVATE_SIDE_CHAT';submit(guest,'#intent-form');
  await until(()=>guest.document.querySelector('#journal-log').textContent.includes('PRIVATE_SIDE_CHAT'),'side chat');
  assert(!host.document.querySelector('#journal-log').textContent.includes('PRIVATE_SIDE_CHAT'));
  await groupDialog(host);
  const operation=host.document.querySelector('[name="operation"]');operation.value='merge';operation.dispatchEvent(new host.Event('change'));
  submit(host,'#group-form');await until(()=>host.document.querySelector('#group-confirm'),'merge preview');click(host,'#group-confirm');
  await until(()=>host.document.querySelectorAll('.party-member').length===2 && guest.document.querySelectorAll('.party-member').length===2,'merged');
  await until(()=>!host.document.querySelector('[data-group-dialog]'),'merge response complete');
  assert(!host.document.querySelector('#journal-log').textContent.includes('PRIVATE_SIDE_CHAT'),'merge does not publish side chat');
  await groupDialog(host);click(host,`[name="member"][value="${guestId}"]`);submit(host,'#group-form');
  await until(()=>host.document.querySelector('#group-confirm'),'unknown result preview');
  const unknownStart=commits.length;heldWindows.add(host);dropCommits=2;click(host,'#group-confirm');
  await until(()=>host.document.querySelector('#group-confirm')?.textContent.includes('核对并重试'),'two responses lost');
  assert(!host.document.querySelector('#group-back'),'unknown outcome cannot discard original identity');
  assert(!host.document.querySelector('#group-content [data-close]'),'unknown outcome cannot offer cancellation');
  assert([...Array(host.sessionStorage.length)].some((_,i)=>host.sessionStorage.key(i).startsWith('hexbound-group:')),'pending identity survives dialog reload');
  assert.equal(host.document.querySelectorAll('.party-member').length,2,'host WS intentionally held');
  host.document.querySelector('[data-group-dialog]').remove();
  click(host,'#room-menu');click(host,'#party-groups');
  await until(()=>host.document.querySelector('#group-confirm')?.textContent.includes('核对并重试'),'reopened dialog restores pending identity');
  click(host,'#group-confirm');
  await until(()=>host.document.querySelectorAll('.party-member').length===1 && !host.document.querySelector('[data-group-dialog]'),'unknown result reconciled');
  assert.deepEqual(commits[unknownStart],commits[unknownStart+1]);assert.deepEqual(commits[unknownStart],commits[unknownStart+2]);
  heldWindows.delete(host);
  await groupDialog(host);const merging=host.document.querySelector('[name="operation"]');merging.value='merge';merging.dispatchEvent(new host.Event('change'));submit(host,'#group-form');
  await until(()=>host.document.querySelector('#group-confirm'),'restore combined group');click(host,'#group-confirm');
  await until(()=>host.document.querySelectorAll('.party-member').length===2 && !host.document.querySelector('[data-group-dialog]'),'combined group restored');
  await groupDialog(host);click(host,`[name="member"][value="${guestId}"]`);submit(host,'#group-form');
  await until(()=>host.document.querySelector('#group-confirm'),'truncated response preview');
  const truncatedStart=commits.length;heldWindows.add(host);truncateCommit=true;click(host,'#group-confirm');
  await until(()=>host.document.querySelector('#group-confirm')?.textContent.includes('核对并重试'),'truncated success body is unknown');
  assert(!host.document.querySelector('#group-back'));
  click(host,'#group-confirm');
  await until(()=>host.document.querySelectorAll('.party-member').length===1 && !host.document.querySelector('[data-group-dialog]'),'truncated body reconciled');
  assert.deepEqual(commits[truncatedStart],commits[truncatedStart+1]);heldWindows.delete(host);
  console.log('PASS: account/WS party controls, preview/cancel, stale-plan recovery, scoped chat/drafts, same-ID retries, double lost responses without WS, truncated body reconciliation.');
}
main().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>{
  sockets.forEach(socket=>{socket.onclose=null;socket.onmessage=null;socket.onerror=null;socket.onopen=null;socket.close();});windows.forEach(w=>w.close());
  const cleanup=()=>{assert.equal(path.dirname(path.resolve(temporary)),path.resolve(os.tmpdir()));assert(path.basename(temporary).startsWith('hexbound-groups-'));fs.rmSync(temporary,{recursive:true,force:true,maxRetries:10,retryDelay:100});};
  if(server) {server.once('exit',cleanup);server.kill();} else cleanup();
});
