@echo off
setlocal
rem Configure SURVEY_REVIEW_SCAN_ROOT, DATA_CHECKOUT and FLAGS once, or pass arguments.
cd /d "%~dp0.."
if not exist ".venv\Scripts\survey.exe" (
  echo Dependencies are not installed. Run uv sync --locked once in this checkout.
  pause
  exit /b 1
)
".venv\Scripts\survey.exe" review --open-browser %*
set "REVIEW_EXIT_CODE=%errorlevel%"
if errorlevel 1 echo Startup failed. Check paths, Git credentials, and whether the port is in use.
echo Review backend stopped. Saved local decisions remain on disk.
pause
exit /b %REVIEW_EXIT_CODE%
