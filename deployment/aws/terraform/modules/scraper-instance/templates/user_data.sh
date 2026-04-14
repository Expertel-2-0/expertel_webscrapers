#!/bin/bash
# =============================================================================
# ExpertelIQ2 Webscrapers - EC2 User Data Script
# =============================================================================
# Sets up Ubuntu 22.04 with:
# - XFCE desktop environment
# - noVNC for remote browser access
# - Python 3.11 + Poetry + Playwright
# - Systemd timers for scheduled execution (every 30 min with flock mutex)
# =============================================================================

set -e

# Logging setup
exec > >(tee /var/log/user-data.log | logger -t user-data -s 2>/dev/console) 2>&1
echo "=============================================="
echo "Starting ExpertelIQ2 Scraper deployment"
echo "Date: $(date)"
echo "=============================================="

# Configuration from Terraform
ENVIRONMENT="${environment}"
APP_NAME="${app_name}"
AWS_REGION="${aws_region}"
GITHUB_REPO_URL="${github_repo_url}"
GITHUB_BRANCH="${github_branch}"
SNS_TOPIC_ARN="${sns_topic_arn}"
SCREEN_RESOLUTION="${screen_resolution}"
TIMEZONE="${timezone}"

echo "Environment: $ENVIRONMENT"
echo "App Name: $APP_NAME"
echo "AWS Region: $AWS_REGION"
echo "GitHub Repo: $GITHUB_REPO_URL"
echo "Branch: $GITHUB_BRANCH"
echo "Timezone: $TIMEZONE"
echo "Screen Resolution: $SCREEN_RESOLUTION"

# =============================================================================
# SYSTEM UPDATE & BASE PACKAGES
# =============================================================================

echo "Updating system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y

echo "Installing base packages..."
apt-get install -y \
    curl \
    wget \
    git \
    unzip \
    jq \
    htop \
    vim \
    net-tools \
    software-properties-common \
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsb-release

# =============================================================================
# SET TIMEZONE
# =============================================================================

echo "Setting timezone to $TIMEZONE..."
timedatectl set-timezone $TIMEZONE

# =============================================================================
# INSTALL AWS CLI v2
# =============================================================================

echo "Installing AWS CLI v2..."
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip -q awscliv2.zip
./aws/install
rm -rf aws awscliv2.zip

export AWS_DEFAULT_REGION=$AWS_REGION

# =============================================================================
# INSTALL XFCE DESKTOP + VNC
# =============================================================================

echo "Installing XFCE desktop environment..."
apt-get install -y \
    xfce4 \
    xfce4-goodies \
    xfonts-base \
    xfonts-100dpi \
    xfonts-75dpi \
    dbus-x11

echo "Installing VNC and noVNC..."
apt-get install -y \
    tigervnc-standalone-server \
    tigervnc-common \
    novnc \
    websockify

# =============================================================================
# INSTALL NGINX FOR SSL TERMINATION
# =============================================================================

echo "Installing Nginx..."
apt-get install -y nginx apache2-utils

# =============================================================================
# INSTALL PYENV + PYTHON 3.11 (without modifying system Python)
# =============================================================================

echo "Installing pyenv dependencies..."
apt-get install -y \
    make \
    build-essential \
    libssl-dev \
    zlib1g-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    llvm \
    libncursesw5-dev \
    xz-utils \
    tk-dev \
    libxml2-dev \
    libxmlsec1-dev \
    libffi-dev \
    liblzma-dev \
    libpq-dev

# Install pyenv for scraper user (will be created later, install globally first)
echo "Installing pyenv..."
export PYENV_ROOT="/opt/pyenv"
curl https://pyenv.run | bash

# Add pyenv to system profile for all users
cat > /etc/profile.d/pyenv.sh << 'PYENV_PROFILE'
export PYENV_ROOT="/opt/pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
PYENV_PROFILE

# Load pyenv for current script
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$($PYENV_ROOT/bin/pyenv init -)"

# Install Python 3.11 via pyenv
echo "Installing Python 3.11 via pyenv..."
$PYENV_ROOT/bin/pyenv install 3.11.9
$PYENV_ROOT/bin/pyenv global 3.11.9

# Verify Python version
echo "Python version: $($PYENV_ROOT/shims/python --version)"

# Install Poetry using pyenv's Python
echo "Installing Poetry..."
curl -sSL https://install.python-poetry.org | $PYENV_ROOT/shims/python3 -

