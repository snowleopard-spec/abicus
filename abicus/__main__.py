import argparse
import socket
import sys
import threading
import time
import webbrowser

import uvicorn


def _find_free_port(host: str, start: int, max_tries: int = 10) -> int | None:
    for port in range(start, start + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
            except OSError:
                continue
            return port
    return None


def main() -> None:
    p = argparse.ArgumentParser(prog="abicus")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", default=8765, type=int)
    p.add_argument("--reload", action="store_true", help="Uvicorn auto-reload (dev only)")
    p.add_argument("--no-browser", action="store_true", help="Don't open the browser on boot")
    args = p.parse_args()

    port = _find_free_port(args.host, args.port)
    if port is None:
        print(
            f"No free port found in {args.port}-{args.port + 9}. "
            f"Run `lsof -i :{args.port}` to see what's holding it, or pass `--port N`.",
            file=sys.stderr,
        )
        sys.exit(1)
    if port != args.port:
        print(f"Port {args.port} in use; using {port} instead.")

    if not args.no_browser:
        url = f"http://{args.host}:{port}/"

        def _open() -> None:
            time.sleep(0.8)
            webbrowser.open(url)

        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run("abicus.server:app", host=args.host, port=port, reload=args.reload)


if __name__ == "__main__":
    main()
