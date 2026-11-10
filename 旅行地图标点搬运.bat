@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
if exist "%ROOT%python\python.exe" (
  "%ROOT%python\python.exe" "%ROOT%app\main.py" %*
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python runtime not found.
    echo Run tools\build_dist.py to assemble the distributable package.
    pause
    exit /b 1
  )
  python "%ROOT%app\main.py" %*
)
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
