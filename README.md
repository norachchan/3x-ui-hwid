# 3x-UI HWID

A lightweight, secure, and zero-overhead middleware proxy for the [3x-ui](https://github.com/MHSanaei/3x-ui) panel that enforces strict device limits based on **Hardware ID (HWID)**. It perfectly solves the issue of subscription sharing by locking access to a predefined number of unique devices.

Unlike standard IP-based limits which trigger false positives when users switch between Wi-Fi and mobile data (LTE), **3x-UI HWID** tracks actual hardware signatures.

---

## 🚀 Key Features

* **True HWID Enforcement:** Uses `x-hwid`, `x-device-model`, and `User-Agent` headers injected by modern VPN clients.
* **Smart Error Handling:** If the limit is exceeded, it preserves the original subscription name and data usage headers, but replaces the configuration list with a clear placeholder node (e.g., `⚠️ DEVICE LIMIT REACHED`).
* **Auto-Cleanup (TTL):** Automatically unlinks old, inactive devices after a configurable number of days, saving admins from manual support requests.
* **Self-Cleaning Database:** Instantly wipes local client device data if the subscription is deleted or deactivated inside the main 3x-UI panel (handles `404 Not Found` responses).
* **Master API:** Comes with a secure, token-protected API allowing full integration with Telegram bots, websites, CRM, or billing systems.
* **Ultra Lightweight:** Written in FastAPI (Python) with a fast SQLite backend, ensuring high performance and minimal resource consumption on any server.

---

## 🛠️ How It Works

```text
[ VPN Client ] 
 (v2RayTun, Happ, etc.)
       │
       ▼  (Requests Sub via Port 2096 with X-Hwid Header)
┌─────────────────────────┐
│       3x-UI HWID        │ ───► Limit Exceeded? ──► Returns: ⚠️ DEVICE LIMIT REACHED
└─────────────────────────┘
       │
       ▼  (If Access Granted, Proxies Request Locally)
┌─────────────────────────┐
│     Main 3x-UI Panel    │ (Running on Port 2097)
└─────────────────────────┘
```

When a client updates their subscription, the proxy captures their unique Subscription ID (`sub_id`) and hardware identity:
1. If the device is already registered, it updates the `last_seen` timestamp and fetches the subscription from 3x-UI.
2. If it's a new device and the limit **is not reached**, it automatically extracts the device model name (from `x-device-model` or `User-Agent`), registers the device, and fetches the subscription.
3. If it's a new device and the limit **is reached**, it checks for inactive ("expired") devices based on your TTL settings to replace them. If none are found, it fetches the real profile metadata (title, traffic description) from 3x-UI but swaps the actual server configs with an error stub.

---

## ⚡ One-Click Installation

Run the following command on your server as **root**:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/Tsimbalist/3x-ui-hwid/main/install.sh)
```

The interactive installer will automatically:
* Install system dependencies (Python venv, Git, Curl).
* Clone the repository to `/root/3x-ui-hwid`.
* Guide you through configuring ports and limits.
* Generate a secure Master API Token.
* Create and launch a persistent `systemd` service (`3xui-hwid.service`).

---

## ⚙️ Configuration (`.env`)

You can modify your setup at any time by editing the `/root/3x-ui-hwid/.env` file:

```env
THREE_XUI_SUB_URL=http://127.0.0.1:2097  # Internal URL of your 3x-UI subscription system
PORT=2096                                # Public port for your clients
HOST=0.0.0.0
DEFAULT_DEVICE_LIMIT=3                   # Global device limit per subscription
DEVICE_TTL_DAYS=30                       # Auto-unlink devices inactive for X days
ERROR_PROXY_TEXT=⚠️ DEVICE LIMIT REACHED # Text displayed to the user inside the VPN client
API_BEARER_TOKEN=your_generated_secret   # Master token for your external scripts/bots
```
*Note: Remember to restart the service after modifying the `.env` file:* `systemctl restart 3xui-hwid`

---

## 🔌 Master API Reference

All API endpoints are protected. You must pass your secret token in the headers as a Bearer token:
`Authorization: Bearer <YOUR_API_BEARER_TOKEN>`

| Method | Endpoint | Response | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/sub/{sub_id}/devices` | SubDevicesResponse (JSON) | Returns a comprehensive object containing `device_limit`, `current_count`, and the `devices` list. |
| `POST` | `/api/device/{device_id}/rename` | `{"device_name": "..."}` | Updates the display name of a specific device. |
| `DELETE` | `/api/device/{device_id}` | - | Deletes a specific device, freeing up a slot instantly. |
| `DELETE` | `/api/sub/{sub_id}/reset` | - | Unlinks all devices for a subscription. Perfect for a "Reset Devices" button in your Bot/CRM. |
| `POST` | `/api/sub/{sub_id}/limit/{new_limit}`| - | Overrides the global default limit for a specific subscription (e.g., granting a VIP user 5 slots). |

---

## 🤝 License

Distributed under the MIT License. Feel free to fork, modify, and use it for your commercial or private projects!
