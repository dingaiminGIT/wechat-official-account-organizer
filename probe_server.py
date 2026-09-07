from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
import json,secrets,datetime
ROOT=Path(__file__).resolve().parent
RUNTIME=ROOT/'.runtime';RUNTIME.mkdir(exist_ok=True)
TOKEN=secrets.token_urlsafe(24)
(RUNTIME/'endpoint').write_text('http://127.0.0.1:8877/collect/'+TOKEN)
(RUNTIME/'endpoint').chmod(0o600)
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def headers_(self):
  self.send_header('Access-Control-Allow-Origin','*');self.send_header('Access-Control-Allow-Private-Network','true');self.send_header('Access-Control-Allow-Headers','Content-Type');self.send_header('Access-Control-Allow-Methods','POST, OPTIONS');self.send_header('Cache-Control','no-store')
 def do_OPTIONS(self):
  self.send_response(204);self.headers_();self.end_headers()
 def do_GET(self):
  if self.path!='/status':self.send_error(404);return
  p=RUNTIME/'events.jsonl';events=[json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []
  b=json.dumps(events,ensure_ascii=False).encode();self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.end_headers();self.wfile.write(b)
 def do_POST(self):
  if self.path!='/collect/'+TOKEN:self.send_error(404);return
  n=int(self.headers.get('Content-Length','0'))
  if n>2_000_000:self.send_error(413);return
  try: obj=json.loads(self.rfile.read(n))
  except Exception:self.send_error(400);return
  obj['receivedAt']=datetime.datetime.now().isoformat()
  with (RUNTIME/'events.jsonl').open('a') as f:f.write(json.dumps(obj,ensure_ascii=False)+'\n')
  (RUNTIME/'events.jsonl').chmod(0o600)
  self.send_response(204);self.headers_();self.end_headers()
ThreadingHTTPServer(('127.0.0.1',8877),Handler).serve_forever()
