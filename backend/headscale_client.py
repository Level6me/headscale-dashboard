import httpx
from typing import Optional, Dict, Any, Union
from config import load_config

class HeadscaleClient:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        cfg = load_config()
        self.base_url = (base_url or cfg.get("headscale_url", "")).rstrip("/")
        self.api_key = api_key or cfg.get("api_key", "")
        self.verify_ssl = not cfg.get("allow_insecure_tls", False)

    def _headers(self, custom_token: Optional[str] = None) -> Dict[str, str]:
        token = custom_token or self.api_key
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        token = kwargs.pop("token", None)
        headers = self._headers(token)
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))
        
        async with httpx.AsyncClient(verify=self.verify_ssl, timeout=15.0) as client:
            resp = await client.request(method, url, headers=headers, **kwargs)
            return resp

    # 连通性测试
    async def test_connection(self) -> Dict[str, Any]:
        try:
            # 首先测试健康状况或获取节点
            resp = await self.request("GET", "/api/v1/node")
            if resp.status_code == 401:
                return {"success": False, "error": "API Key 认证失败 (401 Unauthorized)，请在控制台设置中填入有效密钥", "status_code": 401}
            if resp.status_code == 200:
                return {"success": True, "message": "连接 Headscale 成功！", "status_code": 200}
            return {"success": False, "error": f"服务器返回异常状态码: {resp.status_code}", "status_code": resp.status_code}
        except httpx.ConnectError:
            return {"success": False, "error": f"无法连接到 Headscale 服务: {self.base_url}，请检查地址及防火墙端口"}
        except Exception as e:
            return {"success": False, "error": f"连接异常: {str(e)}"}

    # 用户管理
    async def get_users(self):
        resp = await self.request("GET", "/api/v1/user")
        return resp

    async def create_user(self, name: str):
        resp = await self.request("POST", "/api/v1/user", json={"name": name})
        return resp

    async def delete_user(self, identifier: Union[str, int]):
        target_id = str(identifier)
        if not target_id.isdigit():
            # If a username was passed, resolve to numeric user ID
            users_resp = await self.get_users()
            if users_resp.status_code == 200:
                user_list = users_resp.json().get("users", [])
                for u in user_list:
                    if u.get("name") == str(identifier):
                        target_id = str(u.get("id"))
                        break
        resp = await self.request("DELETE", f"/api/v1/user/{target_id}")
        # Fallback to identifier directly if failed
        if resp.status_code >= 400 and target_id != str(identifier):
            retry_resp = await self.request("DELETE", f"/api/v1/user/{identifier}")
            if retry_resp.status_code == 200:
                return retry_resp
        return resp

    # 节点管理
    async def get_nodes(self, user: Optional[str] = None):
        params = {}
        if user:
            params["user"] = user
        resp = await self.request("GET", "/api/v1/node", params=params)
        return resp

    async def delete_node(self, node_id: int):
        resp = await self.request("DELETE", f"/api/v1/node/{node_id}")
        return resp

    async def rename_node(self, node_id: int, new_name: str):
        resp = await self.request("POST", f"/api/v1/node/{node_id}/rename/{new_name}")
        return resp

    async def move_node_user(self, node_id: int, target_user: str):
        resp = await self.request("POST", f"/api/v1/node/{node_id}/user", params={"user": target_user})
        return resp

    async def register_node(self, user: str, node_key: str):
        resp = await self.request("POST", "/api/v1/node/register", params={"user": user, "key": node_key})
        return resp

    # 预认证密钥
    async def get_preauth_keys(self, user: Optional[str] = None):
        params = {}
        if user:
            params["user"] = user
        resp = await self.request("GET", "/api/v1/preauthkey", params=params)
        return resp

    async def create_preauth_key(self, user: Union[str, int], reusable: bool = False, ephemeral: bool = False, expiration: Optional[str] = None, acl_tags: list = None):
        user_id = str(user)
        if not user_id.isdigit():
            # If username passed, resolve to user ID
            users_resp = await self.get_users()
            if users_resp.status_code == 200:
                user_list = users_resp.json().get("users", [])
                for u in user_list:
                    if u.get("name") == str(user):
                        user_id = str(u.get("id"))
                        break
        body = {
            "user": user_id,
            "reusable": reusable,
            "ephemeral": ephemeral,
            "aclTags": acl_tags or []
        }
        if expiration:
            body["expiration"] = expiration
        resp = await self.request("POST", "/api/v1/preauthkey", json=body)
        if resp.status_code >= 400 and not str(user).isdigit():
            # Fallback for older Headscale expecting username directly
            body["user"] = str(user)
            fallback_resp = await self.request("POST", "/api/v1/preauthkey", json=body)
            if fallback_resp.status_code == 200:
                return fallback_resp
        return resp

    async def expire_preauth_key(self, key_id: Optional[Union[str, int]] = None, user: Optional[str] = None, key: Optional[str] = None):
        if key_id is not None:
            resp = await self.request("POST", "/api/v1/preauthkey/expire", json={"id": str(key_id)})
            if resp.status_code == 200:
                return resp
        payload = {}
        if user:
            payload["user"] = user
        if key:
            payload["key"] = key
        if key_id and not payload:
            payload["id"] = str(key_id)
        resp = await self.request("POST", "/api/v1/preauthkey/expire", json=payload)
        return resp

    # 路由管理
    async def get_routes(self):
        resp = await self.request("GET", "/api/v1/routes")
        return resp

    async def enable_route(self, route_id: int):
        resp = await self.request("POST", f"/api/v1/routes/{route_id}/enable")
        return resp

    async def disable_route(self, route_id: int):
        resp = await self.request("POST", f"/api/v1/routes/{route_id}/disable")
        return resp

    # API Key 管理
    async def get_api_keys(self):
        resp = await self.request("GET", "/api/v1/apikey")
        return resp

    async def create_api_key(self, expiration: Optional[str] = None):
        body = {}
        if expiration:
            body["expiration"] = expiration
        resp = await self.request("POST", "/api/v1/apikey", json=body)
        return resp

    async def expire_api_key(self, prefix: str):
        resp = await self.request("POST", "/api/v1/apikey/expire", json={"prefix": prefix})
        return resp
