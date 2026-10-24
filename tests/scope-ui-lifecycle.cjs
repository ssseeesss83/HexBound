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
  dom.window.close();console.log('PASS: in-flight character growth completes safely after its scope and controls are revoked.');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
