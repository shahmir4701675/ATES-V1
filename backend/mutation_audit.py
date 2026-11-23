"""Transaction-local authenticated attribution; logs contain field names, never secrets."""
import json
from sqlalchemy import event,inspect
from sqlalchemy.orm import Session
from backend.models import AuditLog
from backend.snapshot_schema import SOURCES


@event.listens_for(Session,'before_flush')
def collect_mutations(session,context,instances):
    actor=session.info.get('authenticated_actor')
    if actor is None:return
    from backend.input_validation import validate_sources
    validate_sources(session)
    pending=session.info.setdefault('audit_mutations',[])
    for collection,action in [(session.new,'CREATE'),(session.dirty,'UPDATE'),(session.deleted,'DELETE')]:
        for row in list(collection):
            if getattr(row,'__tablename__','') not in SOURCES:continue
            if action=='UPDATE' and not session.is_modified(row,include_collections=False):continue
            fields=[a.key for a in inspect(row).attrs if a.history.has_changes() and a.key in inspect(row).mapper.columns]
            pending.append((row,actor,action,fields))


@event.listens_for(Session,'after_flush_postexec')
def persist_mutations(session,context):
    for row,actor,action,fields in session.info.pop('audit_mutations',[]):
        key=inspect(row).mapper.primary_key[0].key
        session.add(AuditLog(user_id=actor,action=action,entity_type=row.__tablename__,entity_id=getattr(row,key),
                            details=json.dumps({'fields':sorted(fields)},sort_keys=True)))


@event.listens_for(Session,'after_rollback')
def clear_pending(session):session.info.pop('audit_mutations',None)
