"""Zero-dependency HTTP server for the DGX Spark desktop pet agent."""

from __future__ import annotations

import argparse
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .chat import ChatError, QwenChatEngine
from .core import AssetCatalog, DesktopPetAgent
from .generation import GenerationManager


class PetHTTPServer(ThreadingHTTPServer):
    catalog: AssetCatalog
    agent: DesktopPetAgent
    jobs: GenerationManager
    chat: QwenChatEngine


class Handler(BaseHTTPRequestHandler):
    server: PetHTTPServer

    def log_message(self, format: str, *args: object) -> None:
        print(f"[pet-agent] {self.address_string()} {format % args}")

    def _headers(self, status: HTTPStatus, content_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, value: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _read_json(self, max_size: int = 64 * 1024) -> dict:
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("无效 Content-Length") from error
        if size > max_size:
            raise ValueError("请求内容过大")
        raw = self.rfile.read(size)
        value = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(value, dict):
            raise ValueError("请求 JSON 必须是对象")
        return value

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._headers(HTTPStatus.NO_CONTENT, "text/plain", 0)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health":
            self._json(
                {
                    "ok": True,
                    "service": "desktop-pet-agent",
                    "actions": list(self.server.agent.catalog.actions),
                    "asset_dir": str(self.server.agent.catalog.asset_dir),
                    "generation_enabled": True,
                    "chat_enabled": self.server.chat.available,
                    "chat_model_loaded": self.server.chat.loaded,
                }
            )
            return
        if path == "/api/v1/pet":
            self._json(self.server.agent.snapshot())
            return
        jobs_prefix = "/api/v1/jobs/"
        if path.startswith(jobs_prefix):
            job = self.server.jobs.get(unquote(path[len(jobs_prefix) :]))
            if job is None:
                self._json({"detail": "job not found"}, HTTPStatus.NOT_FOUND)
            else:
                self._json(job)
            return
        prefix = "/api/v1/assets/"
        if path.startswith(prefix):
            action = unquote(path[len(prefix) :])
            try:
                file_path = self.server.agent.catalog.gif_path(action)
            except KeyError as error:
                self._json({"detail": str(error)}, HTTPStatus.NOT_FOUND)
                return
            body = file_path.read_bytes()
            self._headers(HTTPStatus.OK, "image/gif", len(body))
            self.wfile.write(body)
            return
        self._json({"detail": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            payload = self._read_json(28 * 1024 * 1024 if path == "/api/v1/generate" else 64 * 1024)
            if path == "/api/v1/poke":
                self._json(self.server.agent.poke())
                return
            if path == "/api/v1/command":
                text = str(payload.get("text", ""))[:500]
                raw_action = payload.get("action")
                action = str(raw_action)[:40] if raw_action is not None else None
                if not text.strip() and not action:
                    self._json(
                        {"detail": "text 或 action 至少提供一个"},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._json(self.server.agent.command(text=text, action=action))
                return
            if path == "/api/v1/generate":
                prompt = str(payload.get("prompt", "")).strip()
                reference_b64 = str(payload.get("reference_image_base64", ""))
                reference_name = str(payload.get("reference_filename", "reference.png"))
                actions = payload.get("actions", ["yawn", "sleep", "eat"])
                if not prompt or not reference_b64:
                    raise ValueError("prompt 和 reference_image_base64 都是必填项")
                if not isinstance(actions, list):
                    raise ValueError("actions 必须是数组")
                self.server.chat.unload()
                job = self.server.jobs.create(
                    prompt=prompt,
                    reference_b64=reference_b64,
                    reference_name=reference_name,
                    actions=[str(item) for item in actions],
                )
                self._json(job, HTTPStatus.ACCEPTED)
                return
            if path == "/api/v1/chat":
                message = str(payload.get("message", "")).strip()[:1000]
                conversation_id = str(payload.get("conversation_id", "default"))[:100]
                if not message:
                    raise ValueError("message 不能为空")
                try:
                    result = self.server.chat.chat(conversation_id, message)
                except (ChatError, OSError, RuntimeError) as error:
                    self._json(
                        {"detail": f"对话模型暂时不可用: {error}"},
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                    return
                result["pet"] = self.server.agent.say(
                    result["reply"], result["action"]
                )
                self._json(result)
                return
            self._json({"detail": "not found"}, HTTPStatus.NOT_FOUND)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            self._json({"detail": str(error)}, HTTPStatus.BAD_REQUEST)


def main() -> None:
    parser = argparse.ArgumentParser(description="DGX Spark desktop pet agent")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7000)
    package_root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--asset-dir",
        default=os.environ.get(
            "PET_ASSET_DIR",
            str(Path(__file__).resolve().parents[2] / "output" / "red-scarf-cat-final"),
        ),
    )
    parser.add_argument(
        "--qwen-workflow",
        default=str(package_root / "workflows" / "qwen_image_edit_api.json"),
    )
    parser.add_argument(
        "--wan-workflow",
        default=str(package_root / "workflows" / "wan22_i2v_api.json"),
    )
    parser.add_argument(
        "--jobs-dir",
        default=str(Path.home() / "desktop-pet-agent-data" / "jobs"),
    )
    parser.add_argument("--comfy-server", default="http://127.0.0.1:8188")
    parser.add_argument(
        "--chat-model",
        default=os.environ.get(
            "PET_CHAT_MODEL", str(Path.home() / "model-download" / "Qwen3-4B")
        ),
    )
    args = parser.parse_args()

    server = PetHTTPServer((args.host, args.port), Handler)
    jobs_dir = Path(args.jobs_dir)
    initial_asset_dir = Path(args.asset_dir)
    active_path = jobs_dir / "active.json"
    if active_path.is_file():
        try:
            active_value = json.loads(active_path.read_text(encoding="utf-8"))
            candidate = Path(active_value["asset_dir"])
            if (candidate / "manifest.json").is_file():
                initial_asset_dir = candidate
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            pass
    server.catalog = AssetCatalog(initial_asset_dir)
    server.agent = DesktopPetAgent(server.catalog)
    server.chat = QwenChatEngine(Path(args.chat_model))
    server.jobs = GenerationManager(
        root=jobs_dir,
        qwen_workflow=Path(args.qwen_workflow),
        wan_workflow=Path(args.wan_workflow),
        activate=server.agent.replace_catalog,
        comfy_server=args.comfy_server,
    )
    print(f"Desktop Pet Agent: http://{args.host}:{args.port}")
    print(f"Actions: {', '.join(server.catalog.actions)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDesktop Pet Agent stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
