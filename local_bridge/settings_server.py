"""Local-only browser settings page; never listens outside this computer."""
import html
import json
import os
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from notifications import send_all, send_email, send_feishu
from report_formatter import build_report
from secure_config import load, save

HOST, PORT = "127.0.0.1", 8766
DASHBOARD = Path(__file__).resolve().parents[1] / "public" / "data" / "dashboard.json"

def apply_env(config):
    mapping={"smtp_host":"AURUM_SMTP_HOST","smtp_port":"AURUM_SMTP_PORT","smtp_user":"AURUM_SMTP_USER","smtp_password":"AURUM_SMTP_PASSWORD","email_to":"AURUM_EMAIL_TO","feishu_webhook":"AURUM_FEISHU_WEBHOOK"}
    for key,name in mapping.items():
        if config.get(key): os.environ[name]=config[key]

def latest_report():
    return build_report(json.loads(DASHBOARD.read_text("utf-8"))["current"])

def page(message=""):
    c=load()
    def value(k,d=""): return html.escape(c.get(k,d),quote=True)
    notice=f'<div class="notice">{html.escape(message)}</div>' if message else ''
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Aurum Signal 推送设置</title>
<style>body{{font-family:"Microsoft YaHei",sans-serif;background:#f4f1e8;color:#17221d;margin:0}}main{{max-width:680px;margin:36px auto;background:white;padding:28px;border-radius:18px;box-shadow:0 12px 35px #0002}}label{{display:block;margin:15px 0 6px;font-weight:600}}input{{box-sizing:border-box;width:100%;padding:12px;border:1px solid #bbb;border-radius:9px;font-size:16px}}button{{margin:22px 8px 0 0;padding:11px 18px;border:0;border-radius:9px;background:#166534;color:white;font-size:15px;cursor:pointer}}.muted{{color:#667;font-size:14px}}.notice{{padding:12px;background:#ecfdf5;border-radius:8px;margin:12px 0}}</style>
<main><h1>邮件与飞书推送设置</h1><p class="muted">此页面只在本机 127.0.0.1 打开。授权码与 Webhook 不会上传到 GitHub。</p>{notice}<form method="post">
<label>SMTP服务器</label><input name="smtp_host" value="{value('smtp_host','smtp.qq.com')}">
<label>端口</label><input name="smtp_port" value="{value('smtp_port','465')}">
<label>发件账号</label><input name="smtp_user" value="{value('smtp_user','81302383@qq.com')}">
<label>新的 QQ 邮箱授权码</label><input type="password" name="smtp_password" placeholder="已保存时可留空">
<label>收件邮箱</label><input name="email_to" value="{value('email_to','156934912@qq.com')}">
<label>飞书 Webhook（可暂不填）</label><input type="password" name="feishu_webhook" placeholder="已保存时可留空">
<button name="action" value="save">保存</button><button name="action" value="email">保存并测试邮件</button><button name="action" value="feishu">保存并测试飞书</button><button name="action" value="report">发送上一次完整报告</button></form></main></html>'''

class Handler(BaseHTTPRequestHandler):
    def respond(self, content, status=200):
        data=content.encode("utf-8"); self.send_response(status); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self): self.respond(page())
    def do_POST(self):
        length=int(self.headers.get("Content-Length","0")); form=urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8")); old=load(); cfg={k:v[-1].strip() for k,v in form.items() if k!="action"}
        for secret in ("smtp_password","feishu_webhook"):
            if not cfg.get(secret) and old.get(secret): cfg[secret]=old[secret]
        try:
            save(cfg); apply_env(cfg); action=form.get("action",["save"])[-1]
            if action=="email": result=send_email("Aurum Signal 邮件测试","邮件推送配置成功。"); message="测试邮件已发送，请检查收件箱。" if result.get("ok") else "邮件测试失败："+str(result)
            elif action=="feishu": result=send_feishu("黄金：Aurum Signal 飞书测试","飞书推送配置成功。"); message="飞书测试消息已发送。" if result.get("ok") else "飞书测试失败："+str(result)
            elif action=="report":
                subject,body=latest_report(); result=send_all(subject,body)
                message="上一次完整报告已通过邮件和飞书发送。" if all(x.get("ok") for x in result.values()) else "报告发送失败："+str(result)
            else: message="配置已安全保存。"
        except Exception as exc: message="操作失败："+str(exc)
        self.respond(page(message))
    def log_message(self, *_): pass

if __name__ == "__main__":
    server=ThreadingHTTPServer((HOST,PORT),Handler)
    threading.Timer(0.8,lambda:webbrowser.open(f"http://{HOST}:{PORT}")).start()
    server.serve_forever()
