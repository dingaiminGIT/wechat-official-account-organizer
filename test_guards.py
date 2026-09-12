import hashlib,json,os,pathlib,plistlib,tempfile,unittest
from unittest.mock import patch
import runtime_guard as g
import environment_ops as env
from helper_signing_change import change,inspect
class GuardTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def test_unknown_platform_is_rejected(self):
  manifest=json.loads((pathlib.Path(__file__).parent/'compatibility.json').read_text());(self.root/'compatibility.json').write_text(json.dumps(manifest))
  with patch.object(g.platform,'machine',return_value='x86_64'),patch.object(g,'APP',self.root/'missing'),patch.object(g,'HELPER',self.root/'missing-helper'):
   self.assertFalse(g.preflight(self.root,self.root)['compatible'])
 def package(self):
  target=self.root/'helper';package=self.root/'backup';target.mkdir();(target/'Contents').mkdir();(target/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleVersion':'269136'}));files=[]
  for rel in ['Contents/MacOS/WeChatAppEx','Contents/_CodeSignature/CodeResources']:
   (target/rel).parent.mkdir(exist_ok=True)
   (target/rel).write_bytes(b'original')
   item={'relative_path':rel,'uid':os.getuid(),'gid':os.getgid(),'mode':0o600}
   for kind in ['original','replacement']:
    p=package/kind/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(kind.encode());item[kind+'_sha256']=hashlib.sha256(kind.encode()).hexdigest()
   files.append(item)
  (package/'manifest.json').write_text(json.dumps({'build':'269136','files':files}));return package,target
 def test_exact_backup_can_restore(self):
  package,target=self.package()
  with patch('helper_signing_change.subprocess.run'):
   self.assertTrue(all(s['state']=='replacement' for s in change(package,target,'apply')))
   self.assertTrue(all(s['state']=='original' for s in change(package,target,'restore')))
 def test_upgrade_and_unknown_files_refuse_restore(self):
  package,target=self.package();(target/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleVersion':'new'}))
  with self.assertRaises(RuntimeError):change(package,target,'restore')
  (target/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleVersion':'269136'}));(target/'Contents/MacOS/WeChatAppEx').write_bytes(b'unknown')
  with self.assertRaises(RuntimeError):change(package,target,'restore')
  self.assertEqual((target/'Contents/MacOS/WeChatAppEx').read_bytes(),b'unknown')
 def test_corrupt_backup_refuses_restore(self):
  package,target=self.package();(package/'original/Contents/MacOS/WeChatAppEx').write_bytes(b'corrupt')
  with self.assertRaises(RuntimeError):change(package,target,'restore')
 def test_prepare_archives_stale_build_backup(self):
  resources=self.root/'resources';data=self.root/'data';helper=self.root/'WeChatAppEx.app'
  resources.mkdir();data.mkdir();(resources/'compatibility.json').write_text(json.dumps({'wmpf_build':'269602'}))
  for rel in ['Contents/MacOS/WeChatAppEx','Contents/_CodeSignature/CodeResources']:
   p=helper/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'current')
  stale=data/'helper-signing-change';stale.mkdir();(stale/'manifest.json').write_text(json.dumps({'build':'269136'}))
  check={'compatible':True,'signature':'original'}
  with patch.object(env.runtime_guard,'preflight',return_value=check),patch.object(env.runtime_guard,'HELPER',helper),patch.object(env.subprocess,'run'):
   result=env.prepare(resources,data)
  self.assertTrue(result['ready']);self.assertTrue((data/'helper-signing-change-269136-archive').exists())
  self.assertEqual(json.loads((data/'helper-signing-change/manifest.json').read_text())['build'],'269602')
if __name__=='__main__':unittest.main()
