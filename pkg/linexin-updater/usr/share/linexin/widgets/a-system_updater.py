#!/usr/bin/env python3

import gi
import subprocess
import threading
import gettext
import locale
import os
import distro

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")

from gi.repository import Gtk, Adw, GLib, Gst


# --- Localization Setup ---
APP_NAME = "linexin-updater"
LOCALE_DIR = os.path.abspath("/usr/share/locale")

# Set up the locale environment
locale.setlocale(locale.LC_ALL, '')
locale.bindtextdomain(APP_NAME, LOCALE_DIR)
gettext.bindtextdomain(APP_NAME, LOCALE_DIR)
gettext.textdomain(APP_NAME)
_ = gettext.gettext
# --------------------------


class SoundPlayer:
    def __init__(self):
        # Initialize GStreamer
        Gst.init(None)
        
        # Create a playbin pipeline
        self.player = Gst.ElementFactory.make("playbin", "player")
        
        # Connect to the bus to handle end-of-stream messages
        bus = self.player.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_bus_message)
        
    def play_sound(self, file_path):
        # Reset pipeline to NULL state first
        self.player.set_state(Gst.State.NULL)
        
        # Set the URI for the sound file
        self.player.set_property("uri", f"file://{file_path}")
        
        # Start playing
        self.player.set_state(Gst.State.PLAYING)
        
    def on_bus_message(self, bus, message):
        if message.type == Gst.MessageType.EOS:
            # End of stream - reset to NULL state
            self.player.set_state(Gst.State.NULL)
        elif message.type == Gst.MessageType.ERROR:
            # Handle errors
            err, debug = message.parse_error()
            print(f"Error: {err}, Debug: {debug}")
            self.player.set_state(Gst.State.NULL)
        
    def stop_sound(self):
        self.player.set_state(Gst.State.NULL)



