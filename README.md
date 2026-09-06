# Discord Announcement Forwarding Bot

**目前版本：1.0.0**

以 Python 建立的 Discord 公告監聽與轉發工具。程式使用 user client 輪詢來源頻道，偵測新訊息後，透過官方 Discord Bot 將內容轉發到指定目的頻道。

## 版本 1.0.0

首個完整版本，包含：

- user token 啟動驗證與來源頻道輪詢
- 多監聽組與來源頻道管理
- 每個監聽組設定轉發目的頻道
- 官方 Bot token 驗證與 REST API 訊息轉發
- 訊息來源、傳送者、建立時間與附件網址格式化
- 超過 2000 字的訊息自動分段
- 監聽進度與轉發設定保存
- 專案 `.venv` 與依賴版本固定

## ⚠️⚠️⚠️免責聲明與重要提醒⚠️⚠️⚠️

本專案僅供技術研究與學習交流用途，請勿用於商業或任何未經授權之行為。

風險警告與帳號安全：本專案之來源監聽模組採用 discord.py-self 與 Discord User Token 運作。利用程式自動化操作使用者帳號已明確違反 Discord 服務條款，可能會導致帳號遭受系統限制或永久停權。請絕對不要使用你的個人主要帳號進行測試與運行，並自行承擔所有相關風險。

基於 Discord 服務條款與帳號安全考量，本專案不提供取得 User Token 的具體教學步驟，也不協助繞過 Discord 的登入或安全機制。Token 一旦外洩，請立即依 Discord 官方流程撤銷或更換。

技術架構與套件說明：訊息轉發端係透過 Discord REST API（或 Webhook）呼叫官方 Bot 服務發送訊息，不會將 Bot Token 用於登入 User Client。因此專案環境僅需安裝 discord.py-self，無需重複安裝官方 discord.py。

## 功能

- 使用 user token 登入並檢查 token 是否有效。
- 瀏覽 user account 已加入的伺服器與文字頻道。
- 建立多個監聽組，每個監聽組可包含多個來源頻道。
- 每個監聽組可設定一個轉發目的頻道。
- 每 60 至 110 秒輪詢一次來源頻道的新訊息。
- 記錄最後處理的訊息 ID，避免重複處理。
- 轉發訊息時保留來源伺服器、頻道、傳送者暱稱、訊息建立時間、文字與附件網址。
- 超過 Discord 單則 2000 字限制時自動分段發送。
- 設定與監聽進度保存到 `listener_state.json`。
- Bot token 啟用轉發前會先透過 Discord API 驗證。

## 專案結構

```text
Discord_Announcement_Forwarding_Bot/
├── listen.py              # 主程式
├── listener_state.json    # 監聽組與進度設定
├── requirements.txt       # Python 依賴
├── README.md              # 使用說明
├── .env                   # 本機 token 設定
└── .venv/                 # 專案虛擬環境
```

## 系統需求

