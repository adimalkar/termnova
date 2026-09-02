"""Language normalization boundary used by ingestion and future translation providers."""

import unicodedata


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
    ascii_letters = sum(ord(c) < 128 for c in letters)
    if ascii_letters / len(letters) >= 0.8:
        return "en", round(ascii_letters / len(letters), 3)
    return "und", 0.0


class TranslationProvider:
    """Interface boundary; implementations must preserve source offsets and provider provenance."""

    async def translate(self, text: str, source_language: str, target_language: str) -> str:
        raise NotImplementedError
