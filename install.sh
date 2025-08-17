#!/bin/bash

# Install script for LND Channel Guard

INSTALL_DIR="$HOME/channel_guard"

echo "Installing LND Channel Guard to $INSTALL_DIR..."

# Create installation directory if it doesn't exist
if [ ! -d "$INSTALL_DIR" ]; then
    echo "Creating installation directory..."
    mkdir -p "$INSTALL_DIR"
fi

# Copy files to installation directory
echo "Copying files..."
cp channel_guard.py "$INSTALL_DIR/"
cp README.md "$INSTALL_DIR/"
cp channel_guard.service "$INSTALL_DIR/"

# Make script executable
chmod +x "$INSTALL_DIR/channel_guard.py"

# Create state directory
mkdir -p "$INSTALL_DIR/.state"

# Copy systemd service file with path substitution
echo "Installing systemd service..."
sed "s|/home/admin|$HOME|g" channel_guard.service | sudo tee /etc/systemd/system/channel_guard.service > /dev/null

# Reload systemd
sudo systemctl daemon-reload

echo ""
echo "Installation complete!"
echo ""
echo "Next steps:"
echo "1. Edit the service file to set your channel ID:"
echo "   sudo nano /etc/systemd/system/channel_guard.service"
echo "   Update the ExecStart line with your channel ID and any custom parameters"
echo ""
echo "2. Enable and start the service:"
echo "   sudo systemctl enable channel_guard.service"
echo "   sudo systemctl start channel_guard.service"
echo ""
echo "3. Check status:"
echo "   sudo systemctl status channel_guard.service"
echo "   sudo journalctl -u channel_guard.service -f"
echo ""
echo "Example ExecStart configurations:"
echo "  - Basic: ExecStart=$INSTALL_DIR/channel_guard.py 902245x1158x1"
echo "  - Custom: ExecStart=$INSTALL_DIR/channel_guard.py 902245x1158x1 --lower_threshold 0.25 --upper_threshold 0.45 --blocker_ppm 20000"
