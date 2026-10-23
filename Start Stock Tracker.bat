@echo off
rem Starts Stock Tracker without a console window. Double-click this once;
rem the app then offers to put a shortcut on your desktop.
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw "%~dp0StockTracker.pyw" & exit /b)
where pythonw >nul 2>nul && (start "" pythonw "%~dp0StockTracker.pyw" & exit /b)
echo Python was not found.
echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH",
echo then double-click this file again.
pause
