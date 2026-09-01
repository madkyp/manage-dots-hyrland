#!/usr/bin/env python3
"""
dots_gui.py — interfaz grafica (GTK4 + libadwaita) para exportar/instalar
los dotfiles de Hyprland/HyDE de este repo.

Requiere paquetes del sistema (ya presentes en un escritorio Hyprland/GNOME
tipico): python-gobject, gtk4, libadwaita. Lanzalo con:

    python3 dots_gui.py
    # o: ./gui.sh   (instala las dependencias de sistema si faltan)
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, GLib  # noqa: E402

import dots_core as core  # noqa: E402

APP_ID = "com.madkyp.dots"


class DotsWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="Dotfiles Hyprland / HyDE",
                          default_width=880, default_height=720)

        self.export_switches: dict[str, Adw.SwitchRow] = {}
        self.install_switches: dict[str, Adw.SwitchRow] = {}

        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toast_overlay.set_child(root)

        header = Adw.HeaderBar()
        self.view_stack = Adw.ViewStack(vexpand=True)
        switcher = Adw.ViewSwitcher(stack=self.view_stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)
        root.append(header)
        root.append(self.view_stack)

        export_page = self.build_export_page()
        page = self.view_stack.add_titled(export_page, "export", "Exportar")
        page.set_icon_name("document-export-symbolic")

        install_page = self.build_install_page()
        page = self.view_stack.add_titled(install_page, "install", "Instalar")
        page.set_icon_name("system-software-install-symbolic")

        # log compartido, siempre visible al fondo
        log_frame = Gtk.Frame(margin_start=12, margin_end=12, margin_bottom=12)
        log_scroller = Gtk.ScrolledWindow(min_content_height=110, max_content_height=110)
        self.log_view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                      left_margin=6, right_margin=6, top_margin=4, bottom_margin=4)
        log_scroller.set_child(self.log_view)
        log_frame.set_child(log_scroller)
        root.append(log_frame)

        self.log(f"HOME={core.HOME}  repo={core.REPO}")

    # ---------- pagina exportar ----------

    def build_export_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                       margin_top=18, margin_bottom=12, margin_start=18, margin_end=18)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        scroller.set_child(content)

        groups: dict[str, list[core.Category]] = {}
        for c in core.CATEGORIES:
            if core.category_exists(c):
                groups.setdefault(c.group, []).append(c)

        for group_name, cats in groups.items():
            pg = Adw.PreferencesGroup(title=group_name)
            for c in cats:
                subtitle = core.human(core.category_size(c))
                if c.note:
                    subtitle += f" · {c.note}"
                row = Adw.SwitchRow(title=c.label, subtitle=subtitle, active=c.default)
                self.export_switches[c.id] = row
                pg.add(row)
            content.append(pg)

        box.append(scroller)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.END)
        export_btn = Gtk.Button(label="Exportar seleccionados")
        export_btn.add_css_class("suggested-action")
        export_btn.connect("clicked", self.on_export_clicked)
        btn_row.append(export_btn)
        box.append(btn_row)
        return box

    # ---------- pagina instalar ----------

    def build_install_page(self) -> Gtk.Widget:
        self.install_scroller = Gtk.ScrolledWindow(vexpand=True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                       margin_top=18, margin_bottom=12, margin_start=18, margin_end=18)
        box.append(self.install_scroller)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.END)
        refresh_btn = Gtk.Button(label="Recargar packages.toml")
        refresh_btn.connect("clicked", lambda *_: self.populate_install_page())
        pkg_btn = Gtk.Button(label="Instalar paquetes (abre terminal)")
        pkg_btn.connect("clicked", self.on_install_packages_clicked)
        link_btn = Gtk.Button(label="Crear symlinks")
        link_btn.add_css_class("suggested-action")
        link_btn.connect("clicked", self.on_symlink_clicked)
        for b in (refresh_btn, pkg_btn, link_btn):
            btn_row.append(b)
        box.append(btn_row)

        self.populate_install_page()
        return box

    def populate_install_page(self):
        pkgs = core.load_packages_toml()
        self.install_switches = {}
        if not pkgs:
            status = Adw.StatusPage(
                title="No hay packages.toml",
                description="Corre 'Exportar' primero en la maquina origen, o clona un repo que ya lo tenga.",
                icon_name="dialog-warning-symbolic",
            )
            self.install_scroller.set_child(status)
            return

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        groups: dict[str, list[core.Category]] = {}
        for cid in pkgs:
            c = core.CATEGORY_BY_ID.get(cid)
            if c:
                groups.setdefault(c.group, []).append(c)

        for group_name, cats in groups.items():
            pg = Adw.PreferencesGroup(title=group_name)
            for c in cats:
                entry = pkgs.get(c.id, {})
                pkg_list = entry.get("pacman", []) + entry.get("aur", [])
                subtitle = ", ".join(pkg_list) if pkg_list else "(sin paquetes registrados)"
                row = Adw.SwitchRow(title=c.label, subtitle=subtitle, active=True)
                self.install_switches[c.id] = row
                pg.add(row)
            content.append(pg)
        self.install_scroller.set_child(content)

    # ---------- utilidades UI ----------

    def log(self, text: str):
        def _do():
            buf = self.log_view.get_buffer()
            buf.insert(buf.get_end_iter(), text + "\n")
            self.log_view.scroll_mark_onscreen(buf.get_insert())
            return False
        GLib.idle_add(_do)

    def toast(self, text: str):
        self.toast_overlay.add_toast(Adw.Toast(title=text))

    def selected_ids(self, switches: dict[str, Adw.SwitchRow]) -> list[str]:
        return [cid for cid, row in switches.items() if row.get_active()]

    # ---------- acciones: exportar ----------

    def on_export_clicked(self, btn: Gtk.Button):
        ids = self.selected_ids(self.export_switches)
        if not ids:
            self.toast("Selecciona al menos una categoria.")
            return
        btn.set_sensitive(False)

        def work():
            selected = [core.CATEGORY_BY_ID[i] for i in ids]
            manifest = core.export_categories(selected, progress=lambda m: self.log(f"export: {m}"))

            def done():
                btn.set_sensitive(True)
                msg = f"Exportados {manifest['files_copied']} archivos en {len(ids)} categorias."
                if manifest["skipped_large_files"]:
                    msg += f" ({len(manifest['skipped_large_files'])} saltados por tamano)"
                self.log(msg)
                toast = Adw.Toast(title=msg)
                if (core.REPO / ".git").exists():
                    toast.set_button_label("Hacer commit")
                    toast.connect("button-clicked", lambda *_: self.do_commit(manifest))
                self.toast_overlay.add_toast(toast)
                self.populate_install_page()
                return False
            GLib.idle_add(done)

        threading.Thread(target=work, daemon=True).start()

    def do_commit(self, manifest: dict):
        ok, out = core.git_commit(f"export: {manifest['exported_at']} desde {manifest['host']}")
        self.log(f"git commit: {'OK' if ok else 'sin cambios / error'} — {out}")
        self.toast("Commit hecho." if ok else "Nada que commitear (o fallo).")

    # ---------- acciones: instalar ----------

    def on_install_packages_clicked(self, _btn: Gtk.Button):
        ids = self.selected_ids(self.install_switches)
        if not ids:
            self.toast("Selecciona al menos una categoria.")
            return
        pkgs = core.load_packages_toml()
        pacman_pkgs, aur_pkgs = core.plan_packages(ids, pkgs)
        if not pacman_pkgs and not aur_pkgs:
            self.toast("No hay paquetes registrados para lo seleccionado.")
            return

        term = shutil.which("kitty") or shutil.which("alacritty") or shutil.which("xterm")
        if not term:
            self.toast("No encontre un terminal (kitty/alacritty/xterm) para pedirte la contraseña de sudo.")
            return

        install_cmds = []
        if pacman_pkgs:
            install_cmds.append("sudo pacman -S --needed " + " ".join(pacman_pkgs))
        if aur_pkgs:
            helper = shutil.which("yay") or shutil.which("paru")
            if helper:
                install_cmds.append(f"{helper} -S --needed " + " ".join(aur_pkgs))
            else:
                install_cmds.append(f"echo 'Instala a mano (sin yay/paru): {' '.join(aur_pkgs)}'")
        script = " && ".join(install_cmds) + "; echo; read -p 'Pulsa Enter para cerrar...'"
        subprocess.Popen([term, "-e", "bash", "-c", script])
        self.log("Terminal abierta para instalar: " + ", ".join(pacman_pkgs + aur_pkgs))

    def on_symlink_clicked(self, btn: Gtk.Button):
        ids = self.selected_ids(self.install_switches)
        if not ids:
            self.toast("Selecciona al menos una categoria.")
            return
        btn.set_sensitive(False)

        def work():
            result = core.symlink_categories(ids, progress=lambda m: self.log(f"symlink: {m}"))

            def done():
                btn.set_sensitive(True)
                msg = f"{result['linked']} symlinks creados."
                if result["backup_dir"]:
                    msg += f" Backups previos en {result['backup_dir']}."
                self.log(msg)
                self.toast(msg)
                return False
            GLib.idle_add(done)

        threading.Thread(target=work, daemon=True).start()


class DotsApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        win = self.props.active_window or DotsWindow(self)
        win.present()


def main():
    app = DotsApp()
    app.run(sys.argv)


if __name__ == "__main__":
    main()
