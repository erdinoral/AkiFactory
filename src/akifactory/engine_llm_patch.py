"""Motor LLM — Qwen3 thinking kapat + Turkce senaryo temizligi."""

from __future__ import annotations


def apply_llm_runtime_patch() -> None:
    try:
        from akifactory.engine.services import llm
    except ImportError:
        return

    if getattr(llm, "_aki_patched", False):
        return

    _patch_openai_ollama_think()

    _orig_generate = llm.generate_script

    def _generate_script_wrapped(*args, **kwargs):
        out = _orig_generate(*args, **kwargs)
        if not out:
            return out
        language = kwargs.get("language", "")
        if len(args) > 1:
            language = language or args[1]
        if "tr" in str(language or "").lower():
            from akifactory.text_utils import enforce_spoken_script_limits

            return enforce_spoken_script_limits(out)
        return out

    llm.generate_script = _generate_script_wrapped

    _orig_generate_terms = llm.generate_terms

    def _generate_terms_wrapped(
        video_subject: str, video_script: str, amount: int = 7
    ):
        from akifactory.video_search_terms import generate_search_terms

        return generate_search_terms(
            video_subject,
            video_script,
            amount,
            generate_response=llm._generate_response,
        )

    llm.generate_terms = _generate_terms_wrapped
    llm._aki_patched = True


def _patch_openai_ollama_think() -> None:
    """motor Ollama yolu OpenAI uyumlu API kullanir — think=false enjekte et."""
    try:
        from openai.resources.chat import completions as comp_mod
    except ImportError:
        return

    if getattr(comp_mod.Completions, "_aki_think_patched", False):
        return

    _orig_create = comp_mod.Completions.create

    def _create(self, *args, **kwargs):
        base = str(getattr(self._client, "base_url", "") or "")
        if "11434" in base or "ollama" in base.lower():
            extra = dict(kwargs.get("extra_body") or {})
            extra["think"] = False
            extra["keep_alive"] = 0
            opts = dict(extra.get("options") or {})
            opts.setdefault("temperature", 0.7)
            opts.setdefault("top_p", 0.9)
            opts.setdefault("repeat_penalty", 1.1)
            extra["options"] = opts
            kwargs["extra_body"] = extra
        return _orig_create(self, *args, **kwargs)

    comp_mod.Completions.create = _create
    comp_mod.Completions._aki_think_patched = True
