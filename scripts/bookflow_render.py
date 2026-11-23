#!/usr/bin/env python3
"""Render a silent, animated BookFlow plan with resumable scene-beat clips."""
from __future__ import annotations
import argparse, hashlib, json, shutil, subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

PALETTE = {
    "wood": (55, 36, 27), "paper2": (234, 219, 191), "ink": (31, 42, 43),
    "muted": (102, 91, 73), "gold": (190, 145, 69), "green": (60, 104, 84),
    "cream": (255, 249, 236), "highlight": (239, 205, 112), "shadow": (22, 15, 12)
}
FONT_AR_BOLD = "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf"
FONT_LATIN = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_LATIN_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

def font(path, size):
    return ImageFont.truetype(path, size)

def text(draw, xy, value, fnt, fill, anchor="mm"):
    rtl = any("\u0600" <= c <= "\u06ff" for c in value)
    kwargs = {"direction": "rtl", "language": "ar"} if rtl else {}
    draw.text(xy, value, font=fnt, fill=fill, anchor=anchor, **kwargs)

def wrap(draw, value, fnt, max_width, rtl=False):
    words, lines, current = value.split(), [], ""
    for word in words:
        candidate = (current + " " + word).strip()
        kwargs = {"direction": "rtl", "language": "ar"} if rtl else {}
        box = draw.textbbox((0, 0), candidate, font=fnt, **kwargs)
        if box[2] - box[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines

def draw_wrapped(draw, value, center, fnt, fill, max_width, line_gap=12, rtl=False):
    lines = wrap(draw, value, fnt, max_width, rtl)
    heights = [fnt.size * 1.25 for _ in lines]
    total = sum(heights) + line_gap * max(0, len(lines)-1)
    y = center[1] - total/2
    for line, h in zip(lines, heights):
        text(draw, (center[0], y + h/2), line, fnt, fill)
        y += h + line_gap

def make_frame(scene, index, total, beat, width, height, path):
    im = Image.new("RGB", (width, height), PALETTE["wood"])
    d = ImageDraw.Draw(im)
    for y in range(0, height, max(18, height//70)):
        d.line((0, y, width, y+int(height*.012)), fill=(59 + (y//13)%7, 39, 29), width=max(2,height//700))
    margin = int(width*.075)
    book_top, book_bottom = int(height*.13), int(height*.88)
    d.rounded_rectangle((margin+12, book_top+20, width-margin+12, book_bottom+20), radius=34, fill=PALETTE["shadow"])
    d.rounded_rectangle((margin, book_top, width-margin, book_bottom), radius=30, fill=PALETTE["paper2"], outline=PALETTE["gold"], width=3)
    gutter = width//2
    d.line((gutter, book_top+22, gutter, book_bottom-22), fill=(183,157,121), width=5)
    left, right = margin+int(width*.065), width-margin-int(width*.065)
    for x1,x2 in ((left,gutter-28),(gutter+28,right)):
        for j in range(8):
            yy = book_top+int(height*.12)+j*int(height*.055)
            d.line((x1,yy,x2,yy), fill=(211,196,170), width=max(1,width//1500))
    text(d,(width//2,book_top+int(height*.065)),"MONEY • MINDSET",font(FONT_LATIN_BOLD,int(height*.025)),PALETTE["green"])
    text(d,(left+12,book_bottom-int(height*.055)),f"{index+1:02d}",font(FONT_LATIN,int(height*.022)),PALETTE["muted"],anchor="lm")
    highlight_y = book_top+int(height*(.30 + .12*beat))
    if beat == 0:
        hx1,hx2 = left+12,gutter-35
    elif beat == 1:
        hx1,hx2 = gutter+35,right-12
    else:
        hx1,hx2 = left+12,right-12
    d.rounded_rectangle((hx1,highlight_y,hx2,highlight_y+int(height*.052)),radius=10,fill=PALETTE["highlight"])
    card_w, card_h = int(width*.72), int(height*.39)
    cx, cy = width//2, int(height*.54)
    d.rounded_rectangle((cx-card_w//2+10,cy-card_h//2+14,cx+card_w//2+10,cy+card_h//2+14),radius=24,fill=(194,178,151))
    d.rounded_rectangle((cx-card_w//2,cy-card_h//2,cx+card_w//2,cy+card_h//2),radius=24,fill=PALETTE["cream"],outline=PALETTE["gold"],width=3)
    title, ar = scene["text_en"], scene["translation_ar"]
    draw_wrapped(d,title,(cx,cy-int(height*.105)),font(FONT_LATIN_BOLD,int(height*.038)),PALETTE["ink"],int(card_w*.84),line_gap=int(height*.010))
    d.line((cx-int(card_w*.28),cy+int(height*.045),cx+int(card_w*.28),cy+int(height*.045)),fill=PALETTE["gold"],width=max(2,width//600))
    draw_wrapped(d,ar,(cx,cy+int(height*.135)),font(FONT_AR_BOLD,int(height*.028)),PALETTE["green"],int(card_w*.84),line_gap=int(height*.008),rtl=True)
    mx,my = int(width*.83), int(height*.79)
    if beat == 0:
        for k in range(3):
            r=int(height*(.025+k*.004)); x=mx+k*int(width*.018)
            d.ellipse((x-r,my-r,x+r,my+r),fill=PALETTE["gold"],outline=PALETTE["cream"],width=3)
            text(d,(x,my),"$",font(FONT_LATIN_BOLD,r),PALETTE["cream"])
    elif beat == 1:
        bx=mx-int(width*.06); by=my+int(height*.04)
        for k,hv in enumerate((.06,.11,.17)):
            x=bx+k*int(width*.045)
            d.rounded_rectangle((x,by-int(height*hv),x+int(width*.026),by),radius=8,fill=PALETTE["green"] if k<2 else PALETTE["gold"])
        d.line((bx-int(width*.01),by-int(height*.20),mx+int(width*.10),by-int(height*.20)),fill=PALETTE["gold"],width=4)
    else:
        d.arc((mx-int(width*.07),my-int(height*.07),mx+int(width*.07),my+int(height*.07)),190,510,fill=PALETTE["green"],width=8)
        d.polygon([(mx+int(width*.065),my-int(height*.045)),(mx+int(width*.095),my-int(height*.04)),(mx+int(width*.08),my-int(height*.01))],fill=PALETTE["green"])
    bar_y=int(height*.94); bar_l=int(width*.12); bar_r=int(width*.88)
    d.rounded_rectangle((bar_l,bar_y,bar_r,bar_y+max(6,height//260)),radius=8,fill=(115,87,62))
    d.rounded_rectangle((bar_l,bar_y,bar_l+int((bar_r-bar_l)*(index+1)/total),bar_y+max(6,height//260)),radius=8,fill=PALETTE["gold"])
    im.save(path,quality=95)

def run(cmd):
    subprocess.run(cmd,check=True,capture_output=True,text=True)

def render(plan_path, output, cache):
    plan=json.loads(Path(plan_path).read_text(encoding="utf-8"))
    if plan.get("audio",{}).get("enabled") is not False:
        raise ValueError("BookFlow is silent-only; audio must be disabled")
    if plan.get("video_type")=="long":
        w,h=1920,1080
    else:
        w,h=1080,1920
    ffmpeg,ffprobe=shutil.which("ffmpeg"),shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("FFmpeg and FFprobe are required")
    output,cache=Path(output),Path(cache)
    cache.mkdir(parents=True,exist_ok=True)
    manifest_path=cache/"manifest.json"
    try:
        manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError):
        manifest={}
    if not isinstance(manifest.get("scenes"),dict):
        manifest["scenes"]={}
    manifest.update({"renderer":"bookflow-kinetic-book-v1","silent":True,"status":"rendering"})
    segments=[]
    for i,scene in enumerate(plan["scenes"]):
        duration=float(scene["duration_seconds"])
        phase_duration=duration/3
        scene_id=scene.get("id",f"scene-{i+1}")
        scene_fp=hashlib.sha256(json.dumps({"scene":scene,"size":[w,h]},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        scene_state=manifest["scenes"].setdefault(scene_id,{"fingerprint":scene_fp,"beats":{}})
        if scene_state.get("fingerprint") != scene_fp:
            scene_state.update({"fingerprint":scene_fp,"beats":{}})
        for beat in range(3):
            frame=cache/f"scene-{i:03d}-beat-{beat}.png"
            clip=cache/f"scene-{i:03d}-beat-{beat}.mp4"
            beat_fp=hashlib.sha256(f"{scene_fp}:{beat}:{phase_duration:.5f}".encode()).hexdigest()
            prior=scene_state["beats"].get(str(beat),{})
            reusable=False
            if prior.get("fingerprint")==beat_fp and prior.get("status")=="complete" and clip.is_file():
                probe=subprocess.run([ffprobe,"-v","error","-show_entries","format=duration:stream=codec_type,width,height","-of","json",str(clip)],capture_output=True,text=True)
                if probe.returncode==0:
                    meta=json.loads(probe.stdout)
                    vs=next((x for x in meta.get("streams",[]) if x.get("codec_type")=="video"),None)
                    actual=float(meta.get("format",{}).get("duration",0))
                    reusable=bool(vs and (int(vs.get("width",0)),int(vs.get("height",0)))==(w,h) and abs(actual-phase_duration)<.5 and not any(x.get("codec_type")=="audio" for x in meta.get("streams",[])))
            if not reusable:
                make_frame(scene,i,len(plan["scenes"]),beat,w,h,frame)
                vf=f"zoompan=z='min(zoom+0.00035,1.035)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps=24,fade=t=in:st=0:d=0.12,format=yuv420p"
                try:
                    run([ffmpeg,"-y","-loop","1","-i",str(frame),"-t",f"{phase_duration:.3f}","-vf",vf,"-an","-c:v","libx264","-preset","ultrafast","-crf","25","-pix_fmt","yuv420p",str(clip)])
                    probe=subprocess.run([ffprobe,"-v","error","-show_entries","format=duration:stream=codec_type,width,height","-of","json",str(clip)],check=True,capture_output=True,text=True)
                    meta=json.loads(probe.stdout)
                    vs=next((x for x in meta.get("streams",[]) if x.get("codec_type")=="video"),None)
                    actual=float(meta.get("format",{}).get("duration",0))
                    if not vs or (int(vs.get("width",0)),int(vs.get("height",0)))!=(w,h) or abs(actual-phase_duration)>.5 or any(x.get("codec_type")=="audio" for x in meta.get("streams",[])):
                        raise RuntimeError(f"Beat {beat+1} of scene {scene_id} failed QA")
                    scene_state["beats"][str(beat)]={"fingerprint":beat_fp,"status":"complete","duration":actual,"file":clip.name}
                    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
                except Exception:
                    scene_state["beats"][str(beat)]={"fingerprint":beat_fp,"status":"failed"}
                    manifest["status"]="partial_failed"
                    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
                    raise
            segments.append(clip)
    concat=cache/"concat.txt"
    concat.write_text("\n".join("file '"+str(p.resolve())+"'" for p in segments)+"\n",encoding="utf-8")
    output.parent.mkdir(parents=True,exist_ok=True)
    run([ffmpeg,"-y","-f","concat","-safe","0","-i",str(concat),"-an","-c:v","libx264","-preset","fast","-crf","22","-pix_fmt","yuv420p","-movflags","+faststart",str(output)])
    probe=subprocess.run([ffprobe,"-v","error","-show_entries","format=duration:stream=codec_type,width,height","-of","json",str(output)],check=True,capture_output=True,text=True)
    meta=json.loads(probe.stdout); streams=meta.get("streams",[])
    if any(s.get("codec_type")=="audio" for s in streams):
        raise RuntimeError("Unexpected audio stream in silent BookFlow output")
    video=next((s for s in streams if s.get("codec_type")=="video"),None)
    if not video or (int(video.get("width",0)),int(video.get("height",0)))!=(w,h):
        raise RuntimeError("Output resolution mismatch")
    actual=float(meta.get("format",{}).get("duration",0))
    if abs(actual-float(plan["duration_seconds"]))>2.5:
        raise RuntimeError(f"Duration mismatch: {actual}")
    manifest.update({"output":str(output),"duration_seconds":actual,"resolution":f"{w}x{h}","audio_stream":False,"status":"complete"})
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"[BOOKFLOW_RENDER_OK] {output} duration={actual:.2f}s resolution={w}x{h} silent=true scenes={len(plan['scenes'])} beats=3")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("plan")
    parser.add_argument("--output",default="output/bookflow-preview.mp4")
    parser.add_argument("--cache",default="output/bookflow-cache")
    args=parser.parse_args()
    render(args.plan,args.output,args.cache)
