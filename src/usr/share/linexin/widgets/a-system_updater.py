#!/usr/bin/env python3
import gi
import subprocess
import threading
import gettext
import locale
import os
import stat
import distro
import tempfile
import atexit
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
from gi.repository import Gtk, Adw, GLib, Gst
APP_NAME = "linexin-updater"
LOCALE_DIR = os.path.abspath("/usr/share/locale")
locale.setlocale(locale.LC_ALL, '')
locale.bindtextdomain(APP_NAME, LOCALE_DIR)
gettext.bindtextdomain(APP_NAME, LOCALE_DIR)
gettext.textdomain(APP_NAME)
_ = gettext.gettext
class SoundPlayer:
    def __init__(self):
        Gst.init(None)
        self.player = Gst.ElementFactory.make("playbin", "player")
        bus = self.player.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_bus_message)
    def play_sound(self, file_path):
        self.player.set_state(Gst.State.NULL)
        self.player.set_property("uri", f"file://{file_path}")
        self.player.set_state(Gst.State.PLAYING)
    def on_bus_message(self, bus, message):
        if message.type == Gst.MessageType.EOS:
            self.player.set_state(Gst.State.NULL)
        elif message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"Error: {err}, Debug: {debug}")
            self.player.set_state(Gst.State.NULL)
    def stop_sound(self):
        self.player.set_state(Gst.State.NULL)
