import pytest
import pandas as pd
import zipfile
from core.utils import extract_xlsx_preview
from core.i18n import t

def test_xlsx_preview_narrow_sheet(tmp_path):
    file_path = tmp_path / 'narrow.xlsx'
    df = pd.DataFrame({'SingleCol': [1, 2]})
    df.to_excel(file_path, index=False)

    preview = extract_xlsx_preview(str(file_path), max_chars=16000)
    assert 'SingleCol' in preview
    assert '1' in preview

def test_xlsx_preview_wide_sheet(tmp_path):
    file_path = tmp_path / 'wide.xlsx'
    # 25 columns
    df = pd.DataFrame({f'Col{i}': [1, 2] for i in range(25)})
    df.to_excel(file_path, index=False)

    preview = extract_xlsx_preview(str(file_path), max_chars=16000)
    assert 'Col19' in preview
    assert 'Col20' not in preview # 0-indexed, so 20 is the 21st column

def test_xlsx_huge_cell(tmp_path):
    file_path = tmp_path / 'huge.xlsx'
    df = pd.DataFrame({'Col0': ['A' * 20000]})
    df.to_excel(file_path, index=False)

    preview = extract_xlsx_preview(str(file_path), max_chars=16000)
    assert len(preview) <= 16000
    assert 'A' * 100 not in preview

def test_xlsx_preview_clipping(tmp_path):
    file_path = tmp_path / 'clip.xlsx'
    df = pd.DataFrame({'Col0': ['HelloWorld' * 5]}) # 50 chars data + header
    df.to_excel(file_path, index=False)

    max_chars = 30
    preview = extract_xlsx_preview(str(file_path), max_chars=max_chars)
    assert len(preview) <= max_chars

    clip_msg = "\n" + t("api.server.xlsx_preview_clipped")
    # For a small max_chars like 30, it will be truncated.
    # We check if the end of the preview matches the start of the clip_msg
    # It should have omitted "HelloWorld" since it's cut off early
    assert "HelloWorldHelloWorld" not in preview

    # We know preview ends with some prefix of clip_msg.
    assert clip_msg[:10] in preview

def test_malformed_xlsx(tmp_path):
    file_path = tmp_path / 'bad.xlsx'
    file_path.write_text('not a zip file')

    preview = extract_xlsx_preview(str(file_path), max_chars=16000)
    assert t('api.server.xlsx_corrupt') in preview or t('api.server.xlsx_unreadable_generic') in preview

def test_zip_bomb_metadata(tmp_path, monkeypatch):
    file_path = tmp_path / 'bomb.xlsx'
    with zipfile.ZipFile(file_path, 'w') as z:
        z.writestr('test.xml', 'test')

    def mocked_infolist(self):
        class MockInfo:
            file_size = 60_000_000
        return [MockInfo()]

    monkeypatch.setattr(zipfile.ZipFile, 'infolist', mocked_infolist)

    pandas_called = False
    def mock_read_excel(*args, **kwargs):
        nonlocal pandas_called
        pandas_called = True
        return pd.DataFrame()

    monkeypatch.setattr(pd, 'read_excel', mock_read_excel)

    preview = extract_xlsx_preview(str(file_path), max_chars=16000)
    assert t('api.server.xlsx_oversized_uncompressed') in preview
    assert not pandas_called

def test_xls_path(tmp_path, monkeypatch):
    file_path = tmp_path / 'test.xls'

    class MockExcelFile:
        def __init__(self, path):
            self.sheet_names = ['Sheet1']
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(pd, 'ExcelFile', MockExcelFile)
    monkeypatch.setattr(pd, 'read_excel', lambda *a, **kw: pd.DataFrame({'A': [1]}))

    zip_called = False
    def mock_zip(*args, **kwargs):
        nonlocal zip_called
        zip_called = True
        return zipfile.ZipFile(*args, **kwargs)

    monkeypatch.setattr(zipfile, 'ZipFile', mock_zip)
    file_path.write_bytes(b'dummy')

    preview = extract_xlsx_preview(str(file_path), max_chars=16000)
    assert not zip_called
    assert 'Sheet1' in preview

def test_integration_max_chars():
    from pathlib import Path
    server_src = Path('api/server.py').read_text(encoding='utf-8')
    telegram_src = Path('clients/telegram_bot.py').read_text(encoding='utf-8')

    assert 'extract_xlsx_preview(file_path, max_chars=16000)' in server_src
    assert 'extract_xlsx_preview(local_path, max_chars=8000)' in telegram_src
