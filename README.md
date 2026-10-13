# go_to_ktv

把 StreamerSonglist 公開歌單轉成試算表／CSV，也能做成 Elitesand Pro 可匯入的歌單。版本 **v0.1.0**。

貼上網址 → 本機網頁幫你抓歌 → 下載到自己的電腦。不預先把別人的歌存進專案。

## 需求

- Python 3.10+
- 能連到 `streamersonglist.com`

## 執行

```bash
python server.py
```

瀏覽器打開 http://127.0.0.1:8765

1. 貼上歌單網址，例如 `https://streamersonglist.com/t/名稱/songs`
2. 按「抓取歌單」
3. 可搜尋、依屬性篩選
4. **下載 CSV**／**複製到試算表**：給 Excel、Google 試算表、Numbers
5. **下載 Elitesand 歌單**：給 [Elitesand Pro](https://z22115554.github.io/elitesand-pro/) 匯入

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

- 只讀 `streamersonglist.com` 的公開歌單
- 抓到的資料不會留在這個網頁伺服器；按下載後才存到你的電腦
- CSV 用 UTF-8（含 BOM），Excel 可直接開

## 倉庫

https://github.com/cccsdxtw/go_to_ktv
