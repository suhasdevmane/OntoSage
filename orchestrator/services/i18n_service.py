"""
Phase 7.6 — Internationalisation (i18n) Service
=================================================
TODO: Activate in main.py lifespan — initialize I18nService, wrap dialogue node
      input/output with detect_and_translate / translate_response. Deferred until
      multi-language user base is confirmed.
Auto-detects the language of a user query, translates it to English
for the pipeline, then translates the response back to the original
language before returning it to the user.

Pipeline integration (in main.py or workflow.py):
    from orchestrator.services.i18n_service import I18nService

    i18n = I18nService(llm_manager=llm)

    # Before workflow
    english_query, lang_code = await i18n.to_english(user_message)

    # After workflow produces response
    final_response = await i18n.from_english(response, lang_code)

Supported backends (in priority order):
  1. Google Translate API (requires GOOGLE_TRANSLATE_KEY)
  2. DeepL API (requires DEEPL_API_KEY)
  3. LLM-based translation (any LLM provider — slower but no extra key needed)
  4. Passthrough (English assumed — no error, just no translation)

Language detection:
  Uses langdetect library with confidence threshold.
  Falls back to English if detection confidence < 0.85.

Supported language codes (ISO 639-1):
  en fr de es it pt nl sv da no fi pl cs sk ro bg hr sl lv lt et
  zh ja ko ar hi ru uk tr
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

I18N_ENABLED = os.environ.get("I18N_ENABLED", "true").lower() == "true"
DETECT_CONFIDENCE = float(os.environ.get("I18N_DETECT_CONFIDENCE", "0.85"))
GOOGLE_API_KEY = os.environ.get("GOOGLE_TRANSLATE_KEY", "")
DEEPL_API_KEY = os.environ.get("DEEPL_API_KEY", "")
SKIP_SHORT_QUERIES = int(os.environ.get("I18N_SKIP_SHORT", "10"))  # chars

# Language names for LLM prompt
LANGUAGE_NAMES = {
    "en": "English",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "sv": "Swedish",
    "da": "Danish",
    "no": "Norwegian",
    "fi": "Finnish",
    "pl": "Polish",
    "cs": "Czech",
    "sk": "Slovak",
    "ro": "Romanian",
    "bg": "Bulgarian",
    "hr": "Croatian",
    "sl": "Slovenian",
    "lv": "Latvian",
    "lt": "Lithuanian",
    "et": "Estonian",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "ar": "Arabic",
    "hi": "Hindi",
    "ru": "Russian",
    "uk": "Ukrainian",
    "tr": "Turkish",
}


class I18nService:
    """
    Multi-language support for the OntoSage pipeline.

    The service is stateless — every call is independent.
    Thread-safe with standard asyncio concurrency.
    """

    def __init__(self, llm_manager=None, enabled: bool = I18N_ENABLED):
        self._llm = llm_manager
        self._enabled = enabled

    # ─────────────────────────────────────────────────────────────────────────
    # Detection
    # ─────────────────────────────────────────────────────────────────────────

    def detect_language(self, text: str) -> Tuple[str, float]:
        """
        Detect the language of text.

        Returns:
            (lang_code, confidence)  e.g. ("fr", 0.98)
            Returns ("en", 1.0) if detection fails or text is too short.
        """
        if not self._enabled or len(text) < SKIP_SHORT_QUERIES:
            return "en", 1.0

        # Try langdetect
        try:
            from langdetect import detect_langs

            results = detect_langs(text)
            if results:
                top = results[0]
                return top.lang, float(top.prob)
        except ImportError:
            logger.debug("langdetect not installed — language detection unavailable")
        except Exception as e:
            logger.debug(f"Language detection error: {e}")

        # Fallback: simple ASCII ratio heuristic
        ascii_ratio = sum(c.isascii() for c in text) / max(len(text), 1)
        if ascii_ratio > 0.90:
            return "en", 0.75  # Probably English
        return "en", 0.50  # Unknown, assume English

    # ─────────────────────────────────────────────────────────────────────────
    # Translation
    # ─────────────────────────────────────────────────────────────────────────

    async def to_english(self, text: str) -> Tuple[str, str]:
        """
        Detect language and translate text to English.

        Returns:
            (english_text, lang_code)
            If already English or detection confidence < threshold, returns original.
        """
        if not self._enabled:
            return text, "en"

        lang_code, confidence = self.detect_language(text)

        if lang_code == "en" or confidence < DETECT_CONFIDENCE:
            return text, "en"

        logger.info(
            f"Detected language: {lang_code} (conf={confidence:.2f}) — translating to English"
        )

        translated = await self._translate(text, source=lang_code, target="en")
        return translated, lang_code

    async def from_english(self, text: str, target_lang: str) -> str:
        """
        Translate an English response back to the user's language.

        Returns original text if target_lang == 'en' or translation fails.
        """
        if not self._enabled or target_lang == "en":
            return text

        logger.info(f"Translating response to: {target_lang}")
        return await self._translate(text, source="en", target=target_lang)

    async def _translate(self, text: str, source: str, target: str) -> str:
        """Try translation backends in priority order."""

        # 1. Google Translate
        if GOOGLE_API_KEY:
            result = await self._google_translate(text, source, target)
            if result:
                return result

        # 2. DeepL
        if DEEPL_API_KEY:
            result = await self._deepl_translate(text, source, target)
            if result:
                return result

        # 3. LLM-based translation
        if self._llm:
            result = await self._llm_translate(text, source, target)
            if result:
                return result

        # 4. Passthrough
        logger.warning(f"All translation backends failed — returning original text")
        return text

    # ─────────────────────────────────────────────────────────────────────────
    # Backends
    # ─────────────────────────────────────────────────────────────────────────

    async def _google_translate(self, text: str, source: str, target: str) -> Optional[str]:
        try:
            import httpx

            url = "https://translation.googleapis.com/language/translate/v2"
            params = {"q": text, "source": source, "target": target, "key": GOOGLE_API_KEY}
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                return data["data"]["translations"][0]["translatedText"]
        except Exception as e:
            logger.debug(f"Google Translate error: {e}")
            return None

    async def _deepl_translate(self, text: str, source: str, target: str) -> Optional[str]:
        try:
            import httpx

            url = "https://api-free.deepl.com/v2/translate"
            data = {
                "auth_key": DEEPL_API_KEY,
                "text": text,
                "source_lang": source.upper(),
                "target_lang": target.upper(),
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, data=data)
                resp.raise_for_status()
                return resp.json()["translations"][0]["text"]
        except Exception as e:
            logger.debug(f"DeepL error: {e}")
            return None

    async def _llm_translate(self, text: str, source: str, target: str) -> Optional[str]:
        try:
            source_name = LANGUAGE_NAMES.get(source, source)
            target_name = LANGUAGE_NAMES.get(target, target)
            prompt = (
                f"Translate the following text from {source_name} to {target_name}. "
                f"Return ONLY the translated text, no explanations.\n\n"
                f"Text:\n{text}"
            )
            response = await self._llm.generate(prompt)
            if response and len(response) > 2:
                return response.strip()
            return None
        except Exception as e:
            logger.debug(f"LLM translate error: {e}")
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # Utility
    # ─────────────────────────────────────────────────────────────────────────

    def supported_languages(self):
        return list(LANGUAGE_NAMES.keys())

    def language_name(self, code: str) -> str:
        return LANGUAGE_NAMES.get(code, code)
