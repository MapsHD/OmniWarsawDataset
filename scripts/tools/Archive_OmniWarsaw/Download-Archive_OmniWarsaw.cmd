@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Download-Archive_OmniWarsaw.ps1" %*
set "download_exit=%errorlevel%"
echo.
echo Exit code: %download_exit%. Run again to resume segments in the same folder.
echo Press any key to close this window...
pause >nul
exit /b %download_exit%
