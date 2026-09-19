import asyncio
import httpx
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Set
from config import load_config
from headscale_client import HeadscaleClient
from audit_logger import record_audit_log
from ws_manager import ws_manager

logger = logging.getLogger("HeadscaleMonitor")

async def send_feishu_card(webhook_url: str, title: str, content_lines: list, color: str = "red") -> bool:
    if not webhook_url:
        return False
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fields = []
    for item in content_lines:
        fields.append({
            "is_short": False,
            "text": {
                "tag": "lark_md",
                "content": item
            }
        })
    
    card_payload = {
        "msg_type": "interactive",
        "card": {
            "config": {
                "wide_screen_mode": True
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": title
                },
                "template": color  # red, green, orange, blue, etc.
            },
            "elements": [
                {
                    "tag": "div",
                    "fields": fields
                },
                {
                    "tag": "hr"
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": f"通知时间: {now_str} | Headscale 智能网络控制中心"
                        }
                    ]
                }
            ]
        }
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=card_payload)
            return resp.status_code == 200
    except Exception as e:
        logger.error(f"Failed to send feishu alert: {e}")
        return False

class NodeMonitor:
    def __init__(self):
        self._prev_nodes_status: Dict[int, bool] = {} # node_id -> is_online
        self._known_nodes: Set[int] = set()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._initialized = False

    def start(self):
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._monitor_loop())

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _monitor_loop(self):
        while self._running:
            try:
                cfg = load_config()
                if not cfg.get("enable_node_monitor", True):
                    await asyncio.sleep(15)
                    continue

                client = HeadscaleClient()
                resp = await client.get_nodes()
                if resp.status_code == 200:
                    data = resp.json()
                    nodes = data.get("nodes", []) or []
                    
                    # 广播实时更新到 WebSocket
                    await ws_manager.broadcast("nodes_update", {
                        "count": len(nodes),
                        "online_count": sum(1 for n in nodes if n.get("online", False)),
                        "timestamp": datetime.now().strftime("%H:%M:%S")
                    })

                    current_nids = set()
                    for node in nodes:
                        nid = node.get("id")
                        if not nid:
                            continue
                        current_nids.add(nid)
                        name = node.get("name") or node.get("givenName") or f"Node-{nid}"
                        user = node.get("user", {}).get("name") if isinstance(node.get("user"), dict) else str(node.get("user", "default"))
                        ips = ", ".join(node.get("ipAddresses", []))
                        is_online = node.get("online", False)

                        # 检测新设备入网
                        if self._initialized and nid not in self._known_nodes:
                            logger.info(f"New node joined Headscale: {name} (ID: {nid}, User: {user})")
                            record_audit_log(
                                action="新节点接入",
                                target=name,
                                detail=f"用户 {user} 接入新设备，分配 IP: {ips}",
                                status="info"
                            )
                            webhook = cfg.get("feishu_webhook")
                            if webhook:
                                await send_feishu_card(
                                    webhook,
                                    title=f"🎉 Headscale 新设备接入通知",
                                    content_lines=[
                                        f"**设备名称**: `{name}`",
                                        f"**所属用户**: `{user}`",
                                        f"**分配 IP**: `{ips}`",
                                        f"**节点 ID**: `{nid}`",
                                        f"**状态**: 🟢 **在线已就绪**"
                                    ],
                                    color="blue"
                                )

                        # 检查状态变更
                        if nid in self._prev_nodes_status:
                            was_online = self._prev_nodes_status[nid]
                            if was_online and not is_online:
                                # 节点离线告警！
                                record_audit_log(
                                    action="节点离线告警",
                                    target=name,
                                    detail=f"设备 {name} ({ips}) 与控制面断开连接",
                                    status="warning"
                                )
                                webhook = cfg.get("feishu_webhook")
                                if webhook:
                                    await send_feishu_card(
                                        webhook,
                                        title=f"⚠️ Headscale 节点离线告警",
                                        content_lines=[
                                            f"**节点名称**: `{name}`",
                                            f"**所属用户**: `{user}`",
                                            f"**分配虚拟 IP**: `{ips}`",
                                            f"**当前状态**: 🔴 **已断开连接 / 离线**",
                                            f"**排查建议**: 请检查该节点的 Tailscale 客户端运行状态及网络连通性。"
                                        ],
                                        color="red"
                                    )
                            elif not was_online and is_online:
                                # 节点恢复上线通知！
                                record_audit_log(
                                    action="节点恢复在线",
                                    target=name,
                                    detail=f"设备 {name} ({ips}) 恢复与控制面通信",
                                    status="success"
                                )
                                webhook = cfg.get("feishu_webhook")
                                if webhook:
                                    await send_feishu_card(
                                        webhook,
                                        title=f"✅ Headscale 节点恢复在线",
                                        content_lines=[
                                            f"**节点名称**: `{name}`",
                                            f"**所属用户**: `{user}`",
                                            f"**分配虚拟 IP**: `{ips}`",
                                            f"**当前状态**: 🟢 **在线运行中**"
                                        ],
                                        color="green"
                                    )
                        self._prev_nodes_status[nid] = is_online
                        self._known_nodes.add(nid)
                    
                    self._initialized = True
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")

            interval = load_config().get("monitor_interval_seconds", 60)
            await asyncio.sleep(max(10, interval))

monitor_service = NodeMonitor()
