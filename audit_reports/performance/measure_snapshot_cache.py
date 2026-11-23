"""Read-only microbenchmark using only the prior explicitly disposable QA DB."""
from pathlib import Path
from types import SimpleNamespace
import json
import statistics
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.schedule_integrity import decode_snapshot, _decode_snapshot_uncached, _cached_snapshot


def main():
    metadata = json.loads((ROOT/'audit_reports/final_acceptance/reference_environment.json').read_text())
    folder = Path(metadata['folder']).resolve()
    if folder.parent != Path(tempfile.gettempdir()).resolve() or not folder.name.startswith('ates_acceptance_'):
        raise RuntimeError('Refusing any target outside the known disposable acceptance fixture')
    db = sqlite3.connect((folder/'reference.sqlite').as_uri()+'?mode=ro',uri=True)
    db.row_factory = sqlite3.Row
    row = db.execute('SELECT inputs_json,input_hash,format_version,term_id,schedule_type FROM schedule_snapshots WHERE schedule_id=1').fetchone()
    schedule = db.execute('SELECT term_id,schedule_type,config_id FROM schedules WHERE schedule_id=1').fetchone()
    db.close()
    if row is None:raise RuntimeError('Disposable reference snapshot unavailable; do not substitute user data')
    row, schedule = SimpleNamespace(**dict(row)), SimpleNamespace(**dict(schedule))
    _cached_snapshot.cache_clear()
    decode_snapshot(row,schedule)
    def measure(fn, n):
        values=[]
        for _ in range(n):
            start=time.perf_counter();fn(row,schedule);values.append(time.perf_counter()-start)
        return dict(samples=n,median_s=statistics.median(values),min_s=min(values),max_s=max(values))
    uncached, warm = measure(_decode_snapshot_uncached,5), measure(decode_snapshot,10)
    result=dict(snapshot_bytes=len(row.inputs_json.encode()),uncached=uncached,warm_cached_including_reader_checks_and_deepcopy=warm,
                median_reduction_percent=(1-warm['median_s']/uncached['median_s'])*100,
                cache_info=str(_cached_snapshot.cache_info()),
                scope='Local reference immutable-input decode only, not HTTP latency, validation time, solver speed or a50-user load test. Read-only disposable DB.')
    (ROOT/'audit_reports/performance/snapshot_measurements.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
