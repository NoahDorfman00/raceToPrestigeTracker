# Linux Server Deployment Guide

This guide will help you deploy StreamWatcher on your own Linux server.

## Prerequisites

- Linux server (Ubuntu/Debian recommended, but any Linux distro works)
- Python 3.9+ installed
- At least 2GB RAM (4GB+ recommended if using EasyOCR)
- Root/sudo access for installing system packages
- Port 5001 (or your chosen port) open in firewall

## Quick Setup

### 1. Clone/Upload the Project

```bash
# If using git
git clone <your-repo-url>
cd streamWatcher

# Or upload files via SCP/SFTP
```

### 2. Run the Deployment Script

```bash
chmod +x deploy.sh
sudo ./deploy.sh
```

This will:
- Install system dependencies (Tesseract OCR, Python, etc.)
- Create a Python virtual environment
- Install all Python packages

### 3. Configure Environment Variables

Create a `.env` file (optional, or set environment variables):

```bash
# Memory optimization (recommended for servers with <4GB RAM)
export DISABLE_EASYOCR=true          # Saves ~1-2GB RAM
export MAX_STREAMS=5                  # Number of concurrent streams
export FRAME_SCALE=0.75               # Resize frames to save memory (0.5-1.0)

# Server configuration
export PORT=5001                      # Port to run on
export FLASK_ENV=production           # Production mode

# Firebase (if using admin features)
export FIREBASE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
```

### 4. Run the Application

#### Development Mode (for testing):
```bash
source venv/bin/activate
python app.py
```

#### Production Mode (with Gunicorn):
```bash
source venv/bin/activate
gunicorn app:app --bind 0.0.0.0:5001 --workers 2 --threads 2
```

## Production Deployment with Systemd

Create a systemd service to run the app automatically:

### 1. Create Service File

```bash
sudo nano /etc/systemd/system/streamwatcher.service
```

Add this content:

```ini
[Unit]
Description=StreamWatcher Flask Application
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/streamWatcher
Environment="PATH=/path/to/streamWatcher/venv/bin"
Environment="DISABLE_EASYOCR=true"
Environment="MAX_STREAMS=5"
Environment="FRAME_SCALE=0.75"
Environment="PORT=5001"
Environment="FLASK_ENV=production"
# Uncomment and add if using Firebase:
# Environment="FIREBASE_SERVICE_ACCOUNT_JSON={\"type\":\"service_account\",...}"
ExecStart=/path/to/streamWatcher/venv/bin/gunicorn app:app --bind 0.0.0.0:5001 --workers 2 --threads 2
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Important:** Replace:
- `your-username` with your Linux username
- `/path/to/streamWatcher` with the actual path to your project

### 2. Enable and Start the Service

```bash
sudo systemctl daemon-reload
sudo systemctl enable streamwatcher
sudo systemctl start streamwatcher
sudo systemctl status streamwatcher
```

### 3. View Logs

```bash
# View logs
sudo journalctl -u streamwatcher -f

# View recent logs
sudo journalctl -u streamwatcher -n 50
```

## Reverse Proxy with Nginx (Optional but Recommended)

### 1. Install Nginx

```bash
sudo apt-get install nginx
```

### 2. Create Nginx Configuration

```bash
sudo nano /etc/nginx/sites-available/streamwatcher
```

Add:

```nginx
server {
    listen 80;
    server_name your-domain.com;  # Replace with your domain or IP

    location / {
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support (if needed)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 3. Enable the Site

```bash
sudo ln -s /etc/nginx/sites-available/streamwatcher /etc/nginx/sites-enabled/
sudo nginx -t  # Test configuration
sudo systemctl restart nginx
```

### 4. Set Up SSL with Let's Encrypt (Optional)

```bash
sudo apt-get install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

## Firewall Configuration

```bash
# Ubuntu/Debian (UFW)
sudo ufw allow 5001/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# CentOS/RHEL (firewalld)
sudo firewall-cmd --permanent --add-port=5001/tcp
sudo firewall-cmd --permanent --add-port=80/tcp
sudo firewall-cmd --permanent --add-port=443/tcp
sudo firewall-cmd --reload
```

## Memory Optimization

If you have limited RAM, use these settings:

```bash
# In your systemd service or .env file:
export DISABLE_EASYOCR=true    # Saves 1-2GB (uses Tesseract only)
export MAX_STREAMS=3           # Reduce concurrent streams
export FRAME_SCALE=0.5         # Resize frames to 50% (saves ~75% frame memory)
```

## Troubleshooting

### Check if the app is running:
```bash
sudo systemctl status streamwatcher
ps aux | grep gunicorn
```

### Check logs:
```bash
sudo journalctl -u streamwatcher -f
```

### Restart the service:
```bash
sudo systemctl restart streamwatcher
```

### Test Tesseract:
```bash
tesseract --version
```

### Test the application:
```bash
curl http://localhost:5001
```

## Updating the Application

```bash
cd /path/to/streamWatcher
source venv/bin/activate
git pull  # If using git
pip install -r requirements.txt
sudo systemctl restart streamwatcher
```

## Security Considerations

1. **Firewall**: Only expose necessary ports (80, 443 if using Nginx)
2. **Firebase**: Store `FIREBASE_SERVICE_ACCOUNT_JSON` securely, don't commit to git
3. **User permissions**: Run the service as a non-root user
4. **HTTPS**: Use Let's Encrypt for SSL certificates
5. **Environment variables**: Keep sensitive data in environment variables, not in code

## Performance Tuning

- **Workers**: Adjust `--workers` in gunicorn based on CPU cores (typically 2-4)
- **Threads**: Adjust `--threads` based on I/O operations (2-4 usually good)
- **Memory**: Monitor with `htop` or `free -h` and adjust `MAX_STREAMS` and `FRAME_SCALE` accordingly