class LinexInUpdaterWidget(Gtk.Box):
    def __init__(self, hide_sidebar=False, window=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.sound_player = SoundPlayer()
        self.widgetname = "System Updater"
        self.widgeticon = "/usr/share/icons/github.petexy.linexinupdater.svg"
        self.set_margin_top(12)
        self.set_margin_bottom(50)
        self.set_margin_start(12)
        self.set_margin_end(12)
        self.progress_visible = False
        self.progress_data = ""
        self.install_started = False
        self.error_message = None
        self.turn_off_after_install = False
        self.include_aur_updates = True                                  
        self.available_updates = []
        self.flatpak_updates = []
        self.aur_updates = []
        self.checking_updates = False
        self.user_password = None
        self.last_command = ""
        self.content_stack = Gtk.Stack()
        self.content_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_UP_DOWN)
        self.content_stack.set_hexpand(True)
        self.content_stack.set_vexpand(True)
        self.append(self.content_stack)
        self.setup_updates_view()
        self.setup_info_view()
        self.setup_progress_view()
        self.setup_single_widget_view()
        self.setup_controls()
        self.updates_checked = False
        self.window = window
        self.hide_sidebar = hide_sidebar
        if not self.hide_sidebar:
            self.content_stack.set_visible_child_name("updates_view")
            self.check_for_updates()
            self.updates_checked = True
        else:
            self.content_stack.set_visible_child_name("welcome_view")
            GLib.idle_add(self.resize_window_deferred)
            self.btn_install.set_sensitive(True)
    def get_header_bar_widget(self):
        """Return a header bar widget with toggle button for single widget mode"""
        if not self.hide_sidebar:
            return None                                   
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.toggle_button = Gtk.Button()
        self.toggle_button.set_tooltip_text(_("Toggle updates view"))
        self.toggle_button.connect("clicked", self.on_toggle_view_clicked)
        self.update_toggle_button()
        header_box.append(self.toggle_button)
        return header_box
    def update_toggle_button(self):
        """Update toggle button appearance based on current view"""
        if not hasattr(self, 'toggle_button'):
            return
        current_view = self.content_stack.get_visible_child_name()
        if current_view == "welcome_view":
            self.toggle_button.set_label(_("Show Updates"))
            icon = Gtk.Image.new_from_icon_name("view-list")
            self.toggle_button.set_child(icon)
            self.toggle_button.set_visible(True)
        elif current_view == "updates_view":
            self.toggle_button.set_label(_("Hide Updates"))
            icon = Gtk.Image.new_from_icon_name("go-previous")
            self.toggle_button.set_child(icon)
            self.toggle_button.set_visible(True)
        else:
            self.toggle_button.set_visible(False)
    def on_toggle_view_clicked(self, button):
        """Handle toggle button click"""
        current_view = self.content_stack.get_visible_child_name()
        if current_view == "welcome_view":
            self.content_stack.set_visible_child_name("updates_view")
            if not self.updates_checked:
                self.check_for_updates()
                self.updates_checked = True
        elif current_view == "updates_view":
            self.content_stack.set_visible_child_name("welcome_view")
        self.update_toggle_button()     
    def resize_window_deferred(self):
        """Called after widget initialization to resize window safely"""
        if self.window:
            try:
                self.window.set_default_size(600, 300)
                print("Window default size set to 1400x800")
            except Exception as e:
                print(f"Failed to resize window: {e}")
        return False
    def setup_single_widget_view(self):
        """Setup the welcome view with icon and button"""
        welcome_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        welcome_box.set_valign(Gtk.Align.CENTER)
        welcome_box.set_halign(Gtk.Align.CENTER)
        welcome_image = Gtk.Image()
        if os.path.exists("/usr/share/icons/sync.svg"):
            welcome_image.set_from_file("/usr/share/icons/sync.svg")
        else:
            welcome_image.set_from_icon_name("view-refresh")
        welcome_image.set_pixel_size(64)
        welcome_box.append(welcome_image)
        title = Gtk.Label(label=_("System Updates"))
        title.add_css_class("title-2")
        welcome_box.append(title)
        description = Gtk.Label(label=_("Press the button below to install all of the updates"))
        description.add_css_class("dim-label")
        welcome_box.append(description)
        self.content_stack.add_named(welcome_box, "welcome_view")
    def setup_updates_view(self):
        """Setup the updates view with scrollable list"""
        updates_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        updates_box.set_margin_start(30)
        updates_box.set_margin_end(30)
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header_box.set_margin_bottom(10)
        self.refresh_button = Gtk.Button()
        refresh_icon = Gtk.Image.new_from_icon_name("view-refresh")
        refresh_icon.set_margin_start(7)
        refresh_icon.set_margin_end(7)
        self.refresh_button.set_child(refresh_icon)
        self.refresh_button.set_tooltip_text(_("Refresh updates"))
        self.refresh_button.connect("clicked", self.on_refresh_clicked)
        header_box.append(self.refresh_button)
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_box.set_hexpand(True)
        self.updates_title = Gtk.Label(label=_("Available Updates"))
        self.updates_title.add_css_class("title-3")
        self.updates_title.set_halign(Gtk.Align.START)
        title_box.append(self.updates_title)
        self.updates_subtitle = Gtk.Label(label=_("Checking for updates..."))
        self.updates_subtitle.add_css_class("dim-label")
        self.updates_subtitle.set_halign(Gtk.Align.START)
        title_box.append(self.updates_subtitle)
        header_box.append(title_box)
        updates_box.append(header_box)
        self.updates_scrolled = Gtk.ScrolledWindow()
        self.updates_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.updates_scrolled.set_min_content_height(50)
        self.updates_scrolled.set_vexpand(True)
        self.updates_listbox = Gtk.ListBox()
        self.updates_listbox.add_css_class("boxed-list")
        self.updates_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.updates_scrolled.set_child(self.updates_listbox)
        updates_box.append(self.updates_scrolled)
        self.content_stack.add_named(updates_box, "updates_view")
    def setup_info_view(self):
        """Setup the info view for status messages"""
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        info_box.set_valign(Gtk.Align.CENTER)
        info_box.set_halign(Gtk.Align.CENTER)
        self.fail_image = Gtk.Image()
        if os.path.exists("/usr/share/icons/fault.svg"):
            self.fail_image.set_from_file("/usr/share/icons/fault.svg")
        else:
            self.fail_image.set_from_icon_name("dialog-error")
        self.fail_image.set_pixel_size(48)
        self.fail_image.set_visible(False)
        self.success_image = Gtk.Image()
        if os.path.exists("/usr/share/icons/confirm.svg"):
            self.success_image.set_from_file("/usr/share/icons/confirm.svg")
        else:
            self.success_image.set_from_icon_name("emblem-ok")
        self.success_image.set_pixel_size(48)
        self.success_image.set_visible(False)
        info_box.append(self.fail_image)
        info_box.append(self.success_image)
        self.info_label = Gtk.Label()
        self.info_label.set_wrap(True)
        self.info_label.set_justify(Gtk.Justification.CENTER)
        info_box.append(self.info_label)
        self.content_stack.add_named(info_box, "info_view")
    def setup_progress_view(self):
        """Setup the progress view with terminal output"""
        self.output_buffer = Gtk.TextBuffer()
        self.output_textview = Gtk.TextView.new_with_buffer(self.output_buffer)
        self.output_textview.set_wrap_mode(Gtk.WrapMode.WORD)
        self.output_textview.set_editable(False)
        self.output_textview.set_cursor_visible(False)
        self.output_textview.set_monospace(True)
        self.output_textview.set_left_margin(10)
        self.output_textview.set_right_margin(10)
        self.output_textview.set_top_margin(5)
        self.output_textview.set_bottom_margin(5)
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_child(self.output_textview)
        scrolled_window.set_min_content_height(200)
        output_frame = Gtk.Frame()
        output_frame.set_child(scrolled_window)
        self.content_stack.add_named(output_frame, "progress_view")
    def setup_controls(self):
        """Setup control buttons and options"""
        controls_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        options_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        options_box.set_halign(Gtk.Align.FILL)
        options_box.set_margin_bottom(20)
        options_box.set_margin_start(30)                             
        options_box.set_margin_end(30)                               
        options_listbox = Gtk.ListBox()
        options_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            listbox {
                background: transparent;
                border: none;
            }
            listbox > row {
                background: transparent;
                border: none;
            }
        """)
        options_listbox.get_style_context().add_provider(
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        aur_row = Adw.ActionRow()
        aur_row.set_title(_("Include AUR updates"))
        aur_row.set_subtitle(_("When disabled, the AUR helper (paru/yay) and kwin effects will be automatically rebuilt to prevent breakage"))
        self.aur_switch = Gtk.Switch()
        self.aur_switch.set_active(True)                      
        self.aur_switch.set_valign(Gtk.Align.CENTER)
        self.aur_switch.connect("notify::active", self.on_aur_toggled)
        aur_row.add_suffix(self.aur_switch)
        aur_row.set_activatable_widget(self.aur_switch)
        options_listbox.append(aur_row)
        shutdown_row = Adw.ActionRow()
        shutdown_row.set_title(_("Turn off PC after update"))
        self.shutdown_switch = Gtk.Switch()
        self.shutdown_switch.set_valign(Gtk.Align.CENTER)
        self.shutdown_switch.connect("notify::active", self.on_shutdown_toggled)
        shutdown_row.add_suffix(self.shutdown_switch)
        shutdown_row.set_activatable_widget(self.shutdown_switch)
        options_listbox.append(shutdown_row)
        options_box.append(options_listbox)
        controls_box.append(options_box)
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.CENTER)
        self.btn_install = Gtk.Button(label=_("Install Updates"))
        self.btn_install.add_css_class("suggested-action")
        self.btn_install.add_css_class("buttons_all")
        self.btn_install.connect("clicked", self.on_install_clicked)
        self.btn_install.set_sensitive(False)                      
        self.btn_toggle_progress = Gtk.Button(label=_("Show Progress"))
        self.btn_toggle_progress.set_sensitive(False)
        self.btn_toggle_progress.set_visible(False)
        self.btn_toggle_progress.add_css_class("buttons_all")
        self.btn_toggle_progress.connect("clicked", self.on_toggle_progress_clicked)
        self.btn_retry = Gtk.Button(label=_("Retry"))
        self.btn_retry.set_margin_start(30)
        self.btn_retry.add_css_class("buttons_all")
        self.btn_retry.set_visible(False)
        self.btn_retry.connect("clicked", self.on_install_clicked)
        button_box.append(self.btn_install)
        button_box.append(self.btn_toggle_progress)
        button_box.append(self.btn_retry)
        controls_box.append(button_box)
        self.append(controls_box)
    def create_update_row(self, package_name, current_version, new_version, repo=""):
        """Create a row for an update"""
        row = Gtk.ListBoxRow()
        row.set_margin_top(6)
        row.set_margin_bottom(6)
        row.set_margin_start(12)
        row.set_margin_end(12)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_box.set_hexpand(True)
        name_label = Gtk.Label(label=package_name)
        name_label.add_css_class("heading")
        name_label.set_halign(Gtk.Align.START)
        info_box.append(name_label)
        if repo:
            version_text = f"{current_version} → {new_version} ({repo})"
        else:
            version_text = f"{current_version} → {new_version}"
        version_label = Gtk.Label(label=version_text)
        version_label.add_css_class("caption")
        version_label.add_css_class("dim-label")
        version_label.set_halign(Gtk.Align.START)
        info_box.append(version_label)
        box.append(info_box)
        update_icon = Gtk.Image.new_from_icon_name("software-update-available")
        update_icon.set_pixel_size(16)
        box.append(update_icon)
        row.set_child(box)
        return row
    def on_refresh_clicked(self, button):
        """Handle refresh button click"""
        if not self.checking_updates and not self.install_started:
            self.updates_checked = False                                   
            self.check_for_updates()
            self.updates_checked = True                         
    def on_aur_toggled(self, switch, param):
        """Handle AUR toggle switch"""
        self.include_aur_updates = switch.get_active()
        self.update_displayed_updates()
    def update_displayed_updates(self):
        """Update the displayed updates list based on AUR toggle"""
        child = self.updates_listbox.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.updates_listbox.remove(child)
            child = next_child
        if self.include_aur_updates:
            total_updates = len(self.available_updates) + len(self.flatpak_updates) + len(self.aur_updates)
        else:
            total_updates = len(self.available_updates) + len(self.flatpak_updates)
        if total_updates == 0:
            self.updates_subtitle.set_text(_("System is up to date"))
            self.btn_install.set_sensitive(False)
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            box.set_margin_top(20)
            box.set_margin_bottom(20)
            box.set_halign(Gtk.Align.CENTER)
            icon = Gtk.Image.new_from_icon_name("emblem-ok")
            if os.path.exists("/usr/share/icons/confirm.svg"):
                icon.set_from_file("/usr/share/icons/confirm.svg")
            else:
                icon.set_from_icon_name("emblem-ok")            
            icon.set_pixel_size(24)
            box.append(icon)
            label = Gtk.Label(label=_("No updates available"))
            label.add_css_class("dim-label")
            box.append(label)
            row.set_child(box)
            self.updates_listbox.append(row)
        else:
            if total_updates == 1:
                self.updates_subtitle.set_text(_("1 update available"))
            else:
                self.updates_subtitle.set_text(_("{} updates available").format(total_updates))
            self.btn_install.set_sensitive(True)
            for update in self.available_updates:
                row = self.create_update_row(
                    update['name'], 
                    update['current'], 
                    update['new'], 
                    update['repo']
                )
                self.updates_listbox.append(row)
            if self.include_aur_updates:
                for update in self.aur_updates:
                    row = self.create_update_row(
                        update['name'], 
                        update['current'], 
                        update['new'], 
                        update['repo']
                    )
                    self.updates_listbox.append(row)
            for update in self.flatpak_updates:
                row = self.create_update_row(
                    update['name'], 
                    update['current'], 
                    update['new'], 
                    update['repo']
                )
                self.updates_listbox.append(row)
    def check_for_updates(self):
        """Check for available updates without root privileges"""
        if self.checking_updates:
            return
        self.checking_updates = True
        self.refresh_button.set_sensitive(False)
        self.btn_install.set_sensitive(False)
        self.updates_subtitle.set_text(_("Checking for updates..."))
        child = self.updates_listbox.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.updates_listbox.remove(child)
            child = next_child
        def check_updates():
            try:
                self.available_updates = []
                self.aur_updates = []
                self.flatpak_updates = []
                try:
                    result = subprocess.run(['checkupdates'], 
                                          capture_output=True, text=True, timeout=30, env={'LC_ALL': 'C'})
                    if result.returncode == 0 and result.stdout.strip():
                        for line in result.stdout.strip().split('\n'):
                            if ' ' in line:
                                parts = line.split()
                                if len(parts) >= 4:
                                    package = parts[0]
                                    current_version = parts[1]
                                    arrow = parts[2]                  
                                    new_version = parts[3]
                                    repo = parts[4] if len(parts) > 4 else ""
                                    self.available_updates.append({
                                        'name': package,
                                        'current': current_version,
                                        'new': new_version,
                                        'repo': repo,
                                        'type': 'pacman'
                                    })
                except (subprocess.SubprocessError, FileNotFoundError):
                    pass                                        
                try:
                    result = subprocess.run(['paru', '-Qu'], 
                                          capture_output=True, text=True, timeout=30, env={'LC_ALL': 'C'})
                    if result.returncode == 0 and result.stdout.strip():
                        for line in result.stdout.strip().split('\n'):
                            if ' ' in line:
                                parts = line.split()
                                if len(parts) >= 4:
                                    package = parts[0]
                                    current_version = parts[1]
                                    arrow = parts[2] 
                                    new_version = parts[3]
                                    repo = parts[4] if len(parts) > 4 else ""
                                    is_duplicate = any(pkg['name'] == package for pkg in self.available_updates)
                                    if not is_duplicate:
                                        self.aur_updates.append({
                                            'name': package,
                                            'current': current_version,
                                            'new': new_version,
                                            'repo': repo if repo else "AUR",
                                            'type': 'AUR'
                                        })
                except (subprocess.SubprocessError, FileNotFoundError):
                    pass                                        
                try:
                    all_flatpak_updates = []
                    seen_ids = set()
                    def get_updates_for_scope(scope_flag, scope_name):
                        updates = []
                        try:
                            remotes_cmd = ['flatpak', 'remotes', scope_flag, '--columns=name']
                            res = subprocess.run(remotes_cmd, capture_output=True, text=True, timeout=10, env={'LC_ALL': 'C'})
                            if res.returncode != 0:
                                return updates
                            remotes = [r.strip() for r in res.stdout.strip().split('\n') if r.strip()]
                            for remote in remotes:
                                try:
                                    cmd = ['flatpak', 'remote-ls', scope_flag, '--updates', '--columns=ref,version', remote]
                                    r_res = subprocess.run(cmd, capture_output=True, text=True, timeout=15, env={'LC_ALL': 'C'})
                                    if r_res.returncode == 0 and r_res.stdout.strip():
                                        for line in r_res.stdout.strip().split('\n'):
                                            parts = line.split()
                                            if len(parts) >= 1:
                                                ref = parts[0]
                                                version = parts[1] if len(parts) > 1 else ""
                                                ref_parts = ref.split('/')
                                                if len(ref_parts) >= 4:
                                                    app_id = ref_parts[1]
                                                    branch = ref_parts[3]
                                                    updates.append({
                                                        'name': app_id.split('.')[-1] if '.' in app_id else app_id,
                                                        'current': _("installed"),
                                                        'new': version if version else _("new version"),
                                                        'repo': f"{remote} ({scope_name})",
                                                        'app_id': app_id,
                                                        'type': 'flatpak'
                                                    })
                                except Exception:
                                    continue                              
                        except Exception:
                            pass
                        return updates
                    sys_ups = get_updates_for_scope('--system', 'system')
                    for up in sys_ups:
                        if up['app_id'] not in seen_ids:
                            all_flatpak_updates.append(up)
                            seen_ids.add(up['app_id'])
                    user_ups = get_updates_for_scope('--user', 'user')
                    for up in user_ups:
                        if up['app_id'] not in seen_ids:
                            all_flatpak_updates.append(up)
                            seen_ids.add(up['app_id'])
                    self.flatpak_updates = all_flatpak_updates
                except Exception as e:
                    print(f"Flatpak check error: {e}")
            except Exception as e:
                GLib.idle_add(self.on_update_check_error, str(e))
                return
            GLib.idle_add(self.on_updates_checked)
        threading.Thread(target=check_updates, daemon=True).start()
    def on_updates_checked(self):
        """Handle completion of update check"""
        self.checking_updates = False
        self.refresh_button.set_sensitive(True)
        self.update_displayed_updates()
        return False
    def on_update_check_error(self, error_msg):
        """Handle update check error"""
        self.checking_updates = False
        self.refresh_button.set_sensitive(True)
        self.updates_subtitle.set_text(_("Error checking updates"))
        self.btn_install.set_sensitive(False)
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        box.set_halign(Gtk.Align.CENTER)
        icon = Gtk.Image.new_from_icon_name("dialog-error")
        icon.set_pixel_size(24)
        box.append(icon)
        label = Gtk.Label(label=_("Failed to check for updates"))
        label.add_css_class("error")
        box.append(label)
        row.set_child(box)
        self.updates_listbox.append(row)
        return False
    def get_aur_helper_rebuild_command(self):
        """Check if AUR helper needs to be rebuilt (returns True/False)"""
        try:
            result = subprocess.run(['pacman', '-Q', 'paru'], capture_output=True, text=True)
            if result.returncode == 0:
                return True
            result = subprocess.run(['pacman', '-Q', 'yay'], capture_output=True, text=True)
            if result.returncode == 0:
                return True
        except:
            pass
        return False
    def get_kwin_effects_rebuild_command(self):
        """Check if kwin is being updated and return package names that need rebuilding"""
        kwin_update = False
        for update in self.available_updates:
            if 'kwin' in update.get('name', '').lower():
                kwin_update = True
                break
        if not kwin_update:
            return ""
        rebuild_packages = []
        try:
            result = subprocess.run(['pacman', '-Q', 'kwin-effects-glass-git'], capture_output=True, text=True)
            if result.returncode == 0:
                rebuild_packages.append('kwin-effects-glass-git')
        except:
            pass
        try:
            result = subprocess.run(['pacman', '-Q', 'kwin-effect-rounded-corners-git'], capture_output=True, text=True)
            if result.returncode == 0:
                rebuild_packages.append('kwin-effect-rounded-corners-git')
        except:
            pass
        if not rebuild_packages:
            return ""
        return ' '.join(rebuild_packages)
    def on_shutdown_toggled(self, switch, param):
        """Handle shutdown toggle switch"""
        self.turn_off_after_install = switch.get_active()
    def prompt_for_password(self):
        """Prompt user for sudo password using Adw.MessageDialog"""
        root = self.get_root()
        if not root:
            root = self.window
        dialog = Adw.MessageDialog(
            heading=_("Authentication Required"),
            body=_("Please enter your password to proceed with the system update."),
            transient_for=root
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("unlock", _("Unlock"))
        dialog.set_response_appearance("unlock", Adw.ResponseAppearance.SUGGESTED)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        entry = Gtk.PasswordEntry()
        entry.set_property("placeholder-text", _("Password"))
        box.append(entry)
        dialog.set_extra_child(box)
        def on_response(dialog, response):
            if response == "unlock":
                pwd = entry.get_text()
                if pwd:
                    self.user_password = pwd
                    self.on_install_clicked(None)
            dialog.close()
        dialog.connect("response", on_response)
        def on_entry_activate(widget):
            dialog.response("unlock")
        entry.connect("activate", on_entry_activate)
        dialog.present()
    def validate_password(self):
        """Validate the sudo password using sudo -S"""
        if not self.user_password:
            return False
        if sudo_manager.validate_password(self.user_password):
            sudo_manager.set_password(self.user_password)
            return True
        else:
            return False
    def on_install_clicked(self, button):
        """Handle install button click"""
        if not self.user_password:
            self.prompt_for_password()
            return
        if not self.validate_password():
            self.user_password = None
            root = self.get_root() or self.window
            dialog = Adw.MessageDialog(
                heading=_("Authentication Failed"),
                body=_("The password you entered is incorrect. Please try again."),
                transient_for=root
            )
            dialog.add_response("ok", _("OK"))
            dialog.set_response_appearance("ok", Adw.ResponseAppearance.DEFAULT)
            dialog.connect("response", lambda d, r: d.close())
            dialog.present()
            return
        product_name = distro.name()
        self.btn_retry.set_visible(False)
        priv_cmd = sudo_manager.wrapper_path
        if self.include_aur_updates:
            kwin_effects_packages = self.get_kwin_effects_rebuild_command()
            command = f"echo Updating {product_name}... && paru -Syu --noconfirm --overwrite '*' --sudo '{priv_cmd}' && flatpak update --assumeyes"
            if kwin_effects_packages:
                command += f" && echo 'Rebuilding kwin effects to relink against new kwin...' && paru -S --overwrite '*' --rebuild --noconfirm --sudo '{priv_cmd}' {kwin_effects_packages}"
        else:
            aur_helper_rebuild = self.get_aur_helper_rebuild_command()
            kwin_effects_packages = self.get_kwin_effects_rebuild_command()
            privileged_cmds = f"{priv_cmd} pacman -Syu --noconfirm --overwrite '*'"
            if aur_helper_rebuild:
                privileged_cmds += f" && echo 'Reinstalling paru to relink against new libalpm...' && {priv_cmd} pacman -S --noconfirm paru"
            command = f"echo Updating {product_name}... && sh -c '{privileged_cmds}'"
            command += " && flatpak update --assumeyes"
            if kwin_effects_packages:
                command += f" && echo 'Rebuilding kwin effects to relink against new kwin...' && paru -S --overwrite '*' --rebuild --noconfirm --sudo '{priv_cmd}' {kwin_effects_packages}"
        self.begin_install(command, product_name)
    def begin_install(self, command, product_name):
        """Start the installation process"""
        self.install_started = True
        self.btn_install.set_sensitive(False)
        self.aur_switch.set_sensitive(False)
        self.shutdown_switch.set_sensitive(False)
        self.btn_install.set_visible(False)
        self.btn_toggle_progress.set_sensitive(True)
        self.btn_toggle_progress.set_visible(True)
        self.current_product = product_name
        self.error_message = None
        self.fail_image.set_visible(False)
        self.success_image.set_visible(False)
        self.info_label.set_markup(f'<span size="large" weight="bold">{_("Updating {}...").format(self.current_product)}</span>')
        self.content_stack.set_visible_child_name("info_view")
        self.progress_data = ""
        self.progress_visible = False
        self.btn_toggle_progress.set_label(_("Show Progress"))
        self.output_buffer.set_text("")
        self.last_command = command
        self.retry_in_progress = False
        self.detected_alpm_error = False
        self.run_shell_command(command)
    def on_toggle_progress_clicked(self, button):
        """Handle progress toggle button"""
        self.progress_visible = not self.progress_visible
        if self.progress_visible:
            self.btn_toggle_progress.set_label(_("Hide Progress"))
            self.output_buffer.set_text(self.progress_data or _("[console output]"))
            self.content_stack.set_visible_child_name("progress_view")
            GLib.timeout_add(50, self.scroll_to_end)
        else:
            self.btn_toggle_progress.set_label(_("Show Progress"))
            self.content_stack.set_visible_child_name("info_view")
    def append_to_log(self, text):
        """Append text to output buffer and scroll"""
        if self.progress_visible:
            end_iter = self.output_buffer.get_end_iter()
            self.output_buffer.insert(end_iter, text)
            mark = self.output_buffer.create_mark(None, end_iter, False)
            self.output_textview.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)
        return False
    def run_shell_command(self, command):
        """Execute shell command in a separate thread"""
        def stream_output():
            if sudo_manager:
                sudo_manager.start_privileged_session()
            try:
                env = sudo_manager.get_env()
                env['PACMAN_AUTH'] = sudo_manager.wrapper_path
                process = subprocess.Popen(command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    env=env                              
                )
                for line in iter(process.stdout.readline, ''):
                    if line:
                        if "error while loading shared libraries: libalpm.so" in line:
                            self.detected_alpm_error = True
                        self.progress_data += line
                        GLib.idle_add(self.append_to_log, line)
                process.stdout.close()
                return_code = process.wait()
                if return_code != 0:
                    self.error_message = _("Process exited with code {}").format(return_code)
            except Exception as e:
                self.error_message = str(e)
                self.progress_data += _("\nError: {}").format(e)
                GLib.idle_add(self.append_to_log, _("\nError: {}").format(e))
            GLib.idle_add(self.finish_installation)
        threading.Thread(target=stream_output, daemon=True).start()
    def update_output_buffer(self, text):
        """Update the output buffer with new text"""
        if self.progress_visible:
            self.output_buffer.set_text(text)
            GLib.idle_add(self.scroll_to_end)
        return False
    def scroll_to_end(self):
        """Scroll text view to the end"""
        end_iter = self.output_buffer.get_end_iter()
        self.output_textview.scroll_to_iter(end_iter, 0.0, False, 0.0, 0.0)
        return False
    def finish_installation(self):
        """Handle installation completion"""
        if sudo_manager:
             sudo_manager.stop_privileged_session()
        
        if self.error_message and self.detected_alpm_error and not self.retry_in_progress:
            self.retry_in_progress = True
            self.error_message = None                                        
            self.detected_alpm_error = False                  
            repair_msg = f"\n\n{_('--- DETECTED BROKEN PARU: Compiling fresh source from AUR... ---')}\n"
            self.progress_data += repair_msg
            self.append_to_log(repair_msg)
            priv = sudo_manager.wrapper_path
            repair_cmd = (
                "rm -rf /tmp/paru_repair && "
                "mkdir -p /tmp/paru_repair && "
                "cd /tmp/paru_repair && "
                "echo 'Downloading paru source from AUR...' && "
                "wget -qO paru.tar.gz https://aur.archlinux.org/cgit/aur.git/snapshot/paru.tar.gz && "
                "echo 'Extracting...' && "
                "tar -xzf paru.tar.gz && "
                "cd paru && "
                "echo 'Compiling paru from source (this may take a while)...' && "
                "makepkg --noconfirm && "
                "echo 'Removing old conflicting packages...' && "
                f"{priv} sh -c 'pacman -Rdd --noconfirm paru paru-bin paru-debug paru-bin-debug 2>/dev/null || true; pacman -U --noconfirm --overwrite \"*\" *.pkg.tar.zst'"
            )
            retry_cmd = f"{repair_cmd} && echo '--- Repair complete, retrying system update... ---' && {self.last_command}"
            self.run_shell_command(retry_cmd)
            return False
        if sudo_manager:
            sudo_manager.forget_password()
        self.install_started = False
        self.btn_install.set_sensitive(True)
        self.aur_switch.set_sensitive(True)
        self.shutdown_switch.set_sensitive(True)
        self.btn_install.set_visible(True)
        self.btn_toggle_progress.set_sensitive(True)
        if self.error_message:
            self.info_label.set_markup(f'<span color="#e01b24" weight="bold" size="large">{_("Installation failed: ")}</span>\n{self.error_message}')
            self.sound_player.play_sound("/usr/share/linexin/widgets/sounds/fail.ogg")
            self.fail_image.set_visible(True)
            self.btn_retry.set_visible(True)
            self.btn_retry.add_css_class("suggested-action")
            self.btn_install.set_visible(False)
            if hasattr(self, 'toggle_button'):
                self.toggle_button.set_visible(False)
        else:
            self.info_label.set_markup(f'<span color="#2ec27e" weight="bold" size="large">{_("Successfully updated your {}!").format(self.current_product)}</span>')
            self.sound_player.play_sound("/usr/share/linexin/widgets/sounds/confirm.ogg")
            self.success_image.set_visible(True)
            self.btn_retry.remove_css_class("suggested-action")
            GLib.timeout_add_seconds(2, self.return_to_updates_and_refresh)
            if self.turn_off_after_install:
                command = "shutdown now"
                product_name = "shutdown"
                self.begin_install(command, product_name)
        self.content_stack.set_visible_child_name("info_view")
        self.progress_visible = False
        self.btn_toggle_progress.set_label(_("Show Progress"))
        return False
    def return_to_updates_and_refresh(self):
        """Return to updates view and refresh the list"""
        self.content_stack.set_visible_child_name("updates_view")
        self.check_for_updates()
        return False
