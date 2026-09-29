# DGX Spark Desktop Pet Agent

A local-first desktop companion built for NVIDIA DGX Spark. The Spark runs a
Qwen chat agent and ComfyUI generation pipeline; a lightweight macOS client
renders the transparent always-on-top pet, handles mouse interaction, and
executes explicitly confirmed local tools.

![Desktop pet demo](output/red-scarf-cat-final/yawn.gif)

## What it does

- chats in Chinese with a local Qwen3 model on DGX Spark;
- changes animation in response to conversation and mouse interaction;
- safely opens approved folders, applications, or a user-selected local file;
- creates a new character from a reference image with Qwen Image Edit;
- creates three action loops with Wan 2.2: yawn, sleep, and eat;
- converts generated video into transparent GIF/APNG assets;
- keeps Spark services private behind SSH port forwarding.

## Architecture

```text
macOS PySide6 pet
  ├─ transparent always-on-top window
  ├─ chat and confirmation dialogs
  └─ allowlisted local tools
             │ SSH tunnel :7000
             ▼
DGX Spark agent API
  ├─ Qwen3-4B conversation and tool planning
  ├─ ComfyUI Qwen Image Edit workflow
  └─ ComfyUI Wan 2.2 image-to-video workflow
```

The DGX cannot directly open files on the Mac. It only proposes a structured
tool call; the Mac validates it, asks the user, and executes it locally.

## Repository contents

```text
desktop_pet_agent/
  mac_client/            # PySide6 macOS companion
  spark_agent/           # chat, state, generation, and HTTP API
  tests/                 # unit tests
  workflows/             # ComfyUI API workflow JSON
output/red-scarf-cat-final/
                         # small generated demo asset set
skills/desktop-sprite-generator/
                         # reusable transparent sprite generation Skill
```

Model weights, virtual environments, user photos, generated job data, SSH
credentials, and API keys are intentionally not included.

## Requirements

- NVIDIA DGX Spark or another Linux NVIDIA CUDA host
- Python 3.12 environment with CUDA-enabled PyTorch and Transformers
- Qwen3-4B downloaded locally (the default examples use ModelScope)
- ComfyUI with the exported Qwen Image Edit and Wan 2.2 workflows' nodes/models
- FFmpeg and Pillow for video-to-animation conversion
- macOS with Python 3.9+ and PySide6

## 1. Download the chat model on Spark

Example with ModelScope:

```bash
python -m pip install -U modelscope transformers
modelscope download --model Qwen/Qwen3-4B \
  --local_dir "$HOME/model-download/Qwen3-4B"
```

The model is about 8 GB and is not stored in this repository.

## 2. Start the Spark agent

From the repository root on Spark:

```bash
python -m desktop_pet_agent.spark_agent.server \
  --host 127.0.0.1 \
  --port 7000 \
  --asset-dir "$PWD/output/red-scarf-cat-final" \
  --chat-model "$HOME/model-download/Qwen3-4B"
```

ComfyUI should listen on `127.0.0.1:8188` when character generation is needed.
Chat and the included demo animations work independently of ComfyUI.

Check the API:

```bash
curl http://127.0.0.1:7000/health
```

## 3. Create the SSH tunnel from the Mac

Replace the placeholders with the connection details supplied for your Spark:

```bash
ssh -N \
  -o ServerAliveInterval=60 \
  -o ServerAliveCountMax=5 \
  -L 7000:127.0.0.1:7000 \
  -p <SSH_PORT> <SPARK_USER>@<SPARK_HOST>
```

Keep that terminal open. Do not publish port 7000 on the internet.

## 4. Start the macOS client

From another Mac terminal in the repository root:

```bash
python3 -m venv .venv-mac
.venv-mac/bin/python -m pip install -r desktop_pet_agent/requirements-mac.txt
.venv-mac/bin/python desktop_pet_agent/mac_client/main.py
```

Controls:

- drag: move the pet;
- click: poke reaction;
- double-click: cycle actions;
- right-click: chat, generate a new pet, choose an action, reset, or quit.

Try saying: `帮我打开下载文件夹`. The Mac asks for confirmation before
opening it.

## Generation pipeline

The generation request accepts a reference image and description. The Spark
agent then runs the stages sequentially to reduce peak memory pressure:

1. Qwen Image Edit creates a full-body character on chroma green.
2. Wan 2.2 creates one loop for each action.
3. FFmpeg extracts frames.
4. The pipeline removes the green background and writes APNG/GIF files.
5. A new manifest is activated only after all actions succeed.

The workflow JSON files reference model filenames, not the model weights. See
the ComfyUI workflow nodes for the expected filenames.

## Tests

```bash
python3 -m unittest discover -s desktop_pet_agent/tests -v
```

## Safety limitations

This is a hackathon MVP, not a general-purpose remote administration service.
See [SECURITY.md](SECURITY.md). Keep it loopback-only, review model-proposed
actions, and do not remove the confirmation step around local tools.

## License

Code is available under the MIT License. Model weights retain their respective
upstream licenses. The included companion animations are generated demo assets.

