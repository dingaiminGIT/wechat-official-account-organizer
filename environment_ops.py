"""Guarded user-invoked helper preparation and restoration."""
import json,os,shutil,subprocess,tempfile
from pathlib import Path
import runtime_guard
from helper_signing_change import change,inspect,digest

def prepare(resources,data):
    check=runtime_guard.preflight(resources,data)
    if not check['compatible']:raise RuntimeError('当前微信版本未通过验证，不能准备环境')
    package=data/'helper-signing-change'
    if package.exists():
        _,states=inspect(package,runtime_guard.HELPER)
        if any(s['state']=='unknown' for s in states):raise RuntimeError('已有备份与微信不匹配')
        return {'ready':True,'state':states}
    if check['signature']!='original':raise RuntimeError('只支持从已验证的原始微信创建备份')
    with tempfile.TemporaryDirectory(prefix='wechat-prepare-',dir=data) as tmp:
        trial=Path(tmp)/'WeChatAppEx.app';shutil.copytree(runtime_guard.HELPER,trial,symlinks=True)
        subprocess.run(['/usr/bin/codesign','--force','--sign','-','--preserve-metadata=identifier,entitlements','--requirements','=designated => identifier "com.tencent.flue.WeChatAppEx"',str(trial)],check=True,capture_output=True)
        subprocess.run(['/usr/bin/codesign','--verify','--strict',str(trial)],check=True,capture_output=True)
        staged=Path(tmp)/'package';files=[]
        for rel in ['Contents/MacOS/WeChatAppEx','Contents/_CodeSignature/CodeResources']:
            src=runtime_guard.HELPER/rel;stat=src.stat()
            for kind,base in [('original',runtime_guard.HELPER),('replacement',trial)]:
                dst=staged/kind/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(base/rel,dst);dst.chmod(0o600)
            files.append({'relative_path':rel,'original_sha256':digest(src),'replacement_sha256':digest(trial/rel),'uid':stat.st_uid,'gid':stat.st_gid,'mode':stat.st_mode&0o777})
        (staged/'manifest.json').write_text(json.dumps({'target_app':str(runtime_guard.HELPER),'build':'269136','files':files,'applied':False},indent=2));os.replace(staged,package)
    return {'ready':True,'message':'已生成本机备份，尚未修改微信'}

def modify(resources,data,action):
    if os.geteuid()!=0:raise RuntimeError('需要通过系统管理员授权执行')
    if action not in ('apply','restore'):raise RuntimeError('无效操作')
    procs=subprocess.check_output(['/bin/ps','-axo','comm='],text=True)
    if any('/Applications/WeChat.app/' in line for line in procs.splitlines()):raise RuntimeError('请先完全退出微信，再执行环境修改')
    checked=runtime_guard.preflight(resources,data)
    permitted=checked['compatible'] if action=='apply' else checked.get('restorable') and all(c['ok'] for c in checked['checks'] if c['name']!='微信文件状态')
    if not permitted:raise RuntimeError('当前安装与已验证版本或备份不匹配，拒绝覆盖微信文件')
    result=change(data/'helper-signing-change',runtime_guard.HELPER,action)
    return {'ok':True,'action':action,'files':result,'message':'环境已准备，请重新打开微信' if action=='apply' else '微信原始文件已恢复，请重新打开微信'}
