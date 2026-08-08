import uuid
import logging
import asyncio
from datetime import datetime, timedelta
import aiohttp
from typing import Dict

from shop_bot.data_manager.database import get_host

logger = logging.getLogger(__name__)

async def _login_to_rixxx(session: aiohttp.ClientSession, host_url: str, username: str, password: str) -> bool:
    try:
        base_url = host_url.rstrip('/')
        login_url = f"{base_url}/api/login"
        async with session.post(login_url, json={"username": username, "password": password}) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("ok"):
                    return True
            logger.error(f"Login failed to {host_url}: HTTP {resp.status} - {await resp.text()}")
            return False
    except Exception as e:
        logger.error(f"Error logging in to {host_url}: {e}", exc_info=True)
        return False

async def create_or_update_key_on_host(host_name: str, email: str, days_to_add: int) -> Dict | None:
    host_data = get_host(host_name)
    if not host_data: return None
    base_url = host_data['host_url'].rstrip('/')
    
    # Меняем @, + и ТОЧКУ на подчеркивание!
    safe_username = email.replace('@', '_').replace('+', '_').replace('.', '_')
    
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        if not await _login_to_rixxx(session, base_url, host_data['host_username'], host_data['host_pass']):
            return None

        expiry_dt = datetime.utcnow() + timedelta(days=days_to_add)
        expiry_iso = expiry_dt.isoformat() + "Z"
        expiry_ms = int(expiry_dt.timestamp() * 1000)
        user_id = None
        
        async with session.get(f"{base_url}/api/users") as resp:
            if resp.status == 200:
                users = await resp.json()
                existing_user = next((u for u in users if u.get('username') == safe_username), None)
                if existing_user:
                    user_id = existing_user['id']
                    if existing_user.get('expiry'):
                        current_expiry = datetime.fromisoformat(existing_user['expiry'].replace('Z', '+00:00')).replace(tzinfo=None)
                        if current_expiry > datetime.utcnow():
                            expiry_dt = current_expiry + timedelta(days=days_to_add)
                            expiry_iso = expiry_dt.isoformat() + "Z"
                            expiry_ms = int(expiry_dt.timestamp() * 1000)
                    update_payload = {"expiry": expiry_iso}
                    try:
                        async with session.put(f"{base_url}/api/users/{user_id}", json=update_payload) as up_resp:
                            if up_resp.status != 200: return None
                    except (aiohttp.client_exceptions.ServerDisconnectedError, aiohttp.client_exceptions.ClientOSError):
                        logger.warning("Caddy restarted during user update. Proceeding...")
        
        if not user_id:
            user_password = str(uuid.uuid4())[:16]
            create_payload = {
                "username": safe_username, 
                "email": email, 
                "password": user_password,
                "expiry": expiry_iso, 
                "protocols": ["naive", "mieru", "hy2"], 
                "quotaMB": 0
            }
            try:
                async with session.post(f"{base_url}/api/users", json=create_payload) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        user_id = data.get('id')
                    else: 
                        logger.error(f"Failed to create user {safe_username}: {await resp.text()}")
                        return None
            except (aiohttp.client_exceptions.ServerDisconnectedError, aiohttp.client_exceptions.ClientOSError):
                logger.warning("Server disconnected during user creation (Caddy restart). Verifying...")
                await asyncio.sleep(3)
                if not await _login_to_rixxx(session, base_url, host_data['host_username'], host_data['host_pass']):
                    return None
                async with session.get(f"{base_url}/api/users") as resp:
                    if resp.status == 200:
                        users = await resp.json()
                        new_user = next((u for u in users if u.get('username') == safe_username), None)
                        if new_user:
                            user_id = new_user['id']
                        else:
                            logger.error("User was not found after disconnect.")
                            return None

        connection_string = None
        if user_id:
            for _ in range(3):
                try:
                    async with session.get(f"{base_url}/api/users/{user_id}/sub-link") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            connection_string = data.get('link')
                            break
                except Exception:
                    await asyncio.sleep(2)
                    await _login_to_rixxx(session, base_url, host_data['host_username'], host_data['host_pass'])
                
        if not connection_string:
            return None
                
        return {
            "client_uuid": user_id, "email": email, "expiry_timestamp_ms": expiry_ms,
            "connection_string": connection_string, "host_name": host_name
        }

async def get_key_details_from_host(key_data: dict) -> dict | None:
    host_name = key_data.get('host_name')
    if not host_name: return None
    host_db_data = get_host(host_name)
    if not host_db_data: return None
    base_url = host_db_data['host_url'].rstrip('/')
    async with aiohttp.ClientSession() as session:
        if not await _login_to_rixxx(session, base_url, host_db_data['host_username'], host_db_data['host_pass']): return None
        user_id = key_data.get('xui_client_uuid')
        async with session.get(f"{base_url}/api/users/{user_id}/sub-link") as resp:
            if resp.status == 200:
                data = await resp.json()
                return {"connection_string": data.get('link')}
    return None

async def delete_client_on_host(host_name: str, client_email: str) -> bool:
    host_data = get_host(host_name)
    if not host_data: return False
    base_url = host_data['host_url'].rstrip('/')
    safe_username = client_email.replace('@', '_').replace('+', '_').replace('.', '_')
    async with aiohttp.ClientSession() as session:
        if not await _login_to_rixxx(session, base_url, host_data['host_username'], host_data['host_pass']): return False
        user_id = None
        async with session.get(f"{base_url}/api/users") as resp:
            if resp.status == 200:
                users = await resp.json()
                existing_user = next((u for u in users if u.get('username') == safe_username), None)
                if existing_user: user_id = existing_user['id']
        if user_id:
            try:
                async with session.delete(f"{base_url}/api/users/{user_id}") as resp:
                    if resp.status == 200: return True
            except (aiohttp.client_exceptions.ServerDisconnectedError, aiohttp.client_exceptions.ClientOSError):
                return True
        else: return True
    return False
