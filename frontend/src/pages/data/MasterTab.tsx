import { useState } from 'react'
import { CheckCircle2, CirclePlus, Pencil, Power, RotateCcw, XCircle } from 'lucide-react'
import { Button, ErrorSummary, Field, LoadState, Notice } from '../../components/ui'
import { ConfirmDialog, DataTable, Modal, type Column } from '../../components/Modal'
import { useAsync } from '../../hooks/useAsync'
import { errorMessage } from '../../services/api'

export interface FieldDef {
  name: string
  label: string
  type: 'text' | 'number' | 'select' | 'email' | 'date'
  tooltip: string
  options?: Array<{ value: string; label: string }>
  min?: number
  max?: number
  wide?: boolean
  /** Not editable after the record exists (for example keys the server does not allow to change). */
  createOnly?: boolean
}

export type Form = Record<string, string>

export interface MasterConfig<T> {
  noun: string
  plural: string
  idOf: (row: T) => string
  columns: Column<T>[]
  fields: FieldDef[]
  searchText: (row: T) => string
  blank: Form
  toForm: (row: T) => Form
  /** Returns a message per invalid field. Checks that need all rows (unique codes) get them as `rows`. */
  validate: (form: Form, rows: T[], editingId: string | null) => Form
  toPayload: (form: Form) => Record<string, unknown>
  create: (payload: Record<string, unknown>) => Promise<unknown>
  update?: (id: string, payload: Record<string, unknown>) => Promise<unknown>
  /** Soft deactivate (courses, instructors, rooms, batches) or remove where the server has no soft route. */
  deactivate: (id: string) => Promise<void>
  reactivate?: (id: string) => Promise<void>
  isActive?: (row: T) => boolean
  removeLabel?: 'Deactivate' | 'Remove'
  describe: (row: T) => string
}

/** Integer parsing used by validators; returns NaN for blanks and decimals. */
export const toInt = (value: string): number => (/^-?\d+$/.test(value.trim()) ? Number(value) : Number.NaN)
export const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase()

export function StatusCell({ active }: { active: boolean }) {
  return active ? <span className="inline-status success"><CheckCircle2 size={14} aria-hidden="true" /> Active</span> : <span className="inline-status"><XCircle size={14} aria-hidden="true" /> Inactive</span>
}

