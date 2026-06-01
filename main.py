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

THREE_XUI_SUB_URL = os.getenv("THREE_XUI_SUB_URL", "http://127.0.0.1:2096")
DEFAULT_DEVICE_LIMIT = int(os.getenv("DEFAULT_DEVICE_LIMIT", "3"))
DEVICE_TTL_DAYS = int(os.getenv("DEVICE_TTL_DAYS", "30"))
ERROR_PROXY_TEXT = os.getenv("ERROR_PROXY_TEXT", "⚠️_DEVICE_LIMIT_REACHED")
API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN", "secret")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "2097"))

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

class RenameDeviceRequest(BaseModel):
    device_name: str

def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    if credentials.credentials != API_BEARER_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid API Token")
    return credentials.credentials

def get_client_limit(sub_id: str) -> int:
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT device_limit FROM custom_limits WHERE sub_id = ?", (sub_id,))
        res = cursor.fetchone()
        return res[0] if res else DEFAULT_DEVICE_LIMIT

def generate_error_subscription() -> str:
    fake_vless = f"vless://00000000-0000-0000-0000-000000000000@127.0.0.1:0?encryption=none#{ERROR_PROXY_TEXT}"
    return base64.b64encode(fake_vless.encode("utf-8")).decode("utf-8")


@app.get("/sub/{sub_id}", response_class=PlainTextResponse)
async def handle_subscription(
    sub_id: str, 
    request: Request, 
    x_hwid: str = Header(None, alias="X-Hwid"),
    user_agent: str = Header(None, alias="User-Agent")
):
    if not x_hwid:
        raise HTTPException(status_code=400, detail="Incompatible VPN client. HWID header missing.")

    limit = get_client_limit(sub_id)

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
                return generate_error_subscription()
            
            device_name = user_agent.split('(')[0].strip()[:50] if user_agent else f"Device_{x_hwid[:6]}"
            
            cursor.execute(
                "INSERT INTO devices (sub_id, hwid, device_name) VALUES (?, ?, ?)",
                (sub_id, x_hwid, device_name)
            )
            conn.commit()

    xui_url = f"{THREE_XUI_SUB_URL}/sub/{sub_id}"
    try:
        response = requests.get(xui_url, params=request.query_params, timeout=5)
        
        if response.status_code == 200:
            return response.text
        elif response.status_code == 404:
            with sqlite3.connect(DB_NAME) as conn:
                conn.cursor().execute("DELETE FROM devices WHERE sub_id = ?", (sub_id,))
                conn.commit()
            raise HTTPException(status_code=404, detail="Subscription not found in 3x-UI")
        else:
            return generate_error_subscription()
            
    except requests.exceptions.RequestException:
        raise HTTPException(status_code=500, detail="Internal 3x-UI connection error")


@app.get("/api/sub/{sub_id}/devices", response_model=List[DeviceInfo], dependencies=[Depends(verify_token)])
async def get_client_devices(sub_id: str):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id, hwid, device_name, last_seen, created_at FROM devices WHERE sub_id = ?", (sub_id,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

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
async def reset_client_devices(sub_id: str):
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