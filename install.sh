#!/bin/bash

# Install script for LND Channel Guard

echo "Installing LND Channel Guard..."

# Copy script to /usr/local/bin
sudo cp channel_guard.py /usr/local/bin/channel_guard.py
sudo chmod +x /usr/local/bin/channel_guard.py

# Copy systemd service file
sudo cp channel_guard.service /etc/systemd/system/channel_guard.service

# Reload systemd
sudo systemctl daemon-reload

echo "Installation complete!"
echo "Edit /etc/systemd/system/channel_guard.service to set your ExecStart parameters."
echo "Then run: sudo systemctl enable --now channel_guard.service"
