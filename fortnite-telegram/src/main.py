import ctypes
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

import keyboard
from PIL import Image, ImageTk

def _enable_dpi_awareness():
    try:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

_enable_dpi_awareness()

import config
import i18n
from anti_afk import AntiAfk
from config import Settings
from controller import Controller
from focus import WinApi, find_game
from mode_b import ModeB
from state_machine import State, StateMachine
from vision import capture_screen, find_template, load_template_auto

TITLE = "twitter:4z5pk"

def load_templates(lang):
    return {
        k: (load_template_auto(config.template_path(k, lang), config.PLATES.get(k)) if config.uses_template(k, lang) else None)
        for k in config.TEMPLATE_NAMES
    }

class Worker(threading.Thread):
    def __init__(self, settings, log_q, status):
        super().__init__(daemon=True)
        self.s = settings
        self.log_q = log_q
        self.status = status
        self.stop_event = threading.Event()

    def _load_templates(self, lang):
        templates = load_templates(lang)
        for k, v in templates.items():
            if v is None and k not in config.OPTIONAL_TEMPLATES and config.uses_template(k, lang):
                self.log_q.put(f"template missing: {config.template_filename(k, lang)}")
        return templates

    def run(self):
        lang = self.s.lang
        templates = self._load_templates(lang)

        ctrl = Controller(self.s)
        machines = {"A": StateMachine(self.s, templates, ctrl), "B": ModeB(self.s, templates, ctrl)}
        mode = self.s.mode if self.s.mode in machines else "A"
        sm = machines[mode]
        sm.start()

        afk = AntiAfk(self.s, active=lambda: sm.state is State.IN_MATCH)
        afk_thread = threading.Thread(target=afk.run, args=(self.stop_event, self.log_q.put), daemon=True)
        afk_thread.start()
        last_note, last_score = "", -1.0
        while not self.stop_event.is_set():
            try:
                if self.s.lang != lang:
                    lang = self.s.lang
                    templates = self._load_templates(lang)
                    for m in machines.values():
                        m.templates = templates
                if self.s.mode != mode and self.s.mode in machines:
                    sm.stop()
                    mode = self.s.mode
                    sm = machines[mode]
                    sm.start()
                frame, ox, oy = capture_screen(self.s.monitor_index)
                r = sm.step(frame, ox, oy)
                self.status.update(state=r.state.value, score=r.score, loops=sm.loops)
                if r.note != last_note or r.clicked or abs(r.score - last_score) > 0.1:
                    self.log_q.put(f"[{r.state.value}] {r.note} ({r.score:.2f}/{self.s.threshold:.2f})")
                    last_note, last_score = r.note, r.score
            except Exception as e:
                self.log_q.put(f"error: {e}")
            self.stop_event.wait(self.s.poll_interval)
        afk_thread.join(timeout=2)
        self.status.update(state=State.IDLE.value, score=0.0)

class SnipOverlay:

    def __init__(self, root, key, on_done, lang = "ja"):
        self.key, self.on_done, self.lang = key, on_done, lang
        frame, _, _ = capture_screen(1)
        self.img = Image.fromarray(frame[:, :, ::-1])
        self.top = tk.Toplevel(root)
        self.top.attributes("-fullscreen", True)
        self.top.attributes("-topmost", True)
        self.photo = ImageTk.PhotoImage(self.img)
        self.cv = tk.Canvas(self.top, cursor="cross", highlightthickness=0)
        self.cv.pack(fill="both", expand=True)
        self.cv.create_image(0, 0, image=self.photo, anchor="nw")
        self.start = None
        self.rect = None
        self.cv.bind("<ButtonPress-1>", self._down)
        self.cv.bind("<B1-Motion>", self._drag)
        self.cv.bind("<ButtonRelease-1>", self._up)
        self.top.bind("<Escape>", lambda e: self._close(None))

    def _down(self, e):
        self.start = (e.x, e.y)
        self.rect = self.cv.create_rectangle(e.x, e.y, e.x, e.y, outline="red", width=2)

    def _drag(self, e):
        if self.rect:
            self.cv.coords(self.rect, self.start[0], self.start[1], e.x, e.y)

    def _up(self, e):
        if not self.start:
            return
        x0, x1 = sorted((self.start[0], e.x))
        y0, y1 = sorted((self.start[1], e.y))
        if x1 - x0 < 5 or y1 - y0 < 5:
            return self._close(None)
        os.makedirs(config.assets_dir(), exist_ok=True)
        path = config.external_template_path(self.key, self.lang)
        w, h = self.img.size
        if (x1 - x0) * (y1 - y0) > 0.15 * w * h:
            self._close(None, i18n.t(self.lang, "log_too_large"))
            return
        self.img.crop((x0, y0, x1, y1)).save(path)
        self._close(path)

    def _close(self, path, error=None):
        self.top.destroy()
        self.on_done(path, error)

