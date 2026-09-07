# 無 CLI 版本 v1.1.0

此版本不使用主選單、不呼叫 `input()`，所有設定由 JSON 與環境變數提供，適合部署到任何支援常駐 Python 程序的環境：

本版本與 CLI 版本同步支援 Embed 資訊卡轉發、身份組提及轉換，以及跨伺服器轉發格式化。

- `no_cli/config.json`：監聽組、來源頻道、轉發目的頻道、輪詢間隔
- `DISCORD_USER_TOKEN`：來源監聽 token
- `DISCORD_BOT_TOKEN`：官方 Bot token，負責轉發

## 安全與 ToS 提醒

來源監聽使用 `discord.py-self` 與 Discord user token。以程式自動化 user account 可能違反 Discord 服務條款，並可能造成帳號限制或停權。本專案基於 ToS 與帳號安全考量，不提供取得 User Token 的具體教學，也不協助繞過登入或安全機制。

不要將 token 寫入 Git、`config.json`、公開日誌或聊天訊息。官方 Bot token 必須只用於官方 Bot API；不要在同一個虛擬環境安裝 `discord.py`，因為它與 `discord.py-self` 共用 `discord` 命名空間。

## 目錄

```text
Discord_Announcement_Forwarding_Bot/
├── listen.py
├── requirements.txt
├── listener_state.json
└── no_cli/
    ├── worker.py
    ├── config.json
    ├── .env.example
    ├── requirements.txt
    └── README.md
```

`no_cli/worker.py` 會載入上一層的 `listen.py`，所以請將整個專案一起部署，不要只上傳 `no_cli/`。

## config.json 設定

請修改 `no_cli/config.json`，將範例 ID 換成實際的 Discord 頻道 ID：

```json
{
  "groups": {
    "公告": [
      123456789012345678
    ],
    "行程表": [
      234567890123456789,
      345678901234567890
    ]
  },
  "forwarding_targets": {
    "公告": 456789012345678901,
    "行程表": 567890123456789012
  },
  "poll_min_seconds": 60,
  "poll_max_seconds": 110
}
```

欄位說明：

- `groups`：監聽組名稱對應來源頻道 ID 陣列。
- `forwarding_targets`：監聽組名稱對應一個目的頻道 ID。
- `poll_min_seconds`：最短輪詢間隔，預設 60 秒。
- `poll_max_seconds`：最長輪詢間隔，預設 110 秒。

每個 `groups` 內的來源頻道都會轉發到同名的 `forwarding_targets` 頻道。若某個監聽組沒有目的頻道，worker 會拒絕啟動，避免設定錯誤時無聲運行。

## 部署方式

### 1. 上傳專案

使用 Git、SFTP 或部署環境提供的檔案工具上傳整個專案，例如：

```text
/home/你的帳號/Discord_Announcement_Forwarding_Bot
```

不要上傳本機 `.venv/`、`.env` 或包含真實 token 的檔案。

### 2. 建立虛擬環境與安裝依賴

透過 SSH 或部署環境的終端機執行：

```bash
cd ~/Discord_Announcement_Forwarding_Bot
python3 -m venv .venv
.venv/bin/python -m pip install -r no_cli/requirements.txt
```

若主機提供的 Python 指令名稱不同，請使用主機上的 Python 3.11 或相容版本。

### 3. 設定環境變數

在部署環境的環境變數設定介面設定：

```text
DISCORD_USER_TOKEN=你的_User_Token
DISCORD_BOT_TOKEN=你的_Bot_Token
```

也可以在專案根目錄建立 `.env`，但不要提交到 Git：

```bash
chmod 600 .env
```

### 4. 檢查 JSON 與語法

```bash
cd ~/Discord_Announcement_Forwarding_Bot
.venv/bin/python -m json.tool no_cli/config.json
.venv/bin/python -m py_compile listen.py no_cli/worker.py
```

### 5. 手動測試

```bash
.venv/bin/python no_cli/worker.py
```

啟動後應看到 user token 驗證、Bot token 驗證以及：

```text
[無 CLI] 非互動監聽與轉發已啟動。
```

此後程式不會等待任何選單輸入。

### 6. 設定常駐程序

在部署平台的背景程序或持久程序功能設定啟動命令：

```bash
cd /home/你的帳號/Discord_Announcement_Forwarding_Bot && .venv/bin/python no_cli/worker.py
```

若需要完整路徑：

```bash
/home/你的帳號/Discord_Announcement_Forwarding_Bot/.venv/bin/python /home/你的帳號/Discord_Announcement_Forwarding_Bot/no_cli/worker.py
```

這是常駐 Discord worker，不是 HTTP 網站，不要使用 WSGI 或 Gunicorn 啟動。

## 狀態檔

worker 會使用 `no_cli/listener_state.json` 保存最後處理的訊息 ID。這個檔案會在執行時建立，請確認部署程序對 `no_cli/` 有寫入權限。

監聽組與目的頻道以 `config.json` 為準；重啟時 worker 會重新載入 JSON 設定，但沿用狀態檔中的最後訊息 ID，避免重複轉發。

## 權限需求

來源 user account 必須能讀取來源伺服器、文字頻道與歷史訊息。官方 Bot 必須加入目的伺服器，並在目的頻道具有 `View Channel` 與 `Send Messages` 權限。

## 常見錯誤

### `找不到 DISCORD_USER_TOKEN` 或 `找不到 DISCORD_BOT_TOKEN`

確認部署環境的變數名稱完全正確，或確認專案根目錄的 `.env` 存在且可讀取。

### `config.json 格式錯誤`

執行：

```bash
.venv/bin/python -m json.tool no_cli/config.json
```

並確認頻道 ID 只使用數字、監聽組名稱在 `groups` 與 `forwarding_targets` 中一致。

### Bot 無法發送

確認 Bot 已加入目的伺服器，且目的頻道允許 `View Channel` 與 `Send Messages`。HTTP 403 通常是權限不足，HTTP 404 通常是頻道 ID 錯誤或 Bot 尚未加入伺服器。
