(() => {
  if (window.__baiyaSubscriptionProbe) return;
  window.__baiyaSubscriptionProbe = true;
  const endpoint = '__COLLECTOR__';
  function send(event) {
    event.path = location.pathname;
    fetch(endpoint, {method:'POST', mode:'cors', headers:{'Content-Type':'text/plain'}, body:JSON.stringify(event)}).catch(() => {});
  }
  function badge(text) {
    let el=document.getElementById('baiya-readonly-probe');
    if(!el){el=document.createElement('div');el.id='baiya-readonly-probe';el.style.cssText='position:fixed;right:16px;top:44px;z-index:2147483647;background:#18784b;color:white;padding:10px 16px;border-radius:12px;font:14px sans-serif;pointer-events:none';document.documentElement.append(el)}
    el.textContent=text;
  }
  const normalize = list => (Array.isArray(list) ? list : []).filter(x=>x&&typeof x==='object').map(x=>({id:x.biz_name||x.name||'',name:x.nick_name||x.showName||'',starred:!!(x.top_flag||x.isStar)})).filter(x=>x.id);
  function start(){
    const bridge=window.WeixinJSBridge;
    if(!bridge||typeof bridge.invoke!=='function')return false;
    send({type:'ready',readonly:true});badge('公众号工具 · 正在读取账号');
    // Exactly the read-only call used by SubscriptionProfile/home.html, version 629.
    const request={cgi_cmdid:29175,url:'/cgi-bin/mmbiz-bin/bizattr/getbizlatestitemlisth5',scope:'subscriptions',req_json:JSON.stringify({scene:16,BaseRequest:{SessionKey:'',Uin:0,DeviceID:'',ClientVersion:0,DeviceType:'',Scene:0}})};
    let completed=false;
    bridge.invoke('H5ExtTransfer',request, response=>{
      completed=true;
      try{
        const value=JSON.parse(response?.jsapi_resp?.resp_json||'{}');
        const accounts=normalize(value.list);
        send({type:'accounts',api:'getbizlatestitemlisth5',err:response?.err_msg||'',responseKeys:Object.keys(value),accounts});
        badge(accounts.length ? `公众号工具 · 已读取 ${accounts.length} 个账号（只读）` : '公众号工具 · 接口未返回账号');
      }catch(error){send({type:'error',message:String(error)});badge('公众号工具 · 读取失败')}
    });
    setTimeout(()=>{if(!completed){send({type:'timeout'});badge('公众号工具 · 接口未响应')}},12000);
    return true;
  }
  badge('公众号工具 · 脚本已加载，等待接口');
  send({type:'loaded',readonly:true});
  let attempts=0;const timer=setInterval(()=>{
    if(start())clearInterval(timer);
    else if(++attempts>=80){clearInterval(timer);send({type:'bridge_unavailable'});badge('公众号工具 · 当前页面接口不可用')}
  },250);
})();
