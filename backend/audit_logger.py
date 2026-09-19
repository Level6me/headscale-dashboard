import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger("HeadscaleDashboard.Audit")
AUDIT_LOG_FILE = Path(__file__).parent / "audit_logs.json"
MAX_LOG_ENTRIES = 500

def _load_raw_logs() -> List[Dict[str, Any]]:
    if not AUDIT_LOG_FILE.exists():
        return []
    try:
        with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception as e:
        logger.warning(f"Failed to read audit logs: {e}")
    return []

def _save_raw_logs(logs: List[Dict[str, Any]]) -> None:
    try:
        # 仅保留最近 MAX_LOG_ENTRIES 条
        trimmed = logs[-MAX_LOG_ENTRIES:]
        with open(AUDIT_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to write audit logs: {e}")

def record_audit_log(
    action: str,
    target: str,
    detail: str = "",
    client_ip: str = "",
    operator: str = "admin",
    status: str = "success"
) -> Dict[str, Any]:
    """记录一条控制台安全审计日志"""
    entry = {
        "id": int(datetime.utcnow().timestamp() * 1000),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "target": target,
        "detail": detail,
        "client_ip": client_ip,
        "operator": operator,
        "status": status
    }
    logs = _load_raw_logs()
    logs.append(entry)
    _save_raw_logs(logs)
    logger.info(f"[AUDIT] {operator} -> {action} on {target} [{status}]: {detail}")
    return entry

def get_audit_logs(limit: int = 100) -> List[Dict[str, Any]]:
    """获取倒序排列的最新审计日志"""
    logs = _load_raw_logs()
    logs.reverse()
    return logs[:limit]

def clear_audit_logs() -> bool:
    """清空审计日志"""
    try:
        _save_raw_logs([])
        return True
    except Exception:
        return False
