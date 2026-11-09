import cv2
import numpy as np
import pytest

from spritepilot.demo import make_frame, make_icon, seed_demo
from spritepilot.rewards import IconClassifier, RewardWatcher, crop_rect, write_image


@pytest.mark.parametrize("number", range(1, 6))
def test_identical_text_does_not_merge_five_devices(number, settings, store):
    seed_demo(settings, store)
    watcher = RewardWatcher(store.root, settings)
    # Every frame has exactly the same text; only the icon changes.
    assert watcher.observe(make_frame(number)) is None
    result = watcher.observe(make_frame(number))
    assert result.variant == f"gizmo_{number}"
    assert result.confidence > .9


def test_partial_library_never_assigns_an_unproven_variant(tmp_path, settings):
    write_image(tmp_path / "templates/gizmo_1/sample.png", make_icon(1))
    classifier = IconClassifier(tmp_path, settings.variants)
    assert classifier.classify(make_icon(1))[0] == "unknown"


def test_ambiguous_icons_remain_unknown(tmp_path, settings):
    for key in settings.variants:
        write_image(tmp_path / "templates" / key / "same.png", make_icon(1))
    assert IconClassifier(tmp_path, settings.variants).classify(make_icon(1))[0] == "unknown"


def test_unknown_picture_is_not_falsely_assigned(settings, store):
    seed_demo(settings, store)
    picture = np.random.default_rng(24).integers(0, 256, (144, 144, 3), dtype=np.uint8)
    assert IconClassifier(store.root, settings.variants).classify(picture)[0] == "unknown"


def test_banner_dedup_and_reappearance(settings, store):
    seed_demo(settings, store)
    now = [0.0]
    watcher = RewardWatcher(store.root, settings, clock=lambda: now[0])
    frame = make_frame(3)
    assert watcher.observe(frame) is None
    assert watcher.observe(frame) is not None
    for _ in range(4):
        now[0] += .3
        assert watcher.observe(frame) is None
    blank = np.zeros_like(frame)
    now[0] += .4
    assert watcher.observe(blank) is None
    # Brief animation flicker is still the same appearance.
    assert watcher.observe(frame) is None
    assert watcher.observe(frame) is None
    now[0] += 1.5
    assert watcher.observe(blank) is None
    assert watcher.observe(frame) is None
    assert watcher.observe(frame).variant == "gizmo_3"


def test_banner_single_frame_is_not_counted(settings, store):
    seed_demo(settings, store)
    watcher = RewardWatcher(store.root, settings)
    frame = make_frame(1)
    assert watcher.observe(frame) is None
    assert watcher.observe(np.zeros_like(frame)) is None
    assert watcher.observe(frame) is None


def test_scaled_banner_uses_scaled_icon_offsets(settings, store):
    seed_demo(settings, store)
    watcher = RewardWatcher(store.root, settings)
    frame = cv2.resize(make_frame(4), None, fx=.8, fy=.8)
    assert watcher.observe(frame) is None
    result = watcher.observe(frame)
    assert result.variant == "gizmo_4"


def test_not_configured_produces_no_guess(tmp_path, settings):
    watcher = RewardWatcher(tmp_path, settings)
    assert not watcher.configured
    assert watcher.observe(make_frame(1)) is None


def test_crop_rejects_outside_frame():
    with pytest.raises(ValueError):
        crop_rect(make_frame(), [-10, 0, 100, 100])


def test_new_device_can_be_counted_without_changing_the_shared_text(settings, store):
    seed_demo(settings, store)
    now = [0.0]
    watcher = RewardWatcher(store.root, settings, clock=lambda: now[0])
    watcher.observe(make_frame(1))
    assert watcher.observe(make_frame(1)).variant == "gizmo_1"
    now[0] = 1.0
    assert watcher.observe(make_frame(2)) is None
    assert watcher.observe(make_frame(2)).variant == "gizmo_2"
