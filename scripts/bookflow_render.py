#!/usr/bin/env python3
"""Render a silent, animated BookFlow plan with resumable scene-beat clips."""
from __future__ import annotations
import argparse, hashlib, json, math, os, shutil, subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

PALETTE = {
    "wood": (55, 36, 27), "paper2": (234, 219, 191), "ink": (31, 42, 43),
    "muted": (102, 91, 73), "gold": (190, 145, 69), "green": (60, 104, 84),
    "cream": (255, 249, 236), "highlight": (239, 205, 112), "shadow": (22, 15, 12)
}
def resolve_font(pattern, candidates):
    """Resolve fonts across Ubuntu runner image revisions without hard-coded paths."""
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    # Ubuntu runner images do not always include fontconfig's fc-match binary.
    # Search installed font directories as a portable fallback.
    for root in (Path("/usr/share/fonts"), Path("/usr/local/share/fonts")):
        if root.is_dir():
            for candidate in root.rglob(Path(candidates[0]).name):
                if candidate.is_file():
                    return str(candidate)
    raise RuntimeError(f"Required font not found: {pattern}")

FONT_AR_BOLD = resolve_font(
    "DejaVu Sans:style=Bold",
    [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    ],
)
FONT_LATIN = resolve_font(
    "DejaVu Sans",
    [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu-sans-fonts/DejaVuSans.ttf",
    ],
)
FONT_LATIN_BOLD = FONT_AR_BOLD

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


def motif_kind(cues):
    """Map each scene's own words to a recognizable editorial illustration."""
    if any(k in cues for k in ("hospital", "medical", "clinic")):
        return "hospital"
    if any(k in cues for k in ("library", "book donation", "bookshelf")):
        return "library"
    if any(k in cues for k in ("foreclosure", "seized", "repossession")):
        return "foreclosure"
    if any(k in cues for k in ("gas pump", "gas-station", "janitor", "mop", "worker", "attendant")):
        return "worker"
    if any(k in cues for k in ("mansion", "executive", "office tower", "finance executive", "luxury home")):
        return "executive"
    if any(k in cues for k in ("calendar", "decades", "monthly", "coins accumulate", "savings jar", "patience")):
        return "time"
    if any(k in cues for k in ("chart", "curve", "market", "growth", "investment", "compound")):
        return "growth"
    if any(k in cues for k in ("ledger", "income", "spending", "remaining balance", "budget", "choices")):
        return "ledger"
    return "book"

