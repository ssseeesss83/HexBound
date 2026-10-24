/* Review is separate from confirmation; uncertain replies retain the same ID. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<main id="app"></main>',{url:'http://localhost',runScripts:'outside-only'});
const w=dom.window;
w.fetch=()=>new Promise(()=>{});
w.eval(fs.readFileSync('frontend/app.js','utf8')+`
window.retryCalls=[];
window.retryMode='lost';
window.retryHeld=[];
window.retryFixture=()=>{
 room={id:'room1',version:1,status:'playing',scene_instance_id:'main',membership_epoch:1,action_revision:1,
       route_retry_available:true,director_proposals:[],free_actions:{}};
 session={room_id:'room1',member_id:'leader'};catalog={};connected=true;busy=false;
 routeRetryReview=null;routeRetryFlight=false;sessionStorage.clear();window.retryCalls=[];
 renderRoom=()=>{app.innerHTML='<div class="composer"><div class="actions"></div></div>';installActionEntries();};
 toast=()=>{};
 api=async(path,options)=>{
  const body=JSON.parse(options.body);window.retryCalls.push({path,body});
  if(window.retryMode==='hold')return new Promise(resolve=>window.retryHeld.push({resolve,path,body}));
  if(path.endsWith('/prepare'))return {plan_id:'a'.repeat(32),additional_attempts:1,expires_at:999};
  if(window.retryMode==='lost')throw new TypeError('Connection lost');
  if(window.retryMode==='incomplete')return {room:{...room,version:2}};
  return {room:{...room,version:2,route_retry_available:false},route_retry:{plan_id:body.plan_id,additional_attempts:1,replayed:true}};
 };
 renderRoom();
};
window.retryRerender=()=>renderRoom();
window.retrySetEpoch=()=>{room.membership_epoch++;renderRoom();};
window.retryMarkQueued=()=>{room.route_retry_available=false;renderRoom();};
window.retrySuccess=id=>({room:{...room,version:2,route_retry_available:false},route_retry:{plan_id:id,additional_attempts:1,replayed:true}});
`);
const click=async id=>{const button=w.document.getElementById(id);assert(button,id);await button.onclick();};
(async()=>{
 w.retryFixture();
 await click('route-retry');
 assert.equal(w.retryCalls.length,1);
 assert(w.document.getElementById('route-retry').textContent.includes('确认追加'));
 w.document.getElementById('route-retry-cancel').click();
 assert.equal(w.retryCalls.length,1,'Cancel must never confirm');
 await click('route-retry');
 await click('route-retry');
 assert.equal(w.retryCalls.length,3);
 assert(w.document.querySelector('.route-retry-error').textContent.includes('Connection lost'));
 w.retryMarkQueued();
 assert(w.document.getElementById('route-retry').textContent.includes('核对并重试'));
 w.retryMode='incomplete';await click('route-retry');
 assert(w.document.getElementById('route-retry'),'Incomplete success cannot discard original ID');
 w.retryMode='success';await click('route-retry');
 const confirmations=w.retryCalls.filter(call=>call.path.endsWith('/confirm'));
 assert.equal(confirmations.length,3);
 for(const call of confirmations)assert.deepEqual(Object.keys(call.body),['plan_id']);
 assert(confirmations.every(call=>call.body.plan_id==='a'.repeat(32)));
 assert(!w.document.querySelector('.route-retry'));
 assert.equal(w.sessionStorage.length,0);
 w.retryFixture();w.retryMode='lost';await click('route-retry');await click('route-retry');
 w.retrySetEpoch();
 assert.equal(w.sessionStorage.length,0,'Scope change must discard foreign pending UI');
 assert(w.document.getElementById('route-retry').textContent.includes('审核重新'));
 // A revoked request cannot own the new scope's UI or clear its newer flight.
 w.retryFixture();w.retryMode='hold';w.retryHeld=[];
 const oldPrepare=w.document.getElementById('route-retry').onclick();
 w.retrySetEpoch();assert(!w.document.getElementById('route-retry').disabled);
 const newPrepare=w.document.getElementById('route-retry').onclick();
 w.retryHeld[0].resolve({plan_id:'a'.repeat(32),additional_attempts:1});await oldPrepare;
 assert(w.document.getElementById('route-retry').disabled,'Old finally must not release new flight');
 w.retryHeld[1].resolve({plan_id:'b'.repeat(32),additional_attempts:1});await newPrepare;
 assert(!w.document.getElementById('route-retry').disabled);
 // A late successful old confirmation must preserve the new scope's pending ID.
 w.retryFixture();w.retryMode='success';await click('route-retry');
 w.retryMode='hold';w.retryHeld=[];
 const oldConfirm=w.document.getElementById('route-retry').onclick();
 w.retrySetEpoch();
 const prep=w.document.getElementById('route-retry').onclick();
 w.retryHeld[1].resolve({plan_id:'b'.repeat(32),additional_attempts:1});await prep;
 const newConfirm=w.document.getElementById('route-retry').onclick();
 w.retryHeld[0].resolve(w.retrySuccess('a'.repeat(32)));await oldConfirm;
 assert.equal(JSON.parse(w.sessionStorage.getItem('hexbound-route-retry:room1:leader')).plan.plan_id,'b'.repeat(32));
 assert(w.document.getElementById('route-retry').disabled);
 w.retryHeld[2].resolve(w.retrySuccess('b'.repeat(32)));await newConfirm;
 assert.equal(w.sessionStorage.length,0);
 console.log('Route retry DOM passed: explicit review/confirm, cancel, same-ID lost/incomplete response recovery and scope reset.');
 dom.window.close();
})().catch(error=>{console.error(error);dom.window.close();process.exitCode=1;});