# Poetry is installed to /root/.local/bin
export PATH="/root/.local/bin:$PATH"

# =============================================================================
# INSTALL GOOGLE CHROME
# =============================================================================

echo "Installing Google Chrome..."
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome-keyring.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list
apt-get update -y
apt-get install -y google-chrome-stable

# =============================================================================
# CREATE APPLICATION USER
# =============================================================================

echo "Creating application user..."
useradd -m -s /bin/bash scraper
usermod -aG sudo scraper

# Setup .bashrc for scraper user with pyenv
cat >> /home/scraper/.bashrc << 'EOF'
export PYENV_ROOT="/opt/pyenv"
export PATH="$PYENV_ROOT/bin:$HOME/.local/bin:$PATH"
eval "$(pyenv init -)"
export DISPLAY=:99
EOF

# =============================================================================
# CLONE APPLICATION
# =============================================================================

echo "Cloning application repository..."
APP_DIR="/opt/$APP_NAME"
mkdir -p $APP_DIR
cd $APP_DIR

git clone --branch $GITHUB_BRANCH $GITHUB_REPO_URL .
chown -R scraper:scraper $APP_DIR

# =============================================================================
# INSTALL POETRY FOR SCRAPER USER
# =============================================================================

echo "Installing Poetry for scraper user..."
# Set pyenv permissions so scraper can use it
chmod -R 755 /opt/pyenv
# Allow scraper to write to shims directory (needed for pyenv rehash)
chown -R scraper:scraper /opt/pyenv/shims

# Install Poetry for scraper user using pyenv's Python
sudo -u scraper bash -c 'export PYENV_ROOT="/opt/pyenv" && export PATH="$PYENV_ROOT/bin:$PATH" && eval "$(pyenv init -)" && curl -sSL https://install.python-poetry.org | python3 -'

# =============================================================================
# INSTALL PYTHON DEPENDENCIES
# =============================================================================

echo "Installing Python dependencies..."
cd $APP_DIR

# Configure and install dependencies as scraper user with pyenv
sudo -u scraper bash -c 'export PYENV_ROOT="/opt/pyenv" && export PATH="$PYENV_ROOT/bin:$HOME/.local/bin:$PATH" && eval "$(pyenv init -)" && cd /opt/'"$APP_NAME"' && poetry config virtualenvs.in-project true && poetry install --no-root'

# Install Playwright browsers
echo "Installing Playwright browsers..."
sudo -u scraper bash -c 'export PYENV_ROOT="/opt/pyenv" && export PATH="$PYENV_ROOT/bin:$HOME/.local/bin:$PATH" && eval "$(pyenv init -)" && cd /opt/'"$APP_NAME"' && poetry run playwright install chromium'

# Install Playwright system dependencies (needs root, use virtualenv python)
DEBIAN_FRONTEND=noninteractive $APP_DIR/.venv/bin/python -m playwright install-deps

# =============================================================================
# FETCH SECRETS FROM SSM
# =============================================================================

echo "Fetching configuration from SSM..."

get_ssm_parameter() {
    local param_name=$1
    aws ssm get-parameter \
        --name "$param_name" \
        --with-decryption \
        --query 'Parameter.Value' \
        --output text 2>/dev/null || echo ""
}

# Fetch all required parameters
DB_HOST=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/database/host")
DB_NAME=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/database/name")
DB_PORT=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/database/port")
DB_USERNAME=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/database/username")
DB_PASSWORD=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/database/password")
BACKEND_API_URL=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/backend-api/url")
BACKEND_API_KEY=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/backend-api/key")
CRYPTOGRAPHY_KEY=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/cryptography/key")
AZURE_CLIENT_ID=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/azure/client-id")
AZURE_TENANT_ID=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/azure/tenant-id")
AZURE_CLIENT_SECRET=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/azure/client-secret")
AZURE_USER_EMAIL=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/azure/user-email")
ANTHROPIC_API_KEY=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/anthropic/api-key")
GEMINI_API_KEY=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/gemini/api-key")
MFA_SERVICE_URL=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/mfa-service/url")
NOVNC_PASSWORD=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/novnc/password")

