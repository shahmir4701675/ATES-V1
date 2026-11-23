"""B010 real downloadable bytes, independent CSV/PDF inspection and export scope."""
import csv,io,os
from pathlib import Path
from pypdf import PdfReader
import pytest
from sqlalchemy import select
from backend import models as m
from tests.test_batch1_generation import batch_template,env
from tests.test_schedule_integrity import freeze


@pytest.mark.parametrize('sid',[1,2])
@pytest.mark.parametrize('format',['csv','pdf'])
def test_real_export_content_and_audit_use_authoritative_context(env,sid,format):
    client,factory,_=env;freeze(factory,sid,True)
    with factory.begin() as s:s.get(m.Room,1).room_code='CHANGED-CURRENT-ROOM'
    response=client.get(f'/schedules/{sid}/export',params={'format':format})
    assert response.status_code==200,response.text[:200]
    assert f'.{format}' in response.headers['content-disposition']
    if format=='csv':
        assert 'text/csv' in response.headers['content-type']
        rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
        assert len(rows)==(26 if sid==1 else 5)
        assert all(r['term'] and r['version']=='1' and r['generated_at'] for r in rows)
        assert 'CHANGED-CURRENT-ROOM' not in response.text
        if sid==2:assert all(r['exam_date'] and r['student_count'] and r['room'] for r in rows)
    else:
        assert response.headers['content-type']=='application/pdf'
        reader=PdfReader(io.BytesIO(response.content))
        if os.environ.get('ATES_EXPORT_QA'):
            folder=Path(os.environ['ATES_EXPORT_QA']);folder.mkdir(parents=True,exist_ok=True)
            (folder/f'schedule-{sid}.pdf').write_bytes(response.content)
        assert float(reader.pages[0].mediabox.width)>float(reader.pages[0].mediabox.height)
        text='\n'.join(p.extract_text() for p in reader.pages)
        assert 'NED' in text and 'Fall 2026' in text and 'Version 1' in text and 'Generated:' in text
        assert 'CHANGED-CURRENT-ROOM' not in text
    with factory() as s:assert s.scalar(select(m.AuditLog).where(m.AuditLog.action=='EXPORT',m.AuditLog.entity_id==sid)) is not None


@pytest.mark.parametrize('username,scope,identity',[('cs24a_9002','batch_id',1),('fakhra','instructor_id',1)])
@pytest.mark.parametrize('sid',[1,2])
def test_exports_enforce_scope_and_filters(env,login_as,username,scope,identity,sid):
    client,factory,_=env;freeze(factory,sid,True);headers=login_as(client,factory,username)
    view=client.get(f'/schedules/{sid}/entries',headers=headers).json()
    response=client.get(f'/schedules/{sid}/export',headers={**headers,'X-Batch-Id':'2','X-Instructor-Id':'2'},params={'format':'csv'})
    rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
    assert len(rows)==len(view['entries'])
    assert client.get(f'/schedules/{sid}/export',headers=headers,params={'format':'csv',scope:2}).status_code==403
    assert client.get(f'/schedules/{sid}/export',headers=headers,params={'format':'pdf','group_by':'batch'}).status_code==403


@pytest.mark.parametrize('username',['cs24a_9002','fakhra','admin'])
def test_unpublished_export_denied(env,login_as,username):
    client,factory,_=env;headers=login_as(client,factory,username)
    assert client.get('/schedules/1/export',headers=headers,params={'format':'csv'}).status_code==403


@pytest.mark.parametrize('group_by',['batch','instructor'])
def test_coordinator_grouped_pdf_has_one_page_per_scope(env,group_by):
    client,factory,_=env;freeze(factory,1)
    response=client.get('/schedules/1/export',params={'format':'pdf','group_by':group_by})
    assert response.status_code==200,response.text[:100]
    pages=PdfReader(io.BytesIO(response.content)).pages
    if os.environ.get('ATES_EXPORT_QA'):
        (Path(os.environ['ATES_EXPORT_QA'])/f'grouped-{group_by}.pdf').write_bytes(response.content)
    expected=2 if group_by=='batch' else 3
    assert len(pages)==expected
    assert all('Filter:' in page.extract_text() for page in pages)


def test_csv_filtering_formula_safety_and_no_false_audit_on_bad_format(env):
    client,factory,_=env;freeze(factory,1)
    filtered=client.get('/schedules/1/export',params={'format':'csv','day_of_week':1,'batch_id':1})
    rows=list(csv.DictReader(io.StringIO(filtered.content.decode('utf-8-sig'))))
    assert rows and all(r['day']=='Monday' and '24' in r['batch'] for r in rows)
    assert client.get('/schedules/1/export',params={'format':'exe'}).status_code==422
    from backend.schedule_exports import safe_csv
    assert safe_csv('=1+1').startswith("'") and safe_csv('  @SUM(A1)').startswith("'")


def test_anonymous_export_cannot_be_forged(env):
    client,_,_=env;client.headers.clear()
    assert client.get('/schedules/1/export?format=pdf',headers={'X-User-Role':'Coordinator'}).status_code==401


def test_export_filename_is_exposed_to_authenticated_cross_origin_clients(env):
    client,factory,_=env;freeze(factory,1)
    response=client.get('/schedules/1/export?format=csv',headers={'Origin':'http://localhost:5173'})
    assert response.status_code==200
    assert 'Content-Disposition' in response.headers['access-control-expose-headers']


def test_grouped_pdf_keeps_complete_rows_and_long_unicode_labels_on_scope_pages(env):
    client,factory,_=env
    from sqlalchemy import select
    label='Dr. Élodie '+('Nom '*20)
    with factory.begin() as s:
        for instructor in s.scalars(select(m.Instructor)):instructor.full_name=label
    freeze(factory,1)
    response=client.get('/schedules/1/export?format=pdf&group_by=batch')
    reader=PdfReader(io.BytesIO(response.content));assert len(reader.pages)==2
    text=''.join(page.extract_text() for page in reader.pages)
    assert ''.join(label.split()) in ''.join(text.split())
    assert sum(text.count(code) for code in ['CS-326','CS-310','MT-212','CS-318','CS-332'])==26
    if os.environ.get('ATES_EXPORT_QA'):(Path(os.environ['ATES_EXPORT_QA'])/'grouped-long-labels.pdf').write_bytes(response.content)


def test_exam_date_and_room_filters_preserve_complete_allocation(env):
    client,factory,_=env;freeze(factory,2)
    response=client.get('/schedules/2/export',params={'format':'csv','exam_date':'2026-12-14','room_id':1})
    rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
    assert len(rows)==1 and rows[0]['course_code']=='CS-326'
    assert rows[0]['student_count']=='85'
    assert '60 seats' in rows[0]['room'] and '25 seats' in rows[0]['room']
