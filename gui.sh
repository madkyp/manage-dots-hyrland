#!/usr/bin/env bash
# Bootstrap: asegura GTK4/libadwaita/PyGObject y lanza la interfaz grafica.
set -euo pipefail

if ! python3 -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1'); from gi.repository import Gtk, Adw" >/dev/null 2>&1; then
  echo "==> Instalando dependencias GTK4/libadwaita..."
  sudo pacman -S --needed --noconfirm python-gobject gtk4 libadwaita
fi

cd "$(dirname "${BASH_SOURCE[0]}")"
exec python3 dots_gui.py "$@"
