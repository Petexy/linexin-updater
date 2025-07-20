#!/usr/bin/env python3

import gi
import subprocess
import threading

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_default_size(500, 250)
        self.set_title("Linexin Updater")

        style_manager = Adw.StyleManager.get_default()

        self.output_buffer = []
        self.is_running = False

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        header_bar = Adw.HeaderBar()
        header_bar.set_show_end_title_buttons(True)
        main_box.append(header_bar)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(12)
        content_box.set_margin_start(12)
        content_box.set_margin_end(12)
        content_box.set_vexpand(True)

        self.warning_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.warning_box.set_halign(Gtk.Align.CENTER)
        self.warning_box.set_valign(Gtk.Align.CENTER)
        self.warning_box.set_visible(False)
        content_box.append(self.warning_box)

        self.warning_label_line1 = Gtk.Label(label="The update is in progress...")
        self.warning_label_line1.set_halign(Gtk.Align.CENTER)
        self.warning_label_line1.set_valign(Gtk.Align.CENTER)
        self.warning_box.append(self.warning_label_line1)

        self.warning_label_line2 = Gtk.Label()
        self.warning_label_line2.set_halign(Gtk.Align.CENTER)
        self.warning_label_line2.set_valign(Gtk.Align.CENTER)
        self.warning_label_line2.set_markup(
            '<span foreground="red" weight="bold">Do NOT close the app!</span>'
        )
        self.warning_box.append(self.warning_label_line2)

        # Status label (shown after update finishes)
        self.status_label = Gtk.Label()
        self.status_label.set_halign(Gtk.Align.CENTER)
        self.status_label.set_valign(Gtk.Align.CENTER)
        self.status_label.set_visible(False)
        content_box.append(self.status_label)

        self.text_view = Gtk.TextView()
        self.text_view.set_editable(False)
        self.text_view.set_monospace(True)
        self.text_view.set_visible(False)

        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_child(self.text_view)
        scrolled_window.set_vexpand(True)
        scrolled_window.set_hexpand(True)
        scrolled_window.set_visible(False)

        self.scrolled_window = scrolled_window
        content_box.append(self.scrolled_window)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        content_box.append(spacer)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_hexpand(True)
        content_box.append(button_box)

        self.update_button = Gtk.Button(label="Run System Update")
        self.update_button.add_css_class("suggested-action")
        self.update_button.connect("clicked", self.on_update_button_clicked)
        button_box.append(self.update_button)

        self.show_progress_button = Gtk.Button(label="Show progress")
        self.show_progress_button.set_sensitive(False)
        self.show_progress_button.connect("clicked", self.on_toggle_progress_clicked)
        button_box.append(self.show_progress_button)

        main_box.append(content_box)
        self.set_content(main_box)

    def on_update_button_clicked(self, button):
        self.update_button.set_sensitive(False)
        self.show_progress_button.set_sensitive(True)

        self.output_buffer.clear()
        self.text_view.get_buffer().set_text("")

        self.text_view.set_visible(False)
        self.scrolled_window.set_visible(False)
        self.show_progress_button.set_label("Show progress")

        self.status_label.set_visible(False)  # Hide old status
        self.is_running = True
        self.update_warning_visibility()

        threading.Thread(target=self.run_update_command, daemon=True).start()

    def on_toggle_progress_clicked(self, button):
        if self.text_view.get_visible():
            self.text_view.set_visible(False)
            self.scrolled_window.set_visible(False)
            self.show_progress_button.set_label("Show progress")
        else:
            self.text_view.set_visible(True)
            self.scrolled_window.set_visible(True)
            self.show_progress_button.set_label("Hide progress")

            buffer = self.text_view.get_buffer()
            buffer.set_text("\n".join(self.output_buffer))

            end_iter = buffer.get_end_iter()
            self.text_view.scroll_to_iter(end_iter, 0.0, False, 0.0, 0.0)

        self.update_warning_visibility()

    def run_update_command(self):
        return_code = -1
        try:
            process = subprocess.Popen(
                "run0 pacman -Syu --noconfirm && flatpak update",
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )

            while True:
                output = process.stdout.readline()
                if output == "" and process.poll() is not None:
                    break
                if output:
                    line = output.strip()
                    self.output_buffer.append(line)
                    GLib.idle_add(self.append_output_if_visible, line)

            return_code = process.poll()
            if return_code == 0:
                self.output_buffer.append("Update completed successfully.")
                GLib.idle_add(self.append_output_if_visible, "Update completed successfully.")
            else:
                error_line = f"Update failed with return code {return_code}."
                self.output_buffer.append(error_line)
                GLib.idle_add(self.append_output_if_visible, error_line)

        except Exception as e:
            error_line = f"Error: {str(e)}"
            self.output_buffer.append(error_line)
            GLib.idle_add(self.append_output_if_visible, error_line)
        finally:
            self.is_running = False

            def finish_update_ui():
                self.update_button.set_sensitive(True)
                self.update_warning_visibility()

                self.status_label.set_visible(True)
                if return_code == 0:
                    self.status_label.set_markup('<span foreground="green">✅ Update completed successfully.</span>')
                else:
                    self.status_label.set_markup(f'<span foreground="red">❌ Update failed (code {return_code}).</span>')

            GLib.idle_add(finish_update_ui)

    def append_output_if_visible(self, text):
        if self.text_view.get_visible():
            buffer = self.text_view.get_buffer()
            end_iter = buffer.get_end_iter()
            buffer.insert(end_iter, text + "\n")
            self.text_view.scroll_to_iter(end_iter, 0.0, False, 0.0, 0.0)

    def update_warning_visibility(self):
        should_show = self.is_running and not self.text_view.get_visible()
        self.warning_box.set_visible(should_show)

class MyApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="github.petexy.linexinupdater")
        self.connect("activate", self.on_activate)

    def on_activate(self, app):
        window = MainWindow(self)
        window.present()

def main():
    app = MyApp()
    app.run()

if __name__ == "__main__":
    main()

