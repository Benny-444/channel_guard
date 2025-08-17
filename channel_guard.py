#!/usr/bin/env python3

import subprocess
import json
import time
import argparse
import sys
import signal
from pathlib import Path
import logging

class ChannelGuard:
    def __init__(self, chan_id, lower_threshold, upper_threshold, liquidity_floor, blocker_ppm, poll_interval, htlc_change_threshold):
        self.chan_id = chan_id
        self.lower_threshold = lower_threshold
        self.upper_threshold = upper_threshold
        self.liquidity_floor = liquidity_floor
        self.blocker_ppm = blocker_ppm
        self.poll_interval = poll_interval
        self.htlc_change_threshold = htlc_change_threshold
        self.running = True

        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)

        # State management
        self.state_dir = Path.home() / "channel_guard" / ".state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.state_dir / "channel_state.json"
        self.state = self.load_state()

        # Parse chan_id to numeric format
        self.chan_id_numeric = self.parse_chan_id(chan_id)

        # Get our node's pubkey
        our_info = json.loads(self.run_lncli(['getinfo']))
        self.our_pubkey = our_info['identity_pubkey']

        # Logging setup
        log_dir = Path.home() / "channel_guard" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=log_dir / "channel_guard.log",
            level=logging.INFO,
            format='%(asctime)s %(levelname)s: %(message)s'
        )
        self.logger = logging.getLogger(__name__)

        # Logging control
        self.last_log_time = time.time()
        self.last_perc = None

    def signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        print(f"\nReceived signal {signum}, shutting down gracefully...")
        self.logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False

    def run_lncli(self, cmd_args):
        """Run lncli command and return output as string."""
        try:
            result = subprocess.check_output(['lncli'] + cmd_args, stderr=subprocess.PIPE)
            return result.decode('utf-8').strip()
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error running lncli {' '.join(cmd_args)}: {e}")
            if e.stderr:
                self.logger.error(f"Error details: {e.stderr.decode('utf-8')}")
            raise

    def parse_chan_id(self, chan_id):
        """Parse channel ID to compact numeric format."""
        if 'x' in chan_id:
            parts = chan_id.split('x')
            if len(parts) != 3:
                sys.exit("Invalid SCID format; use format like 902245x1158x1")
            try:
                block = int(parts[0])
                tx = int(parts[1])
                out = int(parts[2])
                return str((block << 40) | (tx << 16) | out)
            except ValueError:
                sys.exit("Invalid SCID parts; must be integers")
        else:
            try:
                int(chan_id)  # Validate it's numeric
                return chan_id
            except ValueError:
                sys.exit("Invalid chan_id; must be numeric SCID or 'x' format")

    def load_state(self):
        """Load persistent state from file."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Could not load state file: {e}. Starting fresh.", file=sys.stderr)
                return {}
        return {}

    def save_state(self):
        """Save persistent state to file."""
        # Ensure directory exists (in case it was deleted)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)

    def get_channel_state(self, chan_id):
        """Get or initialize channel state."""
        if chan_id not in self.state:
            self.state[chan_id] = {
                "blocker_active": False,
                "original_fee_ppm": None,
                "last_htlc_ratio": None
            }
        return self.state[chan_id]

    def get_channel_info(self):
        """Get channel details from listchannels and getchaninfo."""
        # Get channel from listchannels
        list_chans = json.loads(self.run_lncli(['listchannels']))

        # LND uses 'scid' (numeric) in listchannels output
        channel = None
        for ch in list_chans['channels']:
            if ch.get('scid', '') == self.chan_id_numeric:
                channel = ch
                break

        if not channel:
            raise ValueError(f"Channel {self.chan_id_numeric} not found in listchannels.")

        # Get channel policies from getchaninfo
        chan_info = json.loads(self.run_lncli(['getchaninfo', self.chan_id_numeric]))

        # Determine our policy
        if chan_info['node1_pub'] == self.our_pubkey:
            our_policy = chan_info['node1_policy']
        else:
            our_policy = chan_info['node2_policy']

        if not our_policy:
            raise ValueError(f"Could not find our policy for channel {self.chan_id_numeric}")

        return channel, our_policy

    def calculate_htlc_max(self, local_balance, capacity):
        """Calculate HTLC max to preserve liquidity floor."""
        floor_amount = int(capacity * self.liquidity_floor)
        available = local_balance - floor_amount
        # Minimum 1 sat, maximum is available liquidity above floor
        # But also cannot exceed local_balance (in case floor calculation goes negative)
        return max(1, min(available, local_balance))

    def update_channel_policy(self, chan_point, fee_rate_ppm, htlc_max, our_policy):
        """Update channel policy with fee rate and HTLC max, preserving other fields."""
        # Convert satoshis to millisatoshis for max_htlc_msat
        htlc_max_msat = htlc_max * 1000

        # Extract current policy values to preserve
        base_fee_msat = our_policy.get('fee_base_msat', '0')
        time_lock_delta = our_policy.get('time_lock_delta', '144')
        min_htlc_msat = our_policy.get('min_htlc_msat', '5000000')

        cmd = [
            'updatechanpolicy',
            '--chan_point', chan_point,
            '--base_fee_msat', str(base_fee_msat),
            '--fee_rate_ppm', str(fee_rate_ppm),
            '--min_htlc_msat', str(min_htlc_msat),
            '--max_htlc_msat', str(htlc_max_msat),
            '--time_lock_delta', str(time_lock_delta)
        ]

        try:
            self.run_lncli(cmd)
        except Exception as e:
            print(f"Warning: Failed to update channel policy: {e}", file=sys.stderr)
            self.logger.warning(f"Failed to update channel policy: {e}")
            raise

    def should_log(self, perc):
        """Determine if we should log based on time and state changes."""
        current_time = time.time()
        return (perc != self.last_perc) or (current_time - self.last_log_time >= 60)

    def run(self):
        """Main monitoring loop."""
        print(f"Monitoring channel {self.chan_id} (numeric: {self.chan_id_numeric})")
        print(f"Thresholds: Apply blocker at <{self.lower_threshold*100}%, Remove at >{self.upper_threshold*100}%")
        print(f"Liquidity floor: {self.liquidity_floor*100}%, Blocker fee: {self.blocker_ppm} ppm")
        print(f"HTLC change threshold: {self.htlc_change_threshold*100}%")
        self.logger.info(f"Monitoring channel {self.chan_id} (numeric: {self.chan_id_numeric})")
        self.logger.info(f"Thresholds: Apply blocker at <{self.lower_threshold*100}%, Remove at >{self.upper_threshold*100}%")
        self.logger.info(f"Liquidity floor: {self.liquidity_floor*100}%, Blocker fee: {self.blocker_ppm} ppm")
        self.logger.info(f"HTLC change threshold: {self.htlc_change_threshold*100}%")

        consecutive_errors = 0
        consecutive_not_found = 0
        max_consecutive_errors = 5
        max_not_found = 3

        while self.running:
            try:
                # Get channel information
                channel, our_policy = self.get_channel_info()
                consecutive_errors = 0  # Reset on success
                consecutive_not_found = 0  # Reset on success

                # Calculate liquidity percentage
                capacity = int(channel['capacity'])
                local_balance = int(channel['local_balance'])
                perc = local_balance / capacity if capacity > 0 else 0.0
                chan_point = channel['channel_point']

                # Get current fee and channel state
                current_ppm = int(our_policy['fee_rate_milli_msat'])
                # Handle max_htlc_msat - it might be missing or set to 0 (meaning no limit)
                max_htlc_msat = our_policy.get('max_htlc_msat', '0')
                if max_htlc_msat == '0' or not max_htlc_msat:
                    # No limit set, assume full capacity
                    current_htlc_max = capacity
                else:
                    current_htlc_max = int(max_htlc_msat) // 1000  # Convert to sats

                chan_state = self.get_channel_state(self.chan_id_numeric)

                # Calculate desired HTLC max
                desired_htlc_max = self.calculate_htlc_max(local_balance, capacity)

                # Determine if we should log
                log_now = self.should_log(perc)

                # Hysteresis logic for blocker fee
                if perc < self.lower_threshold and not chan_state["blocker_active"]:
                    # Apply blocker fee - store current fee first
                    chan_state["original_fee_ppm"] = current_ppm
                    chan_state["blocker_active"] = True
                    self.save_state()

                    self.update_channel_policy(chan_point, self.blocker_ppm, desired_htlc_max, our_policy)
                    msg = f"Outbound liquidity {perc*100:.2f}% < {self.lower_threshold*100}% - Applied blocker fee {self.blocker_ppm} ppm (was {current_ppm} ppm), HTLC max: {desired_htlc_max:,} sats"
                    print(msg)
                    self.logger.info(msg)
                    self.last_log_time = time.time()
                    
                    # Update HTLC ratio in state since we just updated
                    chan_state["last_htlc_ratio"] = perc
                    self.save_state()

                elif perc > self.upper_threshold and chan_state["blocker_active"]:
                    # Remove blocker fee - restore original
                    original_fee = chan_state.get("original_fee_ppm")
                    if original_fee is None:
                        msg = f"Warning: No original fee stored, keeping current fee {current_ppm} ppm"
                        print(msg)
                        self.logger.warning(msg)
                        original_fee = current_ppm

                    chan_state["blocker_active"] = False
                    chan_state["original_fee_ppm"] = None
                    self.save_state()

                    self.update_channel_policy(chan_point, original_fee, desired_htlc_max, our_policy)
                    msg = f"Outbound liquidity {perc*100:.2f}% > {self.upper_threshold*100}% - Removed blocker fee, restored {original_fee} ppm, HTLC max: {desired_htlc_max:,} sats"
                    print(msg)
                    self.logger.info(msg)
                    self.last_log_time = time.time()
                    
                    # Update HTLC ratio in state since we just updated
                    chan_state["last_htlc_ratio"] = perc
                    self.save_state()

                else:
                    # Check if we should update HTLC max based on ratio change
                    should_update_htlc = False
                    if chan_state.get("last_htlc_ratio") is None:
                        should_update_htlc = True
                        update_reason = "initial setup"
                    else:
                        ratio_change = abs(perc - chan_state["last_htlc_ratio"])
                        if ratio_change >= self.htlc_change_threshold:
                            should_update_htlc = True
                            update_reason = f"ratio changed {ratio_change*100:.2f}%"
                    
                    if should_update_htlc and current_htlc_max != desired_htlc_max:
                        # Only update HTLC max, keep current fee
                        self.update_channel_policy(chan_point, current_ppm, desired_htlc_max, our_policy)
                        msg = f"Updated HTLC max from {current_htlc_max:,} to {desired_htlc_max:,} sats (liquidity: {perc*100:.2f}%, reason: {update_reason})"
                        print(msg)
                        self.logger.info(msg)
                        self.last_log_time = time.time()
                        
                        # Save the ratio to state
                        chan_state["last_htlc_ratio"] = perc
                        self.save_state()
                        
                    elif log_now:
                        status = "Blocker active" if chan_state["blocker_active"] else "Normal"
                        msg = f"Outbound liquidity {perc*100:.2f}% - {status} - Fee: {current_ppm} ppm, HTLC max: {current_htlc_max:,} sats"
                        print(msg)
                        self.logger.info(msg)
                        self.last_log_time = time.time()

                self.last_perc = perc

                time.sleep(self.poll_interval)

            except ValueError as e:
                err_msg = f"Error during poll: {e}"
                print(err_msg, file=sys.stderr)
                self.logger.error(err_msg)
                if "not found in listchannels" in str(e):
                    consecutive_not_found += 1
                    if consecutive_not_found >= max_not_found:
                        print(f"Channel {self.chan_id_numeric} not found after {max_not_found} attempts, exiting.", file=sys.stderr)
                        self.logger.error(f"Channel {self.chan_id_numeric} not found after {max_not_found} attempts, exiting.")
                        break
                time.sleep(self.poll_interval)

            except Exception as e:
                err_msg = f"Error during poll: {e}"
                print(err_msg, file=sys.stderr)
                self.logger.error(err_msg)
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    print("Too many consecutive errors, exiting.", file=sys.stderr)
                    self.logger.error("Too many consecutive errors, exiting.")
                    break
                time.sleep(min(self.poll_interval * (2 ** consecutive_errors), 60))  # Backoff up to 60s

        print("Channel Guard stopped.")
        self.logger.info("Channel Guard stopped.")

def main():
    parser = argparse.ArgumentParser(
        description="Monitor a Lightning channel and manage fees/HTLC limits to preserve outbound liquidity."
    )
    parser.add_argument('chan_id', type=str, help="The channel ID to monitor (compact numeric SCID or human-readable like 902245x1158x1)")
    parser.add_argument('--lower_threshold', type=float, default=0.3, help="Apply blocker when outbound liquidity falls below this (default: 0.3 = 30%)")
    parser.add_argument('--upper_threshold', type=float, default=0.4, help="Remove blocker when outbound liquidity rises above this (default: 0.4 = 40%)")
    parser.add_argument('--liquidity_floor', type=float, default=0.35, help="Preserve this amount of outbound liquidity via HTLC max (default: 0.35 = 35%)")
    parser.add_argument('--blocker_ppm', type=int, default=17000, help="Blocker fee rate in ppm (default: 17000)")
    parser.add_argument('--poll_interval', type=int, default=2, help="Polling interval in seconds (default: 2)")
    parser.add_argument('--htlc_change_threshold', type=float, default=0.01, help="Min ratio change for HTLC updates (default: 0.01 = 1%)")

    args = parser.parse_args()

    # Validate thresholds
    if args.lower_threshold >= args.upper_threshold:
        sys.exit("Error: lower_threshold must be less than upper_threshold")

    if args.liquidity_floor >= 1.0 or args.liquidity_floor < 0:
        sys.exit("Error: liquidity_floor must be between 0 and 1")

    if args.lower_threshold < 0 or args.lower_threshold >= 1:
        sys.exit("Error: lower_threshold must be between 0 and 1")

    if args.upper_threshold < 0 or args.upper_threshold >= 1:
        sys.exit("Error: upper_threshold must be between 0 and 1")
    
    if args.htlc_change_threshold <= 0:
        sys.exit("Error: htlc_change_threshold must be positive")

    guard = ChannelGuard(
        args.chan_id,
        args.lower_threshold,
        args.upper_threshold,
        args.liquidity_floor,
        args.blocker_ppm,
        args.poll_interval,
        args.htlc_change_threshold
    )

    guard.run()

if __name__ == "__main__":
    main()