# Email configuration
EMAIL_HOST=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/email/host")
EMAIL_PORT=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/email/port")
EMAIL_HOST_USER=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/email/host-user")
EMAIL_HOST_PASSWORD=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/email/host-password")
EMAIL_USE_TLS=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/email/use-tls")
EMAIL_FROM_ADDRESS=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/email/from-address")
SCRAPER_ALERT_EMAILS=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/email/alert-recipients")
FRONTEND_URL=$(get_ssm_parameter "/$APP_NAME/$ENVIRONMENT/config/frontend-url")

# Set scraper user password (same as noVNC for convenience)
echo "scraper:$NOVNC_PASSWORD" | chpasswd
echo "Scraper user password set"

# Create .env file
echo "Creating environment configuration..."
cat > $APP_DIR/.env << EOF
# ExpertelIQ2 Scraper - Generated $(date)
# Environment: $ENVIRONMENT

# Database
DB_HOST=$DB_HOST
DB_NAME=$DB_NAME
DB_PORT=$DB_PORT
DB_USERNAME=$DB_USERNAME
DB_PASSWORD=$DB_PASSWORD

# Backend API
EIQ_BACKEND_API_BASE_URL=$BACKEND_API_URL
EIQ_BACKEND_API_KEY=$BACKEND_API_KEY

# Cryptography
CRYPTOGRAPHY_KEY=$CRYPTOGRAPHY_KEY

# Azure (for email notifications)
CLIENT_ID=$AZURE_CLIENT_ID
TENANT_ID=$AZURE_TENANT_ID
CLIENT_SECRET=$AZURE_CLIENT_SECRET
USER_EMAIL=$AZURE_USER_EMAIL

# Anthropic
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY

# Gemini
GEMINI_API_KEY=$GEMINI_API_KEY

# MFA Service
MFA_SERVICE_URL=$MFA_SERVICE_URL

# Email
EMAIL_HOST=$EMAIL_HOST
EMAIL_PORT=$EMAIL_PORT
EMAIL_HOST_USER=$EMAIL_HOST_USER
EMAIL_HOST_PASSWORD=$EMAIL_HOST_PASSWORD
EMAIL_USE_TLS=$EMAIL_USE_TLS
EMAIL_FROM_ADDRESS=$EMAIL_FROM_ADDRESS
SCRAPER_ALERT_EMAILS=$SCRAPER_ALERT_EMAILS
FRONTEND_URL=$FRONTEND_URL

# Environment
ENVIRONMENT=$ENVIRONMENT
SNS_TOPIC_ARN=$SNS_TOPIC_ARN
EOF

chown scraper:scraper $APP_DIR/.env
chmod 600 $APP_DIR/.env

# =============================================================================
# CONFIGURE VNC
# =============================================================================

echo "Configuring VNC..."
mkdir -p /home/scraper/.vnc

# Set VNC password
echo "$NOVNC_PASSWORD" | vncpasswd -f > /home/scraper/.vnc/passwd
chmod 600 /home/scraper/.vnc/passwd

# VNC startup script
cat > /home/scraper/.vnc/xstartup << 'EOF'
#!/bin/bash
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
export XKL_XMODMAP_DISABLE=1
# Disable screen locker
xset s off
xset -dpms
xset s noblank
exec startxfce4
EOF
chmod +x /home/scraper/.vnc/xstartup

chown -R scraper:scraper /home/scraper/.vnc

# Disable XFCE screen locker and power management
mkdir -p /home/scraper/.config/xfce4/xfconf/xfce-perchannel-xml
cat > /home/scraper/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-screensaver.xml << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-screensaver" version="1.0">
  <property name="saver" type="empty">
    <property name="enabled" type="bool" value="false"/>
  </property>
  <property name="lock" type="empty">
    <property name="enabled" type="bool" value="false"/>
  </property>
</channel>
EOF

cat > /home/scraper/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-power-manager.xml << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-power-manager" version="1.0">
  <property name="xfce4-power-manager" type="empty">
    <property name="dpms-enabled" type="bool" value="false"/>
    <property name="lock-screen-suspend-hibernate" type="bool" value="false"/>
  </property>
</channel>
EOF

chown -R scraper:scraper /home/scraper/.config

# =============================================================================
# CONFIGURE NGINX FOR NOVNC
# =============================================================================

echo "Configuring Nginx..."

# Create htpasswd for basic auth
htpasswd -cb /etc/nginx/.htpasswd scraper "$NOVNC_PASSWORD"