- Windows、macOS 或 Linux
- Python 3.11 或相容版本
- 可連線至 Discord API
- 一個可用的 Discord user token，用於來源監聽
- 一個官方 Discord Bot token，用於發送轉發訊息(https://discord.com/developers)

## Discord 權限準備

### 來源監聽帳號

來源 user account 必須能看見來源伺服器與來源文字頻道，並能讀取頻道歷史訊息。

### 官方轉發 Bot

官方 Bot 必須已加入轉發目的伺服器，並在目的文字頻道具有 `View Channel` 與 `Send Messages` 權限。

## 安裝部署

### 1. 建立虛擬環境

在專案根目錄執行：

```powershell
python -m venv .venv
```

### 2. 安裝依賴

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

本專案指定的依賴如下：

```text
discord.py-self==2.1.0
python-dotenv==1.2.2
```

不要在同一個環境額外安裝 `discord.py`。兩者都使用 `discord` Python 命名空間，可能互相覆蓋，導致載入錯誤或 user client API 不相容。

### 3. 建立 `.env`

在專案根目錄建立 `.env`：

```env
DISCORD_USER_TOKEN=你的_User_Token
DISCORD_BOT_TOKEN=你的_Bot_Token
```

`DISCORD_BOT_TOKEN` 請填純 Bot token，不需要加 `Bot ` 前綴。程式會自動移除前後空白、引號與可能誤加的 `Bot ` 前綴。

請勿把 `.env`、token 或 `listener_state.json` 提交到公開版本庫。`.gitignore` 已忽略這些本機資料與 `.venv/`。

## 啟動程式

請使用專案虛擬環境的 Python：

```powershell
.venv\Scripts\python.exe listen.py
```

不要使用全域環境的 `python listen.py`，避免全域 `discord.py` 與 `discord.py-self` 共用 `discord` 命名空間。

程式啟動後會先驗證 user token；驗證失敗時會顯示簡短錯誤並結束，不會進入主選單。

## 使用方法

### 主選單

```text
1. 監聽：未啟動
2. 轉發：關閉
3. 設定
4. 退出程式
```

### 建立監聽組

1. 選擇 `3. 設定`。
2. 選擇 `1. 建立監聽組`。
3. 輸入監聽組名稱，例如 `公告` 或 `行程表`。

同一個監聽組可以包含多個來源頻道。

### 加入來源頻道

1. 進入 `3. 設定`。
2. 選擇 `2. 瀏覽伺服器並選擇頻道`。
3. 選擇伺服器、來源文字頻道及監聽組。

新加入的頻道會先以目前最新訊息作為基準，不會把加入前的舊訊息全部轉發出去。

### 設定轉發目的頻道

1. 進入 `3. 設定`。
2. 選擇 `3. 設定轉發目的頻道`。
3. 選擇監聽組。
4. 輸入目的文字頻道 ID。

取得頻道 ID 的方法：

1. 在 Discord 使用者設定中開啟 Developer Mode。
2. 對目的頻道按右鍵。
3. 選擇 `Copy Channel ID`。

輸入 `0` 可以清除該監聽組的轉發目的頻道。每個監聽組目前只能指定一個目的頻道。

### 開啟轉發與監聽

回到主選單後先選擇 `2. 轉發`。程式會先透過 Discord API 驗證官方 Bot token，成功後才會顯示轉發已啟動。

確認至少有一個來源頻道後，再選擇 `1. 監聽`。程式會以 60 至 110 秒的間隔檢查新訊息。

監聽期間，在提示列輸入 `stop` 即可停止監聽並返回主選單。

### 其他設定功能

在 `3. 設定` 中還可以：

- 刪除單一來源頻道
- 刪除整個監聽組
- 清空所有監聽組、轉發設定與監聽進度
- 返回主選單

## 轉發格式

```text
====================
# [來自「OOO 的伺服器」的「OO」頻道]
## 傳送者暱稱:
時間：2026-09-06 15:30:25
訊息內容
====================
```

時間取自 Discord 訊息的建立時間，不是程式輪詢或偵測到訊息的時間；程式會依執行環境的本機時區顯示。附件會以 URL 附加在訊息內容後方。

## 設定保存

`listener_state.json` 會保存監聽組、來源頻道 ID、各頻道最後處理的訊息 ID，以及各監聽組的轉發目的頻道 ID。程式重新啟動後會讀取這些設定。

刪除 `listener_state.json` 會清除監聽組與處理進度，但不會影響 Discord 伺服器或頻道本身。

## 常見問題

### `Improper token has been passed`

請確認 `DISCORD_USER_TOKEN` 是 user token，而不是 Bot token、Client ID 或 Client Secret；`DISCORD_BOT_TOKEN` 則必須是官方 Bot token。也請確認執行時使用 `.venv\Scripts\python.exe`。

### Bot token 無效

請到 Discord Developer Portal 重新複製或重設 Bot token，更新 `.env` 後重新啟動。不要將 Client ID 或 Client Secret 填入 Bot token 欄位。

### Bot 沒有權限

確認 Bot 已加入目的伺服器，且目的頻道允許 Bot `View Channel` 和 `Send Messages`。

### 找不到來源伺服器或頻道

確認來源 user account 已加入伺服器，並有權限查看該文字頻道與歷史訊息。

### VS Code 顯示 `Import "discord" could not be resolved`

在 VS Code 選擇專案虛擬環境：

```text
.venv\Scripts\python.exe
```

選擇後重新載入視窗或重新啟動 Python language server。

## 驗證安裝

檢查目前程式語法：

```powershell
.venv\Scripts\python.exe -m py_compile listen.py
```

確認載入的是 `discord.py-self`：

```powershell
.venv\Scripts\python.exe -c "import discord; print(discord.__file__); print(discord.__version__)"
```

預期版本為 `2.1.0`，且路徑應位於專案的 `.venv\Lib\site-packages` 下。

