"""Published help artifacts are real documents and match the import contract."""
import csv
import json
from pathlib import Path
from pypdf import PdfReader
from backend.csv_imports import HEADERS

ROOT=Path(__file__).resolve().parents[1]/'frontend'


def test_user_manual_and_two_page_quick_start_are_real_readable_pdfs():
    manual=PdfReader(ROOT/'public/help/user-manual.pdf')
    quick=PdfReader(ROOT/'public/help/quick-start.pdf')
    assert len(manual.pages)==5 and len(quick.pages)==2
    text='\n'.join(p.extract_text() for p in manual.pages)
    for role in ['Coordinator','Approver','Faculty','Student','Administrator']:assert role in text
    assert 'screenshots' in text and 'pending' in text
    assert 'Asia/Karachi' in text and 'Publish' in text


def test_help_roles_and_csv_examples_match_real_server_templates():
    helpdata=json.loads((ROOT/'src/locales/help.en.json').read_text(encoding='utf-8'))
    assert set(helpdata['roles'])=={'Coordinator','Approver','Faculty','Student','Administrator'}
    assert len(helpdata['screens'])>=10
    reference=(ROOT/'public/help/csv-fields.md').read_text(encoding='utf-8')
    for kind,header in HEADERS.items():
        rows=list(csv.reader((ROOT/f'public/help/{kind}-example.csv').read_text(encoding='utf-8').splitlines()))
        assert rows[0]==header.split(',') and len(rows[1])==len(rows[0])
        for field in rows[0]:assert f'`{field}`' in reference
