# LND Channel Guard

A simple Python script to monitor a specific Lightning Network channel on your MiniBolt node and automatically apply a high "blocker" fee rate (default: 17000 ppm) if the outbound liquidity falls below a threshold (default: 40%). This helps preserve remaining outbound liquidity by discouraging routing through the channel.

Inspired by [charge-lnd](https://github.com/accumulator/charge-lnd), but standalone and focused on a single channel with frequent polling (default: 1 second).

## Features
- Polls channel state every 1 second (configurable).
- Checks outbound liquidity (local_balance / capacity) using `lncli listchannels`.
- Fetches current fee policies using `lncli getchaninfo` and applies update only if needed (avoids redundant gossip).
- Runs as a systemd service for daemon-like operation.
- Supports channel ID as compact numeric SCID (e.g., 992028868678647809) or human-readable SCID (e.g., 902245x1158x1)—automatically converts if needed.
- Logs sparingly to avoid spam: Actions/changes immediately; status every 60 seconds otherwise.
- No external dependencies beyond Python 3 and `lncli` (included in LND).

## Prerequisites
- A running MiniBolt node with LND.
- Python 3 (usually pre-installed; if not, `sudo apt install python3`).
- The script must run as a user with access to `lncli` (e.g., `lnd` user).

## Installation
1. Clone this repo:
git clone https://github.com/Benny-444/channel_guard.git
cd channel_guard

2. Run the installer:
./install.sh
This copies the script to `/usr/local/bin/channel_guard.py` and sets up the systemd service template.

3. Configure the systemd service:
- Edit `/etc/systemd/system/channel_guard.service` to set your `ExecStart` line with the desired channel ID and options (e.g., `ExecStart=/usr/local/bin/channel_guard.py 902245x1158x1 --threshold 0.4 --blocker_ppm 17000` or using the numeric SCID).
- Reload systemd: `sudo systemctl daemon-reload`.
- Enable and start: `sudo systemctl enable --now channel_guard.service`.

## Usage
Run manually for testing:
channel_guard.py <chan_id> [--threshold 0.4] [--blocker_ppm 17000] [--poll_interval 1]

`<chan_id>` can be the compact numeric SCID (e.g., 992028868678647809) or human-readable SCID (e.g., 902245x1158x1). The script will convert the latter to the numeric format required by `lncli`.

As a service, it runs continuously in the background.

## Logs
- Check status: `sudo systemctl status channel_guard.service`
- View logs: `sudo journalctl -u channel_guard.service`

## Notes
- This script only applies the blocker fee when liquidity falls below the threshold; it does not automatically reset to a lower fee if liquidity recovers (to preserve the "block" as per the goal). If you need reversibility, you can stop the service and manually update the policy via `lncli`.
- Polling every 1 second is lightweight but ensure it doesn't overload your node.
- Fee updates use `lncli updatechanpolicy`, which gossips changes to the network (no on-chain cost, but avoid excessive updates).

## License
MIT License
