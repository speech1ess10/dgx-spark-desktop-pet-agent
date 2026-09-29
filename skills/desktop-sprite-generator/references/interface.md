# Input/output contract

Input JSON (UTF-8):
```json
{
  "prompt": "一只黑白相间的小猫，戴红色围巾",
  "reference_image": null,
  "identity": "black fur, white muzzle and belly, amber eyes, red scarf",
  "actions": ["yawn", "sleep", "eat"],
  "size": 320,
  "fps": 12,
  "formats": ["apng", "gif"],
  "alignment": "bottom-center",
  "action_specs": {}
}
```

`prompt` or `reference_image` is required. Mode is inferred. `identity` is the Agent's visual description for reference inputs. Size: square 200–400 px. FPS: 12–15. At least 3 unique ASCII action slugs. Additional built-in actions: idle/walk/poke. Other names require motion text in `action_specs`. `alignment`: bottom-center (stable desk contact) or cell (preserve authored translation). Relative reference paths resolve against the request file. Inputs are validated before creating a job.

```bash
python /absolute/skill/scripts/sprite_pipeline.py prepare --request /path/request.json --out /path/new-job
# Agent generates actual transparent anchor and sheets at plan.json destinations.
python /absolute/skill/scripts/sprite_pipeline.py build --job /path/new-job
python /absolute/skill/scripts/sprite_pipeline.py validate --job /path/new-job
```

CLI returns JSON on stdout; errors use stderr and exit 2. `prepare` plans prompts, it does not perform model inference. `build` requires real sheets and refuses an existing manifest. For revisions use a fresh job and reuse unchanged source sheets. A partial failed build can be retried before a manifest exists.

Optional `layout` defaults to `grid`. After visually confirming a correct 4×4 arrangement whose margins were trimmed by a provider, `components` extracts exactly 16 substantial separate alpha silhouettes in four rows. It preserves native edge alpha, drops isolated tiny export speckles, and rejects ambiguous or clipped silhouettes. This mode requires connected character silhouettes and cannot support intentionally detached character parts. Never use it to guess an incorrect grid.

Output files: `plan.json`, Agent-recorded `generation.json`, `sources/character.png`, `sources/{action}.png`, `frames/{action}/000.png…`, `{action}.apng`, `{action}.gif`, `contacts/{action}.png`, `qa.json`, `manifest.json`, `preview.html`.

Manifest paths are relative to the job. Consumers read `actions[name].files`, `duration_ms`, normalized `anchor` and `loop: 0`. Preview checkerboard exists only in CSS, never in exported images. Bottom-center anchor is `[0.5,0.92]`; cell mode anchor is `[0.5,0.5]`.

Examples:
- `$desktop-sprite-generator 生成戴红围巾的黑白猫，打哈欠、睡觉和进食。`
- `$desktop-sprite-generator 基于这张参考图让它睡觉，另配打哈欠和进食。`
- `$desktop-sprite-generator` with only an image: inspect, derive identity, generate defaults.

Install the complete folder into the host skill directory (Codex: `~/.codex/skills/`), then start a new session if needed. Packaging does not itself register a skill. The host must support image generation/reference images. Install Python dependencies with `python -m pip install -r requirements.txt`. No model weights or server are bundled.

Encoding follows [Pillow's official documentation](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html): APNG source replacement; GIF disposal-to-background with a reserved transparent palette index.
