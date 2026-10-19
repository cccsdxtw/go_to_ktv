#!/bin/bash
cd "$(dirname "$0")" || exit 1

echo
echo "歌單轉入 v1.0.6 啟動中..."
echo "這個視窗請留著，用完再關。"
echo "用完請按網頁「結束程式（讓出 8765）」，或關掉這個視窗。"
echo "只關瀏覽器分頁的話，http://127.0.0.1:8765 還會被佔著。"
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
if ! python3 -m pip install -U -r requirements.txt; then
  echo
  echo "套件安裝失敗。請確認網路正常，再雙擊一次。"
  echo
  read -r -p "按 Enter 關閉…"
  exit 1
fi

echo
echo "正在啟動伺服器，瀏覽器應會自動打開..."
echo "看到「打開 http://127.0.0.1:8765」就表示成功。"
echo "用完請按網頁「結束程式」，或關掉這個視窗，8765 才會讓出來。"
echo
python3 server.py
CODE=$?
if [ "$CODE" -eq 0 ]; then
  echo
  echo "已結束，8765 已讓出，視窗即將關閉。"
  osascript -e 'tell application "Terminal" to close front window' >/dev/null 2>&1 || true
  exit 0
fi
echo
echo "程式異常結束，代碼 ${CODE}。"
echo
read -r -p "按 Enter 關閉…"
