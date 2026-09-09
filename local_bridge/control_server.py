"""仅绑定本机的手动分析控制口；不接受命令、路径或交易参数。"""
import json,subprocess,sys
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
HERE=Path(__file__).resolve().parent
class Handler(BaseHTTPRequestHandler):
    def cors(self):
        origin=self.headers.get('Origin','')
        if origin in {'http://localhost:3000','http://127.0.0.1:3000'}:self.send_header('Access-Control-Allow-Origin',origin)
    def do_OPTIONS(self):self.send_response(204);self.cors();self.send_header('Access-Control-Allow-Methods','POST,OPTIONS');self.end_headers()
    def do_POST(self):
        if self.path!='/run':self.send_error(404);return
        result=subprocess.run([sys.executable,str(HERE/'workflow.py'),'--manual','--no-push'],cwd=HERE,capture_output=True,text=True,timeout=90,encoding='utf-8',errors='replace')
        payload={'ok':result.returncode==0,'output':result.stdout,'error':result.stderr}
        self.send_response(200 if result.returncode==0 else 500);self.cors();self.send_header('Content-Type','application/json; charset=utf-8');self.end_headers();self.wfile.write(json.dumps(payload,ensure_ascii=False).encode())
    def log_message(self,fmt,*args):pass
if __name__=='__main__':ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()

