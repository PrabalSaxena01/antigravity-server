@echo off
title Antigravity API Server
echo ========================================================
echo        Starting Antigravity Server on this Device
echo ========================================================
python run.py
if %ERRORLEVEL% NEQ 0 (
    echo [!] Python failed to launch. Please make sure Python 3.8+ is installed and on your PATH.
    pause
)
