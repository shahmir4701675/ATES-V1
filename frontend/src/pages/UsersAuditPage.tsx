import { useState } from 'react'
import { CheckCircle2, CirclePlus, Lock, Pencil, XCircle } from 'lucide-react'
import { Button, Card, ErrorSummary, Field, InputField, LoadState, Notice, PageHeader, SelectField } from '../components/ui'
import { DataTable, Modal } from '../components/Modal'
import { useAsync } from '../hooks/useAsync'
import { errorMessage, getAuditLogMock, getBatches, getInstructors, getUsersMock, saveUserMock } from '../services/api'
import type { AppUser, AppUserInput, UserRole } from '../types'

const ROLES: UserRole[] = ['Administrator', 'Coordinator', 'Approver', 'Faculty', 'Student']
const STATUSES: AppUser['account_status'][] = ['Active', 'Locked', 'Deactivated']

const statusCell = (status: AppUser['account_status']) =>
  status === 'Active' ? (
    <span className="inline-status success"><CheckCircle2 size={14} aria-hidden="true" /> Active</span>
  ) : status === 'Locked' ? (
    <span className="inline-status"><Lock size={14} aria-hidden="true" /> Locked</span>
  ) : (
    <span className="inline-status"><XCircle size={14} aria-hidden="true" /> Deactivated</span>
  )

