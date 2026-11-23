import { TimetableGrid } from '../components/TimetableGrid'
import { useMemo, useState } from 'react'
import { CheckCircle2, Filter, Info, LockKeyhole, PencilLine, SlidersHorizontal } from 'lucide-react'
import { Button, Card, ExportActions, LoadState, Notice, PageHeader, SelectField, StatusBadge } from '../components/ui'
import { Modal, ConfirmDialog } from '../components/Modal'
import { useAsync } from '../hooks/useAsync'
import { DAY_NAMES } from '../data/reference'
import { errorMessage, exportSchedule, getScheduleEditContext, undoSchedule, getSchedules, getTerms, getTimetable, moveTimetableEntry } from '../services/api'
import type { MoveResult, Room, TimeSlot, TimetableRow } from '../types'
import type { Role } from '../components/AppShell'

type Failure = Extract<MoveResult, { ok: false }>

function MoveDialog({ row, slots, rooms, scheduleId, onClose, onMoved }: { row: TimetableRow; slots: TimeSlot[]; rooms: Room[]; scheduleId: string; onClose: () => void; onMoved: () => void }) {
  const [slotId, setSlotId] = useState(row.startSlot.slot_id)
  const [roomId, setRoomId] = useState(row.room.room_id)
  const [locked, setLocked] = useState(row.entry.is_locked)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<Failure | null>(null)
  const [error, setError] = useState('')
  const free = slots.filter((slot) => !slot.is_blocked || slot.slot_id === row.startSlot.slot_id)
  const unchanged = slotId === row.startSlot.slot_id && roomId === row.room.room_id && locked === row.entry.is_locked
  const submit = async () => {
    setBusy(true); setFailure(null); setError('')
    try {
      const result = await moveTimetableEntry(scheduleId, row.entry.entry_id, { slot_id: slotId === row.startSlot.slot_id ? undefined : slotId, room_id: roomId === row.room.room_id ? undefined : roomId, is_locked: locked, expected_revision: row.entry.edit_revision ?? 0 })
      if (result.ok) onMoved(); else setFailure(result)
    } catch (reason) { setError(errorMessage(reason)) } finally { setBusy(false) }
  }
  return <Modal title={`Move ${row.course.course_code} ${row.entry.session_type.toLowerCase()}`} onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={submit} disabled={busy || unchanged}>{busy ? 'Checking…' : 'Save adjustment'}</Button></>}>
    <div className="stack-gap">
      <p className="subtle-note"><Info size={15} aria-hidden="true" />The server atomically validates and moves the complete lab block, including clock-time adjacency, before saving. Current placement: {row.day} {row.startSlot.start_time}–{row.startSlot.end_time}, {row.room.room_code}.</p>
      {failure && <Notice tone="error" title={failure.rule_code ? `Move rejected: ${failure.violated_constraints.join(', ') || failure.rule_code} violated` : 'Move rejected'}>{failure.message}</Notice>}
      {error && <Notice tone="error" title="The move could not be sent">{error}</Notice>}
      <SelectField label="Day and time" id="move-slot" value={slotId} onChange={setSlotId} options={free.map((slot) => ({ value: slot.slot_id, label: `${slot.day_of_week} · ${slot.start_time}–${slot.end_time}` }))} hint="Blocked slots are not offered." />
      <label><input type="checkbox" checked={locked} onChange={(e) => setLocked(e.target.checked)} /> Lock this complete session/block during regeneration. Unlock before moving a locked block.</label>
      <SelectField label="Room" id="move-room" value={roomId} onChange={setRoomId} options={rooms.filter((room) => room.is_active || room.room_id === row.room.room_id).map((room) => ({ value: room.room_id, label: `${room.room_code} · ${room.room_type} · ${room.capacity} seats` }))} />
    </div>
  </Modal>
}

