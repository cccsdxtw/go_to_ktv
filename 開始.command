#!/bin/bash
cd "$(dirname "$0")" || exit 1
LOG="$(pwd)/啟動記錄.txt"
{
  echo "==== 歌單轉入啟動 $(date) ===="
  echo "資料夾：$(pwd)"
} >"$LOG"

echo
echo "歌單轉入啟動中..."
echo "若失敗，請打開同資料夾的「啟動記錄.txt」查看原因。"
echo

export PATH="$HOME/Library/Python/3.13/bin:$HOME/Library/Python/3.12/bin:$HOME/Library/Python/3.11/bin:$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[錯誤] 找不到 Python 3。" | tee -a "$LOG"
  echo "請先安裝：https://www.python.org/downloads/"
  echo
  read -r -p "按 Enter 關閉…"
  exit 1
fi

echo "使用：$(command -v python3)" | tee -a "$LOG"
echo "正在準備套件（第一次會久一點）..."
if ! python3 -m pip install -r requirements.txt -q >>"$LOG" 2>&1; then
  echo "[錯誤] pip 安裝失敗。詳細原因在「啟動記錄.txt」。" | tee -a "$LOG"
  echo
  read -r -p "按 Enter 關閉…"
  exit 1
fi

echo "正在啟動伺服器，瀏覽器應會自動打開..."
echo "用完後關閉這個視窗即可。"
echo
echo "---- server.py ----" >>"$LOG"
python3 server.py 2>&1 | tee -a "$LOG"
CODE=${PIPESTATUS[0]}
echo "---- server exit ${CODE} ----" >>"$LOG"
if [ "$CODE" -ne 0 ]; then
  echo
  echo "程式異常結束，代碼 ${CODE}。"
  echo "請打開「啟動記錄.txt」查看原因。"
fi
echo
read -r -p "按 Enter 關閉…"
