import os
import json
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.json"

DEFAULT_CONFIG = {
    "headscale_url": os.getenv("HEADSCALE_URL", "http://127.0.0.1:8085"),
    "api_key": os.getenv("HEADSCALE_API_KEY", ""),
    "feishu_webhook": os.getenv("FEISHU_WEBHOOK", ""),
    "enable_node_monitor": True,
    "monitor_interval_seconds": 60,
    "allow_insecure_tls": False,
    "server_name": "Headscale 控制台"
}

def load_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                config.update(saved)
        except Exception:
            pass
    return config

def save_config(new_config: dict) -> dict:
    current = load_config()
    current.update(new_config)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    return current
