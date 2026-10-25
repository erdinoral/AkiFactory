"""Edge TTS: ses gelmezse yeni baglantiyla tekrar dene.

Microsoft bazi sunucularda belirli sesleri (or. tr-TR-AhmetNeural) zaman zaman
bos dondurur (NoAudioReceived); her yeni baglanti farkli sunucuya duser.
Tek deneme tum uretimi (RVC tabani dahil) dusuruyordu.
"""

from __future__ import annotations

import asyncio

_ATTEMPTS = 15
_DELAY_S = 0.4


def install() -> None:
    try:
        from edge_tts import communicate as comm_mod
        from edge_tts.exceptions import NoAudioReceived
    except ImportError:
        return
    cls = comm_mod.Communicate
    if getattr(cls, "_aki_retry_installed", False):
        return
    orig = cls._Communicate__stream

    async def _stream_with_retry(self):
        for attempt in range(1, _ATTEMPTS + 1):
            yielded = False
            try:
                async for message in orig(self):
                    yielded = True
                    yield message
                return
            except NoAudioReceived:
                # Parca yarida kaldiysa tekrar denemek sesi/zamanlamayi bozar
                if yielded or attempt == _ATTEMPTS:
                    raise
                self.state["chunk_audio_bytes"] = 0
                await asyncio.sleep(_DELAY_S)

    cls._Communicate__stream = _stream_with_retry
    cls._aki_retry_installed = True
