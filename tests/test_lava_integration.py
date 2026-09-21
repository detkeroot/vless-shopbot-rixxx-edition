import sys
from unittest.mock import MagicMock
for mod in ("qrcode", "yookassa", "aiosend", "pytonconnect", "pytonconnect.exceptions", "py3xui", "pyotp"):
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

import asyncio
import unittest
from unittest.mock import AsyncMock, patch
import json
from shop_bot.modules import lava_api
from shop_bot.bot import keyboards
from shop_bot.data_manager import database

class TestLavaIntegration(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.api_key = "test_api_key_12345"
        self.offer_id = "836b9fc5-7ae9-4a27-9642-592bc44072b7"
        self.bot_username = "test_vpn_bot"

    async def test_create_invoice_success_sbp(self):
        mock_response_data = {
            "id": "contract_uuid_111",
            "status": "new",
            "paymentUrl": "https://gate.lava.top/invoice/contract_uuid_111",
            "amountTotal": {"amount": 150.0, "currency": "RUB"}
        }

        mock_resp = AsyncMock()
        mock_resp.status = 201
        mock_resp.json = AsyncMock(return_value=mock_response_data)

        mock_post = MagicMock()
        mock_post.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession.post", return_value=mock_post):
            result = await lava_api.create_invoice(
                amount=150.0,
                email="user123@telegram.bot",
                api_key=self.api_key,
                offer_id=self.offer_id,
                bot_username=self.bot_username,
                sbp_mode=True
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["invoice_id"], "contract_uuid_111")
        self.assertEqual(result["payment_url"], "https://gate.lava.top/invoice/contract_uuid_111")
        self.assertEqual(result["amount"], 150.0)
        self.assertEqual(result["currency"], "RUB")

    async def test_create_invoice_api_error(self):
        mock_resp = AsyncMock()
        mock_resp.status = 400
        mock_resp.json = AsyncMock(return_value={"error": "Invalid offerId"})

        mock_post = MagicMock()
        mock_post.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession.post", return_value=mock_post):
            result = await lava_api.create_invoice(
                amount=200.0,
                email="user@test.bot",
                api_key=self.api_key,
                offer_id="invalid_offer",
                bot_username=self.bot_username
            )

        self.assertIsNone(result)

    async def test_resolve_offer_id_from_product_id(self):
        mock_products_data = {
            "items": [
                {
                    "id": "product_uuid_999",
                    "title": "VPN Product",
                    "offers": [
                        {"id": "real_offer_uuid_888", "name": "Basic"}
                    ]
                }
            ]
        }
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=mock_products_data)

        mock_get = MagicMock()
        mock_get.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession.get", return_value=mock_get):
            resolved = await lava_api.resolve_offer_id(self.api_key, "product_uuid_999")

        self.assertEqual(resolved, "real_offer_uuid_888")

    async def test_create_invoice_auto_resolves_404(self):
        # 1st post -> 404
        resp_404 = AsyncMock()
        resp_404.status = 404
        resp_404.json = AsyncMock(return_value={"error": "Product with offer id = 'product_uuid_999' not found"})

        # 2nd post -> 201 success
        resp_201 = AsyncMock()
        resp_201.status = 201
        resp_201.json = AsyncMock(return_value={
            "id": "invoice_auto_resolved",
            "paymentUrl": "https://gate.lava.top/invoice/123",
            "status": "new"
        })

        mock_post = MagicMock()
        mock_post.__aenter__ = AsyncMock(side_effect=[resp_404, resp_201])
        mock_post.__aexit__ = AsyncMock(return_value=None)

        # get -> returns product with offers
        resp_get = AsyncMock()
        resp_get.status = 200
        resp_get.json = AsyncMock(return_value={
            "items": [
                {
                    "id": "product_uuid_999",
                    "offers": [{"id": "resolved_offer_111"}]
                }
            ]
        })
        mock_get = MagicMock()
        mock_get.__aenter__ = AsyncMock(return_value=resp_get)
        mock_get.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession.post", return_value=mock_post), \
             patch("aiohttp.ClientSession.get", return_value=mock_get):
            result = await lava_api.create_invoice(
                amount=150.0,
                email="user@test.bot",
                api_key=self.api_key,
                offer_id="product_uuid_999",
                bot_username=self.bot_username
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["invoice_id"], "invoice_auto_resolved")
        self.assertEqual(result["payment_url"], "https://gate.lava.top/invoice/123")

    async def test_get_invoice_status_completed(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"id": "contract_123", "status": "completed"})

        mock_get = MagicMock()
        mock_get.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession.get", return_value=mock_get):
            status_data = await lava_api.get_invoice_status("contract_123", self.api_key)

        self.assertIsNotNone(status_data)
        self.assertTrue(status_data["is_paid"])
        self.assertEqual(status_data["status"], "completed")

    async def test_get_invoice_status_pending(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"id": "contract_123", "status": "in-progress"})

        mock_get = MagicMock()
        mock_get.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession.get", return_value=mock_get):
            status_data = await lava_api.get_invoice_status("contract_123", self.api_key)

        self.assertIsNotNone(status_data)
        self.assertFalse(status_data["is_paid"])
        self.assertEqual(status_data["status"], "in-progress")

    def test_verify_webhook_auth(self):
        expected_secret = "my_super_webhook_secret_key"

        # Case 1: X-Api-Key matching
        headers_valid = {"X-Api-Key": "my_super_webhook_secret_key"}
        self.assertTrue(lava_api.verify_webhook_auth(headers_valid, expected_secret))

        # Case 2: Lowercase x-api-key
        headers_lower = {"x-api-key": "my_super_webhook_secret_key"}
        self.assertTrue(lava_api.verify_webhook_auth(headers_lower, expected_secret))

        # Case 3: Invalid key
        headers_invalid = {"X-Api-Key": "wrong_key"}
        self.assertFalse(lava_api.verify_webhook_auth(headers_invalid, expected_secret))

        # Case 4: Missing key
        self.assertFalse(lava_api.verify_webhook_auth({}, expected_secret))

    def test_keyboards_lava_buttons(self):
        payment_methods = {"lava": True, "yookassa": False, "cryptobot": False}
        markup = keyboards.create_payment_method_keyboard(payment_methods, action="new", key_id=0)

        button_texts = [btn.text for row in markup.inline_keyboard for btn in row]
        self.assertIn("⚡ СБП (Lava.top)", button_texts)

        # Проверка клавиатуры оплаты с кнопкой проверки
        lava_markup = keyboards.create_lava_payment_keyboard("https://lava.top/pay/123", "contract_abc_123")
        lava_texts = [btn.text for row in lava_markup.inline_keyboard for btn in row]
        lava_callbacks = [btn.callback_data for row in lava_markup.inline_keyboard for btn in row if btn.callback_data]

        self.assertIn("💳 Оплатить через СБП", lava_texts)
        self.assertIn("🔄 Проверить оплату", lava_texts)
        self.assertIn("check_lava_contract_abc_123", lava_callbacks)
    def test_webhook_route_success(self):
        from shop_bot.webhook_server.app import create_webhook_app
        mock_controller = MagicMock()
        app = create_webhook_app(mock_controller)
        app.config['TESTING'] = True
        client = app.test_client()

        with patch("shop_bot.webhook_server.app.get_setting", return_value="secret_key_123"), \
             patch("shop_bot.webhook_server.app.find_and_complete_pending_transaction", return_value={"user_id": 111}), \
             patch("shop_bot.webhook_server.app.handlers.process_successful_payment", new_callable=AsyncMock):

            payload = {
                "eventType": "payment.success",
                "contractId": "contract_uuid_777",
                "amount": 150.0,
                "currency": "RUB"
            }
            response = client.post(
                "/lava-webhook",
                json=payload,
                headers={"X-Api-Key": "secret_key_123"}
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("ok", response.get_json().get("status", ""))

    def test_webhook_route_invalid_auth(self):
        from shop_bot.webhook_server.app import create_webhook_app
        mock_controller = MagicMock()
        app = create_webhook_app(mock_controller)
        app.config['TESTING'] = True
        client = app.test_client()

        with patch("shop_bot.webhook_server.app.get_setting", return_value="secret_key_123"):
            response = client.post(
                "/lava-webhook",
                json={"eventType": "payment.success"},
                headers={"X-Api-Key": "wrong_key"}
            )
            self.assertEqual(response.status_code, 403)

if __name__ == "__main__":
    unittest.main()
