"""Language normalization and optional source-preserving translation providers."""

import re
import unicodedata
from dataclasses import dataclass

from termnova.config import Settings, get_settings


def normalize_text(text: str) -> str:
    """Normalize source text without changing its evidentiary wording."""
    return unicodedata.normalize("NFC", text)


def detect_language(text: str) -> tuple[str, float]:
    """Return a conservative BCP-47 language tag from Unicode script evidence."""
    sample = normalize_text(text[:10000])
    letters = [character for character in sample if character.isalpha()]
    if not letters:
        return "und", 0.0
    script_counts = {
        "ar": sum("ARABIC" in unicodedata.name(c, "") for c in letters),
        "ru": sum("CYRILLIC" in unicodedata.name(c, "") for c in letters),
        "zh": sum("CJK" in unicodedata.name(c, "") for c in letters),
        "ja": sum(
            "HIRAGANA" in unicodedata.name(c, "") or "KATAKANA" in unicodedata.name(c, "")
            for c in letters
        ),
    }
    language, count = max(script_counts.items(), key=lambda item: item[1])
    if count / len(letters) >= 0.3:
        return language, round(count / len(letters), 3)
    words = set(re.findall(r"[a-zà-ÿ]+", sample.lower()))
    markers = {
        "es": {"el", "la", "las", "los", "deberá", "contrato", "partes", "pago"},
        "fr": {"le", "la", "les", "des", "devra", "contrat", "parties", "paiement"},
        "de": {"der", "die", "das", "und", "vertrag", "parteien", "zahlung", "muss"},
        "pt": {"o", "a", "os", "as", "deverá", "contrato", "partes", "pagamento"},
        "it": {"il", "la", "le", "deve", "contratto", "parti", "pagamento"},
    }
    scores = {tag: len(words & vocabulary) for tag, vocabulary in markers.items()}
    latin_language, marker_count = max(scores.items(), key=lambda item: item[1])
    if marker_count >= 2:
        return latin_language, min(0.95, round(0.55 + marker_count * 0.05, 3))
    ascii_letters = sum(ord(c) < 128 for c in letters)
    if ascii_letters / len(letters) >= 0.8:
        return "en", round(ascii_letters / len(letters), 3)
    return "und", 0.0


@dataclass(frozen=True)
class TranslationResult:
    text: str
    provider: str
    model: str
    confidence: float | None = None


class TranslationProvider:
    """Interface boundary; implementations must preserve source offsets and provider provenance."""

    async def translate(
        self,
        text: str,
        source_language: str,
        target_language: str,
        glossary: dict[str, str] | None = None,
    ) -> TranslationResult:
        raise NotImplementedError


class LLMTranslationProvider(TranslationProvider):
    """Use the configured bounded LLM route for an explicitly requested translation."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    async def translate(
        self,
        text: str,
        source_language: str,
        target_language: str,
        glossary: dict[str, str] | None = None,
    ) -> TranslationResult:
        from termnova.llm_client import acompletion_with_fallback

        glossary_lines = "\n".join(
            f"- {source}: {target}" for source, target in (glossary or {}).items()
        )
        response = await acompletion_with_fallback(
            [
                {
                    "role": "system",
                    "content": (
                        "Translate legal contract text faithfully. Preserve names, numbers, dates, "
                        "defined terms, paragraph boundaries, and modality. Do not summarize, "
                        "interpret, or add commentary. Return only the translation."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Source language: {source_language}\nTarget language: {target_language}\n"
                        f"Approved terminology:\n{glossary_lines or '(none)'}\n\nText:\n{text}"
                    ),
                },
            ],
            settings=self.settings,
            temperature=0,
        )
        translated = response.choices[0].message.content
        if not translated or not translated.strip():
            raise RuntimeError("Translation provider returned empty content")
        model = str(getattr(response, "model", self.settings.LLM_MODEL))
        return TranslationResult(
            text=normalize_text(translated.strip()),
            provider=self.settings.LLM_PROVIDER,
            model=model,
            confidence=None,
        )
