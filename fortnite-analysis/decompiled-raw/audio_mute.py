import atexit
import ctypes
import threading
from ctypes import wintypes
from typing import (Callable, Dict, List, Optional, Tuple)
GAME_EXES = ('fortniteclient-win64-shipping.exe',)

class Session:
    def __init__(self, pid: int, name: str, get_mute: Callable[[], bool], set_mute: Callable[[bool], None]):
        self.pid, self.name, self.get_mute, self.set_mute = pid, name, get_mute, set_mute


def _guid(s: str):
    import uuid
    class GUID(ctypes.Structure):
        _fields_ = [('a', wintypes.DWORD), ('b', wintypes.WORD), ('c', wintypes.WORD), ('d', ctypes.c_ubyte * 8)]

    u = uuid.UUID(s)
    g = GUID()
    g.a, g.b, g.c = u.time_low, u.time_mid, u.time_hi_version
    for i, byte in enumerate(u.bytes[8:]):
        g.d[i] = byte
    return g

def _call(obj, index: int, argtypes: tuple, *args) -> int:
    table = ctypes.cast(ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(table[index])
    return fn(obj, *args)

def _release(obj) -> None:
    try:
        if obj:
            _call(obj, 2, ())
            return
    except Exception:
        pass

def _process_names() -> Dict[int, str]:
    class ENTRY(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD), ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', ctypes.c_long), ('dwFlags', wintypes.DWORD), ('szExeFile', ctypes.c_wchar * 260)]

    k = ctypes.windll.kernel32
    k.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ENTRY)]
    k.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ENTRY)]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    out = {}
    snap = k.CreateToolhelp32Snapshot(2, 0)
    if not snap or snap == ctypes.c_void_p(-1).value:
        return out
    try:
        e = ENTRY()
        e.dwSize = ctypes.sizeof(ENTRY)
        ok = k.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out[int(e.th32ProcessID)] = e.szExeFile.lower()
            ok = k.Process32NextW(snap, ctypes.byref(e))
    finally:
        k.CloseHandle(snap)
    return out

class CoreAudioBackend:
    CLSID_ENUM = 'BCDE0395-E52F-467C-8E3D-C4579291692E'
    IID_ENUM = 'A95664D2-9614-4F35-A746-DE8DB63617E6'
    IID_MGR2 = '77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F'
    IID_CTRL2 = 'BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D'
    IID_VOL = '87CE5498-68D6-44E5-9215-6DA47EF883D8'
    def sessions(self) -> List[Session]:
        ole = ctypes.windll.ole32
        ole.CoInitializeEx(None, 0)
        out = []
        names = _process_names()
        enum = ctypes.c_void_p()
        hr = ole.CoCreateInstance(ctypes.byref(_guid(self.CLSID_ENUM)), None, 23, ctypes.byref(_guid(self.IID_ENUM)), ctypes.byref(enum))
        if hr != 0 or not enum:
            return out
        dev, mgr, senum = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        try:
            if _call(enum, 4, (ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)), 0, 1, ctypes.byref(dev)) != 0 or not dev:
                _release(senum), _release(mgr), _release(dev), _release(enum)
                return out
        finally:
            _release(senum), _release(mgr), _release(dev), _release(enum)
        try:
            if _call(dev, 3, (ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)), ctypes.byref(_guid(self.IID_MGR2)), 23, None, ctypes.byref(mgr)) != 0 or not mgr:
                _release(senum), _release(mgr), _release(dev), _release(enum)
                return out
        finally:
            _release(senum), _release(mgr), _release(dev), _release(enum)
        try:
            if _call(mgr, 5, (ctypes.POINTER(ctypes.c_void_p),), ctypes.byref(senum)) != 0 or not senum:
                _release(senum), _release(mgr), _release(dev), _release(enum)
                return out
        finally:
            _release(senum), _release(mgr), _release(dev), _release(enum)
        try:
            count = ctypes.c_int(0)
            _call(senum, 3, (ctypes.POINTER(ctypes.c_int),), ctypes.byref(count))
            for i in range(count.value):
                ctrl = ctypes.c_void_p()
                if _call(senum, 4, (ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)), i, ctypes.byref(ctrl)) != 0 or not ctrl:
                    continue
                s = self._session(ctrl, names)
                if s is not None:
                    out.append(s)
        finally:
            _release(senum), _release(mgr), _release(dev), _release(enum)
        return out

    def _session(self, ctrl, names: Dict[int, str]) -> Optional[Session]:
        ctrl2, vol = ctypes.c_void_p(), ctypes.c_void_p()
        try:
            qi = ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
            if _call(ctrl, 0, qi, ctypes.byref(_guid(self.IID_CTRL2)), ctypes.byref(ctrl2)) != 0 or not ctrl2:
                return
            pid = wintypes.DWORD(0)
            if _call(ctrl2, 14, (ctypes.POINTER(wintypes.DWORD),), ctypes.byref(pid)) != 0:
                return
            if _call(ctrl, 0, qi, ctypes.byref(_guid(self.IID_VOL)), ctypes.byref(vol)) != 0 or not vol:
                return
        except Exception:
            _release(ctrl2), _release(vol), _release(ctrl)
        _release(ctrl2)
        _release(ctrl)
        def get_mute() -> bool:
            v = wintypes.BOOL(0)
            _call(vol, 6, (ctypes.POINTER(wintypes.BOOL),), ctypes.byref(v))
            return bool(v.value)

        def set_mute(on: bool) -> None:
            if on:
                _call(vol, 5, (wintypes.BOOL, ctypes.c_void_p), 1, None)
                return
            None(None, None, None, 0, None)

        return Session(int(pid.value), names.get(int(pid.value), ''), get_mute, set_mute)


