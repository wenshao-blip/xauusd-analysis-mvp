"""仅绑定本机的手动分析控制口；不接受命令、路径或交易参数。"""
import json,subprocess,sys,threading,time
from datetime import datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo
HERE=Path(__file__).resolve().parent
BJ=ZoneInfo('Asia/Shanghai')
running=threading.Lock()

def run_workflow(*args):
    if not running.acquire(blocking=False):
        return None
    try:
        return subprocess.run([sys.executable,str(HERE/'workflow.py'),*args],cwd=HERE,capture_output=True,text=True,timeout=120,encoding='utf-8',errors='replace')
    finally:
        running.release()

def scheduled_loop():
    """The local bridge runs in the signed-in user's session, where MT5 and secrets exist."""
    completed=set()
    while True:
        now=datetime.now(BJ)
        key=f'{now:%Y%m%d%H}'
        args=None
        if now.minute < 3 and now.hour % 2 == 0:
            args=[]
        elif now.minute < 3 and now.hour == 21:
            args=['--supplemental']
        if args is not None and key not in completed:
            completed.add(key)
            completed={x for x in completed if x.startswith(f'{now:%Y%m%d}')}
            threading.Thread(target=run_workflow,args=tuple(args),daemon=True).start()
        time.sleep(20)
class Handler(BaseHTTPRequestHandler):
    def cors(self):
        origin=self.headers.get('Origin','')
        if origin in {'http://localhost:3000','http://127.0.0.1:3000'}:self.send_header('Access-Control-Allow-Origin',origin)
    def do_OPTIONS(self):self.send_response(204);self.cors();self.send_header('Access-Control-Allow-Methods','POST,OPTIONS');self.end_headers()
    def do_POST(self):
        if self.path not in {'/run','/run-scheduled'}:self.send_error(404);return
        result=run_workflow('--manual') if self.path=='/run' else run_workflow()
        if result is None:
            self.send_response(409);self.cors();self.send_header('Content-Type','application/json; charset=utf-8');self.end_headers();self.wfile.write(json.dumps({'ok':False,'error':'已有分析正在运行，请稍后再试'},ensure_ascii=False).encode());return
        payload={'ok':result.returncode==0,'output':result.stdout,'error':result.stderr}
        self.send_response(200 if result.returncode==0 else 500);self.cors();self.send_header('Content-Type','application/json; charset=utf-8');self.end_headers();self.wfile.write(json.dumps(payload,ensure_ascii=False).encode())
    def log_message(self,fmt,*args):pass
if __name__=='__main__':
    server=ThreadingHTTPServer(('127.0.0.1',8765),Handler)
    threading.Thread(target=scheduled_loop,daemon=True).start()
    server.serve_forever()
