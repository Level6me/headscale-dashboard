import os
import re
import ssl
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

CERTS_DIR = Path("/etc/headscale/certs")
FALLBACK_CERTS_DIR = Path(__file__).parent / "certs"
HEADSCALE_CONFIG_FILE = Path("/etc/headscale/config.yaml")

def get_certs_dir() -> Path:
    if CERTS_DIR.exists() or Path("/etc/headscale").exists():
        CERTS_DIR.mkdir(parents=True, exist_ok=True)
        return CERTS_DIR
    FALLBACK_CERTS_DIR.mkdir(parents=True, exist_ok=True)
    return FALLBACK_CERTS_DIR

def parse_certificate(cert_pem: str, key_pem: Optional[str] = None) -> Dict[str, Any]:
    """解析 PEM 证书和私钥并校验配对性"""
    if not cert_pem or "-----BEGIN CERTIFICATE-----" not in cert_pem:
        raise ValueError("无效的证书内容，必须包含 -----BEGIN CERTIFICATE----- 格式的 PEM 文本")

    with tempfile.NamedTemporaryFile("w", suffix=".crt", delete=False) as f_cert:
        f_cert.write(cert_pem.strip() + "\n")
        cert_path = f_cert.name

    key_path = None
    if key_pem and ("-----BEGIN" in key_pem and "PRIVATE KEY-----" in key_pem):
        with tempfile.NamedTemporaryFile("w", suffix=".key", delete=False) as f_key:
            f_key.write(key_pem.strip() + "\n")
            key_path = f_key.name

    result: Dict[str, Any] = {
        "valid": True,
        "subject_cn": "",
        "issuer": "",
        "not_before": "",
        "not_after": "",
        "days_remaining": 0,
        "is_expired": False,
        "sans": [],
        "key_match": None,
        "key_type": "",
    }

    try:
        # 1. 解析基础元数据
        cmd = ["openssl", "x509", "-in", cert_path, "-noout", "-subject", "-issuer", "-dates"]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        for line in out.strip().split("\n"):
            line = line.strip()
            if line.startswith("subject="):
                # 提取 CN
                subj = line.replace("subject=", "").strip()
                cn_match = re.search(r"CN\s*=\s*([^/,]+)", subj)
                result["subject_cn"] = cn_match.group(1).strip() if cn_match else subj
            elif line.startswith("issuer="):
                iss = line.replace("issuer=", "").strip()
                # 尝试提取 O 或 CN
                o_match = re.search(r"O\s*=\s*([^/,]+)", iss)
                cn_match = re.search(r"CN\s*=\s*([^/,]+)", iss)
                if o_match:
                    result["issuer"] = o_match.group(1).strip()
                elif cn_match:
                    result["issuer"] = cn_match.group(1).strip()
                else:
                    result["issuer"] = iss
            elif line.startswith("notBefore="):
                nb = line.replace("notBefore=", "").strip()
                result["not_before"] = nb
            elif line.startswith("notAfter="):
                na = line.replace("notAfter=", "").strip()
                result["not_after"] = na
                try:
                    # 格式: Sep 19 02:27:41 2026 GMT
                    exp_dt = datetime.strptime(na, "%b %d %H:%M:%S %Y %Z")
                    now_dt = datetime.utcnow()
                    delta = exp_dt - now_dt
                    result["days_remaining"] = delta.days
                    result["is_expired"] = delta.total_seconds() <= 0
                except Exception:
                    pass

        # 2. 提取备用名称 SANs
        try:
            san_out = subprocess.check_output(["openssl", "x509", "-in", cert_path, "-noout", "-ext", "subjectAltName"], stderr=subprocess.DEVNULL, text=True)
            raw_sans = san_out.replace("X509v3 Subject Alternative Name:", "").strip()
            sans_list = []
            for item in raw_sans.split(","):
                item = item.strip()
                if item.startswith("DNS:"):
                    sans_list.append(item.replace("DNS:", "").strip())
                elif item.startswith("IP Address:"):
                    sans_list.append(item.replace("IP Address:", "").strip())
            result["sans"] = sans_list
        except Exception:
            result["sans"] = [result["subject_cn"]] if result["subject_cn"] else []

        # 3. 校验私钥配对
        if key_path:
            # 检测私钥类型
            try:
                # 尝试 RSA
                cert_mod = subprocess.check_output(["openssl", "x509", "-noout", "-modulus", "-in", cert_path], stderr=subprocess.DEVNULL, text=True).strip()
                key_mod = subprocess.check_output(["openssl", "rsa", "-noout", "-modulus", "-in", key_path], stderr=subprocess.DEVNULL, text=True).strip()
                result["key_match"] = (cert_mod == key_mod and bool(cert_mod))
                result["key_type"] = "RSA"
            except Exception:
                # 尝试通用 PKEY (ECC / ECDSA / ED25519)
                try:
                    cert_pub = subprocess.check_output(["openssl", "x509", "-in", cert_path, "-pubkey", "-noout"], stderr=subprocess.DEVNULL, text=True).strip()
                    key_pub = subprocess.check_output(["openssl", "pkey", "-in", key_path, "-pubout"], stderr=subprocess.DEVNULL, text=True).strip()
                    result["key_match"] = (cert_pub == key_pub and bool(cert_pub))
                    result["key_type"] = "EC/PKEY"
                except Exception:
                    result["key_match"] = False
                    result["key_type"] = "Unknown"

    except subprocess.CalledProcessError as e:
        raise ValueError(f"OpenSSL 解析证书失败: {e.output}")
    finally:
        if os.path.exists(cert_path):
            os.remove(cert_path)
        if key_path and os.path.exists(key_path):
            os.remove(key_path)

    return result

