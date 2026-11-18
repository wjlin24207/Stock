@echo off
:: 切換到腳本所在的當前資料夾
cd /d "%~dp0"

:: 執行 Git 指令把所有變更上傳
git add .
git commit -m "Auto update ETF data: %date% %time%"
git push origin main

pause