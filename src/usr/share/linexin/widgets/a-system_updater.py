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
import datetime
import re
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
from gi.repository import Gtk, Adw, GLib, Gst
import importlib.util
APP_NAME = "linexin-updater"
WIDE_LAYOUT_THRESHOLD = 800
WIDE_LAYOUT_SIDE_PADDING = 12
LEFT_PANE_MIN_WIDTH = 300
LAYOUT_ANIMATION_DURATION = 350
CRITICAL_PACKAGE_PREFIXES = (
    'linux', 'glibc', 'systemd', 'grub', 'mkinitcpio', 'nvidia',
    'mesa', 'xorg-server', 'wayland', 'efibootmgr', 'fwupd',
    'plasma-desktop', 'kwin', 'sddm', 'gdm', 'lightdm',
    'nvidia-open', 'nvidia-dkms', 'nvidia-lts', 'linux-lts', 'linux-hardened',
    'linux-zen', 'linux-rt', 'linux-amd-staging', 'linux-ck', 'linux-xanmod',
)

# --- Set to False for official/release builds ---
DEBUG_MODE = False

def load_translations():
    """Load translation dictionary based on system locale"""
    try:
        # Get language from environment
        lang = os.environ.get('LANG', 'en_US').split('.')[0]
        # Allow override/check other vars
        if not lang or lang == 'C':
             lang = 'en_US'
             
        # Locate dictionary file relative to this script
        base_dir = os.path.dirname(os.path.abspath(__file__))
        loc_file = os.path.join(base_dir, "localization", lang, "system_updater_dictionary.py")
        
        if os.path.exists(loc_file):
            spec = importlib.util.spec_from_file_location("start_dict", loc_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return getattr(mod, "translations", {})
    except Exception as e:
        print(f"Translation load error: {e}")
    return {}

TRANSLATIONS = load_translations()

def _(text):
    """Translate text using loaded dictionary"""
    return TRANSLATIONS.get(text, text)
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
        self.window = window
        self.hide_sidebar = hide_sidebar
        self.available_updates = []
        self.flatpak_updates = []
        self.aur_updates = []
        self.wide_layout_enabled = None
        self.last_measured_width = 0
        self.checking_updates = False
        self.user_password = None
        self.last_command = ""
        self.main_layout_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.main_layout_box.set_hexpand(True)
        self.main_layout_box.set_vexpand(True)
        self.compact_layout_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.compact_layout_box.set_hexpand(True)
        self.compact_layout_box.set_vexpand(True)
        self.wide_paned = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        self.wide_paned.set_hexpand(True)
        self.wide_paned.set_vexpand(True)
        self.wide_paned.set_resize_start_child(True)
        self.wide_paned.set_shrink_start_child(False)
        self.wide_paned.set_resize_end_child(False)
        self.wide_paned.set_shrink_end_child(False)
        self.controls_revealer = Gtk.Revealer()
        self.controls_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self.controls_revealer.set_transition_duration(LAYOUT_ANIMATION_DURATION)
        self.controls_revealer.set_reveal_child(True)
        self.content_stack = Gtk.Stack()
        self.content_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_UP_DOWN)
        self.content_stack.set_hexpand(True)
        self.content_stack.set_vexpand(True)
        self.append(self.main_layout_box)
        self.setup_updates_view()
        self.setup_info_view()
        self.setup_progress_view()
        self.setup_single_widget_view()
        self.setup_controls()
        self.update_adaptive_layout(force=True)
        GLib.timeout_add(200, self.monitor_adaptive_layout)
        self.updates_checked = False
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
                print("Window default size set to 600x300")
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
        self.updates_warnings_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.updates_warnings_box.set_margin_top(4)
        self.updates_warnings_revealer = Gtk.Revealer()
        self.updates_warnings_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self.updates_warnings_revealer.set_transition_duration(300)
        self.updates_warnings_revealer.set_reveal_child(False)
        self.updates_warnings_revealer.set_child(self.updates_warnings_box)
        updates_box.append(self.updates_warnings_revealer)
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
        self.install_progress_bar = Gtk.ProgressBar()
        self.install_progress_bar.set_show_text(True)
        self.install_progress_bar.set_hexpand(True)
        self.install_progress_bar.set_visible(False)
        info_box.append(self.install_progress_bar)
        self.install_status_label = Gtk.Label()
        self.install_status_label.set_wrap(True)
        self.install_status_label.set_justify(Gtk.Justification.CENTER)
        self.install_status_label.add_css_class("dim-label")
        self.install_status_label.add_css_class("caption")
        self.install_status_label.set_visible(False)
        info_box.append(self.install_status_label)
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
        controls_box.set_hexpand(True)
        controls_box.set_valign(Gtk.Align.END)
        self.controls_box = controls_box
        options_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        options_box.set_halign(Gtk.Align.FILL)
        options_box.set_margin_bottom(20)
        options_box.set_margin_start(30)                             
        options_box.set_margin_end(30)
        self.options_box = options_box                               
        options_listbox = Gtk.ListBox()
        options_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        options_listbox.add_css_class("boxed-list")
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
        button_box.set_halign(Gtk.Align.FILL)
        button_box.set_margin_start(30)
        button_box.set_margin_end(30)
        self.button_box = button_box
        self.btn_install = Gtk.Button(label=_("Install Updates"))
        self.btn_install.set_hexpand(True)
        self.btn_install.add_css_class("suggested-action")
        self.btn_install.add_css_class("buttons_all")
        self.btn_install.connect("clicked", self.on_install_clicked)
        self.btn_install.set_sensitive(False)                      
        self.btn_toggle_progress = Gtk.Button(label=_("Show Progress"))
        self.btn_toggle_progress.set_hexpand(True)
        self.btn_toggle_progress.set_sensitive(False)
        self.btn_toggle_progress.set_visible(False)
        self.btn_toggle_progress.add_css_class("buttons_all")
        self.btn_toggle_progress.connect("clicked", self.on_toggle_progress_clicked)
        self.btn_retry = Gtk.Button(label=_("Retry"))
        self.btn_retry.set_hexpand(True)
        self.btn_retry.set_margin_start(30)
        self.btn_retry.add_css_class("buttons_all")
        self.btn_retry.set_visible(False)
        self.btn_retry.connect("clicked", self.on_install_clicked)
        button_box.append(self.btn_install)
        button_box.append(self.btn_toggle_progress)
        button_box.append(self.btn_retry)
        if DEBUG_MODE:
            self.btn_debug_kwin = Gtk.Button(label="[DBG] Rebuild KWin Effects")
            self.btn_debug_kwin.add_css_class("destructive-action")
            self.btn_debug_kwin.add_css_class("buttons_all")
            self.btn_debug_kwin.connect("clicked", self.on_debug_rebuild_kwin_clicked)
            button_box.append(self.btn_debug_kwin)
        controls_box.append(button_box)
        self.controls_box = controls_box
        GLib.idle_add(self.update_controls_min_width)
        self.setup_info_panel()

    def setup_info_panel(self):
        """Setup the wide-mode info panel shown above controls in the right pane."""
        self.info_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.info_panel.set_vexpand(True)

        self._row_selected_handler_id = None

        self.info_panel_stack = Gtk.Stack()
        self.info_panel_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.info_panel_stack.set_transition_duration(200)
        self.info_panel_stack.set_vexpand(True)

        # --- Default view: update summary + system stats + warnings ---
        default_scroll = Gtk.ScrolledWindow()
        default_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        default_scroll.set_vexpand(True)

        default_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        default_box.set_valign(Gtk.Align.CENTER)
        default_box.set_halign(Gtk.Align.FILL)
        default_box.set_margin_top(12)
        default_box.set_margin_bottom(12)
        default_box.set_margin_start(WIDE_LAYOUT_SIDE_PADDING)
        default_box.set_margin_end(WIDE_LAYOUT_SIDE_PADDING)

        # Update summary section
        summary_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        summary_box.set_halign(Gtk.Align.CENTER)

        summary_icon = Gtk.Image.new_from_icon_name("software-update-available-symbolic")
        summary_icon.set_pixel_size(48)
        summary_icon.add_css_class("dim-label")
        summary_box.append(summary_icon)

        self.summary_title_label = Gtk.Label(label=_("No updates"))
        self.summary_title_label.add_css_class("title-2")
        summary_box.append(self.summary_title_label)

        self.summary_breakdown_label = Gtk.Label(label="")
        self.summary_breakdown_label.add_css_class("dim-label")
        self.summary_breakdown_label.set_wrap(True)
        self.summary_breakdown_label.set_justify(Gtk.Justification.CENTER)
        summary_box.append(self.summary_breakdown_label)

        # Warnings section — moved to the left pane (updates_warnings_box)
        self.warnings_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.warnings_box.set_visible(False)  # unused placeholder

        default_box.append(summary_box)

        # System stats rows
        stats_frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        stats_list = Gtk.ListBox()
        stats_list.set_selection_mode(Gtk.SelectionMode.NONE)
        stats_list.add_css_class("boxed-list")

        self.stats_last_update_row = Adw.ActionRow()
        self.stats_last_update_row.set_icon_name("emblem-default-symbolic")
        self.stats_last_update_row.set_title(_("Last updated"))
        self.stats_last_update_row.set_subtitle(_("Unknown"))
        stats_list.append(self.stats_last_update_row)

        self.stats_packages_row = Adw.ActionRow()
        self.stats_packages_row.set_icon_name("package-x-generic-symbolic")
        self.stats_packages_row.set_title(_("Installed packages"))
        self.stats_packages_row.set_subtitle("")
        stats_list.append(self.stats_packages_row)

        self.stats_download_size_row = Adw.ActionRow()
        self.stats_download_size_row.set_icon_name("folder-download-symbolic")
        self.stats_download_size_row.set_title(_("Download size"))
        self.stats_download_size_row.set_subtitle(_("Calculating..."))
        self.stats_download_size_row.set_visible(False)
        stats_list.append(self.stats_download_size_row)

        stats_frame.append(stats_list)
        default_box.append(stats_frame)

        # Hint label
        hint_label = Gtk.Label(label=_("Select a package for details"))
        hint_label.add_css_class("dim-label")
        hint_label.add_css_class("caption")
        hint_label.set_margin_top(4)
        default_box.append(hint_label)

        default_scroll.set_child(default_box)
        self.info_panel_stack.add_named(default_scroll, "default")

        # --- Package detail view ---
        detail_scroll = Gtk.ScrolledWindow()
        detail_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        detail_scroll.set_vexpand(True)

        detail_outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        detail_outer.set_margin_top(8)
        detail_outer.set_margin_bottom(12)
        detail_outer.set_margin_start(WIDE_LAYOUT_SIDE_PADDING)
        detail_outer.set_margin_end(WIDE_LAYOUT_SIDE_PADDING)

        # Header with back button and package name
        detail_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        detail_header.set_valign(Gtk.Align.START)

        back_btn = Gtk.Button()
        back_btn.set_valign(Gtk.Align.CENTER)
        back_btn.set_icon_name("go-previous-symbolic")
        back_btn.set_tooltip_text(_("Back to overview"))
        back_btn.add_css_class("flat")
        back_btn.connect("clicked", lambda b: self.show_info_panel_default())
        detail_header.append(back_btn)

        self.detail_name_label = Gtk.Label()
        self.detail_name_label.set_halign(Gtk.Align.START)
        self.detail_name_label.set_hexpand(True)
        self.detail_name_label.add_css_class("title-2")
        self.detail_name_label.set_wrap(True)
        detail_header.append(self.detail_name_label)

        detail_outer.append(detail_header)

        # Detail fields in a boxed list
        self.detail_list = Gtk.ListBox()
        self.detail_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.detail_list.add_css_class("boxed-list")
        detail_outer.append(self.detail_list)

        # Warning banner area
        self.detail_warning_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        detail_outer.append(self.detail_warning_box)

        detail_scroll.set_child(detail_outer)
        self.info_panel_stack.add_named(detail_scroll, "detail")

        # --- Updating view ---
        updating_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        updating_box.set_valign(Gtk.Align.CENTER)
        updating_box.set_halign(Gtk.Align.CENTER)
        updating_box.set_margin_start(WIDE_LAYOUT_SIDE_PADDING)
        updating_box.set_margin_end(WIDE_LAYOUT_SIDE_PADDING)

        updating_spinner = Gtk.Spinner()
        updating_spinner.set_size_request(48, 48)
        updating_spinner.start()
        updating_box.append(updating_spinner)

        self.updating_label = Gtk.Label()
        self.updating_label.add_css_class("title-2")
        self.updating_label.set_wrap(True)
        self.updating_label.set_justify(Gtk.Justification.CENTER)
        updating_box.append(self.updating_label)

        self.updating_sublabel = Gtk.Label(label=_("Please wait..."))
        self.updating_sublabel.add_css_class("dim-label")
        updating_box.append(self.updating_sublabel)

        self.info_panel_stack.add_named(updating_box, "updating")

        self.info_panel.append(self.info_panel_stack)

    def get_last_update_time(self):
        """Get the last system update time from pacman log."""
        try:
            result = subprocess.run(
                ['grep', '-a', 'starting full system upgrade', '/var/log/pacman.log'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                last_line = result.stdout.strip().splitlines()[-1]
                timestamp = last_line.split(']')[0].lstrip('[').strip()
                dt = datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S%z")
                now = datetime.datetime.now(datetime.timezone.utc)
                delta = now - dt
                if delta.days == 0:
                    return _("Today")
                elif delta.days == 1:
                    return _("Yesterday")
                else:
                    return _("{} days ago").format(delta.days)
        except Exception:
            pass
        return _("Unknown")

    def get_installed_package_count(self):
        """Get the number of installed pacman and flatpak packages."""
        pacman_count = None
        flatpak_count = None
        try:
            result = subprocess.run(
                ['pacman', '-Q'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                pacman_count = len(result.stdout.strip().splitlines())
        except Exception:
            pass
        try:
            result = subprocess.run(
                ['flatpak', 'list', '--app'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                flatpak_count = len([l for l in result.stdout.strip().splitlines() if l.strip()])
        except Exception:
            pass
        if pacman_count is not None and flatpak_count:
            return f"{pacman_count} {_('System')} + {flatpak_count} Flatpak"
        elif pacman_count is not None:
            return str(pacman_count)
        return ""

    def get_download_size(self):
        """Return total download size for pending pacman/AUR updates as a formatted string, or None."""
        pkg_names = [u['name'] for u in self.available_updates]
        if self.include_aur_updates:
            pkg_names += [u['name'] for u in self.aur_updates]
        if not pkg_names:
            return None
        try:
            result = subprocess.run(
                ['pacman', '-Si'] + pkg_names,
                capture_output=True, text=True, timeout=20,
                env={**os.environ, 'LC_ALL': 'C'}
            )
            total_bytes = 0.0
            for line in result.stdout.splitlines():
                if line.startswith('Download Size'):
                    _, _, rest = line.partition(':')
                    parts = rest.strip().split()
                    if len(parts) >= 2:
                        try:
                            value = float(parts[0])
                            unit = parts[1]
                            if unit in ('KiB',):
                                total_bytes += value * 1024
                            elif unit in ('MiB',):
                                total_bytes += value * 1024 * 1024
                            elif unit in ('GiB',):
                                total_bytes += value * 1024 * 1024 * 1024
                            else:  # bytes
                                total_bytes += value
                        except ValueError:
                            pass
            if total_bytes <= 0:
                return None
            mb = total_bytes / (1024 * 1024)
            if mb < 1:
                return f"{total_bytes / 1024:.1f} KB"
            elif mb < 1024:
                return f"{mb:.1f} MB"
            else:
                return f"{mb / 1024:.2f} GB"
        except Exception:
            return None

    def get_critical_updates(self):
        """Return list of critical/core packages found in pending updates."""
        critical = []
        all_updates = self.available_updates + self.aur_updates
        for update in all_updates:
            name = update.get('name', '').lower()
            for prefix in CRITICAL_PACKAGE_PREFIXES:
                if name == prefix or name.startswith(prefix + '-') or name.startswith(prefix):
                    critical.append(update)
                    break
        return critical

    def refresh_info_panel(self):
        """Update the info panel with current system stats and warnings."""
        if not hasattr(self, 'info_panel'):
            return

        def _load_stats():
            last_update = self.get_last_update_time()
            pkg_count = self.get_installed_package_count()
            # Only run the slow pacman -Si query when the package list is final
            download_size = None if self.checking_updates else self.get_download_size()
            GLib.idle_add(self._apply_info_panel_stats, last_update, pkg_count, download_size)

        threading.Thread(target=_load_stats, daemon=True).start()

    def _apply_info_panel_stats(self, last_update, pkg_count, download_size=None, still_checking=False):
        """Apply loaded stats to the info panel (must run on main thread)."""
        self.stats_last_update_row.set_subtitle(last_update)
        self.stats_packages_row.set_subtitle(pkg_count if pkg_count else _("Unknown"))
        # Re-read checking_updates live — avoids stale snapshots from earlier closures
        if self.checking_updates:
            self.stats_download_size_row.set_subtitle(_("Calculating..."))
            self.stats_download_size_row.set_visible(True)
        elif download_size:
            self.stats_download_size_row.set_subtitle(download_size)
            self.stats_download_size_row.set_visible(True)
        else:
            self.stats_download_size_row.set_visible(False)

        # Update summary
        all_updates = list(self.available_updates)
        if self.include_aur_updates:
            all_updates += list(self.aur_updates)
        all_updates += list(self.flatpak_updates)
        total = len(all_updates)

        if total == 0:
            self.summary_title_label.set_text(_("System is up to date"))
        elif total == 1:
            self.summary_title_label.set_text(_("1 update available"))
        else:
            self.summary_title_label.set_text(_("{} updates available").format(total))

        parts = []
        if self.available_updates:
            parts.append(_("{} system").format(len(self.available_updates)))
        if self.include_aur_updates and self.aur_updates:
            parts.append(_("{} AUR").format(len(self.aur_updates)))
        if self.flatpak_updates:
            parts.append(_("{} Flatpak").format(len(self.flatpak_updates)))
        self.summary_breakdown_label.set_text(", ".join(parts) if parts else "")
        self.summary_breakdown_label.set_visible(bool(parts))

        self._refresh_warnings()

    def _refresh_warnings(self):
        """Rebuild the warnings section below the updates list (visible in both layouts)."""
        child = self.updates_warnings_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.updates_warnings_box.remove(child)
            child = nxt

        critical = self.get_critical_updates()
        if not critical:
            self.updates_warnings_revealer.set_reveal_child(False)
            return

        warn_frame = Gtk.Frame()
        warn_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        warn_inner.set_margin_top(10)
        warn_inner.set_margin_bottom(10)
        warn_inner.set_margin_start(12)
        warn_inner.set_margin_end(12)

        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        warn_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        warn_icon.set_pixel_size(16)
        title_row.append(warn_icon)
        header = Gtk.Label(label=_("Core component updates"))
        header.add_css_class("heading")
        title_row.append(header)
        warn_inner.append(title_row)

        subtitle = Gtk.Label(label=_("A reboot may be required after updating"))
        subtitle.set_halign(Gtk.Align.START)
        subtitle.add_css_class("dim-label")
        subtitle.add_css_class("caption")
        subtitle.set_wrap(True)
        warn_inner.append(subtitle)

        for update in critical:
            lbl = Gtk.Label(label=f"{update['name']}  {update['current']} → {update['new']}")
            lbl.set_halign(Gtk.Align.START)
            lbl.add_css_class("caption")
            lbl.set_margin_start(24)
            lbl.set_wrap(True)
            warn_inner.append(lbl)

        warn_frame.set_child(warn_inner)
        self.updates_warnings_box.append(warn_frame)
        self.updates_warnings_revealer.set_reveal_child(True)

    def show_info_panel_default(self):
        """Switch the info panel back to the default stats/warnings view."""
        self.info_panel_stack.set_visible_child_name("default")
        if self.wide_layout_enabled:
            self.updates_listbox.unselect_all()

    def show_package_detail(self, update_data):
        """Show package detail in the info panel."""
        self.detail_name_label.set_text(update_data.get('name', ''))

        # Clear detail list
        while True:
            row = self.detail_list.get_row_at_index(0)
            if row is None:
                break
            self.detail_list.remove(row)

        fields = [
            (_("Current version"), update_data.get('current', ''), "document-edit-symbolic"),
            (_("New version"), update_data.get('new', ''), "emblem-ok-symbolic"),
            (_("Repository"), update_data.get('repo', ''), "folder-remote-symbolic"),
            (_("Type"), update_data.get('type', ''), "application-x-addon-symbolic"),
        ]
        if 'app_id' in update_data:
            fields.append((_("Application ID"), update_data['app_id'], "application-x-executable-symbolic"))

        for title, value, icon_name in fields:
            if not value:
                continue
            row = Adw.ActionRow()
            row.set_title(title)
            row.set_subtitle(value)
            row.set_icon_name(icon_name)
            row.set_subtitle_selectable(True)
            self.detail_list.append(row)

        # Warning banner
        child = self.detail_warning_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.detail_warning_box.remove(child)
            child = nxt

        name_lower = update_data.get('name', '').lower()
        is_critical = any(
            name_lower == p or name_lower.startswith(p + '-') or name_lower.startswith(p)
            for p in CRITICAL_PACKAGE_PREFIXES
        )
        if is_critical:
            banner_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            banner_box.set_margin_top(4)
            warn_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
            warn_icon.set_pixel_size(16)
            banner_box.append(warn_icon)
            warn_lbl = Gtk.Label(label=_("Core component — a reboot may be required"))
            warn_lbl.add_css_class("caption")
            warn_lbl.set_wrap(True)
            banner_box.append(warn_lbl)
            self.detail_warning_box.append(banner_box)

        self.info_panel_stack.set_visible_child_name("detail")

    def on_update_row_selected(self, listbox, row):
        """Handle row selection in the updates list (wide mode only)."""
        if not self.wide_layout_enabled or row is None:
            return
        idx = row.get_index()
        all_updates = list(self.available_updates)
        if self.include_aur_updates:
            all_updates += list(self.aur_updates)
        all_updates += list(self.flatpak_updates)
        if 0 <= idx < len(all_updates):
            self.show_package_detail(all_updates[idx])

    def get_controls_min_width(self):
        """Measure the minimum width needed for the right-side controls pane"""
        minimum, natural, _, _ = self.btn_install.measure(Gtk.Orientation.HORIZONTAL, -1)
        button_width = max(minimum, natural)
        return button_width + (WIDE_LAYOUT_SIDE_PADDING * 2)

    def update_controls_min_width(self):
        """Keep the controls pane at least slightly wider than the install button"""
        # Always use get_controls_min_width() to be consistent with Paned constraints
        self.controls_box.set_size_request(self.get_controls_min_width(), -1)
        return False

    def clear_box_children(self, box):
        """Remove all children from a Gtk.Box"""
        child = box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            box.remove(child)
            child = next_child

    def detach_widget_from_parent(self, widget):
        """Detach a widget from its current parent so it can be reparented"""
        parent = widget.get_parent()
        if not parent:
            return
        if isinstance(parent, Gtk.Revealer):
            parent.set_child(None)
            return
        if isinstance(parent, Gtk.Box):
            parent.remove(widget)
            return
        if isinstance(parent, Gtk.Paned):
            if parent.get_start_child() == widget:
                parent.set_start_child(None)
            elif parent.get_end_child() == widget:
                parent.set_end_child(None)

    def monitor_adaptive_layout(self):
        """Refresh the layout when the allocated widget width changes"""
        width = self.get_width()
        if width <= 0 and self.window:
            width = self.window.get_width()
        if width > 0 and width != self.last_measured_width:
            self.last_measured_width = width
            self.update_adaptive_layout(current_width=width)
        return True

    def update_adaptive_layout(self, force=False, current_width=None):
        """Switch between stacked and split layout depending on the widget width"""
        width = current_width if current_width is not None else self.get_width()
        if width <= 0 and self.window:
            width = self.window.get_width()
        right_min_width = self.get_controls_min_width()
        use_wide_layout = width > WIDE_LAYOUT_THRESHOLD if width > 0 else False
        if not force and use_wide_layout == self.wide_layout_enabled:
            return False
        # Cancel any running layout animation
        if hasattr(self, '_layout_anim') and self._layout_anim is not None:
            self._layout_anim.skip()
            self._layout_anim = None
        previous_layout = self.wide_layout_enabled
        self.wide_layout_enabled = use_wide_layout
        self.update_controls_min_width()
        if use_wide_layout:
            self.set_margin_start(0)
            self.set_margin_end(0)
            self.content_stack.set_margin_start(12)
            self.content_stack.set_margin_end(WIDE_LAYOUT_SIDE_PADDING)
            self.content_stack.set_size_request(LEFT_PANE_MIN_WIDTH, -1)
            self.controls_box.set_margin_start(WIDE_LAYOUT_SIDE_PADDING)
            self.controls_box.set_margin_end(WIDE_LAYOUT_SIDE_PADDING)
            self.options_box.set_margin_start(WIDE_LAYOUT_SIDE_PADDING)
            self.options_box.set_margin_end(WIDE_LAYOUT_SIDE_PADDING)
            self.button_box.set_margin_start(WIDE_LAYOUT_SIDE_PADDING)
            self.button_box.set_margin_end(WIDE_LAYOUT_SIDE_PADDING)
            self.button_box.set_orientation(Gtk.Orientation.VERTICAL)
            self.controls_box.set_valign(Gtk.Align.FILL)
            self.controls_box.prepend(self.info_panel)
            self.info_panel.set_visible(True)
            self.updates_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
            if self._row_selected_handler_id is None:
                self._row_selected_handler_id = self.updates_listbox.connect(
                    "row-selected", self.on_update_row_selected
                )
            self.show_info_panel_default()
            self.refresh_info_panel()
        elif previous_layout is None or force:
            # Only apply compact margins immediately for initial layout or forced refresh.
            # For animated transitions, defer to _finish_compact_transition.
            self.set_margin_start(12)
            self.set_margin_end(12)
            self.content_stack.set_margin_start(0)
            self.content_stack.set_margin_end(0)
            self.content_stack.set_size_request(-1, -1)
            self.controls_box.set_margin_start(0)
            self.controls_box.set_margin_end(0)
            self.options_box.set_margin_start(30)
            self.options_box.set_margin_end(30)
            self.button_box.set_margin_start(30)
            self.button_box.set_margin_end(30)
            self.button_box.set_orientation(Gtk.Orientation.HORIZONTAL)
            self._remove_info_panel_from_controls()
        if use_wide_layout:
            # --- Transition TO wide layout ---
            controls_height = self.controls_box.get_height()
            self.detach_widget_from_parent(self.content_stack)
            self.detach_widget_from_parent(self.controls_box)
            self.clear_box_children(self.main_layout_box)
            target_position = max(0, min(width - right_min_width, int(width * 0.68)))
            self.wide_paned.set_start_child(self.content_stack)
            self.wide_paned.set_end_child(self.controls_box)
            self.main_layout_box.append(self.wide_paned)
            if previous_layout is not None and not force:
                self.controls_box.set_size_request(0, -1)
                self.wide_paned.set_shrink_end_child(True)
                self.wide_paned.set_position(width)
                # Use margin_bottom to visually shrink the content area to its old height,
                # then animate the margin away so the list grows smoothly.
                initial_margin = controls_height + 12
                self.content_stack.set_margin_bottom(initial_margin)
                self._start_layout_animation(
                    width, target_position,
                    initial_margin, 0,
                    on_done=self._restore_after_wide_anim
                )
            else:
                self.wide_paned.set_position(target_position)
        else:
            # --- Transition TO compact layout ---
            if previous_layout is True and not force:
                self.controls_box.set_size_request(0, -1)
                self.wide_paned.set_shrink_end_child(True)
                self._start_layout_animation(
                    self.wide_paned.get_position(), width,
                    0, 0,
                    on_done=self._finish_compact_transition
                )
            else:
                self._apply_compact_layout()
        return False

    def _start_layout_animation(self, paned_from, paned_to, margin_from, margin_to, on_done=None):
        """Animate paned position and content margin_bottom together using a 0→1 progress value."""
        self._anim_paned_from = paned_from
        self._anim_paned_to = paned_to
        self._anim_margin_from = margin_from
        self._anim_margin_to = margin_to
        target = Adw.CallbackAnimationTarget.new(self._on_layout_anim_tick)
        anim = Adw.TimedAnimation.new(
            self.wide_paned, 0.0, 1.0,
            LAYOUT_ANIMATION_DURATION, target
        )
        anim.set_easing(Adw.Easing.EASE_OUT_CUBIC)
        if on_done:
            anim.connect("done", lambda a: on_done())
        self._layout_anim = anim
        anim.play()

    def _on_layout_anim_tick(self, progress):
        """Interpolate both paned position and content margin each frame."""
        paned_pos = self._anim_paned_from + (self._anim_paned_to - self._anim_paned_from) * progress
        margin = self._anim_margin_from + (self._anim_margin_to - self._anim_margin_from) * progress
        self.wide_paned.set_position(int(paned_pos))
        self.content_stack.set_margin_bottom(int(margin))

    def _restore_after_wide_anim(self):
        """Remove temporary constraints after the expand animation."""
        self._layout_anim = None
        self.content_stack.set_margin_bottom(0)
        self.wide_paned.set_shrink_end_child(False)
        self.update_controls_min_width()

    def _finish_compact_transition(self):
        """Switch to compact layout after the collapse animation."""
        self._layout_anim = None
        self.content_stack.set_margin_bottom(0)
        self.wide_paned.set_shrink_end_child(False)
        self.update_controls_min_width()
        # Apply compact margins only after animation finishes to avoid window resize.
        self.set_margin_start(12)
        self.set_margin_end(12)
        self.content_stack.set_margin_start(0)
        self.content_stack.set_margin_end(0)
        self.content_stack.set_size_request(-1, -1)
        self.controls_box.set_margin_start(0)
        self.controls_box.set_margin_end(0)
        self.options_box.set_margin_start(30)
        self.options_box.set_margin_end(30)
        self.button_box.set_margin_start(30)
        self.button_box.set_margin_end(30)
        self.button_box.set_orientation(Gtk.Orientation.HORIZONTAL)
        self._remove_info_panel_from_controls()
        self._apply_compact_layout(animated=True)

    def _apply_compact_layout(self, animated=False):
        """Reparent widgets into the compact (stacked) layout."""
        self.detach_widget_from_parent(self.content_stack)
        self.detach_widget_from_parent(self.controls_box)
        self.clear_box_children(self.main_layout_box)
        self.clear_box_children(self.compact_layout_box)
        self.controls_revealer.set_child(self.controls_box)
        if animated:
            self.controls_revealer.set_reveal_child(False)
        else:
            self.controls_revealer.set_reveal_child(True)
        self.compact_layout_box.append(self.content_stack)
        self.compact_layout_box.append(self.controls_revealer)
        self.main_layout_box.append(self.compact_layout_box)
        if animated:
            GLib.idle_add(self.controls_revealer.set_reveal_child, True)

    def _remove_info_panel_from_controls(self):
        """Remove the info panel from controls_box and restore compact valign."""
        if self.info_panel.get_parent() == self.controls_box:
            self.controls_box.remove(self.info_panel)
        self.controls_box.set_valign(Gtk.Align.END)
        self.updates_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        if self._row_selected_handler_id is not None:
            self.updates_listbox.disconnect(self._row_selected_handler_id)
            self._row_selected_handler_id = None

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
            row.set_vexpand(True)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            box.set_valign(Gtk.Align.CENTER)
            box.set_halign(Gtk.Align.CENTER)
            box.set_vexpand(True)
            icon = Gtk.Image.new_from_icon_name("emblem-ok")
            if os.path.exists("/usr/share/icons/confirm.svg"):
                icon.set_from_file("/usr/share/icons/confirm.svg")
            else:
                icon.set_from_icon_name("emblem-ok")            
            icon.set_pixel_size(48)
            box.append(icon)
            label = Gtk.Label(label=_("No updates available"))
            label.add_css_class("title-3")
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
        if self.wide_layout_enabled:
            self.refresh_info_panel()
    def check_for_updates(self):
        """Check for available updates without root privileges"""
        if self.checking_updates:
            return
        self.checking_updates = True
        self.refresh_button.set_sensitive(False)
        self.btn_install.set_sensitive(False)
        self.updates_subtitle.set_text(_("Checking for updates..."))
        if hasattr(self, 'stats_download_size_row'):
            self.stats_download_size_row.set_subtitle(_("Calculating..."))
            self.stats_download_size_row.set_visible(True)
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
                ignored_pkgs = set()
                try:
                    with open('/etc/pacman.conf', 'r') as f:
                        for cline in f:
                            cline = cline.strip()
                            if cline.startswith('IgnorePkg'):
                                _, _, value = cline.partition('=')
                                ignored_pkgs.update(value.strip().split())
                except Exception:
                    pass
                try:
                    result = subprocess.run(['checkupdates'], 
                                          capture_output=True, text=True, timeout=30, env={**os.environ, 'LC_ALL': 'C'})
                    if result.returncode == 0 and result.stdout.strip():
                        for line in result.stdout.strip().split('\n'):
                            if ' ' in line:
                                parts = line.split()
                                if len(parts) >= 4:
                                    package = parts[0]
                                    if package in ignored_pkgs:
                                        continue
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
                                          capture_output=True, text=True, timeout=30, env={**os.environ, 'LC_ALL': 'C'})
                    if result.returncode == 0 and result.stdout.strip():
                        for line in result.stdout.strip().split('\n'):
                            if ' ' in line:
                                parts = line.split()
                                if len(parts) >= 4:
                                    package = parts[0]
                                    if package in ignored_pkgs:
                                        continue
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
                            res = subprocess.run(remotes_cmd, capture_output=True, text=True, timeout=10, env={**os.environ, 'LC_ALL': 'C'})
                            if res.returncode != 0:
                                return updates
                            remotes = [r.strip() for r in res.stdout.strip().split('\n') if r.strip()]
                            for remote in remotes:
                                try:
                                    cmd = ['flatpak', 'remote-ls', scope_flag, '--updates', '--columns=ref,version', remote]
                                    r_res = subprocess.run(cmd, capture_output=True, text=True, timeout=15, env={**os.environ, 'LC_ALL': 'C'})
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
    def get_kwin_effects_rebuild_command(self, priv_cmd):
        """Check if kwin or plasma is being updated and return a shell command to rebuild effects from source"""
        kwin_update = False
        for update in self.available_updates + self.aur_updates:
            name = update.get('name', '').lower()
            if 'kwin' in name or name.startswith('plasma-'):
                kwin_update = True
                break
        if not kwin_update:
            return ""
        rebuild_cmds = []
        try:
            result = subprocess.run(['pacman', '-Q', 'kwin-effects-glass-git'], capture_output=True, text=True)
            if result.returncode == 0:
                rebuild_cmds.append(
                    "echo 'Rebuilding kwin-effects-glass from source...' && "
                    "rm -rf /tmp/_kwin_glass_build && "
                    "git clone --depth 1 https://github.com/4v3ngR/kwin-effects-glass /tmp/_kwin_glass_build && "
                    "cmake -B /tmp/_kwin_glass_build/build -S /tmp/_kwin_glass_build -DCMAKE_INSTALL_PREFIX=/usr && "
                    "cmake --build /tmp/_kwin_glass_build/build && "
                    f"{priv_cmd} cmake --install /tmp/_kwin_glass_build/build && "
                    "rm -rf /tmp/_kwin_glass_build"
                )
        except:
            pass
        try:
            result = subprocess.run(['pacman', '-Q', 'kwin-effect-rounded-corners-git'], capture_output=True, text=True)
            if result.returncode == 0:
                rebuild_cmds.append(
                    "echo 'Rebuilding KDE-Rounded-Corners from source...' && "
                    "rm -rf /tmp/_kwin_rounded_build && "
                    "git clone --depth 1 https://github.com/matinlotfali/KDE-Rounded-Corners /tmp/_kwin_rounded_build && "
                    "cmake -B /tmp/_kwin_rounded_build/build -S /tmp/_kwin_rounded_build -DCMAKE_INSTALL_PREFIX=/usr && "
                    "cmake --build /tmp/_kwin_rounded_build/build && "
                    f"{priv_cmd} cmake --install /tmp/_kwin_rounded_build/build && "
                    "rm -rf /tmp/_kwin_rounded_build"
                )
        except:
            pass
        if not rebuild_cmds:
            return ""
        return " && ".join(rebuild_cmds)
    def _get_kwin_effects_force_rebuild_command(self, priv_cmd):
        """Return the rebuild-from-source command for all installed kwin effects, unconditionally."""
        rebuild_cmds = []
        try:
            result = subprocess.run(['pacman', '-Q', 'kwin-effects-glass-git'], capture_output=True, text=True)
            if result.returncode == 0:
                rebuild_cmds.append(
                    "echo 'Rebuilding kwin-effects-glass from source...' && "
                    "rm -rf /tmp/_kwin_glass_build && "
                    "git clone --depth 1 https://github.com/4v3ngR/kwin-effects-glass /tmp/_kwin_glass_build && "
                    "cmake -B /tmp/_kwin_glass_build/build -S /tmp/_kwin_glass_build -DCMAKE_INSTALL_PREFIX=/usr && "
                    "cmake --build /tmp/_kwin_glass_build/build && "
                    f"{priv_cmd} cmake --install /tmp/_kwin_glass_build/build && "
                    "rm -rf /tmp/_kwin_glass_build"
                )
        except:
            pass
        try:
            result = subprocess.run(['pacman', '-Q', 'kwin-effect-rounded-corners-git'], capture_output=True, text=True)
            if result.returncode == 0:
                rebuild_cmds.append(
                    "echo 'Rebuilding KDE-Rounded-Corners from source...' && "
                    "rm -rf /tmp/_kwin_rounded_build && "
                    "git clone --depth 1 https://github.com/matinlotfali/KDE-Rounded-Corners /tmp/_kwin_rounded_build && "
                    "cmake -B /tmp/_kwin_rounded_build/build -S /tmp/_kwin_rounded_build -DCMAKE_INSTALL_PREFIX=/usr && "
                    "cmake --build /tmp/_kwin_rounded_build/build && "
                    f"{priv_cmd} cmake --install /tmp/_kwin_rounded_build/build && "
                    "rm -rf /tmp/_kwin_rounded_build"
                )
        except:
            pass
        if not rebuild_cmds:
            return ""
        return " && ".join(rebuild_cmds)

    def on_debug_rebuild_kwin_clicked(self, button):
        """[DEBUG] Force-rebuild kwin effects from source, regardless of pending updates."""
        if not self.user_password:
            self.prompt_for_password(callback=self.on_debug_rebuild_kwin_clicked)
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
            translate_dialog(dialog)
            dialog.present()
            return
        priv_cmd = sudo_manager.wrapper_path
        command = self._get_kwin_effects_force_rebuild_command(priv_cmd)
        if not command:
            root = self.get_root() or self.window
            dialog = Adw.MessageDialog(
                heading=_("No KWin Effects Installed"),
                body=_("Neither kwin-effects-glass-git nor kwin-effect-rounded-corners-git is installed."),
                transient_for=root
            )
            dialog.add_response("ok", _("OK"))
            dialog.connect("response", lambda d, r: d.close())
            translate_dialog(dialog)
            dialog.present()
            return
        self.begin_install(command, "KWin Effects (debug rebuild)")

    def on_shutdown_toggled(self, switch, param):
        """Handle shutdown toggle switch"""
        self.turn_off_after_install = switch.get_active()
    def prompt_for_password(self, callback=None):
        """Prompt user for sudo password using Adw.MessageDialog"""
        if callback is None:
            callback = self.on_install_clicked
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
                    callback(None)
            dialog.close()
        dialog.connect("response", on_response)
        def on_entry_activate(widget):
            dialog.response("unlock")
        entry.connect("activate", on_entry_activate)
        translate_dialog(dialog)
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
            translate_dialog(dialog)
            dialog.present()
            return
        product_name = distro.name()
        self.btn_retry.set_visible(False)
        priv_cmd = sudo_manager.wrapper_path
        kwin_rebuild_cmd = self.get_kwin_effects_rebuild_command(priv_cmd)
        if self.include_aur_updates:
            command = f"echo Updating {product_name}... && paru -Syu --noconfirm --overwrite '*' --sudo '{priv_cmd}'"
            command += " && { flatpak update --assumeyes || true; }"
            if kwin_rebuild_cmd:
                command += f" && {kwin_rebuild_cmd}"
        else:
            aur_helper_rebuild = self.get_aur_helper_rebuild_command()
            privileged_cmds = f"{priv_cmd} pacman -Syu --noconfirm --overwrite '*'"
            if aur_helper_rebuild:
                privileged_cmds += f" && echo 'Reinstalling paru to relink against new libalpm...' && {priv_cmd} pacman -S --noconfirm paru"
            command = f"echo Updating {product_name}... && sh -c '{privileged_cmds}'"
            command += " && { flatpak update --assumeyes || true; }"
            if kwin_rebuild_cmd:
                command += f" && {kwin_rebuild_cmd}"
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
        self.info_label.set_markup(f'<span size="large" weight="bold">{_("Update in progress")}</span>')
        self.install_progress_bar.set_fraction(0.0)
        self.install_progress_bar.set_text("")
        self.install_progress_bar.set_visible(True)
        self.install_status_label.set_text("")
        self.install_status_label.set_visible(True)
        self._install_total_packages = 0
        self.content_stack.set_visible_child_name("info_view")
        if hasattr(self, 'updating_label'):
            self.updating_label.set_text(_("Updating {}...").format(product_name))
            self.updating_sublabel.set_text(_("Do not shut down or close the application"))
            self.info_panel_stack.set_visible_child_name("updating")
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
        """Append text to output buffer, scroll, and update progress bar."""
        if self.progress_visible:
            end_iter = self.output_buffer.get_end_iter()
            self.output_buffer.insert(end_iter, text)
            mark = self.output_buffer.create_mark(None, end_iter, False)
            self.output_textview.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)
        self._parse_install_progress(text)
        return False

    # Regex to match pacman progress lines like "(1/89) upgrading package..."
    _PROGRESS_RE = re.compile(r'^\((\d+)/(\d+)\)\s+(.*)')

    def _parse_install_progress(self, text):
        """Parse pacman output lines to update the progress bar."""
        for line in text.splitlines():
            line = line.strip()
            m = self._PROGRESS_RE.match(line)
            if m:
                current = int(m.group(1))
                total = int(m.group(2))
                action = m.group(3).strip()
                if total > 0:
                    fraction = current / total
                    self.install_progress_bar.set_fraction(fraction)
                    self.install_progress_bar.set_text(f"{current}/{total}")
                    # Truncate long action text
                    if len(action) > 60:
                        action = action[:57] + "..."
                    self.install_status_label.set_text(action)
                    # Update info panel updating view if visible
                    if hasattr(self, 'updating_sublabel'):
                        self.updating_sublabel.set_text(f"{current}/{total} — {action}")

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
        self.user_password = None
        self.install_started = False
        self.btn_install.set_sensitive(True)
        self.aur_switch.set_sensitive(True)
        self.shutdown_switch.set_sensitive(True)
        self.btn_install.set_visible(True)
        self.btn_toggle_progress.set_sensitive(True)
        self.install_progress_bar.set_visible(False)
        self.install_status_label.set_visible(False)
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
        if hasattr(self, 'info_panel_stack'):
            self.show_info_panel_default()
        return False
    def return_to_updates_and_refresh(self):
        """Return to updates view and refresh the list"""
        self.content_stack.set_visible_child_name("updates_view")
        self.check_for_updates()
        return False
