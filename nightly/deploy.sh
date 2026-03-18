#!/bin/bash
# Quick deploy: push nightly files to server and set up cron
# Usage: bash nightly/deploy.sh [api-key]

set -euo pipefail

SERVER="ubuntu@YOUR_SERVER_IP"
KEY="$HOME/.ssh/your-key.pem"
SSH="ssh -i $KEY -o StrictHostKeyChecking=no $SERVER"
SCP="scp -i $KEY -o StrictHostKeyChecking=no"

echo "=== Installing Node.js (if needed) ==="
$SSH << 'REMOTE'
if ! command -v node &>/dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs
fi
echo "Node: $(node --version)"
REMOTE

echo "=== Installing Claude Code (if needed) ==="
$SSH << 'REMOTE'
if ! command -v claude &>/dev/null; then
    sudo npm install -g @anthropic-ai/claude-code
fi
echo "Claude: $(claude --version 2>/dev/null || echo 'installed')"
REMOTE

echo "=== Setting API key ==="
API_KEY="${1:-}"
if [ -n "$API_KEY" ]; then
    $SSH "grep -q ANTHROPIC_API_KEY ~/.bashrc 2>/dev/null && sed -i '/ANTHROPIC_API_KEY/d' ~/.bashrc; echo 'export ANTHROPIC_API_KEY=$API_KEY' >> ~/.bashrc"
    echo "API key set."
else
    echo "No API key provided. Checking if one exists..."
    $SSH "grep -q ANTHROPIC_API_KEY ~/.bashrc && echo 'Key exists' || echo 'WARNING: No API key found. Run: deploy.sh <your-key>'"
fi

echo "=== Syncing repo ==="
$SSH << 'REMOTE'
cd ~
if [ -d email-campaign ]; then
    cd email-campaign
    git pull origin main --ff-only 2>/dev/null || git pull origin main --rebase
else
    git clone https://github.com/YOUR_ORG/email-campaign.git
fi
REMOTE

echo "=== Making scripts executable ==="
$SSH "chmod +x ~/email-campaign/email_campaign/nightly/runner.sh"
$SSH "mkdir -p ~/email-campaign/email_campaign/nightly/logs"

echo "=== Setting up cron (3am Pacific = 10am UTC) ==="
$SSH << 'REMOTE'
(crontab -l 2>/dev/null | grep -v 'nightly/runner' || true) > /tmp/cron_new
echo "0 10 * * * /home/ubuntu/email-campaign/email_campaign/nightly/runner.sh >> /home/ubuntu/nightly.log 2>&1" >> /tmp/cron_new
crontab /tmp/cron_new
rm /tmp/cron_new
echo "Cron installed:"
crontab -l
REMOTE

echo ""
echo "=== Deploy complete ==="
echo ""
echo "To test manually:"
echo "  ssh -i $KEY $SERVER 'cd ~/email-campaign && bash email_campaign/nightly/runner.sh'"
echo ""
echo "To watch logs:"
echo "  ssh -i $KEY $SERVER 'tail -f ~/nightly.log'"
echo ""
echo "To check task logs:"
echo "  ssh -i $KEY $SERVER 'ls -lt ~/email-campaign/email_campaign/nightly/logs/ | head'"
