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
    assert(!m.params.expression.includes('H5ExtTransfer'),'request-only mode must not query subscription state');
    result={result:{value:{ack:ack??(action==='follow_request'?'quicklyAddBrandContact:ok':'unsubscribe:ok')}}};
   }else throw Error('Unexpected CDP method: '+m.method);
   queueMicrotask(()=>this.onmessage({data:JSON.stringify({id:m.id,sessionId:m.sessionId,result})}));
  }
  close(){this.readyState=3}
 }
 const context=vm.createContext({process:fakeProcess,console:{log:v=>output.push(JSON.parse(v))},WebSocket:Socket,setTimeout,clearTimeout,queueMicrotask});
 const modules={
  'node:fs/promises':{readFile:async path=>JSON.stringify(path.endsWith('bridge-token.json')?{token:'token'}:path.endsWith('whitelist.json')?{ids:protectedAccount?['account']:[]}:{profile_key:'fixture',accounts:[{id:'account',...(history?{was_unfollowed:true,subscribed:false}:{})}]})},
  'node:path':{resolve},
  'node:child_process':{execFile:(_command,_args,_options,callback)=>callback(null,JSON.stringify(identity),'')},
  'node:util':{promisify:()=>async()=>({stdout:JSON.stringify(identity),stderr:''})},
 };
 const mod=new vm.SourceTextModule(source,{context,initializeImportMeta(meta){meta.dirname='/fixture'}});
 await mod.link(specifier=>{const exports=modules[specifier];return new vm.SyntheticModule(Object.keys(exports),function(){for(const [key,value] of Object.entries(exports))this.setExport(key,value)},{context})});
 await mod.evaluate();return {result:output.at(-1),evaluations,exitCode:fakeProcess.exitCode};
}
let r=await run('follow_request');
assert.equal(r.result.status,'followed_unverified',JSON.stringify(r));assert.equal(r.result.subscribed,true);assert.equal(r.result.verified,false);assert.equal(r.evaluations.length,1);
assert(r.evaluations[0].includes('quicklyAddBrandContact'));assert(r.evaluations[0].includes('"username":"account"'));
r=await run('follow_request',{ack:'Unable to follow this Official Account as it has violated the regulations'});
assert.equal(r.exitCode,1);assert.equal(r.result.stage,'follow');assert.equal(r.result.mutation_sent,true);assert(r.result.error.includes('violated the regulations'));assert.equal(r.evaluations.length,1);
r=await run('follow_request',{history:false});assert.equal(r.exitCode,1);assert.equal(r.evaluations.length,0);
r=await run('unfollow_request');assert.equal(r.result.status,'unfollowed_unverified');assert.equal(r.result.subscribed,false);assert.equal(r.evaluations.length,1);
r=await run('unfollow_request',{protectedAccount:true});assert.equal(r.exitCode,1);assert.equal(r.evaluations.length,0);
console.log('PASS: fast follow/unfollow use one mutation call and no status queries; follow history, whitelist and explicit rejection handling verified');
