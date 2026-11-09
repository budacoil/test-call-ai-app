from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description="Sprite Pilot")
    parser.add_argument("--demo", action="store_true", help="Synthetic local demo; no game input or Telegram")
    parser.add_argument("--preview", type=Path, help="Save an offscreen demo screenshot and exit")
    parser.add_argument("--page", type=int, default=0, choices=range(5))
    args = parser.parse_args()
    if args.preview:
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from .windows import enable_dpi
    enable_dpi()
    from PySide6.QtWidgets import QApplication
    from .settings import Settings, data_root
    from .storage import Store
    from .engine import Engine
    from .telegram import TelegramBridge
    from .ui import MainWindow
    demo = args.demo or bool(args.preview)
    temporary = tempfile.TemporaryDirectory(prefix="spritepilot-demo-") if demo else None
    root = Path(temporary.name) if temporary else data_root()
    settings = Settings.load(root)
    store = Store(root)
    if demo:
        from .demo import DemoGame, seed_demo
        seed_demo(settings, store)
        game = DemoGame()
    else:
        game = None
    engine = Engine(settings, store, game)
    bridge = TelegramBridge(settings, store, engine.submit)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = MainWindow(settings, store, engine, bridge, demo)
    engine.start_thread()
    if not demo:
        bridge.start()
    window.show()
    window.show_page(args.page)
    if args.preview:
        app.processEvents()
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        if not window.grab().save(str(args.preview)):
            raise RuntimeError("Не удалось сохранить предпросмотр")
        window.close()
        app.processEvents()
    else:
        app.exec()
    if temporary:
        temporary.cleanup()


if __name__ == "__main__":
    main()
