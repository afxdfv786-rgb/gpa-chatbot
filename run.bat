@echo off
cd /d "%~dp0"
echo ===== GradeMate GPA Chatbot =====

if exist venv\Scripts\activate.bat goto start

echo First-time setup. Installing packages, this takes 1 to 2 minutes and needs internet.
python -m venv venv
if errorlevel 1 goto nopython
call venv\Scripts\activate.bat
pip install -r requirements.txt
if errorlevel 1 goto pipfail
goto run

:start
call venv\Scripts\activate.bat

:run
echo.
echo Starting GradeMate. Your browser will open in a few seconds.
echo Keep this window OPEN while you use the chatbot.
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:5000"
python app.py
echo.
echo GradeMate stopped. Read any message above.
pause
exit /b

:nopython
echo.
echo Python was not found. Install Python from python.org and tick Add Python to PATH, then run this file again.
pause
exit /b 1

:pipfail
echo.
echo Package install failed. Check your internet connection, delete the venv folder, and run this file again.
pause
exit /b 1
