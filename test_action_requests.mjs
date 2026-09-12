import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import vm from 'node:vm';

// Exercise the production request-only bridge with a fake transport, never WeChat.
const source=await readFile(new URL('./wechat_action.mjs',import.meta.url),'utf8');
async function run(action,{ack,protectedAccount=false,history=true}={}){
 const identity={profile_key:'fixture',session_key:'session'},evaluations=[],output=[];
 const input={action,identity,id:'account'};
 const fakeProcess={env:{WECHAT_DATA_ROOT:'/fixture',WECHAT_IDENTITY_COMMAND:'["identity"]'},stdin:{on(event,handler){if(event==='data')queueMicrotask(()=>handler(JSON.stringify(input)));if(event==='end')queueMicrotask(handler)}}};
 class Socket {
  static OPEN=1;
  constructor(){this.readyState=1;queueMicrotask(()=>this.onopen())}
  send(raw){
   const m=JSON.parse(raw);let result;
   if(m.method==='Target.detachFromTarget')return;
   if(m.method==='LocalBridge.status')result={connected:true};
   else if(m.method==='Target.getTargets')result={targetInfos:[{url:'weixin://resourceid/SubscriptionDisorder/fixture',targetId:'target'}]};
   else if(m.method==='Target.attachToTarget')result={sessionId:'cdp-session'};
   else if(m.method==='Runtime.evaluate'){
    evaluations.push(m.params.expression);
    if(action==='list'){
     assert(m.params.expression.includes('cgi_cmdid:27493'));
     assert(m.params.expression.includes('request(0),request(1)'));
     result={result:{value:{accounts:[{id:'gh_subscription',name:'订阅号样例',starred:false,account_type:'subscription',service_type:0},{id:'gh_service',name:'服务号样例',starred:true,account_type:'service',service_type:1}],counts:{subscription:1,service:1,total:2}}}};
    }else{
     assert(!m.params.expression.includes('H5ExtTransfer'),'request-only mode must not query subscription state');
     result={result:{value:{ack:ack??(action==='follow_request'?'quicklyAddBrandContact:ok':'unsubscribe:ok')}}};
    }
   }else throw Error('Unexpected CDP method: '+m.method);
   queueMicrotask(()=>this.onmessage({data:JSON.stringify({id:m.id,sessionId:m.sessionId,result})}));
  }
  close(){this.readyState=3}
 }
 const context=vm.createContext({process:fakeProcess,console:{log:v=>output.push(JSON.parse(v))},WebSocket:Socket,setTimeout,clearTimeout,queueMicrotask});
 const modules={
  'node:fs/promises':{readFile:async path=>JSON.stringify(path.endsWith('bridge-token.json')?{token:'token'}:path.endsWith('whitelist.json')?{ids:protectedAccount?['account']:[]}:{profile_key:'fixture',accounts:[{id:'account',account_type:'service',service_type:1,...(history?{was_unfollowed:true,subscribed:false}:{})}]})},
  'node:path':{resolve},
  'node:child_process':{execFile:(_command,_args,_options,callback)=>callback(null,JSON.stringify(identity),'')},
  'node:util':{promisify:()=>async()=>({stdout:JSON.stringify(identity),stderr:''})},
 };
 const mod=new vm.SourceTextModule(source,{context,initializeImportMeta(meta){meta.dirname='/fixture'}});
 await mod.link(specifier=>{const exports=modules[specifier];return new vm.SyntheticModule(Object.keys(exports),function(){for(const [key,value] of Object.entries(exports))this.setExport(key,value)},{context})});
 await mod.evaluate();return {result:output.at(-1),evaluations,exitCode:fakeProcess.exitCode,normalizeContactLists:mod.namespace.normalizeContactLists};
}
let r=await run('list');
assert.equal(r.result.accounts.length,2);assert.deepEqual(r.result.counts,{subscription:1,service:1,total:2});
const normalized=JSON.parse(JSON.stringify(r.normalizeContactLists([
 {account_type:'subscription',service_type:0,list:[{bizusername:'gh_same',nick_name:'旧名称'},{bizusername:'gh_subscription',nick_name:'订阅号',top_flag:1}]},
 {account_type:'service',service_type:1,list:[{bizusername:'gh_service',nick_name:'服务号'},{bizusername:'gh_same',nick_name:'服务号优先'}]},
])));
assert.deepEqual(normalized,[
 {id:'gh_same',name:'服务号优先',starred:false,account_type:'service',service_type:1},
 {id:'gh_subscription',name:'订阅号',starred:true,account_type:'subscription',service_type:0},
 {id:'gh_service',name:'服务号',starred:false,account_type:'service',service_type:1},
]);
r=await run('follow_request');
assert.equal(r.result.status,'followed_unverified',JSON.stringify(r));assert.equal(r.result.subscribed,true);assert.equal(r.result.verified,false);assert.equal(r.evaluations.length,1);
assert(r.evaluations[0].includes('quicklyAddBrandContact'));assert(r.evaluations[0].includes('"username":"account"'));
r=await run('follow_request',{ack:'Unable to follow this Official Account as it has violated the regulations'});
assert.equal(r.exitCode,1);assert.equal(r.result.stage,'follow');assert.equal(r.result.mutation_sent,true);assert(r.result.error.includes('violated the regulations'));assert.equal(r.evaluations.length,1);
r=await run('follow_request',{history:false});assert.equal(r.exitCode,1);assert.equal(r.evaluations.length,0);
r=await run('unfollow_request');assert.equal(r.result.status,'unfollowed_unverified');assert.equal(r.result.subscribed,false);assert.equal(r.evaluations.length,1);
r=await run('unfollow_request',{protectedAccount:true});assert.equal(r.exitCode,1);assert.equal(r.evaluations.length,0);
console.log('PASS: subscription/service catalog mapping plus fast follow/unfollow request guards verified');
