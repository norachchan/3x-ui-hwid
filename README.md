# 3x-UI HWID

Прокси-слой для [3x-ui](https://github.com/MHSanaei/3x-ui), который ограничивает число **устройств** по Hardware ID (HWID). Работает вместе с `limit_ip` в панели — HWID по устройствам, IP-лимит по одновременным подключениям.

Репозиторий: [github.com/norachchan/3x-ui-hwid](https://github.com/norachchan/3x-ui-hwid)

---

## Быстрая установка

На сервере с уже установленной **3x-ui**, от **root**:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/norachchan/3x-ui-hwid/main/install.sh)
```

Если установка обрывается после вопросов — запустите из клонированного репозитория:

```bash
cd /root/3x-ui-hwid && git pull && bash install.sh
```

Без вопросов (все значения по умолчанию):

```bash
bash <(curl -Ls https://raw.githubusercontent.com/norachchan/3x-ui-hwid/main/install.sh) --yes
```

Скрипт автоматически:

- ставит зависимости (Python, git, curl);
- клонирует репозиторий в `/root/3x-ui-hwid`;
- переносит подписку 3x-ui на **127.0.0.1:2097** (внутренний порт);
- поднимает HWID на **0.0.0.0:2096** (публичный порт для клиентов);
- настраивает `subURI` в базе 3x-ui с правильным IP и путём (`/subs/` или `/sub/`);
- создаёт `.env`, venv и systemd-сервис `3xui-hwid`;
- открывает порт в UFW (если включён).

---

## Схема работы

```text
VPN-клиент (Happ, v2RayTun, …)
    │  GET /subs/{sub_id} + заголовок x-hwid
    ▼
┌─────────────────────┐
│   3x-UI HWID :2096  │ ── лимит? ──► ⚠️ ЛИМИТ УСТРОЙСТВ ДОСТИГНУТ
└─────────────────────┘
    │  прокси + Host header
    ▼
┌─────────────────────┐
│  3x-ui :2097 local  │
└─────────────────────┘
```

---

## Возможности

| Функция | Описание |
|---|---|
| HWID-лимит | По заголовку `x-hwid` от VPN-клиента |
| IP-лимит | Через `limit_ip` в 3x-ui (настраивает бот/панель) |
| TTL | Авто-отвязка неактивных устройств |
| Trusted IP | Агрегаторы/боты без `x-hwid` (whitelist) |
| Master API | Управление лимитами и устройствами для CRM/ботов |
| Пути `/subs/` и `/sub/` | Оба маршрута поддерживаются |

---

## Конфигурация (`.env`)

```env
THREE_XUI_SUB_URL=http://127.0.0.1:2097
PORT=2096
SUB_PATH=subs
PUBLIC_HOST=1.2.3.4
DEFAULT_DEVICE_LIMIT=3
DEVICE_TTL_DAYS=30
ERROR_PROXY_TEXT=⚠️ ЛИМИТ УСТРОЙСТВ ДОСТИГНУТ
API_BEARER_TOKEN=your_secret
TRUSTED_IPS=1.2.3.4,5.6.7.8
```

После изменений: `systemctl restart 3xui-hwid`

---

## Master API

Заголовок: `Authorization: Bearer <API_BEARER_TOKEN>`

| Метод | Endpoint | Описание |
|---|---|---|
| GET | `/api/sub/{sub_id}/devices` | Список устройств и лимит |
| POST | `/api/sub/{sub_id}/limit/{N}` | Индивидуальный лимит (семейный тариф = 5) |
| DELETE | `/api/sub/{sub_id}/reset` | Сброс всех устройств |
| DELETE | `/api/device/{id}` | Удалить одно устройство |
| POST | `/api/device/{id}/rename` | Переименовать устройство |

Пример для семейного тарифа (5 устройств):

```bash
curl -X POST "http://127.0.0.1:2096/api/sub/{sub_id}/limit/5" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

## Интеграция с Telegram-ботом

При создании/обновлении клиента в 3x-ui:

1. `limit_ip = N` — лимит одновременных IP (3x-ui);
2. `POST /api/sub/{sub_id}/limit/N` — лимит HWID-устройств.

Оба лимита берутся из поля `devices` в БД бота (1 для обычного, 5 для family).

---

## Удаление

```bash
bash /root/3x-ui-hwid/uninstall.sh
```

---

## Переменные установщика

| Переменная | По умолчанию | Описание |
|---|---|---|
| `HWID_REPO_URL` | GitHub repo | URL репозитория |
| `HWID_INSTALL_DIR` | `/root/3x-ui-hwid` | Папка установки |
| `HWID_PUBLIC_PORT` | `2096` | Публичный порт |
| `HWID_INTERNAL_PORT` | `2097` | Внутренний порт 3x-ui |

---

## Лицензия

MIT
