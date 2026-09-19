import json
import logging
from pathlib import Path
from typing import Dict, Any, List

logger = logging.getLogger("HeadscaleDashboard.NodeMeta")
METADATA_FILE = Path(__file__).parent / "node_metadata.json"

def _load_metadata() -> Dict[str, Any]:
    if not METADATA_FILE.exists():
        return {}
    try:
        with open(METADATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        logger.warning(f"Error loading node_metadata.json: {e}")
    return {}

def _save_metadata(data: Dict[str, Any]) -> None:
    try:
        with open(METADATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving node_metadata.json: {e}")

def get_node_tags(node_id: str) -> List[str]:
    meta = _load_metadata()
    node_data = meta.get(str(node_id), {})
    return node_data.get("tags", [])

def set_node_tags(node_id: str, tags: List[str]) -> List[str]:
    meta = _load_metadata()
    clean_tags = list(dict.fromkeys([t.strip() for t in tags if t.strip()]))
    if str(node_id) not in meta:
        meta[str(node_id)] = {}
    meta[str(node_id)]["tags"] = clean_tags
    _save_metadata(meta)
    return clean_tags

def attach_metadata_to_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    meta = _load_metadata()
    for node in nodes:
        nid = str(node.get("id", ""))
        node_meta = meta.get(nid, {})
        # 如果 Headscale 原生 forcedTags 存在，优先合并
        forced = node.get("forcedTags") or []
        custom = node_meta.get("tags", [])
        combined = list(dict.fromkeys(forced + custom))
        node["custom_tags"] = combined
        node["tags"] = combined
    return nodes
