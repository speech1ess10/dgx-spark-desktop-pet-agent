---
name: desktop-sprite-generator
description: Generate transparent animated desktop companions from text, a reference image with instructions, or an image alone. Produce consistent chibi characters with at least three independent looping APNG/GIF actions. Use for sprite assets, not desktop application implementation.
---

# 桌面精灵动图生成器

Deliver real transparent animated assets. Default: 320×320, 12 FPS, infinite loops, yawn/sleep/eat. Only the character and worn accessories: no floor, shadow, bowl, food props, text, particles or baked checkerboard. Default aesthetic: rounded 2D chibi anime, big head/small body, simple color blocks, comforting expressions. User identity/style instructions take precedence.

## Runtime and interface

Use the host Agent's image-generation tool for character and articulated animation frames, then Python 3.10+ / Pillow for deterministic assembly. Built-in image generation needs no API key. The Python CLI does not itself call a model. If the host lacks image generation, report the missing capability rather than substituting stock characters. This package does not deploy a model on DGX Spark.

Read [references/interface.md](references/interface.md) for commands and JSON contracts. Resolve script paths relative to this skill directory. Use an isolated Python with `requirements.txt`, or the host's bundled Python with Pillow.

## Character module

Infer input mode: prompt only = text; reference + prompt = reference_text; reference only = image. Inspect reference pictures first; record visible colors, markings, ears, face, clothing and proportions in `identity`. Photos become cute cartoons retaining recognizable features; existing cartoon styles are preserved unless restyling is requested. Remove the original background.

Run `prepare` with a request JSON and a new output directory. Generate `plan.json.character_prompt` using actual transparent-background mode, including the input reference when present. Inspect and copy the result to `sources/character.png`. This is the identity anchor for all actions. Record exact prompts and the provider in `generation.json`.

## Action module

Read [references/animation.md](references/animation.md) before generation. Generate each `plan.json.action_prompts` entry as a separate transparent 4×4 sprite sheet, always referencing the inspected anchor. Save to `sources/{action}.png`. Each sheet contains 16 chronological adjacent poses, read left-to-right/top-to-bottom.

Use real articulated poses: yawn opens the mouth and stretches; sleep closes eyes with breathing; eat lowers the head, chews and looks satisfied (mime eating, no bowl/food). Lock markings, accessories, camera, style and scale. Do not pass off scaling a static image or crossfades as finished animation. The last pose approaches the first for cyclic playback. Include at least three actions; supplement a single requested action with defaults. Extra action names need `action_specs`.

Inspect each sheet for exact grid, one whole character per cell, transparent gutters, correct action progression, consistent identity and no clipped limbs. Regenerate malformed sheets; the compiler must not guess broken layouts. If the provider trimmed only outer margins but all 16 silhouettes are intact in four verified rows, use `layout: components` as documented in the interface. Keep fixed camera/head angle and request small motion increments when a first attempt changes poses too abruptly.

## Transparency and export module

Run `build`. It preserves native alpha, cuts cells, applies one shared scale across actions, and exports individual APNG/GIF, RGBA frames, manifest, QA metrics, contact sheets and offline preview. APNG retains partial alpha; GIF uses 1-bit transparency and distributed 10 ms timing units to approximate the target frame rate without cumulative truncation.

If alpha is missing or scenery remains, use image generation's background-removal/edit capability and rebuild. Never remove all white/black pixels because these may belong to the character. No arbitrary chroma keying by default.

Inspect `qa.json`, contact sheets and animated `preview.html` on light/dark/checker backgrounds. Check action semantics, full silhouette, identity, no ghost trails and loop seam. Metrics cannot prove natural motion. Correct suspect sheets with targeted regeneration, up to two retries per action; report unresolved issues honestly. Do not hide bad motion with duplicated static frames or dissolves.

After actual visual review, set `visual_review` in `manifest.json` to `passed` or `needs_revision`, with notes. Numerical validation alone never earns visual approval. Deliver links to all action files, manifest and preview; identify the image provider and preserve source sheets/prompts for revisions.
