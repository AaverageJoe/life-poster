"""Production entrypoint: waitress WSGI server."""
import faulthandler
import os

from waitress import serve

from app import app

# so a hard crash (segfault in a C extension, etc.) leaves a traceback in the log
faulthandler.enable()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Life Poster listening on http://0.0.0.0:{port}")
    # 2 threads is plenty for one person on a LAN and keeps RSS low on a Pi Zero W
    serve(app, host="0.0.0.0", port=port, threads=2, channel_timeout=120)
