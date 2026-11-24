import wx
import wx.adv

from ...i18n import _
from ..service import STATE_CONNECTED

CONNECT_SOUND = "pegconn.wav"
DISCONNECT_SOUND = "pegdisc.wav"


class Frontend:
    key = ""
    title = ""
    device_versions = ()

    def __init__(self, application):
        self.application = application
        self.settings = application.settings
        self.service = application.service
        self.artwork = None
        self.tray = None

    @property
    def device_details(self):
        return self.application.device_details

    def device_name(self, announcement):
        return self.application.device_name(announcement)

    def device_label(self, announcement):
        return self.application.device_label(announcement)

    def device_properties(self, announcement):
        return self.application.device_properties(announcement)

    def tray_available(self):
        return self.settings.show_tray_icon and wx.adv.TaskBarIcon.IsAvailable()

    def start(self):
        raise NotImplementedError

    def stop(self):
        if self.tray:
            tray = self.tray
            tray.RemoveIcon()
            wx.CallAfter(tray.Destroy)
            self.tray = None

    def on_state(self, state, announcement, error):
        raise NotImplementedError

    def on_details(self, announcement):
        pass

    def on_sync_event(self, kind, payload):
        pass

    def offer_partnership(self, announcement):
        pass

    def backup_state_changed(self):
        pass

    def partnership_created(self):
        pass

    def run_automatic_backup(self):
        pass

    def ask_first_sync(self, question):
        from ...sync import FIRST_SYNC_COMBINE
        return FIRST_SYNC_COMBINE

    def set_up_partnership(self, title, failure_text, exclusive=False):
        def created(partnership, error):
            if error or partnership is None:
                wx.MessageBox(f"{failure_text}\n\n{error}" if error else failure_text, title, wx.OK | wx.ICON_ERROR)
                return
            self.sync.start()
            self.partnership_created()
        self.application.create_partnership(created, exclusive=exclusive)

    def prompt_for_conflicts(self, parent, wording):
        from ..common.conflicts import resolve_items
        default = self.sync.conflict_prompt()
        if default and not self.sync.running and self.sync.unresolved_items():
            resolve_items(parent, self.sync, wording, default_resolution=default)

    def partnership_name(self):
        partnership = self.application.partnership
        return partnership.name if partnership else _("Guest")

    @property
    def sync(self):
        return self.application.sync

    def show_main_window(self):
        raise NotImplementedError

    def show_connection_settings(self, parent):
        raise NotImplementedError

    def apply_tray_setting(self):
        pass

    def password_icon(self):
        return None

    def ask_password(self, announcement, attempt):
        from ..common.password import ask_device_password
        return ask_device_password(None, attempt, self.password_icon())

    def show_file_conversion(self, parent):
        from ..common.file_conversion import show_file_conversion
        major = self.application.device_major_version(self.application.service.announcement)
        show_file_conversion(parent, self.application, self.artwork, 1 if major == 1 else 2)

    def play_transition_sound(self, state):
        was_connected = getattr(self, "sound_state", None) == STATE_CONNECTED
        self.sound_state = state
        if (state == STATE_CONNECTED) == was_connected or self.artwork is None:
            return
        path = self.artwork.sound_path(CONNECT_SOUND if state == STATE_CONNECTED else DISCONNECT_SOUND)
        if not path:
            return
        sounds = getattr(self, "sounds", None)
        if sounds is None:
            sounds = self.sounds = {}
        sound = sounds.get(path)
        if sound is None:
            sound = sounds[path] = wx.adv.Sound(str(path))
        if sound.IsOk():
            wx.adv.Sound.Stop()
            sound.Play(wx.adv.SOUND_ASYNC)

    def quit(self):
        self.application.quit()