export function TimetablePage({ onStatus, role }: { onStatus: (message: string) => void; role: Role }) {
  const [batch, setBatch] = useState('all')
  const [instructor, setInstructor] = useState('all')
  const [room, setRoom] = useState('all')
  const [course, setCourse] = useState('all')
  const [day, setDay] = useState('all')
  const [scheduleId, setScheduleId] = useState('')
  const [moving, setMoving] = useState<TimetableRow | null>(null)

  const base = useAsync(getSchedules, [])
  const terms = useAsync(getTerms, [])
  const [termId, setTermId] = useState('')
  const currentTerm = termId || terms.data?.find((t) => t.status === 'Active')?.term_id || (base.data ?? []).find((s) => s.schedule_type === 'Timetable')?.term_id || ''
  const versions = useMemo(() => (base.data ?? []).filter((item) => item.schedule_type === 'Timetable' && item.term_id === currentTerm && item.status !== 'Generating').sort((a, b) => b.version_no - a.version_no), [base.data, currentTerm])
  const selectedVersion = versions.find((item) => item.schedule_id === scheduleId) ?? versions.find((item) => item.status === 'Published') ?? versions[0]
  const view = useAsync(() => (selectedVersion ? Promise.all([getTimetable(selectedVersion.schedule_id, selectedVersion.term_id), getScheduleEditContext(selectedVersion.schedule_id)]) : Promise.resolve([[], { revision: 0, rooms: [], slots: [], examSlots: [] }] as [TimetableRow[], import('../services/api').EditContext])), [selectedVersion?.schedule_id])
  const masterRooms = view.data?.[1]?.rooms ?? []
  const rows = view.data?.[0] ?? []
  const slots = view.data?.[1]?.slots ?? []
  const batches = [...new Map(rows.map((row) => [row.batch.batch_id, row.batch])).values()]
  const instructors = [...new Map(rows.map((row) => [row.instructor.instructor_id, row.instructor])).values()]
  const rooms = [...new Map(rows.map((row) => [row.room.room_id, row.room])).values()]
  const courses = [...new Map(rows.map((row) => [row.course.course_id, row.course])).values()]
  const days = useMemo(() => DAY_NAMES.filter((name) => slots.some((slot) => slot.day_of_week === name)), [slots])
  const filteredRows = useMemo(() => rows.filter((item) => (batch === 'all' || item.batch.batch_id === batch) && (instructor === 'all' || item.instructor.instructor_id === instructor) && (room === 'all' || item.room.room_id === room) && (course === 'all' || item.course.course_id === course) && (day === 'all' || item.day === day)), [rows, batch, instructor, room, course, day])
  const canMove = role === 'Coordinator' && selectedVersion?.status === 'Generated'
  const [undoConfirm, setUndoConfirm] = useState(false)
  const [editError, setEditError] = useState('')
  const [undoBusy, setUndoBusy] = useState(false)
  const undoAll = async () => {
    if (!selectedVersion) return
    setUndoBusy(true); setEditError('')
    try { await undoSchedule(selectedVersion.schedule_id, rows[0]?.entry.edit_revision ?? view.data?.[1]?.revision ?? 0); view.reload(); setUndoConfirm(false); onStatus('The server restored the stored baseline, including rooms and locks.') }
    catch (reason) { setEditError(errorMessage(reason)) }
    finally { setUndoBusy(false) }
  }


  const labelFor = (value: string, allLabel: string, items: Array<{ value: string; label: string }>) => value === 'all' ? allLabel : items.find((item) => item.value === value)?.label ?? value
  const batchLabel = (item: { program_code: string; batch_year: number; section: string }) => `${item.program_code} ${item.batch_year} · ${item.section}`
  const filterText = [
    `Batch: ${labelFor(batch, 'All', batches.map((item) => ({ value: item.batch_id, label: batchLabel(item) })))}`,
    `Instructor: ${labelFor(instructor, 'All', instructors.map((item) => ({ value: item.instructor_id, label: item.full_name })))}`,
    `Room: ${labelFor(room, 'All', rooms.map((item) => ({ value: item.room_id, label: item.room_code })))}`,
    `Course: ${labelFor(course, 'All', courses.map((item) => ({ value: item.course_id, label: item.course_code })))}`,
    `Day: ${day === 'all' ? 'All' : day}`,
  ].join('  ·  ')

  return <div className="page-stack">
    <PageHeader eyebrow="Timetable / View" title="Timetable view" description={`${selectedVersion ? `Version ${selectedVersion.version_no} · ${selectedVersion.status}` : 'No version selected'}${canMove ? ' · Use Move on a session to adjust it; every move is re-validated.' : ''}`} actions={<ExportActions onStatus={onStatus} disabled={!selectedVersion} allowGrouped={role === 'Coordinator'} onExport={(format, group) => selectedVersion ? exportSchedule(selectedVersion.schedule_id, format, { batch_id: batch === 'all' ? undefined : batch, instructor_id: instructor === 'all' ? undefined : instructor, room_id: room === 'all' ? undefined : room, course_id: course === 'all' ? undefined : course, day_of_week: day === 'all' ? undefined : DAY_NAMES.indexOf(day) + 1 }, group) : Promise.resolve()} />} />
    {canMove && <div className="form-actions"><Button variant="secondary" onClick={() => setUndoConfirm(true)}>Undo all tracked manual edits</Button></div>}
    {editError && <Notice tone="error" title="Undo failed">{editError}</Notice>}
    {undoConfirm && selectedVersion && <ConfirmDialog title={`Restore version ${selectedVersion.version_no} baseline?`} confirmLabel="Restore baseline" danger={false} busy={undoBusy} onCancel={() => setUndoConfirm(false)} onConfirm={() => void undoAll()} message={<p>Restore all entries, rooms and lock flags to this Generated version's captured baseline? Existing revision history will be retained.</p>} />}
    <LoadState loading={base.loading || terms.loading || view.loading} error={base.error || terms.error || view.error} onRetry={() => { base.reload(); terms.reload(); view.reload() }}>
      {!selectedVersion ? <Notice title="No timetable has been generated yet">{role === 'Coordinator' ? 'Generate a new version from the Generate screen.' : 'No schedule is available in your permitted scope. Contact the Coordinator.'}</Notice> : <>
        <Card className="filter-card no-print"><div className="filter-card-heading"><div><span className="eyebrow"><SlidersHorizontal size={14} /> Weekly timetable</span><h2>Filter timetable</h2></div>
          <div className="view-version"><SelectField label="Term" id="view-term" value={currentTerm} onChange={(value) => { setTermId(value); setScheduleId(''); setBatch('all'); setInstructor('all'); setRoom('all'); setCourse('all'); setDay('all') }} options={(terms.data ?? []).map((t) => ({ value: t.term_id, label: t.label }))} /><label htmlFor="version-select">Version</label><select id="version-select" value={selectedVersion.schedule_id} onChange={(event) => setScheduleId(event.target.value)}>{versions.map((item) => <option key={item.schedule_id} value={item.schedule_id}>Version {item.version_no} · {item.status}</option>)}</select></div></div>
          <div className="filter-grid">
            <SelectField label="Batch" value={batch} onChange={setBatch} options={[{ value: 'all', label: role === 'Student' ? 'My batch' : 'All permitted batches' }, ...batches.map((item) => ({ value: item.batch_id, label: batchLabel(item) }))]} id="batch-filter" />
            <SelectField label="Instructor" value={instructor} onChange={setInstructor} options={[{ value: 'all', label: role === 'Faculty' ? 'My instructor' : 'All permitted instructors' }, ...instructors.map((item) => ({ value: item.instructor_id, label: item.full_name }))]} id="instructor-filter" />
            <SelectField label="Room" value={room} onChange={setRoom} options={[{ value: 'all', label: 'All rooms' }, ...rooms.map((item) => ({ value: item.room_id, label: item.room_code }))]} id="room-filter" />
            <SelectField label="Course" value={course} onChange={setCourse} options={[{ value: 'all', label: 'All courses' }, ...courses.map((item) => ({ value: item.course_id, label: `${item.course_code} · ${item.title}` }))]} id="course-filter" />
            <SelectField label="Day" value={day} onChange={setDay} options={[{ value: 'all', label: 'All days' }, ...days.map((item) => ({ value: item, label: item }))]} id="day-filter" />
          </div>
          <div className="filter-summary"><span><Filter size={14} /> {filteredRows.length} sessions shown</span><button type="button" onClick={() => { setBatch('all'); setInstructor('all'); setRoom('all'); setCourse('all'); setDay('all') }}>Clear filters</button></div></Card>
        <div className="print-only print-header"><strong>ATES · Timetable view</strong><span>Version {selectedVersion.version_no} · {selectedVersion.status}</span><span>{filterText}</span></div>
        <div className="legend-row"><div className="legend"><span className="legend-label">Legend</span><span><i className="legend-swatch lecture" />Lecture</span><span><i className="legend-swatch lab" />Lab</span><span><i className="legend-swatch blocked" />Break</span><span><LockKeyhole size={14} />Locked</span><span><PencilLine size={14} />Manual override</span></div><div className="legend-note"><CheckCircle2 size={14} /> Version {selectedVersion.version_no} · <StatusBadge status={selectedVersion.status} /></div></div>
        {selectedVersion.status === 'Published' && role !== 'Student' && <Notice title="This version is published and read-only">Generate a new version to make changes.</Notice>}
        <Card className="timetable-card"><div className="timetable-scroll"><TimetableGrid rows={filteredRows} slots={slots} days={days} canMove={canMove} onMove={setMoving} /></div><div className="table-footnote"><Info size={14} /> Hover over a session for the full course, room and instructor label. Lab sessions occupy consecutive slots.{canMove ? ' Multi-slot lab blocks are moved atomically.' : ''}</div></Card>
      </>}
    </LoadState>
    {moving && selectedVersion && <MoveDialog row={moving} slots={slots} rooms={masterRooms} scheduleId={selectedVersion.schedule_id} onClose={() => setMoving(null)} onMoved={() => { setMoving(null); onStatus(`${moving.course.course_code} moved. All hard constraints re-validated.`); view.reload() }} />}
  </div>
}
