import logging
import sys

import wx
import wx.adv

from ..i18n import _, set_language
from .branding import PRODUCT_NAME, set_naming
from .macos import set_application_name
from ..rapi.client import HKEY_LOCAL_MACHINE, RapiError
from ..sync import Partnership, create_partnership, delete_partnership, find_partnership, read_device_partners
from ..sync.partners import clear_device_partner, describe_device, rename_device
from .common.backup import BackupRunner
from .common.sync_runner import SyncRunner
from .frontends import AUTOMATIC, DEFAULT_IDLE, available_frontends, frontend_for_version
from .palm.hotsync import HotSyncManager
from .palm.service import PalmService
from .service import STATE_CONNECTED, DeviceService
from .settings import Settings

log = logging.getLogger("classicsync.gui")


def wx_language(code):
    info = wx.Locale.FindLanguageInfo(code) if code else None
    return info.Language if info else wx.LANGUAGE_DEFAULT


def operating_system_text(major, minor, build):
    return _("Windows CE {version} (build {build})").format(version=f"{major}.{minor:02d}", build=build)


class Application(wx.App):
    def OnInit(self):
        self.SetAppName("classicsync")
        self.settings = Settings.load()
        set_language(self.settings.language or None)
        set_naming(self.settings.naming)
        self.wx_locale = wx.Locale(wx_language(self.settings.language))
        self.device_details = {}
        self.partnership = None
        self.device_partners = None
        self.frontend_classes = available_frontends()
        self.frontend = None
        self.dock_icon = None
        self.service = DeviceService(self.settings, lambda *state: wx.CallAfter(self.on_state, *state))
        self.service.request_password = lambda announcement, attempt, reply: wx.CallAfter(self._ask_password, announcement, attempt, reply)
        self.service.on_sync_request = lambda: wx.CallAfter(self.sync.start)
        self.service.on_sync_cancel = lambda: wx.CallAfter(self.sync.stop)
        self.service.start()
        self.sync = SyncRunner(self)
        self.backup = BackupRunner(self)
        self.sync.add_listener(self._sync_event)
        self.switch_frontend(self.idle_frontend_key(), initial=True)
        self.palm_service = PalmService(self.settings, lambda *event: wx.CallAfter(self.hotsync.on_event, *event))
        self.hotsync = HotSyncManager(self, self.palm_service)
        self.hotsync.start()
        self.palm_service.start()
        return True

    def apply_palm_settings(self):
        self.palm_service.restart()
        self.hotsync.apply_tray_setting()

    def idle_frontend_key(self):
        choice = self.settings.frontend
        if choice != AUTOMATIC and choice in self.frontend_classes:
            return choice
        if self.settings.last_frontend in self.frontend_classes:
            return self.settings.last_frontend
        return DEFAULT_IDLE if DEFAULT_IDLE in self.frontend_classes else next(iter(self.frontend_classes))

    def switch_frontend(self, key, initial=False):
        if self.frontend and self.frontend.key == key:
            return
        if self.frontend:
            self.frontend.stop()
        self.frontend = self.frontend_classes[key](self)
        if self.settings.last_frontend != key:
            self.settings.last_frontend = key
            self.settings.save()
        self.frontend.start(initial=initial)
        self.update_dock_icon()

    def update_dock_icon(self):
        if wx.Platform != "__WXMAC__" or not self.frontend or not self.frontend.artwork:
            return
        bundle = self.frontend.artwork.application_icons()
        if not bundle or not bundle.GetIconCount():
            return
        if self.dock_icon is None:
            self.dock_icon = wx.adv.TaskBarIcon(iconType=wx.adv.TBI_DOCK)
        largest = max((bundle.GetIconByIndex(index) for index in range(bundle.GetIconCount())), key=lambda icon: icon.GetWidth())
        self.dock_icon.SetIcon(largest, PRODUCT_NAME)

    def _ask_password(self, announcement, attempt, reply):
        try:
            reply(self.frontend.ask_password(announcement, attempt))
        except Exception:
            reply(None)
            raise

    def device_major_version(self, announcement):
        if announcement is None:
            return None
        if announcement.legacy:
            return 1
        return announcement.info.os_major

    def on_state(self, state, announcement, error):
        self.partnership = None
        self.device_partners = None
        if state == STATE_CONNECTED:
            self.device_details = {}
            if self.settings.frontend == AUTOMATIC:
                self.switch_frontend(frontend_for_version(self.device_major_version(announcement), self.frontend_classes))
            self._fetch_device_details(announcement)
        self.frontend.on_state(state, announcement, error)

    def apply_settings(self, restart_connection):
        if self.settings.frontend != AUTOMATIC and self.settings.frontend in self.frontend_classes:
            wx.CallAfter(self.switch_frontend, self.settings.frontend)
        if restart_connection:
            self.service.restart()
        else:
            self.frontend.apply_tray_setting()

    def _fetch_device_details(self, announcement):
        async def read(client):
            details = {}
            details["version"] = await client.get_version()
            details["system"] = await client.get_system_info()
            try:
                key = await client.reg_open_key(HKEY_LOCAL_MACHINE, "Ident")
                try:
                    details["name"] = (await client.reg_query_value(key, "Name"))[1]
                    details["description"] = (await client.reg_query_value(key, "Desc"))[1]
                finally:
                    await client.reg_close_key(key)
            except RapiError:
                pass
            try:
                details["store"] = await client.get_store_information()
            except RapiError:
                pass
            try:
                details["memory"] = await client.get_memory_status()
            except RapiError:
                pass
            details["partnership"] = await find_partnership(client, self.announced_partner_ids(announcement))
            return details

        def finished(future):
            if future.exception():
                log.info("could not read device details: %s", future.exception())
                return
            wx.CallAfter(self._details_ready, announcement, future.result())

        self.service.submit(self.service.with_rapi(read)).add_done_callback(finished)

    def _details_ready(self, announcement, details):
        if self.service.announcement is not announcement:
            return
        lookup = details.get("partnership")
        self.partnership = lookup.partnership if lookup else None
        self.device_partners = lookup.partners if lookup else None
        self.device_details = details
        self.frontend.on_details(announcement)
        if self.partnership:
            self.sync.start_on_connect()
            self.backup.schedule_automatic()
        else:
            self.frontend.offer_partnership(announcement)

    def announced_partner_ids(self, announcement):
        if announcement is None or announcement.info is None:
            return ()
        return tuple(partner_id for partner_id in announcement.info.partner_ids if partner_id)

    def partnerships(self):
        return [partnership for partnership in Partnership.list_all() if partnership.explicit]

    def run_on_device(self, operation, finished):
        def done(future):
            error = future.exception()
            wx.CallAfter(finished, None if error else future.result(), error)
        self.service.submit(self.service.with_rapi(operation)).add_done_callback(done)

    def create_partnership(self, finished, name=None, exclusive=False, remove_slots=(), description=None):
        announcement = self.service.announcement

        async def create(client):
            partners = await read_device_partners(client)
            for slot in remove_slots:
                await clear_device_partner(client, partners, slot)
            current_name = self.device_details.get("name") or ""
            if name and name != current_name:
                await rename_device(client, name)
            if description is not None and description != self.device_details.get("description", ""):
                await describe_device(client, description)
            return await create_partnership(client, name or current_name or None, exclusive=exclusive, partners=partners)

        def created(partnership, error):
            if partnership and self.service.announcement is announcement:
                self.partnership = partnership
                if name:
                    self.device_details["name"] = name
                if description is not None:
                    self.device_details["description"] = description
                self.frontend.on_details(announcement)
            finished(partnership, error)

        self.run_on_device(create, created)

    def remove_device_partner(self, slot, finished):
        async def remove(client):
            partners = await read_device_partners(client)
            await clear_device_partner(client, partners, slot)
            return partners

        def removed(partners, error):
            if partners:
                self.device_partners = partners
            finished(partners, error)

        self.run_on_device(remove, removed)

    def delete_partnership(self, partnership, finished):
        connected = self.partnership is not None and self.partnership.directory == partnership.directory

        def deleted(result, error):
            if connected:
                self.partnership = None
                self.frontend.on_details(self.service.announcement)
            finished(result, error)

        if connected and self.service.state == STATE_CONNECTED:
            self.run_on_device(lambda client: delete_partnership(partnership, client), deleted)
        else:
            self.service.submit(delete_partnership(partnership)).add_done_callback(
                lambda future: wx.CallAfter(deleted, None, future.exception()))

    def _sync_event(self, kind, payload):
        if self.frontend:
            self.frontend.on_sync_event(kind, payload)

    def device_name(self, announcement):
        return self.device_details.get("name") or (announcement.info.name if announcement and announcement.info else "")

    def device_label(self, announcement):
        name = self.device_name(announcement)
        description = self.device_details.get("description", "")
        return f"{name} ({description})" if name and description else name or _("Mobile device")

    def device_properties(self, announcement):
        rows = []
        info = announcement.info if announcement else None
        details = self.device_details
        name = self.device_name(announcement)
        if name:
            rows.append((_("Device name"), name))
        if details.get("description"):
            rows.append((_("Description"), details["description"]))
        if info and info.platform:
            rows.append((_("Platform"), info.platform))
        version = details.get("version")
        if version:
            rows.append((_("Operating system"), operating_system_text(version.major, version.minor, version.build)))
        elif info:
            rows.append((_("Operating system"), operating_system_text(info.os_major, info.os_minor, info.os_build)))
        system = details.get("system")
        if system:
            rows.append((_("Processor"), system.processor_name))
        elif info:
            rows.append((_("Processor"), info.processor_name))
        store = details.get("store")
        if store:
            rows.append((_("Storage free"), _("{free} KB of {total} KB").format(free=f"{store.free_size // 1024:,}",
                                                                                total=f"{store.store_size // 1024:,}")))
        if info and info.oem_info:
            rows.append((_("OEM"), info.oem_info))
        if announcement:
            port = _("Network") if self.service.is_network() else self.settings.serial_port
            rows.append((_("Connection"), f"{port} ({announcement.address})"))
            rows.append((_("Partnership"), self.partnership.name if self.partnership else _("Guest")))
        return rows

    def quit(self):
        if self.dock_icon:
            self.dock_icon.Destroy()
            self.dock_icon = None
        self.sync.stop()
        self.service.stop()
        self.hotsync.stop()
        self.palm_service.stop()
        if self.frontend:
            self.frontend.stop()
        for window in wx.GetTopLevelWindows():
            window.Destroy()
        self.ExitMainLoop()


def main(argv=None):
    arguments = argv if argv is not None else sys.argv[1:]
    verbose = sum(argument.count("v") for argument in arguments if argument.startswith("-v"))
    logging.basicConfig(level=logging.WARNING - 10 * min(verbose, 2), format="%(name)s: %(message)s")
    set_application_name(PRODUCT_NAME)
    application = Application(False)
    application.MainLoop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
