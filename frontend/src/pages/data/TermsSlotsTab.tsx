import { useEffect, useMemo, useState } from 'react'
import { CalendarCheck2, CirclePlus, Grid3x3, Lock, Pencil, Power, Unlock } from 'lucide-react'
import { Button, ErrorSummary, Field, InputField, LoadState, Notice, SelectField } from '../../components/ui'
import { ConfirmDialog, DataTable, Modal } from '../../components/Modal'
import { Card } from '../../components/ui'
import { useAsync } from '../../hooks/useAsync'
import { DAY_NAMES } from '../../data/reference'
import { activateTerm, closeTerm, createTerm, errorMessage, saveSlotGrid, getTerms, getTimeSlots, updateSlot, updateTerm } from '../../services/api'
import type { SlotGridInput, Term, TimeSlot } from '../../types'
import { StatusCell, same, toInt } from './MasterTab'

interface Props { readOnly: boolean; onStatus: (message: string) => void }
const termStatusCell = (status: Term['status']) => status === 'Active' ? <StatusCell active /> : <span className="inline-status">{status === 'Closed' ? 'Closed' : 'Planned'}</span>
const timeToMinutes = (value: string) => { const match = /^(\d{1,2}):(\d{2})$/.exec(value.trim()); return match && Number(match[1]) < 24 && Number(match[2]) < 60 ? Number(match[1]) * 60 + Number(match[2]) : Number.NaN }

type TermForm = { name: string; start_date: string; end_date: string }

export function slotGridInputFromSlots(rows: TimeSlot[]): SlotGridInput {
  const first = [...rows].sort((a, b) => a.slot_index - b.slot_index || DAY_NAMES.indexOf(a.day_of_week) - DAY_NAMES.indexOf(b.day_of_week))[0]
  return first ? {
    working_days: DAY_NAMES.flatMap((day, index) => rows.some((slot) => slot.day_of_week === day) ? [index + 1] : []),
    first_start_time: first.start_time,
    slot_length_min: timeToMinutes(first.end_time) - timeToMinutes(first.start_time),
    slots_per_day: Math.max(...rows.map((slot) => slot.slot_index)),
  } : { working_days: [1, 2, 3, 4, 5], first_start_time: '08:00', slot_length_min: 60, slots_per_day: 6 }
}

