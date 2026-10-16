"""Loopback-only HTTP server for the manual knowledge workbench."""
from __future__ import annotations

import argparse
import json
import secrets
import sqlite3
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from app.store import Conflict, Invalid
from app.permanent import PermanentStore
from app.scenes import observe

STATIC = Path(__file__).parent / "static"
MAX_BODY = 64 * 1024 * 1024


def make_server(path, port=8765):
    store = PermanentStore(path)
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # Do not log workspace content or clipboard text.
            pass

        def send(self, status, body, content_type="application/json; charset=utf-8", download=None):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            if download:
                self.send_header("Content-Disposition", f'attachment; filename="{download}"')
            self.end_headers()
            self.wfile.write(body)

        def allowed(self):
            expected = f"127.0.0.1:{self.server.server_port}"
            return self.headers.get("Host") == expected

        def do_GET(self):
            if not self.allowed():
                return self.send(403, {"error": "Используйте адрес 127.0.0.1 и порт приложения."})
            path = urlparse(self.path).path
            if path == "/api/state":
                snapshot = store.read()
                snapshot['sceneView'] = observe(snapshot['state'])
                return self.send(200, {**snapshot, "token": token})
            if path == "/api/history":
                return self.send(200, store.history())
            if path == "/api/export":
                return self.send(200, store.export(), download="concept-field-workspace.json")
            if path == '/api/manage-index':
                from app.lifecycle import catalog
                rows = catalog(store.read()['state'])
                return self.send(200, [{**v, 'depends': sorted(v['depends'])} for v in rows.values()])
            files = {'/': ('index.html', 'text/html'), '/style.css': ('style.css', 'text/css'),
                     '/favicon.svg': ('favicon.svg', 'image/svg+xml')}
            scripts = ('workspace.js', 'graph-view.js', 'canvas-menu.js', 'alpha-captions.js',
                       'overview-geometry.js', 'permanent-layout.js', 'scenes.js', 'thoughts.js',
                       'management.js', 'graph-editor.js', 'layout-engine.js', 'layout-worker.js',
                       'vendor/d3-7.9.0.min.js', 'vendor/dagre-1.1.5.min.js')
            files.update({'/' + name: (name, 'text/javascript') for name in scripts})
            if path not in files:
                return self.send(404, {'error': 'Страница не найдена.'})
            filename, mime = files[path]
            return self.send(200, (STATIC / filename).read_bytes(), mime + '; charset=utf-8')

        def do_POST(self):
            if not self.allowed() or self.headers.get("X-Workspace-Token") != token:
                return self.send(403, {"error": "Запрос отклонён. Обновите страницу приложения."})
            origin = self.headers.get("Origin")
            if origin and origin != f"http://127.0.0.1:{self.server.server_port}":
                return self.send(403, {"error": "Запрос должен исходить из локального приложения."})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY:
                    return self.send(413, {"error": "Предел запроса — 64 МиБ."})
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise Invalid("Ожидался объект запроса.")
                path = urlparse(self.path).path
                if path == '/api/manage-preview':
                    from app.lifecycle import prepare
                    snapshot = store.read()
                    _, preview = prepare(snapshot['state'], data, snapshot['revision'])
                    return self.send(200, preview)
                if path == '/api/graph-preview':
                    from app.graph_editor import prepare
                    snapshot = store.read()
                    _, preview = prepare(snapshot['state'], data)
                    return self.send(200, {'revision': snapshot['revision'], **preview})
                if path == "/api/import-preview":
                    return self.send(200, store.import_preview(data.get('document')))
                if path != "/api/action":
                    return self.send(404, {"error": "Операция не найдена."})
                payload = data.get("data", {})
                if not isinstance(payload, dict):
                    raise Invalid("Ожидались поля операции.")
                snapshot = store.mutate(data.get("action"), payload, data.get("revision"))
                snapshot['sceneView'] = observe(snapshot['state'])
                return self.send(200, snapshot)
            except Conflict as exc:
                self.send(409, {"error": str(exc)})
            except (Invalid, ValueError, TypeError, KeyError, RecursionError) as exc:
                self.send(400, {"error": str(exc) or "Некорректные данные."})
            except Exception as exc:
                print(f"Ошибка сервера: {type(exc).__name__}: {exc}", file=sys.stderr)
                self.send(500, {"error": "Не удалось записать данные. Проверьте свободное место и права на каталог; изменения не применены."})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description="Локальный инструмент ручных структур знаний")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path, default=Path(__file__).resolve().parents[1] / "local-data" / "workspace.sqlite3")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        server = make_server(args.db, args.port)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"Не удалось запустить: {exc}. Проверьте порт и путь к базе.\n")
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Инструмент: {url}\nБаза: {args.db.resolve()}\nДля остановки: Ctrl+C", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