export function MasterTab<T>({ config, load, readOnly, onStatus, extraToolbar }: { config: MasterConfig<T>; load: () => Promise<T[]>; readOnly: boolean; onStatus: (message: string) => void; extraToolbar?: React.ReactNode }) {
  const { data, loading, error, reload } = useAsync(load, [config.noun])
  const [editing, setEditing] = useState<{ id: string | null; form: Form } | null>(null)
  const [errors, setErrors] = useState<Form>({})
  const [serverError, setServerError] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState<T | null>(null)
  const [actionError, setActionError] = useState('')
  const rows = data ?? []
  const removeLabel = config.removeLabel ?? 'Deactivate'

  const open = (row?: T) => { setErrors({}); setServerError(''); setEditing({ id: row ? config.idOf(row) : null, form: row ? config.toForm(row) : { ...config.blank } }) }
  const submit = async () => {
    if (!editing) return
    const found = config.validate(editing.form, rows, editing.id)
    setErrors(found)
    if (Object.keys(found).length) return
    setBusy(true); setServerError('')
    try {
      const payload = config.toPayload(editing.form)
      if (editing.id === null) await config.create(payload); else await config.update!(editing.id, payload)
      onStatus(`${config.noun} ${editing.id === null ? 'added' : 'updated'}.`)
      setEditing(null)
      reload()
    } catch (reason) { setServerError(errorMessage(reason)) } finally { setBusy(false) }
  }
  const deactivate = async () => {
    if (!confirm) return
    setBusy(true); setActionError('')
    try { await config.deactivate(config.idOf(confirm)); onStatus(`${config.noun} ${removeLabel === 'Remove' ? 'removed' : 'deactivated'}.`); setConfirm(null); reload() }
    catch (reason) { setActionError(errorMessage(reason)) } finally { setBusy(false) }
  }
  const reactivate = async (row: T) => { try { await config.reactivate!(config.idOf(row)); onStatus(`${config.noun} reactivated.`); reload() } catch (reason) { setActionError(errorMessage(reason)) } }

  const columns: Column<T>[] = config.isActive ? [...config.columns, { key: 'status', label: 'Status', value: (row) => (config.isActive!(row) ? 'Active' : 'Inactive'), render: (row) => <StatusCell active={config.isActive!(row)} /> }] : config.columns
  const messages = editing ? [...Object.values(errors), ...(serverError ? [serverError] : [])] : []

  return <LoadState loading={loading} error={error} onRetry={reload}>
    {actionError && <Notice tone="error" title="The action could not be completed">{actionError}</Notice>}
    <DataTable rows={rows} columns={columns} rowKey={config.idOf} searchText={config.searchText} caption={config.plural}
      toolbar={<>{extraToolbar}{!readOnly && <Button icon={CirclePlus} onClick={() => open()}>Add {config.noun.toLowerCase()}</Button>}</>}
      actions={readOnly ? undefined : (row) => <>
        {config.update && <Button variant="secondary" icon={Pencil} onClick={() => open(row)} ariaLabel={`Edit ${config.describe(row)}`}>Edit</Button>}
        {config.isActive && !config.isActive(row) && config.reactivate
          ? <Button variant="secondary" icon={RotateCcw} onClick={() => void reactivate(row)} ariaLabel={`Reactivate ${config.describe(row)}`}>Reactivate</Button>
          : (!config.isActive || config.isActive(row)) && <Button variant="secondary" icon={Power} onClick={() => { setActionError(''); setConfirm(row) }} ariaLabel={`${removeLabel} ${config.describe(row)}`}>{removeLabel}</Button>}
      </>} />
    {editing && <Modal title={`${editing.id === null ? 'Add' : 'Edit'} ${config.noun.toLowerCase()}`} onClose={() => setEditing(null)} wide
      footer={<><Button variant="secondary" onClick={() => setEditing(null)}>Cancel</Button><Button onClick={() => void submit()} disabled={busy}>{busy ? 'Saving…' : 'Save'}</Button></>}>
      <form onSubmit={(event) => { event.preventDefault(); void submit() }} noValidate>
        <ErrorSummary errors={messages} />
        <div className="form-columns">
          {config.fields.map((field) => {
            const id = `${config.noun}-${field.name}`.replace(/\s+/g, '-').toLowerCase()
            const value = editing.form[field.name] ?? ''
            const set = (next: string) => setEditing({ ...editing, form: { ...editing.form, [field.name]: next } })
            const disabled = Boolean(field.createOnly && editing.id !== null)
            return <div key={field.name} className={field.wide ? 'field-wide' : ''}><Field label={field.label} htmlFor={id} tooltip={field.tooltip} hint={field.tooltip} error={errors[field.name]}>
              {field.type === 'select'
                ? <select id={id} value={value} disabled={disabled} aria-invalid={Boolean(errors[field.name])} onChange={(event) => set(event.target.value)}><option value="">Select…</option>{field.options?.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>
                : <input id={id} type={field.type} value={value} min={field.min} max={field.max} disabled={disabled} className={errors[field.name] ? 'input-invalid' : ''} aria-invalid={Boolean(errors[field.name])} onChange={(event) => set(event.target.value)} />}
            </Field></div>
          })}
        </div>
        <button type="submit" className="sr-only" tabIndex={-1}>Save</button>
      </form>
    </Modal>}
    {confirm && <ConfirmDialog title={`${removeLabel} ${config.noun.toLowerCase()}`} confirmLabel={removeLabel} busy={busy} onCancel={() => setConfirm(null)} onConfirm={() => void deactivate()}
      message={<>{actionError && <Notice tone="error" title="Not completed">{actionError}</Notice>}<p>{removeLabel === 'Deactivate' ? `Deactivate ${config.describe(confirm)}? It will no longer be offered in new schedules. Existing schedule versions are not changed, and you can reactivate it later.` : `Remove ${config.describe(confirm)}? This cannot be undone.`}</p></>} />}
  </LoadState>
}
