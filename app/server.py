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
from urllib.parse import parse_qs, urlparse

from app.store import Conflict, Invalid, Store
from app.exchange import conflict, current_value, graph_export, object_index, parse_document, structural_diff

STATIC = Path(__file__).parent / "static"
MAX_BODY = 64 * 1024 * 1024


def make_server(path, port=8765):
    store = Store(path)
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
                return self.send(200, {**store.read(), "token": token})
            if path == "/api/history":
                return self.send(200, store.history())
            if path == "/api/export":
                return self.send(200, store.export(), download="concept-field-workspace.json")
            if path in ("/api/graph-export", "/api/diff", "/api/proposals", "/api/substitution-preview"):
                try:
                    query = parse_qs(urlparse(self.path).query)
                    if path == "/api/substitution-preview":
                        from app.composition import replacement_preview
                        return self.send(200, replacement_preview(store.read()["state"], query.get("study", [None])[0], query.get("source", [None])[0], query.get("target", [None])[0]))
                    if path == "/api/graph-export":
                        depth = query.get("depth", ["all"])[0]
                        doc = graph_export(store, query.get("study", [None])[0], query.get("node", [None])[0], None if depth == "all" else int(depth))
                        return self.send(200, doc, download="concept-field-graph.json")
                    snapshot = store.read()
                    if path == "/api/proposals":
                        indexed = object_index(snapshot["state"])
                        rows = []
                        for p in snapshot["state"]["proposals"]:
                            if p["status"] != "pending":
                                continue
                            expected = (p["operation"].removeprefix("delete_"), p.get("studyId"), p["value"]["id"])
                            owner = indexed["__ids__"].get(p["value"]["id"])
                            collision = {"operation": owner[0], "studyId": owner[1], "object": indexed[owner]} if owner is not None and owner != expected else None
                            rows.append({**p, "conflict": conflict(snapshot["state"], p, indexed), "current": current_value(snapshot["state"], p, indexed), "idCollision": collision})
                        return self.send(200, rows)
                    left_id = query.get("left", [None])[0]
                    right_id = query.get("right", [None])[0]
                    from app.store import lookup, decode
                    if "revision" in query:
                        with store.connect() as db:
                            row = db.execute("SELECT state FROM revisions WHERE id = ?", (int(query["revision"][0]),)).fetchone()
                        if row is None:
                            raise Invalid("Версия отсутствует.")
                        left = lookup(decode(row[0])["studies"], left_id, "исследование в выбранной версии")
                        right = lookup(snapshot["state"]["studies"], left_id, "текущее исследование")
                    else:
                        left = lookup(snapshot["state"]["studies"], left_id, "левое исследование")
                        right = lookup(snapshot["state"]["studies"], right_id, "правое исследование")
                    return self.send(200, structural_diff(left, right, snapshot["state"]["matches"]), download="concept-field-diff.json")
                except (Invalid, ValueError, TypeError, KeyError) as exc:
                    return self.send(400, {"error": str(exc)})
            files = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css"), "/favicon.svg": ("favicon.svg", "image/svg+xml")}
            if path not in files:
                return self.send(404, {"error": "Страница не найдена."})
            filename, mime = files[path]
            return self.send(200, (STATIC / filename).read_bytes(), mime + "; charset=utf-8")

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
                if path == "/api/import-preview":
                    changes = parse_document(data.get("document"))
                    state = store.read()["state"]
                    indexed = object_index(state)
                    return self.send(200, {"changes": len(changes), "conflicts": sum(conflict(state, c, indexed) for c in changes), "history": len(data["document"].get("history", []))})
                if path != "/api/action":
                    return self.send(404, {"error": "Операция не найдена."})
                payload = data.get("data", {})
                if not isinstance(payload, dict):
                    raise Invalid("Ожидались поля операции.")
                return self.send(200, store.mutate(data.get("action"), payload, data.get("revision")))
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
