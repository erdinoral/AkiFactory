"""H3 Studio icin sinematik SCENE / h3Prompt uretimi (Ollama).

Kurallar: Pinokio minimax-h3-pinokio «H3 Yonetmen» GOLD STANDARD —
keyword soup degil; continuous-shot sahne senaryosu (Ingilizce).
"""

from __future__ import annotations

import random
import re
from typing import Any

from akifactory.ollama_util import chat as ollama_chat
from akifactory.ollama_util import creative_chat_options

STYLE_LABELS = {
    "dark_mystery": "Karanlik gizem / belgesel (found footage / observational)",
    "cinematic": "Sinematik belgesel (photoreal live-action)",
    "epic_history": "Epik tarih (photoreal period mood)",
    "atmospheric": "Atmosferik / duman-isik",
}

LINE_MODE_LABELS = {
    "sliding_window": "Continue zinciri (shot1 acilis, sonraki Continue…)",
    "queue": "Her sahne bagimsiz (standalone)",
    "single": "Tek uzun SCENE",
}

BATCH_FOCUS: list[tuple[str, str]] = [
    (
        "Tur 1 — Acilis / dunyayi kur",
        "World-open establishing: location, weather, light, main prop; observational documentary camera",
    ),
    (
        "Tur 2 — Detay / yakin beat",
        "Macro / close beats: textures, artifacts, hands, micro-actions; push-in or static hold",
    ),
    (
        "Tur 3 — Atmosfer / gecis",
        "Atmosphere pulse: fog, dust rays, empty corridors, transitional B-roll energy",
    ),
    (
        "Tur 4 — Hareket / dinamik",
        "Dynamic camera: slow track, walking POV, living documentary motion",
    ),
]

NICHE_VISUAL: dict[str, str] = {
    "tarih_gizem": "Ancient ruins, dim torchlight, dusty archives, mysterious artifacts, fog, candlelight, documentary mystery mood",
    "teknoloji": "Modern tech labs, neon accents, screens, clean futuristic spaces, data visualization aesthetics",
    "uzay": "Deep space, planets, nebulae, NASA-style realism, starfields, cosmic scale",
    "tarihi_insanlar": "Period-accurate costumes, royal courts, old portraits coming alive, historical settings",
    "tarihi_olaylar": "Historical reenactment feel, crowds, battlefields, monuments, archival documentary tone",
    "savaslar": "Battlefields, soldiers silhouettes, smoke, strategic maps, dramatic war documentary",
    "yeme_icme": "Food close-ups, steam, warm kitchen light, vibrant ingredients, appetizing macro shots",
    "cocuk_eglence": "Bright cheerful colors, cute friendly animals, nature, soft daylight, playful safe imagery",
    "oyun": "Game-inspired environments, dynamic action, stylized but realistic lighting",
    "muzik": "Concert stages, instruments, vinyl records, neon club lights, performance energy",
    "sanat": "Museum galleries, paintings, sculptures, brush strokes, artistic lighting",
    "seyahat": "Travel vlog aesthetic, scenic landmarks, beaches, old towns, aerial city views, golden hour",
    "genel": "Cinematic realism, balanced lighting, clear subject focus",
}

# MiniMax H3: muzik / BGM yasak (belgesel / B-roll); diegetic SFX OK
DEFAULT_NEGATIVE = (
    "cartoon, anime, oversaturated CGI look, plastic skin, uncanny valley, "
    "watermark, logo, text overlay, subtitles, shaky handheld chaos, "
    "BGM, soundtrack, underscore, phonk, orchestra bed, generated music"
)

STYLE_TO_VISUAL: dict[str, str] = {
    "dark_mystery": "found_footage / observational documentary, natural light, photoreal live-action",
    "cinematic": "photoreal live-action, natural skin, film grain, cinematic contrast",
    "epic_history": "photoreal period live-action, natural skin, subtle film grain",
    "atmospheric": "photoreal atmospheric live-action, volumetric light, film grain",
}

_CAMERA = (
    "slow push-in with small amplitude",
    "wide establishing then gentle push",
    "static medium shot with subtle breathing",
    "tracking dolly at slow speed",
    "low angle observational hold",
    "top-down documentary reveal",
)


