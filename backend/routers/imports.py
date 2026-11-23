"""Real staged CSV upload/confirmation, persisted outside the web root in SQL."""
import csv, io, json, secrets
from datetime import timedelta
from typing import Literal
from fastapi import APIRouter,Depends,File,HTTPException,UploadFile,Response,Query
from pydantic import BaseModel,ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend import models as m
from backend.auth import utc_now
from backend.dependencies import get_db,CurrentUser,require_roles
from backend.csv_imports import MAX_BYTES,HEADERS,MODELS,parse_csv,validate_rows
from backend.schedule_integrity import lock_inputs,canonical

router=APIRouter(prefix='/import',tags=['CSV imports'])


class ConfirmImport(BaseModel):
    model_config=ConfigDict(extra='forbid')
    mode:Literal['valid_only','cancel']


def owned_stage(db,stage_id,user):
    stage=db.get(m.ImportStage,stage_id,populate_existing=True)
    if stage is None:raise HTTPException(404,'Import preview not found.')
    if stage.user_id!=user.user_id:raise HTTPException(403,'This import preview belongs to another Coordinator.')
    return stage


def public_report(stage):
    try: report=json.loads(stage.report_json)
    except (ValueError,TypeError):raise HTTPException(409,'Import preview is corrupted.') from None
    return dict(import_id=stage.stage_id,type=stage.entity_type,file_name=stage.file_name,
                rows_rejected=report['rows_total']-report['rows_valid'],
                **{k:report[k] for k in ('rows_total','rows_valid','rejected')})


@router.get('/history')
def history(db:Session=Depends(get_db),user:CurrentUser=Depends(require_roles('Coordinator','Administrator')),
            page:int=Query(1,ge=1),page_size:int=Query(200,ge=1,le=200)):
    stmt=select(m.ImportLog)
    if user.role=='Coordinator':stmt=stmt.where(m.ImportLog.user_id==user.user_id)
    rows=db.scalars(stmt.order_by(m.ImportLog.import_id.desc()).offset((page-1)*page_size).limit(page_size)).all()
    return [dict(import_id=row.import_id,user_id=row.user_id,entity_type=row.entity_type,file_name=row.file_name,
                 rows_total=row.rows_total,rows_imported=row.rows_imported,rows_rejected=row.rows_rejected,
                 imported_at=row.imported_at.isoformat()+'Z') for row in rows]


@router.get('/preview/{stage_id}')
def preview(stage_id:str,db:Session=Depends(get_db),user:CurrentUser=Depends(require_roles('Coordinator'))):
    stage=owned_stage(db,stage_id,user)
    if stage.state=='Preview' and stage.expires_at<=utc_now():raise HTTPException(409,'Import preview expired; upload again.')
    return public_report(stage)


@router.post('/preview/{stage_id}/confirm')
def confirm(stage_id:str,payload:ConfirmImport,db:Session=Depends(get_db),user:CurrentUser=Depends(require_roles('Coordinator'))):
    lock_inputs(db)
    stage=owned_stage(db,stage_id,user)
    if stage.state!='Preview':
        if stage.state=='Confirmed' and payload.mode=='valid_only':
            log=db.get(m.ImportLog,stage.import_id)
            return dict(rows_imported=log.rows_imported,rows_rejected=log.rows_rejected)
        raise HTTPException(409,'The preview has already been confirmed or cancelled.')
    if stage.expires_at<=utc_now():raise HTTPException(409,'Import preview expired; upload again.')
    try:stored=json.loads(stage.report_json);rows=json.loads(stage.rows_json)
    except (TypeError,ValueError):raise HTTPException(409,'Import preview is corrupted.') from None
    total=stored['rows_total']
    if payload.mode=='valid_only':
        current=validate_rows(db,stage.entity_type,rows)
        if current!=stored:raise HTTPException(409,'Import inputs changed after preview; upload again to review current validation.')
        if not current['accepted']:raise HTTPException(422,'No valid rows are available to import.')
        for record in current['accepted']:db.add(MODELS[stage.entity_type](**record['values']))
        imported=len(current['accepted']);rejected=total-imported;stage.state='Confirmed'
    else:imported=0;rejected=total;stage.state='Cancelled'
    log=m.ImportLog(user_id=user.user_id,entity_type=stage.entity_type,file_name=stage.file_name,rows_total=total,rows_imported=imported,rows_rejected=rejected)
    db.add(log);db.flush()
    stage.import_id=log.import_id;stage.rows_json='[]'
    db.add(m.AuditLog(user_id=user.user_id,action='IMPORT' if payload.mode=='valid_only' else 'IMPORT_CANCELLED',entity_type='import_logs',entity_id=log.import_id))
    db.commit()
    return dict(rows_imported=imported,rows_rejected=rejected)


@router.get('/{kind}/template')
def template(kind:str,user:CurrentUser=Depends(require_roles('Coordinator'))):
    if kind not in HEADERS:raise HTTPException(404,'Unsupported import type.')
    return Response(HEADERS[kind]+'\r\n',media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="{kind}-template.csv"','Cache-Control':'no-store'})


@router.post('/{kind}')
def upload(kind:str,file:UploadFile=File(...),db:Session=Depends(get_db),user:CurrentUser=Depends(require_roles('Coordinator'))):
    if kind not in HEADERS:raise HTTPException(404,'Unsupported import type.')
    name=(file.filename or '').replace('\\','/').rsplit('/',1)[-1]
    if not name.lower().endswith('.csv') or len(name)>120:raise HTTPException(422,'Upload a CSV file with a filename of at most 120 characters.')
    try: content=file.file.read(MAX_BYTES+1)
    finally:file.file.close()
    if len(content)>MAX_BYTES:raise HTTPException(413,'CSV file exceeds the 10 MB limit.')
    try:rows=parse_csv(content,kind)
    except (UnicodeError,ValueError,csv.Error) as exc:raise HTTPException(422,f'Invalid UTF-8 CSV: {exc}') from None
    lock_inputs(db)
    report=validate_rows(db,kind,rows)
    stage=m.ImportStage(stage_id=secrets.token_hex(24),user_id=user.user_id,entity_type=kind,file_name=name,state='Preview',
                        rows_json=canonical(rows),report_json=canonical(report),expires_at=utc_now()+timedelta(hours=1))
    db.add(stage)
    db.add(m.AuditLog(user_id=user.user_id,action='IMPORT_PREVIEW',entity_type='import_stages',details=stage.stage_id))
    db.commit()
    return public_report(stage)


class ImportBodyLimit:
    """Bound actual streamed multipart bytes before parsing/spooling arbitrary uploads."""
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        path=scope.get('path','').removeprefix('/api')
        if scope['type']!='http' or scope.get('method')!='POST' or path not in {'/import/'+kind for kind in HEADERS}:
            return await self.app(scope,receive,send)
        consumed=0
        async def limited():
            nonlocal consumed
            message=await receive();consumed+=len(message.get('body',b''))
            if consumed>MAX_BYTES+65536:raise HTTPException(413,'Multipart upload exceeds the 10 MB CSV limit.')
            return message
        await self.app(scope,limited,send)
