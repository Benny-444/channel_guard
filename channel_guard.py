#!/usr/bin/env python3
import subprocess
import json
import time
import argparse
import sys

def run_lncli(cmd_args):
    """Run lncli command and return output as string."""
    try:
        return subprocess.check_output(['lncli'] + cmd_args).decode('utf-8').strip()
    except subprocess.CalledProcessError as e:
        print(f"Error running lncli: {e}", file=sys.stderr)
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        description="Monitor a Lightning channel and apply a blocker fee if outbound liquidity falls below a threshold."
    )
    parser.add_argument('chan_id', type=str, help="The channel ID to monitor (compact numeric SCID like 992028868678647809 or human-readable like 902245x1158x1)")
    parser.add_argument('--threshold', type=float, default=0.4, help="Outbound liquidity threshold (default: 0.4 = 40%)")
    parser.add_argument('--blocker_ppm', type=int, default=17000, help="Blocker fee rate in ppm (default: 17000)")
    parser.add_argument('--poll_interval', type=int, default=1, help="Polling interval in seconds (default: 1)")
    
    args = parser.parse_args()

    # Parse chan_id to compact numeric if in 'x' format
    if 'x' in args.chan_id:
        parts = args.chan_id.split('x')
        if len(parts) != 3:
            sys.exit("Invalid SCID format; use format like 902245x1158x1")
        try:
            block = int(parts[0])
            tx = int(parts[1])
            out = int(parts[2])
            chan_id_numeric = str((block << 40) | (tx << 16) | out)
        except ValueError:
            sys.exit("Invalid SCID parts; must be integers")
    else:
        try:
            int(args.chan_id)  # Validate it's numeric
            chan_id_numeric = args.chan_id
        except ValueError:
            sys.exit("Invalid chan_id; must be numeric SCID or 'x' format")

    # Get our node's pubkey (cached, as it doesn't change)
    our_info = json.loads(run_lncli(['getinfo']))
    our_pubkey = our_info['identity_pubkey']

    print(f"Monitoring channel {args.chan_id} (numeric: {chan_id_numeric}) with threshold {args.threshold*100}% and blocker {args.blocker_ppm} ppm.")

    last_log_time = time.time()
    last_perc = None

    while True:
        try:
            # Get balances and chan_point from listchannels
            list_chans_str = run_lncli(['listchannels'])
            list_chans = json.loads(list_chans_str)
            channel = next((ch for ch in list_chans['channels'] if ch.get('scid', '') == chan_id_numeric), None)
            if not channel:
                raise ValueError(f"Channel {chan_id_numeric} not found in listchannels.")

            capacity = int(channel['capacity'])
            local_balance = int(channel['local_balance'])
            perc = local_balance / capacity if capacity > 0 else 0.0
            chan_point = channel['channel_point']

            # Get policies from getchaninfo to check current fee
            chan_info_str = run_lncli(['getchaninfo', '--chan_id', chan_id_numeric])
            chan_info = json.loads(chan_info_str)

            # Determine our policy
            if chan_info['node1_pub'] == our_pubkey:
                our_policy = chan_info['node1_policy']
            else:
                our_policy = chan_info['node2_policy']
            current_ppm = int(our_policy['fee_rate_milli_msat'])

            # Check if we need to log (every 60s if no change, or immediately on change/action)
            current_time = time.time()
            log_now = (perc != last_perc) or (current_time - last_log_time >= 60)

            if perc < args.threshold:
                if current_ppm != args.blocker_ppm:
                    # Apply blocker fee (only updates fee_rate_ppm, leaves others unchanged)
                    run_lncli(['updatechanpolicy', '--chan_point', chan_point, '--fee_rate_ppm', str(args.blocker_ppm)])
                    print(f"Outbound liquidity {perc*100:.2f}% < {args.threshold*100}% - Applied blocker fee {args.blocker_ppm} ppm.")
                    last_log_time = current_time
                elif log_now:
                    print(f"Outbound liquidity {perc*100:.2f}% < {args.threshold*100}% - Blocker already applied.")
                    last_log_time = current_time
            else:
                if log_now:
                    print(f"Outbound liquidity {perc*100:.2f}% >= {args.threshold*100}% - No action needed.")
                    last_log_time = current_time

            last_perc = perc

        except Exception as e:
            print(f"Error during poll: {e}", file=sys.stderr)

        time.sleep(args.poll_interval)

if __name__ == "__main__":
    main()
