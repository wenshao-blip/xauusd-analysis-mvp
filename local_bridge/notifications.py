"""邮件与飞书双通道；每个通道独立报告成功/失败。"""
import json,os,smtplib,urllib.request
from email.message import EmailMessage
def send_email(subject,body):
    required=['AURUM_SMTP_HOST','AURUM_SMTP_USER','AURUM_SMTP_PASSWORD','AURUM_EMAIL_TO']; missing=[x for x in required if not os.getenv(x)]
    if missing:return {'ok':False,'reason':'missing:'+','.join(missing)}
    msg=EmailMessage();msg['Subject']=subject;msg['From']=os.environ['AURUM_SMTP_USER'];msg['To']=os.environ['AURUM_EMAIL_TO'];msg.set_content(body)
    with smtplib.SMTP_SSL(os.environ['AURUM_SMTP_HOST'],int(os.getenv('AURUM_SMTP_PORT','465')),timeout=15) as s:s.login(os.environ['AURUM_SMTP_USER'],os.environ['AURUM_SMTP_PASSWORD']);s.send_message(msg)
    return {'ok':True}

def send_feishu(subject,body):
    url=os.getenv('AURUM_FEISHU_WEBHOOK')
    if not url:return {'ok':False,'reason':'missing:AURUM_FEISHU_WEBHOOK'}
    payload=json.dumps({'msg_type':'text','content':{'text':subject+'\n'+body}},ensure_ascii=False).encode('utf-8')
    with urllib.request.urlopen(urllib.request.Request(url,data=payload,headers={'Content-Type':'application/json'}),timeout=15) as r:
        response=json.loads(r.read().decode('utf-8'))
    return {'ok':response.get('code',response.get('StatusCode',0))==0,'response':response}

def send_all(subject,body):
    result={}
    for name,fn in [('email',send_email),('feishu',send_feishu)]:
        try:result[name]=fn(subject,body)
        except Exception as exc:result[name]={'ok':False,'reason':str(exc)}
    return result
def send_feishu(body):
    url=os.getenv('AURUM_FEISHU_WEBHOOK')
    if not url:return {'ok':False,'reason':'missing:AURUM_FEISHU_WEBHOOK'}
    req=urllib.request.Request(url,data=json.dumps({'msg_type':'text','content':{'text':body}},ensure_ascii=False).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=15) as r:return {'ok':200<=r.status<300,'status':r.status}
def send_all(subject,body):
    out={}
    for name,fn,args in [('email',send_email,(subject,body)),('feishu',send_feishu,(body,))]:
        try:out[name]=fn(*args)
        except Exception as exc:out[name]={'ok':False,'reason':str(exc)}
    return out
