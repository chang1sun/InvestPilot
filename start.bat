@echo off
echo ========================================
echo 🚀 AI Quant Agent - Quick Start Script
echo ========================================
echo.

REM Check if virtual environment exists
if not exist "venv\" (
    echo 📦 Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
echo 🔧 Activating virtual environment...
call venv\Scripts\activate.bat

REM Install dependencies
echo 📥 Installing dependencies...
pip install -r requirements.txt

REM Check if GEMINI_API_KEY is set
if "%GEMINI_API_KEY%"=="" (
    echo ⚠️  Warning: GEMINI_API_KEY environment variable is not set!
    echo    Please set it in your environment or config.py
    echo    Get your free API key at: https://aistudio.google.com/app/apikey
    echo.
)

REM Start application
echo.
echo ✅ Starting application...
echo    Access at: http://localhost:5000
echo.
python app.py

pause

