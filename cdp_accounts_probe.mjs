// Read-only probe for WMPFDebugger's loopback CDP relay. Node >= 22.
// Without --target, only list subscription targets; never navigate or unfollow.
import { mkdir, writeFile, chmod } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';

const args = process.argv.slice(2);
const target = args.length === 2 && args[0] === '--target' ? args[1] : null;
if (args.length && !target) throw new Error('Usage: node cdp_accounts_probe.mjs [--target ID]');
const output = resolve(import.meta.dirname, '.runtime/live-accounts-probe.json');
const ws = new WebSocket('ws://127.0.0.1:62000');
const pending = new Map();
let nextId = 800000;
function receive(message, sessionId = '') {
  if (message.method === 'Target.receivedMessageFromTarget') {
    receive(JSON.parse(message.params.message), message.params.sessionId);
    return;
  }
  const key = `${message.sessionId || sessionId}:${message.id}`;
  const entry = pending.get(key);
  if (!entry) return;
  clearTimeout(entry.timer);
  pending.delete(key);
  if (message.error) entry.reject(new Error(`CDP ${entry.method}: ${message.error.code} ${message.error.message}`));
  else entry.resolve(message.result);
}
ws.addEventListener('message', event => {
  try { receive(JSON.parse(event.data)); } catch { /* Ignore unrelated relay data. */ }
});
function command(method, params = {}, sessionId = '') {
  const id = ++nextId;
  const message = JSON.stringify({ id, method, params, ...(sessionId ? {sessionId} : {}) });
  return new Promise((resolve, reject) => {
    const key = `${sessionId}:${id}`;
    const timer = setTimeout(() => {
      pending.delete(key);
      reject(new Error(`Timed out: ${method}`));
    }, 20000);
    pending.set(key, { resolve, reject, timer, method });
    ws.send(message);
  });
}
const expression = String.raw`new Promise(resolve => {
  if (!/^weixin:\/\/resourceid\/Subscription(?:Profile|Disorder)\//.test(location.href))
    return resolve({error:'wrong_page'});
  const bridge=window.WeixinJSBridge;
  if(typeof bridge?.invoke!=='function') return resolve({error:'bridge_unavailable'});
  let done=false;
  const finish=value=>{if(!done){done=true;resolve(value)}};
  const timer=setTimeout(()=>finish({error:'bridge_timeout'}),12000);
  bridge.invoke('H5ExtTransfer',{
    cgi_cmdid:29175,
    url:'/cgi-bin/mmbiz-bin/bizattr/getbizlatestitemlisth5',scope:'subscriptions',
    req_json:JSON.stringify({scene:16,BaseRequest:{SessionKey:'',Uin:0,DeviceID:'',ClientVersion:0,DeviceType:'',Scene:0}})
  },response=>{
    clearTimeout(timer);
    try {
      const value=JSON.parse(response?.jsapi_resp?.resp_json||'{}');
      if(!Array.isArray(value.list))return finish({error:'no_list',responseKeys:Object.keys(value)});
      const accounts=value.list.filter(x=>typeof x.biz_name==='string'&&x.biz_name)
        .map(x=>({id:x.biz_name,name:typeof x.nick_name==='string'?x.nick_name:'',starred:!!x.top_flag}));
      const baseResponse=value.BaseResponse;
      if (typeof baseResponse?.Ret==='number' && baseResponse.Ret!==0)
        return finish({error:'api_return_'+baseResponse.Ret});
      const metadata={baseResponse,accountFields:Object.keys(value.list[0]||{})};
      const checkTimer=setTimeout(()=>finish({accounts,rawCount:value.list.length,responseKeys:Object.keys(value),metadata,nativeCheck:{error:'timeout'}}),8000);
      bridge.invoke('GetSubscriptionList',{},native=>{
        clearTimeout(checkTimer);
        const list=native?.subscriptionUserList;
        const ids=Array.isArray(list)?list.map(x=>typeof x==='string'?x:x?.name).filter(x=>typeof x==='string'):null;
        finish({accounts,rawCount:value.list.length,responseKeys:Object.keys(value),metadata,
          nativeCheck:{keys:Object.keys(native||{}),error:native?.err_msg||'',ids}});
      });
    } catch { finish({error:'invalid_response'}); }
  });
})`;
let sessionId;
try {
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Local CDP relay unavailable')), 5000);
    ws.addEventListener('open', () => { clearTimeout(timer); resolve(); }, { once:true });
    ws.addEventListener('error', () => { clearTimeout(timer); reject(new Error('Local CDP relay unavailable')); }, { once:true });
  });
  const { targetInfos } = await command('Target.getTargets');
  const candidates = targetInfos.filter(t => /^weixin:\/\/resourceid\/Subscription(?:Profile|Disorder)\//.test(t.url));
  if (!target) {
    console.log(JSON.stringify({subscriptionTargets:candidates.map(t=>({targetId:t.targetId,url:t.url.split('?')[0]}))},null,2));
  } else {
    if (!candidates.some(t=>t.targetId===target)) throw new Error('Target is not a current subscription page');
    ({ sessionId } = await command('Target.attachToTarget', { targetId:target, flatten:true }));
    const result = await command('Runtime.evaluate', { expression, awaitPromise:true, returnByValue:true }, sessionId);
    if (result.exceptionDetails || !result.result?.value) throw new Error('Probe evaluation failed');
    const value = result.result.value;
    if (value.error) throw new Error(`Read-only probe: ${value.error}`);
    const accounts = [...new Map(value.accounts.map(a=>[a.id,a])).values()];
    const report = { capturedAt:new Date().toISOString(), api:'getbizlatestitemlisth5',
      complete_follow_list:false, following_verified:false, selectable_for_unfollow:false,
      rawCount:value.rawCount, count:accounts.length, responseKeys:value.responseKeys,
      metadata:value.metadata,nativeCheck:value.nativeCheck,accounts };
    await mkdir(dirname(output),{recursive:true,mode:0o700});
    await writeFile(output,JSON.stringify(report,null,2),{mode:0o600});
    await chmod(output,0o600);
    console.log(JSON.stringify({output,count:accounts.length,complete_follow_list:false}));
  }
} finally {
  if (sessionId && ws.readyState === WebSocket.OPEN) {
    await command('Target.detachFromTarget',{sessionId}).catch(()=>{});
  }
  for (const entry of pending.values()) clearTimeout(entry.timer);
  ws.close();
}
