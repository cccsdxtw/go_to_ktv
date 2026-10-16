@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title 歌單轉入
chcp 65001 >nul

echo.
echo 歌單轉入 v1.0.0 啟動中...
echo 這個黑視窗請留著，用完再關。
echo 用完請按網頁「結束程式（讓出 8765）」，或關掉這個視窗。
echo 只關瀏覽器分頁的話，http://127.0.0.1:8765 還會被佔著。
echo.

set "PY="
python -V >nul 2>&1
if not errorlevel 1 set "PY=python"
if not defined PY (
  py -3 -V >nul 2>&1
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  echo 找不到 Python。
  echo 請先安裝：https://www.python.org/downloads/
  echo 安裝時請勾選「Add python.exe to PATH」。
  echo.
  goto :END
)

echo 使用 Python：%PY%
echo 正在準備套件（第一次會久一點，請等）...
%PY% -m pip install -U -r "%~dp0requirements.txt"
if errorlevel 1 (
  echo.
  echo 套件安裝失敗。請確認網路正常，再雙擊一次。
  echo.
  goto :END
)

echo.
echo 正在啟動伺服器，瀏覽器應會自動打開...
echo 看到「打開 http://127.0.0.1:8765」就表示成功。
echo 用完請按網頁紅色「結束程式」，黑視窗會自己關。
echo.
%PY% "%~dp0server.py"
set "ERR=%ERRORLEVEL%"
if "%ERR%"=="0" (
  echo.
  echo 已結束，8765 已讓出，視窗即將關閉。
  ping -n 2 127.0.0.1 >nul
  endlocal
  exit 0
)
echo.
echo 程式異常結束，代碼 %ERR%。

:END
echo.
echo 視窗保留中。看完後按任意鍵關閉。
pause >nul
endlocal
