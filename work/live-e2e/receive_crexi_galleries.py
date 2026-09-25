import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse,parse_qs
root=Path('data/imports')
out=root/'crexi_extra_galleries.json'
valid={str(x['id']) for x in json.loads((root/'commercial_listings.json').read_text())}
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  q=parse_qs(urlparse(self.path).query)
  try:
   id=q['id'][0]
   if id not in valid:raise ValueError('Unknown property')
   data=json.loads(q['payload'][0])
   if len(data.get('images',[]))>150 or not all(u.startswith('https://crexi.com/images/') and '/assets/'+id+'/' in u for u in data.get('images',[])):raise ValueError('Invalid gallery')
   saved=json.loads(out.read_text()) if out.exists() and out.stat().st_size else {}
   saved[id]=data
   out.write_text(json.dumps(saved,indent=2))
   self.send_response(200);self.end_headers();self.wfile.write(b'OK')
  except Exception as e:
   self.send_response(400);self.end_headers();self.wfile.write(type(e).__name__.encode())
 def log_message(self,*args):pass
HTTPServer(('127.0.0.1',8765),Handler).serve_forever()
