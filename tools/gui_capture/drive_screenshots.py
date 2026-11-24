import ctypes
import ctypes.util
import json
import os
import sys
from pathlib import Path

import wx

home = Path(os.environ["CLASSICSYNC_HOME"])
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
home.mkdir(parents=True, exist_ok=True)
frontend_key = os.environ.get("CLASSICSYNC_FRONTEND", "activesync31")
(home / "settings.json").write_text(json.dumps({"serial_port": sys.argv[1], "language": os.environ.get("CLASSICSYNC_LANGUAGE", ""),
                                                "rapi_proxy": "127.0.0.1:19991", "show_tray_icon": True, "frontend": frontend_key}))

from classicsync.gui.app import Application
from classicsync.gui.service import STATE_CONNECTED
from partnership_prompts import answer_partnership_prompts

objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
objc.objc_getClass.restype = ctypes.c_void_p
objc.objc_getClass.argtypes = [ctypes.c_char_p]
objc.sel_registerName.restype = ctypes.c_void_p
objc.sel_registerName.argtypes = [ctypes.c_char_p]


def send(receiver, selector, *arguments, result=ctypes.c_void_p):
    function = ctypes.CFUNCTYPE(result, ctypes.c_void_p, ctypes.c_void_p, *[ctypes.c_void_p] * len(arguments))
    return function(("objc_msgSend", objc))(receiver, objc.sel_registerName(selector), *arguments)


def ns_string(text):
    function = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)
    return function(("objc_msgSend", objc))(objc.objc_getClass(b"NSString"), objc.sel_registerName(b"stringWithUTF8String:"),
                                             text.encode("utf-8"))


def shared_application():
    return send(objc.objc_getClass(b"NSApplication"), b"sharedApplication")


def use_light_appearance():
    application = shared_application()
    appearance = send(objc.objc_getClass(b"NSAppearance"), b"appearanceNamed:", ns_string("NSAppearanceNameAqua"))
    send(application, b"setAppearance:", appearance)


class Rect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("width", ctypes.c_double), ("height", ctypes.c_double)]


NS_BITMAP_PNG = 4


def capture(window, name, then):
    send(shared_application(), b"activateIgnoringOtherApps:", 1)
    window.Raise()
    send(send(window.GetHandle(), b"window"), b"makeKeyAndOrderFront:", None)
    wx.CallLater(800, lambda: (render(window, name), then()))


def render(window, name):
    window.Update()
    ns_window = send(window.GetHandle(), b"window")
    send(ns_window, b"display")
    frame_view = send(send(ns_window, b"contentView"), b"superview")
    bounds = ctypes.CFUNCTYPE(Rect, ctypes.c_void_p, ctypes.c_void_p)(("objc_msgSend", objc))(frame_view, objc.sel_registerName(b"bounds"))
    with_rect = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, Rect)(("objc_msgSend", objc))
    representation = with_rect(frame_view, objc.sel_registerName(b"bitmapImageRepForCachingDisplayInRect:"), bounds)
    cache = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, Rect, ctypes.c_void_p)(("objc_msgSend", objc))
    cache(frame_view, objc.sel_registerName(b"cacheDisplayInRect:toBitmapImageRep:"), bounds, representation)
    as_png = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p)(("objc_msgSend", objc))
    data = as_png(representation, objc.sel_registerName(b"representationUsingType:properties:"), NS_BITMAP_PNG,
                  send(objc.objc_getClass(b"NSDictionary"), b"dictionary"))
    path = out / f"{name}.png"
    write = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool)(("objc_msgSend", objc))
    write(data, objc.sel_registerName(b"writeToFile:atomically:"), ns_string(str(path)), True)
    print("captured", name, path, flush=True)


application = Application(False)
use_light_appearance()
answer_partnership_prompts(create=True)
frontend = application.frontend


def wait_synchronized(then):
    if frontend.sync.running:
        wx.CallLater(1000, lambda: wait_synchronized(then))
    else:
        wx.CallLater(1500, then)


def wait_connected(then):
    if application.service.state == STATE_CONNECTED and application.device_details:
        wx.CallLater(15000, lambda: wait_synchronized(then))
    else:
        wx.CallLater(500, lambda: wait_connected(then))


def activesync31():
    def explore():
        frontend.show_explore()
        wx.CallLater(8000, lambda: capture(frontend.explore_window, "activesync31-explore", application.quit))
    wait_connected(lambda: capture(frontend.main_window, "activesync31-main", explore))


def ceservices22():
    def status():
        frontend.show_sync_status()
        wx.CallLater(1500, lambda: capture(frontend.sync_status_window, "ceservices22-sync-status", application.quit))
    wait_connected(lambda: capture(frontend.main_window, "ceservices22-mobile-devices", status))


def hpcexplorer11():
    wait_connected(lambda: capture(frontend.explorer_window, "hpcexplorer11-explorer", application.quit))


wx.CallLater(1500, {"activesync31": activesync31, "ceservices22": ceservices22, "hpcexplorer11": hpcexplorer11}[frontend_key])
wx.CallLater(240000, application.quit)
application.MainLoop()