def _diversity_block(*, batch_index: int = 1) -> str:
    cam = random.choice(_CAMERA)
    run = random.randint(1000, 9999)
    return f"""
CESITLILIK (tur {batch_index}, #{run}):
- Bu turda kamera hissi: {cam}
- Her SCENE onceki turlardan FARKLI mekan / beat / kamera; ayni cumleleri TEKRARLAMA."""


def _avoid_block(avoid_scenes: list[str]) -> str:
    if not avoid_scenes:
        return ""
    samples = avoid_scenes[:6]
    lines = "\n".join(f"- {s[:160].replace(chr(10), ' ')}" for s in samples)
    return f"""
ONCEKI SAHNELER (TEKRARLAMA):
{lines}"""


def _build_user_prompt(
    *,
    topic: str,
    niche_id: str,
    scene_count: int,
    style: str,
    line_mode: str,
    aspect: str,
    batch_index: int = 1,
    batch_total: int = 1,
    batch_focus: str = "",
    avoid_scenes: list[str] | None = None,
    script: str = "",
) -> str:
    visual = NICHE_VISUAL.get(niche_id, NICHE_VISUAL["genel"])
    style_label = STYLE_LABELS.get(style, style)
    craft = STYLE_TO_VISUAL.get(style, STYLE_TO_VISUAL["cinematic"])
    mode_hint = LINE_MODE_LABELS.get(line_mode, line_mode)
    vertical = "9:16 vertical portrait framing" if aspect == "9:16" else "16:9 widescreen framing"
    focus_label, focus_hint = BATCH_FOCUS[(batch_index - 1) % len(BATCH_FOCUS)]
    if batch_focus:
        focus_hint = batch_focus
    tur_line = ""
    if batch_total > 1:
        tur_line = f"\nURETIM TURU: {batch_index}/{batch_total} — {focus_label}\nTUR ODAK: {focus_hint}"

    script_bit = ""
    if (script or "").strip():
        script_bit = f"\nSENARYO OZETI (gorsel uyum icin):\n{(script or '').strip()[:900]}\n"

    continue_rules = ""
    if line_mode == "sliding_window":
        continue_rules = f"""
CONTINUE ZINCIRI (ZORUNLU — tam {scene_count} SCENE yaz, eksik birakma):
- SCENE_1: standalone acilis (World open → beat → camera → lock). Hedef ~500–900 karakter.
- SCENE_2…SCENE_{scene_count}: HER BIRI ayri baslikli blok.
  Ilk satir: Continue directly from the previous shot.
  Sonra: Same location/subjects/lighting + BU 5 sn'ye ozel YENI mikro-eylem + kamera.
  Continue sahneleri ~200–450 karakter; ayni cumleyi tekrarlama.
- Beat cesitliligi: establish → detail insert → reveal → push-in → lateral track → atmosphere → aftermath…
- ASLA tek SCENE yazip durma. ASLA "continuing the story of: …" filler yazma.
"""
    elif line_mode == "queue":
        continue_rules = f"""
BAGIMSIZ SAHNELER (ZORUNLU — tam {scene_count} SCENE):
- Her SCENE standalone; "Continue directly…" YAZMA.
- Her biri ~400–800 karakter; eksik SCENE birakma.
"""
    else:
        continue_rules = """
TEK SCENE:
- Tek uzun continuous-shot sahne senaryosu yaz (SCENE_1).
"""

    return f"""Konu (Turkce): {topic}
{tur_line}
{script_bit}
GOREV: MiniMax H3 icin TAM OLARAK {scene_count} adet INGILIZCE SCENE yaz.
Anahtar kelime listesi DEGIL — B-roll sahne senaryosu.
CIKTIDA SCENE_1 … SCENE_{scene_count} basliklarinin HEPSİ olmali.

HEDEF: MiniMax H3 Text-to-Video / continue — {vertical}
GORSEL NIS: {visual}
STIL: {style_label}
CRAFT: {craft}
SATIR MODU: {mode_hint}
{continue_rules}

GOLD STANDARD:
- SCENE_1 orta uzunluk (tum zincire yer birak); SCENE_2+ kisa continue beat.
- SCENE_1: World open → pulse → tek ana beat → camera → atmosphere + Lock (no cuts/dialogue/BGM).
- Belgesel / gizem: gozlemci kamera, dogal isik.
- Diyalog / keyword soup YASAK.
{_diversity_block(batch_index=batch_index)}
{_avoid_block(avoid_scenes or [])}

CIKTI FORMATI (markdown fence YOK):
SCENE_1:
(Ingilizce)

SCENE_2:
(Ingilizce continue)

...

SCENE_{scene_count}:
(Ingilizce continue)

NOTES:
(Turkce, 1-2 cumle)"""


