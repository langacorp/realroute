"""Local HTTP servers for the tests. Nothing here touches the network."""

import http.server
import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PAGE = ("<html><head><title>{title}</title></head>"
        "<body><h1>{title}</h1><p>{body}</p></body></html>")


def page(title, body):
    return PAGE.format(title=title, body=body).encode("utf-8")


class Site:
    """A local site defined by a table: path -> (status, body bytes, headers).

    Paths not in the table get `default`, which is the same shape. A value of
    None for a path closes the connection without answering.
    """

    def __init__(self, routes, default=(404, page("Not Found", "no such page"), {})):
        self.routes = dict(routes)
        self.default = default
        self.requests = []
        site = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                site.requests.append(self.path)
                entry = site.lookup(self.path)
                if entry is None:
                    self.close_connection = True
                    return
                status, body, headers = entry
                self.send_response(status)
                headers = dict(headers)
                headers.setdefault("Content-Type", "text/html; charset=utf-8")
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def lookup(self, path):
        if path in self.routes:
            return self.routes[path]
        if callable(self.default):
            return self.default(path)
        return self.default

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        return False


def closed_port():
    """A local port with nothing listening on it."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port
