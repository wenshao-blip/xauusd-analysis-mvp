"""Local control, persistent scheduling checks, and bounded reconciliation retries."""
import json,subprocess,sys,threading,time,os
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo
import operations
from prediction_ledger import connect

HERE=Path(__file__).resolve().parent
DB=HERE/'aurum.db'
BJ=ZoneInfo('Asia/Shanghai')
running=threading.Lock()


def status():
    db=connect(DB)
    try:
        return operations.health(db,datetime.now(timezone.utc))
    finally:
        db.close()


def run_workflow(*args):
    if not running.acquire(blocking=False):
        return None
    try:
        try:
            result=subprocess.run([sys.executable,str(HERE/'workflow.py'),*args],cwd=HERE,
                capture_output=True,text=True,timeout=240,encoding='utf-8',errors='replace',
                env={**os.environ,'PYTHONIOENCODING':'utf-8'})
        except subprocess.TimeoutExpired:
            result=subprocess.CompletedProcess([],1,'','运行超时；后台将重新核查')
        except OSError:
            result=subprocess.CompletedProcess([],1,'','无法启动分析进程')
        if result.returncode not in (0,3):
            db=connect(DB)
            try:
                operations.initialize(db,datetime.now(timezone.utc))
                # The OS process lock is released after timeout/crash. Preserve any report ID.
                db.execute("UPDATE operation_runs SET code='interrupted',stage='finished',finished_at=? WHERE code='running'",
                           (operations.stamp(datetime.now(timezone.utc)),))
                db.commit()
            finally:
                db.close()
        return result
    finally:
        running.release()


def scheduled_due(db,now):
    local=now.astimezone(BJ)
    if local.minute>=10 or not (local.hour%2==0 or local.hour==21):
        return None
    kind='supplemental' if local.hour==21 else 'scheduled_2h'
    key=operations.job_key(now,kind)
    row=db.execute('SELECT * FROM operation_runs WHERE id=?',(key,)).fetchone()
    if row:
        if (row['report_id'] and row['code']!='shadow_error') or row['code']=='ok':
            return None
        age=(now-datetime.fromisoformat(row['started_at'])).total_seconds()
        if age<60:
            return None
        if row['code']=='stale_quote' and local.weekday()>=5:
            return None
    return ['--supplemental'] if kind=='supplemental' else []


def reconcile():
    run_workflow('--reconcile-only','--no-push','--no-publish')
    db=connect(DB)
    try:
        pending=operations.get(db,'publish_pending')=='1'
    finally:
        db.close()
    if pending:
        run_workflow('--retry-publish','--no-push')


def scheduled_loop():
    next_reconcile=0
    while True:
        try:
            now=datetime.now(timezone.utc)
            db=connect(DB)
            try:
                operations.initialize(db,now)
                operations.set_value(db,'heartbeat',operations.stamp(now))
                args=scheduled_due(db,now)
                report=operations.health(db,now)
                # Existing configured destinations only; no test messages or new recipients.
                try:
                    from notifications import send_all
                    operations.notify_changes(db,report,now,send_all)
                except Exception:
                    operations.set_value(db,'alert_delivery','failed')
            finally:
                db.close()
            if not running.locked():
                if args is not None:
                    threading.Thread(target=run_workflow,args=tuple(args),daemon=True).start()
                elif time.monotonic()>=next_reconcile:
                    next_reconcile=time.monotonic()+300
                    threading.Thread(target=reconcile,daemon=True).start()
        except Exception:
            # The next heartbeat retries. A stopped loop remains visible as an expired heartbeat.
            pass
        time.sleep(20)


class Handler(BaseHTTPRequestHandler):
    def cors(self):
        origin=self.headers.get('Origin','')
        if origin in {'http://localhost:3000','http://127.0.0.1:3000'}:
            self.send_header('Access-Control-Allow-Origin',origin)

    def respond(self,code,payload):
        self.send_response(code);self.cors()
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store');self.end_headers()
        self.wfile.write(json.dumps(payload,ensure_ascii=False).encode('utf-8'))

    def do_GET(self):
        if self.path!='/health':
            self.send_error(404);return
        try:
            self.respond(200,status())
        except Exception:
            self.respond(503,{'error':'运行记录暂时无法读取'})

    def do_OPTIONS(self):
        self.send_response(204);self.cors()
        self.send_header('Access-Control-Allow-Methods','GET,POST,OPTIONS');self.end_headers()

    def do_POST(self):
        if self.path not in {'/run','/run-scheduled'}:
            self.send_error(404);return
        result=run_workflow('--manual') if self.path=='/run' else run_workflow()
        if result is None or result.returncode==3:
            self.respond(409,{'ok':False,'error':'已有分析正在运行，请稍后再试'});return
        self.respond(200 if result.returncode==0 else 500,
                     {'ok':result.returncode==0,'output':result.stdout,'error':result.stderr})

    def log_message(self,fmt,*args):
        pass


if __name__=='__main__':
    server=ThreadingHTTPServer(('127.0.0.1',8765),Handler)
    threading.Thread(target=scheduled_loop,daemon=True).start()
    server.serve_forever()
