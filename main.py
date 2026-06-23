import os
import base64
import sqlite3
import requests
from typing import Optional, List
from fastapi import FastAPI, Header, HTTPException, Request, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

THREE_XUI_SUB_URL = os.getenv("THREE_XUI_SUB_URL", "http://127.0.0.1:2097")
DEFAULT_DEVICE_LIMIT = int(os.getenv("DEFAULT_DEVICE_LIMIT", "3"))
DEVICE_TTL_DAYS = int(os.getenv("DEVICE_TTL_DAYS", "30"))
ERROR_PROXY_TEXT = os.getenv("ERROR_PROXY_TEXT", "⚠️ DEVICE LIMIT REACHED")
API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN", "secret")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "2096"))
TRUSTED_IPS = {ip.strip() for ip in os.getenv("TRUSTED_IPS", "").split(",") if ip.strip()}
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "").strip()
SUB_PATH = os.getenv("SUB_PATH", "/subs/").strip("/") or "subs"

DB_NAME = "hwid_management.db"
security = HTTPBearer()

app = FastAPI(title="3x-UI HWID & API")

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sub_id TEXT,
                hwid TEXT,
                device_name TEXT,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(sub_id, hwid)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS custom_limits (
                sub_id TEXT PRIMARY KEY,
                device_limit INTEGER
            )
        ''')
        conn.commit()

init_db()

class DeviceInfo(BaseModel):
    id: int
    hwid: str
    device_name: Optional[str]
    last_seen: str
    created_at: str

class SubDevicesResponse(BaseModel):
    sub_id: str
    device_limit: int
    current_count: int
    devices: List[DeviceInfo]

class RenameDeviceRequest(BaseModel):
    device_name: str

def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    if credentials.credentials != API_BEARER_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid API Token")
    return credentials.credentials

def get_sub_limit(sub_id: str) -> int:
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT device_limit FROM custom_limits WHERE sub_id = ?", (sub_id,))
        res = cursor.fetchone()
        return res[0] if res else DEFAULT_DEVICE_LIMIT

def generate_error_subscription() -> str:
    fake_vless = f"vless://00000000-0000-0000-0000-000000000000@127.0.0.1:443?type=tcp&encryption=none&security=none#{ERROR_PROXY_TEXT}"
    return base64.b64encode(fake_vless.encode("utf-8")).decode("utf-8")

def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return ""

def proxy_to_xui(request: Request, sub_id: str, is_blocked: bool = False) -> PlainTextResponse:
    xui_url = f"{THREE_XUI_SUB_URL}/{SUB_PATH}/{sub_id}"
    proxy_headers = {}
    client_host = request.headers.get("host", "")
    if client_host:
        proxy_headers["Host"] = client_host.split(":")[0]
    elif PUBLIC_HOST:
        proxy_headers["Host"] = PUBLIC_HOST

    try:
        response = requests.get(xui_url, params=request.query_params, headers=proxy_headers, timeout=5)

        if response.status_code == 200:
            content_to_send = generate_error_subscription() if is_blocked else response.text
            client_response = PlainTextResponse(content=content_to_send)

            excluded_headers = ["content-length", "content-type", "server", "date"]
            for header_name, header_value in response.headers.items():
                if header_name.lower() not in excluded_headers:
                    client_response.headers[header_name] = header_value

            return client_response

        if response.status_code == 404:
            with sqlite3.connect(DB_NAME) as conn:
                conn.cursor().execute("DELETE FROM devices WHERE sub_id = ?", (sub_id,))
                conn.commit()
            raise HTTPException(status_code=404, detail="Subscription not found in 3x-UI")

        return PlainTextResponse(content=generate_error_subscription())

    except requests.exceptions.RequestException:
        raise HTTPException(status_code=500, detail="Internal 3x-UI connection error")


async def handle_subscription(
    sub_id: str,
    request: Request,
    x_hwid: str = Header(None, alias="x-hwid"),
    device_model: str = Header(None, alias="x-device-model"),
    user_agent: str = Header(None, alias="User-Agent"),
):
    client_ip = get_client_ip(request)
    if not x_hwid:
        if client_ip in TRUSTED_IPS:
            return proxy_to_xui(request, sub_id)
        raise HTTPException(status_code=400, detail="Incompatible VPN client. HWID header missing.")

    limit = get_sub_limit(sub_id)
    is_blocked = False

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM devices WHERE sub_id = ? AND hwid = ?", (sub_id, x_hwid))
        device = cursor.fetchone()
        
        if device:
            cursor.execute("UPDATE devices SET last_seen = CURRENT_TIMESTAMP WHERE id = ?", (device[0],))
            conn.commit()
        else:
            cursor.execute("SELECT COUNT(*) FROM devices WHERE sub_id = ?", (sub_id,))
            current_count = cursor.fetchone()[0]
            
            if current_count >= limit:
                cursor.execute(f"DELETE FROM devices WHERE sub_id = ? AND last_seen < datetime('now', '-{DEVICE_TTL_DAYS} days')", (sub_id,))
                conn.commit()
                
                cursor.execute("SELECT COUNT(*) FROM devices WHERE sub_id = ?", (sub_id,))
                current_count = cursor.fetchone()[0]
            
            if current_count >= limit:
                is_blocked = True
            else:
                device_name = device_model if device_model else (user_agent.split('(')[0].strip()[:50] if user_agent else f"Device_{x_hwid[:6]}")
                cursor.execute(
                    "INSERT INTO devices (sub_id, hwid, device_name) VALUES (?, ?, ?)",
                    (sub_id, x_hwid, device_name)
                )
                conn.commit()

    return proxy_to_xui(request, sub_id, is_blocked=is_blocked)


@app.get("/subs/{sub_id}", response_class=PlainTextResponse)
async def handle_subscription_subs(sub_id: str, request: Request, x_hwid: str = Header(None, alias="x-hwid"), device_model: str = Header(None, alias="x-device-model"), user_agent: str = Header(None, alias="User-Agent")):
    return await handle_subscription(sub_id, request, x_hwid, device_model, user_agent)


@app.get("/sub/{sub_id}", response_class=PlainTextResponse)
async def handle_subscription_sub(sub_id: str, request: Request, x_hwid: str = Header(None, alias="x-hwid"), device_model: str = Header(None, alias="x-device-model"), user_agent: str = Header(None, alias="User-Agent")):
    return await handle_subscription(sub_id, request, x_hwid, device_model, user_agent)


@app.get("/api/sub/{sub_id}/devices", response_model=SubDevicesResponse, dependencies=[Depends(verify_token)])
async def get_sub_devices(sub_id: str):
    limit = get_sub_limit(sub_id)
    
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id, hwid, device_name, last_seen, created_at FROM devices WHERE sub_id = ?", (sub_id,))
        rows = cursor.fetchall()
        devices_list = [dict(row) for row in rows]
        
    return {
        "sub_id": sub_id,
        "device_limit": limit,
        "current_count": len(devices_list),
        "devices": devices_list
    }

@app.post("/api/device/{device_id}/rename", dependencies=[Depends(verify_token)])
async def rename_device(device_id: int, data: RenameDeviceRequest):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE devices SET device_name = ? WHERE id = ?", (data.device_name, device_id))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Device not found")
    return {"status": "success", "message": "Device renamed"}

@app.delete("/api/device/{device_id}", dependencies=[Depends(verify_token)])
async def delete_device(device_id: int):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM devices WHERE id = ?", (device_id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Device not found")
    return {"status": "success", "message": "Device unlinked"}

@app.delete("/api/sub/{sub_id}/reset", dependencies=[Depends(verify_token)])
async def reset_sub_devices(sub_id: str):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM devices WHERE sub_id = ?", (sub_id,))
        conn.commit()
    return {"status": "success", "message": f"All devices unlinked for sub {sub_id}"}

@app.post("/api/sub/{sub_id}/limit/{new_limit}", dependencies=[Depends(verify_token)])
async def set_custom_limit(sub_id: str, new_limit: int):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO custom_limits (sub_id, device_limit) VALUES (?, ?) ON CONFLICT(sub_id) DO UPDATE SET device_limit=?",
            (sub_id, new_limit, new_limit)
        )
        conn.commit()
    return {"status": "success", "message": f"Limit updated to {new_limit}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)