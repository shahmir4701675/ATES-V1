import { useAsync } from '../hooks/useAsync'
import { useState } from 'react'
import { ArrowLeft, CheckCircle2, Download, FileSpreadsheet, Upload } from 'lucide-react'
import { Button, Card, Notice, PageHeader, SelectField } from '../components/ui'
import { DataTable } from '../components/Modal'
import { IMPORT_SPECS, MAX_IMPORT_BYTES } from '../data/reference'
import { confirmImport, errorMessage, getImportTemplate, getImportHistory, previewImport } from '../services/api'
import type { ImportReport, ImportResult, ImportType } from '../types'

const TYPES = (Object.keys(IMPORT_SPECS) as ImportType[]).map((value) => ({ value, label: IMPORT_SPECS[value].label }))

export function ImportWizardPage({ onNavigate, onStatus }: { onNavigate: (path: string) => void; onStatus: (message: string) => void }) {
  const history = useAsync(getImportHistory, [])
  const [type, setType] = useState<ImportType>('courses')
  const [report, setReport] = useState<ImportReport | null>(null)
  const [choice, setChoice] = useState<'valid_only' | 'cancel'>('valid_only')
  const [done, setDone] = useState<ImportResult | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const step = done ? 4 : report ? 3 : 1
  const spec = IMPORT_SPECS[type]

  const downloadTemplate = async () => {
    const csv = await getImportTemplate(type)
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
    const link = Object.assign(document.createElement('a'), { href: url, download: `${type}-template.csv` })
    link.click()
    URL.revokeObjectURL(url)
    onStatus(`Downloaded ${spec.label.toLowerCase()} CSV template.`)
  }

  const onFileChange = async (file: File | null) => {
    if (!file) return
    setError('')
    setDone(null)
    if (file.size > MAX_IMPORT_BYTES) {
      setError('File exceeds the 10 MB maximum size.')
      return
    }
    setBusy(true)
    try {
      const next = await previewImport(type, file)
      setReport(next)
      setChoice(next.rows_valid > 0 ? 'valid_only' : 'cancel')
      onStatus(`Validated ${file.name}: ${next.rows_valid} valid, ${next.rejected.length} rejected issue(s).`)
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  const confirm = async () => {
    if (!report) return
    setBusy(true)
    setError('')
    try {
      const result = await confirmImport(report.import_id, choice)
      history.reload()
      if (choice === 'cancel') {
        setReport(null)
        onStatus('Import cancelled. No records were written.')
      } else {
        setDone(result)
        onStatus(`Imported ${result.rows_imported} ${spec.label.toLowerCase()} record(s).`)
      }
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  const reset = () => { setReport(null); setDone(null); setError('') }
  const cancelPreview = async () => {
    if (!report) return
    setBusy(true); setError('')
    try {
      await confirmImport(report.import_id, 'cancel')
      history.reload(); reset(); onStatus('The server cancelled this import preview. No master records were written.')
    } catch (reason) { setError(errorMessage(reason)) }
    finally { setBusy(false) }
  }

  return <div className="page-stack">
    <PageHeader
      eyebrow="Master data / Import"
      title="Import wizard"
      description="Choose a master data type, download the CSV template, upload a CSV file up to 10 MB, review the validation report, and confirm."
      actions={<Button variant="secondary" icon={ArrowLeft} onClick={() => onNavigate('/data')}>Back to data management</Button>}
    />
    <ol className="stepper" aria-label="Import progress">
      {['Choose data type', 'Upload CSV', 'Validation report', 'Confirmation'].map((label, index) => {
        const number = index + 1
        const state = step === number ? 'step-current' : step > number ? 'step-done' : ''
        return <li key={label} className={`step ${state}`}><span className="step-number">{number}</span><span>{label}</span></li>
      })}
    </ol>
    {error && <Notice tone="error" title="Import validation error">{error}</Notice>}

    {!report && !done && (
      <section className="section-grid two-columns">
        <Card title="1. Choose data type and template">
          <div className="stack-gap">
            <SelectField label="Data type" id="import-type" value={type} onChange={(value) => { if (busy) return; setType(value as ImportType); reset() }} options={TYPES} hint="Each CSV import applies to one master data table." />
            <div className="subtle-note">
              <FileSpreadsheet size={16} aria-hidden="true" />
              <span>Required columns: <code>{spec.columns.map((column) => column.name).join(', ')}</code></span>
            </div>
            <div><Button variant="secondary" icon={Download} onClick={() => void downloadTemplate()}>Download CSV template</Button></div>
          </div>
        </Card>
        <Card title="2. Upload CSV file">
          <label className="dropzone" htmlFor="csv-upload" title="Select a CSV file up to 10 MB">
            <Upload size={22} aria-hidden="true" />
            <strong>Select a CSV file to validate</strong>
            <span>UTF-8 comma-separated values · maximum size 10 MB</span>
            <input id="csv-upload" type="file" accept=".csv,text/csv" disabled={busy} onChange={(event) => void onFileChange(event.target.files?.[0] ?? null)} />
          </label>
        </Card>
      </section>
    )}

    {report && !done && (
      <Card title={`3. Validation report · ${report.file_name}`}>
        <div className="stack-gap">
          <div className="report-counts">
            <div><span>Total data rows</span><strong className="tabular">{report.rows_total}</strong></div>
            <div><span>Valid rows ready to import</span><strong className="tabular success-text">{report.rows_valid}</strong></div>
            <div><span>Rejected rows</span><strong className="tabular">{report.rows_rejected ?? report.rows_total - report.rows_valid}</strong></div>
            <div><span>Validation issues</span><strong className={`tabular ${report.rejected.length ? 'text-danger' : ''}`}>{report.rejected.length}</strong></div>
          </div>
          {report.rejected.length > 0 ? (
            <DataTable
              rows={report.rejected.map((item, idx) => ({ ...item, id: `${item.line}-${item.column}-${idx}` }))}
              rowKey={(row) => row.id}
              caption="Rejected CSV rows"
              searchText={(row) => `${row.line} ${row.column} ${row.reason}`}
              columns={[
                { key: 'line', label: 'Line', value: (row) => row.line },
                { key: 'column', label: 'Column', value: (row) => row.column, render: (row) => <code>{row.column}</code> },
                { key: 'reason', label: 'Reason', value: (row) => row.reason },
              ]}
            />
          ) : (
            <Notice tone="success" title="All rows passed validation">Every row in {report.file_name} satisfies the schema rules.</Notice>
          )}
          <fieldset className="stack-gap" style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="eyebrow">Resolution</legend>
            <label className={`radio-card ${choice === 'valid_only' ? 'radio-card-selected' : ''}`} title="Import only the rows that passed validation">
              <input type="radio" name="import-mode" checked={choice === 'valid_only'} disabled={report.rows_valid === 0} onChange={() => setChoice('valid_only')} />
              <span><strong>Import valid rows only ({report.rows_valid})</strong><small>Skip rejected rows and write the valid rows to {spec.label.toLowerCase()}.</small></span>
            </label>
            <label className={`radio-card ${choice === 'cancel' ? 'radio-card-selected' : ''}`} title="Cancel the import without writing any rows">
              <input type="radio" name="import-mode" checked={choice === 'cancel'} onChange={() => setChoice('cancel')} />
              <span><strong>Cancel</strong><small>Discard this upload and make no changes.</small></span>
            </label>
          </fieldset>
          <div className="form-actions">
            <Button variant="secondary" onClick={() => void cancelPreview()} disabled={busy}>Cancel</Button>
            <Button onClick={() => void confirm()} disabled={busy || (choice === 'valid_only' && report.rows_valid === 0)}>{busy ? 'Confirming…' : 'Confirm'}</Button>
          </div>
        </div>
      </Card>
    )}

    {done && (
      <Card title="4. Import complete">
        <div className="stack-gap">
          <Notice tone="success" title={`${done.rows_imported} ${spec.label.toLowerCase()} record(s) imported`}>
            <CheckCircle2 size={15} aria-hidden="true" /> Validated rows have been added.
          </Notice>
          <div className="form-actions">
            <Button variant="secondary" onClick={reset}>Import another file</Button>
            <Button onClick={() => onNavigate('/data')}>Open data management</Button>
          </div>
        </div>
      </Card>
    )}
    <Card title="Import history">
      {history.error && <Notice tone="error" title="History could not be loaded">{history.error}</Notice>}
      <DataTable rows={history.data ?? []} rowKey={(row) => String(row.import_id)} searchText={(row) => `${row.file_name} ${row.entity_type}`} caption="Authoritative import history" columns={[
        { key: 'file', label: 'File', value: (row) => row.file_name },
        { key: 'type', label: 'Type', value: (row) => row.entity_type },
        { key: 'total', label: 'Read', value: (row) => row.rows_total },
        { key: 'imported', label: 'Imported', value: (row) => row.rows_imported },
        { key: 'rejected', label: 'Rejected / skipped', value: (row) => row.rows_rejected },
        { key: 'time', label: 'Time', value: (row) => row.imported_at },
      ]} />
    </Card>
  </div>
}
