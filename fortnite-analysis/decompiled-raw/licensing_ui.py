import queue
import threading
from tkinter import messagebox, simpledialog
import config
import i18n
import licensing

def _t(app, key: str, **kw) -> str:
    return i18n.t(app.s.lang, key, **kw)

def gate(app, then) -> None:
    if not licensing.required() or licensing.is_fresh(app.s):
        then()
        return
    _check(app, app.s.license_key, then)

def _check(app, key: str, then) -> None:
    q = getattr(app, 'lic_q', None)
    if q is None:
        app.lic_q = (q := queue.Queue())
    def work() -> None:
        try:
            res = licensing.verify(app.s, key)
        except Exception:
            res = licensing.OFFLINE
        q.put((res, then))

    threading.Thread(target=work, daemon=True, name='pk-auto-license').start()

def poll(app) -> None:
    try:
        for line in licensing.pop_notices():
            app.log_q.put(line)
    except Exception:
        pass
    q = getattr(app, 'lic_q', None)
    while q is not None:
        try:
            res, then = q.get_nowait()
        except queue.Empty:
            return
        handle(app, res, then)

def handle(app, res: str, then) -> None:
    if res == licensing.OK:
        config.save_user_settings(app.s)
        then()
        return
    if res in (licensing.OFFLINE, licensing.BUSY):
        messagebox.showerror(_t(app, 'lic_title'), _t(app, 'lic_busy' if res == licensing.BUSY else 'lic_offline'), parent=app.root)
        return
    if res == licensing.SERVER:
        messagebox.showerror(_t(app, 'lic_title'), _t(app, 'lic_server'), parent=app.root)
        return
    reason = {licensing.INVALID: 'lic_invalid', licensing.USED: 'lic_used', licensing.REVOKED: 'lic_revoked'}.get(res, '')
    text = _t(app, 'lic_prompt') if not reason else _t(app, reason) + '\n\n' + _t(app, 'lic_prompt')
    key = simpledialog.askstring(_t(app, 'lic_title'), text, parent=app.root)
    if key:
        if key.strip():
            _check(app, key, then)

def startup(app) -> bool:
    if not licensing.required() or licensing.is_fresh(app.s):
        return True
    key = app.s.license_key
    while True:
        try:
            res = licensing.verify(app.s, key)
        except Exception:
            res = licensing.OFFLINE
        if res == licensing.OK:
            config.save_user_settings(app.s)
            return True
        if res in (licensing.OFFLINE, licensing.SERVER, licensing.BUSY):
            messagebox.showerror(_t(app, 'lic_title'), _t(app, {licensing.OFFLINE: 'lic_offline', licensing.BUSY: 'lic_busy'}.get(res, 'lic_server')), parent=app.root)
            return False
        reason = {licensing.INVALID: 'lic_invalid', licensing.USED: 'lic_used', licensing.REVOKED: 'lic_revoked'}.get(res, '')
        text = _t(app, 'lic_prompt') if not reason else _t(app, reason) + '\n\n' + _t(app, 'lic_prompt')
        key = simpledialog.askstring(_t(app, 'lic_title'), text, parent=app.root)
        if not key or not key.strip():
            return False

