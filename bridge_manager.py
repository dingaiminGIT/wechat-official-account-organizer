import json,os,secrets,socket,subprocess,sys,time
from pathlib import Path
class BridgeManager:
    def __init__(self,root,data):self.root=root;self.data=data;self.process=None;self.log=None
    def node(self):return os.environ.get('WECHAT_NODE','node')
    def environment(self):
        env=os.environ.copy();env['WECHAT_DATA_ROOT']=str(self.data)
        env['WECHAT_IDENTITY_COMMAND']=json.dumps([sys.executable,'--identity'] if getattr(sys,'frozen',False) else [sys.executable,str(self.root/'runtime_guard.py')])
        return env
    def call(self,action,identity=None,account_id=None):
        p=subprocess.run([self.node(),str(self.root/'wechat_action.mjs')],input=json.dumps({'action':action,'identity':identity,'id':account_id}),text=True,capture_output=True,env=self.environment(),timeout=120)
        try:result=json.loads(p.stdout.strip().splitlines()[-1])
        except (ValueError,IndexError):raise RuntimeError('连接执行器未正常返回，已停止')
        if p.returncode or result.get('error'):
            e=RuntimeError(result.get('error','连接失败'));e.result=result;raise e
        return result
    def start(self):
        if self.process and self.process.poll() is None:return
        for port in [9421,62000]:
            with socket.socket() as sock:
                if sock.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('检测到其他连接服务占用端口，请先关闭旧版工具')
        self.data.mkdir(parents=True,exist_ok=True,mode=0o700)
        t=self.data/'bridge-token.json';t.write_text(json.dumps({'token':secrets.token_urlsafe(32)}));t.chmod(0o600)
        debugger=Path(os.environ.get('WECHAT_DEBUGGER',str(self.root.parent/'work/wechat-unfollow-feasibility/research/WMPFDebugger')))
        log=self.data/'bridge.log'
        self.log=log.open('w');log.chmod(0o600)
        self.process=subprocess.Popen([self.node(),str(debugger/'build/index.js')],cwd=debugger,env=self.environment(),stdout=self.log,stderr=self.log,start_new_session=True)
        for _ in range(40):
            if self.process.poll() is not None:raise RuntimeError('微信连接组件启动失败，请检查微信已登录并完成环境准备')
            if '[frida] script loaded' in log.read_text(errors='replace'):return
            time.sleep(.2)
        self.stop();raise RuntimeError('连接组件启动超时，请重新检查微信状态')
    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=3)
        self.process=None
        if self.log:self.log.close();self.log=None
        try:(self.data/'bridge-token.json').unlink()
        except FileNotFoundError:pass
