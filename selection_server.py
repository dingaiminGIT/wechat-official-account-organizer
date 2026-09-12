#!/usr/bin/env python3
"""Local app service. Account-scoped storage and fail-closed job execution."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import datetime,json,os,secrets,signal,subprocess,sys,threading,time,uuid
import runtime_guard
from bridge_manager import BridgeManager
ROOT=Path(os.environ.get('WECHAT_RESOURCES',Path(__file__).resolve().parent))
DATA=Path(os.environ.get('WECHAT_DATA_ROOT',ROOT/'.runtime'))
HOST='127.0.0.1:8876';LOCK=threading.RLock();STOP=threading.Event()
CURRENT=None;WORKER=None;CHECKS={};CONNECTING=False;CLOSING=threading.Event();MINIAPPS_AT_BRIDGE_START=set()
SCOPED={'live-accounts-probe.json','whitelist.json','selected-accounts.json','unfollow-job.json','account-history.json'}
MANAGER=BridgeManager(ROOT,DATA)
EMPTY={'accounts':[],'capturedAt':None}
HISTORY_DAYS=30

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def path(name):
    if name in SCOPED:
        if not CURRENT:raise RuntimeError('请先连接并确认当前微信账号')
        return DATA/'accounts'/CURRENT['profile_key']/name
    return DATA/name

def read(name,default=None):
    if name in SCOPED and not CURRENT:return default
    p=path(name);return json.loads(p.read_text()) if p.exists() else default

def write(name,value):
    write_path(path(name),value)

def write_path(p,value):
    p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    tmp=p.with_name(p.name+'.tmp');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(tmp,p);p.chmod(0o600)

def parsed_date(value):
    try:
        dt=datetime.datetime.fromisoformat(value.replace('Z','+00:00'))
        return dt.replace(tzinfo=datetime.timezone.utc) if dt.tzinfo is None else dt
    except (AttributeError,TypeError,ValueError):return None

def prune_history(folder,at=None):
    """Expire recovery data; never touch a whitelist or an executing job."""
    if active():return
    at=at or datetime.datetime.now(datetime.timezone.utc)
    cutoff=at-datetime.timedelta(days=HISTORY_DAYS)
    catalog_path=folder/'live-accounts-probe.json'
    if catalog_path.exists():
        catalog=json.loads(catalog_path.read_text());before=json.dumps(catalog);kept=[]
        for a in catalog.get('accounts',[]):
            if a.get('was_unfollowed') or a.get('subscribed') is False:
                started=parsed_date(a.get('unfollowed_at')) or parsed_date(a.get('history_started_at')) or parsed_date(catalog.get('capturedAt')) or at
                if started<=cutoff:
                    if a.get('subscribed') is False:continue
                    for k in ('was_unfollowed','unfollowed_at','refollowed_at','history_started_at','history_expires_at'):a.pop(k,None)
                else:
                    a.setdefault('history_started_at',started.isoformat())
                    a['history_expires_at']=(started+datetime.timedelta(days=HISTORY_DAYS)).isoformat()
            kept.append(a)
        catalog['accounts']=kept
        if json.dumps(catalog)!=before:write_path(catalog_path,catalog)
    events=folder/'account-history.json'
    if events.exists():
        records=json.loads(events.read_text());kept=[e for e in records if (parsed_date(e.get('at')) or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))>cutoff]
        if kept!=records:write_path(events,kept)
    for name,field in [('unfollow-job.json','finished_at'),('selected-accounts.json','created_at')]:
        p=folder/name
        if p.exists():
            obj=json.loads(p.read_text());stamp=parsed_date(obj.get(field)) or parsed_date(obj.get('started_at')) or datetime.datetime.fromtimestamp(p.stat().st_mtime,datetime.timezone.utc)
            if stamp<=cutoff:p.unlink()

def data():return read('live-accounts-probe.json',EMPTY)
def white():return read('whitelist.json',{'ids':[]})['ids']
def job():return read('unfollow-job.json')
def active():return bool(WORKER and WORKER.is_alive())
def token():
    v=read('web-token.json')
    if not v:v={'token':secrets.token_urlsafe(32)};write('web-token.json',v)
    return v['token']

def preflight():return runtime_guard.preflight(ROOT,DATA)
def verify_identity(expected=None):
    expected=expected or CURRENT
    if not expected:raise RuntimeError('请先连接微信')
    actual=runtime_guard.identity()
    if any(actual.get(k)!=expected.get(k) for k in ('profile_key','session_key')):raise RuntimeError('微信账号或登录会话已变化，请重新连接；旧清单不可继续执行')
    return actual

def ensure_ready(check_identity=True):
    c=preflight()
    if not c['compatible'] or not c['prepared']:raise RuntimeError(c['message'] if not c['compatible'] else '请先完成环境准备')
    if check_identity:verify_identity()
    if not MANAGER.call('health').get('connected'):raise RuntimeError('微信连接已断开，请保留小程序窗口后重新连接')

def open_miniapp_pids(output=None):
    """Return real miniapp renderer PIDs, excluding WeChat's preload process."""
    if output is None:
        try:output=subprocess.run(['/bin/ps','-axo','pid=,command='],capture_output=True,text=True,timeout=3).stdout
        except Exception:return set()
    result=set()
    for line in output.splitlines():
        if '/Helpers/WeApp.app/Contents/MacOS/WeApp ' not in line or '--wmpf-appid=' not in line or '--wmpf-appid=preload-' in line:continue
        try:result.add(int(line.split(None,1)[0]))
        except (ValueError,IndexError):pass
    return result

