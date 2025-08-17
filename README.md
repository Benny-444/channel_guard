# LND Channel Guard

A Python script that monitors Lightning Network channels on your LND node and automatically protects outbound liquidity through intelligent fee management and dynamic HTLC limits. Channel Guard uses two independent protection mechanisms that work together to preserve your ability to route payments.

## How It Works

Channel Guard operates with **two independent protection layers** that work simultaneously:

### 1. Fee Protection (Hysteresis-Based)
Uses a hysteresis system to prevent fee "flapping" and provides aggressive protection when liquidity is critically low:

- **Normal Operation (>40% outbound liquidity)**: Your original fees remain active
- **Hysteresis Zone (30-40% outbound liquidity)**: Maintains current fee state without changes to prevent oscillation
- **Protection Mode (<30% outbound liquidity)**: Applies high "blocker" fee (default: 17,000 ppm) to discourage routing
- **Recovery (>40% outbound liquidity)**: Automatically restores your original fee when liquidity recovers

The system remembers your exact original fee rate before applying protection and restores it precisely when protection is no longer needed.

### 2. HTLC Maximum Protection (Continuous)
Dynamically adjusts the maximum HTLC size every 2 seconds to preserve a liquidity floor:

- **Continuous Monitoring**: Updates `max_htlc_msat` whenever liquidity ratio changes by ≥1% (configurable)
- **Liquidity Floor**: Preserves 35% of channel capacity as unreachable outbound liquidity (configurable)
- **Formula**: `HTLC Max = max(1, local_balance - (capacity × liquidity_floor))`
- **Bidirectional**: Adjusts both up (when receiving) and down (when routing out)
- **Independence**: Works regardless of fee protection state

When liquidity is critically low, HTLC max can drop to 1 satoshi, effectively making the channel "routing-dead" while preserving the liquidity floor.

## Key Features

### Smart State Management
- **Persistent State**: Remembers original fees and protection status across restarts
- **Per-Channel Isolation**: Multiple instances can monitor different channels independently
- **Graceful Recovery**: Handles crashes and restarts without losing configuration

### Intelligent Logging
- **Change-Based**: Immediate logging when protection state changes or HTLC limits update
- **Periodic Status**: Status updates every 60 seconds during normal operation
- **Dual Output**: Console output for real-time monitoring, file logging for history
- **Error Tracking**: Detailed error logging with automatic retry and backoff

### Flexible Configuration
- **Channel ID Formats**: Supports both numeric (992028868678647809) and human-readable (902245x1158x1) formats
- **Threshold Customization**: Adjustable protection and recovery thresholds
- **Fee Configuration**: Customizable blocker fee rates
- **Update Sensitivity**: Configurable HTLC change threshold to control update frequency

## Prerequisites

- **Running LND Node**: LND must be operational and accessible
- **Python 3**: Usually pre-installed on most systems
- **User Access**: User must be able to execute `lncli` commands (typically `admin` user in `lnd` group)

## Installation

1. **Clone the repository**:
```bash
git clone https://github.com/your-repo/channel_guard.git
cd channel_guard
```

2. **Run the installer** (as the user who will run the service, typically `admin`):
```bash
chmod +x install.sh
./install.sh
```

The installer:
- Creates `~/channel_guard/` directory
- Copies all files and makes the script executable
- Creates state directory `~/channel_guard/.state/`
- Installs systemd service to `/etc/systemd/system/channel_guard.service`
- Configures proper paths and permissions

3. **Configure the service**:
```bash
sudo nano /etc/systemd/system/channel_guard.service
```

Update the `ExecStart` line with your channel ID and desired parameters. Verify `User=admin` and `Group=admin` match your setup.

4. **Enable and start**:
```bash
sudo systemctl enable channel_guard.service
sudo systemctl start channel_guard.service
```

## Configuration Options

### Command Line Arguments
```bash
channel_guard.py <chan_id> [options]

Required:
  chan_id                    Channel ID in numeric (992028868678647809) or 
                            human-readable (902245x1158x1) format

Optional:
  --lower_threshold FLOAT    Apply blocker below this ratio (default: 0.3 = 30%)
  --upper_threshold FLOAT    Remove blocker above this ratio (default: 0.4 = 40%)
  --liquidity_floor FLOAT    HTLC max preserves this ratio (default: 0.35 = 35%)
  --blocker_ppm INT         Blocker fee rate in ppm (default: 17000)
  --poll_interval INT       Polling interval in seconds (default: 2)
  --htlc_change_threshold FLOAT  Min ratio change for HTLC updates (default: 0.01 = 1%)
```

### Configuration Examples

