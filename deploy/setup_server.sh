#!/bin/bash
# ==============================================================
# NGO SMS Loan System — DigitalOcean Server Setup Script
# ==============================================================
# Run this script on a fresh Ubuntu 24.04 Droplet as root.
#
# Usage:
#   ssh root@YOUR_DROPLET_IP
#   nano setup_server.sh    (paste this script)
#   chmod +x setup_server.sh
#   ./setup_server.sh
# ==============================================================

set -e  # Stop on any error

echo "========================================"
echo "  NGO Loan System — Server Setup"
echo "========================================"

# -------------------------------------------------
# STEP 1: Create a non-root user called 'deploy'
# -------------------------------------------------
echo ""
echo ">>> Step 1: Creating 'deploy' user..."
if id "deploy" &>/dev/null; then
    echo "    User 'deploy' already exists, skipping."
else
    adduser --gecos "" deploy
    usermod -aG sudo deploy
    echo "    ✅ User 'deploy' created with sudo access."
fi

# -------------------------------------------------
# STEP 2: Update system and install packages
# -------------------------------------------------
echo ""
echo ">>> Step 2: Updating system and installing packages..."
apt update && apt upgrade -y
apt install -y python3-pip python3-venv nginx mariadb-server git ufw curl

echo "    ✅ All packages installed."

# -------------------------------------------------
# STEP 3: Configure firewall
# -------------------------------------------------
echo ""
echo ">>> Step 3: Configuring firewall (UFW)..."
ufw allow OpenSSH
ufw allow 'Nginx Full'
echo "y" | ufw enable
echo "    ✅ Firewall enabled — SSH and Nginx allowed."

# -------------------------------------------------
# STEP 4: Secure MariaDB
# -------------------------------------------------
echo ""
echo ">>> Step 4: Securing MariaDB..."
echo "    Running mysql_secure_installation..."
echo "    Follow the prompts to set a root password and secure the database."
echo ""
mysql_secure_installation

# -------------------------------------------------
# STEP 5: Create database and user
# -------------------------------------------------
echo ""
echo ">>> Step 5: Creating database..."
echo "    Enter your MariaDB root password when prompted."
echo ""

read -sp "Choose a password for the ngo_user database account: " DB_PASSWORD
echo ""

mysql -u root -p <<EOF
CREATE DATABASE IF NOT EXISTS ngo_sms_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'ngo_user'@'localhost' IDENTIFIED BY '${DB_PASSWORD}';
GRANT ALL PRIVILEGES ON ngo_sms_db.* TO 'ngo_user'@'localhost';
FLUSH PRIVILEGES;
EOF

echo "    ✅ Database 'ngo_sms_db' and user 'ngo_user' created."

# -------------------------------------------------
# STEP 6: Clone the repo as 'deploy' user
# -------------------------------------------------
echo ""
echo ">>> Step 6: Cloning repository..."
su - deploy -c "
    cd /home/deploy
    if [ -d 'ngo-sms-loan-system' ]; then
        echo '    Repo already exists, pulling latest...'
        cd ngo-sms-loan-system && git pull
    else
        git clone https://github.com/markfranci/ngo-sms-loan-system.git
    fi
"
echo "    ✅ Repository cloned."

# -------------------------------------------------
# STEP 7: Set up Python virtual environment
# -------------------------------------------------
echo ""
echo ">>> Step 7: Setting up Python environment..."
su - deploy -c "
    cd /home/deploy/ngo-sms-loan-system
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    echo '    ✅ Python environment ready.'
"

# -------------------------------------------------
# STEP 8: Create .env file
# -------------------------------------------------
echo ""
echo ">>> Step 8: Creating .env configuration..."

# Generate a strong secret key
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

cat > /home/deploy/ngo-sms-loan-system/.env <<EOF
SECRET_KEY=${SECRET_KEY}
DB_USERNAME=ngo_user
DB_PASSWORD=${DB_PASSWORD}
DB_HOST=localhost
DB_NAME=ngo_sms_db
EOF

chown deploy:deploy /home/deploy/ngo-sms-loan-system/.env
chmod 600 /home/deploy/ngo-sms-loan-system/.env

echo "    ✅ .env file created (readable only by deploy user)."

