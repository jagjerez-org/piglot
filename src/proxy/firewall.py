"""
System-level firewall rules for PiGlot.

This script configures iptables so that the piglot user can ONLY
access the internet through the proxy. Direct connections are blocked.

This is the nuclear option — even if someone bypasses the proxy in code,
iptables won't let the traffic through.

Run with sudo: sudo python3 -m src.proxy.firewall install
"""

from __future__ import annotations

import subprocess
import sys


PROXY_PORT = 8899
PIGLOT_USER = "piglot"  # Dedicated system user for the service

IPTABLES_RULES = f"""
# Allow loopback (proxy runs on localhost)
-A OUTPUT -o lo -m owner --uid-owner {PIGLOT_USER} -j ACCEPT

# Allow DNS (needed for domain resolution)
-A OUTPUT -p udp --dport 53 -m owner --uid-owner {PIGLOT_USER} -j ACCEPT
-A OUTPUT -p tcp --dport 53 -m owner --uid-owner {PIGLOT_USER} -j ACCEPT

# Allow traffic TO the local proxy
-A OUTPUT -p tcp --dport {PROXY_PORT} -m owner --uid-owner {PIGLOT_USER} -j ACCEPT

# Allow established connections (responses)
-A OUTPUT -m state --state ESTABLISHED,RELATED -m owner --uid-owner {PIGLOT_USER} -j ACCEPT

# BLOCK everything else from piglot user
-A OUTPUT -m owner --uid-owner {PIGLOT_USER} -j REJECT
"""

SETUP_SCRIPT = f"""#!/bin/bash
set -euo pipefail

echo "🛡️  PiGlot Firewall Setup"
echo "========================"

# Create dedicated piglot user (no login shell)
if ! id -u {PIGLOT_USER} &>/dev/null; then
    echo "Creating user '{PIGLOT_USER}'..."
    sudo useradd --system --no-create-home --shell /usr/sbin/nologin {PIGLOT_USER}
    sudo usermod -aG audio {PIGLOT_USER}
fi

# Install iptables rules
echo "Installing iptables rules..."

# Allow loopback
sudo iptables -A OUTPUT -o lo -m owner --uid-owner {PIGLOT_USER} -j ACCEPT

# Allow DNS
sudo iptables -A OUTPUT -p udp --dport 53 -m owner --uid-owner {PIGLOT_USER} -j ACCEPT
sudo iptables -A OUTPUT -p tcp --dport 53 -m owner --uid-owner {PIGLOT_USER} -j ACCEPT

# Allow proxy port
sudo iptables -A OUTPUT -p tcp -d 127.0.0.1 --dport {PROXY_PORT} -m owner --uid-owner {PIGLOT_USER} -j ACCEPT

# Allow established
sudo iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -m owner --uid-owner {PIGLOT_USER} -j ACCEPT

# Block everything else from piglot
sudo iptables -A OUTPUT -m owner --uid-owner {PIGLOT_USER} -j REJECT

# Persist rules
if command -v netfilter-persistent &>/dev/null; then
    sudo netfilter-persistent save
else
    echo "Install iptables-persistent to make rules survive reboot:"
    echo "  sudo apt install iptables-persistent"
fi

echo ""
echo "✅ Firewall rules installed!"
echo "   User '{PIGLOT_USER}' can only access the internet via proxy on port {PROXY_PORT}"
echo ""
echo "To verify:"
echo "  sudo iptables -L OUTPUT -v --line-numbers | grep {PIGLOT_USER}"
"""


def install() -> None:
    """Install firewall rules."""
    print(SETUP_SCRIPT)
    confirm = input("\nRun this script? [y/N] ")
    if confirm.lower() != "y":
        print("Aborted.")
        return
    subprocess.run(["bash", "-c", SETUP_SCRIPT], check=True)


def remove() -> None:
    """Remove firewall rules for piglot user."""
    print(f"Removing iptables rules for user '{PIGLOT_USER}'...")
    result = subprocess.run(
        ["sudo", "iptables", "-L", "OUTPUT", "--line-numbers", "-n"],
        capture_output=True, text=True,
    )
    lines = result.stdout.strip().split("\n")
    # Find and remove rules in reverse order (so line numbers stay valid)
    rule_numbers = []
    for line in lines:
        if PIGLOT_USER in line:
            num = line.split()[0]
            if num.isdigit():
                rule_numbers.append(int(num))
    
    for num in reversed(sorted(rule_numbers)):
        subprocess.run(
            ["sudo", "iptables", "-D", "OUTPUT", str(num)],
            check=True,
        )
        print(f"  Removed rule #{num}")
    
    print("✅ Firewall rules removed.")


def status() -> None:
    """Show current firewall rules for piglot user."""
    result = subprocess.run(
        ["sudo", "iptables", "-L", "OUTPUT", "-v", "--line-numbers"],
        capture_output=True, text=True,
    )
    lines = [l for l in result.stdout.split("\n") if PIGLOT_USER in l or "Chain" in l]
    if not lines:
        print(f"No iptables rules found for user '{PIGLOT_USER}'")
    else:
        print("\n".join(lines))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 -m src.proxy.firewall [install|remove|status]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    if cmd == "install":
        install()
    elif cmd == "remove":
        remove()
    elif cmd == "status":
        status()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
