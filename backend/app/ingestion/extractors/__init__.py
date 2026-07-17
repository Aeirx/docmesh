"""Extractor dispatch: one entry point, one output shape for every file type."""

from pathlib import Path

from app.ingestion.extractors.base import Block, ExtractedDoc, ExtractionError
from app.schemas.documents import FileType

__all__ = ["Block", "ExtractedDoc", "ExtractionError", "extract_document"]


def extract_document(path: Path, file_type: FileType) -> ExtractedDoc:
    """Sync (extractors do blocking I/O + parsing); the pipeline runs it in a thread."""
    if file_type is FileType.PDF:
        from app.ingestion.extractors import pdf

        return pdf.extract(path)
    if file_type is FileType.DOCX:
        from app.ingestion.extractors import docx

        return docx.extract(path)
    from app.ingestion.extractors import text

    return text.extract(path, is_markdown=file_type is FileType.MD)
