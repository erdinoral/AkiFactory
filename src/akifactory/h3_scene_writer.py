"""MiniMax H3 sahne yazari — resmi uc alanli prompt + ortak gorsel kimlik.

LLM yalnizca sahne plani (JSON) yazar; resmi H3 promptunu
(integrated_multimodal_description / overall_soundscape / non_diegetic_music)
kod kurar. Gorsel kimlik (stil, palet, isik, donem, tekrar eden ozneler)
her sahneye birebir ayni girer — zincir boyunca tutarlilik buradan gelir.
"""

from __future__ import annotations

import json
import re
from typing import Any

from akifactory.ollama_util import chat as llm_chat

CLIP_SECONDS = 5
# Uzun continue zinciri son karede kayma biriktirir; mekan degisince temiz kesme
MAX_CONTINUE_STREAK = 3

NICHE_VISUAL: dict[str, str] = {
    "tarih_gizem": "the topic's named figures, gods, artifacts and sites in their era, torch or natural light, documentary mystery",
    "tarihi_insanlar": "period-accurate people, courts, workshops, portraits of the era",
    "tarihi_olaylar": "historical reconstruction, crowds at distance, monuments, archival documentary",
    "savaslar": "battlefields, soldiers at distance, smoke, fortifications, maps on tables",
    "teknoloji": "modern labs, devices, clean industrial spaces, macro hardware detail",
    "uzay": "planets, spacecraft, observatories, starfields, realistic space imagery",
    "yeme_icme": "food macro, steam, kitchens, ingredients, warm practical light",
    "cocuk_eglence": "bright friendly nature, gentle animals, soft daylight, playful but safe",
    "seyahat": "landmarks, streets, landscapes, aerial views, golden hour",
    "genel": "realistic environments with a clear subject",
}

_PERIOD_NICHES = {"tarih_gizem", "tarihi_insanlar", "tarihi_olaylar", "savaslar"}

STYLE_LOOK: dict[str, str] = {
    "dark_mystery": "Live-action, cinematic documentary, photoreal, low-key natural light, subtle film grain",
    "cinematic": "Live-action, cinematic documentary, photoreal, natural contrast, subtle film grain",
    "epic_history": "Live-action, cinematic period documentary, photoreal, epic scale, subtle film grain",
    "atmospheric": "Live-action, cinematic documentary, photoreal, volumetric light, subtle film grain",
}

CAMERA_MOVES: dict[str, str] = {
    "static": "holds a static shot",
    "push in": "pushes in",
    "pull out": "pulls out",
    "zoom in": "zooms in",
    "zoom out": "zooms out",
    "pan left": "pans left",
    "pan right": "pans right",
    "truck left": "trucks left",
    "truck right": "trucks right",
    "tilt up": "tilts up",
    "tilt down": "tilts down",
    "pedestal up": "pedestals up",
    "pedestal down": "pedestals down",
    "arc": "arcs around the subject",
    "tracking": "tracks the moving subject",
}
_MOVE_ROTATION = ("push in", "truck right", "tilt up", "arc", "pull out", "pan left", "pedestal down")

_BIBLE_KEYS = ("style", "palette", "lighting", "era_and_setting", "recurring_subjects")
_CLIP_KEYS = (
    "shot_type", "hero", "location", "subjects", "framing", "opening_frame", "action",
    "camera_move", "camera_amplitude", "camera_speed", "camera_target", "ending_frame",
)


def split_narration(script: str, n: int) -> list[str]:
    """Senaryoyu n esit sureli parcaya bol (kelime sayisina gore)."""
    words = (script or "").split()
    if n <= 0:
        return []
    if not words:
        return [""] * n
    out: list[str] = []
    for i in range(n):
        a = round(i * len(words) / n)
        b = round((i + 1) * len(words) / n)
        out.append(" ".join(words[a:b]))
    return out


def _clean(text: Any, limit: int = 700) -> str:
    s = " ".join(str(text or "").split()).strip()
    return s[:limit].rstrip(" ,;")


def _sentence(text: str) -> str:
    t = text.strip()
    if not t:
        return ""
    return t if t.endswith((".", "!", "?")) else t + "."


