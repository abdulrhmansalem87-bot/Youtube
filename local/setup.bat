@echo off
setlocal EnableExtensions
title WealthRadar - SETUP (one time)
cd /d "%~dp0"
if not exist "requirements.txt" cd /d "%~dp0.."
echo.
echo ==== WealthRadar setup (one time, about 15-20 minutes) ====
echo Do not close this window. If it stops with ERR-xxx, take a screenshot and send it.
echo.

if not exist "requirements.txt" goto :ERR_FOLDER
if not exist "newsflow\pipeline.py" goto :ERR_FOLDER
echo Folder: %CD%
for /f "skip=1 delims=" %%C in ('wmic cpu get name 2^>nul') do if not defined CPUNAME set "CPUNAME=%%C"
echo CPU: %CPUNAME%
where winget >nul 2>nul || goto :ERR_WINGET

echo.
echo [1/5] Python...
set "PY="
py -3.11 --version >nul 2>nul && set "PY=py -3.11"
if not defined PY if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set PY="%LocalAppData%\Programs\Python\Python311\python.exe"
if not defined PY (
  winget install -e --id Python.Python.3.11 --scope user --accept-package-agreements --accept-source-agreements
  if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set PY="%LocalAppData%\Programs\Python\Python311\python.exe"
  if not defined PY py -3.11 --version >nul 2>nul && set "PY=py -3.11"
)
if not defined PY goto :ERR_PYTHON
%PY% --version || goto :ERR_PYTHON

echo.
echo [2/5] FFmpeg...
call :FINDFF
if not defined FFBIN (
  winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
  call :FINDFF
)
if not defined FFBIN goto :ERR_FFMPEG
echo FFmpeg folder: %FFBIN%
> "local\ffmpeg_bin.txt" echo %FFBIN%
"%FFBIN%\ffmpeg.exe" -version | findstr /b "ffmpeg version" || goto :ERR_FFMPEG

echo.
echo [3/5] Project libraries (a few minutes)...
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv || goto :ERR_VENV
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :ERR_PIP

echo.
echo [4/5] Keys file (.env)
if exist ".env" (
  echo .env already exists - keeping it.
  goto :CHECK
)
echo You need two free keys. Open these pages, make or copy the key, then paste it here
echo (paste = right-click in this window, then Enter). Keys stay on this laptop only.
start "" "https://console.groq.com/keys"
start "" "https://pixabay.com/api/docs/"
start "" "https://app.tavily.com/home"
set /p GROQ=Paste GROQ key and press Enter: 
set /p PIXA=Paste PIXABAY key and press Enter: 
set /p TAV=Paste TAVILY key (or just press Enter to skip): 
if "%GROQ%"=="" goto :ERR_KEYS
if "%PIXA%"=="" goto :ERR_KEYS
> ".env" echo GROQ_API_KEY=%GROQ%
>> ".env" echo PIXABAY_API_KEY=%PIXA%
if not "%TAV%"=="" >> ".env" echo TAVILY_API_KEY=%TAV%
>> ".env" echo NEWSFLOW_TTS_VOICE=ar-EG-ShakirNeural
echo .env saved.

:CHECK
echo.
echo [5/5] Final check...
set "PATH=%FFBIN%;%PATH%"
".venv\Scripts\python.exe" local\run_local.py --check
if errorlevel 1 goto :ERR_CHECK
echo.
echo ==============================================
echo  SETUP OK. Now double-click run.bat
echo ==============================================
pause
exit /b 0

:FINDFF
set "FFBIN="
for /d %%D in ("%LocalAppData%\Microsoft\WinGet\Packages\Gyan.FFmpeg*") do for /d %%E in ("%%D\ffmpeg-*") do if exist "%%E\bin\ffmpeg.exe" set "FFBIN=%%E\bin"
if not defined FFBIN for /f "delims=" %%F in ('where ffmpeg 2^>nul') do if not defined FFBIN set "FFBIN=%%~dpF."
exit /b 0

:ERR_FOLDER
echo.
echo ERR-FOLDER: setup.bat must be inside the unzipped project folder (the one that has requirements.txt).
goto :END
:ERR_WINGET
echo.
echo ERR-WINGET: Windows App Installer (winget) not found. Open Microsoft Store, search "App Installer", Update, then run setup again.
goto :END
:ERR_PYTHON
echo.
echo ERR-PYTHON: Python 3.11 did not install. Restart the laptop, then run setup.bat again.
goto :END
:ERR_FFMPEG
echo.
echo ERR-FFMPEG: FFmpeg did not install. Restart the laptop, then run setup.bat again.
goto :END
:ERR_VENV
echo.
echo ERR-VENV: could not create the Python environment. Move the folder to C:\newsflow (short path) and run again.
goto :END
:ERR_PIP
echo.
echo ERR-PIP: library install failed. Check the internet, then run setup.bat again. If the folder path is long, move it to C:\newsflow.
goto :END
:ERR_KEYS
echo.
echo ERR-KEYS: Groq and Pixabay keys are required. Run setup.bat again.
goto :END
:ERR_CHECK
echo.
echo ERR-CHECK: the line above starting with LOCAL_PREFLIGHT_FAIL says what is missing. Screenshot it.
goto :END
:END
echo.
echo Screenshot this window and send it.
pause
exit /b 1
