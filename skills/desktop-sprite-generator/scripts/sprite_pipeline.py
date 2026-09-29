#!/usr/bin/env python3
"""Agent-mediated image planning and transparent animation assembly (Pillow)."""
from __future__ import annotations
import argparse
from collections import deque
import hashlib
import html
import json
import re
import statistics
import sys
from pathlib import Path
from PIL import Image, ImageChops, ImageStat, ImageFilter

MOTIONS = {
    "yawn": "Frames 1-4 sleepy neutral then mouth gradually opens; 5-8 wide yawn with both paws stretching overhead; 9-12 release stretch and lower paws; 13-16 close mouth and return smoothly to first pose.",
    "sleep": "Character in a resting sleeping pose, eyes closed throughout. Frames 1-8 gentle inhalation expands torso slightly; 9-16 exhalation returns to starting pose; adapt limbs and tail to reference anatomy. No Z letters or symbols.",
    "eat": "Mime eating WITHOUT food or bowl. Frames 1-6 head lowered with subtle chewing jaw/cheeks; 7-10 raise head into satisfied closed-eye smile; 11-16 lower head and resume chewing matching first pose.",
    "idle": "Gentle breathing with one natural blink and slight tail sway; return smoothly to the initial pose.",
    "walk": "In-place walking cycle with alternating foot contacts and tail balance, no root translation or ground.",
    "poke": "Neutral then surprised blink and gentle squish/recoil, recover with a smile and return to neutral; no effect symbols.",
}
STYLE = "Rounded 2D chibi anime, oversized head/tiny body, rounded outlines, simple flat colors, comforting expressions. Preserve an existing cartoon reference's style unless restyling is requested."
ISOLATION = "Only character and worn accessories. Genuine alpha transparency. No background, floor, cast shadow, props, bowl, food, particles, text, watermark, grid lines or baked checkerboard."

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def normalize(request, request_path):
    if not isinstance(request, dict):
        raise ValueError("Request must be a JSON object")
    prompt = request.get("prompt") or ""
    if not isinstance(prompt, str):
        raise ValueError("prompt must be text")
    prompt = prompt.strip()
    reference = request.get("reference_image")
    if reference:
        reference = Path(reference).expanduser()
        if not reference.is_absolute():
            reference = Path(request_path).resolve().parent / reference
        reference = reference.resolve()
        with Image.open(reference) as im:
            im.verify()
        reference = str(reference)
    if not prompt and not reference:
        raise ValueError("Supply prompt or reference_image")
    actions = request.get("actions", ["yawn", "sleep", "eat"])
    if not isinstance(actions, list) or len(actions) < 3 or not all(isinstance(a, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,39}", a) for a in actions):
        raise ValueError("At least three safe action slugs required")
    if len(set(actions)) != len(actions):
        raise ValueError("Action names must be unique")
    specs = request.get("action_specs", {})
    if not isinstance(specs, dict):
        raise ValueError("action_specs must be an object")
    for a in actions:
        if a not in MOTIONS and not isinstance(specs.get(a), str):
            raise ValueError(f"Missing action_specs for {a}")
        if a in specs and (not isinstance(specs[a], str) or not specs[a].strip()):
            raise ValueError("Action descriptions must be nonempty text")
    size, fps = request.get("size", 320), request.get("fps", 12)
    if type(size) is not int or not 200 <= size <= 400:
        raise ValueError("size must be an integer from 200 to 400")
    if type(fps) is not int or not 12 <= fps <= 15:
        raise ValueError("fps must be an integer from 12 to 15")
    formats = request.get("formats", ["apng", "gif"])
    if not isinstance(formats, list) or not formats or any(f not in ("apng", "gif") for f in formats) or len(set(formats)) != len(formats):
        raise ValueError("formats must contain apng and/or gif without duplicates")
    alignment = request.get("alignment", "bottom-center")
    if alignment not in ("bottom-center", "cell"):
        raise ValueError("alignment must be bottom-center or cell")
    identity = request.get("identity", "")
    if not isinstance(identity, str):
        raise ValueError("identity must be text")
    layout=request.get("layout", "grid")
    if layout not in ("grid", "components"):
        raise ValueError("layout must be grid or components")
    return dict(prompt=prompt, reference_image=reference, identity=identity, actions=actions, layout=layout,
                size=size, fps=fps, formats=formats, alignment=alignment, action_specs=specs,
                mode="reference_text" if reference and prompt else "image" if reference else "text")

def prepare(request_path, out):
    req = normalize(read_json(request_path), request_path)
    out = Path(out).resolve()
    if out.exists():
        raise ValueError("Use a new output directory; existing jobs are not overwritten")
    out.mkdir(parents=True)
    (out / "sources").mkdir()
    subject = req["prompt"] or "Turn the supplied character into a cute desktop companion retaining recognizable identity."
    identity = req["identity"] or "Preserve visible identity features from the reference when present."
    character = f"Use case: stylized-concept. Canonical desktop character anchor. {subject}\nIdentity: {identity}\n{STYLE}\nFull body, neutral pose, front three-quarter view, generous margins. {ISOLATION}"
    prompts = {}
    for action in req["actions"]:
        motion = req["action_specs"].get(action, MOTIONS.get(action))
        prompts[action] = f"Use case: identity-preserve. Reference is canonical character: preserve exact face, markings, palette, accessories and style. Generate a SQUARE sheet with EXACTLY 4 columns and 4 rows, 16 equal square cells, one complete character in each. No visible grid. Read left-to-right then top-to-bottom as ONE sequential cyclic animation, not unrelated stickers. Same camera/scale, centered x=50%, ground-contact baseline y=85% WITHIN EACH CELL; fit poses within inner 80% of cell. Transparent gutters. Action: {action}. {motion} Each frame is the NEXT small articulated movement. Last pose approaches first; no sudden jumps. {ISOLATION}"
    plan = dict(schema_version=1, request=req, grid=[4, 4], frame_count=16, character_prompt=character,
                action_prompts=prompts, sources={"character": "sources/character.png", **{a: f"sources/{a}.png" for a in req["actions"]}})
    write_json(out / "plan.json", plan)
    return {"status": "awaiting_image_generation", "job": str(out), "plan": str(out / "plan.json")}

def alpha_bbox(im, label):
    alpha = im.getchannel("A")
    lo, hi = alpha.getextrema()
    if lo > 0 or hi == 0:
        raise ValueError(f"{label}: missing transparency or empty image; regenerate with alpha")
    box = alpha.point(lambda v: 255 if v > 8 else 0).getbbox()
    if not box:
        raise ValueError(f"{label}: empty foreground")
    if box[0] <= 1 or box[1] <= 1 or box[2] >= im.width - 1 or box[3] >= im.height - 1:
        raise ValueError(f"{label}: foreground at cell edge; clipping, incorrect grid or background")
    return box

def component_frames(im, label):
    """Opt-in for visually checked sheets whose outer transparent margins were trimmed.

    Require exactly 16 substantial connected silhouettes in four ordered rows.
    Keep native edge alpha around each silhouette; discard isolated export speckles.
    """
    w,h=im.size
    pixels=bytearray(im.getchannel("A").point(lambda a:255 if a>=32 else 0).tobytes())
    components=[]
    for start in range(w*h):
        if not pixels[start]: continue
        queue=deque([start]); pixels[start]=0; points=[]
        while queue:
            v=queue.popleft(); points.append(v)
            x,y=v%w,v//w
            neighbors=[]
            if x: neighbors.append(v-1)
            if x+1<w: neighbors.append(v+1)
            if y: neighbors.append(v-w)
            if y+1<h: neighbors.append(v+w)
            for n in neighbors:
                if pixels[n]: pixels[n]=0; queue.append(n)
        if len(points)>w*h/16*.02:
            xs=[v%w for v in points]; ys=[v//w for v in points]
            components.append((min(xs),min(ys),max(xs)+1,max(ys)+1,points))
    if len(components)!=16:
        raise ValueError(f"{label}: expected 16 separate silhouettes; found {len(components)}")
    components.sort(key=lambda b:(b[1]+b[3])/2)
    ordered=[]
    for r in range(4):
        row=sorted(components[r*4:r*4+4],key=lambda b:b[0])
        centers=[(b[1]+b[3])/2 for b in row]
        if max(centers)-min(centers)>h/8:
            raise ValueError(f"{label}: ambiguous component row; regenerate")
        ordered.extend(row)
    edge=round(max(w,h)/4*1.3)
    frames=[]; boxes=[]
    for i,(x0,y0,x1,y1,points) in enumerate(ordered):
        if x0==0 or y0==0 or x1==w or y1==h:
            raise ValueError(f"{label}: silhouette {i} clipped at sheet boundary")
        pad=2
        box=(max(0,x0-pad),max(0,y0-pad),min(w,x1+pad),min(h,y1+pad))
        crop=im.crop(box)
        mask=Image.new("L",crop.size)
        data=bytearray(crop.width*crop.height)
        for v in points:
            data[(v//w-box[1])*crop.width+(v%w-box[0])]=255
        mask.frombytes(bytes(data))
        mask=mask.filter(ImageFilter.MaxFilter(5))
        crop.putalpha(ImageChops.multiply(crop.getchannel("A"),mask))
        frame=Image.new("RGBA",(edge,edge))
        if crop.width>=edge-4 or crop.height>=edge-4:
            raise ValueError(f"{label}: overlapping/oversize silhouette")
        frame.alpha_composite(crop,((edge-crop.width)//2,round(edge*.92)-crop.height))
        boxes.append(alpha_bbox(frame,f"{label} component {i}")); frames.append(frame)
    return frames,boxes

def split_sheet(path, layout="grid"):
    with Image.open(path) as source:
        im = source.convert("RGBA")
    if layout=="components":
        return component_frames(im,path.name)
    if im.width != im.height:
        raise ValueError(f"{path.name}: require square sheet")
    frames, boxes = [], []
    for i in range(16):
        col,row=i%4,i//4
        frame=im.crop((round(col*im.width/4),round(row*im.height/4),round((col+1)*im.width/4),round((row+1)*im.height/4)))
        boxes.append(alpha_bbox(frame, f"{path.name} cell {i+1}"))
        frames.append(frame)
    return frames, boxes

def durations(count, fps, quantum=1):
    marks = [round(i*1000/fps/quantum)*quantum for i in range(count+1)]
    return [marks[i+1]-marks[i] for i in range(count)]

def visual_distance(a, b):
    scores = []
    for color in ("white", "#202533"):
        bg = Image.new("RGBA", a.size, color)
        aa = Image.alpha_composite(bg, a).convert("RGB")
        bb = Image.alpha_composite(bg, b).convert("RGB")
        scores.append(sum(ImageStat.Stat(ImageChops.difference(aa, bb)).mean)/(3*255))
    return sum(scores)/len(scores)

def encode_gif(frames, path, delays):
    atlas = Image.new("RGB", (frames[0].width*len(frames), frames[0].height))
    for i, f in enumerate(frames):
        atlas.paste(f.convert("RGB"), (i*f.width, 0))
    palette = atlas.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    colors=palette.getpalette()[:765]
    colors += [0]*(765-len(colors))
    # If the quantizer picks reserved 255, it is color-equivalent to index 0.
    palette.putpalette(colors+colors[:3])
    encoded = []
    for f in frames:
        p = f.convert("RGB").quantize(palette=palette, dither=Image.Dither.NONE)
        p = p.point(lambda v: 0 if v == 255 else v)
        p.putpalette(palette.getpalette())
        p.paste(255, mask=f.getchannel("A").point(lambda a: 255 if a < 128 else 0))
        p.info["transparency"] = 255
        encoded.append(p)
    encoded[0].save(path, format="GIF", save_all=True, append_images=encoded[1:],
                    duration=delays, loop=0, transparency=255, background=255, disposal=2, optimize=False)

def inspect_encoded(path, size, expected_ms, expected_frames):
    with Image.open(path) as im:
        count, total = getattr(im, "n_frames", 1), 0
        if im.size != (size, size) or count < 4 or im.info.get("loop") != 0:
            raise ValueError(f"Invalid animated file: {path}")
        for i in range(count):
            im.seek(i)
            alpha_bbox(im.convert("RGBA"), f"{path.name} decoded frame {i}")
            total += im.info.get("duration", 0)
        if abs(total-expected_ms) > 2:
            raise ValueError(f"Incorrect duration: {path}")
        return dict(decoded_frames=count, source_frames=expected_frames, duration_ms=total,
                    infinite_loop=True, transparent=True)

def preview(job, actions, formats):
    options = "".join(f'<option value="{a}">{html.escape(a)}</option>' for a in actions)
    cards = "".join(f'<article><h2>{html.escape(a)}</h2><img src="{a}.{formats[0]}" alt="{a}"></article>' for a in actions)
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>桌面精灵 · 动作预览</title>
<style>body{font:16px system-ui;margin:36px;color:#253140;background:#f5f2ec}h1{font-size:26px}button,select{padding:10px;margin:5px;border:1px solid #aaa;border-radius:8px}main{display:flex;flex-wrap:wrap;gap:20px}article{text-align:center;padding:18px;border-radius:18px;background:#fff}img{width:320px;height:320px;object-fit:contain;background:repeating-conic-gradient(#d7d9dc 0% 25%,#fff 0% 50%) 50%/24px 24px}body[data-bg="dark"] img{background:#202533}body[data-bg="light"] img{background:white}h2{font-size:18px}p{max-width:850px;line-height:1.6}</style>
<h1>桌面精灵 · 透明循环动作</h1><p>背景只用于检查透明边缘，不包含在动图文件中。观察耳朵、尾巴、围巾是否一致，以及循环接缝处有无跳动。</p><button onclick="document.body.dataset.bg='grid'">棋盘格</button><button onclick="document.body.dataset.bg='light'">浅色</button><button onclick="document.body.dataset.bg='dark'">深色</button><main>CARDS</main><h2>状态切换测试</h2><select id="state">OPTIONS</select><br><img id="pet" alt="切换动作"><script>const s=document.getElementById('state'),p=document.getElementById('pet');function update(){p.src=s.value+'.EXT'}s.onchange=update;update();</script></html>'''
    (job/"preview.html").write_text(page.replace("CARDS",cards).replace("OPTIONS",options).replace("EXT",formats[0]),encoding="utf-8")

def build(job):
    job = Path(job).resolve()
    if (job/"manifest.json").exists():
        raise ValueError("Job already built; use a fresh job for revisions")
    plan = read_json(job/"plan.json")
    req = normalize(plan["request"],job/"plan.json")
    with Image.open(job/"sources/character.png") as anchor:
        alpha_bbox(anchor.convert("RGBA"),"character anchor")
    data = {a:split_sheet(job/f"sources/{a}.png",req["layout"]) for a in req["actions"]}
    largest = max(max((b[2]-b[0])/f.width,(b[3]-b[1])/f.height)
                  for frames,boxes in data.values() for f,b in zip(frames,boxes))
    size = req["size"]
    unit = size*.78/largest if req["alignment"]=="bottom-center" else size*.9
    manifest = dict(schema_version=1,mode=req["mode"],size=[size,size],fps=req["fps"],loop=0,
                    visual_review={"status":"pending","notes":"Requires visual inspection and playback."},actions={})
    qa = {"actions":{},"warnings":[]}
    (job/"contacts").mkdir(exist_ok=True)
    for action,(raw,boxes) in data.items():
        frames=[]
        folder=job/"frames"/action
        folder.mkdir(parents=True,exist_ok=True)
        for i,(frame,box) in enumerate(zip(raw,boxes)):
            canvas=Image.new("RGBA",(size,size))
            if req["alignment"]=="bottom-center":
                crop=frame.crop(box)
                sprite=crop.resize((max(1,round(crop.width*unit/frame.width)),max(1,round(crop.height*unit/frame.height))),Image.Resampling.LANCZOS)
                pos=((size-sprite.width)//2,round(size*.92)-sprite.height)
            else:
                sprite=frame.resize((round(unit),round(unit)),Image.Resampling.LANCZOS)
                pos=((size-sprite.width)//2,(size-sprite.height)//2)
            canvas.alpha_composite(sprite,pos)
            alpha_bbox(canvas,f"{action} output {i}")
            canvas.save(folder/f"{i:03}.png")
            frames.append(canvas)
        unique=len({hashlib.sha256(f.tobytes()).hexdigest() for f in frames})
        if unique<4:
            raise ValueError(f"{action}: too few distinct poses")
        distances=[visual_distance(a,b) for a,b in zip(frames,frames[1:])]
        seam=visual_distance(frames[-1],frames[0])
        median=statistics.median(distances)
        warnings=[]
        if seam>max(.025,median*2.5):
            warnings.append("Large loop seam: inspect and regenerate if visible")
        if max(distances)>max(.035,median*3):
            warnings.append("Large adjacent change: inspect for jumping or identity drift")
        entry=dict(files={},frames=len(frames),anchor=[.5,.92] if req["alignment"]=="bottom-center" else [.5,.5],timings_ms={},duration_ms={})
        checks={}
        for fmt in req["formats"]:
            path=job/f"{action}.{fmt}"
            delays=durations(len(frames),req["fps"],10 if fmt=="gif" else 1)
            if fmt=="apng":
                frames[0].save(path,format="PNG",save_all=True,append_images=frames[1:],duration=delays,loop=0,disposal=0,blend=0)
            else:
                encode_gif(frames,path,delays)
            checks[fmt]=inspect_encoded(path,size,sum(delays),len(frames))
            entry["files"][fmt]=path.name
            entry["timings_ms"][fmt]=delays
            entry["duration_ms"][fmt]=sum(delays)
        contact=Image.new("RGBA",(size*4,size*4))
        for i,f in enumerate(frames):
            contact.alpha_composite(f,((i%4)*size,(i//4)*size))
        contact.save(job/"contacts"/f"{action}.png")
        manifest["actions"][action]=entry
        qa["actions"][action]=dict(unique_frames=unique,seam_difference=seam,median_adjacent_difference=median,
            max_adjacent_difference=max(distances),warnings=warnings,encoded=checks)
        qa["warnings"].extend(f"{action}: {w}" for w in warnings)
    preview(job,req["actions"],req["formats"])
    write_json(job/"qa.json",qa)
    write_json(job/"manifest.json",manifest)
    return {"status":"built_needs_visual_review","manifest":str(job/"manifest.json"),"warnings":qa["warnings"]}

def validate(job):
    job=Path(job)
    m=read_json(job/"manifest.json")
    if len(m["actions"])<3:
        raise ValueError("At least three actions required")
    results={}
    for action,entry in m["actions"].items():
        results[action]={fmt:inspect_encoded(job/path,m["size"][0],entry["duration_ms"][fmt],entry["frames"]) for fmt,path in entry["files"].items()}
    return {"status":"file_checks_passed","visual_review":m["visual_review"],"actions":results}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest="command",required=True)
    p=subs.add_parser("prepare")
    p.add_argument("--request",required=True)
    p.add_argument("--out",required=True)
    for name in ("build","validate"):
        p=subs.add_parser(name)
        p.add_argument("--job",required=True)
    args=parser.parse_args()
    try:
        result=prepare(args.request,args.out) if args.command=="prepare" else build(args.job) if args.command=="build" else validate(args.job)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print(json.dumps({"status":"error","message":str(exc)},ensure_ascii=False),file=sys.stderr)
        return 2
    return 0

if __name__=="__main__":
    sys.exit(main())