def get_installed_cert_info() -> Optional[Dict[str, Any]]:
    """获取当前已部署的证书信息"""
    certs_dir = get_certs_dir()
    cert_file = certs_dir / "tls.crt"
    key_file = certs_dir / "tls.key"

    if not cert_file.exists():
        return None

    try:
        with open(cert_file, "r", encoding="utf-8") as f:
            cert_pem = f.read()
        key_pem = None
        if key_file.exists():
            with open(key_file, "r", encoding="utf-8") as f:
                key_pem = f.read()
        info = parse_certificate(cert_pem, key_pem)
        info["cert_path"] = str(cert_file)
        info["key_path"] = str(key_file)
        return info
    except Exception:
        return None

def save_certificate_files(cert_pem: str, key_pem: str) -> Dict[str, str]:
    """将证书与私钥持久化写入系统目录"""
    certs_dir = get_certs_dir()
    cert_file = certs_dir / "tls.crt"
    key_file = certs_dir / "tls.key"

    with open(cert_file, "w", encoding="utf-8") as f:
        f.write(cert_pem.strip() + "\n")
    os.chmod(cert_file, 0o644)

    with open(key_file, "w", encoding="utf-8") as f:
        f.write(key_pem.strip() + "\n")
    os.chmod(key_file, 0o600)

    return {
        "cert_path": str(cert_file),
        "key_path": str(key_file)
    }

def read_headscale_config() -> Dict[str, Any]:
    """读取宿主机 /etc/headscale/config.yaml 中的关键配置"""
    if not HEADSCALE_CONFIG_FILE.exists():
        return {
            "exists": False,
            "path": str(HEADSCALE_CONFIG_FILE),
            "server_url": "",
            "listen_addr": "",
            "tls_cert_path": "",
            "tls_key_path": ""
        }

    try:
        content = HEADSCALE_CONFIG_FILE.read_text(encoding="utf-8")
        server_url_match = re.search(r"^\s*server_url:\s*([^\n#]+)", content, re.MULTILINE)
        listen_addr_match = re.search(r"^\s*listen_addr:\s*([^\n#]+)", content, re.MULTILINE)
        tls_cert_match = re.search(r"^\s*tls_cert_path:\s*([^\n#]*)", content, re.MULTILINE)
        tls_key_match = re.search(r"^\s*tls_key_path:\s*([^\n#]*)", content, re.MULTILINE)

        return {
            "exists": True,
            "path": str(HEADSCALE_CONFIG_FILE),
            "server_url": server_url_match.group(1).strip().strip('"\'') if server_url_match else "",
            "listen_addr": listen_addr_match.group(1).strip().strip('"\'') if listen_addr_match else "",
            "tls_cert_path": tls_cert_match.group(1).strip().strip('"\'') if tls_cert_match else "",
            "tls_key_path": tls_key_match.group(1).strip().strip('"\'') if tls_key_match else ""
        }
    except Exception as e:
        return {
            "exists": True,
            "path": str(HEADSCALE_CONFIG_FILE),
            "error": str(e)
        }

