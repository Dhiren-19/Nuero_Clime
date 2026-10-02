"""
Bhashini translation gateway (TRD 2.3.4).

    input = source text (English) + target language code
    output = cached translated output keyed by (content_hash, language)

If BHASHINI_API_KEY is configured, this calls the real Bhashini ULCA
pipeline API. Otherwise (the default demo state — Bhashini requires a
registered Government of India API key we don't have here) it falls back
to a small built-in phrase dictionary covering the fixed set of UI/alert
strings NeuroClime actually needs, so the multilingual UI toggle and
translated alert text still work end-to-end in the demo. Both paths use
the same on-disk cache keyed by (content_hash, language), exactly as the
TRD specifies, so switching to the real API later changes zero call sites.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import requests

from app.config import settings

CACHE_PATH = Path(settings.LOCAL_DATA_DIR) / "translation_cache.json"

# Fallback phrase book for the fixed set of strings the product actually
# needs translated (build-time UI bundle + the alert-message template used
# in pipeline/run_inference.py). Real Bhashini output is far more general;
# this only exists so the demo isn't silently English-only.
_FALLBACK_PHRASES = {
    "hi": {
        "Safe": "सुरक्षित",
        "Caution": "सावधान",
        "Danger": "खतरा",
        "Extreme": "अत्यधिक",
        "home": "घर",
        "work": "कार्यस्थल",
        "risk": "जोखिम",
        "feels like": "महसूस होता है",
    },
    "mr": {
        "Safe": "सुरक्षित",
        "Caution": "सावध",
        "Danger": "धोका",
        "Extreme": "अत्यंत",
        "home": "घर",
        "work": "कामाचे ठिकाण",
        "risk": "धोका",
        "feels like": "जाणवते",
    },
}


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False))


def _call_real_bhashini(text: str, target_lang: str) -> str:
    """Real ULCA pipeline call — only reached when BHASHINI_API_KEY is set."""
    resp = requests.post(
        f"{settings.BHASHINI_API_BASE_URL}/inference/pipeline",
        headers={"Authorization": settings.BHASHINI_API_KEY},
        json={
            "pipelineTasks": [
                {
                    "taskType": "translation",
                    "config": {"language": {"sourceLanguage": "en", "targetLanguage": target_lang}},
                }
            ],
            "inputData": {"input": [{"source": text}]},
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["pipelineResponse"][0]["output"][0]["target"]


def _fallback_translate(text: str, target_lang: str) -> str:
    phrases = _FALLBACK_PHRASES.get(target_lang)
    if not phrases:
        return text
    out = text
    for en, local in phrases.items():
        out = out.replace(en, local)
    return out


def translate(text: str, target_lang: str) -> str:
    """Translate `text` into `target_lang`, cached by (content_hash, language)."""
    if target_lang in ("en", "", None):
        return text

    cache = _load_cache()
    key = f"{_content_hash(text)}:{target_lang}"
    if key in cache:
        return cache[key]

    if settings.BHASHINI_API_KEY:
        try:
            translated = _call_real_bhashini(text, target_lang)
        except Exception:
            translated = _fallback_translate(text, target_lang)
    else:
        translated = _fallback_translate(text, target_lang)

    cache[key] = translated
    _save_cache(cache)
    return translated
