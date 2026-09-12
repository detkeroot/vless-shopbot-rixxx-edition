import sys
from unittest.mock import MagicMock
for mod in ("qrcode", "yookassa", "aiosend", "pytonconnect", "pytonconnect.exceptions", "py3xui", "pyotp"):
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from shop_bot.modules import xui_api

class AsyncContextManager:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

class TestRixxxFederation(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.host_data = {
            "host_name": "TestHost",
            "host_url": "http://127.0.0.1:2053",
            "host_username": "admin",
            "host_pass": "pass123",
            "host_inbound_id": 1
        }

    async def test_create_key_triggers_federation_deploy(self):
        login_resp = MagicMock(status=200, json=AsyncMock(return_value={"ok": True}))
        users_resp = MagicMock(status=200, json=AsyncMock(return_value=[]))
        create_resp = MagicMock(status=201, json=AsyncMock(return_value={"id": "user_uuid_456"}))
        deploy_resp = MagicMock(status=200, json=AsyncMock(return_value={"ok": True, "results": [{"name": "node-germany", "ok": True}]}))
        sub_resp = MagicMock(status=200, json=AsyncMock(return_value={"link": "https://sub.hub.com/sub/token123"}))

        def post_handler(url, **kwargs):
            if "/api/login" in url: return AsyncContextManager(login_resp)
            elif "/federation/deploy" in url: return AsyncContextManager(deploy_resp)
            elif url.endswith("/api/users"): return AsyncContextManager(create_resp)
            return AsyncContextManager(MagicMock(status=404))

        def get_handler(url, **kwargs):
            if url.endswith("/api/users"): return AsyncContextManager(users_resp)
            elif "/sub-link" in url: return AsyncContextManager(sub_resp)
            return AsyncContextManager(MagicMock(status=404))

        mock_session = MagicMock()
        mock_session.post.side_effect = post_handler
        mock_session.get.side_effect = get_handler

        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("shop_bot.modules.xui_api.get_host", return_value=self.host_data), \
             patch("aiohttp.ClientSession", return_value=session_ctx):

            result = await xui_api.create_or_update_key_on_host(
                host_name="TestHost",
                email="user_123_key1@testhost.bot",
                days_to_add=30
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["client_uuid"], "user_uuid_456")
        self.assertEqual(result["connection_string"], "https://sub.hub.com/sub/token123")

    async def test_delete_client_triggers_federation_undeploy(self):
        login_resp = MagicMock(status=200, json=AsyncMock(return_value={"ok": True}))
        users_resp = MagicMock(status=200, json=AsyncMock(return_value=[{"id": "user_uuid_789", "username": "user_789_key1_bot"}]))
        undeploy_resp = MagicMock(status=200, json=AsyncMock(return_value={"ok": True, "results": []}))
        delete_resp = MagicMock(status=200)

        def post_handler(url, **kwargs):
            if "/api/login" in url: return AsyncContextManager(login_resp)
            elif "/federation/undeploy" in url: return AsyncContextManager(undeploy_resp)
            return AsyncContextManager(MagicMock(status=404))

        def get_handler(url, **kwargs):
            if url.endswith("/api/users"): return AsyncContextManager(users_resp)
            return AsyncContextManager(MagicMock(status=404))

        def delete_handler(url, **kwargs):
            if "/api/users/" in url: return AsyncContextManager(delete_resp)
            return AsyncContextManager(MagicMock(status=404))

        mock_session = MagicMock()
        mock_session.post.side_effect = post_handler
        mock_session.get.side_effect = get_handler
        mock_session.delete.side_effect = delete_handler

        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("shop_bot.modules.xui_api.get_host", return_value=self.host_data), \
             patch("aiohttp.ClientSession", return_value=session_ctx):

            success = await xui_api.delete_client_on_host("TestHost", "user_789_key1@bot")

        self.assertTrue(success)

if __name__ == "__main__":
    unittest.main()
