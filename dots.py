#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["rich>=13.7", "questionary>=2.0"]
# ///
"""
dots.py — CLI para extraer/instalar dotfiles de Hyprland (HyDE) en Arch/CachyOS.

  uv run dots.py export     # snapshot de la maquina actual -> este repo (files/)
  uv run dots.py install    # instala paquetes + symlinks desde este repo -> $HOME
  uv run dots.py list       # muestra categorias y su estado

Tambien hay una interfaz grafica: ver dots_gui.py (requiere GTK4/libadwaita del sistema).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

from rich.console import Console
from rich.table import Table
import questionary

import dots_core as core

console = Console()


def cmd_list(args):
    table = Table(title="Categorias de dotfiles detectadas")
    table.add_column("ID")
    table.add_column("Grupo")
    table.add_column("Existe")
    table.add_column("Tamano")
    table.add_column("Exportado")
    table.add_column("Default")
    exported = set()
    if core.MANIFEST_JSON.exists():
        import json
        exported = set(json.loads(core.MANIFEST_JSON.read_text()).get("categories", []))
    for c in core.CATEGORIES:
        exists = core.category_exists(c)
        table.add_row(
            c.id, c.group,
            "si" if exists else "no",
            core.human(core.category_size(c)) if exists else "-",
            "si" if c.id in exported else "no",
            "si" if c.default else "no",
        )
    console.print(table)


def choose_categories(prompt: str, preselect: set[str]) -> list[core.Category]:
    available = [c for c in core.CATEGORIES if core.category_exists(c)]
    if not available:
        console.print("[red]No se detecto ninguna categoria conocida en este sistema.[/red]")
        sys.exit(1)
    choices = [
        questionary.Choice(
            title=f"{c.label}  [{core.human(core.category_size(c))}]" + (f"  -- {c.note}" if c.note else ""),
            value=c.id,
            checked=c.id in preselect,
        )
        for c in available
    ]
    selected_ids = questionary.checkbox(prompt, choices=choices).ask()
    if selected_ids is None:
        console.print("[yellow]Cancelado.[/yellow]")
        sys.exit(1)
    return [core.CATEGORY_BY_ID[i] for i in selected_ids]


def cmd_export(args):
    console.print(f"[bold]Exportando dotfiles desde {core.HOME} hacia {core.REPO}[/bold]")
    preselect = {c.id for c in core.CATEGORIES if c.default}
    selected = choose_categories("Que categorias quieres exportar/actualizar?", preselect)

    manifest = core.export_categories(selected, progress=lambda m: console.print(f"  [green]OK[/green] {m}"))

    console.print(f"\n[bold green]Listo:[/bold green] {manifest['files_copied']} archivos, {len(selected)} categorias.")
    if manifest["skipped_large_files"]:
        console.print(f"[yellow]{len(manifest['skipped_large_files'])} archivos saltados por tamano (>{core.human(core.MAX_FILE_BYTES)}).[/yellow] Ver manifest.json.")
    if manifest["skipped_excluded_files"]:
        console.print(f"[yellow]{len(manifest['skipped_excluded_files'])} archivos excluidos por patron (ej. wallpapers).[/yellow]")

    if (core.REPO / ".git").exists():
        if questionary.confirm("Hacer commit de estos cambios en git?", default=True).ask():
            ok, out = core.git_commit(f"export: {manifest['exported_at']} desde {manifest['host']}")
            if ok:
                console.print("[green]Commit hecho.[/green]")
            else:
                console.print(f"[yellow]Nada nuevo que commitear (o fallo el commit).[/yellow] {out}")


def cmd_install(args):
    if shutil.which("pacman") is None:
        console.print("[red]Este instalador es para Arch/derivados (pacman no encontrado).[/red]")
        sys.exit(1)
    if not core.FILES_DIR.exists():
        console.print("[red]No hay carpeta files/ en este repo. Nada que instalar.[/red]")
        sys.exit(1)

    pkgs = core.load_packages_toml()
    if not pkgs:
        console.print("[red]No existe packages.toml en este repo. Corre 'export' en la maquina origen primero.[/red]")
        sys.exit(1)
    installed_categories = [c for c in core.CATEGORIES if c.id in pkgs]
    selected = questionary.checkbox(
        "Que categorias quieres instalar en esta maquina?",
        choices=[questionary.Choice(title=c.label, value=c.id, checked=True) for c in installed_categories],
    ).ask()
    if not selected:
        console.print("[yellow]Nada seleccionado, saliendo.[/yellow]")
        return

    pacman_pkgs, aur_pkgs = core.plan_packages(selected, pkgs)
    if pacman_pkgs:
        console.print(f"\n[bold]Paquetes oficiales a instalar:[/bold] {', '.join(pacman_pkgs)}")
    if aur_pkgs:
        console.print(f"[bold]Paquetes AUR a instalar:[/bold] {', '.join(aur_pkgs)}")

    if (pacman_pkgs or aur_pkgs) and questionary.confirm("Confirmas instalar estos paquetes?", default=True).ask():
        if pacman_pkgs:
            subprocess.run(["sudo", "pacman", "-S", "--needed", *pacman_pkgs])
        if aur_pkgs:
            helper = shutil.which("yay") or shutil.which("paru")
            if helper:
                subprocess.run([helper, "-S", "--needed", *aur_pkgs])
            else:
                console.print("[yellow]No hay yay/paru instalado; instala estos paquetes AUR a mano:[/yellow] "
                               + ", ".join(aur_pkgs))

    result = core.symlink_categories(selected, progress=lambda m: console.print(f"  [green]OK[/green] {m}"))
    console.print(f"\n[bold green]Listo:[/bold green] {result['linked']} symlinks creados.")
    if result["backup_dir"]:
        console.print(f"[yellow]{result['backed_up']} archivos previos movidos a {result['backup_dir']}[/yellow]")
    console.print("Puede que necesites reiniciar la sesion de Hyprland para que todo surta efecto.")


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