class LinexInUpdaterWidget(Gtk.Box):
    def __init__(self, hide_sidebar=False, window=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        
        # Sound initialization
        self.sound_player = SoundPlayer()

        # Required: Widget display name
        self.widgetname = "System Updater"
        
        # Optional: Widget icon
        self.widgeticon = "/usr/share/icons/github.petexy.linexinupdater.svg"
        
        # Widget content
        self.set_margin_top(12)
        self.set_margin_bottom(50)
        self.set_margin_start(12)
        self.set_margin_end(12)
        
        # Initialize state variables
        self.progress_visible = False
        self.progress_data = ""
        self.install_started = False
        self.error_message = None
        self.turn_off_after_install = False
        self.include_aur_updates = True  # AUR updates enabled by default
        self.available_updates = []
        self.flatpak_updates = []
        self.aur_updates = []
        self.checking_updates = False
        
        # Create main content stack
        self.content_stack = Gtk.Stack()
        self.content_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_UP_DOWN)
        self.content_stack.set_hexpand(True)
        self.content_stack.set_vexpand(True)
        self.append(self.content_stack)
        
        # Setup different views
        self.setup_updates_view()
        self.setup_info_view()
        self.setup_progress_view()
        self.setup_single_widget_view()
        
        # Controls section
        self.setup_controls()
        
        # Set initial view and check for updates
        
        self.updates_checked = False


        self.window = window
        self.hide_sidebar = hide_sidebar

        if not self.hide_sidebar:
            self.content_stack.set_visible_child_name("updates_view")
            # Check for updates only in sidebar mode
            self.check_for_updates()
            self.updates_checked = True
        else:
            # Single widget mode - don't check updates initially
            self.content_stack.set_visible_child_name("welcome_view")
            GLib.idle_add(self.resize_window_deferred)
            self.btn_install.set_sensitive(True)

    def get_header_bar_widget(self):
        """Return a header bar widget with toggle button for single widget mode"""
        if not self.hide_sidebar:
            return None  # Only show in single widget mode
        
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        # Toggle button to switch between welcome and updates view
        self.toggle_button = Gtk.Button()
        self.toggle_button.set_tooltip_text(_("Toggle updates view"))
        self.toggle_button.connect("clicked", self.on_toggle_view_clicked)
        
        # Update button appearance based on current view
        self.update_toggle_button()
        
        header_box.append(self.toggle_button)
        return header_box

    def update_toggle_button(self):
        """Update toggle button appearance based on current view"""
        if not hasattr(self, 'toggle_button'):
            return
            
        current_view = self.content_stack.get_visible_child_name()
        
        if current_view == "welcome_view":
            # Show "Show Updates" button
            self.toggle_button.set_label(_("Show Updates"))
            icon = Gtk.Image.new_from_icon_name("view-list")
            self.toggle_button.set_child(icon)
            self.toggle_button.set_visible(True)
        elif current_view == "updates_view":
            # Show "Hide Updates" button  
            self.toggle_button.set_label(_("Hide Updates"))
            icon = Gtk.Image.new_from_icon_name("go-previous")
            self.toggle_button.set_child(icon)
            self.toggle_button.set_visible(True)
        else:
            # Hide button for other views
            self.toggle_button.set_visible(False)

    def on_toggle_view_clicked(self, button):
        """Handle toggle button click"""
        current_view = self.content_stack.get_visible_child_name()
        
        if current_view == "welcome_view":
            # Switch to updates view
            self.content_stack.set_visible_child_name("updates_view")
            # Check for updates only when first switching to updates view
            if not self.updates_checked:
                self.check_for_updates()
                self.updates_checked = True
        elif current_view == "updates_view":
            # Switch back to welcome view
            self.content_stack.set_visible_child_name("welcome_view")
        
        # Update button appearance
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
        
        # Welcome icon
        welcome_image = Gtk.Image()
        if os.path.exists("/usr/share/icons/sync.svg"):
            welcome_image.set_from_file("/usr/share/icons/sync.svg")
        else:
            welcome_image.set_from_icon_name("view-refresh")
        welcome_image.set_pixel_size(64)
        welcome_box.append(welcome_image)
        
        # Title
        title = Gtk.Label(label=_("System Updates"))
        title.add_css_class("title-2")
        welcome_box.append(title)
        
        # Description
        description = Gtk.Label(label=_("Press the button below to install all of the updates"))
        description.add_css_class("dim-label")
        welcome_box.append(description)
        
        self.content_stack.add_named(welcome_box, "welcome_view")

    def setup_updates_view(self):
        """Setup the updates view with scrollable list"""
        updates_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        updates_box.set_margin_start(30)
        updates_box.set_margin_end(30)

        # Header
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header_box.set_margin_bottom(10)
        
        # Refresh button
        self.refresh_button = Gtk.Button()
        refresh_icon = Gtk.Image.new_from_icon_name("view-refresh")
        refresh_icon.set_margin_start(7)
        refresh_icon.set_margin_end(7)
        self.refresh_button.set_child(refresh_icon)
        self.refresh_button.set_tooltip_text(_("Refresh updates"))
        self.refresh_button.connect("clicked", self.on_refresh_clicked)
        header_box.append(self.refresh_button)
        
        # Title and status
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
        
        # Scrollable updates list
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
        
        # Status images
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
        
        # Status label
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
        
        # Options container
        options_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        options_box.set_halign(Gtk.Align.CENTER)
        options_box.set_margin_bottom(20)
        
        # AUR updates option
        aur_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        aur_box.set_halign(Gtk.Align.CENTER)
        
        aur_label = Gtk.Label(label=_("Include AUR updates"))
        self.aur_switch = Gtk.Switch()
        self.aur_switch.set_active(True)  # Checked by default
        self.aur_switch.connect("notify::active", self.on_aur_toggled)
        
        aur_box.append(aur_label)
        aur_box.append(self.aur_switch)
        options_box.append(aur_box)
        
        # Shutdown option
        shutdown_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        shutdown_box.set_halign(Gtk.Align.CENTER)
        
        shutdown_label = Gtk.Label(label=_("Turn off PC after update"))
        self.shutdown_switch = Gtk.Switch()
        self.shutdown_switch.connect("notify::active", self.on_shutdown_toggled)
        
        shutdown_box.append(shutdown_label)
        shutdown_box.append(self.shutdown_switch)
        options_box.append(shutdown_box)
        
        controls_box.append(options_box)
        
        # Action buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.CENTER)
        
        self.btn_install = Gtk.Button(label=_("Install Updates"))
        self.btn_install.add_css_class("suggested-action")
        self.btn_install.add_css_class("buttons_all")
        self.btn_install.connect("clicked", self.on_install_clicked)
        self.btn_install.set_sensitive(False)  # Initially disabled
        
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
        
        # Package info
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
        
        # Update icon
        update_icon = Gtk.Image.new_from_icon_name("software-update-available")
        update_icon.set_pixel_size(16)
        box.append(update_icon)
        
        row.set_child(box)
        return row
    
    def on_refresh_clicked(self, button):
        """Handle refresh button click"""
        if not self.checking_updates and not self.install_started:
            self.updates_checked = False  # Reset flag to allow fresh check
            self.check_for_updates()
            self.updates_checked = True   # Set flag after check

    def on_aur_toggled(self, switch, param):
        """Handle AUR toggle switch"""
        self.include_aur_updates = switch.get_active()
        # Update the displayed updates list
        self.update_displayed_updates()
    
    def update_displayed_updates(self):
        """Update the displayed updates list based on AUR toggle"""
        # Clear existing updates
        child = self.updates_listbox.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.updates_listbox.remove(child)
            child = next_child
        
        # Calculate total updates based on AUR setting
        if self.include_aur_updates:
            total_updates = len(self.available_updates) + len(self.flatpak_updates) + len(self.aur_updates)
        else:
            total_updates = len(self.available_updates) + len(self.flatpak_updates)
        
        if total_updates == 0:
            self.updates_subtitle.set_text(_("System is up to date"))
            self.btn_install.set_sensitive(False)
            
            # Show "no updates" row
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
            
            # Add pacman updates
            for update in self.available_updates:
                row = self.create_update_row(
                    update['name'], 
                    update['current'], 
                    update['new'], 
                    update['repo']
                )
                self.updates_listbox.append(row)
            
            # Add AUR updates only if enabled
            if self.include_aur_updates:
                for update in self.aur_updates:
                    row = self.create_update_row(
                        update['name'], 
                        update['current'], 
                        update['new'], 
                        update['repo']
                    )
                    self.updates_listbox.append(row)

            # Add flatpak updates
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
        
        # Clear existing updates
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
                
                # Check pacman updates
                try:
                    result = subprocess.run(['checkupdates'], 
                                          capture_output=True, text=True, timeout=30)
                    if result.returncode == 0 and result.stdout.strip():
                        for line in result.stdout.strip().split('\n'):
                            if ' ' in line:
                                parts = line.split()
                                if len(parts) >= 4:
                                    package = parts[0]
                                    current_version = parts[1]
                                    arrow = parts[2]  # Should be '->'
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
                    pass  # checkupdates not available or failed
                
                try:
                    result = subprocess.run(['paru', '-Qu'], 
                                          capture_output=True, text=True, timeout=30)
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
                                    
                                    self.aur_updates.append({
                                        'name': package,
                                        'current': current_version,
                                        'new': new_version,
                                        'repo': repo,
                                        'type': 'AUR'
                                    })
                except (subprocess.SubprocessError, FileNotFoundError):
                    pass  # checkupdates not available or failed

                # Check flatpak updates
                try:
                    result = subprocess.run(['flatpak', 'remote-ls', '--updates'], 
                                          capture_output=True, text=True, timeout=30)
                    if result.returncode == 0 and result.stdout.strip():
                        for line in result.stdout.strip().split('\n'):
                            parts = line.split('\t')
                            if len(parts) >= 3:
                                app_id = parts[0]
                                version = parts[1]
                                branch = parts[2]
                                
                                self.flatpak_updates.append({
                                    'name': app_id.split('.')[-1] if '.' in app_id else app_id,
                                    'current': _("installed"),
                                    'new': version,
                                    'repo': f"flatpak ({branch})",
                                    'type': 'flatpak'
                                })
                except (subprocess.SubprocessError, FileNotFoundError):
                    pass  # flatpak not available or failed
                
            except Exception as e:
                GLib.idle_add(self.on_update_check_error, str(e))
                return
            
            GLib.idle_add(self.on_updates_checked)
        
        threading.Thread(target=check_updates, daemon=True).start()
    
    def on_updates_checked(self):
        """Handle completion of update check"""
        self.checking_updates = False
        self.refresh_button.set_sensitive(True)
        
        # Use the common method to display updates
        self.update_displayed_updates()
        
        return False
    
    def on_update_check_error(self, error_msg):
        """Handle update check error"""
        self.checking_updates = False
        self.refresh_button.set_sensitive(True)
        self.updates_subtitle.set_text(_("Error checking updates"))
        self.btn_install.set_sensitive(False)
        
        # Show error row
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
    
    def on_shutdown_toggled(self, switch, param):
        """Handle shutdown toggle switch"""
        self.turn_off_after_install = switch.get_active()
    
    def on_install_clicked(self, button):
        """Handle install button click"""
        product_name = distro.name()
        self.btn_retry.set_visible(False)
        
        # Choose command based on AUR toggle
        if self.include_aur_updates:
            command = f"echo Updating {product_name}... && paru -Syu --noconfirm --sudo run0 && flatpak update --assumeyes"
        else:
            command = f"echo Updating {product_name}... && run0 pacman -Syu --noconfirm && flatpak update --assumeyes"
        
        self.begin_install(command, product_name)
    
    def begin_install(self, command, product_name):
        """Start the installation process"""
        self.install_started = True
        self.btn_install.set_sensitive(False)
        self.btn_install.set_visible(False)
        self.btn_toggle_progress.set_sensitive(True)
        self.btn_toggle_progress.set_visible(True)
        self.current_product = product_name
        self.error_message = None
        
        # Reset images
        self.fail_image.set_visible(False)
        self.success_image.set_visible(False)
        
        self.info_label.set_markup(f'<span size="large" weight="bold">{_("Updating {}...").format(self.current_product)}</span>')
        self.content_stack.set_visible_child_name("info_view")
        
        self.progress_data = ""
        self.progress_visible = False
        self.btn_toggle_progress.set_label(_("Show Progress"))
        self.output_buffer.set_text("")
        
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
    
    def run_shell_command(self, command):
        """Execute shell command in a separate thread"""
        def stream_output():
            try:
                process = subprocess.Popen(command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    errors='replace'
                )
                
                for line in iter(process.stdout.readline, ''):
                    if line:
                        self.progress_data += line
                        GLib.idle_add(self.update_output_buffer, self.progress_data)
                
                process.stdout.close()
                return_code = process.wait()
                if return_code != 0:
                    self.error_message = _("Process exited with code {}").format(return_code)
            except Exception as e:
                self.error_message = str(e)
                self.progress_data += _("\nError: {}").format(e)
                GLib.idle_add(self.update_output_buffer, self.progress_data)
            
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
        self.install_started = False
        self.btn_install.set_sensitive(True)
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
            
            # Refresh the updates list after successful installation
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
