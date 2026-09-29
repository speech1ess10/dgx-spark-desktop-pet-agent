# DGX Spark 桌面精灵 Agent

<p align="center"><a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a></p>
<p align="center"><strong>把一张照片变成可爱、会动、能对话的桌面陪伴精灵。</strong></p>
<p align="center">基于 NVIDIA DGX Spark · Qwen · Wan 2.2 · ComfyUI · PySide6</p>
<p align="center"><img src="docs/assets/demo-dog/yawn.gif" width="320" alt="正在打哈欠的桌面精灵"></p>

## 从真实照片到有生命感的桌面精灵

用户向 Agent 上传参考照片后，DGX Spark 上的 Qwen Image Edit 会生成统一的
Q 版角色设定图；Wan 2.2 根据角色图生成动作视频；后处理流水线再把视频转换为
透明背景、无缝循环的 GIF/APNG，最终交给 macOS 桌面精灵使用。

<table>
  <tr><th align="center">用户上传的参考照片</th><th align="center">Qwen 生成的 Q 版角色</th></tr>
  <tr>
    <td align="center"><img src="docs/assets/demo-dog/reference.png" width="300" alt="白色小狗参考照片"></td>
    <td align="center"><img src="docs/assets/demo-dog/character.png" width="300" alt="Qwen 生成的 Q 版桌面精灵"></td>
  </tr>
</table>

## 三组独立生成的循环动作

每个动作都由 Wan 2.2 独立生成，Agent 可以根据对话和状态切换动作。演示动图
尺寸为 320×320、12 FPS、61 帧，单次循环约 5 秒。

| 吃饭 | 睡觉 | 打哈欠 |
|:---:|:---:|:---:|
| ![精灵吃饭](docs/assets/demo-dog/eat.gif) | ![精灵睡觉](docs/assets/demo-dog/sleep.gif) | ![精灵打哈欠](docs/assets/demo-dog/yawn.gif) |
| [查看 Wan 原始视频](docs/assets/demo-dog/eat.mp4) | [查看 Wan 原始视频](docs/assets/demo-dog/sleep.mp4) | [查看 Wan 原始视频](docs/assets/demo-dog/yawn.mp4) |

## 为什么它是一个 Agent

- **本地模型对话：** Qwen3-4B 在 DGX Spark 上运行，为精灵提供中文对话和个性。
- **自主视觉生成：** 上传照片和描述后，自动生成新形象与三组动作。
- **有状态的行为：** 对话、鼠标互动和指令都会改变精灵的动作状态。
- **安全的电脑工具：** 精灵可以建议打开 Mac 上经过许可的文件夹、应用或用户选择的文件。
- **操作前确认：** 本地工具受白名单限制，并且执行前必须得到用户确认。
- **私有连接：** Spark 服务只监听本机地址，通过 SSH 隧道与 Mac 通信。

## 系统架构

\`\`\`text
macOS PySide6 桌面精灵
  ├─ 透明、置顶的悬浮窗口
  ├─ 鼠标互动、对话与操作确认
  └─ 白名单本地工具
             │ SSH 隧道 :7000
             ▼
DGX Spark Agent API
  ├─ Qwen3-4B 对话与工具规划
  ├─ Qwen Image Edit 角色生成
  ├─ Wan 2.2 图生视频
  └─ FFmpeg/Pillow 透明 GIF/APNG 流水线
             │ 本机 :8188
             ▼
          ComfyUI
\`\`\`

DGX 无法直接操作 Mac。它只返回结构化的工具建议；macOS 客户端会验证建议、
征求用户确认，然后才执行白名单内的本地操作。

## 仓库结构

\`\`\`text
desktop_pet_agent/
  mac_client/            # PySide6 macOS 桌面精灵
  spark_agent/           # 对话、状态、生成任务与 HTTP API
  tests/                 # 单元测试
  workflows/             # 导出的 ComfyUI API 工作流
docs/assets/demo-dog/    # 照片生成桌面精灵的展示素材
output/red-scarf-cat-final/
                         # 小型回退动画资源
skills/desktop-sprite-generator/
                         # 可复用的透明精灵动图生成 Skill
\`\`\`

模型权重、虚拟环境、私人连接信息、API 密钥以及用户生成任务历史不会提交到仓库。

## 环境要求

- NVIDIA DGX Spark，或其他带 NVIDIA CUDA GPU 的 Linux 主机
- Python 3.12、支持 CUDA 的 PyTorch 和 Transformers
- 用于对话的 Qwen3-4B
- 安装了 Qwen Image Edit、Wan 2.2 所需模型和节点的 ComfyUI
- FFmpeg 和 Pillow
- Python 3.9+ 与 PySide6 的 macOS

## 快速开始

### 1. 在 Spark 下载对话模型

\`\`\`bash
python -m pip install -U modelscope transformers
modelscope download --model Qwen/Qwen3-4B \
  --local_dir "$HOME/model-download/Qwen3-4B"
\`\`\`

模型约 8 GB，不包含在本仓库中。

### 2. 启动 Spark Agent

\`\`\`bash
python -m desktop_pet_agent.spark_agent.server \
  --host 127.0.0.1 \
  --port 7000 \
  --asset-dir "$PWD/output/red-scarf-cat-final" \
  --chat-model "$HOME/model-download/Qwen3-4B"
\`\`\`

需要生成新角色时，ComfyUI 必须监听 \`127.0.0.1:8188\`。没有启动 ComfyUI
时，对话功能和仓库附带的回退动画仍然可以使用。

### 3. 在 Mac 建立 SSH 隧道

把占位符替换成比赛方提供的 Spark 连接信息：

\`\`\`bash
ssh -N \
  -o ServerAliveInterval=60 \
  -o ServerAliveCountMax=5 \
  -L 7000:127.0.0.1:7000 \
  -p <SSH端口> <Spark用户名>@<Spark主机>
\`\`\`

保持这个终端窗口运行，不要把 7000 端口直接暴露在公网。

### 4. 启动 macOS 客户端

\`\`\`bash
python3 -m venv .venv-mac
.venv-mac/bin/python -m pip install -r desktop_pet_agent/requirements-mac.txt
.venv-mac/bin/python desktop_pet_agent/mac_client/main.py
\`\`\`

操作方式：拖动可移动精灵，单击会触发被戳反应，双击轮换动作，右键可以
对话、生成新精灵、选择动作、重置或退出。

可以试着说：\`帮我打开下载文件夹\`。执行前，Mac 会弹窗请求确认。

## 角色与动作生成流程

1. macOS 客户端上传参考图片和角色描述。
2. Qwen Image Edit 在纯绿背景上生成完整角色设定图。
3. Wan 2.2 分别生成打哈欠、睡觉、吃饭视频。
4. FFmpeg 从视频中提取逐帧图像。
5. 流水线移除绿色背景并生成透明 APNG/GIF。
6. 三组动作全部成功后，服务端才会启用新精灵的资源清单。

仓库中的工作流 JSON 只保存模型文件名，不包含模型权重。

## 运行测试

\`\`\`bash
python3 -m unittest discover -s desktop_pet_agent/tests -v
\`\`\`

## 安全说明

本项目是黑客松 MVP，不是通用远程管理工具。请阅读 [SECURITY.md](SECURITY.md)，
让 API 只监听本机地址，并保留本地操作前的确认步骤。

## 许可证

代码采用 MIT License。模型权重遵循各自的上游许可证。仓库内的精灵图片、
动图和视频作为本项目的生成效果演示提供。

