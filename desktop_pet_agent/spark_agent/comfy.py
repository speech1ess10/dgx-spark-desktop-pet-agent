"""Small standard-library client for a local ComfyUI server."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
import uuid
from typing import Any


class ComfyError(RuntimeError):
    pass


class ComfyClient:
    def __init__(self, server: str = "http://127.0.0.1:8188") -> None:
        self.server = server.rstrip("/")

    def _json(self, path: str, payload: dict | None = None, timeout: int = 60) -> dict:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.server}{path}",
            data=data,
            headers={"Content-Type": "application/json"} if data else {},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def upload_image(self, content: bytes, filename: str) -> str:
        boundary = f"----pet-agent-{uuid.uuid4().hex}"
        chunks: list[bytes] = []

        def field(name: str, value: str) -> None:
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                    value.encode(),
                    b"\r\n",
                ]
            )

        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    'Content-Disposition: form-data; name="image"; '
                    f'filename="{filename}"\r\n'
                ).encode(),
                b"Content-Type: application/octet-stream\r\n\r\n",
                content,
                b"\r\n",
            ]
        )
        field("type", "input")
        field("overwrite", "true")
        chunks.append(f"--{boundary}--\r\n".encode())
        request = urllib.request.Request(
            f"{self.server}/upload/image",
            data=b"".join(chunks),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
        name = result["name"]
        subfolder = result.get("subfolder", "")
        return f"{subfolder}/{name}" if subfolder else name

    def run(self, workflow: dict, timeout: int) -> list[dict[str, Any]]:
        submitted = self._json(
            "/prompt", {"prompt": workflow, "client_id": str(uuid.uuid4())}
        )
        prompt_id = submitted.get("prompt_id")
        if not prompt_id:
            raise ComfyError(f"ComfyUI 未返回 prompt_id: {submitted}")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            history = self._json(f"/history/{prompt_id}")
            item = history.get(prompt_id)
            if item:
                status = item.get("status", {})
                if status.get("status_str") == "error":
                    raise ComfyError(json.dumps(status, ensure_ascii=False))
                files = self._collect_files(item.get("outputs", {}))
                if files:
                    return files
            time.sleep(2)
        raise TimeoutError(f"ComfyUI 任务 {prompt_id} 超时")

    @staticmethod
    def _collect_files(value: Any) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        if isinstance(value, dict):
            if isinstance(value.get("filename"), str):
                found.append(value)
            else:
                for child in value.values():
                    found.extend(ComfyClient._collect_files(child))
        elif isinstance(value, list):
            for child in value:
                found.extend(ComfyClient._collect_files(child))
        return found

    def download(self, descriptor: dict[str, Any]) -> bytes:
        query = urllib.parse.urlencode(
            {
                "filename": descriptor["filename"],
                "subfolder": descriptor.get("subfolder", ""),
                "type": descriptor.get("type", "output"),
            }
        )
        with urllib.request.urlopen(f"{self.server}/view?{query}", timeout=300) as response:
            return response.read()

    def free_memory(self) -> None:
        """Ask ComfyUI to unload the previous model family before the next stage."""
        payload = json.dumps({"unload_models": True, "free_memory": True}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.server}/free",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                response.read()
        except Exception:
            # Older ComfyUI builds may not expose /free; normal model management still applies.
            return
