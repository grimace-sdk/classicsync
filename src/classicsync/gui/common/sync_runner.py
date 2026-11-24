import asyncio
import concurrent.futures
import logging
from datetime import datetime, timezone

import wx

from ...sync import (
    BUILTIN_OBJECT_TYPES, FIRST_SYNC_COMBINE, SyncOptions, load_providers, set_resolutions, synchronize, unresolved_items,
)

log = logging.getLogger("classicsync.gui.sync")

EVENT_STARTED = "started"
EVENT_PROGRESS = "progress"
EVENT_FINISHED = "finished"
EVENT_FAILED = "failed"
EVENT_STOPPED = "stopped"

SYNC_MODE_CONNECT = "connect"
SYNC_MODE_MANUAL = "manual"


class SyncRunner:
    def __init__(self, application):
        self.application = application
        self.future = None
        self.listeners = []
        self.last_report = None
        self.last_progress = None

    @property
    def running(self):
        return self.future is not None and not self.future.done()

    def add_listener(self, callback):
        self.listeners.append(callback)

    def remove_listener(self, callback):
        if callback in self.listeners:
            self.listeners.remove(callback)

    def _notify(self, kind, payload=None):
        for callback in list(self.listeners):
            try:
                callback(kind, payload)
            except RuntimeError:
                self.remove_listener(callback)

    def partnership(self):
        return self.application.partnership

    def object_types(self):
        partnership = self.partnership()
        options = partnership.load_options() if partnership else SyncOptions()
        providers = load_providers()
        provider = providers.get(options.provider)
        available = list(getattr(provider, "object_types", None) or BUILTIN_OBJECT_TYPES)
        enabled = set(options.object_types) if options.object_types is not None else {object_type.key for object_type in available}
        return [(object_type, object_type.key in enabled) for object_type in available]

    def set_enabled_types(self, keys):
        partnership = self.partnership()
        if not partnership:
            return
        options = partnership.load_options()
        options.object_types = list(keys)
        partnership.save_options(options)

    def conflict_policy(self):
        partnership = self.partnership()
        if not partnership:
            return None
        return partnership.load_options().conflict.get("*")

    def set_conflict_policy(self, policy):
        partnership = self.partnership()
        if not partnership:
            return
        options = partnership.load_options()
        if policy:
            options.conflict["*"] = policy
        else:
            options.conflict.pop("*", None)
        partnership.save_options(options)

    def conflict_prompt(self):
        partnership = self.partnership()
        return partnership.load_options().conflict_prompt if partnership else ""

    def set_conflict_prompt(self, default_action):
        partnership = self.partnership()
        if not partnership:
            return
        options = partnership.load_options()
        options.conflict_prompt = default_action or ""
        partnership.save_options(options)

    def last_sync(self):
        partnership = self.partnership()
        if not partnership:
            return None, ""
        state = partnership.load_state()
        stamp = state.get("last_sync")
        if not stamp:
            return None, ""
        moment = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone()
        return moment, state.get("last_result", "")

    def unresolved_items(self):
        partnership = self.partnership()
        return unresolved_items(partnership) if partnership else []

    def apply_resolutions(self, items):
        partnership = self.partnership()
        if partnership:
            set_resolutions(partnership, items)

    async def ask_first_sync(self, question):
        loop = asyncio.get_running_loop()
        answer = loop.create_future()

        def reply(choice):
            loop.call_soon_threadsafe(lambda: answer.done() or answer.set_result(choice))

        def ask():
            try:
                reply(self.application.frontend.ask_first_sync(question))
            except Exception:
                reply(FIRST_SYNC_COMBINE)
                raise

        wx.CallAfter(ask)
        return await answer

    def start(self):
        if self.running:
            return False
        partnership = self.partnership()
        if not partnership:
            return False
        options = partnership.load_options()
        service = self.application.service

        def progress(update):
            self.last_progress = update
            wx.CallAfter(self._notify, EVENT_PROGRESS, update)

        async def run(client):
            return await synchronize(client, partnership, options, progress, first_sync=self.ask_first_sync)

        self.future = service.submit(service.with_rapi(run))
        self.future.add_done_callback(lambda future: wx.CallAfter(self._finished, future))
        self._notify(EVENT_STARTED)
        return True

    def stop(self):
        if self.running:
            self.future.cancel()

    def _finished(self, future):
        if future is not self.future:
            return
        try:
            report = future.result()
        except concurrent.futures.CancelledError:
            self._notify(EVENT_STOPPED)
            return
        except Exception as error:
            log.info("synchronization failed: %s", error)
            self._notify(EVENT_FAILED, error)
            return
        self.last_report = report
        self._notify(EVENT_FINISHED, report)

    def start_on_connect(self):
        if self.application.settings.sync_mode == SYNC_MODE_CONNECT:
            self.start()
