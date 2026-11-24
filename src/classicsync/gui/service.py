import asyncio
import logging
import threading
from datetime import datetime, timezone

from ..connection.dccm import STATUS_NO_PARTNERSHIP
from ..connection.desktop import Desktop
from ..connection.scanner import AUTOBAUD_SPEEDS, DTR_DROP_SECONDS
from ..i18n import _
from ..link.transport import open_transport, port_has_baud
from ..rapi.structures import datetime_to_filetime
from ..sync import Partnership
from ..sync.partners import match_partnership

log = logging.getLogger("classicsync.gui")

STATE_DISABLED = "disabled"
STATE_WAITING = "waiting"
STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"

RESTART_SECONDS = 3.0
AUTOBAUD_ATTEMPT_SECONDS = 30.0


class DeviceService:
    def __init__(self, settings, notify):
        self.settings = settings
        self.notify = notify
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, name="classicsync-service", daemon=True)
        self.state = STATE_DISABLED
        self.announcement = None
        self.desktop = None
        self.client = None
        self.client_lock = None
        self.supervisor = None
        self.proxy_server = None
        self.error = None
        self.request_password = None

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def start(self):
        self.thread.start()
        self.submit(self._start())

    def stop(self):
        future = self.submit(self._shutdown())
        try:
            future.result(5)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)

    def submit(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def restart(self):
        self.submit(self._restart())

    def suspend(self, reason=None):
        return self.submit(self._suspend(reason))

    async def _start(self):
        self.client_lock = asyncio.Lock()
        self.supervisor = asyncio.create_task(self._supervise())

    async def _restart(self):
        if self.supervisor:
            self.supervisor.cancel()
            try:
                await self.supervisor
            except (asyncio.CancelledError, Exception):
                pass
        await self._close_desktop()
        self.supervisor = asyncio.create_task(self._supervise())

    async def _suspend(self, reason):
        if self.supervisor:
            self.supervisor.cancel()
            try:
                await self.supervisor
            except (asyncio.CancelledError, Exception):
                pass
            self.supervisor = None
        await self._close_desktop()
        self._set_state(STATE_DISABLED, error=reason)

    async def _shutdown(self):
        if self.supervisor:
            self.supervisor.cancel()
        await self._close_desktop()

    def _set_state(self, state, announcement=None, error=None):
        self.state = state
        self.announcement = announcement
        self.error = error
        self.notify(state, announcement, error)

    async def _close_desktop(self):
        if self.proxy_server:
            self.proxy_server.close()
            self.proxy_server = None
        if self.client:
            self.client.close()
            self.client = None
        if self.desktop:
            try:
                await self.desktop.close()
            except Exception:
                pass
            self.desktop = None

    async def _supervise(self):
        while True:
            if not (self.settings.serial_enabled and self.settings.serial_port):
                self._set_state(STATE_DISABLED)
                return
            try:
                await self._run_session()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                log.info("connection ended: %s", error)
                self._set_state(STATE_WAITING, error=str(error))
            await self._close_desktop()
            await asyncio.sleep(RESTART_SECONDS)

    def _starting_baud(self):
        return self.settings.serial_baud or self.settings.last_baud or AUTOBAUD_SPEEDS[0]

    async def _run_session(self):
        transport = open_transport(self.settings.serial_port, self._starting_baud())
        self.desktop = Desktop(transport, password_provider=self._password_provider, partnership_policy=self._partnership_policy)
        await self.desktop.start()
        autobaud = None
        if port_has_baud(self.settings.serial_port) and not self.settings.serial_baud:
            autobaud = asyncio.create_task(self._autobaud(transport))
        try:
            await self._serve_session()
        finally:
            if autobaud:
                autobaud.cancel()

    async def _autobaud(self, transport):
        speeds = list(AUTOBAUD_SPEEDS)
        index = speeds.index(transport.baud) if transport.baud in speeds else 0
        while True:
            await asyncio.sleep(AUTOBAUD_ATTEMPT_SECONDS)
            if self.state != STATE_WAITING or self.desktop.link.handshaken:
                continue
            index = (index + 1) % len(speeds)
            log.info("autobaud: trying %d", speeds[index])
            await transport.set_dtr(False)
            await asyncio.sleep(DTR_DROP_SECONDS)
            await transport.set_baud(speeds[index])
            self.desktop.link.decoder.reset()
            await transport.set_dtr(True)

    async def _serve_session(self):
        host, separator, port = self.settings.rapi_proxy.rpartition(":")
        try:
            self.proxy_server = await self.desktop.serve_rapi_proxy(host or "127.0.0.1", int(port))
        except OSError as error:
            log.warning("RAPI proxy unavailable on %s: %s", self.settings.rapi_proxy, error)
        self.desktop.link.add_listener(self._link_event)
        self._set_state(STATE_WAITING)
        while True:
            self.desktop.device_changed.clear()
            if self.desktop.device:
                if self.client:
                    self.client.close()
                    self.client = None
                baud = self.desktop.transport.baud
                if baud and baud != self.settings.last_baud:
                    self.settings.last_baud = baud
                    self.settings.save()
                self._set_state(STATE_CONNECTED, self.desktop.device)
                if self.settings.sync_clock_on_connect:
                    asyncio.create_task(self._sync_clock())
            elif self.state == STATE_CONNECTED:
                if self.client:
                    self.client.close()
                    self.client = None
                self._set_state(STATE_WAITING)
            waiter = asyncio.create_task(self.desktop.device_changed.wait())
            done, pending = await asyncio.wait({waiter, self.desktop.link.finished}, return_when=asyncio.FIRST_COMPLETED)
            if waiter not in done:
                waiter.cancel()
                raise ConnectionError(self.desktop.link.close_reason or _("link closed"))

    async def _password_provider(self, announcement, attempt):
        saved_key = f"{announcement.key:08x}"
        saved = self.settings.saved_passwords.get(saved_key)
        if saved is not None and attempt == 0:
            return saved
        if saved is not None:
            self.settings.saved_passwords.pop(saved_key, None)
            self.settings.save()
            attempt = 0
        if not self.request_password:
            return None
        future = self.loop.create_future()

        def reply(result):
            self.loop.call_soon_threadsafe(lambda: future.done() or future.set_result(result))

        self.request_password(announcement, attempt, reply)
        result = await future
        if not result:
            return None
        password, save = result
        if save:
            self.settings.saved_passwords[saved_key] = password
            self.settings.save()
        return password

    async def _partnership_policy(self, announcement):
        if not announcement.info.remote_sync:
            return 0
        if match_partnership(announcement.info.partner_ids, Partnership.list_all()) is None:
            return STATUS_NO_PARTNERSHIP
        return 0

    def _link_event(self, event):
        if event == "handshake" and self.state == STATE_WAITING:
            self._set_state(STATE_CONNECTING)

    async def rapi(self):
        async with self.client_lock:
            if self.state != STATE_CONNECTED or not self.desktop:
                raise ConnectionError(_("no device connected"))
            if self.client is None:
                self.client = await self.desktop.open_rapi()
            return self.client

    async def with_rapi(self, operation):
        client = await self.rapi()
        try:
            return await operation(client)
        except ConnectionError:
            async with self.client_lock:
                if self.client is client:
                    self.client.close()
                    self.client = None
            raise

    async def _sync_clock(self):
        async def set_clock(client):
            offset = datetime.now().astimezone().utcoffset()
            bias = -int(offset.total_seconds() // 60) if offset else 0
            await client.sync_time_to_pc(datetime_to_filetime(datetime.now(timezone.utc)), bias & 0xFFFFFFFF)
        try:
            await self.with_rapi(set_clock)
        except Exception as error:
            log.info("clock sync failed: %s", error)
