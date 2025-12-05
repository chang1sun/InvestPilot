#!/bin/bash

echo "🚀 AI Quant Agent - Quick Start Script"
echo "======================================"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install -r requirements.txt

# Check if GEMINI_API_KEY is set
if [ -z "$GEMINI_API_KEY" ]; then
    echo "⚠️  Warning: GEMINI_API_KEY environment variable is not set!"
    echo "   Please set it in your environment or config.py"
    echo "   Get your free API key at: https://aistudio.google.com/app/apikey"
fi

# Start Redis (optional)
echo "🔍 Checking for Redis..."
if command -v docker &> /dev/null; then
    if ! docker ps | grep -q quant_redis; then
        echo "🐳 Starting Redis container..."
        docker run -d -p 6379:6379 --name quant_redis redis:alpine 2>/dev/null || echo "   Redis already running or Docker unavailable (will use in-memory cache)"
    else
        echo "   Redis is already running"
    fi
else
    echo "   Docker not found (will use in-memory cache)"
fi

# Initialize database and start application
echo ""
echo "✅ Starting application..."
echo "   Access at: http://localhost:5000"
echo ""
python app.py

