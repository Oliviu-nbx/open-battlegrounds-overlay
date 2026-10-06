"""macOS Carbon hotkey registration: no accessibility/input-monitoring hooks."""
from __future__ import annotations

import ctypes as C
import sys
from typing import Callable


class HotkeyID(C.Structure):
    _fields_ = [("signature", C.c_uint32), ("id", C.c_uint32)]


class EventType(C.Structure):
    _fields_ = [("eventClass", C.c_uint32), ("eventKind", C.c_uint32)]


def fourcc(value: str) -> int:
    return int.from_bytes(value.encode("ascii"), "big")


class MacHotkey:
    def __init__(self, callback: Callable[[], None]) -> None:
        self._handler, self._hotkey = C.c_void_p(), C.c_void_p()
        self._carbon = None
        self.status = "⌘⇧H works while this overlay is focused" if sys.platform == "darwin" else "Ctrl+Shift+H works while this overlay is focused"
        if sys.platform != "darwin":
            return
        try:
            carbon = C.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
            self._carbon = carbon
            carbon.GetApplicationEventTarget.restype = C.c_void_p
            carbon.InstallEventHandler.argtypes = [C.c_void_p, C.c_void_p, C.c_uint32,
                                                  C.POINTER(EventType), C.c_void_p, C.POINTER(C.c_void_p)]
            carbon.RegisterEventHotKey.argtypes = [C.c_uint32, C.c_uint32, HotkeyID,
                                                   C.c_void_p, C.c_uint32, C.POINTER(C.c_void_p)]
            carbon.UnregisterEventHotKey.argtypes = [C.c_void_p]
            carbon.RemoveEventHandler.argtypes = [C.c_void_p]
            signature = fourcc("OBGT")
            carbon.GetEventParameter.argtypes = [C.c_void_p, C.c_uint32, C.c_uint32,
                                                 C.c_void_p, C.c_uint32, C.c_void_p, C.c_void_p]
            callback_type = C.CFUNCTYPE(C.c_int32, C.c_void_p, C.c_void_p, C.c_void_p)
            def handle(_next, event, _data):
                identity = HotkeyID()
                result = carbon.GetEventParameter(event, fourcc("----"), fourcc("hkid"),
                                                   None, C.sizeof(identity), None, C.byref(identity))
                if result == 0 and identity.signature == signature and identity.id == 1:
                    callback()  # Caller queues UI work, never touches Tk here.
                    return 0
                return -9874  # eventNotHandledErr
            self._callback = callback_type(handle)  # Retain until handler removal.
            event_type = EventType(fourcc("keyb"), 6)
            target = carbon.GetApplicationEventTarget()
            status = carbon.InstallEventHandler(target, self._callback, 1,
                                                C.byref(event_type), None, C.byref(self._handler))
            if status:
                raise RuntimeError(f"handler OSStatus {status}")
            # Physical H key (4); cmdKey=256, shiftKey=512.
            status = carbon.RegisterEventHotKey(4, 256 | 512, HotkeyID(signature, 1),
                                                target, 0, C.byref(self._hotkey))
            if status:
                raise RuntimeError(f"registration OSStatus {status}; shortcut may be in use")
            self.status = "Global ⌘⇧H: show/hide overlay"
        except (OSError, AttributeError, RuntimeError) as exc:
            self.close()
            self.status += f" (global hotkey unavailable: {exc})"

    @property
    def registered(self) -> bool:
        return bool(self._hotkey.value)

    def close(self) -> None:
        if self._carbon:
            if self._hotkey.value:
                self._carbon.UnregisterEventHotKey(self._hotkey)
                self._hotkey = C.c_void_p()
            if self._handler.value:
                self._carbon.RemoveEventHandler(self._handler)
                self._handler = C.c_void_p()