def miniapp_wait_message():
    if MINIAPPS_AT_BRIDGE_START:
        return '检测到小程序是在连接服务启动前打开的。请关闭当前小程序窗口，再重新打开任意小程序的内容页。'
    return '请打开一个微信小程序并保留窗口，然后重新连接'

def connection():
    if not CURRENT:return {'connected':False,'message':'尚未连接微信，请先检查环境并连接'}
    try:
        verify_identity()
        if MANAGER.process is None or MANAGER.process.poll() is not None:raise RuntimeError('连接服务未启动，请重新连接')
        # Native TCP peer count is only a transport indicator, never identity proof.
        p=subprocess.run(['/usr/sbin/lsof','-nP','-iTCP:9421','-sTCP:ESTABLISHED','-F','n'],capture_output=True,text=True,timeout=3)
        if '127.0.0.1:9421->127.0.0.1:' not in p.stdout:raise RuntimeError(miniapp_wait_message())
        return {'connected':True,'message':'已连接 · '+CURRENT['label']}
    except Exception as e:
        if active():STOP.set()
        return {'connected':False,'message':str(e)}

def snapshot():
    c=connection();visible=False
    try:verify_identity();visible=True
    except Exception:pass
    with LOCK:
        if visible:prune_history(path('live-accounts-probe.json').parent)
        return {'history_retention_days':HISTORY_DAYS,'catalog':data() if visible else EMPTY,'whitelist':white() if visible else [],'plan':read('selected-accounts.json') if visible else None,'job':job() if visible else None,'identity':CURRENT if visible else None,'connection':c,'preflight':CHECKS,'connecting':CONNECTING}

def ids_checked(ids):
    known={a['id']:a for a in data()['accounts']}
    if not isinstance(ids,list) or not all(isinstance(i,str) for i in ids) or len(ids)!=len(set(ids)) or not set(ids)<=known.keys():raise ValueError('包含重复或未知账号，请重新加载列表')
    return known

def bind_request(req):
    verify_identity()
    if req.get('profile_key')!=CURRENT['profile_key'] or req.get('session_key')!=CURRENT['session_key']:raise ValueError('页面账号已过期，请重新连接并选择账号')

