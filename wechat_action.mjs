// Restricted, account-bound bridge. All mutations require a pinned local session.
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
const exec=promisify(execFile),root=import.meta.dirname;
let ws,session,stage='connect',mutationSent=false,seq=Math.floor(Math.random()*1e9);const pending=new Map();
function call(method,params={},sid='',timeout=22000){return new Promise((resolve,reject)=>{const id=++seq,key=`${sid}:${id}`;const timer=setTimeout(()=>{pending.delete(key);reject(Error(mutationSent?'操作请求后连接超时，请先核实状态':'微信连接未响应，尚未发出操作请求'))},timeout);pending.set(key,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params,...(sid?{sessionId:sid}:{})}))})}
async function evaluate(expression){const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true},session);if(r.exceptionDetails||!r.result?.value)throw Error('公众号页面执行失败');if(r.result.value.error)throw Error(r.result.value.error);return r.result.value}
const guard=String.raw`if(!/^weixin:\/\/resourceid\/Subscription(?:Profile|Disorder)\//.test(location.href)||!window.WeixinJSBridge)return resolve({error:'公众号页面已关闭'});`;
try{
 const input=JSON.parse(await new Promise(r=>{let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>r(s))}));
 if(!['health','list','check','unfollow','follow'].includes(input.action))throw Error('无效操作');
 const data=process.env.WECHAT_DATA_ROOT;if(!data)throw Error('执行环境未配置');
 const auth=JSON.parse(await readFile(resolve(data,'bridge-token.json'),'utf8')).token;
 async function identityGuard(){
  if(!input.identity?.profile_key||!input.identity?.session_key)throw Error('缺少账号绑定');
  const command=JSON.parse(process.env.WECHAT_IDENTITY_COMMAND||'[]');if(!command.length)throw Error('身份校验器未配置');
  const r=JSON.parse((await exec(command[0],command.slice(1),{timeout:10000,maxBuffer:8192})).stdout);
  if(r.error||r.profile_key!==input.identity.profile_key||r.session_key!==input.identity.session_key)throw Error('微信账号或登录会话已变化，请重新连接并核对清单');
 }
 ws=new WebSocket('ws://127.0.0.1:62000/?token='+encodeURIComponent(auth));
 ws.onmessage=e=>{let m;try{m=JSON.parse(e.data)}catch{return}const key=`${m.sessionId||''}:${m.id}`,p=pending.get(key);if(!p)return;clearTimeout(p.timer);pending.delete(key);m.error?p.reject(Error(m.error.message)):p.resolve(m.result)};
 await new Promise((r,j)=>{const t=setTimeout(()=>j(Error('连接服务未启动')),4000);ws.onopen=()=>{clearTimeout(t);r()};ws.onerror=()=>{clearTimeout(t);j(Error('连接服务不可用或身份验证失败'))}});
 const health=await call('LocalBridge.status',{},'',4000);
 if(input.action==='health'){console.log(JSON.stringify(health));}
 else{
  if(!health.connected)throw Error('请打开一个微信小程序并保留窗口，然后重新连接');
  await identityGuard();stage='targets';const {targetInfos}=await call('Target.getTargets',{},'',5000);
  const target=targetInfos.find(t=>/^weixin:\/\/resourceid\/SubscriptionDisorder\//.test(t.url))||targetInfos.find(t=>/^weixin:\/\/resourceid\/SubscriptionProfile\//.test(t.url));
  if(!target)throw Error('请在微信打开公众号页面，然后重新连接');
  ({sessionId:session}=await call('Target.attachToTarget',{targetId:target.targetId,flatten:true}));
  if(input.action==='list'){
   const result=await evaluate(`new Promise(resolve=>{${guard}const timer=setTimeout(()=>resolve({error:'读取公众号超时'}),16000);WeixinJSBridge.invoke('H5ExtTransfer',{cgi_cmdid:29175,url:'/cgi-bin/mmbiz-bin/bizattr/getbizlatestitemlisth5',scope:'subscriptions',req_json:JSON.stringify({scene:16,BaseRequest:{SessionKey:'',Uin:0,DeviceID:'',ClientVersion:0,DeviceType:'',Scene:0}})},r=>{clearTimeout(timer);try{const d=JSON.parse(r?.jsapi_resp?.resp_json||'{}');if(d.BaseResponse?.Ret!==0||!Array.isArray(d.list))return resolve({error:'微信未返回有效账号列表'});resolve({accounts:d.list.filter(a=>typeof a.biz_name==='string'&&a.biz_name).map(a=>({id:a.biz_name,name:a.nick_name||'',starred:!!a.top_flag}))})}catch{resolve({error:'账号列表解析失败'})}})})`);
   await identityGuard();console.log(JSON.stringify({...result,capturedAt:new Date().toISOString(),profile_key:input.identity.profile_key}));
  }else{
   if(typeof input.id!=='string')throw Error('无效账号');
   const profileDir=resolve(data,'accounts',input.identity.profile_key);
   const catalog=JSON.parse(await readFile(resolve(profileDir,'live-accounts-probe.json'),'utf8'));
   if(catalog.profile_key!==input.identity.profile_key||!catalog.accounts.some(a=>a.id===input.id))throw Error('账号不属于当前清单');
   async function allowed(){const w=JSON.parse(await readFile(resolve(profileDir,'whitelist.json'),'utf8'));if(w.ids.includes(input.id))throw Error('账号在白名单中');if(input.id==='gh_b4af18eac3d5')throw Error('该账号仅支持手机端取关')}
   const id=JSON.stringify(input.id);
   async function status(){stage=mutationSent?'verify':'check';return evaluate(`new Promise(resolve=>{${guard}const timer=setTimeout(()=>resolve({error:'关注状态查询超时'}),16000);WeixinJSBridge.invoke('H5ExtTransfer',{cgi_cmdid:5814,url:'/cgi-bin/mmbiz-bin/bizattr/bizprofilev2h5',scope:'subscriptions',webcgi_header:[],cgi_type:0,webcgi_method:1,req_json:JSON.stringify({BizUserName:${id},ActionType:0,PageSize:10,BizSessionID:Math.floor(Date.now()/1000),Scene:207,UsePlainTopic:true,PreLoad:0,FilterPicText:true,BaseRequest:{SessionKey:'',Uin:0,DeviceID:'',ClientVersion:0,DeviceType:'',Scene:0}})},r=>{clearTimeout(timer);try{const d=JSON.parse(r?.jsapi_resp?.resp_json||'{}');if(d.BaseResponse?.Ret!==0||d.AccountInfo?.UserName!==${id}||![0,1,false,true].includes(d.BaseInfo?.IsSubscribed))return resolve({error:'无法核实当前账号关注状态'});resolve({id:d.AccountInfo.UserName,name:d.AccountInfo.NickName||'',subscribed:!!d.BaseInfo.IsSubscribed})}catch{resolve({error:'账号状态解析失败'})}})})`)}
   if(input.action==='follow'&&!catalog.accounts.some(a=>a.id===input.id&&(a.was_unfollowed||a.subscribed===false)))throw Error('只能恢复本机取关记录中的账号');
   if(input.action==='unfollow')await allowed();const before=await status();await identityGuard();
   if(input.action==='check')console.log(JSON.stringify(before));
   else if(input.action==='follow'&&before.subscribed)console.log(JSON.stringify({...before,status:'already_followed',mutation_sent:false}));
   else if(input.action==='unfollow'&&!before.subscribed)console.log(JSON.stringify({...before,status:'already_unfollowed',mutation_sent:false}));
   else{
    if(input.action==='unfollow')await allowed();await identityGuard();const restoring=input.action==='follow';stage=restoring?'follow':'unfollow';mutationSent=true;
    const method=restoring?'quicklyAddBrandContact':'Unsubscribe';const params=restoring?{username:input.id,webtype:'1',scene:'241'}:{userName:input.id};
    const ack=await evaluate(`new Promise(resolve=>{${guard}const timer=setTimeout(()=>resolve({error:'操作回执超时，请先核实状态'}),16000);WeixinJSBridge.invoke(${JSON.stringify(method)},${JSON.stringify(params)},r=>{clearTimeout(timer);resolve({ack:r?.err_msg||''})})})`);
    if(ack.ack.toLowerCase()!==(method+':ok').toLowerCase())throw Error('微信未确认操作：'+ack.ack);
    let after;for(const delay of [0,350,750,1500,2000]){if(delay)await new Promise(r=>setTimeout(r,delay));await identityGuard();after=await status();if(after.subscribed===restoring)break}
    await identityGuard();if(after.subscribed!==restoring)throw Error('微信返回成功，但关注状态未达到预期，已暂停');
    console.log(JSON.stringify({...after,status:restoring?'followed':'unfollowed',mutation_sent:true,ack:ack.ack}));
   }
  }
 }
}catch(e){console.log(JSON.stringify({error:e.message,stage,mutation_sent:mutationSent}));process.exitCode=1}
finally{if(session&&ws?.readyState===WebSocket.OPEN)ws.send(JSON.stringify({id:++seq,method:'Target.detachFromTarget',params:{sessionId:session}}));for(const p of pending.values())clearTimeout(p.timer);ws?.close()}
