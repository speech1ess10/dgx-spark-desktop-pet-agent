#!/usr/bin/env python3
"""Transparent macOS desktop companion backed by the Spark agent API."""

from __future__ import annotations

import base64
import json
import os
import signal
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from PySide6.QtCore import QPoint, QThread, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QMovie
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)


SERVER = os.environ.get("PET_AGENT_URL", "http://127.0.0.1:7000").rstrip("/")


class ChatWorker(QThread):
    completed = Signal(dict)
    failed = Signal(str)

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def run(self) -> None:
        try:
            self.completed.emit(
                json_request(
                    "/api/v1/chat",
                    {"conversation_id": "lucy", "message": self.message},
                    timeout=300,
                )
            )
        except Exception as error:  # Qt worker must report failures to the UI thread.
            self.failed.emit(str(error))


def json_request(path: str, payload: dict | None = None, timeout: int = 10) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{SERVER}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class PetWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DGX Spark Desktop Pet")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        if sys.platform == "darwin":
            # Qt.Tool windows are hidden when their app loses focus on macOS unless
            # this attribute is set. A desktop pet must remain visible over other apps.
            self.setAttribute(Qt.WA_MacAlwaysShowToolWindow, True)
        self.setFixedSize(340, 390)

        self.sprite = QLabel(alignment=Qt.AlignCenter)
        self.sprite.setFixedSize(340, 340)
        self.sprite.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.message = QLabel("正在连接 DGX Spark…", alignment=Qt.AlignCenter)
        self.message.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.message.setStyleSheet(
            "QLabel { background: rgba(255,255,255,220); color: #222; "
            "border-radius: 12px; padding: 7px 12px; font-size: 14px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.message, alignment=Qt.AlignCenter)
        layout.addWidget(self.sprite)

        self.cache_dir = Path(tempfile.mkdtemp(prefix="desktop-pet-"))
        self.movie: QMovie | None = None
        self.current_action = ""
        self.current_asset_url = ""
        self.sequence = -1
        self.drag_origin: QPoint | None = None
        self.window_origin: QPoint | None = None
        self.moved = False
        self.generation_job: str | None = None
        self.chat_worker: ChatWorker | None = None

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll)
        self.poll_timer.start(1000)
        QTimer.singleShot(0, self.poll)

    def load_action(self, action: str, asset_url: str) -> None:
        version = asset_url.partition("?v=")[2] or "initial"
        target = self.cache_dir / f"{action}-{version}.gif"
        if not target.exists():
            with urllib.request.urlopen(
                f"{SERVER}{asset_url}", timeout=15
            ) as response:
                target.write_bytes(response.read())
        movie = QMovie(str(target))
        movie.setCacheMode(QMovie.CacheAll)
        movie.setScaledSize(self.sprite.size())
        self.sprite.setMovie(movie)
        movie.start()
        self.movie = movie
        self.current_action = action
        self.current_asset_url = asset_url

    def apply_state(self, state: dict) -> None:
        action = state["action"]
        asset_url = state.get("asset_url", f"/api/v1/assets/{action}")
        if action != self.current_action or asset_url != self.current_asset_url:
            self.load_action(action, asset_url)
        sequence = int(state.get("sequence", 0))
        if sequence != self.sequence:
            self.sequence = sequence
            self.message.setText(state.get("speech", ""))
            self.message.show()
            QTimer.singleShot(2500, self.message.hide)

    def poll(self) -> None:
        try:
            self.apply_state(json_request("/api/v1/pet"))
            if self.generation_job:
                job = json_request(f"/api/v1/jobs/{self.generation_job}")
                self.message.setText(
                    f"生成中 {job.get('progress', 0)}%：{job.get('stage', '')}"
                )
                self.message.show()
                if job.get("status") == "completed":
                    self.generation_job = None
                    self.message.setText("新精灵已经生成完成！")
                    QTimer.singleShot(4000, self.message.hide)
                elif job.get("status") == "failed":
                    self.generation_job = None
                    self.message.setText(f"生成失败：{job.get('error', '未知错误')}")
        except (OSError, ValueError, KeyError, urllib.error.URLError) as error:
            self.message.setText(f"无法连接 Spark：{error}")
            self.message.show()

    def send_action(self, action: str) -> None:
        try:
            state = json_request("/api/v1/command", {"action": action})
            self.apply_state(state)
        except (OSError, ValueError, KeyError, urllib.error.URLError) as error:
            self.message.setText(f"操作失败：{error}")
            self.message.show()

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.LeftButton:
            self.drag_origin = event.globalPosition().toPoint()
            self.window_origin = self.pos()
            self.moved = False
            event.accept()
        elif event.button() == Qt.RightButton:
            self.show_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.drag_origin is not None and self.window_origin is not None:
            delta = event.globalPosition().toPoint() - self.drag_origin
            if delta.manhattanLength() > 4:
                self.moved = True
            self.move(self.window_origin + delta)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.LeftButton:
            if not self.moved:
                try:
                    self.apply_state(json_request("/api/v1/poke", {}))
                except (OSError, ValueError, KeyError, urllib.error.URLError):
                    self.message.setText("没有戳到 Spark，请检查 SSH 隧道。")
                    self.message.show()
            self.drag_origin = None
            self.window_origin = None
            event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        actions = ["yawn", "sleep", "eat"]
        try:
            index = actions.index(self.current_action)
        except ValueError:
            index = -1
        self.send_action(actions[(index + 1) % len(actions)])
        event.accept()

    def show_menu(self, point: QPoint) -> None:
        menu = QMenu(self)
        chat_action = QAction("和精灵对话…", menu)
        chat_action.triggered.connect(self.chat_with_pet)
        menu.addAction(chat_action)
        menu.addSeparator()
        generate_action = QAction("根据照片生成新精灵…", menu)
        generate_action.triggered.connect(self.generate_pet)
        menu.addAction(generate_action)
        menu.addSeparator()
        for label, action in (("打哈欠", "yawn"), ("睡觉", "sleep"), ("进食", "eat")):
            item = QAction(label, menu)
            item.triggered.connect(lambda checked=False, name=action: self.send_action(name))
            menu.addAction(item)
        menu.addSeparator()
        reset_action = QAction("重置到屏幕右下角", menu)
        reset_action.triggered.connect(self.place_on_primary_screen)
        menu.addAction(reset_action)
        quit_action = QAction("退出精灵", menu)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_action)
        menu.exec(point)

    def chat_with_pet(self) -> None:
        if self.chat_worker and self.chat_worker.isRunning():
            self.message.setText("我还在想刚才的问题哦……")
            self.message.show()
            return
        text, accepted = QInputDialog.getMultiLineText(
            self,
            "和桌面精灵对话",
            "你想对精灵说什么？",
            "",
        )
        if not accepted or not text.strip():
            return
        self.message.setText("让我想一想……")
        self.message.show()
        worker = ChatWorker(text.strip())
        worker.completed.connect(self._chat_completed)
        worker.failed.connect(self._chat_failed)
        worker.finished.connect(self._chat_finished)
        worker.finished.connect(worker.deleteLater)
        self.chat_worker = worker
        worker.start()

    def _chat_finished(self) -> None:
        # QThread.deleteLater destroys the wrapped C++ object. Drop our Python
        # reference first so the next conversation never calls isRunning() on
        # an already-deleted Qt object.
        self.chat_worker = None

    def _chat_completed(self, result: dict) -> None:
        pet = result.get("pet")
        if isinstance(pet, dict):
            self.apply_state(pet)
        self.message.setText(str(result.get("reply", "我听见啦。")))
        self.message.show()
        tool = result.get("tool")
        if isinstance(tool, dict):
            self._handle_tool(tool)

    def _chat_failed(self, detail: str) -> None:
        self.message.setText(f"对话失败：{detail}")
        self.message.show()

    def _handle_tool(self, tool: dict) -> None:
        name = tool.get("name")
        arguments = tool.get("arguments", {})
        try:
            if name == "open_folder":
                folder = str(arguments.get("folder", ""))
                mapping = {
                    "Desktop": Path.home() / "Desktop",
                    "Documents": Path.home() / "Documents",
                    "Downloads": Path.home() / "Downloads",
                }
                target = mapping.get(folder)
                if target is not None:
                    self._confirm_open(target, f"打开文件夹“{folder}”吗？")
            elif name == "open_file":
                self._find_and_open(str(arguments.get("query", "")))
            elif name == "open_app":
                app = str(arguments.get("app", ""))
                allowed = {
                    "Finder", "Safari", "Notes", "Calendar", "Calculator",
                    "TextEdit", "Preview", "System Settings",
                }
                if app in allowed and self._confirm(f"打开应用“{app}”吗？"):
                    subprocess.Popen(["open", "-a", app])
        except OSError as error:
            self.message.setText(f"工具执行失败：{error}")
            self.message.show()

    def _find_and_open(self, query: str) -> None:
        needle = query.strip().lower()
        if not needle:
            return
        roots = [Path.home() / name for name in ("Desktop", "Documents", "Downloads")]
        matches: list[Path] = []
        for root in roots:
            if not root.is_dir():
                continue
            for candidate in root.rglob("*"):
                if len(matches) >= 50:
                    break
                try:
                    if candidate.is_file() and needle in candidate.name.lower():
                        resolved = candidate.resolve()
                        if any(resolved.is_relative_to(base.resolve()) for base in roots if base.exists()):
                            matches.append(resolved)
                except (OSError, RuntimeError):
                    continue
        if not matches:
            self.message.setText(f"没有找到包含“{query}”的文件。")
            self.message.show()
            return
        labels = [str(path.relative_to(Path.home())) for path in matches]
        selected, accepted = QInputDialog.getItem(
            self, "选择要打开的文件", "找到这些文件：", labels, 0, False
        )
        if accepted:
            target = matches[labels.index(selected)]
            self._confirm_open(target, f"打开“{target.name}”吗？")

    def _confirm_open(self, target: Path, question: str) -> None:
        if self._confirm(question):
            subprocess.Popen(["open", str(target)])

    def _confirm(self, question: str) -> bool:
        return QMessageBox.question(
            self,
            "桌面精灵请求操作",
            question,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) == QMessageBox.Yes

    def generate_pet(self) -> None:
        image_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择角色参考图",
            "",
            "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if not image_path:
            return
        prompt, accepted = QInputDialog.getMultiLineText(
            self,
            "描述桌面精灵",
            "补充描述（会保留照片主体特征）：",
            "把照片中的主体变成可爱的Q版动漫桌面精灵",
        )
        if not accepted or not prompt.strip():
            return
        raw = Path(image_path).read_bytes()
        self.message.setText("正在把任务发送到 DGX Spark…")
        self.message.show()
        QApplication.processEvents()
        try:
            job = json_request(
                "/api/v1/generate",
                {
                    "prompt": prompt.strip(),
                    "reference_filename": Path(image_path).name,
                    "reference_image_base64": base64.b64encode(raw).decode("ascii"),
                    "actions": ["yawn", "sleep", "eat"],
                },
                timeout=60,
            )
            self.generation_job = job["id"]
            self.message.setText(f"已提交生成任务：{self.generation_job}")
        except (OSError, ValueError, KeyError, urllib.error.URLError) as error:
            self.message.setText(f"提交失败：{error}")

    def place_on_primary_screen(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen.right() - self.width() - 30,
            screen.bottom() - self.height() - 30,
        )
        self.show()
        self.raise_()


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    # PySide may route KeyboardInterrupt through the currently executing Qt
    # callback and keep the event loop alive. Convert terminal signals into an
    # explicit Qt shutdown so Control+C reliably stops the desktop client.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())

    window = PetWindow()
    window.place_on_primary_screen()
    window.show()
    window.raise_()
    print(f"Desktop Pet connected to {SERVER}. Press Control+C in this terminal to stop.")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
