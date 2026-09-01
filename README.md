# dotfiles

Config de escritorio (Hyprland + [HyDE](https://github.com/HyDE-Project/HyDE)) para Arch/CachyOS,
gestionada con `dots.py` (CLI) o `dots_gui.py` (interfaz grafica GTK4/libadwaita) — ambos
comparten la misma logica en `dots_core.py`.

## Interfaz grafica (GTK4 + libadwaita)

```bash
git clone <url-de-este-repo> ~/dotfiles
cd ~/dotfiles
./gui.sh
```

`gui.sh` instala `python-gobject`, `gtk4` y `libadwaita` via pacman si faltan, y abre una
ventana con dos pestañas:

- **Exportar**: checklist de categorias (con tamaño y notas) → copia lo seleccionado a `files/`,
  regenera `packages.toml`/`manifest.json` y ofrece hacer commit desde un toast.
- **Instalar**: checklist de las categorias presentes en `packages.toml` → "Instalar paquetes"
  abre una terminal (kitty/alacritty/xterm) con `sudo pacman` / `yay` para que introduzcas tu
  contraseña con normalidad; "Crear symlinks" enlaza `files/<ruta>` → `$HOME/<ruta>` (sin sudo),
  con backup automatico de lo que ya exista.

Si ya tienes las dependencias GTK, tambien puedes lanzarla directo: `python3 dots_gui.py`.

## Linea de comandos

No hace falta instalar nada a mano: el script usa [`uv`](https://docs.astral.sh/uv/) para
resolver sus propias dependencias (`rich`, `questionary`) la primera vez que se ejecuta.

```bash
git clone <url-de-este-repo> ~/dotfiles
cd ~/dotfiles
./install.sh
```

Esto:
1. Instala `uv` si falta (via pacman).
2. Te muestra un checklist interactivo de que categorias instalar.
3. Instala los paquetes pacman/AUR necesarios (pide confirmacion antes).
4. Crea symlinks desde `files/<ruta>` hacia `$HOME/<ruta>`, haciendo backup de
   cualquier config previa en `~/.dotfiles-backup-<fecha>/`.

Si ya tienes `uv`, tambien puedes saltarte `install.sh` y correr directamente:

```bash
uv run dots.py install
```

## Actualizar el repo desde la maquina actual

Cuando cambies algo en tu configuracion y quieras guardarlo:

```bash
uv run dots.py export
```

Te deja elegir que categorias re-exportar, regenera `packages.toml` y `manifest.json`,
y te ofrece hacer el commit de git.

## Ver el estado

```bash
uv run dots.py list
```

## Estructura

```
dots_core.py        logica compartida (categorias, export, install, symlinks)
dots.py              CLI (export / install / list) sobre dots_core
dots_gui.py          GUI GTK4/libadwaita sobre dots_core
install.sh           bootstrap CLI (instala uv si falta)
gui.sh               bootstrap GUI (instala GTK4/libadwaita si falta)
packages.toml        paquetes pacman/AUR por categoria (generado)
manifest.json        metadata del ultimo export (generado)
files/               copia espejo de las rutas de $HOME versionadas
```

## Notas importantes

- **No se versionan wallpapers ni assets pesados** (`hyde/themes/*/wallpapers`,
  iconos, fuentes, Steam, flatpak...). Esos se instalan como paquetes o se gestionan
  aparte; este repo es solo configuracion textual.
- La categoria `hyde` asume que ya tienes el motor de temas de
  [HyDE](https://github.com/HyDE-Project/HyDE) instalado (o lo instalas primero);
  aqui solo se versiona tu `config.toml` y tus overrides de tema.
- Cualquier archivo mayor a 5MB se salta automaticamente en el export (ver
  `manifest.json` -> `skipped_large_files`).