def _parse_scenes(content: str) -> list[str]:
    """SCENE_N: bloklari veya eski SCENES: satir formatini oku."""
    text = (content or "").strip()
    if not text:
        return []
    blocks = re.findall(
        r"SCENE[_\s-]*(\d+)\s*:\s*(.*?)(?=SCENE[_\s-]*\d+\s*:|NOTES:|NEGATIVE:|$)",
        text,
        re.S | re.I,
    )
    if blocks:
        ordered = sorted(blocks, key=lambda x: int(x[0]))
        out: list[str] = []
        for _, body in ordered:
            scene = body.strip()
            if scene:
                out.append(scene[:2800])
        if out:
            return out

    # Eski tek-satir SCENES: formati (geriye uyum)
    m = re.search(r"SCENES:\s*(.+?)(?=NEGATIVE:|NOTES:|$)", text, re.S | re.I)
    if not m:
        return []
    lines = []
    for line in m.group(1).strip().splitlines():
        line = re.sub(r"^\d+[\).\-\s]+", "", line.strip())
        line = line.strip("-•* ")
        if line and not line.upper().startswith("SCENES"):
            lines.append(line[:2800])
    return lines


def _parse_negative(content: str) -> str:
    m = re.search(r"NEGATIVE:\s*(.+?)(?=NOTES:|WGP_AYAR:|SCENE_|$)", content, re.S | re.I)
    if not m:
        return DEFAULT_NEGATIVE
    text = m.group(1).strip().splitlines()[0].strip()
    return text[:500] if text else DEFAULT_NEGATIVE


def _parse_wgp_notes(content: str) -> str:
    m = re.search(r"(?:NOTES|WGP_AYAR):\s*(.+)", content, re.S | re.I)
    if not m:
        return (
            "Pinokio H3 Studio'ya yapistir. Continue zincirinde shot1 standalone, "
            "sonraki shot'lar «Continue directly from the previous shot.» ile baslar. "
            "Klip suresi 5 sn onerilir; muzik/BGM kapali."
        )
    return m.group(1).strip()[:900]


def _format_prompt_block(scenes: list[str], line_mode: str) -> str:
    if not scenes:
        return ""
    if line_mode == "single":
        return scenes[0]
    # MiniMax: sahneleri ayirici ile — kopyala-yapistir kolay
    parts = []
    for i, s in enumerate(scenes, start=1):
        parts.append(f"=== SCENE {i} ===\n{s.strip()}")
    return "\n\n".join(parts)


async def _generate_single_batch(
    *,
    topic: str,
    niche_id: str,
    scene_count: int,
    style: str,
    line_mode: str,
    aspect: str,
    batch_index: int,
    batch_total: int,
    avoid_scenes: list[str],
    script: str = "",
) -> dict[str, str | list[str] | int]:
    focus_label, focus_hint = BATCH_FOCUS[(batch_index - 1) % len(BATCH_FOCUS)]
    prompt = _build_user_prompt(
        topic=topic.strip(),
        niche_id=niche_id,
        scene_count=scene_count,
        style=style,
        line_mode=line_mode,
        aspect=aspect,
        batch_index=batch_index,
        batch_total=batch_total,
        batch_focus=focus_hint,
        avoid_scenes=avoid_scenes,
        script=script,
    )
    opts = {**creative_chat_options(), "num_predict": 8192, "max_tokens": 8192}
    content = await ollama_chat(
        [{"role": "user", "content": prompt}],
        think=False,
        timeout=240.0,
        clean_script=False,
        options=opts,
    )
    content = (content or "").strip()
    scenes = _parse_scenes(content)
    negative = _parse_negative(content)
    notes = _parse_wgp_notes(content)
    block = _format_prompt_block(scenes, line_mode)

    if not scenes and content:
        # Son care: tum metni tek SCENE say
        cleaned = re.sub(r"^(NOTES|NEGATIVE|WGP_AYAR):.*", "", content, flags=re.S | re.I).strip()
        if len(cleaned) > 80:
            scenes = [cleaned[:2800]]
            block = _format_prompt_block(scenes, line_mode)

    return {
        "index": batch_index,
        "label": focus_label,
        "focus": focus_hint,
        "scenes": scenes,
        "prompt_block": block,
        "negative_prompt": negative,
        "wgp_notes": notes,
        "engine": "minimax_h3",
    }



