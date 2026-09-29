"""State machine and manifest loading for the desktop pet agent."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sleep", ("睡", "休息", "晚安", "困", "sleep")),
    ("eat", ("吃", "喂", "饿", "零食", "eat", "food")),
    ("yawn", ("哈欠", "伸懒腰", "疲惫", "yawn", "stretch")),
    ("poke", ("戳", "点一下", "摸摸", "poke", "touch")),
    ("walk", ("走", "散步", "walk")),
    ("idle", ("待机", "回来", "醒来", "idle")),
)

SPEECH = {
    "sleep": "好呀，我眯一小会儿。",
    "eat": "开饭啦！",
    "yawn": "哈——伸个懒腰。",
    "poke": "呀，被你发现了！",
    "walk": "一起走走吧。",
    "idle": "我在这里陪你。",
}


@dataclass
class PetState:
    action: str
    speech: str
    sequence: int
    updated_at: str


class AssetCatalog:
    def __init__(self, asset_dir: Path) -> None:
        self.asset_dir = asset_dir.resolve()
        manifest_path = self.asset_dir / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"找不到 manifest: {manifest_path}")
        self.manifest: dict[str, Any] = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        self.version = str(manifest_path.stat().st_mtime_ns)
        actions = self.manifest.get("actions")
        if not isinstance(actions, dict) or not actions:
            raise ValueError("manifest.json 没有可用动作")

        self._files: dict[str, Path] = {}
        for action, details in actions.items():
            relative = details.get("files", {}).get("gif")
            if not relative:
                continue
            candidate = (self.asset_dir / relative).resolve()
            if self.asset_dir not in candidate.parents:
                raise ValueError(f"资源路径越界: {relative}")
            if candidate.is_file():
                self._files[action] = candidate
        if not self._files:
            raise FileNotFoundError("manifest 中的 GIF 文件均不存在")

    @property
    def actions(self) -> tuple[str, ...]:
        return tuple(self._files)

    def gif_path(self, action: str) -> Path:
        try:
            return self._files[action]
        except KeyError as error:
            raise KeyError(f"未知动作: {action}") from error


class DesktopPetAgent:
    def __init__(self, catalog: AssetCatalog) -> None:
        self.catalog = catalog
        self._lock = threading.Lock()
        initial = "yawn" if "yawn" in catalog.actions else catalog.actions[0]
        self._state = PetState(
            action=initial,
            speech="我在这里陪你。",
            sequence=0,
            updated_at=self._now(),
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _available_or_default(self, requested: str) -> str:
        if requested in self.catalog.actions:
            return requested
        if requested == "poke" and "yawn" in self.catalog.actions:
            return "yawn"
        return self._state.action

    def infer_action(self, text: str) -> str:
        lowered = text.strip().lower()
        for action, words in KEYWORDS:
            if any(word in lowered for word in words):
                return action
        return self._state.action

    def command(self, text: str = "", action: str | None = None) -> dict[str, Any]:
        requested = action or self.infer_action(text)
        with self._lock:
            selected = self._available_or_default(requested)
            self._state = PetState(
                action=selected,
                speech=SPEECH.get(requested, "我听见啦。"),
                sequence=self._state.sequence + 1,
                updated_at=self._now(),
            )
            return self.snapshot()

    def poke(self) -> dict[str, Any]:
        return self.command(action="poke")

    def say(self, speech: str, action: str = "yawn") -> dict[str, Any]:
        """Apply an LLM reply and its requested animation to the visible pet."""
        with self._lock:
            selected = self._available_or_default(action)
            self._state = PetState(
                action=selected,
                speech=speech[:500],
                sequence=self._state.sequence + 1,
                updated_at=self._now(),
            )
            return self.snapshot()

    def replace_catalog(self, catalog: AssetCatalog) -> None:
        with self._lock:
            self.catalog = catalog
            action = self._state.action
            if action not in catalog.actions:
                action = catalog.actions[0]
            self._state = PetState(
                action=action,
                speech="新精灵已经准备好啦！",
                sequence=self._state.sequence + 1,
                updated_at=self._now(),
            )

    def snapshot(self) -> dict[str, Any]:
        state = asdict(self._state)
        state["available_actions"] = list(self.catalog.actions)
        state["asset_url"] = (
            f"/api/v1/assets/{self._state.action}?v={self.catalog.version}"
        )
        return state
