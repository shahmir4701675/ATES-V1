import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Info, Lock, Save, XCircle } from 'lucide-react'
import { Button, Card, LoadState, Notice, PageHeader, SelectField } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { DAY_NAMES } from '../data/reference'
import { errorMessage, getAvailability, getInstructors, getTerms, getTimeSlots, saveAvailability } from '../services/api'
import type { AvailabilityItem, TimeSlot } from '../types'
import type { Role } from '../components/AppShell'

export function AvailabilityPage({ role, facultyInstructorId, onStatus }: { role: Role; facultyInstructorId?: string | null; onStatus: (message: string) => void }) {
  const base = useAsync(() => Promise.all([getInstructors(), getTerms()]), [])
  const [instructorId, setInstructorId] = useState('')
  const [termId, setTermId] = useState('')
  const [unavailable, setUnavailable] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const instructors = useMemo(() => (base.data?.[0] ?? []).filter((item) => item.is_active), [base.data])
  const terms = base.data?.[1] ?? []
  const isFaculty = role === 'Faculty'
  const activeInstructor = isFaculty
    ? instructors.find((item) => item.instructor_id === facultyInstructorId) ?? instructors[0]
    : instructors.find((item) => item.instructor_id === instructorId) ?? instructors[0]
  const activeTerm = terms.find((item) => item.term_id === termId) ?? terms.find((item) => item.status === 'Active') ?? terms[0]

  const grid = useAsync<[TimeSlot[], AvailabilityItem[]]>(
    () => (activeInstructor && activeTerm ? Promise.all([getTimeSlots(activeTerm.term_id), getAvailability(activeInstructor.instructor_id)]) : Promise.resolve([[], []])),
    [activeInstructor?.instructor_id, activeTerm?.term_id],
  )

  const slots = grid.data?.[0] ?? []
  const stored = grid.data?.[1] ?? []

  useEffect(() => {
    setUnavailable(new Set(stored.filter((item) => !item.is_available).map((item) => item.slot_id)))
  }, [stored])

  const days = useMemo(() => DAY_NAMES.filter((name) => slots.some((slot) => slot.day_of_week === name)), [slots])
  const hours = useMemo(() => [...new Map(slots.map((slot) => [slot.slot_index, slot])).values()].sort((a, b) => a.slot_index - b.slot_index), [slots])

  const toggle = (slotId: string) => {
    setUnavailable((current) => {
      const next = new Set(current)
      if (next.has(slotId)) next.delete(slotId)
      else next.add(slotId)
      return next
    })
  }

  const save = async () => {
    if (!activeInstructor) return
    setBusy(true)
    setError('')
    try {
      const items = slots.filter((slot) => !slot.is_blocked).map((slot) => ({ slot_id: slot.slot_id, is_available: !unavailable.has(slot.slot_id) }))
      await saveAvailability(activeInstructor.instructor_id, items)
      onStatus(`Saved availability for ${activeInstructor.full_name}.`)
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  return <div className="page-stack">
    <PageHeader
      eyebrow="Availability"
      title={isFaculty ? 'My teaching availability' : 'Instructor availability'}
      description="Toggle weekly teaching slots between available and unavailable."
      actions={<Button icon={Save} onClick={() => void save()} disabled={busy || !slots.length}>{busy ? 'Saving…' : 'Save availability'}</Button>}
    />
    <Notice tone="info" title="Changes apply only to the next generated version">
      <Info size={14} aria-hidden="true" /> Updating availability does not alter any currently generated or published schedule.
    </Notice>
    {error && <Notice tone="error" title="Could not save availability">{error}</Notice>}
    <LoadState loading={base.loading || grid.loading} error={base.error || grid.error} onRetry={() => { base.reload(); grid.reload() }}>
      <Card title={activeInstructor ? `Weekly grid · ${activeInstructor.full_name}` : 'Weekly grid'}>
        <div className="stack-gap">
          <div className="form-columns">
            {isFaculty ? (
              <div className="field"><label>Instructor</label><input value={activeInstructor?.full_name ?? '—'} disabled /></div>
            ) : (
              <SelectField label="Instructor" id="avail-inst" value={activeInstructor?.instructor_id ?? ''} onChange={setInstructorId} options={instructors.map((item) => ({ value: item.instructor_id, label: `${item.full_name} · ${item.email}` }))} hint="Coordinator can edit any instructor's availability." />
            )}
            <SelectField label="Academic term" id="avail-term" value={activeTerm?.term_id ?? ''} onChange={setTermId} options={terms.map((item) => ({ value: item.term_id, label: item.label }))} hint="Slots are loaded from the selected term." />
          </div>
          {slots.length === 0 ? (
            <Notice title="No time slots in this term">Generate the term slot grid in Data management › Terms and slots first.</Notice>
          ) : (
            <div className="avail-scroll">
              <div className="avail-grid" style={{ gridTemplateColumns: `110px repeat(${days.length}, minmax(120px, 1fr))` }}>
                <div className="avail-head">Time</div>
                {days.map((day) => <div className="avail-head" key={day}>{day}</div>)}
                {hours.flatMap((hour) => [
                  <div className="avail-time" key={`t-${hour.slot_index}`}>Slot {hour.slot_index}<span>{hour.start_time}–{hour.end_time}</span></div>,
                  ...days.map((day) => {
                    const slot = slots.find((item) => item.slot_index === hour.slot_index && item.day_of_week === day)
                    if (!slot) return <div className="avail-cell avail-blocked" key={`${day}-${hour.slot_index}`}>—</div>
                    if (slot.is_blocked) {
                      return <div className="avail-cell avail-blocked" key={slot.slot_id} title={slot.block_reason ?? 'Blocked'}><Lock size={13} aria-hidden="true" />{slot.block_reason ?? 'Break'}</div>
                    }
                    const isAvail = !unavailable.has(slot.slot_id)
                    return (
                      <button
                        type="button"
                        key={slot.slot_id}
                        className={`avail-cell ${isAvail ? 'avail-yes' : 'avail-no'}`}
                        aria-pressed={!isAvail}
                        aria-label={`${day} ${slot.start_time}, ${isAvail ? 'Available' : 'Unavailable'}`}
                        onClick={() => toggle(slot.slot_id)}
                      >
                        {isAvail ? <><CheckCircle2 size={14} aria-hidden="true" />Available</> : <><XCircle size={14} aria-hidden="true" />Unavailable</>}
                      </button>
                    )
                  }),
                ])}
              </div>
            </div>
          )}
        </div>
      </Card>
    </LoadState>
  </div>
}
