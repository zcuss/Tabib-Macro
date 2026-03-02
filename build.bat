@echo off
cd /d %~dp0
py -m pip install -r requirements.txt
py -m PyInstaller --onefile --noconsole --name TabibMacro app.py
echo.
echo Build selesai. EXE ada di folder dist\TabibMacro.exe
pause