def draw_scene_motif(draw, cues, width, height, mode, beat):
    """Add a scene-specific illustrated prop so the visual follows the narration."""
    kind = motif_kind(cues)
    unit = min(width, height)
    gold, cream = PALETTE["gold"], PALETTE["cream"]
    green, ink = PALETTE["green"], PALETTE["ink"]
    if mode == 0:
        cx, cy = int(width*.28), int(height*.43)
    elif mode == 1:
        left_side = any(k in cues for k in ("worker", "janitor", "attendant", "gas pump"))
        cx, cy = (int(width*.25) if left_side else int(width*.75)), int(height*.39)
    elif mode == 2:
        cx, cy = int(width*.50), int(height*.25)
    elif mode == 3:
        cx, cy = int(width*.78), int(height*.35)
    elif mode == 4:
        cx, cy = int(width*.88), int(height*.18)
    else:
        cx, cy = int(width*.78), int(height*.23)

    r = int(unit*.105)
    # A warm illuminated medallion anchors the illustration without becoming a card.
    draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill=(72, 53, 38), outline=gold, width=max(3, unit//260))
    lw = max(4, unit//115)
    def line(points, fill=cream, width=lw):
        draw.line(points, fill=fill, width=width, joint="curve")
    def rect(box, fill=None, outline=cream, radius=8, width=lw):
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)
    def circle(x, y, radius, fill=None, outline=cream, width=lw):
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=fill, outline=outline, width=width)

    if kind == "worker":
        # Work jacket, head and mop: a human-scale visual for the opening story.
        circle(cx, cy-int(r*.42), int(r*.19), fill=gold, outline=gold)
        draw.polygon([(cx-int(r*.43),cy+int(r*.53)),(cx-int(r*.29),cy-int(r*.08)),
                      (cx+int(r*.29),cy-int(r*.08)),(cx+int(r*.43),cy+int(r*.53))],
                     fill=green, outline=cream)
        line([(cx+int(r*.55),cy-int(r*.50)),(cx+int(r*.83),cy+int(r*.67))], gold, max(5,lw))
        line([(cx+int(r*.68),cy+int(r*.57)),(cx+int(r*.93),cy+int(r*.75))], cream, max(4,lw))
    elif kind == "executive":
        # Office tower and pitched roof suggest status and an expensive property.
        rect((cx-int(r*.62),cy-int(r*.30),cx-int(r*.05),cy+int(r*.68)), fill=(54,75,69))
        for row in range(3):
            for col in range(2):
                x=cx-int(r*.48)+col*int(r*.22); y=cy-int(r*.14)+row*int(r*.23)
                draw.rectangle((x,y,x+int(r*.09),y+int(r*.10)),fill=gold)
        draw.polygon([(cx-int(r*.02),cy+int(r*.02)),(cx+int(r*.40),cy-int(r*.40)),
                      (cx+int(r*.82),cy+int(r*.02))],fill=gold,outline=cream)
        rect((cx+int(r*.12),cy+int(r*.02),cx+int(r*.68),cy+int(r*.66)),fill=(90,66,48))
        line([(cx+int(r*.40),cy+int(r*.28)),(cx+int(r*.40),cy+int(r*.66))],cream)
    elif kind in ("hospital", "library"):
        rect((cx-int(r*.62),cy-int(r*.30),cx+int(r*.62),cy+int(r*.58)),fill=(65,82,70))
        draw.polygon([(cx-int(r*.72),cy-int(r*.30)),(cx,cy-int(r*.78)),
                      (cx+int(r*.72),cy-int(r*.30))],fill=gold,outline=cream)
        for off in (-.38,0,.38):
            rect((cx+int(r*off)-int(r*.10),cy+int(r*.10),cx+int(r*off)+int(r*.10),cy+int(r*.58)),fill=(234,219,191),outline=gold,width=2)
        if kind == "hospital":
            line([(cx,cy-int(r*.20)),(cx,cy+int(r*.02))],cream,max(6,lw*2))
            line([(cx-int(r*.11),cy-int(r*.09)),(cx+int(r*.11),cy-int(r*.09))],cream,max(6,lw*2))
        else:
            line([(cx-int(r*.23),cy+int(r*.02)),(cx,cy+int(r*.20)),(cx+int(r*.23),cy+int(r*.02))],gold,max(5,lw))
    elif kind == "foreclosure":
        draw.polygon([(cx-int(r*.72),cy-int(r*.02)),(cx,cy-int(r*.62)),
                      (cx+int(r*.72),cy-int(r*.02))],fill=gold,outline=cream)
        rect((cx-int(r*.52),cy-int(r*.02),cx+int(r*.52),cy+int(r*.63)),fill=(78,57,43))
        rect((cx-int(r*.22),cy+int(r*.27),cx+int(r*.02),cy+int(r*.63)),fill=cream,outline=gold,width=2)
        line([(cx-int(r*.62),cy-int(r*.42)),(cx+int(r*.62),cy+int(r*.42))],(190,85,64),max(7,lw*2))
    elif kind == "time":
        rect((cx-int(r*.58),cy-int(r*.52),cx+int(r*.58),cy+int(r*.48)),fill=(234,219,191),outline=gold)
        line([(cx-int(r*.58),cy-int(r*.20)),(cx+int(r*.58),cy-int(r*.20))],green)
        for off in (-.30,0,.30):
            circle(cx+int(r*off),cy+int(r*.08),int(r*.07),fill=gold,outline=gold,width=1)
        for stack, height_n in ((-.25,2),(.15,3),(.48,1)):
            x=cx+int(r*stack)
            for n in range(height_n):
                draw.ellipse((x-int(r*.10),cy+int(r*.68)-n*int(r*.13),x+int(r*.10),cy+int(r*.78)-n*int(r*.13)),fill=gold,outline=cream,width=2)
    elif kind in ("growth", "ledger"):
        base_y=cy+int(r*.55)
        line([(cx-int(r*.68),base_y),(cx+int(r*.68),base_y)],cream)
        heights=(.25,.43,.62,.82) if kind=="growth" else (.30,.48,.35,.68)
        for i,hv in enumerate(heights):
            x=cx-int(r*.55)+i*int(r*.31)
            draw.rounded_rectangle((x,base_y-int(r*hv),x+int(r*.18),base_y),radius=5,fill=green if i<3 else gold)
        if kind == "growth":
            line([(cx-int(r*.58),cy+int(r*.10)),(cx-int(r*.20),cy-int(r*.12)),
                  (cx+int(r*.12),cy-int(r*.04)),(cx+int(r*.57),cy-int(r*.58))],gold,max(5,lw))
    else:
        # Open book: recurring series signature.
        draw.polygon([(cx-int(r*.68),cy-int(r*.38)),(cx-int(r*.05),cy-int(r*.20)),
                      (cx-int(r*.05),cy+int(r*.56)),(cx-int(r*.68),cy+int(r*.34))],
                     fill=(234,219,191),outline=gold)
        draw.polygon([(cx+int(r*.05),cy-int(r*.20)),(cx+int(r*.68),cy-int(r*.38)),
                      (cx+int(r*.68),cy+int(r*.34)),(cx+int(r*.05),cy+int(r*.56))],
                     fill=(234,219,191),outline=gold)
        line([(cx,cy-int(r*.20)),(cx,cy+int(r*.56))],green)
    # Small orbit marks shift between beats, adding movement without random clutter.
    orbit = r + int(unit*.025)
    for offset in (-1, 1):
        x = cx + offset*orbit
        y = cy + int(math.sin((beat+1)*1.2)*r*.12)
        circle(x, y, max(3,unit//180), fill=gold, outline=gold, width=1)
    return kind

def make_frame(scene, index, total, beat, width, height, path):
    """Create varied editorial compositions rather than repeating one centered card."""
    im = Image.new("RGB", (width, height), PALETTE["wood"])
    # Draw a subtle warm gradient in horizontal bands; avoid per-pixel Python loops.
    d = ImageDraw.Draw(im)
    band = max(8, height // 80)
    for y in range(0, height, band):
        t = y / max(1, height - 1)
        shade = int(8 * (1 - abs(t - .48) * 1.7))
        base = PALETTE["wood"]
        fill = tuple(min(255, channel + max(0, shade)) for channel in base)
        d.rectangle((0, y, width, min(height, y + band)), fill=fill)
    title, ar = scene["text_en"], scene["translation_ar"]
    role = str(scene.get("role", "story")).lower()
    visual = str(scene.get("visual", "")).lower()
    # Select the composition from the actual editorial direction, not scene order.
    # This keeps the visual grammar attached to the story beat when scenes are reordered.
    cues = f"{visual} {title} {role}".lower()
    if any(k in cues for k in ("split-screen", "facing", "contrast", "two ", "versus", "executive", "worker", "align")):
        mode = 1
    elif any(k in cues for k in ("calendar", "coins accumulate", "decades", "monthly", "patience", "steadily", "savings jar", "repeat")):
        mode = 2
    elif any(k in cues for k in ("chart", "blueprint", "debt", "curve", "column", "income", "market", "foreclosure", "financial")):
        mode = 3
    elif any(k in cues for k in ("soft skill", "iq", "keywords", "underlined", "question mark", "behavioral", "lesson", "three keywords")):
        mode = 4
    elif any(k in cues for k in ("ledger", "spending", "plan on", "reserve", "remaining balance", "options", "jar")):
        mode = 5
    else:
        mode = 0
    gold, cream, ink, green = PALETTE["gold"], PALETTE["cream"], PALETTE["ink"], PALETTE["green"]
    pad = int(width * .07)
    headline = font(FONT_LATIN_BOLD, int(height * (.050 if width > height else .043)))
    arabic = font(FONT_AR_BOLD, int(height * (.034 if width > height else .030)))
    small = font(FONT_LATIN_BOLD, int(height * .022))

    def page(x1, y1, x2, y2, tilt=False):
        d.rounded_rectangle((x1+12,y1+18,x2+12,y2+18), radius=24, fill=PALETTE["shadow"])
        d.rounded_rectangle((x1,y1,x2,y2), radius=22, fill=PALETTE["paper2"], outline=gold, width=3)
        d.line((x1+24,y1+35,x2-24,y1+35), fill=(197,177,145), width=2)
        d.line((x1+24,y2-35,x2-24,y2-35), fill=(197,177,145), width=2)

    def caption(x1,y1,x2,y2, title_size=None, ar_size=None):
        d.rounded_rectangle((x1,y1,x2,y2), radius=20, fill=cream, outline=gold, width=3)
        tf = font(FONT_LATIN_BOLD, title_size or headline.size)
        af = font(FONT_AR_BOLD, ar_size or arabic.size)
        draw_wrapped(d,title,((x1+x2)//2,(y1+y2)//2-int((y2-y1)*.17)),tf,ink,int((x2-x1)*.84),line_gap=int(height*.009))
        d.line((x1+int((x2-x1)*.22),(y1+y2)//2+int((y2-y1)*.02),x2-int((x2-x1)*.22),(y1+y2)//2+int((y2-y1)*.02)),fill=gold,width=max(2,width//700))
        draw_wrapped(d,ar,((x1+x2)//2,(y1+y2)//2+int((y2-y1)*.23)),af,green,int((x2-x1)*.84),line_gap=int(height*.007),rtl=True)

    # Six distinct editorial layouts; beat changes move the focal treatment.
    if mode == 0:  # cinematic open-book spread, text on the right page
        page(pad,int(height*.12),int(width*.94),int(height*.88))
        mid=width//2
        d.line((mid,int(height*.15),mid,int(height*.84)),fill=(173,145,109),width=5)
        for j in range(7):
            yy=int(height*(.25+j*.075))
            d.line((pad+35,yy,mid-28,yy),fill=(207,188,157),width=2)
        caption(mid+int(width*.035),int(height*.25),int(width*.88),int(height*.75))
        text(d,(pad+int(width*.16),int(height*.52)),"THE MONEY\nSTORY",small,gold)
    elif mode == 1:  # two-sided human/wealth comparison
        d.rectangle((0,0,width//2,height),fill=(37,57,48))
        d.rectangle((width//2,0,width,height),fill=(48,34,29))
        text(d,(width//4,int(height*.18)),"THE QUIET BUILDER",small,cream)
        text(d,(3*width//4,int(height*.18)),"THE BIG SPENDER",small,cream)
        for cx,cy,r in ((width//4,int(height*.39),int(height*.11)),(3*width//4,int(height*.39),int(height*.11))):
            d.ellipse((cx-r,cy-r,cx+r,cy+r),outline=gold,width=6)
        text(d,(width//4,int(height*.39)),"$",font(FONT_LATIN_BOLD,int(height*.12)),gold)
        text(d,(3*width//4,int(height*.39)),"!",font(FONT_LATIN_BOLD,int(height*.12)),gold)
        caption(int(width*.06),int(height*.58),int(width*.94),int(height*.91),int(height*.032),int(height*.026))
    elif mode == 2:  # timeline / compounding / patience
        page(int(width*.08),int(height*.13),int(width*.92),int(height*.87))
        y=int(height*.43); x1=int(width*.18); x2=int(width*.82)
        d.line((x1,y,x2,y),fill=green,width=max(6,height//100))
        for k in range(5):
            x=x1+int((x2-x1)*k/4); r=int(height*(.025+.009*((k+beat)%3)))
            d.ellipse((x-r,y-r,x+r,y+r),fill=gold,outline=cream,width=3)
            text(d,(x,y+int(height*.09)),str(2000+k*5),small,ink)
        caption(int(width*.13),int(height*.58),int(width*.87),int(height*.84),int(height*.030),int(height*.025))
    elif mode == 3:  # data / chart composition
        page(int(width*.08),int(height*.12),int(width*.92),int(height*.88))
        left=int(width*.19); bottom=int(height*.72); top=int(height*.29); right=int(width*.82)
        d.line((left,top,left,bottom,right,bottom),fill=ink,width=4)
        vals=(.12,.20,.18,.36,.43,.58,.55,.78,.91)
        pts=[]
        for k,v in enumerate(vals):
            pts.append((left+int((right-left)*k/(len(vals)-1)),bottom-int((bottom-top)*v)))
        d.line(pts,fill=green,width=max(7,height//90),joint="curve")
        for x,y in pts[::2]:
            r=max(5,height//100); d.ellipse((x-r,y-r,x+r,y+r),fill=gold)
        caption(int(width*.14),int(height*.70),int(width*.86),int(height*.91),int(height*.026),int(height*.022))
    elif mode == 4:  # dramatic full-frame typography with page edge
        d.rectangle((0,0,int(width*.13),height),fill=(35,57,47))
        for k in range(9):
            yy=int(height*(.08+k*.105))
            d.line((int(width*.04),yy,int(width*.10),yy),fill=gold,width=3)
        text(d,(int(width*.56),int(height*.20)),"A LESSON IN MONEY",small,gold)
        d.line((int(width*.23),int(height*.29),int(width*.88),int(height*.29)),fill=gold,width=4)
        draw_wrapped(d,title,(int(width*.56),int(height*.48)),font(FONT_LATIN_BOLD,int(height*.060)),cream,int(width*.66),line_gap=int(height*.018))
        d.line((int(width*.23),int(height*.66),int(width*.88),int(height*.66)),fill=gold,width=4)
        draw_wrapped(d,ar,(int(width*.56),int(height*.79)),font(FONT_AR_BOLD,int(height*.040)),cream,int(width*.66),line_gap=int(height*.012),rtl=True)
    else:  # desk / ledger still life
        page(int(width*.09),int(height*.12),int(width*.91),int(height*.88))
        # Ledger columns and a highlighted actionable line.
        lx=int(width*.18); rx=int(width*.82); ty=int(height*.30)
        d.rectangle((lx,ty,rx,int(height*.62)),outline=green,width=4)
        d.line((lx,int(height*.40),rx,int(height*.40)),fill=(190,170,140),width=3)
        d.line((lx,int(height*.51),rx,int(height*.51)),fill=(190,170,140),width=3)
        d.line((int(width*.52),ty,int(width*.52),int(height*.62)),fill=(190,170,140),width=3)
        d.rounded_rectangle((lx+8,int(height*.405),rx-8,int(height*.505)),radius=8,fill=(239,205,112))
        text(d,(int(width*.35),int(height*.355)),"INCOME",small,ink)
        text(d,(int(width*.68),int(height*.355)),"CHOICES",small,ink)
        text(d,(int(width*.35),int(height*.455)),"SAVE",small,green)
        text(d,(int(width*.68),int(height*.455)),"SPEND",small,ink)
        caption(int(width*.14),int(height*.66),int(width*.86),int(height*.89),int(height*.027),int(height*.023))

    motif_kind(cues)
    draw_scene_motif(d, cues, width, height, mode, beat)

    # A restrained scene progress marker; beat changes the moving highlight.
    bar_y=int(height*.955); bar_l=int(width*.12); bar_r=int(width*.88)
    d.rounded_rectangle((bar_l,bar_y,bar_r,bar_y+max(6,height//260)),radius=8,fill=(115,87,62))
    progress=(index + (beat+1)/3)/max(1,total)
    d.rounded_rectangle((bar_l,bar_y,bar_l+int((bar_r-bar_l)*progress),bar_y+max(6,height//260)),radius=8,fill=gold)
    im.save(path,quality=95)

def run(cmd):
    subprocess.run(cmd,check=True,capture_output=True,text=True)

def beats_for_duration(seconds):
    if float(seconds) <= 0:
        raise ValueError("Scene duration must be positive")
    return max(2, math.ceil(float(seconds) / 3.0))

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
        beat_count=beats_for_duration(duration)
        phase_duration=duration/beat_count
        scene_id=scene.get("id",f"scene-{i+1}")
        scene_fp=hashlib.sha256(json.dumps({"scene":scene,"size":[w,h]},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        scene_state=manifest["scenes"].setdefault(scene_id,{"fingerprint":scene_fp,"beats":{}})
        if scene_state.get("fingerprint") != scene_fp:
            scene_state.update({"fingerprint":scene_fp,"beats":{}})
        scene_state["beat_count"]=beat_count
        for beat in range(beat_count):
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
                make_frame(scene,i,len(plan["scenes"]),beat % 3,w,h,frame)
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
