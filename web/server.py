#!/usr/bin/env python3
"""资料站 HTTP 服务(仅标准库)。

路由:
  GET /api/overview                         楼层展区
  GET /api/exhibits?floor=&zone=
  GET /api/exhibit/E001?mode=short&lang=zh&at=ISO
  GET /api/map/E001?at=ISO                  地图定位(同布局版)
  GET /api/route/E001?origin=N-LOBBY&at=ISO
  GET /api/plan?minutes=120&lang=zh&at=ISO
  GET /api/packs                            整馆包 vs 路线包 + 块清单
所有 JSON 带 as_of; at 缺省取当前时刻。
"""
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))

from guide.content import Mode  # noqa: E402
from guide.errors import GuideError  # noqa: E402
from guide.guide import Guide  # noqa: E402
from guide.offline import compare_packs  # noqa: E402
from guide.sample_data import build_world  # noqa: E402
from test_acceptance import PackFixture  # noqa: E402

FX = PackFixture()


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, name, ctype):
        path = os.path.join(os.path.dirname(__file__), name)
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)
        q = lambda k, d=None: qs.get(k, [d])[0]
        try:
            guide = Guide(build_world())
            if path == "/":
                return self._static("static/index.html", "text/html; charset=utf-8")
            if path == "/static/app.js":
                return self._static("static/app.js",
                                    "application/javascript; charset=utf-8")
            if path == "/api/overview":
                return self._send(guide.catalog_overview())
            if path == "/api/exhibits":
                return self._send(guide.list_exhibits(
                    floor=int(q("floor")) if q("floor") else None,
                    zone=q("zone")))
            if path.startswith("/api/exhibit/"):
                eid = path.rsplit("/", 1)[-1]
                return self._send(guide.exhibit_page(
                    eid, Mode(q("mode", "short")), q("lang", "zh"), q("at")))
            if path.startswith("/api/map/"):
                eid = path.rsplit("/", 1)[-1]
                return self._send(guide.map_descriptor(eid, q("at")))
            if path.startswith("/api/route/"):
                eid = path.rsplit("/", 1)[-1]
                return self._send(guide.route_to_exhibit(
                    q("origin", "N-LOBBY"), eid, q("at")))
            if path == "/api/plan":
                return self._send(guide.plan_visit(
                    q("origin", "N-LOBBY"), int(q("minutes", "90")),
                    q("at"), q("lang", "zh"), Mode(q("mode", "short"))))
            if path == "/api/packs":
                return self._send(compare_packs(FX.full_pack, FX.route_pack))
            self._send({"code": "not_found", "message": path}, 404)
        except GuideError as e:
            self._send({"error": e.to_dict()}, 409)
        except Exception as e:  # noqa: BLE001
            self._send({"code": "internal", "message": str(e)}, 500)

    def log_message(self, fmt, *args):
        sys.stderr.write("[web] " + fmt % args + "\n")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"展馆导览资料站: http://localhost:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
