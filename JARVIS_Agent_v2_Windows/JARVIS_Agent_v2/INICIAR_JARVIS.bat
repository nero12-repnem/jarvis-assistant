@echo off
chcp 65001 >nul
cd /d "%~dp0"
title JARVIS Agent v2
if not exist ".venv\Scripts\python.exe" (
 echo Execute INSTALAR_JARVIS.bat primeiro.
 pause
 exit /b
)
".venv\Scripts\python.exe" jarvis.py
if errorlevel 1 pause