class PycawBackend:
    def __init__(self):
        from pycaw.pycaw import AudioUtilities

    def sessions(self) -> List[Session]:
        from pycaw.pycaw import AudioUtilities
        out = []
        for s in AudioUtilities.GetAllSessions():
            if s.Process is not None:
                vol = s.SimpleAudioVolume
                out.append(Session(int(s.ProcessId), (s.Process.name() or '').lower(), (lambda v=vol: bool(v.GetMute())), (lambda on, v=vol: v.SetMute(1, None) if on else None(0, None))))
        return out


def default_backend():
    try:
        return PycawBackend()
    except Exception:
        return CoreAudioBackend()

class GameAudioController:
    def __init__(self, backend=None, names: Tuple[str, ...]=GAME_EXES, log: Optional[Callable[[str], None]]=None):
        self._backend = backend
        self._names = tuple((n.lower() for n in names))
        self.log = log or (lambda _m: None)
        self._lock = threading.Lock()
        self._before = {}
        self._muted_by_us = {}
        self._registered = False

    def _backend_or_default(self):
        if self._backend is None:
            self._backend = default_backend()
        return self._backend

    def _game_sessions(self) -> List[Session]:
        return [s for s in self._backend_or_default().sessions() if s.name in self._names]

    def mute(self) -> int:
        n = 0
        try:
            with self._lock:
                if not self._registered:
                    atexit.register(self.restore)
                    self._registered = True
                for s in self._game_sessions():
                    if s.pid in self._muted_by_us:
                        continue
                    try:
                        try:
                            was = bool(s.get_mute())
                            self._before[s.pid] = was
                            if not was:
                                s.set_mute(True)
                                self._muted_by_us[s.pid] = s
                                n += 1
                        except Exception:
                            continue
                    finally:
                        pass
        except Exception:
            pass
        try:
            pass
        except Exception:
            pass
        if n:
            self.log('auto-silencer: game muted')
        return n

    def refresh(self) -> int:
        return self.mute()

    def restore(self) -> int:
        n = 0
        try:
            with self._lock:
                for pid, s in list(self._muted_by_us.items()):
                    try:
                        try:
                            if not self._before.get(pid, False):
                                s.set_mute(False)
                                n += 1
                        except Exception:
                            continue
                    finally:
                        pass
        except Exception:
            pass
        self._muted_by_us.clear()
        self._before.clear()
        try:
            pass
        except Exception:
            pass
        if n:
            self.log('auto-silencer: game sound restored')
        return n


# WARNING: Decompyle incomplete