# -------------------------------------------------
# STEP 9: Initialize database tables
# -------------------------------------------------
echo ""
echo ">>> Step 9: Initializing database tables..."
su - deploy -c "
    cd /home/deploy/ngo-sms-loan-system
    source venv/bin/activate
    python3 -c \"
from app import create_app, db
app = create_app()
with app.app_context():
    db.create_all()
    print('    ✅ Database tables created.')
\"
"

# -------------------------------------------------
# STEP 10: Create admin user
# -------------------------------------------------
echo ""
echo ">>> Step 10: Creating admin user..."
read -p "Admin username: " ADMIN_USERNAME
read -p "Admin email: " ADMIN_EMAIL
read -sp "Admin password: " ADMIN_PASSWORD
echo ""

su - deploy -c "
    cd /home/deploy/ngo-sms-loan-system
    source venv/bin/activate
    python3 -c \"
from app import create_app, db
from app.models.user import User
app = create_app()
with app.app_context():
    existing = User.query.filter_by(username='${ADMIN_USERNAME}').first()
    if existing:
        print('    Admin user already exists, skipping.')
    else:
        admin = User(username='${ADMIN_USERNAME}', email='${ADMIN_EMAIL}', role='admin')
        admin.set_password('${ADMIN_PASSWORD}')
        db.session.add(admin)
        db.session.commit()
        print('    ✅ Admin user created!')
\"
"

# -------------------------------------------------
# STEP 11: Configure Gunicorn systemd service
# -------------------------------------------------
echo ""
echo ">>> Step 11: Configuring Gunicorn service..."

cat > /etc/systemd/system/ngo-loan.service <<EOF
[Unit]
Description=NGO SMS Loan System (Gunicorn)
After=network.target mariadb.service

[Service]
User=deploy
Group=www-data
WorkingDirectory=/home/deploy/ngo-sms-loan-system
Environment="PATH=/home/deploy/ngo-sms-loan-system/venv/bin"
ExecStart=/home/deploy/ngo-sms-loan-system/venv/bin/gunicorn --workers 3 --bind unix:/home/deploy/ngo-sms-loan-system/ngo-loan.sock -m 007 wsgi:app

[Install]
WantedBy=multi-user.target
EOF

# Add deploy user to www-data group so Nginx can access the socket
usermod -aG www-data deploy

systemctl daemon-reload
systemctl start ngo-loan
systemctl enable ngo-loan

echo "    ✅ Gunicorn service started and enabled on boot."

# -------------------------------------------------
# STEP 12: Configure Nginx reverse proxy
# -------------------------------------------------
echo ""
echo ">>> Step 12: Configuring Nginx..."

# Get server IP
SERVER_IP=$(curl -s ifconfig.me)

cat > /etc/nginx/sites-available/ngo-loan <<EOF
server {
    listen 80;
    server_name ${SERVER_IP};

    location / {
        include proxy_params;
        proxy_pass http://unix:/home/deploy/ngo-sms-loan-system/ngo-loan.sock;
    }

    # Allow larger file uploads (for CSV exports etc.)
    client_max_body_size 10M;
}
EOF

# Remove default Nginx page
rm -f /etc/nginx/sites-enabled/default

# Enable our site
ln -sf /etc/nginx/sites-available/ngo-loan /etc/nginx/sites-enabled/

# Test and restart
nginx -t
systemctl restart nginx

echo "    ✅ Nginx configured and restarted."

# -------------------------------------------------
# DONE!
# -------------------------------------------------
echo ""
echo "========================================"
echo "  🎉 SETUP COMPLETE!"
echo "========================================"
echo ""
echo "  Your app is live at: http://${SERVER_IP}"
echo ""
echo "  Useful commands:"
echo "    sudo systemctl status ngo-loan    # Check app status"
echo "    sudo systemctl restart ngo-loan   # Restart app"
echo "    sudo journalctl -u ngo-loan       # View app logs"
echo "    sudo systemctl status nginx       # Check Nginx status"
echo ""
echo "  Next step: Set up Twilio WhatsApp webhook to:"
echo "    http://${SERVER_IP}/whatsapp/incoming"
echo ""
echo "========================================"