**Basic Protection** (recommended for most users):
```bash
ExecStart=/home/admin/channel_guard/channel_guard.py 902245x1158x1
```
- Applies blocker fee at 30% liquidity
- Removes blocker at 40% liquidity  
- Preserves 35% liquidity floor via HTLC limits
- Updates HTLC when liquidity changes by 1%

**Aggressive Protection** (for critical channels):
```bash
ExecStart=/home/admin/channel_guard/channel_guard.py 902245x1158x1 --lower_threshold 0.25 --upper_threshold 0.45 --blocker_ppm 25000 --liquidity_floor 0.40
```
- Earlier protection (25% trigger)
- Higher blocker fee (25,000 ppm)
- Larger hysteresis gap (20%)
- Higher liquidity floor (40%)

**Conservative Protection** (for stable channels):
```bash
ExecStart=/home/admin/channel_guard/channel_guard.py 902245x1158x1 --lower_threshold 0.35 --liquidity_floor 0.30 --htlc_change_threshold 0.05
```
- Later protection (35% trigger)
- Lower liquidity floor (30%)
- Less frequent HTLC updates (5% change threshold)

**High-Frequency Trading Channel**:
```bash
ExecStart=/home/admin/channel_guard/channel_guard.py 902245x1158x1 --poll_interval 1 --htlc_change_threshold 0.005 --liquidity_floor 0.45
```
- Faster polling (1 second)
- More sensitive HTLC updates (0.5% change)
- Higher liquidity preservation (45%)

### Multiple Channels

To monitor multiple channels, create separate service files:

1. **Copy the service file**:
```bash
sudo cp /etc/systemd/system/channel_guard.service /etc/systemd/system/channel_guard_chan1.service
sudo cp /etc/systemd/system/channel_guard.service /etc/systemd/system/channel_guard_chan2.service
```

2. **Edit each service file** with different channel IDs:
```bash
# channel_guard_chan1.service
ExecStart=/home/admin/channel_guard/channel_guard.py 902245x1158x1 --blocker_ppm 20000

# channel_guard_chan2.service  
ExecStart=/home/admin/channel_guard/channel_guard.py 993290x1842x0 --lower_threshold 0.25
```

3. **Enable and start each service**:
```bash
sudo systemctl enable channel_guard_chan1.service channel_guard_chan2.service
sudo systemctl start channel_guard_chan1.service channel_guard_chan2.service
```

Each instance operates independently but shares the same state file (channel IDs are isolated within `channel_state.json`).

## Monitoring

### Service Status
```bash
# Check service status
sudo systemctl status channel_guard.service

# View live logs
sudo journalctl -u channel_guard.service -f

# View recent logs
sudo journalctl -u channel_guard.service -n 50
```

### Log Files
```bash
# Application logs
tail -f ~/channel_guard/logs/channel_guard.log

# State inspection
cat ~/channel_guard/.state/channel_state.json
```

### Common Log Messages

**Normal Operation**:
```
Outbound liquidity 45.30% - Normal - Fee: 1000 ppm, HTLC max: 2,500,000 sats
```

**Protection Activated**:
```
Outbound liquidity 28.45% < 30% - Applied blocker fee 17000 ppm (was 1000 ppm), HTLC max: 1,950,000 sats
```

**Protection Removed**:
```
Outbound liquidity 42.15% > 40% - Removed blocker fee, restored 1000 ppm, HTLC max: 2,100,000 sats
```

**HTLC Update**:
```
Updated HTLC max from 2,100,000 to 1,850,000 sats (liquidity: 37.20%, reason: ratio changed 1.15%)
```

## Advanced Usage

### State File Structure
The state file (`~/channel_guard/.state/channel_state.json`) stores:

```json
{
  "992028868678647809": {
    "blocker_active": false,
    "original_fee_ppm": 1000,
    "last_htlc_ratio": 0.4523
  }
}
```

- `blocker_active`: Whether protection fee is currently applied
- `original_fee_ppm`: Fee rate before protection (for restoration)
- `last_htlc_ratio`: Last liquidity ratio when HTLC was updated

### Manual State Reset
If needed, you can reset state by stopping the service and deleting the state file:

```bash
sudo systemctl stop channel_guard.service
rm ~/channel_guard/.state/channel_state.json
sudo systemctl start channel_guard.service
```

## Important Notes

### Fee Policy Preservation
- The script preserves **all** existing policy parameters (base fee, time lock delta, min HTLC)
- Only `fee_rate_ppm` and `max_htlc_msat` are modified
- Original fee rates are stored precisely and restored exactly

### Performance Impact
- Minimal CPU usage (simple JSON parsing every 2 seconds)
- No impact on LND performance
- Network calls only for channel state queries and policy updates

## License

MIT License - see LICENSE file for details.