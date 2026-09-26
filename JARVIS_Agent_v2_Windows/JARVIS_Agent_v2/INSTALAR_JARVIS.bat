@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Instalador JARVIS Agent v2
where py >nul 2>nul
if errorlevel 1 (set PY=python) else (set PY=py)
%PY% -m venv .venv
if errorlevel 1 goto erro
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 goto erro
echo.
echo Instalacao concluida.
echo Configure as IAs em CONFIGURAR_IA.bat e inicie o JARVIS.
pause
exit /b
:erro
echo Erro na instalacao. Envie o erro ao ChatGPT.
pause
