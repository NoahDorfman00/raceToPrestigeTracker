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
        tesseract-ocr-eng \
        ffmpeg \
        build-essential \
        libssl-dev \
        libffi-dev
elif [ "$OS" == "centos" ] || [ "$OS" == "rhel" ] || [ "$OS" == "fedora" ]; then
    sudo yum install -y \
        python3 \
        python3-pip \
        tesseract \
        tesseract-langpack-eng \
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
    TESSERACT_VERSION=$(tesseract --version 2>&1 | head -n 1)
    echo "✓ Tesseract found: $TESSERACT_VERSION"
    
    # Verify Tesseract is accessible from Python
    echo "Verifying Tesseract Python integration..."
    if python3 -c "import pytesseract; print('Tesseract version:', pytesseract.get_tesseract_version())" 2>/dev/null; then
        echo "✓ Tesseract is accessible from Python"
    else
        echo "✗ WARNING: Tesseract is installed but not accessible from Python"
        echo "  This may cause OCR detection to fail."
        echo "  Try running: export TESSDATA_PREFIX=/usr/share/tesseract-ocr"
    fi
else
    echo "✗ ERROR: Tesseract not found in PATH!"
    echo "  Tesseract is required for OCR detection to work."
    echo "  Please install it manually:"
    echo "    Ubuntu/Debian: sudo apt-get install tesseract-ocr tesseract-ocr-eng"
    echo "    CentOS/RHEL: sudo yum install tesseract tesseract-langpack-eng"
    exit 1
fi

echo ""
echo "Step 6: Verifying other system dependencies..."
# Verify streamlink
if command -v streamlink &> /dev/null || [ -f "venv/bin/streamlink" ]; then
    echo "✓ streamlink found"
else
    echo "✗ WARNING: streamlink not found (should be in venv/bin/streamlink)"
fi

# Verify ffmpeg
if command -v ffmpeg &> /dev/null; then
    echo "✓ ffmpeg found"
else
    echo "⚠ WARNING: ffmpeg not found (optional, but recommended)"
fi

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "To run the application:"
echo "  1. Activate virtual environment: source venv/bin/activate"
echo "  2. Set environment variables (see .env.example)"
echo "  3. Run: python app.py"
echo ""
echo "For production deployment, see DEPLOYMENT.md"