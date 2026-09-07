"""Read-only compatibility and active local-account checks. Never reads DB contents."""
import hashlib,json,os,platform,plistlib,re,subprocess
from pathlib import Path
APP=Path('/Applications/WeChat.app')
HELPER=APP/'Contents/MacOS/WeChatAppEx.app'
_HASH_CACHE={}

def sha(path):
    s=path.stat();key=(str(path),s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    if key not in _HASH_CACHE:
        with path.open('rb') as f:_HASH_CACHE[key]=hashlib.file_digest(f,'sha256').hexdigest()
    return _HASH_CACHE[key]

def identity():
    p=subprocess.run(['/usr/bin/pgrep','-x','WeChat'],capture_output=True,text=True,timeout=3)
    pids=p.stdout.split()
    if len(pids)!=1:raise RuntimeError('请只打开一个微信并完成登录')
    pid=pids[0]
    executable=subprocess.check_output(['/bin/ps','-p',pid,'-o','comm='],text=True,timeout=3).strip()
    if executable!=str(APP/'Contents/MacOS/WeChat'):raise RuntimeError('微信进程路径不匹配')
    start=subprocess.check_output(['/bin/ps','-p',pid,'-o','lstart='],text=True,timeout=3).strip()
    opened=subprocess.check_output(['/usr/sbin/lsof','-a','-p',pid,'-Fn'],text=True,timeout=5)
    roots=set()
    for line in opened.splitlines():
        m=re.match(r'n(.*/Library/Containers/com\.tencent\.xinWeChat/Data/Documents/xwechat_files/[^/]+/db_storage)/',line)
        if m:roots.add(str(Path(m.group(1)).resolve()))
    if len(roots)!=1:raise RuntimeError('无法唯一确认当前微信账号，请登录后重新连接')
    key=hashlib.sha256(next(iter(roots)).encode()).hexdigest()
    session=hashlib.sha256((key+':'+pid+':'+start).encode()).hexdigest()
    return {'profile_key':key,'session_key':session,'label':'本机微信 · '+key[:6], 'pid':int(pid)}

def preflight(resources,data_root):
    manifest=json.loads((resources/'compatibility.json').read_text())
    checks=[]
    def check(name,ok,detail):checks.append({'name':name,'ok':bool(ok),'detail':detail})
    check('Mac 架构',platform.machine()==manifest['architecture'],platform.machine())
    check('macOS 版本',platform.mac_ver()[0] in manifest['tested_macos'],platform.mac_ver()[0]+'；已验证：'+', '.join(manifest['tested_macos']))
    signature='unknown';restorable=False
    try:
        info=plistlib.load((APP/'Contents/Info.plist').open('rb'))
        helper=plistlib.load((HELPER/'Contents/Info.plist').open('rb'))
        check('微信版本',info.get('CFBundleShortVersionString')==manifest['wechat_version'] and str(helper.get('CFBundleVersion'))==manifest['wmpf_build'],str(info.get('CFBundleShortVersionString'))+' / '+str(helper.get('CFBundleVersion')))
        framework=HELPER/'Contents/Frameworks/WeChatAppEx Framework.framework/WeChatAppEx Framework'
        check('连接组件指纹',sha(framework)==manifest['framework_sha256'],'校验微信内部组件，避免误用版本配置')
        digest=sha(HELPER/'Contents/MacOS/WeChatAppEx')
        if digest==manifest['original_helper_sha256']:signature='original'
        backup=data_root/'helper-signing-change/manifest.json'
        if backup.exists():
            m=json.loads(backup.read_text())
            if m.get('build')==manifest['wmpf_build']:
                expected=next((x for x in m['files'] if x['relative_path']=='Contents/MacOS/WeChatAppEx'),{})
                if expected.get('original_sha256')!=manifest['original_helper_sha256']:raise RuntimeError('备份不是已验证的原始文件')
                from helper_signing_change import inspect
                _,states=inspect(backup.parent,HELPER)
                known=all(s['state'] in ('original','replacement') for s in states)
                restorable=known and any(s['state']=='replacement' for s in states)
                if all(s['state']=='replacement' for s in states):signature='prepared'
                elif known and restorable:signature='partial'
                elif not known:signature='unknown'
        check('微信文件状态',signature in ('original','prepared'),'原始安装' if signature=='original' else '已准备，原始文件备份可用' if signature=='prepared' else '检测到未完成修改，可恢复备份' if signature=='partial' else '文件状态未知，禁止接入')
    except Exception:check('微信安装检查',False,'未找到可验证的微信安装或备份')
    compatible=all(c['ok'] for c in checks)
    return {'compatible':compatible,'prepared':signature=='prepared','restorable':restorable,'signature':signature,'checks':checks,'adapter':manifest['adapter'],'message':'环境已通过检查' if compatible else '当前环境未通过兼容性检查，取关不可用；请等待经过验证的适配更新。'}

if __name__=='__main__':
    try:print(json.dumps(identity()))
    except Exception as e:print(json.dumps({'error':str(e)},ensure_ascii=False));raise SystemExit(1)
