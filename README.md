# go_to_ktv

把歌單轉成 Elitesand Pro 可匯入的格式。支援網址抓歌、CSV／試算表，以及用歌名搜 YouTube **伴奏**網址。版本 **v0.4.2**。

## 怎麼用（建議）

不用自己打指令。

1. 安裝一次 [Python](https://www.python.org/downloads/)（Windows 請勾選 Add to PATH）
2. 雙擊：
   - Windows：`開始.bat`（若中文檔名有問題，可改雙擊 `start.bat`）
   - Mac：`開始.command`（若不能執行，終端機跑一次 `chmod +x 開始.command`）
3. 瀏覽器會自動打開；黑色／終端機視窗要留著，用完再關

若視窗一閃就關掉：再雙擊一次，看同資料夾有沒有 `啟動記錄.txt`，裡面會寫原因（多半是還沒裝 Python，或沒勾 PATH）。

> 不要只雙擊 `index.html`。網址抓歌與 YouTube 搜尋需要背景小伺服器；「開始」會幫你開好。

## 頁面功能

### 從網址

貼上 `https://streamersonglist.com/t/名稱/songs` → 抓取歌單

### 從 CSV／試算表

上傳 `.csv`，或從 Excel／Google 試算表複製貼上 → 轉成歌單

表頭建議：`標題`／`歌名`、`歌手`／`artist`。沒有表頭時，預設第一欄歌名、第二欄歌手。

### 搜 YouTube 再匯出

1. 按「搜尋 YouTube」（會自動加「伴奏」，並優先挑伴奏／karaoke）
2. 看一下找到的影片
3. 按「下載 Elitesand 歌單」

## 匯入 Elitesand Pro

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
- YouTube 搜尋走本機 `yt-dlp`
- 搜尋結果仍可能對錯，匯出前請看一眼

## 倉庫

https://github.com/cccsdxtw/go_to_ktv
