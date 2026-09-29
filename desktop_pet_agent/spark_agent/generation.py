"""Qwen Image Edit -> Wan 2.2 -> transparent sprite generation jobs."""

from __future__ import annotations

import base64
import copy
import json
import queue
import random
import shutil
import subprocess
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .comfy import ComfyClient
from .core import AssetCatalog


ACTION_PROMPTS = {
    "yawn": "The character yawns, opens its mouth, stretches, then returns to the starting pose.",
    "sleep": "The character closes its eyes and sleeps with subtle breathing and one gentle ear twitch.",
    "eat": "The character lowers its head, chews happily, looks up with a satisfied expression, then repeats.",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class GenerationJob:
    id: str
    prompt: str
    reference_b64: str = field(repr=False)
    reference_name: str
    actions: list[str]
    status: str = "queued"
    stage: str = "等待执行"
    progress: int = 0
    error: str | None = None
    asset_dir: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def public(self) -> dict:
        value = asdict(self)
        value.pop("reference_b64", None)
        return value


class GenerationManager:
    def __init__(
        self,
        root: Path,
        qwen_workflow: Path,
        wan_workflow: Path,
        activate: Callable[[AssetCatalog], None],
        comfy_server: str = "http://127.0.0.1:8188",
    ) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.qwen_template = json.loads(qwen_workflow.read_text(encoding="utf-8"))
        self.wan_template = json.loads(wan_workflow.read_text(encoding="utf-8"))
        self.activate = activate
        self.comfy = ComfyClient(comfy_server)
        self.jobs: dict[str, GenerationJob] = {}
        self.pending: queue.Queue[str] = queue.Queue()
        self.lock = threading.Lock()
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

    def create(
        self, prompt: str, reference_b64: str, reference_name: str, actions: list[str]
    ) -> dict:
        selected = [name for name in actions if name in ACTION_PROMPTS]
        if len(set(selected)) < 3:
            raise ValueError("actions 必须包含 yawn、sleep、eat 三个动作")
        try:
            raw = base64.b64decode(reference_b64, validate=True)
        except Exception as error:
            raise ValueError("reference_image_base64 不是有效 Base64") from error
        if not raw or len(raw) > 20 * 1024 * 1024:
            raise ValueError("参考图必须为 1 字节到 20 MB")
        job_id = uuid.uuid4().hex[:12]
        job = GenerationJob(
            id=job_id,
            prompt=prompt.strip(),
            reference_b64=reference_b64,
            reference_name=Path(reference_name).name or "reference.png",
            actions=list(dict.fromkeys(selected)),
        )
        with self.lock:
            self.jobs[job_id] = job
        self.pending.put(job_id)
        return job.public()

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return None if job is None else job.public()

    def _update(self, job: GenerationJob, **changes: object) -> None:
        with self.lock:
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = utc_now()

    def _worker(self) -> None:
        while True:
            job_id = self.pending.get()
            job = self.jobs[job_id]
            try:
                self._run(job)
            except Exception as error:
                self._update(job, status="failed", stage="生成失败", error=repr(error))
            finally:
                self.pending.task_done()

    def _run(self, job: GenerationJob) -> None:
        self._update(job, status="running", stage="上传参考图", progress=2)
        job_dir = self.root / job.id
        job_dir.mkdir(parents=True, exist_ok=False)
        reference = base64.b64decode(job.reference_b64)
        uploaded_reference = self.comfy.upload_image(reference, f"pet-{job.id}-{job.reference_name}")

        self._update(job, stage="Qwen 生成角色设定图", progress=5)
        qwen = copy.deepcopy(self.qwen_template)
        qwen["19"]["inputs"]["image"] = uploaded_reference
        qwen["17:13"]["inputs"]["prompt"] = self._qwen_prompt(job.prompt)
        qwen["17:9"]["inputs"]["prompt"] = ""
        qwen["17:15"]["inputs"]["seed"] = random.randrange(0, 2**32)
        qwen["20"]["inputs"]["filename_prefix"] = f"pet_agent/{job.id}/character"
        qwen_files = self.comfy.run(qwen, timeout=1800)
        image_file = self._pick(qwen_files, (".png", ".jpg", ".jpeg", ".webp"))
        character_bytes = self.comfy.download(image_file)
        character_path = job_dir / "character.png"
        character_path.write_bytes(character_bytes)
        uploaded_character = self.comfy.upload_image(character_bytes, f"pet-{job.id}-character.png")
        self.comfy.free_memory()

        action_outputs: dict[str, dict] = {}
        total = len(job.actions)
        for index, action in enumerate(job.actions):
            start = 20 + int(index * 65 / total)
            self._update(job, stage=f"Wan 生成动作：{action}", progress=start)
            wan = copy.deepcopy(self.wan_template)
            wan["120"]["inputs"]["image"] = uploaded_character
            wan["116:93"]["inputs"]["text"] = self._wan_prompt(action)
            wan["116:86"]["inputs"]["noise_seed"] = random.randrange(0, 2**48)
            wan["122"]["inputs"]["filename_prefix"] = f"pet_agent/{job.id}/{action}"
            files = self.comfy.run(wan, timeout=7200)
            video_file = self._pick(files, (".mp4", ".webm", ".mov", ".mkv"))
            suffix = Path(video_file["filename"]).suffix or ".mp4"
            video_path = job_dir / f"{action}{suffix}"
            video_path.write_bytes(self.comfy.download(video_file))
            self._update(job, stage=f"处理透明动图：{action}", progress=start + 15)
            action_outputs[action] = self._build_animation(video_path, job_dir, action)

        manifest = {
            "schema_version": 1,
            "mode": "reference_image",
            "size": [320, 320],
            "fps": 12,
            "loop": 0,
            "source_character": "character.png",
            "actions": action_outputs,
        }
        (job_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        catalog = AssetCatalog(job_dir)
        self.activate(catalog)
        (self.root / "active.json").write_text(
            json.dumps({"asset_dir": str(job_dir)}, ensure_ascii=False), encoding="utf-8"
        )
        self._update(
            job,
            status="completed",
            stage="已更新桌面精灵",
            progress=100,
            asset_dir=str(job_dir),
        )

    @staticmethod
    def _qwen_prompt(user_prompt: str) -> str:
        return (
            f"{user_prompt}\n"
            "Keep the subject identity recognizable. Transform it into one cute chibi anime desktop "
            "companion, rounded clean outlines, large head and small body, simple color blocks, full "
            "body centered, no text, no props. Use a perfectly flat pure chroma green (#00FF00) "
            "background with no shadow, gradient, scenery, floor, or border."
        )

    @staticmethod
    def _wan_prompt(action: str) -> str:
        return (
            "Preserve exactly the same character, clothes, colors, proportions and camera. "
            f"{ACTION_PROMPTS[action]} The first and last pose should match for a seamless loop. "
            "Single character only, fixed camera, full body always visible. Keep the background "
            "perfectly flat pure chroma green (#00FF00), with no shadow, scenery, floor, text, or props."
        )

    @staticmethod
    def _pick(files: list[dict], suffixes: tuple[str, ...]) -> dict:
        for item in files:
            if str(item.get("filename", "")).lower().endswith(suffixes):
                return item
        raise RuntimeError(f"ComfyUI 输出中没有找到 {suffixes}: {files}")

    @staticmethod
    def _build_animation(video: Path, job_dir: Path, action: str) -> dict:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("节点没有 ffmpeg，无法将 Wan 视频转换为动图")
        frames_dir = job_dir / "frames" / action
        frames_dir.mkdir(parents=True)
        subprocess.run(
            [ffmpeg, "-y", "-i", str(video), "-vf", "fps=12", str(frames_dir / "%04d.png")],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        from PIL import Image

        source_paths = sorted(frames_dir.glob("*.png"))
        if len(source_paths) < 4:
            raise RuntimeError(f"{action} 视频抽帧不足")
        frames = []
        for path in source_paths:
            image = Image.open(path).convert("RGBA")
            image.thumbnail((320, 320), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (320, 320), (0, 0, 0, 0))
            canvas.alpha_composite(image, ((320 - image.width) // 2, 320 - image.height))
            pixels = []
            for red, green, blue, alpha in canvas.getdata():
                dominance = green - max(red, blue)
                if green > 80 and dominance > 20:
                    removed = min(255, max(0, int((dominance - 20) * 2.8)))
                    alpha = alpha * (255 - removed) // 255
                    green = min(green, max(red, blue) + 25)
                pixels.append((red, green, blue, alpha))
            canvas.putdata(pixels)
            canvas.save(path)
            frames.append(canvas)

        duration = 83
        apng = job_dir / f"{action}.apng"
        frames[0].save(
            apng,
            save_all=True,
            append_images=frames[1:],
            duration=duration,
            loop=0,
            disposal=1,
            blend=0,
        )
        gif_frames = [GenerationManager._gif_frame(frame) for frame in frames]
        gif = job_dir / f"{action}.gif"
        gif_frames[0].save(
            gif,
            save_all=True,
            append_images=gif_frames[1:],
            duration=duration,
            loop=0,
            disposal=2,
            transparency=255,
        )
        return {
            "files": {"apng": apng.name, "gif": gif.name},
            "frames": len(frames),
            "anchor": [0.5, 0.92],
            "duration_ms": len(frames) * duration,
        }

    @staticmethod
    def _gif_frame(frame):
        from PIL import Image

        alpha = frame.getchannel("A")
        paletted = frame.convert("RGB").quantize(colors=255, method=Image.Quantize.MEDIANCUT)
        palette = (paletted.getpalette() or [])[: 255 * 3]
        palette.extend([0] * (768 - len(palette)))
        paletted.putpalette(palette)
        data = list(paletted.getdata())
        mask = list(alpha.getdata())
        paletted.putdata([255 if a < 128 else pixel for pixel, a in zip(data, mask)])
        paletted.info["transparency"] = 255
        return paletted
