@echo off
REM Double-click on Windows: asks for the client URL, cities and name, then runs the audit.
cd /d "%~dp0"
python -m auditor
pause
