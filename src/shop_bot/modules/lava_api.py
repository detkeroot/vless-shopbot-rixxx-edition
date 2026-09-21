import logging
import aiohttp
from typing import Dict, Any, Optional
from hmac import compare_digest

logger = logging.getLogger(__name__)

LAVA_GATE_BASE_URL = "https://gate.lava.top"

async def resolve_offer_id(
    api_key: str,
    identifier: str,
    session: Optional[aiohttp.ClientSession] = None,
    timeout_sec: int = 10
) -> str:
    """
    Автоматически определяет реальный Offer ID в Lava.top.
    Если пользователь указал Product ID (UUID товара) вместо Offer ID
    (у товаров с динамической ценой в интерфейсе Lava нет кнопки «Купить»),
    функция запрашивает GET /api/v2/products?feedVisibility=ALL и находит Offer ID этого товара.
    """
    if not api_key or not identifier:
        return identifier

    url = f"{LAVA_GATE_BASE_URL}/api/v2/products?feedVisibility=ALL"
    headers = {
        "X-Api-Key": api_key,
        "Accept": "application/json"
    }

    own_session = False
    if session is None:
        own_session = True
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_sec))

    try:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                items = data.get("items", [])
                for item in items:
                    # Проверяем совпадение по Product ID
                    if item.get("id") == identifier:
                        offers = item.get("offers", [])
                        if offers and offers[0].get("id"):
                            resolved_id = offers[0]["id"]
                            logger.info(
                                f"Lava.top: Auto-resolved Product ID '{identifier}' "
                                f"to Offer ID '{resolved_id}' for product '{item.get('title')}'"
                            )
                            return resolved_id
                    # Проверяем, может это уже Offer ID
                    for offer in item.get("offers", []):
                        if offer.get("id") == identifier:
                            return identifier
            else:
                logger.warning(f"Lava.top resolve_offer_id HTTP {response.status}: {await response.text()}")
    except Exception as e:
        logger.warning(f"Lava.top resolve_offer_id error: {e}")
    finally:
        if own_session and session and not session.closed:
            await session.close()

    return identifier

async def create_invoice(
    amount: float,
    email: str,
    api_key: str,
    offer_id: str,
    bot_username: Optional[str] = None,
    sbp_mode: bool = True,
    timeout_sec: int = 15
) -> Optional[Dict[str, Any]]:
    """
    Создает инвойс на оплату через API Lava.top (/api/v3/invoice).
    Для СБП передаются параметры paymentProvider="PAY2ME" и paymentMethod="SBP".
    """
    if not api_key or not offer_id:
        logger.error("Lava.top Error: api_key or offer_id is missing.")
        return None

    return_url = f"https://t.me/{bot_username}" if bot_username else "https://t.me"

    payload: Dict[str, Any] = {
        "email": email,
        "offerId": offer_id,
        "currency": "RUB",
        "amount": round(float(amount), 2),
        "successful_return_url": return_url,
        "failure_return_url": return_url,
        "cancel_return_url": return_url
    }

    if sbp_mode:
        payload["paymentProvider"] = "PAY2ME"
        payload["paymentMethod"] = "SBP"

    headers = {
        "X-Api-Key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    url = f"{LAVA_GATE_BASE_URL}/api/v3/invoice"

    try:
        timeout = aiohttp.ClientTimeout(total=timeout_sec)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as response:
                response_data = await response.json()

                if response.status in (200, 201):
                    invoice_id = response_data.get("id")
                    payment_url = response_data.get("paymentUrl")
                    status = response_data.get("status")

                    logger.info(f"Lava.top invoice created successfully: ID={invoice_id}, Status={status}")
                    return {
                        "invoice_id": invoice_id,
                        "payment_url": payment_url,
                        "status": status,
                        "amount": payload["amount"],
                        "currency": payload["currency"]
                    }
                elif response.status == 404:
                    logger.warning(f"Lava.top returned 404 for offerId '{offer_id}'. Attempting auto-resolution from Product ID...")
                    resolved_id = await resolve_offer_id(api_key, offer_id, session=session, timeout_sec=timeout_sec)
                    if resolved_id and resolved_id != offer_id:
                        logger.info(f"Lava.top: Retrying invoice creation with resolved Offer ID: {resolved_id}")
                        payload["offerId"] = resolved_id
                        async with session.post(url, json=payload, headers=headers) as retry_resp:
                            retry_data = await retry_resp.json()
                            if retry_resp.status in (200, 201):
                                invoice_id = retry_data.get("id")
                                payment_url = retry_data.get("paymentUrl")
                                status = retry_data.get("status")
                                logger.info(f"Lava.top invoice created successfully on retry: ID={invoice_id}, Status={status}")
                                return {
                                    "invoice_id": invoice_id,
                                    "payment_url": payment_url,
                                    "status": status,
                                    "amount": payload["amount"],
                                    "currency": payload["currency"]
                                }
                            else:
                                logger.error(f"Lava.top API retry error: Status={retry_resp.status}, Response={retry_data}")
                                return None
                    else:
                        logger.error(f"Lava.top API error: Status={response.status}, Response={response_data}")
                        return None
                else:
                    logger.error(
                        f"Lava.top API error: Status={response.status}, "
                        f"Response={response_data}"
                    )
                    return None
    except Exception as e:
        logger.error(f"Lava.top request failed: {e}", exc_info=True)
        return None


async def get_invoice_status(
    invoice_id: str,
    api_key: str,
    timeout_sec: int = 15
) -> Optional[Dict[str, Any]]:
    """
    Проверяет текущий статус инвойса через API Lava.top (/api/v1/invoices/{id}).
    Возвращает статус и флаг is_paid.
    """
    if not api_key or not invoice_id:
        logger.error("Lava.top get_invoice_status: api_key or invoice_id is missing.")
        return None

    headers = {
        "X-Api-Key": api_key,
        "Accept": "application/json"
    }

    url = f"{LAVA_GATE_BASE_URL}/api/v1/invoices/{invoice_id}"

    try:
        timeout = aiohttp.ClientTimeout(total=timeout_sec)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                response_data = await response.json()

                if response.status == 200:
                    status = (response_data.get("status") or "").lower()
                    is_paid = status in ("completed", "paid", "success", "subscription-active")
                    return {
                        "invoice_id": invoice_id,
                        "status": status,
                        "is_paid": is_paid,
                        "raw": response_data
                    }
                else:
                    logger.warning(
                        f"Lava.top get_invoice_status failed: Status={response.status}, "
                        f"Data={response_data}"
                    )
                    return None
    except Exception as e:
        logger.error(f"Lava.top get_invoice_status error: {e}", exc_info=True)
        return None


def verify_webhook_auth(headers: dict, expected_key: Optional[str]) -> bool:
    """
    Проверяет аутентификацию входящего вебхука от Lava.top.
    Поддерживает:
    - Заголовок X-Api-Key
    - Basic Auth (если настроен)
    """
    if not expected_key:
        # Если секретный ключ в настройках не задан, принимаем с предупреждением
        logger.warning("Lava.top webhook: lava_webhook_key is not configured in settings.")
        return True

    # 1. Проверка X-Api-Key
    received_key = headers.get("X-Api-Key") or headers.get("x-api-key")
    if received_key and compare_digest(received_key.strip(), expected_key.strip()):
        return True

    # 2. Проверка Authorization: Basic (если ключ передан в виде пароля или токена)
    auth_header = headers.get("Authorization") or headers.get("authorization")
    if auth_header and expected_key in auth_header:
        return True

    return False