export function UsersAuditPage({ onStatus }: { onStatus: (message: string) => void }) {
  const [tab, setTab] = useState<'users' | 'audit'>('users')
  const [userFilter, setUserFilter] = useState('')
  const [actionFilter, setActionFilter] = useState('')
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const [editing, setEditing] = useState<{ id: string | null; form: AppUserInput } | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [serverError, setServerError] = useState('')
  const [busy, setBusy] = useState(false)

  const base = useAsync(() => Promise.all([getUsersMock(), getInstructors(), getBatches()]), [])
  const audit = useAsync(() => getAuditLogMock({ user_id: userFilter || undefined, action: actionFilter || undefined, from: fromDate || undefined, to: toDate || undefined }), [userFilter, actionFilter, fromDate, toDate])

  const [users, instructors, batches] = base.data ?? [[], [], []]
  const auditRows = audit.data ?? []
  const actions = [...new Set(auditRows.map((item) => item.action))].sort()

  const instructorLabel = (id: string | null) => instructors.find((item) => item.instructor_id === id)?.full_name ?? ''
  const batchLabel = (id: string | null) => {
    const batch = batches.find((item) => item.batch_id === id)
    return batch ? `${batch.program_code} ${batch.batch_year} · ${batch.section}` : ''
  }

  const openUser = (user?: AppUser) => {
    setErrors({})
    setServerError('')
    setEditing({
      id: user?.user_id ?? null,
      form: user
        ? { username: user.username, full_name: user.full_name, email: user.email, role: user.role, account_status: user.account_status, instructor_id: user.instructor_id, batch_id: user.batch_id, password: '' }
        : { username: '', full_name: '', email: '', role: 'Faculty', account_status: 'Active', instructor_id: instructors[0]?.instructor_id ?? null, batch_id: null, password: '' },
    })
  }

  const save = async () => {
    if (!editing) return
    const { form, id } = editing
    const found: Record<string, string> = {}
    if (!form.username.trim()) found.username = 'User name is required.'
    if (!form.full_name.trim()) found.full_name = 'Full name is required.'
    if (!form.email.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())) found.email = 'Enter a valid e-mail address.'
    if (id === null && (!form.password || form.password.length < 8)) found.password = 'Initial password must be at least 8 characters.'
    if (form.role === 'Faculty' && !form.instructor_id) found.instructor_id = 'Faculty accounts must be linked to an instructor record.'
    if (form.role === 'Student' && !form.batch_id) found.batch_id = 'Student accounts must be linked to a batch.'
    setErrors(found)
    if (Object.keys(found).length) return
    setBusy(true)
    setServerError('')
    try {
      await saveUserMock(id, {
        ...form,
        username: form.username.trim(),
        full_name: form.full_name.trim(),
        email: form.email.trim(),
        instructor_id: form.role === 'Faculty' ? form.instructor_id : null,
        batch_id: form.role === 'Student' ? form.batch_id : null,
      })
      onStatus(`Account '${form.username.trim()}' ${id === null ? 'created' : 'updated'}.`)
      setEditing(null)
      base.reload()
    } catch (reason) {
      setServerError(errorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  const summaryErrors = [...Object.values(errors), ...(serverError ? [serverError] : [])]

  return <div className="page-stack">
    <PageHeader eyebrow="Administration" title="Users and audit log" description="Manage user accounts, role assignments, instructor/batch links and inspect the read-only governance audit trail." />
    <Notice tone="info" title="Awaiting backend authentication routes">
      Account management and the audit log currently use <code>getUsersMock</code>, <code>saveUserMock</code> and <code>getAuditLogMock</code> in the API service until <code>/users</code> and <code>/audit</code> are added on the server.
    </Notice>
    <div className="tabs" role="tablist" aria-label="Administration sections">
      <button type="button" role="tab" aria-selected={tab === 'users'} className="tab" onClick={() => setTab('users')}>User accounts</button>
      <button type="button" role="tab" aria-selected={tab === 'audit'} className="tab" onClick={() => setTab('audit')}>Audit log (read-only)</button>
    </div>

    {tab === 'users' ? (
      <LoadState loading={base.loading} error={base.error} onRetry={base.reload}>
        <Card title="User accounts">
          <DataTable
            rows={users}
            rowKey={(row) => row.user_id}
            caption="User accounts"
            searchText={(row) => `${row.username} ${row.full_name} ${row.email} ${row.role} ${row.account_status}`}
            toolbar={<Button icon={CirclePlus} onClick={() => openUser()}>Add account</Button>}
            columns={[
              { key: 'username', label: 'User name', value: (row) => row.username, render: (row) => <strong>{row.username}</strong> },
              { key: 'name', label: 'Full name', value: (row) => row.full_name },
              { key: 'email', label: 'E-mail', value: (row) => row.email },
              { key: 'role', label: 'Role', value: (row) => row.role },
              { key: 'link', label: 'Instructor / batch link', value: (row) => instructorLabel(row.instructor_id) || batchLabel(row.batch_id) || '—' },
              { key: 'status', label: 'Status', value: (row) => row.account_status, render: (row) => statusCell(row.account_status) },
            ]}
            actions={(row) => <Button variant="secondary" icon={Pencil} onClick={() => openUser(row)} ariaLabel={`Edit ${row.username}`}>Edit</Button>}
          />
        </Card>
      </LoadState>
    ) : (
      <LoadState loading={audit.loading} error={audit.error} onRetry={audit.reload}>
        <Card className="filter-card no-print">
          <div className="filter-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
            <SelectField label="User" id="aud-user" value={userFilter} onChange={setUserFilter} options={[{ value: '', label: 'All users' }, ...users.map((item) => ({ value: item.user_id, label: `${item.username} (${item.full_name})` }))]} />
            <SelectField label="Action" id="aud-action" value={actionFilter} onChange={setActionFilter} options={[{ value: '', label: 'All actions' }, ...actions.map((item) => ({ value: item, label: item }))]} />
            <InputField label="From date" id="aud-from" type="date" required={false} value={fromDate} onChange={setFromDate} tooltip="Filter entries on or after this date." />
            <InputField label="To date" id="aud-to" type="date" required={false} value={toDate} onChange={setToDate} tooltip="Filter entries on or before this date." />
          </div>
        </Card>
        <Card title="Audit log">
          <DataTable
            rows={auditRows}
            rowKey={(row) => row.log_id}
            caption="Read-only system audit log"
            searchText={(row) => `${row.username} ${row.action} ${row.entity_type ?? ''} ${row.details}`}
            columns={[
              { key: 'time', label: 'Timestamp', value: (row) => row.created_at, render: (row) => <span className="tabular">{new Date(row.created_at).toLocaleString('en-GB')}</span> },
              { key: 'user', label: 'User', value: (row) => row.username, render: (row) => <strong>{row.username}</strong> },
              { key: 'action', label: 'Action', value: (row) => row.action, render: (row) => <code>{row.action}</code> },
              { key: 'entity', label: 'Entity', value: (row) => `${row.entity_type ?? ''} ${row.entity_id ?? ''}` },
              { key: 'details', label: 'Details', value: (row) => row.details },
            ]}
          />
        </Card>
      </LoadState>
    )}

    {editing && (
      <Modal
        title={editing.id === null ? 'Add user account' : 'Edit user account'}
        onClose={() => setEditing(null)}
        wide
        footer={<><Button variant="secondary" onClick={() => setEditing(null)}>Cancel</Button><Button onClick={() => void save()} disabled={busy}>{busy ? 'Saving…' : 'Save'}</Button></>}
      >
        <form onSubmit={(event) => { event.preventDefault(); void save() }} noValidate>
          <ErrorSummary errors={summaryErrors} />
          <div className="form-columns">
            <InputField id="usr-username" label="User name" value={editing.form.username} error={errors.username} tooltip="Unique sign-in identifier (up to 40 characters)." onChange={(val) => setEditing({ ...editing, form: { ...editing.form, username: val } })} />
            <InputField id="usr-fullname" label="Full name" value={editing.form.full_name} error={errors.full_name} tooltip="Full display name." onChange={(val) => setEditing({ ...editing, form: { ...editing.form, full_name: val } })} />
            <InputField id="usr-email" label="E-mail" type="email" value={editing.form.email} error={errors.email} tooltip="Unique institutional e-mail address." onChange={(val) => setEditing({ ...editing, form: { ...editing.form, email: val } })} />
            <SelectField label="Role" id="usr-role" value={editing.form.role} onChange={(val) => setEditing({ ...editing, form: { ...editing.form, role: val as UserRole } })} options={ROLES.map((item) => ({ value: item, label: item }))} hint="Determines navigation and permissions." />
            <SelectField label="Account status" id="usr-status" value={editing.form.account_status} onChange={(val) => setEditing({ ...editing, form: { ...editing.form, account_status: val as AppUser['account_status'] } })} options={STATUSES.map((item) => ({ value: item, label: item }))} hint="Active, Locked or Deactivated." />
            {editing.id === null && (
              <InputField id="usr-pass" label="Initial password" type="password" value={editing.form.password ?? ''} error={errors.password} tooltip="Minimum 8 characters." onChange={(val) => setEditing({ ...editing, form: { ...editing.form, password: val } })} />
            )}
            {editing.form.role === 'Faculty' && (
              <Field label="Linked instructor" htmlFor="usr-inst" error={errors.instructor_id} tooltip="Required when the role is Faculty.">
                <select id="usr-inst" value={editing.form.instructor_id ?? ''} onChange={(event) => setEditing({ ...editing, form: { ...editing.form, instructor_id: event.target.value || null } })}>
                  <option value="">Select instructor…</option>
                  {instructors.map((item) => <option key={item.instructor_id} value={item.instructor_id}>{item.full_name} ({item.email})</option>)}
                </select>
              </Field>
            )}
            {editing.form.role === 'Student' && (
              <Field label="Linked batch" htmlFor="usr-batch" error={errors.batch_id} tooltip="Required when the role is Student.">
                <select id="usr-batch" value={editing.form.batch_id ?? ''} onChange={(event) => setEditing({ ...editing, form: { ...editing.form, batch_id: event.target.value || null } })}>
                  <option value="">Select batch…</option>
                  {batches.map((item) => <option key={item.batch_id} value={item.batch_id}>{item.program_code} {item.batch_year} · {item.section}</option>)}
                </select>
              </Field>
            )}
          </div>
        </form>
      </Modal>
    )}
  </div>
}
