import { useEffect, useMemo, useState } from 'react'
import { CirclePlus, Copy, Lock, Save, Trash2 } from 'lucide-react'
import { Button, Card, ErrorSummary, InputField, LoadState, Notice, PageHeader, SelectField, Switch } from '../components/ui'
import { ConfirmDialog, DataTable, Modal } from '../components/Modal'
import { useAsync } from '../hooks/useAsync'
import { CONSTRAINT_CATALOGUE, MANDATORY_CODES, defaultRules, type ConstraintMeta } from '../data/reference'
import {
  cloneConfig, createConfig, createExamSlot, deleteConfigMock, errorMessage, getConfigs, getExamSlots, getSchedules, getTerms, saveConfigRules, updateConfig,
} from '../services/api'
import type { ConstraintRule, ScheduleType, SchedulingConfig } from '../types'

const mergeCatalogue = (type: ScheduleType, stored: ConstraintRule[]) =>
  CONSTRAINT_CATALOGUE.filter((item) => item.scheduleType === type).map((meta) => {
    const match = stored.find((rule) => rule.rule_code === meta.code)
    return {
      meta,
      rule: match ?? {
        rule_code: meta.code,
        rule_type: meta.type,
        is_enabled: true,
        weight: meta.defaultWeight,
        param_value: meta.param?.defaultValue ?? null,
      },
    }
  })

