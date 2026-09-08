"""Upload content validation and scanner behavior tests."""

import io
import zipfile

import pytest

from termnova.config import Settings
from termnova.security.intake import MalwareScanner, validate_content_type


def _docx_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<document />")
    return output.getvalue()


def test_content_validation_checks_structure_not_only_extension():
    assert validate_content_type("agreement.pdf", b"%PDF-1.7\n") == "application/pdf"
    assert "wordprocessingml" in validate_content_type("agreement.docx", _docx_bytes())
    assert validate_content_type("notes.txt", b"valid text") == "text/plain"

    with pytest.raises(ValueError, match="does not match PDF"):
        validate_content_type("malware.pdf", b"MZ executable")
    with pytest.raises(ValueError, match="NUL"):
        validate_content_type("bad.txt", b"text\x00binary")


@pytest.mark.asyncio
async def test_disabled_scanner_is_explicitly_reported():
    result = await MalwareScanner(Settings(MALWARE_SCAN_MODE="disabled")).scan(b"safe")
    assert result.clean is True
    assert result.engine == "disabled"