# Nginx configuration
cat > /etc/nginx/sites-available/novnc << 'EOF'
server {
    listen 80;
    server_name _;

    # Redirect to HTTPS
    location / {
        return 301 https://$host$request_uri;
    }

    # ACME challenge for Let's Encrypt
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
}

server {
    listen 443 ssl;
    server_name _;

    # Self-signed cert initially (replace with Let's Encrypt later)
    ssl_certificate /etc/nginx/ssl/nginx.crt;
    ssl_certificate_key /etc/nginx/ssl/nginx.key;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Basic authentication
    auth_basic "Scraper Access";
    auth_basic_user_file /etc/nginx/.htpasswd;

    # noVNC static files
    location /vnc/ {
        alias /usr/share/novnc/;
        index vnc.html;
        try_files $uri $uri/ /vnc/vnc.html;
    }

    # WebSocket proxy to VNC
    location /websockify {
        proxy_pass http://127.0.0.1:6080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }
}
EOF

# Create self-signed certificate (temporary)
mkdir -p /etc/nginx/ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/nginx/ssl/nginx.key \
    -out /etc/nginx/ssl/nginx.crt \
    -subj "/C=US/ST=State/L=City/O=Expertel/CN=scraper-$ENVIRONMENT.expertel.com"

# Enable site
ln -sf /etc/nginx/sites-available/novnc /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

nginx -t && systemctl restart nginx

# =============================================================================
# CREATE SYSTEMD SERVICES
# =============================================================================

echo "Creating systemd services..."

# VNC Service
cat > /etc/systemd/system/vncserver.service << EOF
[Unit]
Description=TigerVNC Server
After=network.target

[Service]
Type=simple
User=scraper
Group=scraper
WorkingDirectory=/home/scraper
Environment=DISPLAY=:99
ExecStartPre=/bin/sh -c 'rm -f /tmp/.X99-lock /tmp/.X11-unix/X99'
ExecStart=/usr/bin/vncserver :99 -geometry $SCREEN_RESOLUTION -depth 24 -fg
ExecStop=/usr/bin/vncserver -kill :99
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Websockify Service (noVNC bridge)
cat > /etc/systemd/system/websockify.service << EOF
[Unit]
Description=Websockify for noVNC
After=vncserver.service
Requires=vncserver.service

[Service]
Type=simple
User=scraper
ExecStart=/usr/bin/websockify --web=/usr/share/novnc 6080 localhost:5999
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Scraper Service (with flock to prevent concurrent executions)
cat > /etc/systemd/system/scraper.service << EOF
[Unit]
Description=ExpertelIQ2 Webscraper
After=network.target vncserver.service
Wants=vncserver.service

[Service]
Type=oneshot
User=scraper
Group=scraper
WorkingDirectory=$APP_DIR
Environment=DISPLAY=:99
Environment=HOME=/home/scraper
Environment=PYENV_ROOT=/opt/pyenv
Environment=PATH=/opt/pyenv/shims:/opt/pyenv/bin:/home/scraper/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# Use flock to prevent concurrent executions (-n = non-blocking, exits immediately if lock is held)
ExecStart=/usr/bin/flock -n /var/lock/scraper.lock /home/scraper/.local/bin/poetry run python main.py
StandardOutput=append:/var/log/scraper/scraper.log
StandardError=append:/var/log/scraper/scraper.log

# Notify on failure (exit code 1 = flock couldn't acquire lock, which is expected - don't notify)
ExecStopPost=/bin/bash -c 'if [ "\$EXIT_STATUS" != "0" ] && [ "\$EXIT_STATUS" != "1" ]; then aws sns publish --topic-arn "$SNS_TOPIC_ARN" --message "Scraper failed with exit code \$EXIT_STATUS" --subject "Scraper Error - $ENVIRONMENT" --region $AWS_REGION; fi'
EOF

# Scraper Timer (every 30 minutes)
cat > /etc/systemd/system/scraper.timer << EOF
[Unit]
Description=Run scraper every 30 minutes (with flock mutex to prevent overlapping)

[Timer]
# Run every 30 minutes (at :00 and :30 of each hour)
OnCalendar=*:00,30
# Randomize start by up to 60 seconds to avoid thundering herd
RandomizedDelaySec=60
Persistent=true
Unit=scraper.service

[Install]
WantedBy=timers.target
EOF

# MFA Service (runs permanently on port 7000)
cat > /etc/systemd/system/mfa.service << EOF
[Unit]
Description=ExpertelIQ2 MFA Authentication Service
After=network.target

[Service]
Type=simple
User=scraper
Group=scraper
WorkingDirectory=$APP_DIR
Environment=PYENV_ROOT=/opt/pyenv
Environment=PATH=/opt/pyenv/shims:/opt/pyenv/bin:/home/scraper/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
EnvironmentFile=$APP_DIR/.env
ExecStart=/home/scraper/.local/bin/poetry run uvicorn mfa.main:app --host 127.0.0.1 --port 7000
Restart=always
RestartSec=5
StandardOutput=append:/var/log/scraper/mfa.log
StandardError=append:/var/log/scraper/mfa.log

[Install]
WantedBy=multi-user.target
EOF

# Create log directory
mkdir -p /var/log/scraper
chown scraper:scraper /var/log/scraper

# Create lock file for flock with correct permissions
touch /var/lock/scraper.lock
chown scraper:scraper /var/lock/scraper.lock

# Reload and enable services
systemctl daemon-reload
systemctl enable vncserver
systemctl enable websockify
systemctl enable scraper.timer
systemctl enable mfa
systemctl enable nginx

# Start services
systemctl start vncserver
sleep 5
systemctl start websockify
systemctl start mfa
systemctl start scraper.timer
systemctl start nginx

# =============================================================================
# INSTALL CLOUDWATCH AGENT
# =============================================================================

echo "Installing CloudWatch agent..."
wget https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
dpkg -i amazon-cloudwatch-agent.deb
rm amazon-cloudwatch-agent.deb

# CloudWatch agent configuration
cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json << EOF
{
    "agent": {
        "metrics_collection_interval": 60,
        "run_as_user": "root"
    },
    "logs": {
        "logs_collected": {
            "files": {
                "collect_list": [
                    {
                        "file_path": "/var/log/scraper/scraper.log",
                        "log_group_name": "/experteliq2/scraper/$ENVIRONMENT",
                        "log_stream_name": "{instance_id}/scraper",
                        "timezone": "Local"
                    },
                    {
                        "file_path": "/var/log/scraper/mfa.log",
                        "log_group_name": "/experteliq2/scraper/$ENVIRONMENT",
                        "log_stream_name": "{instance_id}/mfa",
                        "timezone": "Local"
                    },
                    {
                        "file_path": "/var/log/user-data.log",
                        "log_group_name": "/experteliq2/scraper/$ENVIRONMENT",
                        "log_stream_name": "{instance_id}/user-data",
                        "timezone": "Local"
                    }
                ]
            }
        }
    },
    "metrics": {
        "namespace": "ExpertelIQ2/Scraper",
        "metrics_collected": {
            "cpu": {
                "measurement": ["cpu_usage_active"],
                "metrics_collection_interval": 60
            },
            "mem": {
                "measurement": ["mem_used_percent"],
                "metrics_collection_interval": 60
            },
            "disk": {
                "measurement": ["disk_used_percent"],
                "metrics_collection_interval": 60,
                "resources": ["/"]
            }
        }
    }
}
EOF

systemctl enable amazon-cloudwatch-agent
systemctl start amazon-cloudwatch-agent

# =============================================================================
# FINAL SETUP
# =============================================================================

echo "=============================================="
echo "Deployment completed!"
echo "Date: $(date)"
echo "=============================================="
echo ""
echo "Access noVNC at: https://<public-ip>/vnc/"
echo "Username: scraper"
echo "Password: (stored in SSM)"
echo ""
echo "Services:"
echo "  - MFA Service: Running on port 7000 (internal only)"
echo "  - Scraper: Runs every 30 minutes (with flock mutex)"
echo ""
echo "Commands:"
echo "  systemctl status mfa           - Check MFA service"
echo "  systemctl status scraper.timer - Check scraper timer"
echo "  systemctl list-timers          - List all timers"
echo "  journalctl -u mfa -f           - View MFA logs"
echo "  journalctl -u scraper -f       - View scraper logs"
echo "  flock -n /var/lock/scraper.lock echo 'Lock free' - Check if scraper is running"
echo "=============================================="

# Send deployment notification
aws sns publish \
    --topic-arn "$SNS_TOPIC_ARN" \
    --message "Scraper instance deployed successfully in $ENVIRONMENT environment" \
    --subject "Scraper Deployed - $ENVIRONMENT" \
    --region $AWS_REGION || true
