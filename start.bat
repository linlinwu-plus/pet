@echo off
rem Bubble Cat desktop pet - silent launcher
cd /d "%~dp0"
where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw "%~dp0pet.py"
) else (
    start "" python "%~dp0pet.py"
)
