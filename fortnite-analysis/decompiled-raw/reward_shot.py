import base64
import threading
import time
from typing import Callable, Optional
import numpy as np
import shot
import telemetry
COOLDOWN_S = 300.0

class RewardShotSender:
    def __init__(self, settings, post: Optional[Callable[[str, dict], dict]]=None, log: Optional[Callable[[str], None]]=None, clock: Callable[[], float]=time.monotonic, sync: bool=False):
        self.s = settings
        self._post = post or telemetry._http_post
        self.log = log or (lambda _m: None)
        self._clock = clock
        self._sync = sync
        self._last = None
        self._busy = threading.Lock()
        self.sent = 0
        self.skipped = 0

    def allowed(self) -> bool:
        s = self.s
        return bool(getattr(s, 'reward_shot_enabled', False) and telemetry.valid_link_key(s.discord_link_key) and telemetry.valid_endpoint(s.telemetry_api_url))

    def notify(self, frame: np.ndarray) -> bool:
        try:
            if not self.allowed():
                return False
            now = self._clock()
            if self._last is not None and now - self._last < COOLDOWN_S:
                self.skipped += 1
                return False
            if not self._busy.acquire(blocking=False):
                return False
            self._last = now
            picture = np.array(frame, copy=True)
            if self._sync:
                self._run(picture)
                return True
            threading.Thread(target=self._run, args=(picture,), daemon=True, name='pk-auto-rewardshot').start()
            return True
        except Exception:
            return False

    def _run(self, frame: np.ndarray) -> str:
        try:
            jpeg = shot.encode_jpeg(frame)
            if jpeg is None:
                self.log('reward screen: could not encode the picture')
                self._busy.release()
                return 'no_picture'
            s = self.s
            ans = self._post(telemetry.api_url(s.telemetry_api_url, '/api/reward-shot'), {'link_key': telemetry.clean_key(s.discord_link_key), 'image': base64.b64encode(jpeg).decode('ascii')})
            ok = isinstance(ans, dict) and ans.get('ok') is True
            status = 'ok' if ok else str(ans.get('error', 'server')) if isinstance(ans, dict) else 'server'
            if ok:
                self.sent += 1
            self.log(f'reward screen: {status}')
        except Exception as e:
            kind, text = telemetry.classify_error(e)
            self.log(f'reward screen: {type(e).__name__} ({kind}) {text}')
            self._busy.release()
            return 'error'
        finally:
            self._busy.release()
        return status


