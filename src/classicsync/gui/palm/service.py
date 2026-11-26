import asyncio
import logging
import threading
from pathlib import Path

from ...i18n import _
from ...link.usb import usb_available
from ...palm import DlpClient, NetSyncLink, PalmUsbTransport
from ...palm.conduits import BackupConduit
from ...palm.dlp import END_OF_SYNC_CANCELLED
from ...palm.install import InstallError, install_files, load_installables
from ...palm.sync import create_palm_partnership, find_palm_partnership, synchronize_handheld
from ...palm.usb import attached_palm
from ...palm.users import new_identifier, set_user
from .hotsync_log import append_session, conduit_line

log = logging.getLogger("classicsync.gui.palm")

POLL_SECONDS = 0.5
INSTALL_FOLDER = "Install"

EVENT_STARTED = "started"
EVENT_STATUS = "status"
EVENT_USER = "user"
EVENT_STAGE = "stage"
EVENT_FINISHED = "finished"

STAGE_CONNECTING = 1
STAGE_IDENTIFIED = 2
STAGE_SYNCHRONIZING = 3


class HotSyncCancelled(Exception):
    pass


class PalmService:
    def __init__(self, settings, notify):
        self.settings = settings
        self.notify = notify
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, name="classicsync-palm", daemon=True)
        self.watcher = None
        self.session = None
        self.syncing = False
        self.ask_user_name = None

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def start(self):
        self.thread.start()
        self.restart()

    def restart(self):
        asyncio.run_coroutine_threadsafe(self._restart(), self.loop)

    def stop(self):
        future = asyncio.run_coroutine_threadsafe(self._stop_watching(), self.loop)
        try:
            future.result(5)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)

    def cancel(self):
        if self.session:
            self.loop.call_soon_threadsafe(self.session.cancel)

    async def _stop_watching(self):
        if self.watcher:
            self.watcher.cancel()
            try:
                await self.watcher
            except (asyncio.CancelledError, Exception):
                pass
            self.watcher = None

    async def _restart(self):
        await self._stop_watching()
        if self.settings.palm_usb_enabled and await asyncio.to_thread(usb_available):
            self.watcher = asyncio.create_task(self._watch())

    async def _watch(self):
        while True:
            device = await asyncio.to_thread(attached_palm)
            if device is None:
                await asyncio.sleep(POLL_SECONDS)
                continue
            self.session = asyncio.create_task(self._hotsync(device))
            try:
                await self.session
            except asyncio.CancelledError:
                if not self.session.cancelled():
                    raise
            except Exception as error:
                log.info("HotSync failed: %s", error)
            self.session = None
            while await asyncio.to_thread(attached_palm) is not None:
                await asyncio.sleep(POLL_SECONDS)

    def transport_for(self, device):
        return PalmUsbTransport(device)

    def emit(self, kind, payload=None):
        self.notify(kind, payload)

    def pc_identifier(self):
        if not self.settings.palm_pc_id:
            self.settings.palm_pc_id = new_identifier()
            self.settings.save()
        return self.settings.palm_pc_id

    async def request_user_name(self):
        if not self.ask_user_name:
            return None
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.ask_user_name(lambda name: loop.call_soon_threadsafe(lambda: future.done() or future.set_result(name)))
        return await future

    async def _identify(self, client):
        user = await client.read_user_info()
        if not user.name:
            chosen = await self.request_user_name()
            if not chosen:
                raise HotSyncCancelled(_("No user name was chosen"))
            name, user_id = chosen
            await set_user(client, name, self.pc_identifier(), user_id=user_id)
            user = await client.read_user_info()
        elif not user.synced:
            await set_user(client, user.name, self.pc_identifier())
            user = await client.read_user_info()
        partnership = find_palm_partnership(user) or create_palm_partnership(user.name, user.user_id)
        return user, partnership

    async def _install_queue(self, client, partnership):
        folder = Path(partnership.directory) / INSTALL_FOLDER
        files = sorted(path for path in folder.iterdir() if path.is_file()) if folder.is_dir() else []
        if not files:
            return []
        self.emit(EVENT_STATUS, _("Installing handheld applications"))
        lines = []
        for path in files:
            try:
                result = await install_files(client, load_installables([path]))
            except InstallError as error:
                lines.append(_("Install failed: {name} ({error})").format(name=path.name, error=error))
                continue
            path.unlink()
            lines.append(_("Installed file: {name}").format(name=path.name))
            if result.reset_needed:
                await client.reset_system()
        return lines

    async def _hotsync(self, device):
        self.syncing = True
        self.emit(EVENT_STARTED)
        self.emit(EVENT_STATUS, _("Connecting with handheld"))
        self.emit(EVENT_STAGE, STAGE_CONNECTING)
        transport = self.transport_for(device)
        client = None
        partnership = None
        lines = []
        completed = False
        try:
            await transport.open()
            link = NetSyncLink(transport)
            await link.accept()
            client = DlpClient(link)
            self.emit(EVENT_STATUS, _("Identifying user"))
            user, partnership = await self._identify(client)
            self.emit(EVENT_USER, user.name)
            self.emit(EVENT_STAGE, STAGE_IDENTIFIED)
            lines += await self._install_queue(client, partnership)
            self.emit(EVENT_STAGE, STAGE_SYNCHRONIZING)

            def conduit_started(conduit):
                if isinstance(conduit, BackupConduit):
                    self.emit(EVENT_STATUS, _("Backing up handheld databases"))
                else:
                    self.emit(EVENT_STATUS, _("Synchronizing {conduit}").format(conduit=_(conduit.display_name)))

            report = await synchronize_handheld(client, partnership, self.pc_identifier(), on_conduit=conduit_started,
                                                log=lines.append)
            lines += self.conduit_lines(report)
            await client.end_of_sync()
            completed = True
            self.emit(EVENT_STATUS, _("HotSync operation complete"))
            self.emit(EVENT_FINISHED, (True, report.summary(), bool(report.errors)))
        except asyncio.CancelledError:
            await self._end_quietly(client, END_OF_SYNC_CANCELLED)
            self.emit(EVENT_FINISHED, (False, _("HotSync operation canceled."), False))
            raise
        except HotSyncCancelled as error:
            await self._end_quietly(client, END_OF_SYNC_CANCELLED)
            self.emit(EVENT_FINISHED, (False, str(error), False))
        except Exception as error:
            lines.append(_("HotSync Error: {error}").format(error=error))
            self.emit(EVENT_FINISHED, (False, str(error), True))
        finally:
            self.syncing = False
            if partnership is not None:
                append_session(partnership, lines, completed)
            await transport.close()

    @staticmethod
    def conduit_lines(report):
        from ...palm.conduits import CONDUITS
        lines = []
        names = {conduit.object_type.key: conduit.display_name for conduit in CONDUITS if getattr(conduit, "object_type", None)}
        for key, name in names.items():
            messages = sum(1 for action in report.actions if action.object_type == key and action.error)
            lines.append(conduit_line(_(name), key in report.skipped_types, messages))
        return lines

    async def _end_quietly(self, client, status):
        if client is None:
            return
        try:
            await client.end_of_sync(status)
        except Exception:
            pass
