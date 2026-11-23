import type { LucideIcon } from 'lucide-react'
import { useState } from 'react'
import { AlertTriangle, CheckCircle2, CircleAlert, Clock3, Download, Info, Printer, XCircle } from 'lucide-react'
import type { ScheduleStatus } from '../types'

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description?: string; actions?: React.ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <div className="breadcrumb"><span>ATES</span><span className="breadcrumb-separator">/</span><span>{eyebrow}</span></div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </div>
  )
}

const statusMap: Record<string, { icon: LucideIcon; className: string }> = {
  Draft: { icon: Clock3, className: 'status-neutral' },
  Generating: { icon: Clock3, className: 'status-warning' },
  Infeasible: { icon: CircleAlert, className: 'status-danger' },
  Generated: { icon: CheckCircle2, className: 'status-success' },
  Published: { icon: CheckCircle2, className: 'status-success' },
  Archived: { icon: Info, className: 'status-neutral' },
  Optimal: { icon: CheckCircle2, className: 'status-success' },
  Feasible: { icon: CheckCircle2, className: 'status-success' },
  Running: { icon: Clock3, className: 'status-warning' },
  Stopped: { icon: XCircle, className: 'status-danger' },
}

export function StatusBadge({ status, label }: { status: ScheduleStatus | string; label?: string }) {
  const mapped = statusMap[status] ?? { icon: Info, className: 'status-neutral' }
  const Icon = mapped.icon
  return <span className={`status-badge ${mapped.className}`}><Icon size={14} aria-hidden="true" /><span>{label ?? status}</span></span>
}

export function Button({ children, variant = 'primary', icon: Icon, type = 'button', onClick, disabled, className = '', ariaLabel }: { children: React.ReactNode; variant?: 'primary' | 'secondary' | 'danger' | 'ghost'; icon?: LucideIcon; type?: 'button' | 'submit' | 'reset'; onClick?: () => void; disabled?: boolean; className?: string; ariaLabel?: string }) {
  return <button type={type} className={`button button-${variant} ${className}`} onClick={onClick} disabled={disabled} aria-label={ariaLabel}>{Icon && <Icon size={16} aria-hidden="true" />}{children}</button>
}

export function Card({ children, className = '', title, actions }: { children: React.ReactNode; className?: string; title?: string; actions?: React.ReactNode }) {
  return <section className={`card ${className}`}>{(title || actions) && <div className="card-header">{title && <h2>{title}</h2>}{actions && <div className="card-actions">{actions}</div>}</div>}{children}</section>
}

export function Field({ label, htmlFor, hint, error, children, tooltip }: { label: string; htmlFor?: string; hint?: string; error?: string; children: React.ReactNode; tooltip?: string }) {
  return <div className="field" title={tooltip ?? hint ?? label}><label htmlFor={htmlFor}>{label}</label>{children}{hint && !error && <div id={htmlFor ? `${htmlFor}-hint` : undefined} className="field-hint">{hint}</div>}{error && <div id={htmlFor ? `${htmlFor}-error` : undefined} className="field-error" role="alert"><AlertTriangle size={14} aria-hidden="true" />{error}</div>}</div>
}

export function InputField({ label, id, value, onChange, type = 'text', error, hint, tooltip, min, max, step, disabled, required = true, placeholder }: { label: string; id: string; value: string | number; onChange: (value: string) => void; type?: string; error?: string; hint?: string; tooltip?: string; min?: number | string; max?: number | string; step?: number; disabled?: boolean; required?: boolean; placeholder?: string }) {
  return <Field label={required ? label : `${label} (optional)`} htmlFor={id} hint={hint} error={error} tooltip={tooltip}><input id={id} type={type} value={value} min={min} max={max} step={step} disabled={disabled} placeholder={placeholder} required={required} aria-required={required} aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined} onChange={(event) => onChange(event.target.value)} className={error ? 'input-invalid' : ''} /></Field>
}

