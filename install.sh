#!/usr/bin/env bash
# Bootstrap: asegura que 'uv' este disponible y delega en dots.py.
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "==> 'uv' no encontrado, instalando con pacman..."
  sudo pacman -S --needed --noconfirm uv
fi

cd "$(dirname "${BASH_SOURCE[0]}")"
exec uv run dots.py install "$@"
