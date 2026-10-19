# go_to_ktv

把歌單轉成 Elitesand Pro 可唱的歌：從網址或表格抓歌，必要時搜 YouTube **伴奏**，再交給 **Elitesand 自己下載**，並掛上目前播放清單。版本 **v1.0.7**（對應 Elitesand Pro **v1.1.1**）。

影片說明：https://youtu.be/PVoaureN8vg

## 怎麼用

不用自己打指令。

1. 安裝一次 [Python](https://www.python.org/downloads/)（Windows 請勾選 Add to PATH）
2. 先打開 **Elitesand Pro**
3. 雙擊 `開始.bat`（Windows；檔名有問題可改雙擊 `start.bat`）或 `開始.command`（Mac）
4. 瀏覽器會自動打開。使用中請留著黑色視窗

不要只雙擊 `index.html`，那樣抓歌單、搜 YouTube、送到 Elitesand 都不會動。

### 轉歌

1. 先打開 Elitesand，再貼上網址或試算表，按「**一鍵開始**」  
   網址支援：**StreamerSonglist**、**YouTube 播放清單／單支影片**、**KKBOX**、**Spotify** 歌單／專輯／歌曲
2. 頁面最上方有固定流程：截取歌曲 → 確定Elitesand歌單 → YT搜尋 → 匯入Elitesand下載 → 完成。暫停在流程圖旁邊，一次只跑一條。貼網址按一鍵開始後：先對 Elitesand 庫，接著邊抓歌單、邊搜 YouTube、邊送給 Elitesand（下載仍一首一首）。可自己按「確定Elitesand歌單」看略過了幾首。
3. 若要先看歌單再動手，改按「抓取歌單」或「轉成歌單」。YouTube 欄可「去聽」、按「另外 N 筆」改選
4. 也可以分開按「搜尋 YouTube」或「送到 Elitesand 下載」

若 Elitesand 沒開，會跳出「請開啟Elitesand」。全部送完會跳出「已下載完成」，可按「確認」或「關閉程式」。

音檔會進 Elitesand 媒體庫，並掛上**目前播放清單**（用歌單原本的歌名／歌手）。不必再一首一首點，也不必匯入 json。

Elitesand 有設 PIN 才要填。這個工具跟 Elitesand 要在**同一台電腦**。

### 失敗時

表格上方會列出失敗的歌，點歌名跳到該列。改完歌名／歌手後按「重試這 N 首」，或用「YouTube 失敗／送出失敗」篩選。

### 用完

按頁面上方紅色「**結束程式（讓出 8765）**」，或下載完成提示裡的「關閉程式」。會先看到「已結束」，接著 `http://127.0.0.1:8765` 讓出、黑色視窗關掉、這個分頁自己關。下次再雙擊「開始」即可。

**只關瀏覽器分頁不夠**，位置還會被佔著。若還是跳出「上一份還佔著」，按「是」結束舊的。

## 注意

- 不要用 Elitesand 的「匯入歌單」代替下載：那只會有歌名和網址，首頁會顯示音檔遺失
- 搜尋結果仍可能對錯，送出前請看一眼
- 找不到 Elitesand、或下載卡住：先看它視窗是否開著；仍不行就關掉 VPN／虛擬區網（工作列右下角小箭頭）再試
- 網址來源：StreamerSonglist、YouTube、KKBOX、Spotify（公開歌單／專輯／歌曲）
- Spotify 很長的清單目前先抓公開頁看得到的前面（大約幾十到一百首）
- 實況主也常用、尚未直接支援：Apple Music、LINE MUSIC、網易雲音樂、SoundCloud。這些可先匯出／複製成 CSV 再貼上來。之後要加哪一個再說

## 進階（一般不用）

```bash
pip install -r requirements.txt
python server.py
```

Elitesand 不在 3000 時：`GO_TO_KTV_ELITESAND=http://127.0.0.1:3001`

https://github.com/cccsdxtw/go_to_ktv
