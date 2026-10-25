"""Telegram bot bildirimleri — uretim bitti / video hazir."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from akifactory.paths import data_dir

log = logging.getLogger(__name__)

CONFIG_FILE = data_dir() / "telegram.json"
_notified_video_tasks: set[str] = set()
_last_queue_notify_ts: float = 0.0
DEFAULT_SHARED_BOT = "AkiFactory_bot"

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "bot_token": "",
    "chat_id": "",
    "notify_video": True,
    "notify_queue": True,
}


def _load() -> dict[str, Any]:
    if not CONFIG_FILE.is_file():
        return dict(DEFAULTS)
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULTS)
    if not isinstance(raw, dict):
        return dict(DEFAULTS)
    out = dict(DEFAULTS)
    out.update(raw)
    return out


def _save(data: dict[str, Any]) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_settings_public() -> dict[str, Any]:
    cfg = _load()
    token = (cfg.get("bot_token") or "").strip()
    masked = ""
    if len(token) > 12:
        masked = token[:6] + "…" + token[-4:]
    elif token:
        masked = "••••"
    bot_username = (cfg.get("bot_username") or "").strip()
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "configured": bool(token and (cfg.get("chat_id") or "").strip()),
        "has_token": bool(token),
        "bot_token_masked": masked,
        "bot_username": bot_username,
        "chat_id": str(cfg.get("chat_id") or "").strip(),
        "notify_video": bool(cfg.get("notify_video", True)),
        "notify_queue": bool(cfg.get("notify_queue", True)),
    }


def update_settings(
    *,
    enabled: bool | None = None,
    bot_token: str | None = None,
    chat_id: str | None = None,
    notify_video: bool | None = None,
    notify_queue: bool | None = None,
) -> dict[str, Any]:
    cfg = _load()
    if enabled is not None:
        cfg["enabled"] = bool(enabled)
    if bot_token is not None:
        t = bot_token.strip()
        if t:
            cfg["bot_token"] = t
    if chat_id is not None:
        cfg["chat_id"] = str(chat_id).strip()
    if notify_video is not None:
        cfg["notify_video"] = bool(notify_video)
    if notify_queue is not None:
        cfg["notify_queue"] = bool(notify_queue)
    _save(cfg)
    return get_settings_public()


def remember_bot_username(username: str) -> dict[str, Any]:
    u = (username or "").strip().lstrip("@")
    if not u:
        return get_settings_public()
    cfg = _load()
    cfg["bot_username"] = u
    _save(cfg)
    return get_settings_public()


def get_telegram_guide() -> dict[str, Any]:
    """UI icin Telegram kurulum ve kullanim rehberi."""
    pub = get_settings_public()
    bot = (pub.get("bot_username") or DEFAULT_SHARED_BOT).lstrip("@")
    return {
        "default_bot_username": DEFAULT_SHARED_BOT,
        "bot_username": bot,
        "bot_link": f"https://t.me/{bot}",
        "botfather_link": "https://t.me/BotFather",
        "sections": [
            {
                "title": "Hizli kurulum (paylasilan bot)",
                "steps": [
                    "Telegram'da @AkiFactory_bot botunu ac (BotFather degil).",
                    "Bota /start yaz — bu adim zorunlu, yoksa mesaj gitmez.",
                    "Bot token kutusuna paylasilan bot token'ini yapistir → Kaydet (kendi botun varsa onun token'i).",
                    "Chat ID bul — senin Telegram kullanici ID'n otomatik gelir ve kaydedilir.",
                    "Test gonder ile telefonuna deneme mesaji dus.",
                ],
            },
            {
                "title": "Kendi botun (istege bagli)",
                "steps": [
                    "Telegram'da @BotFather ac → /newbot ile yeni bot olustur.",
                    "Verilen token'i asagidaki Bot token kutusuna yapistir → Kaydet.",
                    "Kendi botuna /start yaz → Chat ID bul → Test gonder.",
                ],
            },
            {
                "title": "Baska birine bildirim (farkli kullanici)",
                "steps": [
                    "Her kullanici kendi telefonundan bota /start yazmali.",
                    "O kisi kendi AkiFactory kurulumunda Chat ID bul yapar (veya ID'yi sana iletir).",
                    "Ayni bot token paylasilabilir; Chat ID kisi basina farklidir.",
                    "Senin Chat ID'n pakete gitmez — data/telegram.json yalnizca o PC'de kalir.",
                ],
            },
        ],
        "when_notified": [
            "Her video hazir olunca (aciksa)",
            "Uretim kuyrugu tamamen bitince (aciksa)",
        ],
        "notes": [
            "BotFather'a /start yazma — bildirim botuna yaz.",
            "Token ve Chat ID kurulum paketine dahil edilmez.",
            "Bildirimler kapaliysa mesaj gonderilmez.",
        ],
    }


async def _bot_username(token: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.get(f"https://api.telegram.org/bot{token}/getMe")
            data = r.json()
        if data.get("ok"):
            return str((data.get("result") or {}).get("username") or "").strip()
    except Exception:
        pass
    return ""


async def refresh_bot_username_from_token() -> dict[str, Any]:
    cfg = _load()
    token = (cfg.get("bot_token") or "").strip()
    if not token:
        return get_settings_public()
    user = await _bot_username(token)
    if user:
        return remember_bot_username(user)
    return get_settings_public()


def _chat_id_from_update(upd: dict[str, Any]) -> int | None:
    for key in ("message", "edited_message", "channel_post", "edited_channel_post"):
        msg = upd.get(key) or {}
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid is not None:
            return int(cid)
    cb = upd.get("callback_query") or {}
    msg = cb.get("message") or {}
    chat = msg.get("chat") or {}
    cid = chat.get("id")
    if cid is not None:
        return int(cid)
    for key in ("my_chat_member", "chat_member"):
        mcm = upd.get(key) or {}
        chat = mcm.get("chat") or {}
        cid = chat.get("id")
        if cid is not None:
            return int(cid)
    return None


async def discover_chat_id(token: str | None = None) -> str | None:
    result = await discover_chat_id_detail(token)
    return result.get("chat_id") if result.get("ok") else None


async def discover_chat_id_detail(token: str | None = None) -> dict[str, Any]:
    tok = (token or _load().get("bot_token") or "").strip()
    if not tok:
        return {"ok": False, "error": "Bot token yok — once token kaydedin."}

    bot_user = await _bot_username(tok)
    bot_hint = f"@{bot_user}" if bot_user else "kendi botunuza"

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            wh = await client.get(f"https://api.telegram.org/bot{tok}/getWebhookInfo")
            wh_data = wh.json()
            if wh_data.get("ok") and (wh_data.get("result") or {}).get("url"):
                await client.post(f"https://api.telegram.org/bot{tok}/deleteWebhook")

            r = await client.get(
                f"https://api.telegram.org/bot{tok}/getUpdates",
                params={"limit": 25, "timeout": 0},
            )
            data = r.json()
    except Exception as exc:
        log.warning("telegram getUpdates failed: %s", exc)
        return {
            "ok": False,
            "error": f"Telegram API'ye ulasilamadi: {exc}",
            "bot_username": bot_user,
        }

    if not data.get("ok"):
        desc = data.get("description") or "Telegram API hatasi"
        if "Unauthorized" in desc or "401" in desc:
            desc = "Token gecersiz — BotFather'dan yeni token alip kaydedin."
        return {"ok": False, "error": desc, "bot_username": bot_user}

    updates = data.get("result") or []
    for upd in reversed(updates):
        cid = _chat_id_from_update(upd)
        if cid is not None:
            return {"ok": True, "chat_id": str(cid), "bot_username": bot_user}

    # Bekleyen guncellemeleri temizle — sonraki /start mesaji okunabilsin
    if updates:
        try:
            last_id = max(int(u.get("update_id", 0)) for u in updates)
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.get(
                    f"https://api.telegram.org/bot{tok}/getUpdates",
                    params={"offset": last_id + 1, "timeout": 0},
                )
        except Exception:
            pass

    pending = 0
    try:
        pending = int((wh_data.get("result") or {}).get("pending_update_count") or 0)
    except Exception:
        pending = 0

    hint = (
        f"Telegram'da {bot_hint} botuna gidin (BotFather degil) ve /start yazin, "
        "sonra tekrar «Chat ID bul» deyin."
    )
    if pending > 0:
        hint += " Bekleyen mesaj var ama okunamadi — bota tekrar /start yazin."

    return {"ok": False, "error": hint, "bot_username": bot_user}


async def send_message(text: str, *, parse_mode: str | None = None) -> dict[str, Any]:
    cfg = _load()
    if not cfg.get("enabled", True):
        return {"ok": False, "skipped": "disabled"}
    token = (cfg.get("bot_token") or "").strip()
    if not token:
        return {"ok": False, "error": "bot_token yok"}

    chat_id = str(cfg.get("chat_id") or "").strip()
    if not chat_id:
        found = await discover_chat_id(token)
        if found:
            chat_id = found
            cfg["chat_id"] = found
            _save(cfg)
        else:
            return {
                "ok": False,
                "error": "chat_id yok — Telegram'da bota /start yazin, sonra Ayarlar'dan Chat ID bul",
            }

    body = (text or "").strip()[:3900]
    if not body:
        return {"ok": False, "error": "bos mesaj"}

    payload: dict[str, Any] = {"chat_id": chat_id, "text": body, "disable_web_page_preview": True}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            r = await client.post(url, json=payload)
            data = r.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    if data.get("ok"):
        return {"ok": True}
    return {"ok": False, "error": data.get("description") or "Telegram hatasi"}


async def send_photo(
    photo_path: str | Path,
    *,
    caption: str = "",
) -> dict[str, Any]:
    """Telegram sendPhoto — basarisizsa ok=False (metin fallback cagiran tarafta)."""
    cfg = _load()
    if not cfg.get("enabled", True):
        return {"ok": False, "skipped": "disabled"}
    token = (cfg.get("bot_token") or "").strip()
    if not token:
        return {"ok": False, "error": "bot_token yok"}
    chat_id = str(cfg.get("chat_id") or "").strip()
    if not chat_id:
        found = await discover_chat_id(token)
        if found:
            chat_id = found
            cfg["chat_id"] = found
            _save(cfg)
        else:
            return {"ok": False, "error": "chat_id yok"}
    path = Path(photo_path)
    if not path.is_file():
        return {"ok": False, "error": "thumbnail yok"}
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            with path.open("rb") as f:
                files = {"photo": (path.name, f, "image/jpeg")}
                data = {"chat_id": chat_id, "caption": (caption or "")[:1000]}
                r = await client.post(url, data=data, files=files)
            resp = r.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if resp.get("ok"):
        return {"ok": True}
    return {"ok": False, "error": resp.get("description") or "Telegram hatasi"}


def _resolve_notify_thumbnail(task_id: str | None) -> Path | None:
    """Galeri veya motor task klasorunden thumbnail yolu."""
    tid = (task_id or "").strip()
    if not tid:
        return None
    try:
        from akifactory import gallery as gal
        from akifactory.paths import gallery_dir

        gdir = gallery_dir()
        for e in gal.list_items():
            if e.get("task_id") == tid:
                thumb = e.get("thumbnail") or ""
                if thumb:
                    p = gdir / thumb
                    if p.is_file():
                        return p
                fn = e.get("filename") or ""
                if fn:
                    stem = Path(fn).stem
                    for cand in (gdir / f"{stem}.jpg", gdir / f"{stem}_thumb.jpg"):
                        if cand.is_file():
                            return cand
    except Exception:
        pass
    try:
        from akifactory.paths import engine_task_dir

        tdir = engine_task_dir(tid)
        for name in ("thumbnail.jpg", "cover.jpg", "poster.jpg"):
            p = tdir / name
            if p.is_file():
                return p
        for p in tdir.glob("*.jpg"):
            return p
    except Exception:
        pass
    return None


async def notify_video_ready(subject: str, *, task_id: str | None = None) -> None:
    cfg = _load()
    if not cfg.get("enabled") or not cfg.get("notify_video", True):
        return
    tid = (task_id or "").strip()
    if tid:
        if tid in _notified_video_tasks:
            return
        _notified_video_tasks.add(tid)
        if len(_notified_video_tasks) > 500:
            _notified_video_tasks.clear()
    subj = (subject or "Video").strip()[:200]
    caption = f"✅ Video hazir\n{subj}"
    thumb = _resolve_notify_thumbnail(tid)
    if thumb:
        photo_result = await send_photo(thumb, caption=caption)
        if photo_result.get("ok") or photo_result.get("skipped"):
            return
        log.warning("Telegram foto basarisiz, metne dusuluyor: %s", photo_result.get("error"))
    result = await send_message(caption)
    if not result.get("ok") and not result.get("skipped"):
        log.warning("Telegram video bildirimi basarisiz: %s", result.get("error"))


async def notify_queue_idle(items: list[Any]) -> None:
    global _last_queue_notify_ts
    import time

    cfg = _load()
    if not cfg.get("enabled") or not cfg.get("notify_queue", True):
        return
    now = time.time()
    if now - _last_queue_notify_ts < 45:
        return
    done = sum(1 for it in items if getattr(it, "status", None) == "done")
    failed = sum(1 for it in items if getattr(it, "status", None) == "failed")
    active = sum(
        1 for it in items if getattr(it, "status", None) in ("pending", "running")
    )
    if active:
        return
    if done + failed == 0:
        return
    if failed:
        err = ""
        for it in items:
            if getattr(it, "status", None) == "failed" and getattr(it, "error", None):
                err = str(it.error)[:120]
                break
        msg = f"⚠️ Uretim kuyrugu bitti\n{done} tamam, {failed} hata"
        if err:
            msg += f"\n{err}"
    else:
        msg = f"✅ Uretim kuyrugu tamamlandi\n{done} islem bitti"
    result = await send_message(msg)
    if result.get("ok"):
        _last_queue_notify_ts = now
    elif not result.get("skipped"):
        log.warning("Telegram kuyruk bildirimi basarisiz: %s", result.get("error"))


async def send_test() -> dict[str, Any]:
    return await send_message("✅ AkiFactory Telegram baglantisi calisiyor.")
