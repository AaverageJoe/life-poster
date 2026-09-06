"""Production entrypoint: waitress WSGI server."""
import os

from waitress import serve

from app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Life Poster listening on http://0.0.0.0:{port}")
    serve(app, host="0.0.0.0", port=port, threads=4, channel_timeout=120)