def _build_request(
    *,
    topic: str,
    niche_id: str,
    style: str,
    aspect: str,
    chunks: list[str],
    continue_mode: bool,
    clip_seconds: int = CLIP_SECONDS,
) -> str:
    n = len(chunks)
    cs = max(1, int(clip_seconds))
    blocks = max(1, round(n / 2.5))
    frame = "9:16 portrait" if aspect == "9:16" else "16:9 widescreen"
    niche = NICHE_VISUAL.get(niche_id, NICHE_VISUAL["genel"])
    look = STYLE_LOOK.get(style, STYLE_LOOK["cinematic"])
    timeline = "\n".join(
        f"Clip {i + 1} ({i * cs}-{(i + 1) * cs}s): {c or '(no narration)'}"
        for i, c in enumerate(chunks)
    )
    if continue_mode:
        chain = (
            'Each clip has a shot_type. "new" = a clean cut to a fresh shot. "continue" = the clip '
            "starts on the exact last frame of the previous clip, so it must stay in the same "
            "location with the same subjects and progress only through camera movement and small "
            "physical actions.\n"
            f"Plan the video as about {blocks} location blocks. Each block = one \"new\" clip "
            f"followed by 1-{min(2, MAX_CONTINUE_STREAK)} \"continue\" clips in the same location. "
            "Inside a block, keep the same hero and show the changing narration through camera "
            "progression and detail reveals on it (from the statue's feet to its face, from the "
            "priest to the offering in his hands). Start a new block "
            "only when the narration clearly moves to another place or time. Clip 1 is \"new\"."
        )
    else:
        chain = (
            "Every clip is an independent new shot. Locations may change, but the visual bible "
            "(style, palette, lighting, era, recurring subjects) stays identical in every clip."
        )
    period = (
        "- Historical accuracy: period-correct architecture, clothing, tools and materials; no modern objects.\n"
        if niche_id in _PERIOD_NICHES
        else ""
    )
    return f"""You are a documentary cinematographer planning shots for the MiniMax H3 text-to-video model.

Topic: {topic[:300]}
Visual niche: {niche}
Base look: {look}
Frame: {frame}
Video: {n} clips, each exactly {cs} seconds, total {n * cs} seconds.
{chain}

Narration heard during each clip (Turkish). Show what is being said visually; never write the words on screen:
{timeline}

First decide what this topic must show. A viewer who reads the topic title expects to see its
specific, recognizable subjects: the named gods, people, creatures, objects, places or events it is
about (for example "Gods of Egypt" means Anubis, Horus, Ra, Osiris and Isis with their canonical
iconography, as colossal statues, painted reliefs or living mythic figures). List them in key_subjects.

Return ONLY a JSON object:
{{
  "key_subjects": [
    {{"name": "real name of the subject", "look": "canonical, exact visual appearance: shape, material, colors, attributes, scale"}}
  ],
  "visual_bible": {{
    "style": "one line, starts with the base look",
    "palette": "dominant colors",
    "lighting": "light source, direction, time of day",
    "era_and_setting": "period and place",
    "recurring_subjects": "exact appearance of every person or object that appears in more than one clip (age, clothing, material, color), or 'none'"
  }},
  "clips": [
    {{
      "index": 1,
      "shot_type": "new | continue",
      "hero": "the name of the key_subject that is the visual focus of this clip",
      "location": "concrete place with materials and depth",
      "subjects": "who or what is visible, with appearance; the hero first",
      "framing": "shot size and angle only, e.g. low-angle wide shot; never the words vertical, horizontal, portrait or landscape",
      "opening_frame": "composition at 0.00s",
      "action": "3-5 short chronological physical beats that fit in {cs} seconds, as plain sentences (no numbering)",
      "camera_move": "one of: {', '.join(CAMERA_MOVES)}",
      "camera_amplitude": "small | medium | large",
      "camera_speed": "slow | normal | fast",
      "camera_target": "what the camera moves toward or reveals",
      "ending_frame": "composition at {cs}.00s"
    }}
  ]
}}

Rules:
- Exactly {n} clips, index 1 to {n}. English only in every field.
- key_subjects: 4-8 entries, the most iconic and specific subjects of the topic, with real names. A look never contains readable words or letters (describe carvings as knife-cut marks or symbols).
- The topic must be on screen. Every clip has a hero from key_subjects, large and clearly recognizable (at least a third of the frame). At most one clip may be an establishing shot without a hero.
- Never fill a clip with empty architecture, columns, closed doors, boxes, dust or landscapes alone.
- When the narration is general or abstract, illustrate it with a key_subject (a ritual in front of a god's statue, a pharaoh making an offering) instead of an empty place.
- Spread the key_subjects across the video; the same hero appears in at most 3 clips.
- Every detail must be visible: materials, textures, light, motion. No abstract mood words, no plot summary.
- Each clip shows the narration of its own time slot.
- If a person appears in more than one clip, describe them once in recurring_subjects and reuse that exact appearance.
- No on-screen text, letters, inscriptions to read, captions, logos or maps with labels.
- No dialogue, no music.
- Do not use the same camera_move in two consecutive clips.
- In continue clips, location stays the same and opening_frame matches the previous clip's ending_frame.
{period}"""


