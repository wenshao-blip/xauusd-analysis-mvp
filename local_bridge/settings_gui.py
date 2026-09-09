"""Simple local-only notification settings window for nontechnical users."""
import os
import tkinter as tk
from tkinter import messagebox, ttk

from notifications import send_email, send_feishu
from secure_config import load, save

FIELDS = [
    ("smtp_host", "SMTP服务器", "smtp.qq.com", False),
    ("smtp_port", "端口", "465", False),
    ("smtp_user", "发件账号", "81302383@qq.com", False),
    ("smtp_password", "QQ邮箱授权码", "", True),
    ("email_to", "收件邮箱", "156934912@qq.com", False),
    ("feishu_webhook", "飞书 Webhook（可暂不填）", "", True),
]


def apply_env(config):
    mapping = {
        "smtp_host": "AURUM_SMTP_HOST", "smtp_port": "AURUM_SMTP_PORT",
        "smtp_user": "AURUM_SMTP_USER", "smtp_password": "AURUM_SMTP_PASSWORD",
        "email_to": "AURUM_EMAIL_TO", "feishu_webhook": "AURUM_FEISHU_WEBHOOK",
    }
    for key, env_name in mapping.items():
        if config.get(key):
            os.environ[env_name] = config[key]


def main():
    current = load()
    root = tk.Tk(); root.title("Aurum Signal 推送设置"); root.geometry("620x430")
    frame = ttk.Frame(root, padding=22); frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="邮件与飞书推送设置", font=("Microsoft YaHei UI", 16, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
    ttk.Label(frame, text="授权码和 Webhook 保存在 Windows 凭据管理器，不会上传到 GitHub。", foreground="#555").grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 15))
    entries = {}
    for row, (key, label, default, secret) in enumerate(FIELDS, start=2):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=6)
        entry = ttk.Entry(frame, width=52, show="●" if secret else "")
        entry.insert(0, current.get(key, default)); entry.grid(row=row, column=1, sticky="ew", pady=6)
        entries[key] = entry
    frame.columnconfigure(1, weight=1)

    def values(): return {key: entry.get().strip() for key, entry in entries.items()}
    def save_only():
        save(values()); messagebox.showinfo("保存成功", "密码已保存到 Windows 凭据管理器。")
    def test_email():
        cfg=values()
        if not cfg["smtp_password"]: return messagebox.showwarning("缺少授权码", "请填写新生成的 QQ 邮箱授权码。")
        try:
            apply_env(cfg); result=send_email("Aurum Signal 邮件测试", "邮件推送配置成功。")
            if result.get("ok"): save(cfg); messagebox.showinfo("测试成功", "测试邮件已发送，请检查收件箱。")
            else: messagebox.showerror("测试失败", str(result))
        except Exception as exc: messagebox.showerror("测试失败", str(exc))
    def test_feishu():
        cfg=values()
        if not cfg["feishu_webhook"]: return messagebox.showwarning("缺少地址", "请先填写飞书机器人 Webhook。")
        try:
            apply_env(cfg); result=send_feishu("黄金：Aurum Signal 飞书测试")
            if result.get("ok"): save(cfg); messagebox.showinfo("测试成功", "飞书测试消息已发送。")
            else: messagebox.showerror("测试失败", str(result))
        except Exception as exc: messagebox.showerror("测试失败", str(exc))
    buttons=ttk.Frame(frame); buttons.grid(row=9,column=0,columnspan=2,pady=24,sticky="e")
    ttk.Button(buttons,text="保存",command=save_only).pack(side="left",pad=5)
    ttk.Button(buttons,text="测试邮件",command=test_email).pack(side="left",pad=5)
    ttk.Button(buttons,text="测试飞书",command=test_feishu).pack(side="left",pad=5)
    root.mainloop()

if __name__ == "__main__": main()
