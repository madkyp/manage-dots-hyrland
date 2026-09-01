#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["rich>=13.7", "questionary>=2.0"]
# ///
"""
dots.py — extractor/instalador de dotfiles de Hyprland (HyDE) para Arch/CachyOS.

  uv run dots.py export     # snapshot de la maquina actual -> este repo (files/)
  uv run dots.py install    # instala paquetes + symlinks desde este repo -> $HOME
  uv run dots.py list       # muestra categorias y su estado

No necesitas instalar nada a mano: `uv run` resuelve rich/questionary solo.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import socket
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table
import questionary

console = Console()
HOME = Path.home()
REPO = Path(__file__).resolve().parent
FILES_DIR = REPO / "files"
PACKAGES_TOML = REPO / "packages.toml"
MANIFEST_JSON = REPO / "manifest.json"

MAX_FILE_BYTES = 5 * 1024 * 1024  # 5MB: por encima, se salta (wallpapers, binarios, etc.)


@dataclass
class Category:
    id: str
    label: str
    group: str
    home_paths: list[str]                       # rutas relativas a $HOME (archivo o carpeta)
    pacman_candidates: list[str] = field(default_factory=list)
    aur_candidates: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)  # globs relativos a cada home_path, solo para dirs
    default: bool = True
    note: str | None = None


CATEGORIES: list[Category] = [
    Category("hypr", "Hyprland (core: hyprland/hypridle/hyprlock/hyprsunset)", "Hyprland",
             [".config/hypr"], ["hyprland", "hypridle", "hyprlock", "hyprsunset"]),
    Category("waybar", "Waybar", "Hyprland", [".config/waybar"], ["waybar"]),
    Category("rofi", "Rofi (launcher)", "Hyprland", [".config/rofi"], ["rofi", "rofi-wayland"]),
    Category("dunst", "Dunst (notificaciones)", "Hyprland", [".config/dunst"], ["dunst"]),
    Category("swaync", "SwayNC (centro de notificaciones)", "Hyprland", [".config/swaync"],
             ["swaync"], ["sw-notification-center"]),
    Category("kitty", "Kitty (terminal)", "Terminal", [".config/kitty"], ["kitty"]),
    Category("ghostty", "Ghostty (terminal)", "Terminal", [".config/ghostty"], ["ghostty"]),
    Category("fish", "Fish (shell)", "Shell", [".config/fish"], ["fish", "cachyos-fish-config"]),
    Category("fastfetch", "Fastfetch", "Utils", [".config/fastfetch"], ["fastfetch"]),
    Category("pypr", "Pyprland (pypr)", "Hyprland", [".config/pypr"], [], ["pyprland"]),
    Category("nwg-look", "nwg-look (tema GTK)", "Theming", [".config/nwg-look"], [], ["nwg-look"]),
    Category("nwg-displays", "nwg-displays (monitores)", "Theming", [".config/nwg-displays"], [], ["nwg-displays"]),
    Category("gtk", "Temas GTK (config, no assets)", "Theming",
             [".config/gtk-3.0", ".gtkrc-2.0"], [],
             note="El tema GTK en si (iconos/gtk-4.0) se instala como paquete, no se copia."),
    Category("qt-theming", "Qt theming (qt5ct/qt6ct/Kvantum)", "Theming",
             [".config/qt5ct", ".config/qt6ct", ".config/Kvantum"],
             ["qt5ct", "qt6ct"], ["kvantum", "kvantum-qt5"]),
    Category("skwd-wall", "skwd-wall (wallpaper switcher)", "Hyprland",
             [".config/skwd-wall"], [],
             note="Herramienta personalizada: revisa manualmente de donde viene."),
    Category("spicetify", "Spicetify (Spotify theming)", "Extras", [".config/spicetify"], [], ["spicetify-cli"]),
    Category("hyde", "HyDE (config.toml + wallbash + definiciones de tema, SIN wallpapers)", "Hyprland",
             [".config/hyde"], [], ["hyde-cli-git"],
             exclude=["*/wallpapers/*", "*/wallpapers", "*/walls/*", "*/walls", "*/wall.*"],
             note="Instala HyDE primero (https://github.com/HyDE-Project/HyDE) para tener el motor de temas."),
    Category("shell-rc", "Dotfiles sueltos de shell (.zshrc, .bashrc, .xprofile, .Xresources...)", "Shell",
             [".zshrc", ".zshenv", ".bashrc", ".bash_profile", ".bash_logout",
              ".xprofile", ".Xresources"]),
    Category("autostart", "Autostart de apps (.config/autostart)", "Extras",
             [".config/autostart"], default=False),
    Category("mimeapps", "Apps por defecto (mimeapps.list)", "Extras", [".config/mimeapps.list"], default=False),
]

CATEGORY_BY_ID = {c.id: c for c in CATEGORIES}


# ---------- utilidades ----------

def sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, capture_output=True, **kw)


def installed_pacman_set() -> set[str]:
    r = sh(["pacman", "-Qq"])
    return set(r.stdout.split()) if r.returncode == 0 else set()


def path_size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    total = 0
    for f in p.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def category_exists(c: Category) -> bool:
    return any((HOME / p).exists() for p in c.home_paths)


def category_size(c: Category) -> int:
    return sum(path_size(HOME / p) for p in c.home_paths if (HOME / p).exists())


# ---------- comando: list ----------

def cmd_list(args):
    table = Table(title="Categorias de dotfiles detectadas")
    table.add_column("ID")
    table.add_column("Grupo")
    table.add_column("Existe")
    table.add_column("Tamano")
    table.add_column("Exportado")
    table.add_column("Default")
    exported = set()
    if MANIFEST_JSON.exists():
        exported = set(json.loads(MANIFEST_JSON.read_text()).get("categories", []))
    for c in CATEGORIES:
        exists = category_exists(c)
        table.add_row(
            c.id, c.group,
            "si" if exists else "no",
            human(category_size(c)) if exists else "-",
            "si" if c.id in exported else "no",
            "si" if c.default else "no",
        )
    console.print(table)


# ---------- comando: export ----------

def choose_categories(prompt: str, preselect: set[str]) -> list[Category]:
    available = [c for c in CATEGORIES if category_exists(c)]
    if not available:
        console.print("[red]No se detecto ninguna categoria conocida en este sistema.[/red]")
        sys.exit(1)
    choices = [
        questionary.Choice(
            title=f"{c.label}  [{human(category_size(c))}]" + (f"  -- {c.note}" if c.note else ""),
            value=c.id,
            checked=c.id in preselect,
        )
        for c in available
    ]
    selected_ids = questionary.checkbox(prompt, choices=choices).ask()
    if selected_ids is None:
        console.print("[yellow]Cancelado.[/yellow]")
        sys.exit(1)
    return [CATEGORY_BY_ID[i] for i in selected_ids]


def should_skip(rel: Path, excludes: list[str]) -> bool:
    s = rel.as_posix()
    return any(fnmatch.fnmatch(s, pat) or fnmatch.fnmatch(s + "/", pat) for pat in excludes)


def copy_category(c: Category, skipped_large: list[str], skipped_excluded: list[str]) -> int:
    count = 0
    for home_rel in c.home_paths:
        src = HOME / home_rel
        if not src.exists():
            continue
        if src.is_file():
            dest = FILES_DIR / home_rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.stat().st_size > MAX_FILE_BYTES:
                skipped_large.append(home_rel)
                continue
            shutil.copy2(src, dest)
            count += 1
            continue
        for f in src.rglob("*"):
            if not f.is_file():
                continue
            rel_to_cat = f.relative_to(src)
            if should_skip(rel_to_cat, c.exclude):
                skipped_excluded.append(str((Path(home_rel) / rel_to_cat)))
                continue
            try:
                size = f.stat().st_size
            except OSError:
                continue
            if size > MAX_FILE_BYTES:
                skipped_large.append(str((Path(home_rel) / rel_to_cat)))
                continue
            rel_home = Path(home_rel) / rel_to_cat
            dest = FILES_DIR / rel_home
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
            count += 1
    return count


def build_packages_toml(selected: list[Category]) -> str:
    installed = installed_pacman_set()
    lines = [
        "# Generado por dots.py export. No edites a mano salvo que sepas lo que haces.",
        "# 'pacman' = paquetes de repos oficiales (o CachyOS). 'aur' = requieren yay/paru.",
        "",
    ]
    for c in selected:
        pac = [p for p in c.pacman_candidates if p in installed]
        aur = [p for p in c.aur_candidates if p in installed]
        undetected = [p for p in c.pacman_candidates + c.aur_candidates if p not in installed]
        lines.append(f"[{c.id}]")
        lines.append(f"label = {json.dumps(c.label)}")
        lines.append(f"pacman = {json.dumps(pac)}")
        lines.append(f"aur = {json.dumps(aur)}")
        if undetected:
            lines.append(f"# no detectados como instalados, verifica manualmente: {', '.join(undetected)}")
        if c.note:
            lines.append(f"note = {json.dumps(c.note)}")
        lines.append("")
    return "\n".join(lines)


def cmd_export(args):
    console.print(f"[bold]Exportando dotfiles desde {HOME} hacia {REPO}[/bold]")
    preselect = {c.id for c in CATEGORIES if c.default}
    selected = choose_categories("Que categorias quieres exportar/actualizar?", preselect)
    FILES_DIR.mkdir(exist_ok=True)

    skipped_large: list[str] = []
    skipped_excluded: list[str] = []
    total = 0
    for c in selected:
        n = copy_category(c, skipped_large, skipped_excluded)
        console.print(f"  [green]OK[/green] {c.id}: {n} archivos")
        total += n

    PACKAGES_TOML.write_text(build_packages_toml(selected))
    manifest = {
        "host": socket.gethostname(),
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "categories": [c.id for c in selected],
        "files_copied": total,
        "skipped_large_files": skipped_large,
        "skipped_excluded_files": skipped_excluded,
    }
    MANIFEST_JSON.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    console.print(f"\n[bold green]Listo:[/bold green] {total} archivos, {len(selected)} categorias.")
    if skipped_large:
        console.print(f"[yellow]{len(skipped_large)} archivos saltados por tamano (>{human(MAX_FILE_BYTES)}).[/yellow] Ver manifest.json.")
    if skipped_excluded:
        console.print(f"[yellow]{len(skipped_excluded)} archivos excluidos por patron (ej. wallpapers).[/yellow]")

    if (REPO / ".git").exists():
        if questionary.confirm("Hacer commit de estos cambios en git?", default=True).ask():
            sh(["git", "-C", str(REPO), "add", "-A"])
            msg = f"export: {manifest['exported_at']} desde {manifest['host']}"
            r = subprocess.run(["git", "-C", str(REPO), "commit", "-m", msg])
            if r.returncode != 0:
                console.print("[yellow]Nada nuevo que commitear (o fallo el commit).[/yellow]")


# ---------- comando: install ----------

def load_packages_toml() -> dict:
    if not PACKAGES_TOML.exists():
        console.print("[red]No existe packages.toml en este repo. Corre 'export' en la maquina origen primero.[/red]")
        sys.exit(1)
    return tomllib.loads(PACKAGES_TOML.read_text())


def cmd_install(args):
    if shutil.which("pacman") is None:
        console.print("[red]Este instalador es para Arch/derivados (pacman no encontrado).[/red]")
        sys.exit(1)
    if not FILES_DIR.exists():
        console.print("[red]No hay carpeta files/ en este repo. Nada que instalar.[/red]")
        sys.exit(1)

    pkgs = load_packages_toml()
    installed_categories = [c for c in CATEGORIES if c.id in pkgs]
    preselect = {c.id for c in installed_categories}
    selected = questionary.checkbox(
        "Que categorias quieres instalar en esta maquina?",
        choices=[questionary.Choice(title=c.label, value=c.id, checked=True) for c in installed_categories],
    ).ask()
    if not selected:
        console.print("[yellow]Nada seleccionado, saliendo.[/yellow]")
        return

    pacman_pkgs: set[str] = set()
    aur_pkgs: set[str] = set()
    for cid in selected:
        entry = pkgs.get(cid, {})
        pacman_pkgs.update(entry.get("pacman", []))
        aur_pkgs.update(entry.get("aur", []))

    if pacman_pkgs:
        console.print(f"\n[bold]Paquetes oficiales a instalar:[/bold] {', '.join(sorted(pacman_pkgs))}")
    if aur_pkgs:
        console.print(f"[bold]Paquetes AUR a instalar:[/bold] {', '.join(sorted(aur_pkgs))}")

    if (pacman_pkgs or aur_pkgs) and questionary.confirm("Confirmas instalar estos paquetes?", default=True).ask():
        if pacman_pkgs:
            subprocess.run(["sudo", "pacman", "-S", "--needed", *sorted(pacman_pkgs)])
        if aur_pkgs:
            helper = shutil.which("yay") or shutil.which("paru")
            if helper:
                subprocess.run([helper, "-S", "--needed", *sorted(aur_pkgs)])
            else:
                console.print("[yellow]No hay yay/paru instalado; instala estos paquetes AUR a mano:[/yellow] "
                               + ", ".join(sorted(aur_pkgs)))

    backup_dir = HOME / f".dotfiles-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    linked = 0
    backed_up = 0
    for cid in selected:
        c = CATEGORY_BY_ID.get(cid)
        if not c:
            continue
        for home_rel in c.home_paths:
            src_root = FILES_DIR / home_rel
            if not src_root.exists():
                continue
            files = [src_root] if src_root.is_file() else [f for f in src_root.rglob("*") if f.is_file()]
            for src in files:
                rel = src.relative_to(FILES_DIR)
                dest = HOME / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.is_symlink() and dest.resolve() == src.resolve():
                    continue
                if dest.exists() or dest.is_symlink():
                    backup_dest = backup_dir / rel
                    backup_dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(dest), str(backup_dest))
                    backed_up += 1
                dest.symlink_to(src)
                linked += 1

    console.print(f"\n[bold green]Listo:[/bold green] {linked} symlinks creados.")
    if backed_up:
        console.print(f"[yellow]{backed_up} archivos previos movidos a {backup_dir}[/yellow]")
    console.print("Puede que necesites reiniciar la sesion de Hyprland para que todo surta efecto.")


# ---------- main ----------

def main():
    parser = argparse.ArgumentParser(description="Extractor/instalador de dotfiles Hyprland/HyDE")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="Muestra categorias detectadas y su estado")
    sub.add_parser("export", help="Exporta la config actual de esta maquina a este repo")
    sub.add_parser("install", help="Instala paquetes y crea symlinks desde este repo")
    args = parser.parse_args()

    {"list": cmd_list, "export": cmd_export, "install": cmd_install}[args.cmd](args)


if __name__ == "__main__":
    main()
