@echo off
rem Legal-Agent: starts start.ps1 with no window and closes this one immediately.
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0start.ps1"
