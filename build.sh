#!/usr/bin/env bash
# Build script for Render deployment

# Install system dependencies for Tesseract OCR
apt-get update && apt-get install -y tesseract-ocr

# Install Python dependencies
pip install -r requirements.txt

