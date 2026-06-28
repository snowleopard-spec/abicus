import argparse
import threading
import time
import webbrowser

import uvicorn


def main() -> None:
    p = argparse.ArgumentParser(prog="abicus")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", default=8765, type=int)
    p.add_argument("--reload", action="store_true", help="Uvicorn auto-reload (dev only)")
    p.add_argument("--no-browser", action="store_true", help="Don't open the browser on boot")
    args = p.parse_args()

    if not args.no_browser:
        url = f"http://{args.host}:{args.port}/"

        def _open() -> None:
            time.sleep(0.8)
            webbrowser.open(url)

        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run("abicus.server:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
