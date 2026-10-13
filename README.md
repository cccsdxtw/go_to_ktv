# go_to_ktv

把歌單轉成 Elitesand Pro 可唱的歌：搜 YouTube **伴奏**，再交給 **Elitesand 自己下載**，並掛上目前播放清單。版本 **v0.6.7**（對應 Elitesand Pro **v1.1.0**）。

影片說明：https://youtu.be/PVoaureN8vg

## 怎麼用

不用自己打指令。

1. 安裝一次 [Python](https://www.python.org/downloads/)（Windows 請勾選 Add to PATH）
2. 先打開 **Elitesand Pro**
3. 雙擊 `開始.bat`（Windows；檔名有問題可改雙擊 `start.bat`）或 `開始.command`（Mac）
4. 瀏覽器會自動打開。使用中請留著黑色視窗

不要只雙擊 `index.html`，那樣抓歌單、搜 YouTube、送到 Elitesand 都不會動。

### 轉歌

1. 貼上 `https://streamersonglist.com/t/名稱/songs` 按「抓取歌單」  
   或上傳 CSV／從試算表貼上，按「轉成歌單」（表頭用「標題／歌名」「歌手」；沒表頭時第一欄歌名、第二欄歌手）
2. 按「搜尋 YouTube」（會加「伴奏」，並優先挑伴奏／karaoke）
3. 看一下找到的影片；不對就直接在格子裡改歌名／歌手再重搜
4. 按「**送到 Elitesand 下載**」（按下去會立刻改字，一首一首較久，屬正常）

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
- 網址來源只讀 streamersonglist.com 公開歌單

## 進階（一般不用）

```bash
pip install -r requirements.txt
python server.py
```

Elitesand 不在 3000 時：`GO_TO_KTV_ELITESAND=http://127.0.0.1:3001`

https://github.com/cccsdxtw/go_to_ktv
