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
start "" http://localhost:7860
.venv\Scripts\easel.exe web
pause