export function TermsSlotsTab({ readOnly, onStatus }: Props) {
  const terms = useAsync(getTerms, [])
  const [termId, setTermId] = useState('')
  const [form, setForm] = useState<{ id: string | null; values: TermForm } | null>(null)
  const [errors, setErrors] = useState<Partial<TermForm>>({})
  const [serverError, setServerError] = useState('')
  const [busy, setBusy] = useState(false)
  const [activating, setActivating] = useState<Term | null>(null)
  const [closing, setClosing] = useState<Term | null>(null)
  const [actionError, setActionError] = useState('')

  const list = terms.data ?? []
  const selected = list.find((item) => item.term_id === termId) ?? list.find((item) => item.status === 'Active') ?? list[0]
  const active = list.find((item) => item.status === 'Active')

  const validate = (values: TermForm, id: string | null) => {
    const found: Partial<TermForm> = {}
    if (!values.name.trim()) found.name = 'Term name is required.'
    else if (values.name.trim().length > 50) found.name = 'Term name can have at most 50 characters.'
    else if (list.some((item) => item.term_id !== id && same(item.label, values.name))) found.name = `A term named ${values.name.trim()} already exists.`
    if (!values.start_date) found.start_date = 'Start date is required.'
    if (!values.end_date) found.end_date = 'End date is required.'
    else if (values.start_date && values.end_date <= values.start_date) found.end_date = 'End date must be after the start date.'
    return found
  }
  const save = async () => {
    if (!form) return
    const found = validate(form.values, form.id)
    setErrors(found)
    if (Object.keys(found).length) return
    setBusy(true); setServerError('')
    try {
      const payload = { label: form.values.name.trim(), start_date: form.values.start_date, end_date: form.values.end_date }
      if (form.id === null) await createTerm({ ...payload, status: 'Planned' }); else await updateTerm(form.id, payload)
      onStatus(`Term ${form.id === null ? 'created' : 'updated'}.`)
      setForm(null); terms.reload()
    } catch (reason) { setServerError(errorMessage(reason)) } finally { setBusy(false) }
  }
  const markActive = async () => {
    if (!activating) return
    setBusy(true); setActionError('')
    try { await activateTerm(activating.term_id); onStatus(`${activating.label} is now the Active term.`); setActivating(null); terms.reload() }
    catch (reason) { setActionError(errorMessage(reason)) } finally { setBusy(false) }
  }
  const close = async () => {
    if (!closing) return
    setBusy(true); setActionError('')
    try { await closeTerm(closing.term_id); onStatus(`${closing.label} closed.`); setClosing(null); terms.reload() }
    catch (reason) { setActionError(errorMessage(reason)) } finally { setBusy(false) }
  }
  const messages = [...Object.values(errors), ...(serverError ? [serverError] : [])]

  return <div className="page-stack">
    <LoadState loading={terms.loading} error={terms.error} onRetry={terms.reload}>
      <Card title="Academic terms">
        {actionError && !activating && !closing && <Notice tone="error" title="The action could not be completed">{actionError}</Notice>}
        {!active && <Notice tone="warning" title="No term is Active">Exactly one term should be Active so that generation and dashboards know which term to use.</Notice>}
        <DataTable rows={list} rowKey={(row) => row.term_id} caption="Academic terms" searchText={(row) => `${row.label} ${row.status} ${row.start_date} ${row.end_date}`}
          toolbar={!readOnly && <Button icon={CirclePlus} onClick={() => { setErrors({}); setServerError(''); setForm({ id: null, values: { name: '', start_date: '', end_date: '' } }) }}>Add term</Button>}
          columns={[
            { key: 'name', label: 'Term', value: (row) => row.label, render: (row) => <strong>{row.label}</strong> },
            { key: 'start', label: 'Start date', value: (row) => row.start_date },
            { key: 'end', label: 'End date', value: (row) => row.end_date },
            { key: 'status', label: 'Status', value: (row) => row.status, render: (row) => termStatusCell(row.status) },
          ]}
          actions={readOnly ? undefined : (row) => <>
            <Button variant="secondary" icon={Pencil} ariaLabel={`Edit ${row.label}`} onClick={() => { setErrors({}); setServerError(''); setForm({ id: row.term_id, values: { name: row.label, start_date: row.start_date, end_date: row.end_date } }) }}>Edit</Button>
            {row.status !== 'Active' && row.status !== 'Closed' && <Button variant="secondary" icon={CalendarCheck2} ariaLabel={`Mark ${row.label} Active`} onClick={() => { setActionError(''); setActivating(row) }}>Mark Active</Button>}
            {row.status !== 'Closed' && <Button variant="secondary" icon={Power} ariaLabel={`Close ${row.label}`} onClick={() => { setActionError(''); setClosing(row) }}>Close</Button>}
          </>} />
      </Card>
      {selected && <SlotGrid key={selected.term_id} term={selected} terms={list} onTerm={setTermId} readOnly={readOnly} onStatus={onStatus} />}
    </LoadState>
    {form && <Modal title={`${form.id === null ? 'Add' : 'Edit'} term`} onClose={() => setForm(null)} footer={<><Button variant="secondary" onClick={() => setForm(null)}>Cancel</Button><Button onClick={() => void save()} disabled={busy}>{busy ? 'Saving…' : 'Save'}</Button></>}>
      <form onSubmit={(event) => { event.preventDefault(); void save() }} noValidate><ErrorSummary errors={messages} /><div className="stack-gap">
        <InputField id="term-name" label="Term name" value={form.values.name} error={errors.name} tooltip="Unique name, for example Fall 2026." onChange={(value) => setForm({ ...form, values: { ...form.values, name: value } })} />
        <InputField id="term-start" type="date" label="Start date" value={form.values.start_date} error={errors.start_date} tooltip="First day of the term." onChange={(value) => setForm({ ...form, values: { ...form.values, start_date: value } })} />
        <InputField id="term-end" type="date" label="End date" value={form.values.end_date} error={errors.end_date} tooltip="Last day of the term. Must be after the start date." onChange={(value) => setForm({ ...form, values: { ...form.values, end_date: value } })} />
        <p className="subtle-note">New terms start as Planned. Use Mark Active when the term should drive generation.</p>
      </div><button type="submit" className="sr-only" tabIndex={-1}>Save</button></form>
    </Modal>}
    {activating && <ConfirmDialog title="Mark term Active" confirmLabel="Mark Active" danger={false} busy={busy} onCancel={() => setActivating(null)} onConfirm={() => void markActive()}
      message={<>{actionError && <Notice tone="error" title="Not completed">{actionError}</Notice>}<p>{activating.label} will become the Active term.{active ? ` ${active.label} will be closed, because only one term can be Active.` : ''}</p></>} />}
    {closing && <ConfirmDialog title="Close term" confirmLabel="Close term" busy={busy} onCancel={() => setClosing(null)} onConfirm={() => void close()}
      message={<>{actionError && <Notice tone="error" title="Not completed">{actionError}</Notice>}<p>Close {closing.label}? A closed term is no longer offered for new schedules. Existing versions are kept.</p></>} />}
  </div>
}

