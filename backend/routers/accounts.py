"""Administrator account administration and append-only audit retrieval (B011)."""
from datetime import date, datetime, time, timedelta
import re
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator
from sqlalchemy import delete, func, select, or_, cast, String
from sqlalchemy.orm import Session
from backend.auth import hash_password
from backend.dependencies import CurrentUser, get_db, require_roles
from backend.models import User, Instructor, Batch, AuthSession, AuditLog
from backend.routers.auth import AuthUserResponse
from backend.schedule_integrity import lock_inputs

router=APIRouter(tags=['Accounts and audit'])
Role=Literal['Administrator','Coordinator','Approver','Faculty','Student']
Status=Literal['Active','Locked','Deactivated']


class AccountCore(BaseModel):
    model_config=ConfigDict(extra='forbid')
    username: str=Field(min_length=1,max_length=40)
    full_name: str=Field(min_length=1,max_length=100)
    email: str=Field(min_length=3,max_length=120)
    role: Role
    account_status: Status='Active'
    instructor_id: int | None=None
    batch_id: int | None=None

    @field_validator('username','full_name','email')
    @classmethod
    def clean(cls,value,info):
        value=value.strip()
        if not value or (info.field_name=='email' and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value)):
            raise ValueError('A valid nonempty value is required.')
        return value


class AccountCreate(AccountCore):
    password: SecretStr


class AccountUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    username: str | None=None
    full_name: str | None=None
    email: str | None=None
    role: Role | None=None
    account_status: Status | None=None
    instructor_id: int | None=None
    batch_id: int | None=None
    password: SecretStr | None=None


class PasswordReset(BaseModel):
    model_config=ConfigDict(extra='forbid')
    password: SecretStr


def secure_hash(secret):
    try: return hash_password(secret.get_secret_value())
    except ValueError as exc: raise HTTPException(422,str(exc)) from None


def validate_links(db,values):
    role=values['role']
    for field,required,model in [('instructor_id','Faculty',Instructor),('batch_id','Student',Batch)]:
        identity=values[field]
        if role==required:
            linked=db.get(model,identity) if identity is not None else None
            if linked is None or (values['account_status']=='Active' and not linked.is_active):
                raise HTTPException(422,f'{required} requires a valid active {field} link.')
        elif identity is not None:
            raise HTTPException(422,f'{field} is only valid for role {required}.')


def audit(db,actor,action,uid,fields=None):
    # Record field names only. Never serialize passwords, hashes or tokens.
    db.add(AuditLog(user_id=actor.user_id,action=action,entity_type='users',entity_id=uid,
                    details=', '.join(sorted(fields or []))))


@router.get('/users',response_model=list[AuthUserResponse])
def users(response:Response,db:Session=Depends(get_db),user:CurrentUser=Depends(require_roles('Administrator')),
          page:int=Query(1,ge=1),page_size:int=Query(200,ge=1,le=200),q:str=Query('',max_length=200),
          sort:Literal['user_id','username','name','email','role','status']='user_id',direction:Literal['asc','desc']='asc'):
    response.headers['Cache-Control']='no-store'
    stmt=select(User)
    if q.strip():
        stmt=stmt.where(or_(*(column.icontains(q.strip(),autoescape=True) for column in (cast(User.user_id,String),User.username,User.full_name,User.email,User.role,User.account_status))))
    response.headers['X-Total-Count']=str(db.scalar(select(func.count()).select_from(stmt.subquery())))
    column={'user_id':User.user_id,'username':User.username,'name':User.full_name,'email':User.email,'role':User.role,'status':User.account_status}[sort]
    return db.scalars(stmt.order_by(column.desc() if direction=='desc' else column.asc(),User.user_id).offset((page-1)*page_size).limit(page_size)).all()


@router.post('/users',response_model=AuthUserResponse,status_code=201)
def create_user(payload:AccountCreate,db:Session=Depends(get_db),user:CurrentUser=Depends(require_roles('Administrator'))):
    values=payload.model_dump(exclude={'password'});validate_links(db,values)
    row=User(**values,password_hash=secure_hash(payload.password))
    db.add(row);db.flush();audit(db,user,'CREATE_ACCOUNT',row.user_id,values)
    db.commit();return row


