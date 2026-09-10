"""Email and Feishu notifications with verified provider responses."""
import json
import os
import smtplib
import urllib.request
from email.message import EmailMessage

from secure_config import load as load_secure_config


def _load_local_settings():
    config = load_secure_config()
    mapping = {
        "smtp_host": "AURUM_SMTP_HOST", "smtp_port": "AURUM_SMTP_PORT",
        "smtp_user": "AURUM_SMTP_USER", "smtp_password": "AURUM_SMTP_PASSWORD",
        "email_to": "AURUM_EMAIL_TO", "feishu_webhook": "AURUM_FEISHU_WEBHOOK",
    }
    for key, name in mapping.items():
        if config.get(key) and not os.getenv(name):
            os.environ[name] = config[key]


def send_email(subject, body):
    _load_local_settings()
    required = ["AURUM_SMTP_HOST", "AURUM_SMTP_USER", "AURUM_SMTP_PASSWORD", "AURUM_EMAIL_TO"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        return {"ok": False, "reason": "missing:" + ",".join(missing)}
    msg = EmailMessage()
    msg["Subject"] = subject; msg["From"] = os.environ["AURUM_SMTP_USER"]; msg["To"] = os.environ["AURUM_EMAIL_TO"]
    msg.set_content(body)
    with smtplib.SMTP_SSL(os.environ["AURUM_SMTP_HOST"], int(os.getenv("AURUM_SMTP_PORT", "465")), timeout=15) as server:
        server.login(os.environ["AURUM_SMTP_USER"], os.environ["AURUM_SMTP_PASSWORD"])
        server.send_message(msg)
    return {"ok": True}


def send_feishu(subject, body=""):
    _load_local_settings()
    url = os.getenv("AURUM_FEISHU_WEBHOOK")
    if not url:
        return {"ok": False, "reason": "missing:AURUM_FEISHU_WEBHOOK"}
    payload = json.dumps({"msg_type": "text", "content": {"text": subject + ("\n" + body if body else "")}}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.loads(response.read().decode("utf-8"))
    code = result.get("code", result.get("StatusCode", 0))
    return {"ok": code == 0, "response": result}


def send_all(subject, body):
    output = {}
    for name, function in (("email", send_email), ("feishu", send_feishu)):
        try:
            output[name] = function(subject, body)
        except Exception as exc:
            output[name] = {"ok": False, "reason": str(exc)}
    return output
