@echo off
title JARVIS MISSION CONTROL OS - AUTONOMOUS CAREER ENGINE
mode con: cols=115 lines=35
color 0B
cd /d "%~dp0"

echo ===================================================================================================
echo     JARVIS MISSION CONTROL OS -- AUTONOMOUS JOB AGENT & 24/7 LIVE PIPELINE
echo     Candidate: Naga Satya Phanindra Vallabhaneni (Dayton, OH)
echo     Mode: FULL INTERACTIVE WEB UI + LIVE DESKTOP CHROMIUM GUI
echo ===================================================================================================
echo.

set "PYTHON_EXE=C:\Users\phani\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python"
)

echo [*] Starting Jarvis Mission Control Server on http://127.0.0.1:8765 ...
start "Jarvis Server Engine" /min "%PYTHON_EXE%" -u hunter_server.py

echo [*] Starting Autonomous 5-Minute Market Scanner Daemon...
start "Jarvis Autonomous Scanner" /min "%PYTHON_EXE%" -u autonomous_scanner_5min.py

echo [*] Waiting for Mission Control Server to initialize...
timeout /t 3 /nobreak >nul

echo [*] Launching Jarvis Mission Control UI in your default browser...
start http://127.0.0.1:8765/

echo.
echo ===================================================================================================
echo   MISSION CONTROL UI IS NOW LIVE AT:
echo   --^> http://127.0.0.1:8765/
echo.
echo   Features Active in UI:
echo   - 5-Column Live Kanban Pipeline (Discovered / Captured / Submitted / Confirmed / Radar)
echo   - 50,000+ US Company Universe Directory with Underdog Backbone Filtering
echo   - 24/7 Night Shift Scheduler (Configured up to 50 apps/night)
echo   - Unlimited Manual Auto-Apply Mode (No Limits)
echo   - Live Visible Chromium Automation Viewport with Co-Pilot Pre-Submission Review Gate
echo   - Star Method AI Interview Coach & Recruiter Outreach Generator
echo   - Gmail IMAP Application Tracking Radar
echo ===================================================================================================
echo.
echo Press any key to stop all Jarvis services and exit...
pause >nul

echo Stopping background Jarvis services...
taskkill /f /fi "WINDOWTITLE eq Jarvis*" >nul 2>&1
echo Done. Goodbye Phanindra!
