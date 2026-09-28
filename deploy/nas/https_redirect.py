"""Host-scoped HTTPS entry point. Does not load application or database."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

class Redirect(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path)
        if path.scheme or path.netloc:
            self.send_error(400)
            return
        location = 'https://trustflow.co.kr' + (path.path if path.path.startswith('/') else '/')
        if path.query:
            location += '?' + path.query
        self.send_response(308)
        self.send_header('Location', location)
        self.send_header('Content-Length', '0')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
    do_HEAD = do_GET
    do_POST = do_GET
    def log_message(self, format, *args):
        pass  # Do not log query strings or user data.

if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 8080), Redirect).serve_forever()
