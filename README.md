# go_to_ktv

把歌單轉成 Elitesand Pro 可唱的歌：**用 Elitesand 自己的 YouTube 下載**。支援網址抓歌、CSV／試算表，以及用歌名搜 YouTube **伴奏**。版本 **v0.6.2**。

## 怎麼用（建議）

不用自己打指令。

1. 安裝一次 [Python](https://www.python.org/downloads/)（Windows 請勾選 Add to PATH）
2. 先打開 **Elitesand Pro**（本機，預設埠 3000）
3. 雙擊：
   - Windows：`開始.bat`（若中文檔名有問題，可改雙擊 `start.bat`）
   - Mac：`開始.command`（若不能執行，終端機跑一次 `chmod +x 開始.command`）
4. 瀏覽器會自動打開；黑色／終端機視窗要留著，用完再關

黑視窗請留著。若 8765 被舊程式佔用，會跳出視窗問要不要關掉，按「是」即可。正確畫面標題是「歌單轉入 v0.6.2」。

> 不要只雙擊 `index.html`。網址抓歌、YouTube 搜尋與送到 Elitesand 需要背景小伺服器；「開始」會幫你開好。

## 頁面功能

### 從網址

貼上 `https://streamersonglist.com/t/名稱/songs` → 抓取歌單

### 從 CSV／試算表

上傳 `.csv`，或從 Excel／Google 試算表複製貼上 → 轉成歌單

表頭建議：`標題`／`歌名`、`歌手`／`artist`。沒有表頭時，預設第一欄歌名、第二欄歌手。

### 搜 YouTube，再交給 Elitesand 下載

1. 按「搜尋 YouTube」（會自動加「伴奏」，並優先挑伴奏／karaoke）
2. 看一下找到的影片
3. 按「**送到 Elitesand 下載**」——一首一首呼叫本機 Elitesand 的 `POST /api/youtube`（跟右邊貼網址同一條路，含歌詞）
4. 到 Elitesand 看進度；歌會進它自己的曲庫，不必再拖檔

Elitesand 有設 PIN 才要填（本機 loopback 通常不用）。找不到程式時，頁面上會顯示「找不到 Elitesand」。

YouTube 搜尋或送到 Elitesand 若有失敗，表格**上方**會列出失敗的歌，點一下跳到該列。歌名／歌手可直接在格子裡改（原字留下，只改錯的那幾個字），Enter 會用新字重搜那一首；或改完後按「重試這 N 首」。也可以按「YouTube 失敗／送出失敗」只看那些列。

頁面必須連到真正的 Elitesand（健康檢查要有版本與 timestamp）。若 3000 被其他程式佔走，會改找 3001–3010。

「本機另存音檔」仍在，只是備用。沒有帳號下載。

## Elitesand 匯入 json 與下載不是同一件事

Elitesand Pro 的「匯入歌單」**只匯入歌名、歌手、YouTube 網址**，不會下載音檔。這是 Elitesand 自己的設計。要立刻能唱，請走上面的「送到 Elitesand 下載」。

json 仍可當備份：

```text
%APPDATA%\Elitesand Pro\data\playlist-exports
```

一般路徑：

```text
C:\Users\你的名字\AppData\Roaming\Elitesand Pro\data\playlist-exports
```

## 進階

若要自己下指令：

```bash
pip install -r requirements.txt
python server.py
```

- 預設聽 `0.0.0.0:8765`，並自動打開瀏覽器
- 不自動開瀏覽器：`GO_TO_KTV_NO_BROWSER=1`
- 只聽本機：`GO_TO_KTV_HOST=127.0.0.1`
- Elitesand 不在預設埠：`GO_TO_KTV_ELITESAND=http://127.0.0.1:3001`

這個工具與 Elitesand 必須跑在**同一台電腦**（它只連 `127.0.0.1:3000`–`3010`）。遠端打開 8765 也可以，真正下載仍發生在那台本機的 Elitesand。

## 注意

- 網址來源只讀 `streamersonglist.com` 公開歌單
- 表格來源不把檔案內容送到伺服器
- YouTube 搜尋走本機 `yt-dlp`；實際抓檔交給 Elitesand
- 搜尋結果仍可能對錯，送出前請看一眼

## 倉庫

https://github.com/cccsdxtw/go_to_ktv