export function ConstraintsSettingsPage({ onStatus }: { onStatus: (message: string) => void }) {
  const base = useAsync(() => Promise.all([getTerms(), getSchedules()]), [])
  const [termId, setTermId] = useState('')
  const [scheduleType, setScheduleType] = useState<ScheduleType>('Timetable')
  const [configId, setConfigId] = useState('')
  const [rules, setRules] = useState<ConstraintRule[]>([])
  const [timeLimit, setTimeLimit] = useState('120')
  const [seed, setSeed] = useState('1')
  const [errors, setErrors] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [warnHard, setWarnHard] = useState<ConstraintMeta | null>(null)
  const [modalMode, setModalMode] = useState<'create' | 'clone' | null>(null)
  const [newName, setNewName] = useState('')
  const [nameError, setNameError] = useState('')
  const [deleting, setDeleting] = useState<SchedulingConfig | null>(null)

  const terms = base.data?.[0] ?? []
  const schedules = base.data?.[1] ?? []
  const activeTermId = termId || terms.find((item) => item.status === 'Active')?.term_id || terms[0]?.term_id || ''

  const configs = useAsync(() => (activeTermId ? getConfigs(activeTermId, scheduleType) : Promise.resolve([])), [activeTermId, scheduleType])
  const configList = configs.data ?? []
  const selected = configList.find((item) => item.config_id === configId) ?? configList[0] ?? null
  const isUsed = Boolean(selected && schedules.some((item) => item.config_id === selected.config_id))

  useEffect(() => {
    if (selected) {
      setRules(mergeCatalogue(scheduleType, selected.rules).map((item) => item.rule))
      setTimeLimit(String(selected.solver_time_limit_s))
      setSeed(String(selected.random_seed))
    } else {
      setRules(defaultRules(scheduleType))
      setTimeLimit('120')
      setSeed('1')
    }
  }, [selected?.config_id, scheduleType])

  const merged = useMemo(() => mergeCatalogue(scheduleType, rules), [scheduleType, rules])

  const patchRule = (code: string, patch: Partial<ConstraintRule>) => {
    setRules((current) => current.map((item) => (item.rule_code === code ? { ...item, ...patch } : item)))
  }

  const toggleRule = (meta: ConstraintMeta, nextEnabled: boolean) => {
    if (MANDATORY_CODES.has(meta.code)) return
    if (meta.type === 'Hard' && !nextEnabled) {
      setWarnHard(meta)
      return
    }
    patchRule(meta.code, { is_enabled: nextEnabled })
  }

  const saveAll = async () => {
    const found: string[] = []
    const limitNum = Number(timeLimit)
    const seedNum = Number(seed)
    if (!Number.isInteger(limitNum) || limitNum < 10 || limitNum > 600) found.push('Solver time limit must be a whole number from 10 to 600 seconds.')
    if (!Number.isInteger(seedNum)) found.push('Random seed must be a whole number.')
    merged.forEach(({ meta, rule }) => {
      if (meta.param) {
        const val = rule.param_value
        if (val === null || !Number.isInteger(val) || val < meta.param.min || val > meta.param.max) {
          found.push(`${meta.code} (${meta.param.label}): enter a whole number from ${meta.param.min} to ${meta.param.max}.`)
        }
      }
    })
    setErrors(found)
    if (found.length || !activeTermId) return
    setBusy(true)
    try {
      if (selected) {
        await updateConfig(selected.config_id, { solver_time_limit_s: limitNum, random_seed: seedNum })
        await saveConfigRules(selected.config_id, rules)
        onStatus(`Saved configuration '${selected.name}'.`)
      } else {
        const created = await createConfig({
          term_id: activeTermId,
          schedule_type: scheduleType,
          name: `Default ${scheduleType.toLowerCase()}`,
          solver_time_limit_s: limitNum,
          random_seed: seedNum,
          rules,
        })
        setConfigId(created.config_id)
        onStatus(`Created configuration '${created.name}'.`)
      }
      configs.reload()
    } catch (reason) {
      setErrors([errorMessage(reason)])
    } finally {
      setBusy(false)
    }
  }

  const createOrClone = async () => {
    if (!newName.trim()) { setNameError('Configuration name is required.'); return }
    if (newName.trim().length > 60) { setNameError('Configuration name can have at most 60 characters.'); return }
    setBusy(true)
    setNameError('')
    try {
      const created = modalMode === 'clone' && selected
        ? await cloneConfig({ ...selected, rules }, newName.trim())
        : await createConfig({ term_id: activeTermId, schedule_type: scheduleType, name: newName.trim(), solver_time_limit_s: 120, random_seed: 1, rules: defaultRules(scheduleType) })
      setConfigId(created.config_id)
      setModalMode(null)
      onStatus(`${modalMode === 'clone' ? 'Cloned' : 'Created'} configuration '${created.name}'.`)
      configs.reload()
    } catch (reason) {
      setNameError(errorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  const confirmDelete = async () => {
    if (!deleting) return
    setBusy(true)
    try {
      await deleteConfigMock(deleting.config_id)
      onStatus(`Deleted configuration '${deleting.name}'.`)
      setDeleting(null)
      setConfigId('')
      configs.reload()
    } catch (reason) {
      setErrors([errorMessage(reason)])
      setDeleting(null)
    } finally {
      setBusy(false)
    }
  }

  return <div className="page-stack">
    <PageHeader
      eyebrow="Configuration"
      title="Constraints and settings"
      description="Configure hard and soft scheduling constraints (H01–H10, S01–S06, E01–E05, ES01–ES03), solver parameters, named configurations and examination sessions."
      actions={<Button icon={Save} onClick={() => void saveAll()} disabled={busy}>{busy ? 'Saving…' : 'Save configuration'}</Button>}
    />
    <ErrorSummary errors={errors} />
    <LoadState loading={base.loading || configs.loading} error={base.error || configs.error} onRetry={() => { base.reload(); configs.reload() }}>
      <Card title="Named configuration and solver settings" actions={<div className="card-actions">
        <Button variant="secondary" icon={CirclePlus} onClick={() => { setNewName(''); setNameError(''); setModalMode('create') }}>New configuration</Button>
        <Button variant="secondary" icon={Copy} disabled={!selected} onClick={() => { setNewName(selected ? `${selected.name} (copy)` : ''); setNameError(''); setModalMode('clone') }}>Clone</Button>
        <Button variant="secondary" icon={Trash2} disabled={!selected || isUsed} onClick={() => selected && setDeleting(selected)} ariaLabel="Delete unused configuration">Delete</Button>
      </div>}>
        <div className="form-columns">
          <SelectField label="Academic term" id="cfg-term" value={activeTermId} onChange={(val) => { setTermId(val); setConfigId('') }} options={terms.map((item) => ({ value: item.term_id, label: item.label }))} hint="Configurations belong to one academic term." />
          <SelectField label="Schedule type" id="cfg-type" value={scheduleType} onChange={(val) => { setScheduleType(val as ScheduleType); setConfigId('') }} options={[{ value: 'Timetable', label: 'Timetable (H01–H10, S01–S06)' }, { value: 'Exam schedule', label: 'Exam schedule (E01–E05, ES01–ES03)' }]} hint="Switch between timetable and examination constraint catalogues." />
          <SelectField label="Configuration" id="cfg-select" value={selected?.config_id ?? ''} onChange={setConfigId} options={configList.length ? configList.map((item) => ({ value: item.config_id, label: item.name })) : [{ value: '', label: 'Unsaved default configuration' }]} hint={isUsed ? 'Used by an existing schedule version (cannot be deleted).' : 'Unused configuration.'} />
          <InputField label="Solver time limit (seconds)" id="cfg-limit" type="number" min={10} max={600} value={timeLimit} onChange={setTimeLimit} tooltip="Allowed range: 10–600 seconds. Default is 120 seconds." hint="10–600 seconds (default 120)." />
          <InputField label="Random seed" id="cfg-seed" type="number" value={seed} onChange={setSeed} tooltip="Integer seed for deterministic solver runs." hint="Same seed and inputs produce the same schedule." />
        </div>
      </Card>

      <Card title={`${scheduleType} constraints (${merged.length})`}>
        <div className="constraint-head" aria-hidden="true">
          <span>Code</span><span>Type</span><span>Constraint</span><span>Enabled</span><span>Weight (0–10)</span><span>Parameter</span>
        </div>
        <div>
          {merged.map(({ meta, rule }) => (
            <div className="constraint-row" key={meta.code}>
              <span className="constraint-code">{meta.code}</span>
              <span><span className={`chip ${meta.type === 'Hard' ? 'chip-hard' : 'chip-soft'}`}>{meta.type}</span></span>
              <div className="constraint-title">
                <strong>{meta.title}</strong>
                {meta.mandatory && <small><Lock size={12} aria-hidden="true" /> Mandatory constraint (locked on)</small>}
              </div>
              <div>
                <Switch
                  id={`sw-${meta.code}`}
                  checked={rule.is_enabled}
                  locked={meta.mandatory}
                  label={`Enable ${meta.code}`}
                  onChange={(next) => toggleRule(meta, next)}
                />
              </div>
              <div>
                {meta.type === 'Soft' ? (
                  <label className="weight-control" htmlFor={`wt-${meta.code}`} title="Soft constraint weight from 0 to 10">
                    <span className="sr-only">{meta.code} weight</span>
                    <input
                      id={`wt-${meta.code}`}
                      type="range"
                      min={0}
                      max={10}
                      step={1}
                      disabled={!rule.is_enabled}
                      value={rule.weight}
                      onChange={(event) => patchRule(meta.code, { weight: Number(event.target.value) })}
                    />
                    <output htmlFor={`wt-${meta.code}`}>{rule.weight}</output>
                  </label>
                ) : (
                  <span className="muted">Not applicable (hard)</span>
                )}
              </div>
              <div>
                {meta.param ? (
                  <label className="param-control" htmlFor={`pm-${meta.code}`} title={`${meta.param.label} (${meta.param.min}–${meta.param.max} ${meta.param.unit})`}>
                    <span>{meta.param.label}</span>
                    <input
                      id={`pm-${meta.code}`}
                      type="number"
                      min={meta.param.min}
                      max={meta.param.max}
                      value={rule.param_value ?? meta.param.defaultValue}
                      onChange={(event) => patchRule(meta.code, { param_value: Number(event.target.value) })}
                    />
                  </label>
                ) : (
                  <span className="muted">No parameter</span>
                )}
              </div>
            </div>
          ))}
        </div>
      </Card>

      {activeTermId && <ExamSessionEditor termId={activeTermId} onStatus={onStatus} />}
    </LoadState>

    {warnHard && (
      <ConfirmDialog
        title={`Disable hard constraint ${warnHard.code}?`}
        confirmLabel={`Disable ${warnHard.code}`}
        onCancel={() => setWarnHard(null)}
        onConfirm={() => { patchRule(warnHard.code, { is_enabled: false }); setWarnHard(null) }}
        message={<p>Disabling hard constraint <strong>{warnHard.code}</strong> ({warnHard.title}) permits the solver and manual move validator to produce schedules that violate this rule.</p>}
      />
    )}

    {modalMode && (
      <Modal
        title={modalMode === 'clone' ? 'Clone configuration' : 'New configuration'}
        onClose={() => setModalMode(null)}
        footer={<><Button variant="secondary" onClick={() => setModalMode(null)}>Cancel</Button><Button onClick={() => void createOrClone()} disabled={busy}>Save</Button></>}
      >
        <form onSubmit={(event) => { event.preventDefault(); void createOrClone() }} noValidate>
          <InputField id="cfg-new-name" label="Configuration name" value={newName} onChange={setNewName} error={nameError || undefined} tooltip="Unique name for this term and schedule type (up to 60 characters)." />
        </form>
      </Modal>
    )}

    {deleting && (
      <ConfirmDialog
        title="Delete configuration"
        confirmLabel="Delete"
        busy={busy}
        onCancel={() => setDeleting(null)}
        onConfirm={() => void confirmDelete()}
        message={<p>Delete unused configuration <strong>{deleting.name}</strong>?</p>}
      />
    )}
  </div>
}

function ExamSessionEditor({ termId, onStatus }: { termId: string; onStatus: (message: string) => void }) {
  const slots = useAsync(() => getExamSlots(termId), [termId])
  const [examDate, setExamDate] = useState('2026-12-10')
  const [startTime, setStartTime] = useState('09:00')
  const [endTime, setEndTime] = useState('12:00')
  const [label, setLabel] = useState('Morning session')
  const [errors, setErrors] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  const list = slots.data ?? []

  const addSession = async () => {
    const found: string[] = []
    if (!examDate) found.push('Exam date is required.')
    if (!startTime) found.push('Start time is required.')
    if (!endTime) found.push('End time is required.')
    if (startTime && endTime && endTime <= startTime) found.push('End time must be after start time.')
    if (!label.trim()) found.push('Session label is required.')
    const overlap = list.find((item) => item.exam_date === examDate && startTime < item.end_time && item.start_time < endTime)
    if (overlap) found.push(`Exam session ${startTime}–${endTime} overlaps existing session ${overlap.start_time}–${overlap.end_time} on ${examDate}.`)
    setErrors(found)
    if (found.length) return
    setBusy(true)
    try {
      await createExamSlot(termId, { exam_date: examDate, start_time: startTime, end_time: endTime, label: label.trim() })
      onStatus(`Added exam session on ${examDate} (${startTime}–${endTime}).`)
      slots.reload()
    } catch (reason) {
      setErrors([errorMessage(reason)])
    } finally {
      setBusy(false)
    }
  }

  return <Card title="Exam session editor">
    <div className="stack-gap">
      <ErrorSummary errors={errors} />
      <div className="inline-form">
        <InputField id="ex-date" type="date" label="Exam date" value={examDate} onChange={setExamDate} tooltip="Calendar date of the examination session." />
        <InputField id="ex-start" type="time" label="Start time" value={startTime} onChange={setStartTime} tooltip="Start time (HH:MM)." />
        <InputField id="ex-end" type="time" label="End time" value={endTime} onChange={setEndTime} tooltip="End time (must be after start time; overlapping sessions on the same date are rejected)." />
        <InputField id="ex-label" label="Label" value={label} onChange={setLabel} tooltip="Session label, e.g. Morning session." />
        <Button icon={CirclePlus} onClick={() => void addSession()} disabled={busy}>Add session</Button>
      </div>
      <LoadState loading={slots.loading} error={slots.error} onRetry={slots.reload}>
        {list.length === 0 ? (
          <Notice title="No exam sessions defined for this term">Add examination dates and sessions above.</Notice>
        ) : (
          <DataTable
            rows={list}
            rowKey={(row) => row.exam_slot_id}
            caption="Examination sessions"
            searchText={(row) => `${row.exam_date} ${row.start_time} ${row.end_time} ${row.label}`}
            columns={[
              { key: 'date', label: 'Date', value: (row) => row.exam_date, render: (row) => <strong>{row.exam_date}</strong> },
              { key: 'start', label: 'Start', value: (row) => row.start_time },
              { key: 'end', label: 'End', value: (row) => row.end_time },
              { key: 'label', label: 'Label', value: (row) => row.label || '—' },
            ]}
          />
        )}
      </LoadState>
    </div>
  </Card>
}