def _parse_json(text: str) -> dict[str, Any] | None:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I)
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        data = json.loads(t[a : b + 1])
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _normalize_bible(raw: Any, style: str) -> dict[str, str]:
    src = raw if isinstance(raw, dict) else {}
    bible = {k: _clean(src.get(k), 300) for k in _BIBLE_KEYS}
    look = STYLE_LOOK.get(style, STYLE_LOOK["cinematic"])
    bible["style"] = _ASPECT_RE.sub("", bible["style"])
    bible["style"] = re.sub(r",?\s*\baspect(\s+ratio)?\b", "", bible["style"], flags=re.I).strip(" ,;")
    if not bible["style"].lower().startswith(("live-action", "live action")):
        bible["style"] = look
    if bible["recurring_subjects"].lower() in ("", "none", "n/a", "-"):
        bible["recurring_subjects"] = ""
    return bible


_ASPECT_RE = re.compile(r",?\s*\b(9:16|16:9)\b(\s+(vertical|widescreen|portrait|horizontal))?(\s+frame)?", re.I)
# "exactly matching the ending frame of clip 9" — video modeli klip numarasini bilmez
_CLIP_REF_RE = re.compile(
    r",?\s*\(?\s*(exactly\s+)?(matching|matches|same as|identical to|continuing from)\s+"
    r"(the\s+)?(ending|end|final|last)\s+frame\s+of\s+(the\s+)?(previous\s+)?clip(\s*\d+)?\s*\)?",
    re.I,
)
# "Continuation from clip 1 ending, showing ..."
_CLIP_LEAD_RE = re.compile(
    r"^\s*(a\s+)?continu\w*\s+(from|of)\s+(the\s+)?(previous\s+)?clip(\s*\d+)?('s)?(\s+(ending|end|final frame))?[,:;]?\s*(showing\s+)?",
    re.I,
)


