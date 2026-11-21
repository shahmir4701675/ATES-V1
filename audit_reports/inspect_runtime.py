import json,sys,platform,importlib.metadata as md
from pathlib import Path
from backend.models import Base
from backend.main import create_app
out={'python':platform.python_version(),'packages':{},'unindexed_foreign_keys':[],'tables':[]}
for n in ['ortools','networkx','sqlalchemy','fastapi','pytest','uvicorn','httpx']:
 out['packages'][n]=md.version(n)
for t in Base.metadata.sorted_tables:
 out['tables'].append({'name':t.name,'columns':list(t.columns.keys()),'foreign_keys':[{'column':fk.parent.name,'target':fk.target_fullname,'ondelete':fk.ondelete} for fk in t.foreign_keys],'checks':[str(c.sqltext) for c in t.constraints if hasattr(c,'sqltext')]})
 cover=[list(i.columns.keys()) for i in t.indexes]+[list(c.columns.keys()) for c in t.constraints if c.__class__.__name__ in ('UniqueConstraint','PrimaryKeyConstraint')]
 for fk in t.foreign_keys:
  if not any(x and x[0]==fk.parent.name for x in cover):out['unindexed_foreign_keys'].append(t.name+'.'+fk.parent.name)
out['routes']=[{'path':p,'methods':sorted(v.keys())} for p,v in create_app().openapi()['paths'].items()]
Path('audit_reports/runtime_inventory.json').write_text(json.dumps(out,indent=2),encoding='utf8')
print(json.dumps({'python':out['python'],'packages':out['packages'],'unindexed_foreign_keys':out['unindexed_foreign_keys'],'tables':len(out['tables']),'routes':len(out['routes'])},indent=2))
