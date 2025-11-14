#!/usr/bin/env bash
# Deployment script for Linux server

set -e

echo "=== StreamWatcher Linux Server Deployment ==="
echo ""

# Check if running as root for system package installation
if [ "$EUID" -ne 0 ]; then 
    echo "Note: Some commands may require sudo. Run with sudo for full installation."
fi

# Detect Linux distribution
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    echo "Cannot detect Linux distribution. Assuming Debian/Ubuntu."
    OS="debian"
fi

echo "Detected OS: $OS"
echo ""

# Install system dependencies
echo "Step 1: Installing system dependencies..."
if [ "$OS" == "ubuntu" ] || [ "$OS" == "debian" ]; then
    sudo apt-get update
    sudo apt-get install -y \
        python3 \
        python3-pip \
        python3-venv \
        tesseract-ocr \
        ffmpeg \
        build-essential \
        libssl-dev \
        libffi-dev
elif [ "$OS" == "centos" ] || [ "$OS" == "rhel" ] || [ "$OS" == "fedora" ]; then
    sudo yum install -y \
        python3 \
        python3-pip \
        tesseract \
        ffmpeg \
        gcc \
        openssl-devel \
        libffi-devel
else
    echo "Please install manually: python3, python3-pip, tesseract-ocr, ffmpeg"
fi

echo ""
echo "Step 2: Setting up Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate

echo ""
echo "Step 3: Upgrading pip..."
pip install --upgrade pip setuptools wheel

echo ""
echo "Step 4: Installing Python dependencies..."
pip install -r requirements.txt

echo ""
echo "Step 5: Verifying Tesseract installation..."
if command -v tesseract &> /dev/null; then
    tesseract --version
else
    echo "WARNING: Tesseract not found in PATH. OCR may not work."
fi

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "To run the application:"
echo "  1. Activate virtual environment: source venv/bin/activate"
echo "  2. Set environment variables (see .env.example)"
echo "  3. Run: python app.py"
echo "     OR with gunicorn: gunicorn app:app --bind 0.0.0.0:5001"
echo ""
echo "For production deployment, see DEPLOYMENT.md"

