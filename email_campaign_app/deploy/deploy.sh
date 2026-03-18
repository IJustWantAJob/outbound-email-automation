#!/bin/bash
# Deploy Email Campaign Manager to server
set -e

REMOTE="ubuntu@YOUR_SERVER_IP"
SSH_KEY="$HOME/.ssh/your-key.pem"
APP_DIR="/opt/email-campaign"
LOCAL_APP="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Email Campaign Manager Deployment ==="

# 1. Create directories on server
echo "[1/8] Creating directories..."
ssh -i $SSH_KEY $REMOTE "sudo mkdir -p $APP_DIR/{data,logs,reports,static} && sudo chown -R ubuntu:ubuntu $APP_DIR"

# 2. Sync app files (exclude tests, __pycache__, .db files)
echo "[2/8] Syncing application files..."
rsync -avz --delete \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache' \
    --exclude='tests/' \
    --exclude='data/*.db' \
    --exclude='data/client_secret*.json' \
    --exclude='reports/*.md' \
    --exclude='.env' \
    --exclude='venv/' \
    --exclude='logs/' \
    -e "ssh -i $SSH_KEY" \
    "$LOCAL_APP/" "$REMOTE:$APP_DIR/"

# 3. Setup Python venv and install deps
echo "[3/8] Setting up Python environment..."
ssh -i $SSH_KEY $REMOTE "cd $APP_DIR && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt -q"

# 4. Setup SSL certs
echo "[4/8] Setting up Cloudflare origin certificates..."
ssh -i $SSH_KEY $REMOTE "sudo mkdir -p /etc/ssl/cloudflare"

# 5. Install Nginx config
echo "[5/8] Configuring Nginx..."
ssh -i $SSH_KEY $REMOTE "sudo cp $APP_DIR/deploy/nginx-campaign.conf /etc/nginx/sites-available/campaign && sudo ln -sf /etc/nginx/sites-available/campaign /etc/nginx/sites-enabled/campaign && sudo nginx -t && sudo systemctl reload nginx"

# 6. Install systemd service
echo "[6/8] Installing systemd service..."
ssh -i $SSH_KEY $REMOTE "sudo cp $APP_DIR/deploy/email-campaign.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable email-campaign"

# 7. Initialize database
echo "[7/8] Initializing database..."
ssh -i $SSH_KEY $REMOTE "cd $APP_DIR && source venv/bin/activate && python3 -c 'from app import create_app; app = create_app(); print(\"DB initialized\")'"

# 8. Start/restart service
echo "[8/8] Starting service..."
ssh -i $SSH_KEY $REMOTE "sudo systemctl restart email-campaign && sleep 2 && sudo systemctl status email-campaign --no-pager"

echo ""
echo "=== Deployment complete! ==="
echo "App: https://campaign.example.com/"
echo "Logs: ssh -i $SSH_KEY $REMOTE 'sudo journalctl -u email-campaign -f'"
