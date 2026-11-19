@echo off

cd /d "%~dp0"


git add .
git commit -m "Auto update ETF data: %date% %time%"
git push origin main

pause