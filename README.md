# go_to_ktv

把歌單轉成 Elitesand Pro 可匯入的格式，並可一次下載全部伴奏音檔。支援網址抓歌、CSV／試算表，以及用歌名搜 YouTube **伴奏**。版本 **v0.5.2**。

## 怎麼用（建議）

不用自己打指令。

1. 安裝一次 [Python](https://www.python.org/downloads/)（Windows 請勾選 Add to PATH）
2. 雙擊：
   - Windows：`開始.bat`（若中文檔名有問題，可改雙擊 `start.bat`）
   - Mac：`開始.command`（若不能執行，終端機跑一次 `chmod +x 開始.command`）
3. 瀏覽器會自動打開；黑色／終端機視窗要留著，用完再關

黑視窗請留著。若 8765 被舊程式佔用，會跳出視窗問要不要關掉，按「是」即可。正確畫面標題是「歌單轉入 v0.5.2」。

> 不要只雙擊 `index.html`。網址抓歌、YouTube 搜尋與音檔下載需要背景小伺服器；「開始」會幫你開好。

## 頁面功能

### 從網址

貼上 `https://streamersonglist.com/t/名稱/songs` → 抓取歌單

### 從 CSV／試算表

上傳 `.csv`，或從 Excel／Google 試算表複製貼上 → 轉成歌單

表頭建議：`標題`／`歌名`、`歌手`／`artist`。沒有表頭時，預設第一欄歌名、第二欄歌手。

### 搜 YouTube、一次下載音檔

1. 按「搜尋 YouTube」（會自動加「伴奏」，並優先挑伴奏／karaoke）
2. 看一下找到的影片
3. 選你平常登入 YouTube 的瀏覽器（Chrome／Edge）
4. 按「下載全部音檔」——本機一次排程抓好，**不用一首一首另存**
5. 按「開啟音檔資料夾」，把裡面的 mp3／m4a **一次拖進** Elitesand 右邊「本機檔案」區塊

音檔會放在工具旁邊的 `elitesand-audio` 資料夾。已下載過的影片會略過。

Elitesand 要能唱，音檔本來就必須在這台電腦上（它自己抓 YouTube 也是存硬碟）。差別只是這裡一次抓好，不是你手動點 201 次。

若出現 `Sign in to confirm you're not a bot`：先在 Chrome 登入 YouTube，然後**完全關掉 Chrome**（工作列也不要留著），再按「下載全部音檔」。光開著 youtube.com 時 Cookie 常被鎖住，程式拿不到登入狀態。

## Elitesand 匯入到底做什麼？

Elitesand Pro 的「匯入歌單」**只匯入歌名、歌手、YouTube 網址**，不會下載音檔。這是 Elitesand 自己的設計，不是漏欄位。所以匯入後會看到「音檔遺失／無歌詞」，點播放才會問你要不要重新下載——那才是一首一首點。

這個工具的匯入 json 仍然有用：一次帶進整份歌名與網址當備份。要立刻能唱，請走上面的「下載全部音檔 → 一次拖進本機檔案」。

Elitesand 右邊貼 YouTube 連結時，只有 **YouTube 播放清單（網址含 `list=`）** 才會一次排下載；貼單支影片仍是一首一首。我們沒辦法幫你在 YouTube 上建官方播放清單，所以改成本機一次把音檔抓好。

可選 json 路徑：

```text
%APPDATA%\Elitesand Pro\data\playlist-exports
```

一般路徑：

```text
C:\Users\你的名字\AppData\Roaming\Elitesand Pro\data\playlist-exports
```

把下載的 json 放進去，再在程式裡匯入。

## 進階

若要自己下指令：

```bash
pip install -r requirements.txt
python server.py
```

- 預設聽 `0.0.0.0:8765`，並自動打開瀏覽器
- 不自動開瀏覽器：`GO_TO_KTV_NO_BROWSER=1`
- 只聽本機：`GO_TO_KTV_HOST=127.0.0.1`

## 注意

- 網址來源只讀 `streamersonglist.com` 公開歌單
- 表格來源不把檔案內容送到伺服器
- YouTube 搜尋與音檔下載走本機 `yt-dlp`
- 轉成 mp3 需要本機有 `ffmpeg`；沒有的話會改抓 m4a
- 搜尋結果仍可能對錯，下載前請看一眼

## 倉庫

https://github.com/cccsdxtw/go_to_ktv
