import ctypes
import ctypes.util
import logging
import sys

log = logging.getLogger("classicsync.gui")


def _runtime():
    library = ctypes.util.find_library("objc")
    if not library:
        return None
    objc = ctypes.cdll.LoadLibrary(library)
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    return objc


def _send(objc, receiver, selector, *arguments):
    function = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, *[ctypes.c_void_p] * len(arguments))
    send = function(("objc_msgSend", objc))
    return send(receiver, objc.sel_registerName(selector), *arguments)


def _string(objc, text):
    function = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)
    send = function(("objc_msgSend", objc))
    return send(objc.objc_getClass(b"NSString"), objc.sel_registerName(b"stringWithUTF8String:"), text.encode("utf-8"))


def set_application_name(name):
    if sys.platform != "darwin" or getattr(sys, "frozen", False):
        return
    try:
        objc = _runtime()
        if objc is None:
            return
        bundle = _send(objc, objc.objc_getClass(b"NSBundle"), b"mainBundle")
        information = _send(objc, bundle, b"infoDictionary") if bundle else None
        value = _string(objc, name)
        if information:
            for key in ("CFBundleName", "CFBundleDisplayName"):
                _send(objc, information, b"setObject:forKey:", value, _string(objc, key))
        process = _send(objc, objc.objc_getClass(b"NSProcessInfo"), b"processInfo")
        if process:
            _send(objc, process, b"setProcessName:", value)
    except (OSError, AttributeError, ctypes.ArgumentError) as error:
        log.info("could not set the application name: %s", error)
