from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import socket


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data = {
            "app": socket.gethostname(),
            "client_address_seen_by_app": self.client_address[0],
            "x_forwarded_for": self.headers.get("X-Forwarded-For"),
            "x_real_ip": self.headers.get("X-Real-IP"),
            "headers": dict(self.headers),
        }

        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