/* ------------------------------------------------------------------------- slot grid */
function SlotGrid({ term, terms, onTerm, readOnly, onStatus }: { term: Term; terms: Term[]; onTerm: (id: string) => void; readOnly: boolean; onStatus: (message: string) => void }) {
  const slots = useAsync(() => getTimeSlots(term.term_id), [term.term_id])
  const [days, setDays] = useState<number[]>([1, 2, 3, 4, 5])
  const [start, setStart] = useState('08:00')
  const [length, setLength] = useState('60')
  const [perDay, setPerDay] = useState('6')
  const [errors, setErrors] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [blocking, setBlocking] = useState<TimeSlot | null>(null)
  const [reason, setReason] = useState('')
  const [reasonError, setReasonError] = useState('')
  const [notice, setNotice] = useState('')
  const [initialized, setInitialized] = useState(false)

  const rows = slots.data ?? []
  const usedDays = useMemo(() => DAY_NAMES.filter((name) => rows.some((slot) => slot.day_of_week === name)), [rows])
  const hours = useMemo(() => [...new Map(rows.map((slot) => [slot.slot_index, slot])).values()].sort((a, b) => a.slot_index - b.slot_index), [rows])

  useEffect(() => {
    if (initialized || slots.loading || slots.error) return
    const input = slotGridInputFromSlots(slots.data ?? [])
    setDays(input.working_days); setStart(input.first_start_time)
    setLength(String(input.slot_length_min)); setPerDay(String(input.slots_per_day))
    setInitialized(true)
  }, [initialized, slots.loading, slots.error, slots.data])

  const generate = async () => {
    const found: string[] = []
    const startMinutes = timeToMinutes(start)
    const len = toInt(length)
    const count = toInt(perDay)
    if (!days.length) found.push('Select at least one working day.')
    if (Number.isNaN(startMinutes)) found.push('First start time must be a valid time such as 08:00.')
    if (!(len > 0)) found.push('Slot length must be a whole number of minutes greater than 0.')
    if (!(count > 0)) found.push('Slots per day must be a whole number greater than 0.')
    if (!found.length && startMinutes + len * count >= 24 * 60) found.push('The last slot must end before midnight. Reduce the slot length or the number of slots.')
    setErrors(found)
    if (found.length) return
    setBusy(true); setNotice('')
    try { const saved = await saveSlotGrid(term.term_id, { working_days: days, first_start_time: start, slot_length_min: len, slots_per_day: count }); onStatus(`${saved.length} slots saved for ${term.label}.`); slots.reload() }
    catch (reasonError) { setErrors([errorMessage(reasonError)]) } finally { setBusy(false) }
  }
  const applyBlock = async (slot: TimeSlot, blocked: boolean, why: string | null) => {
    try { await updateSlot(term.term_id, slot.slot_id, { is_blocked: blocked, block_reason: why }); onStatus(`${slot.day_of_week} ${slot.start_time} slot ${blocked ? 'blocked' : 'unblocked'}.`); setBlocking(null); slots.reload() }
    catch (failure) { setReasonError(errorMessage(failure)); setNotice(errorMessage(failure)) }
  }

  return <Card title="Slot grid" actions={<SelectField label="Term" id="slot-term" value={term.term_id} onChange={onTerm} options={terms.map((item) => ({ value: item.term_id, label: item.label }))} />}>
    <div className="stack-gap">
      {!readOnly && <fieldset className="stack-gap" style={{ border: 0, padding: 0, margin: 0 }}>
        <legend className="eyebrow"><Grid3x3 size={14} aria-hidden="true" /> Save the weekly grid</legend>
        <ErrorSummary errors={errors} />
        <div><span className="eyebrow">Working days</span><div className="legend" style={{ marginTop: 8 }}>{DAY_NAMES.map((name, index) => <label key={name} className="check-row" style={{ borderTop: 0, padding: 0 }} title={`Include ${name} in the grid`}><input type="checkbox" checked={days.includes(index + 1)} onChange={(event) => setDays(event.target.checked ? [...days, index + 1] : days.filter((item) => item !== index + 1))} /><span><strong>{name}</strong></span></label>)}</div></div>
        <div className="inline-form">
          <InputField id="slot-start" label="First start time" type="time" value={start} onChange={setStart} tooltip="Start of the first slot of each day." />
          <InputField id="slot-length" label="Slot length (minutes)" type="number" min={1} value={length} onChange={setLength} tooltip="Default 60 minutes." />
          <InputField id="slot-count" label="Slots per day" type="number" min={1} value={perDay} onChange={setPerDay} tooltip="Number of consecutive slots each working day." />
          <Button icon={Grid3x3} onClick={() => void generate()} disabled={busy || slots.loading || Boolean(slots.error) || !initialized}>{busy ? 'Saving…' : 'Save grid'}</Button>
        </div>
        {rows.length > 0 && <p className="subtle-note">{term.label} has {rows.length} slots. Saving updates their times and preserves blocked periods and slot IDs. Keep the existing slot length, working days and slot indexes; saving cannot remove slots.</p>}
      </fieldset>}
      {notice && <Notice tone="error" title="The slot could not be changed">{notice}</Notice>}
      <LoadState loading={slots.loading} error={slots.error} onRetry={slots.reload}>
        {rows.length === 0 ? <Notice title={`No slots for ${term.label}`}>{readOnly ? 'The Coordinator has not saved a grid for this term yet.' : 'Save the weekly grid above.'}</Notice> : <div className="avail-scroll"><div className="avail-grid" style={{ gridTemplateColumns: `110px repeat(${usedDays.length}, minmax(112px, 1fr))` }}>
          <div className="avail-head">Time</div>{usedDays.map((name) => <div className="avail-head" key={name}>{name}</div>)}
          {hours.flatMap((hour) => [<div className="avail-time" key={`t${hour.slot_index}`}>Slot {hour.slot_index}<span>{hour.start_time}–{hour.end_time}</span></div>, ...usedDays.map((name) => {
            const slot = rows.find((item) => item.slot_index === hour.slot_index && item.day_of_week === name)
            if (!slot) return <div className="avail-cell avail-blocked" key={`${name}${hour.slot_index}`}>—</div>
            return <button type="button" key={slot.slot_id} className={`avail-cell ${slot.is_blocked ? 'avail-no' : 'avail-yes'}`} disabled={readOnly}
              aria-label={`${name} ${slot.start_time}, ${slot.is_blocked ? `blocked: ${slot.block_reason}. Unblock` : 'open. Block'}`}
              onClick={() => { if (slot.is_blocked) void applyBlock(slot, false, null); else { setReason(''); setReasonError(''); setBlocking(slot) } }}>
              {slot.is_blocked ? <><Lock size={13} aria-hidden="true" />{slot.block_reason ?? 'Blocked'}</> : <><Unlock size={13} aria-hidden="true" />Open</>}</button>
          })])}
        </div></div>}
      </LoadState>
      {!readOnly && rows.length > 0 && <p className="subtle-note">Select an open slot to block it with a reason (for example Prayer break). Select a blocked slot to unblock it.</p>}
    </div>
    {blocking && <Modal title={`Block ${blocking.day_of_week} ${blocking.start_time}–${blocking.end_time}`} onClose={() => setBlocking(null)} footer={<><Button variant="secondary" onClick={() => setBlocking(null)}>Cancel</Button><Button onClick={() => { if (!reason.trim()) setReasonError('A reason is required to block a slot.'); else void applyBlock(blocking, true, reason.trim()) }}>Block slot</Button></>}>
      <form onSubmit={(event) => { event.preventDefault(); if (!reason.trim()) setReasonError('A reason is required to block a slot.'); else void applyBlock(blocking, true, reason.trim()) }} noValidate>
        <Field label="Reason" htmlFor="block-reason" tooltip="Shown on the timetable in place of sessions." error={reasonError || undefined}><input id="block-reason" value={reason} className={reasonError ? 'input-invalid' : ''} onChange={(event) => setReason(event.target.value)} /></Field>
        <button type="submit" className="sr-only" tabIndex={-1}>Block</button>
      </form>
    </Modal>}
  </Card>
}
