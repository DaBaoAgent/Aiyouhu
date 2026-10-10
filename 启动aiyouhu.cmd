@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title AINSNBOT
cd /d D:\@kaifa\Aiyouhu
echo ============================================
echo  AINSNBOT 启动中...
echo  启动后浏览器将自动打开 http://localhost:7860
echo  关闭本窗口即停止 AINSNBOT（可随时重新双击启动）
echo ============================================
set "PATH=D:\@kaifa\Aiyouhu\.venv\Scripts;C:\Users\20200\node24\node-v24.21.0-win-x64;C:\Users\20200\AppData\Local\hermes\git\cmd;C:\Users\20200\bin;%PATH%"
echo  正在启动 OpenClaw 网关...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\gateway.ps1" start
start "" http://localhost:7860
.venv\Scripts\easel.exe web
pause
