#!/bin/bash
cd "$(dirname "$0")" || exit 1

echo
echo "歌單轉入 v0.4.3 啟動中..."
echo "這個視窗請留著，用完再關。"
echo "正確網頁標題是「歌單轉入」，不是「哈娜比77 歌單」。"
echo

export PATH="$HOME/Library/Python/3.13/bin:$HOME/Library/Python/3.12/bin:$HOME/Library/Python/3.11/bin:$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"

if ! command -v python3 >/dev/null 2>&1; then
  echo "找不到 Python 3。"
  echo "請先安裝：https://www.python.org/downloads/"
  echo
  read -r -p "按 Enter 關閉…"
  exit 1
fi

echo "使用：$(command -v python3)"
echo "正在準備套件（第一次會久一點，請等）..."
if ! python3 -m pip install -r requirements.txt; then
  echo
  echo "套件安裝失敗。請確認網路正常，再雙擊一次。"
  echo
  read -r -p "按 Enter 關閉…"
  exit 1
fi

echo
echo "正在啟動伺服器，瀏覽器應會自動打開..."
echo "看到「打開 http://127.0.0.1:8765」就表示成功。"
echo "用完後關閉這個視窗即可。"
echo
python3 server.py
CODE=$?
if [ "$CODE" -ne 0 ]; then
  echo
  echo "程式異常結束，代碼 ${CODE}。"
fi
echo
read -r -p "按 Enter 關閉…"