def connect():
    global CURRENT,CHECKS,MINIAPPS_AT_BRIDGE_START
    if CLOSING.is_set():raise RuntimeError('应用正在退出')
    CHECKS=preflight()
    if not CHECKS['compatible']:raise RuntimeError(CHECKS['message'])
    if not CHECKS['prepared']:raise RuntimeError('此微信尚未准备连接环境。请在应用菜单中查看“环境准备与恢复”。')
    identity=runtime_guard.identity()
    if MANAGER.process is None or MANAGER.process.poll() is not None:MINIAPPS_AT_BRIDGE_START=open_miniapp_pids()
    MANAGER.start()
    try:listing=MANAGER.call('list',identity)
    except RuntimeError as e:
        if '小程序' in str(e):raise RuntimeError(miniapp_wait_message()) from e
        raise
    verify_identity(identity)
    if CLOSING.is_set():raise RuntimeError('应用正在退出')
    with LOCK:
        CURRENT=identity
        prune_history(path('live-accounts-probe.json').parent)
        previous=data();old={a['id']:a for a in previous['accounts']}
    fresh={a['id']:a for a in listing['accounts']}
    for account_id,a in fresh.items():
        if old.get(account_id,{}).get('subscribed') is False or old.get(account_id,{}).get('was_unfollowed'):
            result=MANAGER.call('check',identity,account_id)
            a.update(subscribed=result['subscribed'],following_verified=True,was_unfollowed=True)
            for k in ('unfollowed_at','refollowed_at','history_started_at','history_expires_at'):
                if k in old[account_id]:a[k]=old[account_id][k]
    for account_id,a in old.items():
        if account_id not in fresh and (a.get('subscribed') is False or a.get('was_unfollowed')):
            # Catalogs before v0.5.0 only contained subscription accounts.
            a.setdefault('account_type','subscription');a.setdefault('service_type',0);fresh[account_id]=a
    listing['accounts']=list(fresh.values())
    verify_identity(identity)
    with LOCK:
        MINIAPPS_AT_BRIDGE_START=set()
        write('live-accounts-probe.json',listing)
        if read('whitelist.json') is None:write('whitelist.json',{'ids':[]})
        oldjob=job()
        if oldjob and oldjob['status'] in ('running','stopping'):
            oldjob.update(status='paused',message='上次执行中断，继续前将重新核对状态。');write('unfollow-job.json',oldjob)
        plan=read('selected-accounts.json')
        if plan and plan.get('session_key')!=identity['session_key']:
            plan.update(consumed=True);write('selected-accounts.json',plan)
    return snapshot()

TERMINAL={'unfollowed','unfollowed_unverified','already_unfollowed','followed','followed_unverified','already_followed','skipped_unavailable'}
MODES={'safe','fast','turbo'}
def unavailable_follow_reason(detail):
    # Only an explicit account-level rejection from the follow callback is skippable.
    if detail.get('stage')!='follow':return None
    error=detail.get('error','')
    if not isinstance(error,str) or not error.startswith('微信未确认操作：'):return None
    response=error.removeprefix('微信未确认操作：').strip().lower()
    reasons={
        '该公众号因违规无法关注':('unable to follow this official account as it has violated the regulations','该公众号因违规无法关注','该账号因违规无法关注','该帐号因违规无法关注'),
        '该公众号已注销，无法关注':('this official account has been deleted','this official account has been deregistered','该公众号已注销','该公众号已被注销','该账号已注销','该帐号已注销','公众号已注销'),
    }
    for reason,phrases in reasons.items():
        if any(phrase in response for phrase in phrases):return reason
    return None

def store_follow_skip(j,index,detail,reason):
    item=j['items'][index]
    item.update(status='skipped_unavailable',message=reason+'，已跳过',diagnostic=detail)
    # A rejected follow must not change the cached subscription, recovery date or whitelist.
    history=read('account-history.json',[])
    history.append({'id':item['id'],'name':item.get('name',''),'action':'follow','status':'skipped_unavailable','reason':reason,'verified':False,'at':now(),'execution_ms':item.get('execution_ms')})
    write('account-history.json',history)

