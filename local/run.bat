@echo off
setlocal EnableExtensions
title WealthRadar - make a video
cd /d "%~dp0"
if not exist "requirements.txt" cd /d "%~dp0.."
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
if not exist ".venv\Scripts\python.exe" goto :ERR_SETUP
if not exist ".env" goto :ERR_SETUP
if exist "local\ffmpeg_bin.txt" for /f "usebackq delims=" %%B in ("local\ffmpeg_bin.txt") do set "PATH=%%B;%PATH%"
if not defined NEWSFLOW_FFMPEG_THREADS set "NEWSFLOW_FFMPEG_THREADS=4"
echo.
echo ==== WealthRadar: making a video. 20-60 minutes. Keep the charger in and do not close this window. ====
echo.
".venv\Scripts\python.exe" local\run_local.py
set "CODE=%ERRORLEVEL%"
echo.
if not "%CODE%"=="0" goto :ERR_RUN
echo ==============================================
echo  DONE. Opening the output folder.
echo  Video: output\bulletin\long.mp4
echo  Title and description to paste in YouTube Studio: output\bulletin\upload_kit.txt
echo ==============================================
if exist "output\bulletin" start "" explorer "output\bulletin"
pause
exit /b 0
:ERR_SETUP
echo ERR-SETUP: run setup.bat first (it finishes with SETUP OK).
goto :END
:ERR_RUN
echo ERR-RUN: the render stopped (code %CODE%). The last red or [BLOCKED] lines above say why.
echo If it says BLOCKED with no story, that is normal: no story passed the checks. Try again later.
:END
echo Screenshot this window and send it.
pause
exit /b 1
