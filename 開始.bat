@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title 歌單轉入
chcp 65001 >nul

set "LOG=%~dp0啟動記錄.txt"
echo ==== 歌單轉入啟動 %DATE% %TIME% ==== > "%LOG%"
echo 資料夾：%~dp0>> "%LOG%"

echo.
echo 歌單轉入啟動中...
echo 若失敗，請打開同資料夾的「啟動記錄.txt」查看原因。
echo.

set "PY="
python -V >nul 2>&1
if not errorlevel 1 set "PY=python"
if not defined PY (
  py -3 -V >nul 2>&1
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  echo [錯誤] 找不到 Python。>> "%LOG%"
  echo 找不到 Python。
  echo 請先安裝：https://www.python.org/downloads/
  echo 安裝時請勾選「Add python.exe to PATH」。
  echo.
  goto :END
)

echo 使用：%PY%>> "%LOG%"
echo 使用 Python：%PY%
echo 正在準備套件（第一次會久一點）...
%PY% -m pip install -r "%~dp0requirements.txt" -q >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [錯誤] pip 安裝失敗。>> "%LOG%"
  echo 套件安裝失敗。詳細原因在「啟動記錄.txt」。
  echo.
  goto :END
)

echo 正在啟動伺服器，瀏覽器應會自動打開...
echo 用完後關閉這個視窗即可。
echo.
echo ---- server.py ---->> "%LOG%"
%PY% "%~dp0server.py" >> "%LOG%" 2>&1
set "ERR=%ERRORLEVEL%"
echo ---- server exit %ERR% ---->> "%LOG%"
if not "%ERR%"=="0" (
  echo.
  echo 程式異常結束，代碼 %ERR%。
  echo 請打開「啟動記錄.txt」查看原因。
)

:END
echo.
echo 視窗保留中。看完後按任意鍵關閉。
pause >nul
endlocal
