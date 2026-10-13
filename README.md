# go_to_ktv

把歌單轉成 Elitesand Pro 可匯入的格式。也支援匯出／讀入 CSV、試算表。版本 **v0.2.0**。

兩種進法：

1. 貼上 StreamerSonglist 公開歌單網址，本機幫你抓
2. 帶 CSV／試算表進來（上傳或貼上），轉成需要的 json

## 需求

- Python 3.10+
- 網址抓歌時要能連到 `streamersonglist.com`
- CSV／試算表轉入只在瀏覽器解析，不用上網

## 執行

```bash
python server.py
```

瀏覽器打開 http://127.0.0.1:8765

### 從網址

1. 貼上 `https://streamersonglist.com/t/名稱/songs`
2. 按「抓取歌單」
3. 可搜尋、依屬性篩選
4. 下載 CSV／複製到試算表，或下載 Elitesand 歌單

### 從 CSV／試算表

1. 上傳 `.csv`，或從 Excel／Google 試算表複製後貼上
2. 按「轉成歌單」
3. 下載 Elitesand 歌單

表頭建議：

| 標題 | 歌手 | 屬性 | 上次播放 | 播放次數 |
| --- | --- | --- | --- | --- |

也接受 `歌名`／`title`、`藝術家`／`artist` 等常見別名。沒有表頭時，預設第一欄歌名、第二欄歌手。

## 匯入 Elitesand Pro

Elitesand Pro 匯入時不會開系統檔案視窗，只列出固定資料夾裡的 json：

```text
%APPDATA%\Elitesand Pro\data\playlist-exports
```

一般路徑：

```text
C:\Users\你的名字\AppData\Roaming\Elitesand Pro\data\playlist-exports
```

把下載的 json 放進去（資料夾沒有就先建），再在程式裡按匯入、選這份歌單。

清單帶的是歌名和歌手。要播得出聲音，還得在 Elitesand 裡為每首歌加上 YouTube 連結或本機音檔。

## 注意

- 網址來源只讀 `streamersonglist.com` 的公開歌單
- 表格來源不把檔案內容送到伺服器
- CSV 用 UTF-8（含 BOM），Excel 可直接開

## 倉庫

https://github.com/cccsdxtw/go_to_ktv
