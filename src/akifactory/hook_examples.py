"""Kullanici hook ornekleri — nis basina data/hook_examples.json."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from akifactory.paths import data_dir
from akifactory.script_prompts import resolve_niche

STORE_FILE = "hook_examples.json"
MAX_PER_NICHE = 40

_BUILTIN: dict[str, list[str]] = {
    "tarih_gizem": [
        "1912'de Titanik battiktan sonra batarya kutulari hala sinyal gonderiyordu.",
        "Gobeklitepe, yazinin bulundugu sehirden 7 bin yil once insa edildi.",
        "Voynic el yazmasinin 240 sayfasinda hicbir cumle bugune kadar cozulemedi.",
    ],
    "teknoloji": [
        "ChatGPT yayinlandiktan bir hafta icinde milyonlarca kullaniciya ulasti.",
        "2017'de WannaCry fidye yazilimi 150 ulkede bilgisayarlari ayni gunde kilitlemisti.",
        "iPhone 2007'de ciktiginda dokunmatik ekranli telefon fikri cogu markayi sasirtti.",
    ],
    "uzay": [
        "Perseverance araci 2021'de Mars'a indi ve Jezero kraterinde kaya ornekleri topluyor.",
        "Hubble Uzay Teleskobu 1990'dan beri evrenin en uzak galaksilerini goruntuluyor.",
        "Ingenuity, ince Mars atmosferinde ucabilen ilk insansiz helikopter oldu.",
    ],
    "tarihi_insanlar": [
        "Nikola Tesla, Edison'dan once alternatif akim sistemini evlere tasidi.",
        "Cleopatra M.O. 30'da olmeden once Misir'in son Helenistik hukumdariydi.",
        "Ataturk 1923'te Turkiye Cumhuriyeti'ni kurarak yeni bir devlet modeli olusturdu.",
    ],
    "tarihi_olaylar": [
        "9 Kasim 1989'da Berlin Duvari'nin kapilari aniden acildi.",
        "1929 Borsa cokusu Buyuk Buhran'in baslangic gunu olarak tarihe gecti.",
        "1789'da Bastille hapishanesinin dusmesi Fransiz Devrimi'nin simgesi oldu.",
    ],
    "savaslar": [
        "18 Mart 1915'te Canakkale'de Ittifak donanmasi agir kayip vererek geri cekildi.",
        "1944 Haziran'inda Normandiya cikarmasi ikinci dunya savasinin donum noktasiydi.",
        "Waterloo Savasi 1815'te Napolyon'un son buyuk yenilgisini getirdi.",
    ],
    "yeme_icme": [
        "Iskender kebap 19. yuzyilda Bursa'da Iskender Efendi tarafindan gelistirildi.",
        "Espresso Italya'da 20. yuzyil basinda hizli kahve kulturunun simgesi oldu.",
        "Sushi aslinda balik koruma yontemi olarak Japonya'da yuzyillar once basladi.",
    ],
    "cocuk_eglence": [
        "Biliyor musun, arilar gun boyu calisip bal yapar.",
        "Vay be, kaplumbagalar kabuklarini evleri gibi tasir.",
        "Haydi bakalim, gokkusagi yagmur damlalarinda gizlenir.",
    ],
    "oyun": [
        "Minecraft 2011'de cikti ve bloklardan dunya kurma fikri milyonlari cekti.",
        "Tetris 1984'te Alexey Pajitnov tarafindan yazildi ve en cok oynanan oyunlardan biri oldu.",
        "Fortnite 2017'de battle royale moduyla dunya capinda patladi.",
    ],
    "muzik": [
        "Bohemian Rhapsody 1975'te alti dakikalik opera rock formatinda yayinlandi.",
        "Michael Jackson'in Thriller albumu dunyanin en cok satan plagi oldu.",
        "The Beatles 1964'te Ed Sullivan programinda 73 milyon kisiye canli yayinlandi.",
    ],
    "sanat": [
        "Mona Lisa 1911'de Louvre'dan calindi ve iki yil sonra bulundu.",
        "Van Gogh yasarken sadece bir tablo satabildi; bugun eserleri milyonlarca dolara gidiyor.",
        "Michelangelo'nun Davut heykeli 1504'te Floransa'da tamamlandi.",
    ],
    "seyahat": [
        "Kapadokya'da sabah balonlari vadilerin uzerinde yukselirken sehir tas bir masal gibi gorunur.",
        "Tokyo'da Shibuya Kavsaği her gun milyonlarca insanin gectigi en yogun noktalardan biri.",
        "Santorini'nin mavi kubbeli evleri volkanik kayalarin uzerine kurulu.",
    ],
    "genel": [
        "Insan beyni gece uykusunda REM evresinde yogun ruya gorur.",
        "Dunya yuzeyinin yuzde yetmisinden fazlasi okyanuslarla kapli.",
        "Bal arilari gun boyu calisarak bir kovan bal uretir.",
    ],
}


def _path():
    return data_dir() / STORE_FILE


def _load() -> dict[str, Any]:
    p = _path()
    if not p.is_file():
        return {"niches": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("niches"), dict):
            return data
    except Exception:
        pass
    return {"niches": {}}


def _save(data: dict[str, Any]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _niche_key(niche_id: str | None) -> str:
    return resolve_niche(niche_id or "genel")


def _items_for(data: dict[str, Any], niche_id: str) -> list[dict[str, Any]]:
    niches = data.setdefault("niches", {})
    raw = niches.get(niche_id)
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw:
        if isinstance(row, dict) and (row.get("text") or "").strip():
            out.append(row)
    return out


def list_for_niche(niche_id: str | None) -> list[dict[str, Any]]:
    key = _niche_key(niche_id)
    items = _items_for(_load(), key)
    if items:
        return items
    builtin = _BUILTIN.get(key) or []
    return [
        {
            "id": f"builtin-{i}",
            "text": t,
            "builtin": True,
            "created_at": "",
        }
        for i, t in enumerate(builtin)
    ]


def list_all() -> dict[str, list[dict[str, Any]]]:
    data = _load()
    niches = data.get("niches") or {}
    out: dict[str, list[dict[str, Any]]] = {}
    keys = set(niches.keys()) | set(_BUILTIN.keys())
    for key in keys:
        saved = _items_for(data, key)
        if saved:
            out[key] = saved
        elif key in _BUILTIN:
            out[key] = list_for_niche(key)
    return out


def add_example(niche_id: str, text: str) -> dict[str, Any]:
    hook = (text or "").strip()
    if len(hook) < 8:
        raise ValueError("Hook en az 8 karakter olmali")
    key = _niche_key(niche_id)
    data = _load()
    items = _items_for(data, key)
    norm = hook.lower()
    if any((it.get("text") or "").strip().lower() == norm for it in items):
        raise ValueError("Bu hook zaten kayitli")
    entry = {
        "id": uuid.uuid4().hex[:10],
        "text": hook[:500],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    items.insert(0, entry)
    data.setdefault("niches", {})[key] = items[:MAX_PER_NICHE]
    _save(data)
    return entry


def remove_example(niche_id: str, example_id: str) -> bool:
    key = _niche_key(niche_id)
    eid = (example_id or "").strip()
    if not eid or eid.startswith("builtin-"):
        return False
    data = _load()
    items = _items_for(data, key)
    new_items = [it for it in items if it.get("id") != eid]
    if len(new_items) == len(items):
        return False
    data.setdefault("niches", {})[key] = new_items
    _save(data)
    return True


def remove_from_pool(niche_id: str, example_id: str) -> str | None:
    """Ornek listesinden kaldir; builtin ise kullanici havuzuna donustur."""
    key = _niche_key(niche_id)
    eid = (example_id or "").strip()
    if not eid:
        return None
    data = _load()
    items = _items_for(data, key)
    if items:
        for i, it in enumerate(items):
            if it.get("id") == eid:
                text = (it.get("text") or "").strip()
                items.pop(i)
                data.setdefault("niches", {})[key] = items
                _save(data)
                return text or None
        return None
    if not eid.startswith("builtin-"):
        return None
    try:
        idx = int(eid.split("-", 1)[1])
    except (IndexError, ValueError):
        return None
    builtin = _BUILTIN.get(key) or []
    if idx < 0 or idx >= len(builtin):
        return None
    removed = builtin[idx]
    new_items: list[dict[str, Any]] = []
    for i, t in enumerate(builtin):
        if i == idx:
            continue
        new_items.append(
            {
                "id": uuid.uuid4().hex[:10],
                "text": t,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    data.setdefault("niches", {})[key] = new_items
    _save(data)
    return removed


def all_texts_for_niche(niche_id: str | None) -> list[str]:
    return [(it.get("text") or "").strip() for it in list_for_niche(niche_id) if (it.get("text") or "").strip()]

def prompt_block(niche_id: str | None, *, limit: int = 8) -> str:
    items = list_for_niche(niche_id)
    user_items = [it for it in items if not it.get("builtin")]
    pool = user_items if user_items else items
    if not pool:
        return ""
    lines = "\n".join(f"- «{(it.get('text') or '').strip()}»" for it in pool[:limit])
    return (
        "\nKULLANICI HOOK ORNEKLERI (ton ve yapi icin; birebir kopyalama, konuya uyarla):\n"
        f"{lines}\n"
    )


def public_snapshot() -> dict[str, Any]:
    all_items = list_all()
    counts = {k: len(v) for k, v in all_items.items()}
    return {"counts": counts, "niches": all_items}
