"""Lazy Qwen chat engine for the DGX Spark desktop-pet agent."""

from __future__ import annotations

import gc
import json
import threading
from pathlib import Path
from typing import Any


SYSTEM_PROMPT = """你是一只可爱、简短、可靠的中文桌面精灵。
你可以聊天，也可以建议调用一个 Mac 本机工具。只输出一个 JSON 对象，不要输出 Markdown。
格式：
{"reply":"给用户的简短回复","action":"yawn|sleep|eat","tool":null}
或：
{"reply":"给用户的简短回复","action":"yawn|sleep|eat","tool":{"name":"工具名","arguments":{}}}

可用工具：
1. open_folder，arguments.folder 只能是 Desktop、Documents、Downloads。
2. open_file，arguments.query 是用户要寻找并打开的文件名关键词，不得编造绝对路径。
3. open_app，arguments.app 只能是 Finder、Safari、Notes、Calendar、Calculator、TextEdit、Preview、System Settings。

不需要工具时 tool 必须为 null。不要请求删除、移动、覆盖文件或执行终端命令。
action 根据语气选择；没有明显偏好时使用 yawn。
"""


class ChatError(RuntimeError):
    pass


class QwenChatEngine:
    def __init__(self, model_path: Path) -> None:
        self.model_path = model_path.resolve()
        self._tokenizer: Any = None
        self._model: Any = None
        self._torch: Any = None
        self._lock = threading.Lock()
        self._history: dict[str, list[dict[str, str]]] = {}

    @property
    def available(self) -> bool:
        return (self.model_path / "config.json").is_file()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _load(self) -> None:
        if self._model is not None:
            return
        if not self.available:
            raise ChatError(f"找不到对话模型: {self.model_path}")
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(str(self.model_path))
        self._model = AutoModelForCausalLM.from_pretrained(
            str(self.model_path), dtype="auto"
        ).to("cuda")
        self._model.eval()

    def unload(self) -> None:
        """Release the chat model before a large ComfyUI generation job."""
        with self._lock:
            self._model = None
            self._tokenizer = None
            gc.collect()
            if self._torch is not None and self._torch.cuda.is_available():
                self._torch.cuda.empty_cache()

    def chat(self, conversation_id: str, message: str) -> dict[str, Any]:
        with self._lock:
            self._load()
            history = self._history.setdefault(conversation_id, [])
            messages = (
                [{"role": "system", "content": SYSTEM_PROMPT}]
                + history[-8:]
                + [{"role": "user", "content": message}]
            )
            text = self._tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            inputs = self._tokenizer(text, return_tensors="pt").to("cuda")
            with self._torch.inference_mode():
                outputs = self._model.generate(
                    **inputs,
                    max_new_tokens=240,
                    do_sample=True,
                    temperature=0.7,
                    top_p=0.8,
                    pad_token_id=self._tokenizer.eos_token_id,
                )
            raw = self._tokenizer.decode(
                outputs[0][inputs.input_ids.shape[1] :], skip_special_tokens=True
            ).strip()
            result = self.parse_response(raw)
            history.extend(
                [
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": result["reply"]},
                ]
            )
            self._history[conversation_id] = history[-12:]
            return result

    @staticmethod
    def parse_response(raw: str) -> dict[str, Any]:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            cleaned = cleaned.rsplit("```", 1)[0].strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        try:
            value = json.loads(cleaned[start : end + 1])
        except (ValueError, json.JSONDecodeError):
            return {"reply": raw or "我刚刚走神啦，请再说一次。", "action": "yawn", "tool": None}

        reply = str(value.get("reply", "我听见啦。"))[:500]
        action = str(value.get("action", "yawn"))
        if action not in {"yawn", "sleep", "eat"}:
            action = "yawn"
        tool = QwenChatEngine._validate_tool(value.get("tool"))
        return {"reply": reply, "action": action, "tool": tool}

    @staticmethod
    def _validate_tool(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        name = value.get("name")
        arguments = value.get("arguments")
        if not isinstance(arguments, dict):
            return None
        if name == "open_folder" and arguments.get("folder") in {
            "Desktop",
            "Documents",
            "Downloads",
        }:
            return {"name": name, "arguments": {"folder": arguments["folder"]}}
        if name == "open_file":
            query = str(arguments.get("query", "")).strip()[:200]
            return {"name": name, "arguments": {"query": query}} if query else None
        allowed_apps = {
            "Finder",
            "Safari",
            "Notes",
            "Calendar",
            "Calculator",
            "TextEdit",
            "Preview",
            "System Settings",
        }
        if name == "open_app" and arguments.get("app") in allowed_apps:
            return {"name": name, "arguments": {"app": arguments["app"]}}
        return None
