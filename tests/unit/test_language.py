"""Language-service boundary tests."""

from termnova.language import detect_language, normalize_text


def test_detects_script_languages_conservatively():
    assert detect_language("This agreement governs cloud services.")[0] == "en"
    assert detect_language("Настоящее соглашение регулирует услуги.")[0] == "ru"
    assert detect_language("")[0] == "und"


def test_normalization_preserves_text_in_nfc():
    assert normalize_text("Cafe\u0301") == "Café"
