#!/usr/bin/env bash
# First-boot unattended install, run once by eparking-firstboot.service.
# Role comes from /etc/eparking-install.conf (ROLE=combo|server|booth, EXTRA="--server-ip=.. --token=.."),
# default combo. On success: writes the done marker and leaves a one-time
# autostart that opens the setup wizard when the 'parking' user logs in.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROLE=combo
EXTRA=""
[[ -r /etc/eparking-install.conf ]] && source /etc/eparking-install.conf

# shellcheck disable=SC2086
"$HERE/../install-gui.sh" --auto "$ROLE" $EXTRA

mkdir -p /var/lib/parking
touch /var/lib/parking/firstboot.done

# Wizard launcher: opens while the one-time token exists (the API deletes it
# on redeem), then removes its own autostart entry.
install -d -o parking -g parking /home/parking/.config/autostart
cat > /usr/local/bin/eparking-open-wizard <<'EOS'
#!/usr/bin/env bash
if [[ -r /etc/parking/setup-token ]]; then
    exec google-chrome --no-first-run "http://localhost/setup?token=$(cat /etc/parking/setup-token)"
fi
rm -f "$HOME/.config/autostart/eparking-wizard.desktop"
EOS
chmod +x /usr/local/bin/eparking-open-wizard
cat > /home/parking/.config/autostart/eparking-wizard.desktop <<'EOD'
[Desktop Entry]
Type=Application
Name=E-Parking Setup Wizard
Exec=/usr/local/bin/eparking-open-wizard
EOD
chown parking:parking /home/parking/.config/autostart/eparking-wizard.desktop
