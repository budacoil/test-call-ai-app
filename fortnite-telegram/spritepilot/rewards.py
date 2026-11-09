from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

import cv2
import numpy as np


def read_image(path: Path):
    try:
        return cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    except OSError:
        return None


def write_image(path: Path, frame):
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, data = cv2.imencode(path.suffix, frame)
    if not ok:
        raise ValueError("Не удалось сохранить шаблон")
    path.write_bytes(data.tobytes())


def crop_rect(frame, rect):
    x, y, w, h = map(int, rect)
    if w < 12 or h < 12 or x < 0 or y < 0 or x + w > frame.shape[1] or y + h > frame.shape[0]:
        raise ValueError("Область выходит за границы кадра или слишком мала")
    return frame[y:y+h, x:x+w].copy()


def icon_feature(image):
    # Remove the common golden border. Preserve colour and interior shape.
    h, w = image.shape[:2]
    image = image[int(h*.12):max(int(h*.88), 1), int(w*.12):max(int(w*.88), 1)]
    image = cv2.resize(image, (64, 64), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32) / 255
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 120).astype(np.float32) / 255
    colours = cv2.resize(lab, (16, 16)).ravel()
    shape = cv2.resize(edges, (16, 16)).ravel()
    # Centering suppresses uniform background similarity.
    colours -= colours.mean()
    colours /= max(float(np.linalg.norm(colours)), 1e-8)
    shape /= max(float(np.linalg.norm(shape)), 1e-8)
    return np.concatenate((colours * .8, shape * .6))


class IconClassifier:
    def __init__(self, root: Path, variant_ids):
        self.root = root
        self.ids = tuple(variant_ids)
        self.reload()

    def reload(self):
        self.features = {}
        for key in self.ids:
            features = [icon_feature(im) for path in (self.root / "templates" / key).glob("*.png")
                        if (im := read_image(path)) is not None and min(im.shape[:2]) >= 12]
            if features:
                self.features[key] = features

    def classify(self, image):
        if not self.features:
            return "unknown", 0.0
        feature = icon_feature(image)
        scores = sorted(((max(float(np.dot(feature, ref)) for ref in refs), key)
                         for key, refs in self.features.items()), reverse=True)
        first, key = scores[0]
        runner_up = scores[1][0] if len(scores) > 1 else 0.0
        # Conservative: require the full five-way library before assigning a
        # variant. A partial library cannot rule out an unregistered lookalike.
        if len(self.features) < len(self.ids) or first < .78 or first - runner_up < .055:
            return "unknown", max(0.0, first)
        return key, min(1.0, max(0.0, first))


@dataclass
class Detection:
    variant: str
    confidence: float
    crop: np.ndarray
    anchor_score: float


class RewardWatcher:
    """Detect a shared banner, then classify its icon independently of the text."""
    def __init__(self, root: Path, settings, clock=time.monotonic):
        self.root, self.settings, self.clock = root, settings, clock
        self.classifier = IconClassifier(root, settings.variants)
        self.anchor = read_image(root / "templates/anchor.png")
        self.reset()
        self.last_debug = "Области настроены · ожидание плашки" if self.configured else "Нужна настройка областей награды"

    def reset(self):
        self.visible = False
        self.hits = 0
        self.last_seen = None
        self.candidate = None
        self.emitted_variant = None
        self.emitted_at = -1e9

    @property
    def configured(self):
        return self.anchor is not None and bool(self.settings.calibration)

    def _find_anchor(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        template = cv2.cvtColor(self.anchor, cv2.COLOR_BGR2GRAY)
        if template.std() < 4:
            return None
        best = (-1.0, 0, 0, 1.0)
        for scale in (.5, .65, .8, .9, 1., 1.1, 1.25, 1.5, 1.75, 2.):
            small = cv2.resize(template, None, fx=scale, fy=scale)
            if min(small.shape) < 10 or small.shape[0] > gray.shape[0] or small.shape[1] > gray.shape[1]:
                continue
            _, score, _, point = cv2.minMaxLoc(cv2.matchTemplate(gray, small, cv2.TM_CCOEFF_NORMED))
            if score > best[0]:
                best = (float(score), *point, scale)
        return best if best[0] >= .82 else None

    def observe(self, frame):
        if not self.configured:
            return None
        now = self.clock()
        found = self._find_anchor(frame)
        if found is None:
            self.hits = 0
            if self.last_seen is not None and now - self.last_seen >= 1.2:
                self.visible = False
                self.candidate = None
            self.last_debug = "Плашка Sprite Gizmo не найдена"
            return None
        score, x, y, scale = found
        self.last_seen = now
        a = self.settings.calibration["anchor"]
        i = self.settings.calibration["icon"]
        rect = [round(x + (i[0]-a[0])*scale), round(y + (i[1]-a[1])*scale),
                round(i[2]*scale), round(i[3]*scale)]
        try:
            icon = crop_rect(frame, rect)
        except ValueError:
            self.last_debug = "Иконка вне кадра — проверьте области"
            return None
        variant, confidence = self.classifier.classify(icon)
        self.last_debug = f"Плашка {score:.0%} · иконка {confidence:.0%} · {variant}"
        # A short disappearance during animation does not create another award.
        if variant == self.candidate:
            self.hits += 1
        else:
            self.candidate, self.hits = variant, 1
        changed_known_icon = (variant != "unknown" and self.emitted_variant not in (None, "unknown", variant)
                              and now-self.emitted_at >= .8)
        if self.hits < 2 or self.visible and not changed_known_icon:
            return None
        self.visible = True
        self.emitted_variant, self.emitted_at = variant, now
        return Detection(variant, confidence, icon, score)