def _normalize_clip(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    clip = {
        k: _CLIP_LEAD_RE.sub("", _CLIP_REF_RE.sub("", _clean(raw.get(k)))).strip(" ,;")
        for k in _CLIP_KEYS
    }
    if clip["opening_frame"]:
        clip["opening_frame"] = clip["opening_frame"][0].upper() + clip["opening_frame"][1:]
    # "medium vertical shot" H3'te goruntuyu 90 derece yatirabiliyor; yon parametreden gelir
    clip["framing"] = re.sub(
        r"\s*\b(vertical|horizontal|portrait|landscape)\b", "", clip["framing"], flags=re.I
    ).strip(" ,;")
    clip["action"] = re.sub(r"(?:^|(?<=\s))\d+[.)]\s+", "", clip["action"]).strip()
    if not clip["location"] or not clip["action"]:
        return None
    move = clip["camera_move"].lower().replace("-", " ").strip()
    clip["camera_move"] = move if move in CAMERA_MOVES else ""
    for key, allowed in (("camera_amplitude", ("small", "large")), ("camera_speed", ("slow", "fast"))):
        v = clip[key].lower()
        clip[key] = v if v in allowed else ""
    clip["camera_target"] = re.sub(
        r"^(A|An|The)\b", lambda m: m.group(1).lower(), clip["camera_target"]
    )
    return clip


def _normalize_key_subjects(raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name, look = _clean(item.get("name"), 80), _clean(item.get("look"), 300)
        if name and look:
            out.append({"name": name, "look": look})
    return out[:8]


def _hero_look(hero: str, subjects: list[dict[str, str]]) -> str:
    """Klibin hero adini key_subjects'teki kanonik gorunusle eslestir."""
    h = hero.lower().strip()
    if not h:
        return ""
    for s in subjects:
        n = s["name"].lower()
        if n == h or n in h or h in n:
            return f"{s['name']}, {s['look']}"
    return ""


def _same_place(a: str, b: str) -> bool:
    from difflib import SequenceMatcher

    na, nb = a.lower().strip(), b.lower().strip()
    if not na or not nb:
        return False
    wa = {w for w in re.findall(r"[a-z]{4,}", na)}
    wb = {w for w in re.findall(r"[a-z]{4,}", nb)}
    overlap = len(wa & wb) / max(1, min(len(wa), len(wb)))
    return overlap >= 0.5 or SequenceMatcher(None, na, nb).ratio() >= 0.6


def decide_modes(clips: list[dict[str, str]], *, continue_mode: bool) -> list[str]:
    """1. klip yeni; continue yalnizca ayni mekanda ve en fazla MAX_CONTINUE_STREAK art arda."""
    modes: list[str] = []
    streak = 0
    for i, c in enumerate(clips):
        want = continue_mode and i > 0 and c.get("shot_type", "").lower().startswith("cont")
        if want and _same_place(c["location"], clips[i - 1]["location"]) and streak < MAX_CONTINUE_STREAK:
            modes.append("continue")
            streak += 1
        else:
            modes.append("t2v")
            streak = 0
    return modes


def _fix_camera_repeats(clips: list[dict[str, str]]) -> None:
    prev = ""
    for i, c in enumerate(clips):
        if not c["camera_move"] or c["camera_move"] == prev:
            c["camera_move"] = next(
                m for m in (_MOVE_ROTATION[(i + k) % len(_MOVE_ROTATION)] for k in range(len(_MOVE_ROTATION)))
                if m != prev
            )
        prev = c["camera_move"]


def compose_scene_prompt(
    clip: dict[str, str],
    bible: dict[str, str],
    *,
    is_continuation: bool,
    aspect: str = "9:16",
    period: bool = False,
) -> str:
    """Sahne plani + gorsel kimlik → resmi H3 uc alanli prompt."""
    lock_bits = [bible.get("palette"), bible.get("lighting"), bible.get("era_and_setting")]
    lock = "; ".join(b for b in lock_bits if b)
    parts = [f"[Shot 1] {_sentence(bible['style'])}"]
    if lock:
        parts.append(f"Visual production lock: {_sentence(lock)}")
    if bible.get("recurring_subjects"):
        parts.append(
            "Appearance lock, applies only to subjects visible in this shot: "
            f"{_sentence(bible['recurring_subjects'])}"
        )
    if is_continuation:
        parts.append(
            "The shot opens exactly on the final frame of the previous clip and continues it without "
            "restarting: same place, same subjects, same lighting and camera position."
        )
    if clip.get("hero_look"):
        name = clip["hero_look"].split(",", 1)[0]
        # Kisi zaten appearance lock'ta tarif edildiyse ikinci kez yazma
        shown = name if name.lower() in bible.get("recurring_subjects", "").lower() else clip["hero_look"]
        parts.append(f"Main subject, large and clearly recognizable: {_sentence(shown)}")
    parts.append(f"Location: {_sentence(clip['location'])}")
    if clip["subjects"]:
        parts.append(f"Visible subjects: {_sentence(clip['subjects'])}")
    parts.append(f"Framing: {_sentence(clip['framing'] or 'medium-wide shot at eye level')}")
    if clip["opening_frame"]:
        parts.append(f"Opening composition: {_sentence(clip['opening_frame'])}")
    parts.append(_sentence(clip["action"]))
    motion = f"The camera {CAMERA_MOVES.get(clip['camera_move'], 'pushes in')}"
    if clip["camera_amplitude"]:
        motion += f" with {clip['camera_amplitude']} amplitude"
    if clip["camera_speed"]:
        motion += f" at {clip['camera_speed']} speed"
    if clip["camera_target"] and clip["camera_move"] not in ("static", "arc", "tracking"):
        motion += f" toward {clip['camera_target']}"
    parts.append(_sentence(motion))
    if clip["ending_frame"]:
        parts.append(f"End composition: {_sentence(clip['ending_frame'])}")
    constraints = (
        "Constraints: one continuous shot, no cuts, no on-screen text, letters or logos, "
        "no dialogue, no generated music, no sound effects"
    )
    if period:
        constraints += ", period-accurate details, no modern objects"
    parts.append(constraints + ".")
    body = " ".join(p for p in parts if p)
    return (
        f"integrated_multimodal_description: {body}\n\n"
        "overall_soundscape: N/A\n\n"
        "non_diegetic_music: N/A"
    )


async def _ask(prompt: str) -> dict[str, Any] | None:
    content = await llm_chat(
        [{"role": "user", "content": prompt}],
        think=False,
        timeout=240.0,
        clean_script=False,
        format_json=True,
        options={"temperature": 0.7, "num_predict": 8192, "max_tokens": 8192},
    )
    return _parse_json(content or "")


async def _fill_missing(
    *,
    base_prompt: str,
    bible: dict[str, str],
    have: dict[int, dict[str, str]],
    missing: list[int],
) -> None:
    known = {str(i): have[i] for i in sorted(have)}
    prompt = (
        f"{base_prompt}\n\nThe visual bible is fixed:\n{json.dumps(bible, ensure_ascii=False)}\n"
        f"Clips already written:\n{json.dumps(known, ensure_ascii=False)[:6000]}\n\n"
        f"Write ONLY the missing clips {missing} with the same JSON clip fields. "
        'Return {"clips": [...]}.'
    )
    data = await _ask(prompt)
    for raw in (data or {}).get("clips") or []:
        idx = raw.get("index") if isinstance(raw, dict) else None
        clip = _normalize_clip(raw)
        if clip and isinstance(idx, int) and idx in missing:
            have[idx] = clip


def _carry_forward(prev: dict[str, str]) -> dict[str, str]:
    """Son care: onceki sahnenin dunyasinda kalan, kamerayla ilerleyen sahne."""
    return {
        **prev,
        "shot_type": "continue",
        "opening_frame": prev.get("ending_frame") or prev.get("opening_frame") or "",
        "action": (
            "Dust drifts slowly through the light while the camera reveals further details "
            f"of {prev['location']}, keeping every surface and material unchanged"
        ),
        "camera_move": "",
        "camera_target": "deeper parts of the same space",
        "ending_frame": "",
    }


async def write_scenes(
    *,
    topic: str,
    script: str,
    niche_id: str = "tarih_gizem",
    style: str = "dark_mystery",
    scene_count: int = 10,
    aspect: str = "9:16",
    continue_mode: bool = True,
    clip_seconds: int = CLIP_SECONDS,
) -> dict[str, Any] | None:
    """N sahne icin resmi H3 promptlari. LLM basarisizsa None (cagiran eski yola duser)."""
    n = max(1, int(scene_count))
    chunks = split_narration(script or topic, n)
    base_prompt = _build_request(
        topic=topic, niche_id=niche_id, style=style, aspect=aspect,
        chunks=chunks, continue_mode=continue_mode, clip_seconds=clip_seconds,
    )
    data = await _ask(base_prompt)
    if not data:
        data = await _ask(base_prompt)
    if not data:
        return None
    bible = _normalize_bible(data.get("visual_bible"), style)
    have: dict[int, dict[str, str]] = {}
    for pos, raw in enumerate(data.get("clips") or [], start=1):
        clip = _normalize_clip(raw)
        idx = raw.get("index") if isinstance(raw, dict) else None
        idx = idx if isinstance(idx, int) and 1 <= idx <= n else pos
        if clip and idx <= n and idx not in have:
            have[idx] = clip
    if not have:
        return None
    missing = [i for i in range(1, n + 1) if i not in have]
    if missing:
        await _fill_missing(base_prompt=base_prompt, bible=bible, have=have, missing=missing)
    clips: list[dict[str, str]] = []
    for i in range(1, n + 1):
        if i in have:
            clips.append(have[i])
        else:
            clips.append(_carry_forward(clips[-1] if clips else have[min(have)]))
    _fix_camera_repeats(clips)
    key_subjects = _normalize_key_subjects(data.get("key_subjects"))
    for c in clips:
        c["hero_look"] = _hero_look(c.get("hero", ""), key_subjects)
    period = niche_id in _PERIOD_NICHES
    modes = decide_modes(clips, continue_mode=continue_mode)
    prompts = [
        compose_scene_prompt(c, bible, is_continuation=(modes[i] == "continue"), aspect=aspect, period=period)
        for i, c in enumerate(clips)
    ]
    return {
        "scenes": prompts,
        "modes": modes,
        "visual_bible": bible,
        "key_subjects": key_subjects,
        "clips": clips,
        "narration": chunks,
        "filled": missing,
    }
