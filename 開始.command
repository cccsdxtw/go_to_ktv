#!/bin/bash
cd "$(dirname "$0")"
export PATH="$HOME/Library/Python/3.*/bin:$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"

if ! command -v python3 >/dev/null 2>&1; then
  echo "找不到 Python 3。請先安裝：https://www.python.org/downloads/"
  read -r -p "按 Enter 關閉…"
  exit 1
fi

echo "正在準備套件（第一次會久一點）…"
python3 -m pip install -r requirements.txt -q
if [ $? -ne 0 ]; then
  echo "套件安裝失敗，請確認網路與 Python 正常。"
  read -r -p "按 Enter 關閉…"
  exit 1
fi

echo "正在啟動，瀏覽器會自動打開…"
echo "用完後關閉這個視窗即可。"
echo
python3 server.py
echo
read -r -p "按 Enter 關閉…"
