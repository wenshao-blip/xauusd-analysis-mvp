"""Store secrets in Windows Credential Manager and ordinary settings locally."""
import json
from pathlib import Path
import keyring

CONFIG_PATH = Path(__file__).with_name("aurum_config.json")
SERVICE = "Aurum Signal"
SECRET_KEYS = ("smtp_password", "feishu_webhook")

def load() -> dict:
    values = json.loads(CONFIG_PATH.read_text("utf-8")) if CONFIG_PATH.exists() else {}
    for key in SECRET_KEYS:
        try:
            secret = keyring.get_password(SERVICE, key)
        except Exception:
            secret = None
        if secret:
            values[key] = secret
    return values

def save(values: dict) -> None:
    public_values = {k: v for k, v in values.items() if k not in SECRET_KEYS}
    CONFIG_PATH.write_text(json.dumps(public_values, ensure_ascii=False, indent=2), "utf-8")
    for key in SECRET_KEYS:
        if values.get(key):
            keyring.set_password(SERVICE, key, values[key])