def action(account_id):return MANAGER.call('unfollow',CURRENT,account_id)
def fast_action(account_id):return MANAGER.call('unfollow_request',CURRENT,account_id)
def record_execution(j,index,started):
    elapsed=max(0,round((time.monotonic()-started)*1000));item=j['items'][index]
    item['execution_ms']=item.get('execution_ms',0)+elapsed;item['execution_finished_at']=now();item.pop('execution_started_at',None);j['execution_ms']=j.get('execution_ms',0)+elapsed

def store_result(j,index,result):
    item=j['items'][index];messages={'unfollowed':'已取关并复核','unfollowed_unverified':'已取关，未复核','already_unfollowed':'已未关注，跳过','followed':'已重新关注并复核','followed_unverified':'已重新关注，未复核','already_followed':'已经关注，已复核'}
    item.update(status=result['status'],message=messages[result['status']],result=result)
    catalog=data()
    for a in catalog['accounts']:
        if a['id']==item['id']:
            a.update(subscribed=result['subscribed'],following_verified=result.get('verified',result['status'] not in ('unfollowed_unverified','followed_unverified')),was_unfollowed=True)
            a['refollowed_at' if result['subscribed'] else 'unfollowed_at']=now()
            if not result['subscribed']:
                a['history_started_at']=a['unfollowed_at'];a['history_expires_at']=(parsed_date(a['unfollowed_at'])+datetime.timedelta(days=HISTORY_DAYS)).isoformat()
    write('live-accounts-probe.json',catalog)
    history=read('account-history.json',[]);history.append({'id':item['id'],'name':item.get('name',''),'action':j.get('kind','unfollow'),'status':result['status'],'verified':result.get('verified',result['status'] not in ('unfollowed_unverified','followed_unverified')),'at':now(),'execution_ms':item.get('execution_ms')});write('account-history.json',history)
    if j.get('kind')=='follow' and j.get('protect_after'):write('whitelist.json',{'ids':list(dict.fromkeys([*white(),item['id']])),'updated_at':now()})

def process_item(job_id,index):
    started=time.monotonic();invoked=False
    try:
        with LOCK:
            j=job()
            if not j or j['id']!=job_id or STOP.is_set():return True
            item=j['items'][index]
            if item['status'] in TERMINAL:return True
            if j.get('kind')!='follow' and item['id'] in white():raise RuntimeError('账号已在白名单中，执行停止')
            item.update(status='running',execution_started_at=now());write('unfollow-job.json',j)
        started=time.monotonic();invoked=True
        if j.get('kind')=='follow':result=MANAGER.call('follow_request' if j.get('mode','safe')=='fast' else 'follow',CURRENT,item['id'])
        elif j.get('mode','safe')=='safe':result=action(item['id'])
        else:result=fast_action(item['id'])
        verify_identity()
    except Exception as e:
        detail=getattr(e,'result',{}) if invoked else {'mutation_sent':False,'stage':'preflight'}
        reason=unavailable_follow_reason(detail) if (j or {}).get('kind')=='follow' else None
        if reason:
            try:verify_identity()
            except Exception as identity_error:e=identity_error;reason=None;detail={'stage':'identity','mutation_sent':True}
        with LOCK:
            j=job()
            if not j or j['id']!=job_id:return False
            if reason:
                record_execution(j,index,started);store_follow_skip(j,index,detail,reason);write('unfollow-job.json',j)
                return True
            j['items'][index].update(status='blocked' if detail.get('mutation_sent') is False else 'uncertain',message=str(e),diagnostic=detail);record_execution(j,index,started);write('unfollow-job.json',j)
        return False
    with LOCK:
        j=job()
        if not j or j['id']!=job_id:return False
        record_execution(j,index,started);store_result(j,index,result);write('unfollow-job.json',j)
    return True

