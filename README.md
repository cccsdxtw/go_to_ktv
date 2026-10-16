# go_to_ktv

把歌單轉成 Elitesand Pro 可唱的歌：從網址或表格抓歌，必要時搜 YouTube **伴奏**，再交給 **Elitesand 自己下載**，並掛上目前播放清單。版本 **v0.7.3**（對應 Elitesand Pro **v1.1.0**）。

影片說明：https://youtu.be/PVoaureN8vg

## 怎麼用

不用自己打指令。

1. 安裝一次 [Python](https://www.python.org/downloads/)（Windows 請勾選 Add to PATH）
2. 先打開 **Elitesand Pro**
3. 雙擊 `開始.bat`（Windows；檔名有問題可改雙擊 `start.bat`）或 `開始.command`（Mac）
4. 瀏覽器會自動打開。使用中請留著黑色視窗

不要只雙擊 `index.html`，那樣抓歌單、搜 YouTube、送到 Elitesand 都不會動。

### 轉歌

1. 貼上網址按「抓取歌單」，或上傳 CSV／從試算表貼上按「轉成歌單」  
   網址支援：**StreamerSonglist**、**YouTube 播放清單／單支影片**、**KKBOX**、**Spotify** 歌單／專輯／歌曲
2. YouTube 來源已有影片網址，可直接進下一步。其他來源按「搜尋 YouTube」（會加「伴奏」）
3. 看一下找到的影片；不對就直接在格子裡改歌名／歌手再重搜
4. 按「**送到 Elitesand 下載**」（按下去會立刻改字，一首一首較久，屬正常）

若 Elitesand 沒開，會跳出「請開啟Elitesand」。全部送完會跳出「已下載完成」，可按「確認」或「關閉程式」。

音檔會進 Elitesand 媒體庫，並掛上**目前播放清單**（用歌單原本的歌名／歌手）。不必再一首一首點，也不必匯入 json。

Elitesand 有設 PIN 才要填。這個工具跟 Elitesand 要在**同一台電腦**。

### 失敗時

表格上方會列出失敗的歌，點歌名跳到該列。改完歌名／歌手後按「重試這 N 首」，或用「YouTube 失敗／送出失敗」篩選。

### 用完

按頁面上方紅色「**結束程式（讓出 8765）**」。`http://127.0.0.1:8765` 會空出來，黑色命令提示字元也會一起關。下次再雙擊「開始」即可。

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
