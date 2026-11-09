import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from spritepilot.demo import DemoGame, seed_demo
from spritepilot.engine import Engine
from spritepilot.telegram import TelegramBridge
from spritepilot.ui import MainWindow, CropCanvas


def test_all_pages_render_and_save_controls_dispatch(settings, store, tmp_path):
    seed_demo(settings, store)
    app = QApplication.instance() or QApplication([])
    engine = Engine(settings, store, DemoGame())
    bridge = TelegramBridge(settings, store, engine.submit)
    window = MainWindow(settings, store, engine, bridge, demo=True)
    window.show()
    try:
        for index in range(5):
            window.show_page(index)
            app.processEvents()
            assert window.pages.currentIndex() == index
            assert not window.grab().isNull()
        window.fields['wait_b'].setValue(125)
        window.save_automation()
        action, values, chat = engine.commands.get_nowait()
        assert action == 'configure' and values['wait_b'] == 125
        window.variant_filter.setCurrentIndex(1)
        app.processEvents()
        assert window.gallery_layout.count() == 1  # unknown-filter empty state
    finally:
        # The store fixture owns its connection in this test.
        window.timer.stop()
        window.hide()
        window.deleteLater()
        app.processEvents()


def test_crop_canvas_maps_scaled_selection_to_original_pixels():
    from PySide6.QtCore import QRect
    from spritepilot.demo import make_frame
    app = QApplication.instance() or QApplication([])
    canvas = CropCanvas(make_frame())
    canvas.rect = QRect(75, 75, 150, 75)
    # 1280x720 is rendered at 960x540.
    assert canvas.selected() == [100, 100, 200, 100]
