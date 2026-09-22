#!/bin/bash
# AWS EC2 setup script for NSE Swing Trading Agent
# Run on a fresh Ubuntu 22.04+ EC2 instance (t3.small recommended)
#
# Prerequisites:
#   - EC2 instance with IAM role "TradingAgentRole" attached (see deploy/iam-policy.json)
#   - Security group allowing inbound 80, 443, 22
#   - At least 2GB RAM, 20GB disk
#
# Usage: bash deploy/setup.sh

set -euo pipefail

APP_DIR="/opt/trading-agent"

echo "============================================"
echo "  NSE Swing Trading Agent — AWS Setup"
echo "============================================"
echo ""

# --- System updates ---
echo "[1/6] Updating system packages..."
sudo apt-get update -qq && sudo apt-get upgrade -y -qq

# --- Install Docker ---
echo "[2/6] Installing Docker..."
if ! command -v docker &>/dev/null; then
    sudo apt-get install -y -qq ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg

    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt-get update -qq
    sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    sudo usermod -aG docker "$USER"
    echo "  Docker installed. You may need to log out and back in for group change."
else
    echo "  Docker already installed."
fi

# --- Install Nginx ---
echo "[3/6] Installing Nginx..."
sudo apt-get install -y -qq nginx

# --- Create app directory ---
echo "[4/6] Setting up application directory..."
sudo mkdir -p "$APP_DIR"
sudo chown "$USER:$USER" "$APP_DIR"

# --- Copy Nginx config ---
echo "[5/6] Configuring Nginx reverse proxy..."
sudo tee /etc/nginx/sites-available/trading-agent > /dev/null <<'NGINX'
server {
    listen 80;
    server_name _;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 10s;
    }

    location /static/ {
        alias /opt/trading-agent/web/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    # Health check endpoint (no proxy overhead)
    location = /health {
        proxy_pass http://127.0.0.1:8000/;
        proxy_read_timeout 5s;
        access_log off;
    }
}
NGINX

sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sf /etc/nginx/sites-available/trading-agent /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl enable nginx

# --- Verify AWS access ---
echo "[6/6] Verifying AWS Bedrock access..."
if command -v aws &>/dev/null; then
    REGION=$(curl -s http://169.254.169.254/latest/meta-data/placement/region 2>/dev/null || echo "unknown")
    echo "  EC2 region: $REGION"
    echo "  Testing IAM role..."
    if aws sts get-caller-identity --region "$REGION" &>/dev/null; then
        ROLE_ARN=$(aws sts get-caller-identity --query Arn --output text --region "$REGION")
        echo "  IAM Role: $ROLE_ARN"
    else
        echo "  WARNING: No IAM role detected. Attach TradingAgentRole to this instance."
    fi
else
    echo "  AWS CLI not found — installing..."
    sudo apt-get install -y -qq awscli
    REGION=$(curl -s http://169.254.169.254/latest/meta-data/placement/region 2>/dev/null || echo "ap-south-1")
    echo "  EC2 region: $REGION"
fi

echo ""
echo "============================================"
echo "  Setup complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo ""
echo "  1. Copy project files to $APP_DIR:"
echo "     scp -r ./* ec2-user@<IP>:$APP_DIR/"
echo ""
echo "  2. Create .env file:"
echo "     cd $APP_DIR"
echo "     cp .env.example .env"
echo "     nano .env  # Set AWS_REGION and Telegram tokens"
echo ""
echo "  3. Start the application:"
echo "     cd $APP_DIR && docker compose up -d --build"
echo ""
echo "  4. Check logs:"
echo "     docker compose logs -f"
echo ""
echo "  5. (Optional) Add SSL with Let's Encrypt:"
echo "     sudo apt install certbot python3-certbot-nginx"
echo "     sudo certbot --nginx -d yourdomain.com"
echo ""
echo "  6. Verify:"
echo "     curl http://localhost"
echo "     curl http://<your-ec2-public-ip>"
echo ""
