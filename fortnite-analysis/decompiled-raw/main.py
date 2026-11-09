import os
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import ttk

def _enable_dpi_awareness() -> None:
    try:
        import ctypes
    except Exception:
        return
    try:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            return
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        return

_enable_dpi_awareness()
import config
import i18n
import remote
import gui_extras
import licensing_ui
import relay
import rescue
import shot
from config import Settings
from snip import SnipOverlay
from state_machine import State
from telemetry import TelemetryManager, clean_key
from update_ui import UpdateController
from vision import capture_screen, load_template_auto
from worker import Worker, load_templates
TITLE = 'twitter:4z5pk'

class App:
    def __init__(self) -> None:
        self.s = Settings()
        self.log_q = queue.Queue()
        self.status = {'state': State.IDLE.value, 'score': 0.0, 'loops': 0}
        self.worker = None
        self._tr = []
        config.load_user_settings(self.s)
        relay.start(self.s)
        import ghost
        ghost.recover_at_launch(os.path.join(config.base_dir(), ghost.MARKER_NAME))
        self.tm = TelemetryManager(log=self.log_q.put)
        self._dm_q = queue.Queue()
        self._dm_status = ''
        self._diag_q = queue.Queue()
        self._diag_busy = False
        self._ac_q = queue.Queue()
        self._ac_busy = False
        self._cfg_q = queue.Queue()
        self.shots = shot.ShotSender(self.s, log=self.log_q.put)
        self.remote = remote.RemoteSync(self.s, on_config=(lambda cfg, rev: self._cfg_q.put(cfg)), on_shot=self.shots.request, on_rescue=rescue.push, log=self.log_q.put, active=(lambda: self._running()))
        self.tm.extra = self.remote.piggy_body
        self.tm.on_answer = self.remote.handle_answer
        self.root = tk.Tk()
        self.root.withdraw()
        if not licensing_ui.startup(self):
            self.root.destroy()
            raise SystemExit(0)
        self.root.deiconify()
        self.root.title('pk-auto')
        r = self.root
        k = r.winfo_fpixels('1i') / 96.0
        r.geometry(f'{int(480 * k)}x{min(int(840 * k), r.winfo_screenheight() - 90)}')
        ttk.Label(r, text=TITLE, font=('Segoe UI', 16, 'bold')).pack(pady=(8, 0))
        self.upd = UpdateController(self)
        self.upd.build_row(r)
        self._build_diag(r)
        self.nb = ttk.Notebook(r)
        self.nb.pack(fill='both', expand=True, padx=6, pady=6)
        self.ctl = ttk.Frame(self.nb)
        self.ex = ttk.Frame(self.nb)
        self.gd = ttk.Frame(self.nb)
        self.nb.add(self.ctl, text='')
        self.nb.add(self.ex, text='')
        self.nb.add(self.gd, text='')
        self._build_control(self.ctl)
        gui_extras.build(self, self.ex)
        self._build_guide(self.gd)
        self._apply_lang()
        self._start_hotkey()
        self.remote.start()
        self.upd.start_auto_check()
        self.root.after(200, self._tick)
        self.root.protocol('WM_DELETE_WINDOW', self._quit)

    def _l(self, widget, key: str):
        self._tr.append((widget, key))
        return widget

    def _build_control(self, r) -> None:
        self.info_var = tk.StringVar()
        ttk.Label(r, textvariable=self.info_var).pack(pady=(6, 0))
        row = ttk.Frame(r)
        row.pack(pady=6)
        self.btn = ttk.Button(row, command=self.toggle)
        self.btn.pack(side='left', padx=4)
        self.top_var = tk.BooleanVar(value=False)
        self._l(ttk.Checkbutton(row, variable=self.top_var, command=(lambda: self.root.attributes('-topmost', self.top_var.get()))), 'topmost').pack(side='left')
        lang_row = ttk.Frame(r)
        lang_row.pack(pady=(0, 4))
        self._l(ttk.Label(lang_row), 'lang_label').pack(side='left', padx=4)
        self.lang_var = tk.StringVar(value=config.LANGS[self.s.lang])
        lang_box = ttk.Combobox(lang_row, textvariable=self.lang_var, values=list(config.LANGS.values()), width=16, state='readonly')
        lang_box.pack(side='left')
        lang_box.bind('<<ComboboxSelected>>', self._on_lang)
        self._build_modes(r)
        self._build_keys(r)
        self._build_tail(r)

    def _build_modes(self, r) -> None:
        self.mode_var = tk.StringVar(value=self.s.mode)
        for code in config.MODES:
            self._l(ttk.Radiobutton(r, value=code, variable=self.mode_var, command=self._on_mode), f'mode_{code}').pack(anchor='w', padx=16)
        wait_row = ttk.Frame(r)
        wait_row.pack(pady=2)
        self.wait_b_var = tk.StringVar(value=f'{self.s.wait_b:g}')
        self._l(ttk.Label(wait_row), 'b_pre').pack(side='left')
        ttk.Spinbox(wait_row, from_=10, to=600, increment=5, width=5, textvariable=self.wait_b_var).pack(side='left', padx=2)
        self._l(ttk.Label(wait_row), 'b_post').pack(side='left')
        self.wait_b_var.trace_add('write', (lambda *_: self._on_afk_num('wait_b', self.wait_b_var, 10.0, 600.0)))
        wait_c_row = ttk.Frame(r)
        wait_c_row.pack(pady=2)
        self.wait_c_var = tk.StringVar(value=f'{self.s.wait_c:g}')
        self._l(ttk.Label(wait_c_row), 'c_pre').pack(side='left')
        ttk.Spinbox(wait_c_row, from_=10, to=600, increment=5, width=5, textvariable=self.wait_c_var).pack(side='left', padx=2)
        self._l(ttk.Label(wait_c_row), 'c_post').pack(side='left')
        self.wait_c_var.trace_add('write', (lambda *_: self._on_afk_num('wait_c', self.wait_c_var, 10.0, 600.0)))

    def _build_keys(self, r) -> None:
        self.bg_var = tk.BooleanVar(value=self.s.background_mode)
        self._l(ttk.Checkbutton(r, variable=self.bg_var, command=(lambda: setattr(self.s, 'background_mode', self.bg_var.get()))), 'bg_check').pack()
        self.ghost_var = tk.BooleanVar(value=self.s.background_ghost)
        self._l(ttk.Checkbutton(r, variable=self.ghost_var, command=(lambda: setattr(self.s, 'background_ghost', self.ghost_var.get()))), 'ghost_check').pack()
        self.ghost_show_var = tk.BooleanVar(value=self.s.ghost_show)
        self._l(ttk.Checkbutton(r, variable=self.ghost_show_var, command=(lambda: setattr(self.s, 'ghost_show', self.ghost_show_var.get()))), 'ghost_show_check').pack()
        self.afk_var = tk.BooleanVar(value=self.s.afk_enabled)
        self._l(ttk.Checkbutton(r, variable=self.afk_var, command=(lambda: setattr(self.s, 'afk_enabled', self.afk_var.get()))), 'afk_check').pack()
        afk_row = ttk.Frame(r)
        afk_row.pack(pady=2)
        self.afk_int_var = tk.StringVar(value=f'{self.s.afk_interval:g}')
        self.afk_hold_var = tk.StringVar(value=f'{self.s.afk_hold:g}')
        self._l(ttk.Label(afk_row), 'afk_pre').pack(side='left')
        ttk.Spinbox(afk_row, from_=1, to=600, increment=1, width=5, textvariable=self.afk_int_var).pack(side='left', padx=2)
        self._l(ttk.Label(afk_row), 'afk_mid').pack(side='left')
        ttk.Spinbox(afk_row, from_=0.5, to=30, increment=0.5, width=5, textvariable=self.afk_hold_var).pack(side='left', padx=2)
        self._l(ttk.Label(afk_row), 'afk_post').pack(side='left')
        self.afk_int_var.trace_add('write', (lambda *_: self._on_afk_num('afk_interval', self.afk_int_var, 1.0, 600.0)))
        self.afk_hold_var.trace_add('write', (lambda *_: self._on_afk_num('afk_hold', self.afk_hold_var, 0.5, 30.0)))
        self.space_var = tk.BooleanVar(value=self.s.space_enabled)
        self._l(ttk.Checkbutton(r, variable=self.space_var, command=(lambda: setattr(self.s, 'space_enabled', self.space_var.get()))), 'space_check').pack()
        space_row = ttk.Frame(r)
        space_row.pack(pady=2)
        self.space_sec_var = tk.StringVar(value=f'{self.s.space_seconds:g}')
        self.space_cnt_var = tk.StringVar(value=f'{self.s.space_count:g}')
        self._l(ttk.Label(space_row), 'space_pre').pack(side='left')
        ttk.Spinbox(space_row, from_=1, to=600, increment=1, width=5, textvariable=self.space_sec_var).pack(side='left', padx=2)
        self._l(ttk.Label(space_row), 'space_mid').pack(side='left')
        ttk.Spinbox(space_row, from_=1, to=50, increment=1, width=4, textvariable=self.space_cnt_var).pack(side='left', padx=2)
        self._l(ttk.Label(space_row), 'space_post').pack(side='left')
        self.space_sec_var.trace_add('write', (lambda *_: self._on_afk_num('space_seconds', self.space_sec_var, 1.0, 600.0)))
        self.space_cnt_var.trace_add('write', (lambda *_: self._on_space_count()))

    def _build_tail(self, r) -> None:
        self.th_var = tk.DoubleVar(value=self.s.threshold)
        self._l(ttk.Label(r), 'threshold').pack()
        ttk.Scale(r, from_=0.5, to=0.95, variable=self.th_var, command=self._on_th).pack(fill='x', padx=12)
        self.th_lbl = ttk.Label(r, text=f'{self.s.threshold:.2f}')
        self.th_lbl.pack()
        cap = ttk.Frame(r)
        cap.pack(pady=4)
        self.cap_key = tk.StringVar(value='play')
        ttk.Combobox(cap, textvariable=self.cap_key, values=list(config.TEMPLATE_NAMES), width=14, state='readonly').pack(side='left', padx=4)
        self._l(ttk.Button(cap, command=self.capture_template), 'crop').pack(side='left')
        self._build_discord(r)
        self.log = tk.Text(r, height=5, state='disabled', font=('Consolas', 9))
        self.log.pack(fill='both', expand=True, padx=8, pady=6)

    def _build_discord(self, r) -> None:
        lf = ttk.LabelFrame(r, text='Discord DM')
        lf.pack(fill='x', padx=10, pady=(2, 4))
        row = ttk.Frame(lf)
        row.pack(fill='x', padx=6, pady=(4, 0))
        self._l(ttk.Label(row), 'dm_key_label').pack(side='left')
        self.key_var = tk.StringVar(value=self.s.discord_link_key)
        self.key_var.trace_add('write', (lambda *_: setattr(self.s, 'discord_link_key', clean_key(self.key_var.get()))))
        entry = ttk.Entry(row, textvariable=self.key_var, show='•')
        entry.pack(side='left', fill='x', expand=True, padx=4)
        entry.bind('<FocusOut>', (lambda _e: self.remote.poke()))
        self._l(ttk.Button(row, command=self.send_test_dm), 'dm_test').pack(side='left')
        self.dm_status_var = tk.StringVar()
        ttk.Label(lf, textvariable=self.dm_status_var, font=('Segoe UI', 8)).pack(anchor='w', padx=8)
        self._l(ttk.Button(lf, command=self.fix_network), 'net_fix_button').pack(anchor='w', padx=8, pady=(0, 2))
        self.tele_var = tk.BooleanVar(value=self.s.telemetry_enabled)
        self._l(ttk.Checkbutton(lf, variable=self.tele_var, command=(lambda: setattr(self.s, 'telemetry_enabled', self.tele_var.get()))), 'dm_enabled').pack(anchor='w', padx=6)
        self.alert_var = tk.BooleanVar(value=self.s.alert_enabled)
        self._l(ttk.Checkbutton(lf, variable=self.alert_var, command=(lambda: setattr(self.s, 'alert_enabled', self.alert_var.get()))), 'alert_check').pack(anchor='w', padx=6)
        self.shot_var = tk.BooleanVar(value=self.s.screenshot_enabled)
        self._l(ttk.Checkbutton(lf, variable=self.shot_var, command=(lambda: (setattr(self.s, 'screenshot_enabled', self.shot_var.get()), self.remote.poke()))), 'shot_check').pack(anchor='w', padx=6)
        every = ttk.Frame(lf)
        every.pack(anchor='w', padx=6)
        self.report_var = tk.StringVar(value=f'{self.s.report_hours:g}')
        self._l(ttk.Label(every), 'dm_every_pre').pack(side='left')
        ttk.Spinbox(every, from_=0, to=24, increment=0.5, width=5, textvariable=self.report_var).pack(side='left', padx=2)
        self._l(ttk.Label(every), 'dm_every_post').pack(side='left')
        self.report_var.trace_add('write', (lambda *_: self._on_afk_num('report_hours', self.report_var, 0.0, 24.0)))
        self.remote_var = tk.BooleanVar(value=self.s.remote_enabled)
        self._l(ttk.Checkbutton(lf, variable=self.remote_var, command=(lambda: (setattr(self.s, 'remote_enabled', self.remote_var.get()), self.remote.poke()))), 'remote_enabled').pack(anchor='w', padx=6)
        k = self.root.winfo_fpixels('1i') / 96.0
        self._l(ttk.Label(lf, font=('Segoe UI', 8), wraplength=int(440 * k), foreground='#666666'), 'dm_desc').pack(anchor='w', padx=8, pady=(0, 2))
        self._l(ttk.Button(lf, command=self.open_invite), 'dm_join').pack(anchor='w', padx=8, pady=(0, 4))

    def _build_diag(self, r) -> None:
        row = ttk.Frame(r)
        row.pack(pady=(0, 2))
        self._l(ttk.Button(row, command=self.run_diagnose), 'diag_button').pack(side='left')
        self._l(ttk.Button(row, command=self.run_autocheck), 'ac_button').pack(side='left', padx=(6, 0))
        self.diag_var = tk.StringVar()
        ttk.Label(row, textvariable=self.diag_var, font=('Segoe UI', 8), foreground='#666666').pack(side='left', padx=6)

    def run_diagnose(self) -> None:
        if self._diag_busy:
            return
        import diagnose
        self._diag_busy = True
        self.diag_var.set(i18n.t(self.s.lang, 'diag_running'))
        path = diagnose.default_report_path()
        def work() -> None:
            try:
                diagnose.run(path)
                with open(path, 'r', encoding='utf-8') as f:
                    self._diag_q.put(('ok', path, f.read()))
            except Exception:
                self._diag_q.put(('fail', path, ''))

        threading.Thread(target=work, daemon=True, name='pk-auto-diagnose').start()

    def run_autocheck(self) -> None:
        if self._ac_busy:
            return
        import autocheck
        self._ac_busy = True
        self.diag_var.set(i18n.t(self.s.lang, 'ac_running'))
        lang = self.s.lang
        def work() -> None:
            try:
                self._ac_q.put(autocheck.format_items(autocheck.run_checks(self.s), lang))
                return
            except Exception as e:
                self._ac_q.put(f'error: {type(e).__name__}: {e}')

        threading.Thread(target=work, daemon=True, name='pk-auto-autocheck').start()

    def _autocheck_done(self, text: str) -> None:
        from tkinter import messagebox
        self._ac_busy = False
        self.diag_var.set('')
        messagebox.showinfo(i18n.t(self.s.lang, 'ac_title'), text, parent=self.root)

    def _diag_done(self, kind: str, path: str, text: str) -> None:
        self._diag_busy = False
        if kind != 'ok':
            self.diag_var.set(i18n.t(self.s.lang, 'diag_failed'))
            return
        self.diag_var.set(i18n.t(self.s.lang, 'diag_done', name=os.path.basename(path)))
        self._log(path)
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except Exception:
            pass
        try:
            os.startfile(path)
        except Exception:
            return

    def _build_guide(self, r) -> None:
        sb = ttk.Scrollbar(r, orient='vertical')
        self.guide_txt = tk.Text(r, wrap='word', state='disabled', font=('Segoe UI', 10), padx=10, pady=6, relief='flat', yscrollcommand=sb.set)
        sb.config(command=self.guide_txt.yview)
        sb.pack(side='right', fill='y')
        self.guide_txt.pack(side='left', fill='both', expand=True)
        g = self.guide_txt
        g.tag_configure('p', spacing3=4)
        g.tag_configure('n', lmargin1=12, lmargin2=30, spacing3=2)
        g.tag_configure('li', lmargin1=12, lmargin2=26, spacing3=2)

    def _render_guide(self) -> None:
        g = self.guide_txt
        family = 'Yu Gothic UI' if self.s.lang == 'ja' else 'Segoe UI'
        g.config(state='normal', font=(family, 10), wrap='char' if self.s.lang == 'ja' else 'word')
        g.tag_configure('h1', font=(family, 12, 'bold'), spacing1=12, spacing3=4)
        g.tag_configure('h2', font=(family, 10, 'bold'), spacing1=8, spacing3=2)
        g.delete('1.0', 'end')
        for kind, text in i18n.guide(self.s.lang):
            g.insert('end', ('•  ' if kind == 'li' else '') + text + '\n', kind)
        g.config(state='disabled')
        g.yview_moveto(0)

    def _apply_lang(self) -> None:
        lang = i18n.norm(self.s.lang)
        for widget, key in self._tr:
            widget.config(text=i18n.t(lang, key))
        self.nb.tab(self.ctl, text=i18n.t(lang, 'tab_control'))
        self.nb.tab(self.ex, text=i18n.t(lang, 'tab_extras'))
        self.nb.tab(self.gd, text=i18n.t(lang, 'tab_guide'))
        self._refresh_btn()
        self._show(self.status['state'], self.status['score'], self.status['loops'])
        self.dm_status_var.set(i18n.t(lang, f'dm_s_{self._dm_status}') if self._dm_status else '')
        self._render_guide()
        self.upd.relabel()

    def _running(self) -> bool:
        return bool(self.worker and self.worker.is_alive() and not self.worker.stop_event.is_set())

    def _refresh_btn(self) -> None:
        self.btn.config(text=i18n.t(self.s.lang, 'stop' if self._running() else 'start'))

    def _on_th(self, _v) -> None:
        self.s.threshold = round(self.th_var.get(), 2)
        self.th_lbl.config(text=f'{self.s.threshold:.2f}')

    def _on_lang(self, _event=None) -> None:
        for code, name in config.LANGS.items():
            if name == self.lang_var.get():
                self.s.lang = code
                self._apply_lang()
                self._log(i18n.t(code, 'log_language', name=name))

    def _on_mode(self) -> None:
        self.s.mode = self.mode_var.get()
        self._log(i18n.t(self.s.lang, 'log_mode', name=i18n.t(self.s.lang, f'mode_{self.s.mode}')))

    def _on_afk_num(self, attr: str, var: tk.StringVar, lo: float, hi: float) -> None:
        try:
            v = float(var.get())
        except ValueError:
            pass
        else:
            if lo <= v <= hi:
                setattr(self.s, attr, v)
                return

    def _on_space_count(self) -> None:
        try:
            v = float(self.space_cnt_var.get())
        except ValueError:
            pass
        else:
            if v == int(v):
                if 1 <= v <= 50:
                    self.s.space_count = int(v)
                    return
                return

    def _show(self, state: str, score: float, loops: int) -> None:
        self.info_var.set(i18n.t(self.s.lang, 'info', state=state, score=score, loops=loops))

    def toggle(self) -> None:
        if self._running():
            self.stop()
            return
        licensing_ui.gate(self, self._start_run)

    def _start_run(self) -> None:
        if not self._running():
            self.tm.begin_session(self.s.mode, self.s.lang)
            self.remote.poke()
            self.worker = Worker(self.s, self.log_q, self.status, self.tm)
            self.worker.start()
            self._refresh_btn()
            self._log(i18n.t(self.s.lang, 'log_started'))
            config.save_user_settings(self.s)

    def stop(self) -> None:
        if self.worker:
            self.worker.stop_event.set()
        self._refresh_btn()
        self._show('IDLE', 0.0, self.status.get('loops', 0))
        self._log(i18n.t(self.s.lang, 'log_stopped'))
        self._finish_session()

    def _finish_session(self) -> None:
        if self.s.telemetry_enabled:
            self.tm.send_session_summary(self.s.discord_link_key, self.s.telemetry_api_url)

    def _apply_remote(self, cfg: dict) -> None:
        changed = remote.apply_config(self.s, cfg)
        if not changed:
            return
        self.mode_var.set(self.s.mode)
        self.wait_b_var.set(f'{self.s.wait_b:g}')
        self.report_var.set(f'{self.s.report_hours:g}')
        self.afk_var.set(self.s.afk_enabled)
        self.afk_int_var.set(f'{self.s.afk_interval:g}')
        self.afk_hold_var.set(f'{self.s.afk_hold:g}')
        if 'lang' in changed:
            self.lang_var.set(config.LANGS[self.s.lang])
            self._apply_lang()
        self._log(i18n.t(self.s.lang, 'log_remote', what=', '.join((f'{k}={v[1]:g}' if isinstance(v[1], float) else f'{k}={v[1]}' for k, v in changed.items()))))
        config.save_user_settings(self.s)

    def open_invite(self) -> None:
        try:
            webbrowser.open(config.DISCORD_INVITE_URL)
            return
        except Exception as e:
            self._log(f'{config.DISCORD_INVITE_URL} ({type(e).__name__})')

    def send_test_dm(self) -> None:
        self.remote.poke()
        self._dm_status = 'sending'
        self.dm_status_var.set(i18n.t(self.s.lang, 'dm_s_sending'))
        self.tm.send_test_dm(self.s.discord_link_key, self.s.telemetry_api_url, callback=self._dm_q.put)
        config.save_user_settings(self.s)

    def fix_network(self) -> None:
        import netfix
        self._dm_q.put('fix_running')
        netfix.repair_async(self.s.telemetry_api_url, self._dm_q.put)

    def capture_template(self) -> None:
        key = self.cap_key.get()
        self.root.withdraw()
        def go():
            def done(path, error=None):
                self.root.deiconify()
                if path:
                    self._log(i18n.t(self.s.lang, 'log_saved', path=path))
                    return
                None(error or i18n.t(self.s.lang, 'log_cancelled'))

            try:
                SnipOverlay(self.root, key, done, self.s.lang)
                return
            except Exception as e:
                self.root.deiconify()
                self._log(i18n.t(self.s.lang, 'log_capture_error', error=e))

        self.root.after(300, go)

    def _start_hotkey(self) -> None:
        def listen():
            try:
                import keyboard
                keyboard.add_hotkey('f8', (lambda: self.root.after(0, self.stop)))
                keyboard.wait()
                return
            except Exception as e:
                self.log_q.put(f'hotkey error: {e}')

        threading.Thread(target=listen, daemon=True).start()

    def _log(self, msg: str) -> None:
        self.log.config(state='normal')
        self.log.insert('end', f'{time.strftime('%H:%M:%S')} {msg}\n')
        self.log.see('end')
        self.log.config(state='disabled')

    def _tick(self) -> None:
        if self.upd.poll():
            return
        licensing_ui.poll(self)
        while True:
            try:
                self._log(self.log_q.get_nowait())
            except queue.Empty:
                break
        try:
            self._apply_remote(self._cfg_q.get_nowait())
        except queue.Empty:
            pass
        while True:
            try:
                self._autocheck_done(self._ac_q.get_nowait())
            except queue.Empty:
                break
        while True:
            try:
                self._diag_done(*self._diag_q.get_nowait())
            except queue.Empty:
                break
        while True:
            try:
                self._dm_status = self._dm_q.get_nowait()
            except queue.Empty:
                break
            self.dm_status_var.set(i18n.t(self.s.lang, f'dm_s_{self._dm_status}'))
        if self._running():
            self._show(self.status['state'], self.status['score'], self.status['loops'])
        self.root.after(200, self._tick)

    def _quit(self) -> None:
        if self.worker:
            self.worker.stop_event.set()
            self.worker.join(timeout=3)
        self.remote.stop()
        self._finish_session()
        self.tm.flush(3.0)
        config.save_user_settings(self.s)
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def selftest(out_path: str) -> None:
    from vision import find_template
    lines = []
    for lang in config.LANGS:
        for k in config.TEMPLATE_NAMES:
            path = config.template_path(k, lang)
            if config.uses_template(k, lang):
                lines.append(f'template {lang}:{k}: loaded={load_template_auto(path, config.PLATES.get(k)) is not None} {path}')
    for mod in ('cv2', 'numpy', 'mss', 'pydirectinput', 'keyboard', 'PIL.Image', 'PIL.ImageTk', 'tkinter.ttk'):
        try:
            __import__(mod)
            lines.append(f'import {mod}: ok')
        except Exception as e:
            lines.append(f'import {mod}: FAIL {e}')
            continue
    for lang in config.LANGS:
        ok = all((i18n.t(lang, key) != key for key in i18n.UI['en'])) and len(i18n.guide(lang)) == len(i18n.guide('en'))
        lines.append(f'i18n {lang}: {'ok' if ok else 'FAIL'}')
    try:
        from focus import find_game, WinApi
        lines.append(f'focus: ok game_window={find_game(WinApi())}')
    except Exception as e:
        lines.append(f'focus: FAIL {e}')
    try:
        import telemetry
        if remote.clean_config({'mode': 'B', 'wait_b': 5}) != {'mode': 'B', 'wait_b': 10}:
            raise RuntimeError('remote.clean_config check failed')
        import space_press
        import updater
        import version
        import background_input
        import ghost
        import window_capture
        ghost.GhostApi()
        window_capture.Win32Gdi()
        background_input.Win32Input()
        lines.append(f'background: ok game_window={window_capture.GameWindow().hwnd()}')
        if not updater.is_newer('v99', version.__version__) or updater.is_newer('v0.1', version.__version__):
            raise RuntimeError('updater.is_newer check failed')
        lines.append(f'updater: ok version={version.__version__} replace_allowed={updater.AutoUpdater().can_self_replace}')
        sp = space_press.SpacePresser(config.Settings(space_enabled=True), active=(lambda: True), press=(lambda: None))
        lines.append(f'space: ok window_presses={len(sp._window(0.0)[0])}')
        tm = telemetry.TelemetryManager(sync=True)
        tm.begin_session()
        tm.record_action()
        no_key = tm.send_test_dm('', 'https://example.invalid') is None
        lines.append(f'telemetry: ok snapshot={tm.snapshot()['total_actions']} empty_key_blocked={no_key}')
        lines.append(f'certs: {'ok' if telemetry.bundled_context() else 'FAIL bundled root list missing'}')
    except Exception as e:
        lines.append(f'telemetry: FAIL {e}')
    try:
        frame, _, _ = capture_screen(1)
        lines.append(f'capture: ok {frame.shape}')
        tpl = load_template_auto(config.template_path('play'))
        m, score = find_template(frame, tpl, 0.99, config.Settings().scales)
        lines.append(f'match: ok score={score:.2f}')
    except Exception as e:
        lines.append(f'capture/match: FAIL {e}')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--selftest':
        selftest(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == '--diagnose':
        import diagnose
        diagnose.run(sys.argv[2])
    else:
        App().run()
# WARNING: Decompyle incomplete
