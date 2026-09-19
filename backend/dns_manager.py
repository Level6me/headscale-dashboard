import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("HeadscaleDashboard.DNS")

HEADSCALE_CONFIG_FILE = Path("/etc/headscale/config.yaml")
FALLBACK_DNS_FILE = Path(__file__).parent / "dns_config.json"

DEFAULT_DNS_CONFIG = {
    "magic_dns": True,
    "base_domain": "net",
    "override_local_dns": True,
    "nameservers": ["1.1.1.1", "1.0.0.1", "223.5.5.5"],
    "extra_records": [],
    "synced_to_headscale": False
}

def read_dns_config() -> Dict[str, Any]:
    """读取当前 DNS 与 Extra Records 配置"""
    result = DEFAULT_DNS_CONFIG.copy()

    # 1. 尝试从 /etc/headscale/config.yaml 读取真实生效配置
    if HEADSCALE_CONFIG_FILE.exists():
        try:
            content = HEADSCALE_CONFIG_FILE.read_text(encoding="utf-8")
            # 使用正则安全提取关键字段
            m_magic = re.search(r"^\s*magic_dns:\s*(true|false)", content, re.MULTILINE | re.IGNORECASE)
            m_base = re.search(r"^\s*base_domain:\s*([^\n#]+)", content, re.MULTILINE)
            m_override = re.search(r"^\s*override_local_dns:\s*(true|false)", content, re.MULTILINE | re.IGNORECASE)

            if m_magic:
                result["magic_dns"] = m_magic.group(1).lower() == "true"
            if m_base:
                result["base_domain"] = m_base.group(1).strip().strip('"\'')
            if m_override:
                result["override_local_dns"] = m_override.group(1).lower() == "true"

            # 提取 global nameservers
            ns_match = re.search(r"nameservers:\s*\n\s*global:\s*\n((?:\s*-\s*[^\n#]+\n?)*)", content)
            if ns_match:
                lines = ns_match.group(1).splitlines()
                ns_list = []
                for line in lines:
                    line = line.strip()
                    if line.startswith("-"):
                        val = line[1:].strip().strip('"\'')
                        if val:
                            ns_list.append(val)
                if ns_list:
                    result["nameservers"] = ns_list

            # 提取 extra_records
            er_match = re.search(r"extra_records:\s*(\[.*?\]|\n(?:\s*-\s*\{.*?\}|\s*-\s*name:.*?\n(?:\s+[a-zA-Z0-9_]+:.*?\n?)*)*)", content, re.DOTALL)
            if er_match:
                raw_records = er_match.group(0)
                try:
                    import yaml
                    parsed = yaml.safe_load(raw_records)
                    if isinstance(parsed, dict) and "extra_records" in parsed and isinstance(parsed["extra_records"], list):
                        result["extra_records"] = parsed["extra_records"]
                except Exception:
                    pass

            result["synced_to_headscale"] = True
            result["config_path"] = str(HEADSCALE_CONFIG_FILE)
            return result
        except Exception as e:
            logger.warning(f"Failed to parse config.yaml for DNS: {e}")

    # 2. 回退从本地 json 读取
    if FALLBACK_DNS_FILE.exists():
        try:
            with open(FALLBACK_DNS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                result.update(saved)
        except Exception as e:
            logger.warning(f"Failed to read fallback dns_config.json: {e}")

    result["synced_to_headscale"] = HEADSCALE_CONFIG_FILE.exists()
    return result

def save_dns_config(
    magic_dns: bool,
    base_domain: str,
    override_local_dns: bool,
    nameservers: List[str],
    extra_records: List[Dict[str, str]],
    sync_to_headscale: bool = True
) -> Dict[str, Any]:
    """保存 DNS 配置并可选同步写入 /etc/headscale/config.yaml"""
    clean_ns = [str(ns).strip() for ns in nameservers if str(ns).strip()]
    clean_records = []
    for r in extra_records:
        if isinstance(r, dict) and r.get("name") and r.get("value"):
            clean_records.append({
                "name": str(r["name"]).strip(),
                "type": str(r.get("type", "A")).upper().strip(),
                "value": str(r["value"]).strip()
            })

    data_to_save = {
        "magic_dns": bool(magic_dns),
        "base_domain": str(base_domain).strip().rstrip("."),
        "override_local_dns": bool(override_local_dns),
        "nameservers": clean_ns,
        "extra_records": clean_records,
        "synced_to_headscale": False
    }

    # 1. 备份并保存本地 json
    try:
        with open(FALLBACK_DNS_FILE, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving fallback DNS json: {e}")

    # 2. 若开启同步且 config.yaml 存在，更新 config.yaml
    if sync_to_headscale and HEADSCALE_CONFIG_FILE.exists():
        try:
            # 制作备份
            backup_file = HEADSCALE_CONFIG_FILE.with_suffix(".yaml.dnsbak")
            shutil.copy2(HEADSCALE_CONFIG_FILE, backup_file)

            content = HEADSCALE_CONFIG_FILE.read_text(encoding="utf-8")

            # 替换 magic_dns
            content = re.sub(
                r"^(\s*magic_dns:\s*)(true|false)(.*)$",
                rf"\g<1>{'true' if magic_dns else 'false'}\g<3>",
                content,
                flags=re.MULTILINE | re.IGNORECASE
            )

            # 替换 base_domain
            content = re.sub(
                r"^(\s*base_domain:\s*)[^\n#]+(.*)$",
                rf"\g<1>{data_to_save['base_domain']}\g<2>",
                content,
                flags=re.MULTILINE
            )

            # 替换 override_local_dns
            content = re.sub(
                r"^(\s*override_local_dns:\s*)(true|false)(.*)$",
                rf"\g<1>{'true' if override_local_dns else 'false'}\g<3>",
                content,
                flags=re.MULTILINE | re.IGNORECASE
            )

            # 替换 global nameservers
            ns_yaml_block = "nameservers:\n    global:\n" + "\n".join([f"      - {ns}" for ns in clean_ns])
            content = re.sub(
                r"nameservers:\s*\n\s*global:\s*\n(?:\s*-\s*[^\n#]+\n?)*",
                ns_yaml_block + "\n",
                content
            )

            # 替换 extra_records
            if clean_records:
                records_lines = ["extra_records:"]
                for rec in clean_records:
                    records_lines.append(f'  - {{ name: "{rec["name"]}", type: "{rec["type"]}", value: "{rec["value"]}" }}')
                records_yaml_block = "\n".join(records_lines)
            else:
                records_yaml_block = "extra_records: []"

            content = re.sub(
                r"extra_records:\s*(?:\[.*?\]|\n(?:\s*-\s*\{.*?\}|\s*-\s*name:.*?\n(?:\s+[a-zA-Z0-9_]+:.*?\n?)*)*)",
                records_yaml_block,
                content
            )

            HEADSCALE_CONFIG_FILE.write_text(content, encoding="utf-8")
            data_to_save["synced_to_headscale"] = True

            # 尝试发送 SIGHUP 重载
            try:
                subprocess.run(["pkill", "-HUP", "headscale"], check=False)
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Failed to update /etc/headscale/config.yaml for DNS: {e}")
            data_to_save["error"] = str(e)

    return data_to_save
