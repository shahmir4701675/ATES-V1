"""Downloadable exports use the same authorization and immutable view as the API."""
from datetime import date
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException,Query,Response
from sqlalchemy.orm import Session
from backend.dependencies import CurrentUser,get_db,require_roles
from backend.models import AuditLog
from backend.routers.schedules import get_schedule_entries
from backend.schedule_exports import csv_bytes,pdf_bytes,export_rows

router=APIRouter(tags=['Schedule exports'])


@router.get('/schedules/{schedule_id}/export')
def export_schedule(schedule_id:int,format:Literal['csv','pdf']=Query('pdf'),
                    batch_id:int | None=Query(None,gt=0),instructor_id:int | None=Query(None,gt=0),
                    room_id:int | None=Query(None,gt=0),course_id:int | None=Query(None,gt=0),
                    day_of_week:int | None=Query(None,ge=1,le=7),exam_date:date | None=None,
                    session_type:Literal['Lecture','Lab'] | None=None,group_by:Literal['batch','instructor'] | None=None,
                    db:Session=Depends(get_db),user:CurrentUser=Depends(require_roles('Coordinator','Approver','Administrator','Faculty','Student'))):
    if group_by and (user.role!='Coordinator' or format!='pdf'):
        raise HTTPException(403 if user.role!='Coordinator' else 422,'Grouped PDFs are available only to Coordinators.')
    filters=dict(batch_id=batch_id,instructor_id=instructor_id,room_id=room_id,course_id=course_id,
                 day_of_week=day_of_week,exam_date=str(exam_date) if exam_date else None,session_type=session_type)
    view=get_schedule_entries(schedule_id,db=db,_user=user,**filters)
    rows=export_rows(view)
    if user.role=='Student':filters['batch_id']=user.batch_id
    if user.role=='Faculty':filters['instructor_id']=user.instructor_id
    filter_text='; '.join(f'{k}={v}' for k,v in filters.items() if v is not None)
    content=csv_bytes(rows) if format=='csv' else pdf_bytes(view,rows,filter_text,group_by)
    db.add(AuditLog(user_id=user.user_id,action='EXPORT',entity_type='schedules',entity_id=schedule_id,
                    details=f'{format}; {filter_text}; group_by={group_by or "none"}; rows={len(rows)}'))
    db.commit()
    filename=f'ates-{view.term_id}-{view.schedule_type.lower()}-v{view.version_no}.{format}'
    return Response(content,media_type='text/csv; charset=utf-8' if format=='csv' else 'application/pdf',
                    headers={'Content-Disposition':f'attachment; filename="{filename}"','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
