@echo off
REM =========================================================================
REM  Automated Video De-duplication & Batch Sanitizer Tool
REM  Single-command PyInstaller build for Windows
REM
REM  Usage (double-click, or from a terminal in this folder):
REM      build_exe.bat
REM
REM  Requirements before running this script:
REM    1. Python 3.9+ installed, with "Add python.exe to PATH" checked.
REM    2. FFmpeg installed (see README.md). The .exe does NOT bundle
REM       ffmpeg.exe by itself -- see the note at the bottom of this file.
REM =========================================================================
setlocal

echo Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found on PATH.
    echo Install Python 3.9+ from python.org and tick "Add python.exe to PATH".
    pause
    exit /b 1
)

echo Installing PyInstaller (one time)...
python -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo [ERROR] Could not install PyInstaller. Check your internet connection.
    pause
    exit /b 1
)

echo Building standalone .exe (this may take 1-3 minutes)...
python -m PyInstaller --noconfirm --onefile --windowed ^
    --name "VideoSanitizer" ^
    main.py
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed. See the output above.
    pause
    exit /b 1
)

echo.
echo =========================================================================
echo  BUILD COMPLETE
echo  Your program is here:
echo      dist\VideoSanitizer.exe
echo.
echo  IMPORTANT - FFmpeg:
echo  VideoSanitizer.exe still needs ffmpeg.exe and ffprobe.exe.
echo  Copy BOTH files into the SAME folder as VideoSanitizer.exe
echo  (for example, the dist folder, or wherever you ship the .exe),
echo  or make sure FFmpeg is installed on the buyer's computer and
echo  on PATH. The app checks for them on startup and will warn
echo  you if they are missing.
echo =========================================================================
pause
endlocal
