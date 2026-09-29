from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from desktop_pet_agent.spark_agent.chat import QwenChatEngine
from desktop_pet_agent.spark_agent.core import AssetCatalog, DesktopPetAgent
from desktop_pet_agent.spark_agent.comfy import ComfyClient
from desktop_pet_agent.spark_agent.generation import GenerationManager


class AgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        actions = {}
        for name in ("yawn", "sleep", "eat"):
            (root / f"{name}.gif").write_bytes(b"GIF89a")
            actions[name] = {"files": {"gif": f"{name}.gif"}}
        (root / "manifest.json").write_text(
            json.dumps({"actions": actions}), encoding="utf-8"
        )
        self.agent = DesktopPetAgent(AssetCatalog(root))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_chinese_sleep_command(self) -> None:
        result = self.agent.command(text="困了，去睡觉吧")
        self.assertEqual(result["action"], "sleep")

    def test_eat_command(self) -> None:
        result = self.agent.command(text="给你吃一点零食")
        self.assertEqual(result["action"], "eat")

    def test_poke_falls_back_to_available_reaction(self) -> None:
        result = self.agent.poke()
        self.assertEqual(result["action"], "yawn")
        self.assertIn("被你发现", result["speech"])

    def test_unknown_text_keeps_current_action(self) -> None:
        first = self.agent.command(action="sleep")
        second = self.agent.command(text="今天天气不错")
        self.assertEqual(first["action"], second["action"])
        self.assertGreater(second["sequence"], first["sequence"])

    def test_asset_url_has_version_for_hot_reload(self) -> None:
        state = self.agent.snapshot()
        self.assertIn("?v=", state["asset_url"])

    def test_comfy_output_file_discovery(self) -> None:
        files = ComfyClient._collect_files(
            {"20": {"images": [{"filename": "pet.png", "type": "output"}]}}
        )
        self.assertEqual(files[0]["filename"], "pet.png")

    def test_prompts_require_chroma_background(self) -> None:
        self.assertIn("#00FF00", GenerationManager._qwen_prompt("保留黑猫特征"))
        self.assertIn("seamless loop", GenerationManager._wan_prompt("sleep"))

    def test_chat_response_rejects_unsafe_tool(self) -> None:
        value = QwenChatEngine.parse_response(
            '{"reply":"不执行危险操作","action":"sleep",'
            '"tool":{"name":"shell","arguments":{"command":"rm"}}}'
        )
        self.assertEqual(value["reply"], "不执行危险操作")
        self.assertEqual(value["action"], "sleep")
        self.assertIsNone(value["tool"])

    def test_chat_response_accepts_allowed_folder(self) -> None:
        value = QwenChatEngine.parse_response(
            '{"reply":"好的","action":"yawn",'
            '"tool":{"name":"open_folder","arguments":{"folder":"Downloads"}}}'
        )
        self.assertEqual(value["tool"]["name"], "open_folder")
        self.assertEqual(value["tool"]["arguments"]["folder"], "Downloads")


if __name__ == "__main__":
    unittest.main()