class App:
    def __init__(self):
        self.s = Settings()
        self.log_q = queue.Queue()
        self.status = {"state": State.IDLE.value, "score": 0.0, "loops": 0}
        self.worker = None
        self._tr = []

        self.root = tk.Tk()
        self.root.title("pk-auto")
        r = self.root
        k = r.winfo_fpixels("1i") / 96.0
        r.geometry(f"{int(480 * k)}x{int(690 * k)}")

        ttk.Label(r, text=TITLE, font=("Segoe UI", 16, "bold")).pack(pady=(8, 0))

        self.nb = ttk.Notebook(r)
        self.nb.pack(fill="both", expand=True, padx=6, pady=6)
        self.ctl = ttk.Frame(self.nb)
        self.gd = ttk.Frame(self.nb)
        self.nb.add(self.ctl, text="")
        self.nb.add(self.gd, text="")
        self._build_control(self.ctl)
        self._build_guide(self.gd)

        self._apply_lang()
        self._start_hotkey()
        self.root.after(200, self._tick)
        self.root.protocol("WM_DELETE_WINDOW", self._quit)

    def _l(self, widget, key):
        self._tr.append((widget, key))
        return widget

    def _build_control(self, r):
        self.info_var = tk.StringVar()
        ttk.Label(r, textvariable=self.info_var).pack(pady=(6, 0))

        row = ttk.Frame(r)
        row.pack(pady=6)
        self.btn = ttk.Button(row, command=self.toggle)
        self.btn.pack(side="left", padx=4)
        self.top_var = tk.BooleanVar(value=False)
        self._l(ttk.Checkbutton(row, variable=self.top_var, command=lambda: self.root.attributes("-topmost", self.top_var.get())), "topmost").pack(side="left")

        lang_row = ttk.Frame(r)
        lang_row.pack(pady=(0, 4))
        self._l(ttk.Label(lang_row), "lang_label").pack(side="left", padx=4)
        self.lang_var = tk.StringVar(value=config.LANGS[self.s.lang])
        lang_box = ttk.Combobox(lang_row, textvariable=self.lang_var, values=list(config.LANGS.values()), width=16, state="readonly")
        lang_box.pack(side="left")
        lang_box.bind("<<ComboboxSelected>>", self._on_lang)

        self.mode_var = tk.StringVar(value=self.s.mode)
        for code in config.MODES:
            self._l(ttk.Radiobutton(r, value=code, variable=self.mode_var, command=self._on_mode), f"mode_{code}").pack(anchor="w", padx=16)
        wait_row = ttk.Frame(r)
        wait_row.pack(pady=2)
        self.wait_b_var = tk.StringVar(value=f"{self.s.wait_b}")
        self._l(ttk.Label(wait_row), "b_pre").pack(side="left")
        ttk.Spinbox(wait_row, from_=10, to=600, increment=5, width=5, textvariable=self.wait_b_var).pack(side="left", padx=2)
        self._l(ttk.Label(wait_row), "b_post").pack(side="left")
        self.wait_b_var.trace_add("write", lambda *_: self._on_afk_num("wait_b", self.wait_b_var, 10.0, 600.0))

        self.afk_var = tk.BooleanVar(value=self.s.afk_enabled)
        self._l(
            ttk.Checkbutton(r, variable=self.afk_var, command=lambda: setattr(self.s, "afk_enabled", self.afk_var.get())),
            "afk_check",
        ).pack()

        afk_row = ttk.Frame(r)
        afk_row.pack(pady=2)
        self.afk_int_var = tk.StringVar(value=f"{self.s.afk_interval}")
        self.afk_hold_var = tk.StringVar(value=f"{self.s.afk_hold}")
        self._l(ttk.Label(afk_row), "afk_pre").pack(side="left")
        ttk.Spinbox(afk_row, from_=1, to=600, increment=1, width=5, textvariable=self.afk_int_var).pack(side="left", padx=2)
        self._l(ttk.Label(afk_row), "afk_mid").pack(side="left")
        ttk.Spinbox(afk_row, from_=0.5, to=30, increment=0.5, width=5, textvariable=self.afk_hold_var).pack(side="left", padx=2)
        self._l(ttk.Label(afk_row), "afk_post").pack(side="left")
        self.afk_int_var.trace_add("write", lambda *_: self._on_afk_num("afk_interval", self.afk_int_var, 1.0, 600.0))
        self.afk_hold_var.trace_add("write", lambda *_: self._on_afk_num("afk_hold", self.afk_hold_var, 0.5, 30.0))

        self.th_var = tk.DoubleVar(value=self.s.threshold)
        self._l(ttk.Label(r), "threshold").pack()
        ttk.Scale(r, from_=0.5, to=0.95, variable=self.th_var, command=self._on_th).pack(fill="x", padx=12)
        self.th_lbl = ttk.Label(r, text=f"{self.s.threshold:.2f}")
        self.th_lbl.pack()

        cap = ttk.Frame(r)
        cap.pack(pady=4)
        self.cap_key = tk.StringVar(value="play")
        ttk.Combobox(cap, textvariable=self.cap_key, values=list(config.TEMPLATE_NAMES), width=14, state="readonly").pack(side="left", padx=4)
        self._l(ttk.Button(cap, command=self.capture_template), "crop").pack(side="left")

        self.log = tk.Text(r, height=9, state="disabled", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=8, pady=6)

    def _build_guide(self, r):
        sb = ttk.Scrollbar(r, orient="vertical")
        self.guide_txt = tk.Text(r, wrap="word", state="disabled", font=("Segoe UI", 10), padx=10, pady=6, relief="flat", yscrollcommand=sb.set)
        sb.config(command=self.guide_txt.yview)
        sb.pack(side="right", fill="y")
        self.guide_txt.pack(side="left", fill="both", expand=True)
        g = self.guide_txt
        g.tag_configure("p", spacing3=4)
        g.tag_configure("n", lmargin1=12, lmargin2=30, spacing3=2)
        g.tag_configure("li", lmargin1=12, lmargin2=26, spacing3=2)

    def _render_guide(self):
        g = self.guide_txt
        family = "Yu Gothic UI" if self.s.lang == "ja" else "Segoe UI"

        g.config(state="normal", font=(family, 10), wrap="char" if self.s.lang == "ja" else "word")
        g.tag_configure("h1", font=(family, 12, "bold"), spacing1=12, spacing3=4)
        g.tag_configure("h2", font=(family, 10, "bold"), spacing1=8, spacing3=2)
        g.delete("1.0", "end")
        for kind, text in i18n.guide(self.s.lang):
            g.insert("end", ("•  " if kind == "li" else "") + text + "\n", kind)
        g.config(state="disabled")
        g.yview_moveto(0)

    def _apply_lang(self):
        lang = i18n.norm(self.s.lang)
        for widget, key in self._tr:
            widget.config(text=i18n.t(lang, key))
        self.nb.tab(self.ctl, text=i18n.t(lang, "tab_control"))
        self.nb.tab(self.gd, text=i18n.t(lang, "tab_guide"))
        self._refresh_btn()
        self._show(self.status["state"], self.status["score"], self.status["loops"])
        self._render_guide()

    def _running(self):
        return bool(self.worker and self.worker.is_alive() and not self.worker.stop_event.is_set())

    def _refresh_btn(self):
        self.btn.config(text=i18n.t(self.s.lang, "stop" if self._running() else "start"))

    def _on_th(self, _v):
        self.s.threshold = round(self.th_var.get(), 2)
        self.th_lbl.config(text=f"{self.s.threshold:.2f}")

    def _on_lang(self, _event=None):
        for code, name in config.LANGS.items():
            if name == self.lang_var.get():
                self.s.lang = code
                self._apply_lang()
                self._log(i18n.t(code, "log_language", name=name))

    def _on_mode(self):
        self.s.mode = self.mode_var.get()
        self._log(i18n.t(self.s.lang, "log_mode", name=i18n.t(self.s.lang, f"mode_{self.s.mode}")))

    def _on_afk_num(self, attr, var, lo, hi):
        try:
            v = float(var.get())
        except ValueError:
            return
        if lo <= v <= hi:
            setattr(self.s, attr, v)

    def _show(self, state, score, loops):
        self.info_var.set(i18n.t(self.s.lang, "info", state=state, score=score, loops=loops))

    def toggle(self):
        if self._running():
            self.stop()
        else:
            self.worker = Worker(self.s, self.log_q, self.status)
            self.worker.start()
            self._refresh_btn()
            self._log(i18n.t(self.s.lang, "log_started"))

    def stop(self):
        if self.worker:
            self.worker.stop_event.set()
        self._refresh_btn()
        self._show("IDLE", 0.0, self.status.get("loops", 0))
        self._log(i18n.t(self.s.lang, "log_stopped"))

    def capture_template(self):
        key = self.cap_key.get()
        self.root.withdraw()

        def go():
            def done(path, error=None):
                self.root.deiconify()
                self._log(i18n.t(self.s.lang, "log_saved", path=path) if path else (error or i18n.t(self.s.lang, "log_cancelled")))

            try:
                SnipOverlay(self.root, key, done, self.s.lang)
            except Exception as e:
                self.root.deiconify()
                self._log(i18n.t(self.s.lang, "log_capture_error", error=e))

        self.root.after(300, go)

    def _start_hotkey(self):
        def listen():
            try:
                keyboard.add_hotkey("f8", lambda: self.root.after(0, self.stop))
                keyboard.wait()
            except Exception as e:
                self.log_q.put(f"hotkey error: {e}")

        threading.Thread(target=listen, daemon=True).start()

    def _log(self, msg):
        self.log.config(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')} {msg}\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _tick(self):
        while True:
            try:
                self._log(self.log_q.get_nowait())
            except queue.Empty:
                break
        if self._running():
            self._show(self.status["state"], self.status["score"], self.status["loops"])
        self.root.after(200, self._tick)

    def _quit(self):
        if self.worker:
            self.worker.stop_event.set()
            self.worker.join(timeout=3)
        self.root.destroy()

    def run(self):
        self.root.mainloop()

def selftest(out_path):
    lines = []
    for lang in config.LANGS:
        for k in config.TEMPLATE_NAMES:
            path = config.template_path(k, lang)
            if config.uses_template(k, lang):
                lines.append(f"template {lang}:{k}: loaded={load_template_auto(path, config.PLATES.get(k)) is not None} {path}")
    for mod in ("cv2", "numpy", "mss", "pydirectinput", "keyboard", "PIL.Image", "PIL.ImageTk", "tkinter.ttk"):
        try:
            __import__(mod)
            lines.append(f"import {mod}: ok")
        except Exception as e:
            lines.append(f"import {mod}: FAIL {e}")
    for lang in config.LANGS:
        ok = all(i18n.t(lang, key) != key for key in i18n.UI["en"]) and len(i18n.guide(lang)) == len(i18n.guide("en"))
        lines.append(f"i18n {lang}: {'ok' if ok else 'FAIL'}")
    try:
        lines.append(f"focus: ok game_window={find_game(WinApi())}")
    except Exception as e:
        lines.append(f"focus: FAIL {e}")
    try:
        frame, _, _ = capture_screen(1)
        lines.append(f"capture: ok {frame.shape}")
        tpl = load_template_auto(config.template_path("play"))
        m, score = find_template(frame, tpl, 0.99, config.Settings().scales)
        lines.append(f"match: ok score={score:.2f}")
    except Exception as e:
        lines.append(f"capture/match: FAIL {e}")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2])
    else:
        App().run()