def update_headscale_server_url(new_server_url: str) -> bool:
    """安全更新 /etc/headscale/config.yaml 中的 server_url"""
    if not HEADSCALE_CONFIG_FILE.exists():
        return False
    try:
        content = HEADSCALE_CONFIG_FILE.read_text(encoding="utf-8")
        clean_url = new_server_url.strip().rstrip("/")
        # 使用正则替换，保留原有缩进和注释
        new_content, count = re.subn(
            r"^(\s*server_url:\s*)[^\n#]+(.*)$",
            rf"\g<1>{clean_url}\g<2>",
            content,
            flags=re.MULTILINE
        )
        if count == 0:
            # 如果没找到，追加到顶部
            new_content = f"server_url: {clean_url}\n" + content
        HEADSCALE_CONFIG_FILE.write_text(new_content, encoding="utf-8")
        return True
    except Exception:
        return False

def update_headscale_tls_paths(cert_path: str, key_path: str) -> bool:
    """更新 /etc/headscale/config.yaml 中的 tls_cert_path 与 tls_key_path"""
    if not HEADSCALE_CONFIG_FILE.exists():
        return False
    try:
        content = HEADSCALE_CONFIG_FILE.read_text(encoding="utf-8")
        content, _ = re.subn(r"^(\s*tls_cert_path:\s*)[^\n#]*(.*)$", rf'\g<1>"{cert_path}"\g<2>', content, flags=re.MULTILINE)
        content, _ = re.subn(r"^(\s*tls_key_path:\s*)[^\n#]*(.*)$", rf'\g<1>"{key_path}"\g<2>', content, flags=re.MULTILINE)
        HEADSCALE_CONFIG_FILE.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False

def reload_headscale_service() -> bool:
    """尝试通过发送信号触发 Headscale 配置重载"""
    try:
        subprocess.run(["pkill", "-HUP", "headscale"], check=False)
        return True
    except Exception:
        return False

def get_derp_info() -> Dict[str, Any]:
    """读取 DERP 中继配置与状态"""
    info = {
        "server_enabled": False,
        "region_id": 999,
        "region_code": "headscale",
        "region_name": "Headscale Embedded DERP",
        "stun_listen_addr": "0.0.0.0:3478",
        "urls": [],
        "paths": []
    }
    if HEADSCALE_CONFIG_FILE.exists():
        try:
            content = HEADSCALE_CONFIG_FILE.read_text(encoding="utf-8")
            m_enabled = re.search(r"^\s*enabled:\s*(true|false)", content, re.MULTILINE | re.IGNORECASE)
            m_rid = re.search(r"^\s*region_id:\s*(\d+)", content, re.MULTILINE)
            m_rcode = re.search(r"^\s*region_code:\s*([^\n#]+)", content, re.MULTILINE)
            m_rname = re.search(r"^\s*region_name:\s*([^\n#]+)", content, re.MULTILINE)
            m_stun = re.search(r"^\s*stun_listen_addr:\s*([^\n#]+)", content, re.MULTILINE)

            if m_enabled:
                info["server_enabled"] = m_enabled.group(1).lower() == "true"
            if m_rid:
                info["region_id"] = int(m_rid.group(1))
            if m_rcode:
                info["region_code"] = m_rcode.group(1).strip().strip('"\'')
            if m_rname:
                info["region_name"] = m_rname.group(1).strip().strip('"\'')
            if m_stun:
                info["stun_listen_addr"] = m_stun.group(1).strip().strip('"\'')
        except Exception:
            pass
    return info

