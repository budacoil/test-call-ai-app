import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk
from typing import Optional
import i18n
from updater import (AutoUpdater, UpdateError, UpdateInfo)
from version import GITHUB_REPO, __version__
WHY_KEYS = {'verify': 'upd_err_verify', 'network': 'upd_err_network', 'not_writable': 'upd_err_write'}
AUTO_CHECK_DELAY_MS = 1500

class UpdateDialog:
    def __init__(self, ctl: 'UpdateController', info: UpdateInfo):
        self.ctl, self.info = ctl, info
        t, root = ctl.t, ctl.app.root
        k = root.winfo_fpixels('1i') / 96.0
        self.top = tk.Toplevel(root)
        self.top.title(t('upd_title'))
        self.top.transient(root)
        self.top.resizable(False, False)
        self.top.protocol('WM_DELETE_WINDOW', self.later)
        box = ttk.Frame(self.top, padding=14)
        box.pack(fill='both', expand=True)
        ttk.Label(box, text=t('upd_title'), font=('Segoe UI', 13, 'bold')).pack(anchor='w')
        ttk.Label(box, text=t('upd_newver', new=info.latest_version, cur=__version__)).pack(anchor='w', pady=(2, 8))
        ttk.Label(box, text=t('upd_notes'), font=('Segoe UI', 9, 'bold')).pack(anchor='w')
        frame = ttk.Frame(box)
        frame.pack(fill='both', expand=True, pady=(2, 8))
        sb = ttk.Scrollbar(frame, orient='vertical')
        self.notes = tk.Text(frame, width=int(58), height=10, wrap='word', font=('Segoe UI', 9), relief='flat', yscrollcommand=sb.set)
        sb.config(command=self.notes.yview)
        sb.pack(side='right', fill='y')
        self.notes.pack(side='left', fill='both', expand=True)
        self.notes.insert('1.0', info.release_notes.strip() or '-')
        self.notes.config(state='disabled')
        self.bar = ttk.Progressbar(box, maximum=100, length=int(440 * k))
        self.msg = ttk.Label(box, text='', wraplength=int(440 * k))
        self.bar.pack(fill='x')
        self.msg.pack(anchor='w', pady=(4, 8))
        row = ttk.Frame(box)
        row.pack(anchor='e')
        can_install = ctl.updater.can_self_replace
        self.now_btn = ttk.Button(row, text=t('upd_now' if can_install else 'upd_page'), command=ctl.install)
        self.later_btn = ttk.Button(row, text=t('upd_later'), command=self.later)
        self.now_btn.pack(side='left', padx=4)
        self.later_btn.pack(side='left')
        if not can_install:
            self.msg.config(text=t('upd_dev'))
        self.top.update_idletasks()
        x = root.winfo_rootx() + max(0, (root.winfo_width() - self.top.winfo_reqwidth()) // 2)
        self.top.geometry(f'+{x}+{root.winfo_rooty() + int(60 * k)}')

    def alive(self) -> bool:
        try:
            return bool(self.top.winfo_exists())
        except tk.TclError:
            return False

    def lift(self) -> None:
        self.top.deiconify()
        self.top.lift()

    def set_progress(self, pct: int) -> None:
        self.bar['value'] = pct
        self.msg.config(text=self.ctl.t('upd_downloading', pct=pct))

    def installing(self) -> None:
        self.bar['value'] = 100
        self.msg.config(text=self.ctl.t('upd_installing'))
        self.now_btn.state(['disabled'])
        self.later_btn.state(['disabled'])

    def busy(self) -> None:
        self.now_btn.state(['disabled'])
        self.later_btn.state(['disabled'])
        self.set_progress(0)

    def error(self, why: str) -> None:
        self.bar['value'] = 0
        self.msg.config(text=self.ctl.t('upd_error', why=self.ctl.t(WHY_KEYS.get(why, 'upd_err_network'))))
        self.now_btn.state(['!disabled'])
        self.later_btn.state(['!disabled'])

    def later(self) -> None:
        if not self.ctl.installing:
            self.top.destroy()


class UpdateController:
    def __init__(self, app, updater: Optional[AutoUpdater]=None):
        self.app = app
        self.updater = updater or AutoUpdater()
        self.q = queue.Queue()
        self.info = None
        self.dialog = None
        self.notified = False
        self.checking = False
        self.installing = False
        self.status = None

    def t(self, key: str, **kw) -> str:
        return i18n.t(self.app.s.lang, key, **kw)

    def build_row(self, parent) -> None:
        self.status = tk.StringVar()
        row = ttk.Frame(parent)
        row.pack(pady=(0, 2))
        self.ver_lbl = ttk.Label(row, font=('Segoe UI', 9))
        self.ver_lbl.pack(side='left', padx=4)
        self.check_btn = ttk.Button(row, command=(lambda: self.check(manual=True)))
        self.check_btn.pack(side='left')
        self.auto_var = tk.BooleanVar(value=self.app.s.auto_update_check)
        self.auto_chk = ttk.Checkbutton(row, variable=self.auto_var, command=(lambda: setattr(self.app.s, 'auto_update_check', self.auto_var.get())))
        self.auto_chk.pack(side='left', padx=6)
        ttk.Label(parent, textvariable=self.status, font=('Segoe UI', 8), foreground='#666666').pack()
        self.banner = ttk.Frame(parent)
        self.banner_lbl = ttk.Label(self.banner, foreground='#0b5cad', font=('Segoe UI', 9, 'bold'))
        self.banner_btn = ttk.Button(self.banner, command=self.open_dialog)
        self.banner_lbl.pack(side='left', padx=6)
        self.banner_btn.pack(side='left')

    def relabel(self) -> None:
        self.ver_lbl.config(text=self.t('upd_ver', cur=__version__))
        self.check_btn.config(text=self.t('upd_check'))
        self.auto_chk.config(text=self.t('upd_auto'))
        self.banner_btn.config(text=self.t('upd_details'))
        if self.info:
            self.banner_lbl.config(text=self.t('upd_banner', new=self.info.latest_version))

    def _show_banner(self) -> None:
        self.relabel()
        if not self.banner.winfo_ismapped():
            self.banner.pack(before=self.app.nb, fill='x', padx=6, pady=(0, 2))

    def start_auto_check(self) -> None:
        if self.app.s.auto_update_check:
            self.app.root.after(AUTO_CHECK_DELAY_MS, (lambda: self.check(manual=False)))

    def check(self, manual: bool) -> None:
        if self.checking or self.installing:
            return
        self.checking = True
        if manual:
            self.status.set(self.t('upd_checking'))
        self.updater.check_async((lambda info: self.q.put(('check', info, manual, self.updater.last_error))))

    def open_dialog(self) -> None:
        if not self.info:
            return
        if self.dialog and self.dialog.alive():
            self.dialog.lift()
            return
        self.dialog = UpdateDialog(self, self.info)

    def install(self) -> None:
        info = self.info
        if not info or self.installing:
            return
        if not self.updater.can_self_replace:
            webbrowser.open(info.page_url or f'https://github.com/{GITHUB_REPO}/releases/latest')
            return
        self.installing = True
        self.dialog.busy()
        def work():
            try:
                staged = self.updater.download_update(info, (lambda p: self.q.put(('progress', p))))
                self.q.put(('staged', staged))
                return
            except UpdateError as e:
                self.q.put(('failed', str(e.args[0]) if e.args else 'network'))
            except Exception:
                self.q.put(('failed', 'network'))
            e = None
            del e
            if Exception:
                self.q.put(('failed', 'network'))

        threading.Thread(target=work, daemon=True, name='pk-auto-update-download').start()

    def _apply(self, staged: str) -> bool:
        self.dialog.installing()
        try:
            self.updater.launch_runner(staged)
        except Exception as e:
            self.installing = False
            self.dialog.error(str(e.args[0]) if isinstance(e, UpdateError) and e.args else 'not_writable')
            return False
        self.app._quit()
        return True

    def poll(self) -> bool:
        while True:
            try:
                msg = self.q.get_nowait()
            except queue.Empty:
                return False
            kind = msg[0]
            if kind == 'check':
                _, info, manual, err = msg
                self.checking = False
                if info:
                    self.info = info
                    self.status.set('')
                    self._show_banner()
                    if manual or not self.notified:
                        self.notified = True
                        self.open_dialog()
                elif manual:
                    self.status.set(self.t('upd_check_failed' if err else 'upd_latest'))
            elif kind == 'progress' and self.dialog and self.dialog.alive():
                self.dialog.set_progress(msg[1])
            elif kind == 'failed':
                self.installing = False
                if self.dialog and self.dialog.alive():
                    self.dialog.error(msg[1])
            elif kind == 'staged' and self._apply(msg[1]):
                return True


# WARNING: Decompyle incomplete