export type NoticeTone = 'info' | 'success' | 'warning' | 'error'
const noticeIcons = { info: Info, success: CheckCircle2, warning: AlertTriangle, error: CircleAlert }
/** Message block that uses both colour and an icon (SRS GUI standard 4). */
export function Notice({ tone = 'info', title, children, action }: { tone?: NoticeTone; title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  const Icon = noticeIcons[tone]
  return <div className={`notice notice-${tone}`} role={tone === 'error' || tone === 'warning' ? 'alert' : 'status'}><Icon size={18} aria-hidden="true" /><div><strong>{title}</strong>{children && <p>{children}</p>}</div>{action}</div>
}

/** Summary at the top of a form; each message is also shown beside its field. */
export function ErrorSummary({ errors }: { errors: string[] }) {
  if (!errors.length) return null
  return <div className="validation-summary" role="alert"><AlertTriangle size={18} aria-hidden="true" /><div><strong>Review {errors.length === 1 ? 'one problem' : `${errors.length} problems`} before saving</strong><ul>{errors.map((message) => <li key={message}>{message}</li>)}</ul></div></div>
}

/** Standard loading / error / retry wrapper for api-backed screens. */
export function LoadingSkeleton({ label = 'Loading data…' }: { label?: string }) {
  return <div className="loading-skeleton" role="status" aria-live="polite" aria-busy="true"><span className="sr-only">{label}</span><div className="skeleton-line skeleton-heading" aria-hidden="true" /><div className="skeleton-line" aria-hidden="true" /><div className="skeleton-line" aria-hidden="true" /><div className="skeleton-line" aria-hidden="true" /></div>
}

export function LoadState({ loading, error, onRetry, children }: { loading: boolean; error: string; onRetry: () => void; children: React.ReactNode }) {
  if (error) return <Notice tone="error" title="Data could not be loaded" action={<button type="button" onClick={onRetry}>Retry</button>}>{error}</Notice>
  if (loading) return <LoadingSkeleton />
  return <>{children}</>
}

export function Switch({ checked, onChange, label, disabled, locked, id }: { checked: boolean; onChange: (value: boolean) => void; label: string; disabled?: boolean; locked?: boolean; id: string }) {
  return <button id={id} type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled || locked} className={`switch ${checked ? 'switch-on' : ''}`} onClick={() => onChange(!checked)} title={locked ? 'Mandatory constraint: cannot be switched off' : label}><span className="switch-knob" /><span className="switch-text">{checked ? 'On' : 'Off'}</span></button>
}

export function SelectField({ label, value, onChange, options, hint, id }: { label: string; value: string; onChange: (value: string) => void; options: Array<{ value: string; label: string }>; hint?: string; id?: string }) {
  const selectId = id ?? label.toLowerCase().replace(/ /g, '-')
  return <Field label={label} htmlFor={selectId} hint={hint}><select id={selectId} value={value} aria-describedby={hint ? `${selectId}-hint` : undefined} onChange={(event) => onChange(event.target.value)}>{options.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}</select></Field>
}

export function StatCard({ label, value, detail, icon: Icon }: { label: string; value: string | number; detail: string; icon: LucideIcon }) {
  return <div className="stat-card"><div className="stat-icon"><Icon size={19} aria-hidden="true" /></div><div><div className="stat-label">{label}</div><div className="stat-value tabular">{value}</div><div className="stat-detail">{detail}</div></div></div>
}

export function ExportActions({ onStatus, onExport, disabled = false, allowGrouped = false }: { onStatus: (message: string) => void; onExport: (format: 'csv' | 'pdf', groupBy?: 'batch' | 'instructor') => Promise<void>; disabled?: boolean; allowGrouped?: boolean }) {
  const [busy, setBusy] = useState(false)
  const run = async (format: 'csv' | 'pdf', groupBy?: 'batch' | 'instructor') => {
    setBusy(true)
    try { await onExport(format, groupBy); onStatus(`${format.toUpperCase()} download started.`) }
    catch (error) { onStatus(error instanceof Error ? error.message : 'Export failed.') }
    finally { setBusy(false) }
  }
  return <div className="export-actions no-print"><Button variant="secondary" icon={Download} disabled={disabled || busy} onClick={() => void run('csv')}>Export CSV</Button><Button variant="secondary" icon={Printer} disabled={disabled || busy} onClick={() => void run('pdf')}>Export PDF</Button>{allowGrouped && <><Button variant="secondary" disabled={disabled || busy} onClick={() => void run('pdf', 'batch')}>PDF by batch</Button><Button variant="secondary" disabled={disabled || busy} onClick={() => void run('pdf', 'instructor')}>PDF by instructor</Button></>}</div>
}
