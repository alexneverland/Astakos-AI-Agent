"""Exercise the native PDF writer and ReportLab's default resource boundary offline."""
from pathlib import Path
from typing import Any
import urllib.request

import pytest
from pypdf import PdfReader

from astakos_skills import file_generator


@pytest.fixture
def pdf_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep localization independent from document-generation assertions."""
    monkeypatch.setattr(file_generator, 't', lambda key, **kwargs: key)


def test_native_pdf_preserves_sections_and_literal_body(tmp_path: Path, pdf_messages: None) -> None:
    """Read the actual generated PDF, including escaped body markup."""
    output = tmp_path / 'sections.pdf'
    content = '## Section One\n- Item One\n\nA <b>literal</b> & text\n<img src="https://example.invalid/image.png"/>'
    result = file_generator.generate_pdf.func(output_path=str(output), content=content, title='Audit')
    assert result == 'skills.file_generator.msg_pdf_success'
    extracted = '\n'.join(page.extract_text() for page in PdfReader(output).pages)
    for expected in ('Section One', 'Item One', 'A <b>literal</b> & text', 'example.invalid'):
        assert expected in extracted


def test_native_pdf_preserves_unicode_metadata(tmp_path: Path, pdf_messages: None) -> None:
    """Unicode metadata survives the native writer without using unsafe evaluators."""
    output = tmp_path / 'metadata.pdf'
    result = file_generator.generate_pdf.func(output_path=str(output), content='Document body',
                                             title='Τίτλος Αστακού', author='Λάζαρος')
    assert result == 'skills.file_generator.msg_pdf_success'
    reader = PdfReader(output)
    assert reader.metadata.title == 'Τίτλος Αστακού'
    assert reader.metadata.author == 'Λάζαρος'
    assert 'Document body' in reader.pages[0].extract_text()


def test_native_pdf_paginates_without_losing_content(tmp_path: Path, pdf_messages: None) -> None:
    """A multi-page native document retains both ends of the supplied content."""
    output = tmp_path / 'pages.pdf'
    content = '\n'.join(f'Entry {index:04d}: compatibility audit text.' for index in range(200))
    result = file_generator.generate_pdf.func(output_path=str(output), content=content)
    assert result == 'skills.file_generator.msg_pdf_success'
    reader = PdfReader(output)
    assert len(reader.pages) > 1
    extracted = '\n'.join(page.extract_text() for page in reader.pages)
    for index in range(200):
        assert f'Entry {index:04d}:' in extracted


@pytest.mark.parametrize('placement', ['title', 'heading'])
def test_native_pdf_blocks_untrusted_remote_image_before_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pdf_messages: None, placement: str,
) -> None:
    """The upgraded default denies remote images even in interpreted title/header markup."""
    attempts: list[str] = []

    def deny(*args: Any, **kwargs: Any) -> None:
        attempts.append('transport')
        raise RuntimeError('Network transport is forbidden in this offline test')

    monkeypatch.setattr(urllib.request, 'urlopen', deny)
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', deny)
    image = '<img src="https://example.invalid/image.png"/>'
    output = tmp_path / 'blocked.pdf'
    result = file_generator.generate_pdf.func(
        output_path=str(output), title=image if placement == 'title' else 'Safe title',
        content=('## ' + image) if placement == 'heading' else 'Safe body',
    )
    assert result == 'skills.file_generator.msg_pdf_error'
    assert attempts == [], 'Remote image reached transport instead of the default trust boundary'
