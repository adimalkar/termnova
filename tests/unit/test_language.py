"""Language-service boundary tests."""

from termnova.language import detect_language, normalize_text


def test_detects_script_languages_conservatively():
    assert detect_language("This agreement governs cloud services.")[0] == "en"
    assert detect_language("Настоящее соглашение регулирует услуги.")[0] == "ru"
    assert detect_language("")[0] == "und"


def test_normalization_preserves_text_in_nfc():
    assert normalize_text("Cafe\u0301") == "Café"


def test_detects_common_latin_script_contract_languages():
    assert (
        detect_language("El contrato establece que las partes deberán efectuar el pago.")[0] == "es"
    )
    assert (
        detect_language("Le contrat prévoit que les parties devront effectuer le paiement.")[0]
        == "fr"
    )
    assert detect_language("Der Vertrag regelt die Zahlung und die Parteien.")[0] == "de"
