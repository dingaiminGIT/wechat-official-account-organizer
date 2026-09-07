from pathlib import Path
import zipfile,io,json,hashlib,os,sys
ROOT=Path(__file__).resolve().parent;rt=ROOT/'.runtime';rt.mkdir(exist_ok=True)
p=Path.home()/'Library/Containers/com.tencent.xinWeChat/Data/Documents/app_data/radium/users/b387f814c50b65327c643f768f2d99c9/udr/subscription/629/main'
record=rt/'patch.json'
if sys.argv[1:] == ['restore']:
 meta=json.loads(record.read_text());backup=Path(meta['backup']);current=p.read_bytes()
 if hashlib.sha256(backup.read_bytes()).hexdigest()!=meta['original_sha256']:raise SystemExit('Backup checksum mismatch')
 if hashlib.sha256(current).hexdigest()==meta['original_sha256']:
  meta['restored']=True;record.write_text(json.dumps(meta,indent=2));print('Original package already restored');raise SystemExit
 if hashlib.sha256(current).hexdigest()!=meta['patched_sha256']:raise SystemExit('Current package changed; refusing overwrite')
 tmp=p.with_name('main.baiya-restore.tmp');tmp.write_bytes(backup.read_bytes());os.chmod(tmp,p.stat().st_mode);os.replace(tmp,p)
 meta['restored']=True;record.write_text(json.dumps(meta,indent=2));print('Restored original package');raise SystemExit
if record.exists():
 previous=json.loads(record.read_text())
 if not previous.get('restored') or hashlib.sha256(p.read_bytes()).hexdigest()!=previous['original_sha256']:raise SystemExit('An existing patch is not verified restored')
original=p.read_bytes();digest=hashlib.sha256(original).hexdigest()
if digest!='72fcaae304a2088fb36ae1471780d85d7dbded69af5871261f062562a3bc30df':raise SystemExit('Package version changed')
backup=rt/'subscription-629-original.zip';backup.write_bytes(original);backup.chmod(0o600)
probe=(ROOT/'probe.js').read_text().replace('__COLLECTOR__',(rt/'endpoint').read_text())
z=zipfile.ZipFile(io.BytesIO(original));updates={}
for name in z.namelist():
 data=z.read(name)
 if name.endswith('.html'):
  s=data.decode();marker='<script>'+probe+'</script>'
  if '</body>' not in s:raise SystemExit('Missing HTML insertion anchor')
  updates[name]=s.replace('</body>',marker+'</body>',1).encode()
 else:updates[name]=data
# Keep version metadata; adjust the package's own content hashes to its edited HTML.
for name,data in list(updates.items()):
 if name.endswith('config.conf'):
  lines=[]
  for line in data.decode().splitlines():
   if line.startswith(('md5map = ','shamap = ')):
    key,raw=line.split(' = ',1);mapping=json.loads(raw)
    for entry in mapping:
     candidates=[v for n,v in updates.items() if n.endswith('/'+entry)]
     if len(candidates)==1:mapping[entry]=(hashlib.md5(candidates[0]) if key=='md5map' else hashlib.sha1(candidates[0])).hexdigest()
    line=key+' = '+json.dumps(mapping,separators=(',',':'))
   lines.append(line)
  updates[name]=('\n'.join(lines)+'\n').encode()
out=io.BytesIO()
with zipfile.ZipFile(out,'w') as w:
 for info in z.infolist():w.writestr(info,updates[info.filename])
patched=out.getvalue();zipfile.ZipFile(io.BytesIO(patched)).testzip()
meta={'path':str(p),'backup':str(backup),'original_sha256':digest,'patched_sha256':hashlib.sha256(patched).hexdigest(),'readonly':True}
record.write_text(json.dumps(meta,indent=2));record.chmod(0o600)
tmp=p.with_name('main.baiya-probe.tmp');tmp.write_bytes(patched);os.chmod(tmp,p.stat().st_mode);os.replace(tmp,p)
print('Read-only probe installed in subscription resource package; original backed up.')
