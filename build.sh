#!/usr/bin/env bash
# Build script for Render deployment

set -e  # Exit on error

# Check Python version
echo "Python version:"
python --version

# Upgrade pip first
pip install --upgrade pip

# Install setuptools and wheel first (pinned versions)
pip install setuptools==60.10.0 wheel

# Install system dependencies for Tesseract OCR
apt-get update && apt-get install -y tesseract-ocr

# Install base dependencies first (ones with reliable wheels)
pip install numpy==1.26.2 Pillow==10.1.0 requests==2.31.0

# Install remaining dependencies
pip install -r requirements.txt

