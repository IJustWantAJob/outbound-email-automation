#!/bin/bash
# One-time setup for server to run nightly Claude Code automation
# Run this from your local machine:
#   bash nightly/setup_server.sh

set -euo pipefail

SERVER="ubuntu@YOUR_SERVER_IP"
KEY="$HOME/.ssh/your-key.pem"
SSH="ssh -i $KEY -o StrictHostKeyChecking=no $SERVER"
SCP="scp -i $KEY -o StrictHostKeyChecking=no"

echo "=== Step 1: Install Node.js 20 LTS ==="
$SSH << 'REMOTE'
if ! command -v node &>/dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs
    echo "Node $(node --version) installed"
else
    echo "Node already installed: $(node --version)"
fi
REMOTE

echo "=== Step 2: Install Claude Code CLI ==="
$SSH << 'REMOTE'
if ! command -v claude &>/dev/null; then
    sudo npm install -g @anthropic-ai/claude-code
    echo "Claude Code installed: $(claude --version 2>/dev/null || echo 'installed')"
else
    echo "Claude Code already installed"
fi
REMOTE

echo "=== Step 3: Clone repo (or pull latest) ==="
$SSH << 'REMOTE'
cd ~
if [ -d email-campaign ]; then
    cd email-campaign
    git pull origin main
    echo "Repo updated"
else
    git clone https://github.com/YOUR_ORG/email-campaign.git
    echo "Repo cloned"
fi
REMOTE

echo "=== Step 4: Set up ANTHROPIC_API_KEY ==="
echo ""
echo "IMPORTANT: You need to set your API key on the server."
echo "SSH in and run:"
echo "  echo 'export ANTHROPIC_API_KEY=sk-ant-...' >> ~/.bashrc"
echo ""
echo "Or pass it now (will be appended to ~/.bashrc):"
read -rp "Enter ANTHROPIC_API_KEY (or press Enter to skip): " api_key
if [ -n "$api_key" ]; then
    $SSH "grep -q ANTHROPIC_API_KEY ~/.bashrc || echo 'export ANTHROPIC_API_KEY=$api_key' >> ~/.bashrc"
    echo "API key saved to ~/.bashrc"
fi

echo "=== Step 5: Set up cron job (3am-7am Pacific = 10am-2pm UTC) ==="
$SSH << 'REMOTE'
# Remove old cron entries
crontab -l 2>/dev/null | grep -v 'nightly_runner' > /tmp/crontab_clean || true

# Add new entry: run at 10:00 UTC (3:00 AM Pacific) every day
echo "0 10 * * * /home/ubuntu/email-campaign/email_campaign/nightly/runner.sh >> /home/ubuntu/nightly.log 2>&1" >> /tmp/crontab_clean
crontab /tmp/crontab_clean
rm /tmp/crontab_clean

echo "Cron job installed:"
crontab -l
REMOTE

echo "=== Step 6: Make runner executable ==="
$SSH "chmod +x ~/email-campaign/email_campaign/nightly/runner.sh"

echo ""
echo "=== Setup complete! ==="
echo "The nightly runner will execute at 3:00 AM Pacific (10:00 UTC) daily."
echo "Logs: ssh -i $KEY $SERVER 'tail -f ~/nightly.log'"
echo ""
echo "To test manually:"
echo "  ssh -i $KEY $SERVER 'cd ~/email-campaign && bash email_campaign/nightly/runner.sh'"
