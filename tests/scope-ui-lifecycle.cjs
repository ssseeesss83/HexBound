const assert=require('node:assert/strict'), fs=require('node:fs'), path=require('node:path'), vm=require('node:vm');
const {JSDOM}=require('jsdom');
const source=fs.readFileSync(path.resolve(__dirname,'../frontend/app.js'),'utf8');
const start=source.indexOf('async function confirmLevelUp(event)'), end=source.indexOf('async function spellManagementDialog()',start);
async function run(){
  const dom=new JSDOM('<form><p id="growth-error"></p><button type="submit">Upgrade</button></form>');
  const form=dom.window.document.querySelector('form');
  let complete, reloads=0, refreshes=0;
  const original={owner:true,loading:false,mutationPending:false,scope:'old',overlay:dom.window.document.body,advancement:{required_choices:{}}};
  const context={sheetState:original,activeTextScope:'old',busy:false,connected:true,room:{status:'playing'},FormData:dom.window.FormData,
    $:(selector,root)=>root.querySelector(selector),command:()=>new Promise(resolve=>complete=resolve),toast:()=>{},
    reloadCharacterSheet:async()=>{reloads++;},refreshSheetVitals:()=>{refreshes++;}};
  vm.createContext(context);vm.runInContext(source.slice(start,end),context);
  const pending=context.confirmLevelUp({preventDefault(){},currentTarget:form});
  assert.equal(original.mutationPending,true);
  // A real scope update destroys the old sheet while its mutation awaits a receipt.
  context.sheetState=null;context.activeTextScope='new';form.remove();complete(true);
  await pending;
  assert.equal(original.mutationPending,false);
  assert.equal(reloads,0,'late mutation cannot reload the old character sheet');
  assert.equal(refreshes,0,'late mutation cannot refresh revoked controls');
  assert.equal(context.sheetState,null);
  dom.window.close();
  await chatLifecycle();
  console.log('PASS: late character growth and chat respect scope revocation; chat preserves newer drafts and action locks.');
}
async function chatLifecycle(){
  const start=source.indexOf('async function chatCommand(text)'),end=source.indexOf('async function command(',start);
  for(const scenario of ['current','revoked','reentered']){
    const revoked=scenario!=='current';
    const dom=new JSDOM('<textarea id="intent">sent message</textarea>');
    let finish, renders=0;
    const context={session:{room_id:'r',member_id:'p'},room:{id:'r',version:1,action_revision:4,scene_instance_id:'s',membership_epoch:1},
      activeTextScope:'old',chatRequest:null,busy:true,connected:true,draft:'',newCommandId:()=> 'chat-request',
      $:selector=>dom.window.document.querySelector(selector),api:()=>new Promise(resolve=>finish=resolve),
      renderRoom:()=>{renders++;},toast:()=>{}};
    vm.createContext(context);vm.runInContext(source.slice(start,end),context);
    const pending=context.chatCommand('sent message');
    assert.equal(context.busy,true);
    dom.window.document.querySelector('#intent').value='new unsent draft';
    if(revoked){
      context.chatRequest='new-request';context.room={id:'r',version:10};
      if(scenario==='revoked')context.activeTextScope='new';
      else context.session={room_id:'r',member_id:'p'};
    }
    finish({room:{id:'r',version:2}});
    assert.equal(await pending,!revoked);
    assert.equal(context.busy,true,'chat never changes the action lock');
    assert.equal(dom.window.document.querySelector('#intent').value,'new unsent draft');
    assert.equal(context.room.version,revoked?10:2);
    assert.equal(context.chatRequest,revoked?'new-request':null,'old response cannot release a newer chat request');
    assert.equal(renders,revoked?1:2,'revoked response cannot redraw the old scope');
    dom.window.close();
  }
}
run().catch(error=>{console.error(error);process.exitCode=1;});
