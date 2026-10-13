# go_to_ktv

把歌單轉成 Elitesand Pro 可匯入的格式。支援網址抓歌、CSV／試算表，以及用歌名搜 YouTube **伴奏**網址。版本 **v0.3.2**。

## 需求

- Python 3.10+
- `pip install -r requirements.txt`（會裝 `yt-dlp`，給 YouTube 搜尋用）
- 網址抓歌時要能連到 `streamersonglist.com`

## 執行

```bash
pip install -r requirements.txt
python server.py
```

瀏覽器打開 http://127.0.0.1:8765

遠端／另一台電腦：伺服器預設聽 `0.0.0.0:8765`，請用 `http://那台機器的IP:8765` 打開（不要直接雙擊 `index.html`）。防火牆要放行 8765。若只想本機連：

```bash
GO_TO_KTV_HOST=127.0.0.1 python server.py
```

### 從網址

1. 貼上 `https://streamersonglist.com/t/名稱/songs`
2. 按「抓取歌單」

### 從 CSV／試算表

1. 上傳 `.csv`，或從 Excel／Google 試算表複製後貼上
2. 按「轉成歌單」

表頭建議：`標題`／`歌名`、`歌手`／`artist`。沒有表頭時，預設第一欄歌名、第二欄歌手。

### 搜 YouTube 再匯出

1. 歌單出現後，按「搜尋 YouTube」（只處理目前畫面上、還沒有網址的歌）
2. 搜尋關鍵字會自動加上「伴奏」，比較容易對到可唱版本
3. 表格會顯示找到的影片；不對可以之後再改
4. 按「下載 Elitesand 歌單」

有 YouTube 網址的歌會寫進 json 的 `url`，Elitesand 匯入後比較有機會直接抓音訊。搜尋結果仍可能對錯，請先看一眼。

## 匯入 Elitesand Pro

```text
%APPDATA%\Elitesand Pro\data\playlist-exports
```

一般路徑：

```text
C:\Users\你的名字\AppData\Roaming\Elitesand Pro\data\playlist-exports
```

把下載的 json 放進去，再在程式裡匯入。

## 注意

- 網址來源只讀 `streamersonglist.com` 公開歌單
- 表格來源不把檔案內容送到伺服器
- YouTube 搜尋走本機 `yt-dlp`
- CSV 用 UTF-8（含 BOM）

## 倉庫

https://github.com/cccsdxtw/go_to_ktv