def run_job(job_id):
    run_started=time.monotonic()
    try:
        current=job();indexes=[i for i,item in enumerate(current['items']) if item['status'] not in TERMINAL]
        width=3 if current.get('kind')!='follow' and current.get('mode')=='turbo' else 1
        failed=False
        for offset in range(0,len(indexes),width):
            if STOP.is_set():break
            batch=indexes[offset:offset+width]
            if width==1:results=[process_item(job_id,batch[0])]
            else:
                with ThreadPoolExecutor(max_workers=width) as pool:results=[future.result() for future in [pool.submit(process_item,job_id,index) for index in batch]]
            if not all(results):failed=True;break
        with LOCK:
            j=job()
            if not j or j['id']!=job_id:return
            j['wall_time_ms']=j.get('wall_time_ms',0)+round((time.monotonic()-run_started)*1000);j['finished_at']=now()
            if failed or any(item['status'] in ('blocked','uncertain') for item in j['items']):
                message='已暂停。继续前会重新核对账号和关注状态。' if j.get('mode','safe')=='safe' else '已暂停。当前模式不复核关注状态，请先在微信确认异常项，再决定是否继续。'
                j.update(status='paused',message=message)
            elif STOP.is_set():j.update(status='stopped',message='队列已停止。超级快速模式最多仍有 3 个已经发出的请求。' if j.get('mode')=='turbo' else '队列已停止。')
            else:j.update(status='completed',message='全部请求已处理。' if j.get('mode')=='safe' or j.get('kind')=='follow' else '全部取关请求已被微信接收；本模式未逐项复核关注状态。')
            j.pop('run_started_at',None)
            write('unfollow-job.json',j)
    except Exception as e:
        with LOCK:
            j=job()
            if j:
                j.update(status='paused',message=str(e),finished_at=now(),wall_time_ms=j.get('wall_time_ms',0)+round((time.monotonic()-run_started)*1000));j.pop('run_started_at',None);write('unfollow-job.json',j)