@router.put('/users/{user_id}',response_model=AuthUserResponse)
def update_user(user_id:int,payload:AccountUpdate,db:Session=Depends(get_db),user:CurrentUser=Depends(require_roles('Administrator'))):
    lock_inputs(db)
    row=db.get(User,user_id,populate_existing=True)
    if row is None: raise HTTPException(404,'Account not found.')
    changes=payload.model_dump(exclude_unset=True,exclude={'password'})
    values={field:getattr(row,field) for field in AccountCore.model_fields}
    values.update(changes)
    if 'role' in changes:
        if values['role']!='Faculty' and 'instructor_id' not in changes: values['instructor_id']=None
        if values['role']!='Student' and 'batch_id' not in changes: values['batch_id']=None
    try: values=AccountCore.model_validate(values).model_dump()
    except ValidationError: raise HTTPException(422,'Invalid account fields or role.') from None
    validate_links(db,values)
    if row.role=='Administrator' and row.account_status=='Active' and (values['role']!='Administrator' or values['account_status']!='Active'):
        count=db.scalar(select(func.count()).select_from(User).where(User.role=='Administrator',User.account_status=='Active'))
        if count<=1: raise HTTPException(409,'The last active Administrator must remain active.')
    sensitive=any(values[k]!=getattr(row,k) for k in ('role','account_status','instructor_id','batch_id'))
    for field,value in values.items():setattr(row,field,value)
    if 'account_status' in changes:row.failed_attempts=0;row.locked_until=None
    if payload.password is not None:
        row.password_hash=secure_hash(payload.password);sensitive=True
        audit(db,user,'RESET_PASSWORD',user_id)
    if sensitive:db.execute(delete(AuthSession).where(AuthSession.user_id==user_id))
    audit(db,user,'UPDATE_ACCOUNT',user_id,changes)
    db.commit();return row


@router.post('/users/{user_id}/password',status_code=204)
def reset_password(user_id:int,payload:PasswordReset,db:Session=Depends(get_db),user:CurrentUser=Depends(require_roles('Administrator'))):
    row=db.get(User,user_id)
    if row is None:raise HTTPException(404,'Account not found.')
    row.password_hash=secure_hash(payload.password)
    db.execute(delete(AuthSession).where(AuthSession.user_id==user_id))
    audit(db,user,'RESET_PASSWORD',user_id);db.commit()
    return Response(status_code=204,headers={'Cache-Control':'no-store'})


@router.get('/audit')
def audit_log(response:Response,db:Session=Depends(get_db),user:CurrentUser=Depends(require_roles('Administrator')),
              user_id:int | None=None,action:str | None=Query(None,max_length=40),
              from_date:date | None=Query(None,alias='from'),to_date:date | None=Query(None,alias='to'),
              page:int=Query(1,ge=1),page_size:int=Query(200,ge=1,le=200),q:str=Query('',max_length=200),
              sort:Literal['time','user','action','entity','details']='time',direction:Literal['asc','desc']='desc'):
    if from_date and to_date and from_date>to_date:raise HTTPException(422,'Date range is reversed.')
    stmt=select(AuditLog,User.username).outerjoin(User,User.user_id==AuditLog.user_id)
    if user_id is not None:stmt=stmt.where(AuditLog.user_id==user_id)
    if action:stmt=stmt.where(AuditLog.action==action)
    if from_date:stmt=stmt.where(AuditLog.created_at>=datetime.combine(from_date,time.min))
    if to_date:stmt=stmt.where(AuditLog.created_at<datetime.combine(to_date,time.min)+timedelta(days=1))
    if q.strip():
        stmt=stmt.where(or_(*(column.icontains(q.strip(),autoescape=True) for column in (func.coalesce(User.username,'Unknown'),AuditLog.action,AuditLog.entity_type,AuditLog.details))))
    response.headers['Cache-Control']='no-store'
    response.headers['X-Total-Count']=str(db.scalar(select(func.count()).select_from(stmt.subquery())))
    column={'time':AuditLog.created_at,'user':User.username,'action':AuditLog.action,'entity':AuditLog.entity_type,'details':AuditLog.details}[sort]
    return [dict(log_id=row.log_id,user_id=row.user_id,username=name or 'Unknown',action=row.action,
                 entity_type=row.entity_type,entity_id=row.entity_id,details=row.details or '',created_at=row.created_at.isoformat()+'Z')
            for row,name in db.execute(stmt.order_by(column.desc() if direction=='desc' else column.asc(),AuditLog.log_id.desc()).offset((page-1)*page_size).limit(page_size))]


@router.get('/audit/actions', response_model=list[str])
def audit_actions(db:Session=Depends(get_db),user:CurrentUser=Depends(require_roles('Administrator'))):
    return list(db.scalars(select(AuditLog.action).distinct().order_by(AuditLog.action)))
