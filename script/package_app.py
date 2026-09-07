from pathlib import Path
import os,plistlib,shutil,subprocess
root=Path(os.environ['WECHAT_PROJECT']);debugger=root.parent/'work/wechat-unfollow-feasibility/research/WMPFDebugger'
subprocess.run([str(debugger/'node_modules/.bin/tsc'),'--noEmit','false','--module','commonjs','--rootDir','src','--outDir','build'],cwd=debugger,check=True)
shutil.copytree(debugger/'src/third-party',debugger/'build/third-party',dirs_exist_ok=True)
bundle=root/'dist/公众号整理.app';stage=root/'dist/.Organizer-stage.app'
if stage.exists():shutil.rmtree(stage)
contents=stage/'Contents';macos=contents/'MacOS';resources=contents/'Resources'
macos.mkdir(parents=True);resources.mkdir();shutil.copy2(root/'macapp/.build/debug/WeChatOrganizer',macos/'WeChatOrganizer')
shutil.copytree(root/'.package/WeChatBridge',resources/'backend',symlinks=True)
bridge=resources/'bridge';bridge.mkdir()
for name in ['selection.html','wechat_action.mjs','compatibility.json']:shutil.copy2(root/name,bridge/name)
node=Path(shutil.which('node')).resolve();shutil.copy2(node,resources/'node')
for part in ['build','frida']:shutil.copytree(debugger/part,resources/'debugger'/part,symlinks=True)
def ignore(path,names):
    path=Path(path);skip=set()
    if path.name=='frida' and path.parent.name=='node_modules':skip.update({'deps','subprojects','releng','src','scripts','test'})
    if path.name=='build' and path.parent.name=='frida' and path.parent.parent.name=='node_modules':skip.update(n for n in names if n not in ('src','frida_binding.node'))
    if path.name=='node_modules':skip.add('.cache')
    return list(skip)
shutil.copytree(debugger/'node_modules',resources/'debugger/node_modules',symlinks=True,ignore=ignore)
source=resources/'Source';source.mkdir()
for name in ['selection_server.py','runtime_guard.py','bridge_manager.py','environment_ops.py','helper_signing_change.py','wechat_action.mjs','selection.html','compatibility.json']:shutil.copy2(root/name,source/name)
shutil.copytree(root/'macapp/Sources',source/'macapp/Sources');shutil.copy2(root/'macapp/Package.swift',source/'macapp/Package.swift');shutil.copytree(root/'script',source/'script')
up=source/'WMPFDebugger';up.mkdir()
for name in ['src','frida']:shutil.copytree(debugger/name,up/name)
for name in ['LICENSE','README.md','README.zh.md','EXTENSION.md','package.json','yarn.lock','tsconfig.json']:
    if (debugger/name).exists():shutil.copy2(debugger/name,up/name)
(source/'NOTICE.txt').write_text('WMPFDebugger by evi0s and contributors; GPL-2.0-only.\nhttps://github.com/evi0s/WMPFDebugger\nPinned commit: 1d9f6e03a24dcd39baa223e25a883a85b84bd303\nLocal changes: loopback binding, authenticated CDP relay, health query and graceful shutdown.\nFrida 17.3.2: https://github.com/frida/frida/releases/tag/17.3.2\nNode.js v22.22.0: https://nodejs.org/download/release/v22.22.0/\nThis local evaluation bundle is not notarized or validated for public distribution.\n')
plist={'CFBundleExecutable':'WeChatOrganizer','CFBundleIdentifier':'com.baiya.WeChatOrganizer','CFBundleName':'公众号整理','CFBundleDisplayName':'公众号整理','CFBundlePackageType':'APPL','CFBundleVersion':'1','CFBundleShortVersionString':'0.2.0','LSMinimumSystemVersion':'14.0','NSPrincipalClass':'NSApplication','NSAppleEventsUsageDescription':'仅在你选择环境准备或恢复时，请求系统授权修改已验证的微信辅助程序。'}
(contents/'Info.plist').write_bytes(plistlib.dumps(plist))
for path in [resources/'node',resources/'debugger/node_modules/frida/build/frida_binding.node']:subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(path)],check=True,capture_output=True)
subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(stage)],check=True,capture_output=True);subprocess.run(['/usr/bin/codesign','--verify','--strict',str(stage)],check=True,capture_output=True)
if bundle.exists():shutil.rmtree(bundle)
stage.rename(bundle);print(bundle)
