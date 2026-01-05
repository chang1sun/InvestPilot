#!/bin/bash
# ============================================================
# SQLite Database Initialization Script
# ============================================================
# Description: Initialize SQLite database for InvestPilot
# Usage: ./tools/init_sqlite.sh
# ============================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}InvestPilot SQLite Database Initialization${NC}"
echo -e "${BLUE}============================================================${NC}"
echo ""

# Load environment variables
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo -e "${GREEN}✓${NC} Loading environment variables from .env"
    export $(cat "$PROJECT_ROOT/.env" | grep -v '^#' | xargs)
else
    echo -e "${YELLOW}⚠${NC} .env file not found, using default values"
fi

# Get database path from environment or use default
DATABASE_URL=${DATABASE_URL:-sqlite:///investpilot.db}
DB_PATH=$(echo "$DATABASE_URL" | sed 's|sqlite:///||')

# If relative path, make it absolute
if [[ ! "$DB_PATH" = /* ]]; then
    DB_PATH="$PROJECT_ROOT/$DB_PATH"
fi

echo -e "${BLUE}Database Configuration:${NC}"
echo -e "  Type: SQLite"
echo -e "  Path: ${DB_PATH}"
echo ""

# Check if database already exists
if [ -f "$DB_PATH" ]; then
    echo -e "${YELLOW}⚠ Database file already exists: ${DB_PATH}${NC}"
    read -p "Do you want to recreate it? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Backing up existing database...${NC}"
        cp "$DB_PATH" "${DB_PATH}.backup.$(date +%Y%m%d_%H%M%S)"
        echo -e "${GREEN}✓${NC} Backup created"
    else
        echo -e "${BLUE}Keeping existing database, will only create missing tables${NC}"
    fi
fi

# Check if python is available
if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python not found${NC}"
    echo -e "${YELLOW}Please install Python 3.7+ to continue${NC}"
    exit 1
fi

# Determine python command
PYTHON_CMD="python"
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
fi

echo -e "${GREEN}Using Python: $($PYTHON_CMD --version)${NC}"
echo ""

# Execute Python script
echo -e "${GREEN}Executing database initialization...${NC}"
cd "$PROJECT_ROOT"
$PYTHON_CMD tools/init_db.py

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✓ Database initialized successfully!${NC}"
    echo ""
    echo -e "${BLUE}Database file: ${DB_PATH}${NC}"
    
    # Show database size
    if [ -f "$DB_PATH" ]; then
        DB_SIZE=$(du -h "$DB_PATH" | cut -f1)
        echo -e "${BLUE}Database size: ${DB_SIZE}${NC}"
    fi
else
    echo ""
    echo -e "${RED}✗ Database initialization failed${NC}"
    exit 1
fi

echo ""
echo -e "${BLUE}============================================================${NC}"
echo -e "${GREEN}Next Steps:${NC}"
echo -e "  1. Start application: python run.py"
echo -e "  2. Access web interface: http://localhost:5000"
echo -e "  3. View database: sqlite3 ${DB_PATH}"
echo -e "${BLUE}============================================================${NC}"
echo ""