_FILLER_RE = re.compile(
    r"cinematic\s+5-second\s+shot\s+continuing\s+the\s+story\s+of\s*:",
    re.I,
)

_CAMERA_BEATS = (
    "Slow overhead descent revealing more of the same ground details and textures.",
    "Gentle lateral track across the same location, holding identical dawn lighting.",
    "Intimate push-in toward a carved stone edge and dry clay fragment already in frame.",
    "Slight tilt down as thin fog drifts through the same trunks and limestone base.",
    "Observational hold, then a subtle forward creep over silt and buried relief.",
    "Rise a fraction then settle again, keeping top-down documentary framing.",
    "Follow a drifting dust mote toward abandoned tools already established.",
    "Continue descending until cracked vessels dominate the vertical frame.",
    "Soft orbiting micro-move around the measuring rod and urn fragments.",
    "Final lingering pullback that still stays within the same clearing.",
)


def is_filler_scene(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if _FILLER_RE.search(t):
        return True
    if len(t) < 40 and "continuing the story" in t.lower():
        return True
    return False


def _script_beat_lines(script: str, topic: str, need: int) -> list[str]:
    raw = re.split(r"(?<=[.!?…])\s+", (script or "").strip())
    beats = [b.strip() for b in raw if len(b.strip()) >= 12]
    if not beats:
        topic = (topic or "mystery site").strip()[:80]
        beats = [f"Documentary beat about {topic}"] * need
    out: list[str] = []
    i = 0
    while len(out) < need:
        out.append(beats[i % len(beats)])
        i += 1
    return out[:need]


def pad_scenes_locally(
    scenes: list[str],
    *,
    need: int,
    topic: str,
    script: str = "",
) -> list[str]:
    """Eksik / filler SCENE'leri senaryo + kamera beat ile doldur (LLM yok)."""
    cleaned = [s.strip() for s in scenes if (s or "").strip() and not is_filler_scene(s)]
    if not cleaned:
        t = (topic or "ancient site").strip()[:120]
        cleaned = [
            f"Overhead documentary view of a moisture-starved clearing related to {t}. "
            f"Cold dawn light, thin fog, cracked earth and weathered stone details. "
            f"Slow observational downward push. One continuous shot, no cuts, no dialogue, no BGM."
        ]
    anchor = cleaned[0]
    anchor_hint = " ".join(anchor.split())[:280]
    beats = _script_beat_lines(script, topic, max(need, 1))
    while len(cleaned) < need:
        idx = len(cleaned)
        cam = _CAMERA_BEATS[(idx - 1) % len(_CAMERA_BEATS)]
        narr = beats[(idx - 1) % len(beats)]
        cleaned.append(
            "Continue directly from the previous shot. "
            "Same location, same props, same lighting and camera language. "
            f"Visual continuity with: {anchor_hint}. "
            f"Story beat (show, do not narrate words): {narr[:220]}. "
            f"Camera: {cam} "
            "One continuous 5-second shot, no cuts, no dialogue, no BGM."
        )
    fixed: list[str] = []
    for i, s in enumerate(cleaned[:need]):
        if is_filler_scene(s) and i > 0:
            cam = _CAMERA_BEATS[(i - 1) % len(_CAMERA_BEATS)]
            narr = beats[(i - 1) % len(beats)]
            fixed.append(
                "Continue directly from the previous shot. "
                "Same location, same props, same lighting. "
                f"Story beat: {narr[:220]}. Camera: {cam} "
                "One continuous 5-second shot, no cuts, no dialogue, no BGM."
            )
        else:
            fixed.append(s)
    while len(fixed) < need:
        i = len(fixed)
        cam = _CAMERA_BEATS[(i - 1) % len(_CAMERA_BEATS)]
        narr = beats[(i - 1) % len(beats)]
        fixed.append(
            "Continue directly from the previous shot. "
            f"Story beat: {narr[:220]}. Camera: {cam} "
            "One continuous 5-second shot, no cuts, no dialogue, no BGM."
        )
    return fixed[:need]


async def fill_continue_scenes(
    *,
    existing: list[str],
    need: int,
    topic: str,
    script: str = "",
    niche_id: str = "tarih_gizem",
    style: str = "dark_mystery",
) -> list[str]:
    """Eksik continue SCENE'lerini ikinci LLM gecisiyle tamamla."""
    from akifactory.ollama_util import chat as ollama_chat

    have = [s for s in existing if (s or "").strip() and not is_filler_scene(s)]
    if len(have) >= need:
        return have[:need]
    missing = need - len(have)
    start_n = len(have) + 1
    end_n = need
    visual = NICHE_VISUAL.get(niche_id, NICHE_VISUAL["genel"])
    craft = STYLE_TO_VISUAL.get(style, STYLE_TO_VISUAL["cinematic"])
    anchor = have[0][:1200] if have else topic
    prompt = f"""You write MiniMax H3 CONTINUE shot prompts in ENGLISH.

Topic: {topic[:500]}
Visual niche: {visual}
Craft: {craft}

SCENE_1 (already done — keep continuity with this world):
{anchor}

Narration cues (match visuals to these beats, do NOT quote Turkish speech):
{(script or topic)[:1200]}

Write ONLY SCENE_{start_n} through SCENE_{end_n} ({missing} scenes).
Each scene:
- First line: Continue directly from the previous shot.
- Same location/subjects/lighting; NEW 5s micro-action + camera move
- 200–450 characters; no filler like "continuing the story of"
- No dialogue, no BGM, no cuts

Format:
SCENE_{start_n}:
...

SCENE_{end_n}:
...
"""
    try:
        opts = {**creative_chat_options(), "num_predict": 4096, "max_tokens": 4096}
        content = await ollama_chat(
            [{"role": "user", "content": prompt}],
            think=False,
            timeout=180.0,
            clean_script=False,
            options=opts,
        )
        more = _parse_scenes(content)
        more = [m for m in more if not is_filler_scene(m)]
        merged = have + more
        if len(merged) >= need:
            return merged[:need]
        return pad_scenes_locally(merged, need=need, topic=topic, script=script)
    except Exception:
        return pad_scenes_locally(have, need=need, topic=topic, script=script)


async def generate_wangp_prompt(
    *,
    topic: str,
    niche_id: str = "tarih_gizem",
    scene_count: int = 5,
    style: str = "dark_mystery",
    line_mode: str = "sliding_window",
    aspect: str = "9:16",
    batch_count: int = 1,
    script: str = "",
) -> dict[str, Any]:
    """API adi geriye uyumlu; icerik H3 Studio SCENE senaryosu."""
    scene_count = max(3, min(12, int(scene_count)))
    batch_count = max(1, min(4, int(batch_count)))
    batches: list[dict[str, Any]] = []
    avoid: list[str] = []
    all_scenes: list[str] = []
    negative = DEFAULT_NEGATIVE
    notes = ""

    for i in range(1, batch_count + 1):
        batch = await _generate_single_batch(
            topic=topic,
            niche_id=niche_id,
            scene_count=scene_count,
            style=style,
            line_mode=line_mode,
            aspect=aspect,
            batch_index=i,
            batch_total=batch_count,
            avoid_scenes=avoid,
            script=script,
        )
        scenes = list(batch.get("scenes") or [])
        if scenes:
            batches.append(batch)
            avoid.extend(scenes)
            all_scenes.extend(scenes)
            if batch.get("negative_prompt"):
                negative = str(batch["negative_prompt"])
            if batch.get("wgp_notes"):
                notes = str(batch["wgp_notes"])

    first_block = str(batches[0]["prompt_block"]) if batches else ""
    multi_note = ""
    if batch_count > 1 and batches:
        multi_note = (
            f"\n\n{len(batches)} tur uretildi — H3 Studio'da once Tur 1 SCENE'lerini "
            "calistir, bitince Tur 2'yi yapistir (VRAM icin sirayla)."
        )

    return {
        "batches": batches,
        "batch_count": len(batches),
        "scenes": all_scenes,
        "prompt_block": first_block,
        "prompt": first_block,
        "negative_prompt": negative,
        "wgp_notes": (notes + multi_note).strip(),
        "line_mode": line_mode,
        "style": style,
        "aspect": aspect,
        "engine": "minimax_h3",
    }
