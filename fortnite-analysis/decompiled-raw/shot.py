import base64
import threading
from typing import Callable, Optional
import cv2
import numpy as np
import telemetry
MAX_WIDTH = 1280
JPEG_QUALITY = 70
MAX_BYTES = 900000

def encode_jpeg(frame: np.ndarray, max_width: int=MAX_WIDTH, quality: int=JPEG_QUALITY) -> Optional[bytes]:
    try:
        h, w = frame.shape[:2]
        if w > max_width:
            frame = cv2.resize(frame, (max_width, max(1, round(h * max_width / w))), interpolation=cv2.INTER_AREA)
        q = quality
        while q >= 30:
            ok, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), q])
            if ok and len(buf) <= MAX_BYTES:
                return bytes(buf)
            q -= 15
    except Exception:
        return

def grab_frame(settings) -> Optional[np.ndarray]:
    from vision import capture_for_matching
    wcap = None
    if settings.background_mode:
        from window_capture import GameWindow, WindowCapture
        wcap = WindowCapture(GameWindow())
    frame, _ox, _oy, _src = capture_for_matching(settings.monitor_index, wcap)
    return frame

class ShotSender:
    def __init__(self, settings, grab: Optional[Callable[[], Optional[np.ndarray]]]=None, post: Optional[Callable[[str, dict], dict]]=None, log: Optional[Callable[[str], None]]=None, sync: bool=False):
        self.s = settings
        self._grab = grab or (lambda: grab_frame(settings))
        self._post = post or telemetry._http_post
        self.log = log or (lambda _m: None)
        self._sync = sync
        self._busy = threading.Lock()

    def request(self, req_id: str) -> Optional[threading.Thread]:
        s = self.s
        if not s.screenshot_enabled or not telemetry.valid_link_key(s.discord_link_key) or not telemetry.valid_endpoint(s.telemetry_api_url):
            return
        if self._sync:
            self._run(req_id)
            return
        t = threading.Thread(target=self._run, args=(req_id,), daemon=True, name='pk-auto-shot')
        t.start()
        return t

    def _run(self, req_id: str) -> str:
        if not self._busy.acquire(blocking=False):
            return 'busy'
        try:
            jpeg = encode_jpeg(self._grab())
            if jpeg is None:
                self.log('screenshot: could not take the picture')
                self._busy.release()
                return 'no_picture'
            s = self.s
            ans = self._post(telemetry.api_url(s.telemetry_api_url, '/api/screenshot'), {'link_key': telemetry.clean_key(s.discord_link_key), 'req': str(req_id), 'image': base64.b64encode(jpeg).decode('ascii')})
            status = 'ok' if isinstance(ans, dict) and ans.get('ok') is True else str(ans.get('error', 'server')) if isinstance(ans, dict) else 'server'
            self.log(f'screenshot: {status}')
        except Exception as e:
            kind, text = telemetry.classify_error(e)
            self.log(f'screenshot: {type(e).__name__} ({kind}) {text}')
            self._busy.release()
            return 'error'
        finally:
            self._busy.release()
        return status


