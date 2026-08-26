#!/usr/bin/env bash
# Switch only the Pi Wi-Fi connection mode. Do not edit or remove existing profiles.
set -euo pipefail

DEVICE="${HUIAN_WIFI_DEVICE:-wlan0}"
DEV_CONNECTION="${HUIAN_DEV_CONNECTION:-MAGO2_5G}"
SHOW_CONNECTION="${HUIAN_SHOW_CONNECTION:-Huian_Loudao}"
FALLBACK_UNIT="huian-network-show-fallback"
ROLLBACK_SECONDS="${HUIAN_SHOW_ROLLBACK_SECONDS:-180}"

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo "$0" "$@"
fi

require_connection() {
  nmcli --terse --fields NAME connection show | grep --fixed-strings --quiet -- "$1" || {
    echo "Missing NetworkManager connection profile: $1" >&2
    exit 1
  }
}

cancel_fallback() {
  systemctl stop "${FALLBACK_UNIT}.timer" "${FALLBACK_UNIT}.service" 2>/dev/null || true
}

show_status() {
  echo "Wi-Fi device: ${DEVICE}"
  nmcli --terse --fields DEVICE,TYPE,STATE,CONNECTION device status
  echo
  echo "Active connections:"
  nmcli --terse --fields NAME,TYPE,DEVICE connection show --active
  echo
  echo "Configured profiles:"
  nmcli --terse --fields NAME,TYPE,AUTOCONNECT connection show | grep --extended-regexp "^(${DEV_CONNECTION}|${SHOW_CONNECTION}):" || true
}

activate_development() {
  require_connection "${DEV_CONNECTION}"
  require_connection "${SHOW_CONNECTION}"
  cancel_fallback
  nmcli connection modify "${SHOW_CONNECTION}" connection.autoconnect no
  nmcli connection modify "${DEV_CONNECTION}" connection.autoconnect yes
  nmcli connection up "${DEV_CONNECTION}" ifname "${DEVICE}"
  echo "Development network restored: ${DEV_CONNECTION}"
}

activate_showcase() {
  require_connection "${DEV_CONNECTION}"
  require_connection "${SHOW_CONNECTION}"
  if [[ "${ROLLBACK_SECONDS}" != "0" ]]; then
    cancel_fallback
    systemd-run --unit="${FALLBACK_UNIT}" --on-active="${ROLLBACK_SECONDS}s" "$0" development
    echo "Safety rollback armed for ${ROLLBACK_SECONDS}s. Run '$0 showcase-confirm' after local verification."
  fi
  nmcli connection modify "${DEV_CONNECTION}" connection.autoconnect no
  nmcli connection modify "${SHOW_CONNECTION}" connection.autoconnect yes
  nmcli connection up "${SHOW_CONNECTION}" ifname "${DEVICE}"
  echo "Showcase hotspot enabled: ${SHOW_CONNECTION}"
}

confirm_showcase() {
  require_connection "${SHOW_CONNECTION}"
  cancel_fallback
  nmcli connection modify "${SHOW_CONNECTION}" connection.autoconnect yes
  echo "Showcase hotspot confirmed. It will stay selected after reboot."
}

case "${1:-status}" in
  development) activate_development ;;
  showcase) activate_showcase ;;
  showcase-confirm) confirm_showcase ;;
  status) show_status ;;
  *)
    echo "Usage: $0 {status|development|showcase|showcase-confirm}" >&2
    exit 2
    ;;
esac