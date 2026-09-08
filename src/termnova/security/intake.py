"""Fail-closed upload type validation and optional ClamAV scanning."""

from __future__ import annotations

import asyncio
import io
import socket
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from termnova.config import Settings

MIME_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


@dataclass(frozen=True, slots=True)
class ScanResult:
    clean: bool
    engine: str
    details: str


def validate_content_type(filename: str, content: bytes) -> str:
    """Validate file structure instead of trusting the extension or HTTP header."""
    extension = Path(filename).suffix.lower()
    if extension not in MIME_BY_EXTENSION:
        raise ValueError("Unsupported file extension")
    if extension == ".pdf" and not content.startswith(b"%PDF-"):
        raise ValueError("File extension does not match PDF content")
    if extension == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise ValueError("DOCX package is missing required entries")
        except zipfile.BadZipFile as exc:
            raise ValueError("File extension does not match DOCX content") from exc
    if extension in {".txt", ".md"}:
        if b"\x00" in content:
            raise ValueError("Text uploads cannot contain NUL bytes")
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Text uploads must be valid UTF-8") from exc
    return MIME_BY_EXTENSION[extension]


class MalwareScanner:
    """Scan bytes using ClamAV INSTREAM without placing files on a shared disk."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def scan(self, content: bytes) -> ScanResult:
        if self.settings.MALWARE_SCAN_MODE == "disabled":
            return ScanResult(clean=True, engine="disabled", details="scanner disabled")
        return await asyncio.to_thread(self._scan_clamav, content)

    def _scan_clamav(self, content: bytes) -> ScanResult:
        with socket.create_connection(
            (self.settings.CLAMAV_HOST, self.settings.CLAMAV_PORT),
            timeout=self.settings.CLAMAV_TIMEOUT_SECONDS,
        ) as connection:
            connection.sendall(b"zINSTREAM\0")
            for offset in range(0, len(content), 64 * 1024):
                chunk = content[offset : offset + 64 * 1024]
                connection.sendall(struct.pack("!I", len(chunk)) + chunk)
            connection.sendall(struct.pack("!I", 0))
            response = connection.recv(4096).decode("utf-8", errors="replace").strip("\0\r\n")
        if response.endswith("OK"):
            return ScanResult(clean=True, engine="clamav", details=response)
        if "FOUND" in response:
            return ScanResult(clean=False, engine="clamav", details=response)
        raise RuntimeError(f"Malware scanner returned an indeterminate result: {response}")
