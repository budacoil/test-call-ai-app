import os
import tkinter as tk
import config
import i18n
from vision import capture_screen

class SnipOverlay:
    def __init__(self, root: tk.Tk, key: str, on_done, lang: str='ja'):
        from PIL import Image, ImageTk
        self.key, self.on_done, self.lang = key, on_done, lang
        frame, _, _ = capture_screen(1)
        self.img = Image.fromarray(frame[:, :, ::-1])
        self.top = tk.Toplevel(root)
        self.top.attributes('-fullscreen', True)
        self.top.attributes('-topmost', True)
        self.photo = ImageTk.PhotoImage(self.img)
        self.cv = tk.Canvas(self.top, cursor='cross', highlightthickness=0)
        self.cv.pack(fill='both', expand=True)
        self.cv.create_image(0, 0, image=self.photo, anchor='nw')
        self.start = None
        self.rect = None
        self.cv.bind('<ButtonPress-1>', self._down)
        self.cv.bind('<B1-Motion>', self._drag)
        self.cv.bind('<ButtonRelease-1>', self._up)
        self.top.bind('<Escape>', (lambda e: self._close(None)))

    def _down(self, e):
        self.start = e.x, e.y
        self.rect = self.cv.create_rectangle(e.x, e.y, e.x, e.y, outline='red', width=2)

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
            self._close(None, i18n.t(self.lang, 'log_too_large'))
            return
        self.img.crop((x0, y0, x1, y1)).save(path)
        self._close(path)

    def _close(self, path, error=None):
        self.top.destroy()
        self.on_done(path, error)