def launch_job(j):
    global WORKER
    j['run_started_at']=now();j.pop('finished_at',None);write('unfollow-job.json',j);STOP.clear();WORKER=threading.Thread(target=run_job,args=(j['id'],),daemon=True);WORKER.start()

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,status,payload,kind='application/json; charset=utf-8'):
        self.send_response(status)
        for k,v in {'Content-Type':kind,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Content-Security-Policy':"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"}.items():self.send_header(k,v)
        self.end_headers()
        try:self.wfile.write(payload.encode() if isinstance(payload,str) else json.dumps(payload,ensure_ascii=False).encode())
        except (BrokenPipeError,ConnectionResetError):pass
    def do_GET(self):
        if self.headers.get('Host')!=HOST:return self.send(403,{'error':'host'})
        try:
            if self.path=='/':return self.send(200,(ROOT/'selection.html').read_text().replace('__TOKEN__',token()),'text/html; charset=utf-8')
            if self.path=='/api/state':return self.send(200,snapshot())
            if self.path=='/api/connection':return self.send(200,connection())
            if self.path=='/api/preflight':return self.send(200,preflight())
            return self.send(404,{'error':'not found'})
        except Exception as e:return self.send(500,{'error':str(e)})
    def do_POST(self):
        global CURRENT,CHECKS,CONNECTING
        try:size=int(self.headers.get('Content-Length','0'))
        except ValueError:return self.send(400,{'error':'请求大小无效'})
        if not 0<size<65536:return self.send(413,{'error':'请求大小无效'})
        raw=self.rfile.read(size)
        if self.headers.get('Host')!=HOST or self.headers.get('Origin')!='http://'+HOST or self.headers.get('X-Selection-Token')!=token():return self.send(403,{'error':'页面验证已失效，请刷新'})
        try:
            req=json.loads(raw)
            if not isinstance(req,dict):raise ValueError('请求内容无效')
            if self.path=='/api/stop':
                STOP.set()
                with LOCK:
                    j=job()
                    if j and j['status']=='running':j['status']='stopping';write('unfollow-job.json',j)
                return self.send(200,{'ok':True})
            with LOCK:
                if active() or CONNECTING:raise ValueError('正在处理，请先停止并等待当前请求完成')
                if self.path=='/api/connect':CONNECTING=True
            if self.path=='/api/connect':
                try:return self.send(200,connect())
                finally:CONNECTING=False
            if self.path=='/api/disconnect':
                with LOCK:
                    if active() or CONNECTING:raise ValueError('请等待当前操作完成')
                    MANAGER.stop();CURRENT=None
                return self.send(200,{'ok':True})
            if self.path=='/api/shutdown':
                with LOCK:
                    if active() or CONNECTING:raise ValueError('请先停止并等待当前操作完成')
                self.send(200,{'ok':True});threading.Thread(target=shutdown,daemon=True).start();return
            with LOCK:
                if active() or CONNECTING:raise ValueError('正在处理，请等待当前操作完成')
                bind_request(req)
                prune_history(path('live-accounts-probe.json').parent)
                if self.path=='/api/whitelist':
                    ids=req.get('ids');ids_checked(ids);write('whitelist.json',{'ids':ids,'updated_at':now()})
                    plan=read('selected-accounts.json')
                    if plan:plan.update(consumed=True);write('selected-accounts.json',plan)
                    return self.send(200,{'ids':ids})
                if self.path=='/api/selection':
                    ids=req.get('ids');known=ids_checked(ids)
                    if not ids or set(ids)&set(white()):raise ValueError('清单为空或包含白名单账号')
                    plan={**{k:CURRENT[k] for k in ('profile_key','session_key')},'plan_id':uuid.uuid4().hex,'selected_accounts':[known[i] for i in ids],'count':len(ids),'source_captured_at':data()['capturedAt'],'created_at':now(),'consumed':False}
                    write('selected-accounts.json',plan);return self.send(200,plan)
                if self.path=='/api/refollow':
                    mode=req.get('mode','fast')
                    if mode not in ('safe','fast'):raise ValueError('重新关注模式无效，请重新选择')
                    ids=req.get('ids') if 'ids' in req else [req.get('id')]
                    known=ids_checked(ids)
                    if not ids:raise ValueError('请先选择要重新关注的账号')
                    if any(not (known[i].get('was_unfollowed') or known[i].get('subscribed') is False) for i in ids):raise ValueError('所选账号中包含没有本机取关记录的账号')
                    protect_after=req.get('protect_after',False)
                    if not isinstance(protect_after,bool):raise ValueError('请选择是否加入白名单')
                    ensure_ready()
                    j={'id':uuid.uuid4().hex,'kind':'follow','mode':mode,'protect_after':protect_after,'profile_key':CURRENT['profile_key'],'session_key':CURRENT['session_key'],'status':'running','started_at':now(),'items':[{**known[i],'status':'queued'} for i in ids]}
                    launch_job(j);return self.send(200,j)
                if self.path=='/api/execute':
                    mode=req.get('mode','safe')
                    if mode not in MODES:raise ValueError('执行模式无效，请重新选择')
                    plan=read('selected-accounts.json')
                    if not plan or req.get('plan_id')!=plan['plan_id'] or plan.get('consumed'):raise ValueError('清单已变化或已执行，请重新生成')
                    if plan.get('session_key')!=CURRENT['session_key']:raise ValueError('清单属于旧会话，请重新选择')
                    ids=[a['id'] for a in plan['selected_accounts']];ids_checked(ids)
                    if not ids or set(ids)&set(white()):raise ValueError('清单为空或包含白名单账号')
                    ensure_ready()
                    j={'id':uuid.uuid4().hex,'kind':'unfollow','mode':mode,'plan_id':plan['plan_id'],'profile_key':CURRENT['profile_key'],'session_key':CURRENT['session_key'],'status':'running','started_at':now(),'items':[{**a,'status':'queued'} for a in plan['selected_accounts']]}
                    plan['consumed']=True;write('selected-accounts.json',plan);launch_job(j);return self.send(200,j)
                if self.path=='/api/resume':
                    j=job()
                    if not j or req.get('job_id')!=j['id'] or j['status'] not in ('paused','stopped'):raise ValueError('没有可继续的队列')
                    if j.get('kind')=='follow':
                        mode=req.get('mode',j.get('mode','safe'))
                        if mode not in ('safe','fast'):raise ValueError('重新关注模式无效，请重新选择')
                        j['mode']=mode
                    if j.get('profile_key')!=CURRENT['profile_key'] or j.get('session_key')!=CURRENT['session_key']:raise ValueError('登录会话已变化，请重新选择未完成账号')
                    pending=[a['id'] for a in j['items'] if a['status'] not in TERMINAL];ids_checked(pending)
                    if j.get('kind')!='follow' and set(pending)&set(white()):raise ValueError('未完成项包含白名单账号')
                    ensure_ready();resume_message='正在核实并继续未完成项。' if j.get('mode','safe')=='safe' else ('正在继续发送未完成的关注请求；本模式不复核关注状态。' if j.get('kind')=='follow' else '正在继续发送未完成的取关请求；本模式不复核关注状态。');j.update(status='running',message=resume_message,resumed_at=now());launch_job(j);return self.send(200,j)
            return self.send(404,{'error':'not found'})
        except (ValueError,TypeError,RuntimeError) as e:return self.send(409,{'error':str(e)})
        except Exception:return self.send(500,{'error':'服务处理失败，操作已停止'})

def shutdown():
    CLOSING.set();STOP.set()
    for _ in range(700):
        if not CONNECTING:break
        time.sleep(.1)
    if WORKER and WORKER.is_alive():WORKER.join(timeout=125)
    MANAGER.stop();os._exit(0)

if __name__=='__main__':
    if '--identity' in sys.argv:
        try:print(json.dumps(runtime_guard.identity()))
        except Exception as e:print(json.dumps({'error':str(e)}));sys.exit(1)
        sys.exit(0)
    if '--environment' in sys.argv:
        import environment_ops,argparse
        parser=argparse.ArgumentParser();parser.add_argument('--environment',choices=['prepare','apply','restore'],required=True);parser.add_argument('--data',required=True);parser.add_argument('--resources',required=True);args=parser.parse_args()
        try:
            r=environment_ops.prepare(Path(args.resources),Path(args.data)) if args.environment=='prepare' else environment_ops.modify(Path(args.resources),Path(args.data),args.environment)
            print(json.dumps(r,ensure_ascii=False))
        except Exception as e:print(json.dumps({'error':str(e)},ensure_ascii=False));sys.exit(1)
        sys.exit(0)
    os.umask(0o077);DATA.mkdir(parents=True,exist_ok=True,mode=0o700);token()
    for folder in (DATA/'accounts').glob('*'):
        if folder.is_dir():prune_history(folder)
    CHECKS=preflight()
    # Show only the saved records belonging to the currently identifiable WeChat account.
    try:
        saved_identity=runtime_guard.identity()
        if (DATA/'accounts'/saved_identity['profile_key']/'live-accounts-probe.json').exists():
            CURRENT=saved_identity
            previous_job=job()
            if previous_job and previous_job['status'] in ('running','stopping'):
                previous_job.update(status='paused',message='上次操作中断。连接后将先核对关注状态。');write('unfollow-job.json',previous_job)
    except Exception:CURRENT=None
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:threading.Thread(target=shutdown,daemon=True).start())
    server=ThreadingHTTPServer(('127.0.0.1',8876),Handler)
    print('READY http://'+HOST,flush=True);server.serve_forever()
