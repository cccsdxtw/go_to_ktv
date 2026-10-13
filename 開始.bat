@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 歌單轉入

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo 找不到 Python。
  echo 請先安裝：https://www.python.org/downloads/
  echo 安裝時請勾選「Add python.exe to PATH」。
  pause
  exit /b 1
)

echo 正在準備套件（第一次會久一點）...
%PY% -m pip install -r requirements.txt -q
if errorlevel 1 (
  echo 套件安裝失敗，請確認網路與 Python 正常。
  pause
  exit /b 1
)

echo 正在啟動，瀏覽器會自動打開…
echo 用完後關閉這個視窗即可。
echo.
%PY% server.py
echo.
pause
