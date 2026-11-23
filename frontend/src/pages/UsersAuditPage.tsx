import { formatTimestamp } from '../locales'
import { useState } from 'react'
import { CheckCircle2, CirclePlus, Lock, Pencil, XCircle } from 'lucide-react'
import { Button, Card, ErrorSummary, Field, InputField, LoadState, PageHeader, SelectField } from '../components/ui'
import { DataTable, Modal } from '../components/Modal'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import { useAsync } from '../hooks/useAsync'
import { errorMessage, getAuditPage, getAuditActions, getBatches, getInstructors, getUsersPage, saveUser } from '../services/api'
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

  const [userPage, setUserPage] = useState(1)
  const [auditPage, setAuditPage] = useState(1)
  const [userQuery, setUserQuery] = useState('')
  const [auditQuery, setAuditQuery] = useState('')
  const [userSort, setUserSort] = useState<{ key: string; dir: 1 | -1 }>({ key: 'user_id', dir: 1 })
  const [auditSort, setAuditSort] = useState<{ key: string; dir: 1 | -1 }>({ key: 'time', dir: -1 })
  const debouncedUserQuery = useDebouncedValue(userQuery)
  const debouncedAuditQuery = useDebouncedValue(auditQuery)
  const debouncedUserFilter = useDebouncedValue(userFilter)
  const base = useAsync(() => Promise.all([getInstructors(), getBatches()]), [])
  const usersPage = useAsync(() => getUsersPage({ page: userPage, q: debouncedUserQuery, sort: userSort.key, direction: userSort.dir === 1 ? 'asc' : 'desc' }), [userPage, debouncedUserQuery, userSort])
  const audit = useAsync(() => tab === 'audit' ? getAuditPage({ page: auditPage, q: debouncedAuditQuery, sort: auditSort.key, direction: auditSort.dir === 1 ? 'asc' : 'desc' }, { user_id: debouncedUserFilter || undefined, action: actionFilter || undefined, from: fromDate || undefined, to: toDate || undefined }) : Promise.resolve({ items: [], total: 0 }), [tab, auditPage, debouncedAuditQuery, auditSort, debouncedUserFilter, actionFilter, fromDate, toDate])
  const auditActions = useAsync(() => tab === 'audit' ? getAuditActions() : Promise.resolve([]), [tab])

  const [instructors, batches] = base.data ?? [[], []]
  const users = usersPage.data?.items ?? []
  const auditRows = audit.data?.items ?? []
  const actions = auditActions.data ?? []

  const instructorLabel = (id: string | null) => instructors.find((item) => item.instructor_id === id)?.full_name ?? ''
  const batchLabel = (id: string | null) => {
    const batch = batches.find((item) => item.batch_id === id)
    return batch ? `${batch.program_code} ${batch.batch_year} Â· ${batch.section}` : ''
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
      await saveUser(id, {
        ...form,
        username: form.username.trim(),
        full_name: form.full_name.trim(),
        email: form.email.trim(),
        instructor_id: form.role === 'Faculty' ? form.instructor_id : null,
        batch_id: form.role === 'Student' ? form.batch_id : null,
      })
      onStatus(`Account '${form.username.trim()}' ${id === null ? 'created' : 'updated'}.`)
      setEditing(null)
      usersPage.reload()
    } catch (reason) {
      setServerError(errorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  const summaryErrors = [...Object.values(errors), ...(serverError ? [serverError] : [])]

  return <div className="page-stack">
    <PageHeader eyebrow="Administration" title="Users and audit log" description="Manage user accounts, role assignments, instructor/batch links and inspect the read-only governance audit trail." />
    <div className="tabs" role="tablist" aria-label="Administration sections">
      <button type="button" role="tab" aria-selected={tab === 'users'} className="tab" onClick={() => setTab('users')}>User accounts</button>
      <button type="button" role="tab" aria-selected={tab === 'audit'} className="tab" onClick={() => setTab('audit')}>Audit log (read-only)</button>
    </div>

    {tab === 'users' ? (
      <LoadState loading={base.loading || (!usersPage.data && usersPage.loading)} error={base.error || usersPage.error} onRetry={() => { base.reload(); usersPage.reload() }}>
        <Card title="User accounts">
          {usersPage.loading && <p role="status">Updating accounts…</p>}
          <DataTable
            rows={users}
            rowKey={(row) => row.user_id}
            caption="User accounts"
            remote={{ page: userPage, total: usersPage.data?.total ?? 0, query: userQuery, sort: userSort, onPage: setUserPage, onQuery: (value) => { setUserQuery(value); setUserPage(1) }, onSort: (key) => { setUserSort({ key, dir: userSort.key === key && userSort.dir === 1 ? -1 : 1 }); setUserPage(1) } }}
            searchText={(row) => `${row.username} ${row.full_name} ${row.email} ${row.role} ${row.account_status}`}
            toolbar={<Button icon={CirclePlus} onClick={() => openUser()}>Add account</Button>}
            columns={[
              { key: 'user_id', label: 'User ID', value: (row) => Number(row.user_id) },
              { key: 'username', label: 'User name', value: (row) => row.username, render: (row) => <strong>{row.username}</strong> },
              { key: 'name', label: 'Full name', value: (row) => row.full_name },
              { key: 'email', label: 'E-mail', value: (row) => row.email },
              { key: 'role', label: 'Role', value: (row) => row.role },
              { key: 'link', sortable: false, label: 'Instructor / batch link', value: (row) => instructorLabel(row.instructor_id) || batchLabel(row.batch_id) || 'â€”' },
              { key: 'status', label: 'Status', value: (row) => row.account_status, render: (row) => statusCell(row.account_status) },
            ]}
            actions={(row) => <Button variant="secondary" icon={Pencil} onClick={() => openUser(row)} ariaLabel={`Edit ${row.username}`}>Edit</Button>}
          />
        </Card>
      </LoadState>
    ) : (
      <LoadState loading={!audit.data && audit.loading} error={audit.error || auditActions.error} onRetry={() => { audit.reload(); auditActions.reload() }}>
        <Card className="filter-card no-print">
          <div className="filter-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
            <InputField label="User ID" id="aud-user" type="number" min={1} required={false} value={userFilter} onChange={(value) => { setUserFilter(value); setAuditPage(1) }} tooltip="Optional account ID, shown in the User accounts table. Empty includes all users." />
            <SelectField label="Action" id="aud-action" value={actionFilter} onChange={(value) => { setActionFilter(value); setAuditPage(1) }} options={[{ value: '', label: 'All actions' }, ...actions.map((item) => ({ value: item, label: item }))]} />
            <InputField label="From date" id="aud-from" type="date" required={false} value={fromDate} onChange={(value) => { setFromDate(value); setAuditPage(1) }} tooltip="Filter entries on or after this date." />
            <InputField label="To date" id="aud-to" type="date" required={false} value={toDate} onChange={(value) => { setToDate(value); setAuditPage(1) }} tooltip="Filter entries on or before this date." />
          </div>
        </Card>
        <Card title="Audit log">
          {audit.loading && <p role="status">Updating audit entries…</p>}
          <DataTable
            rows={auditRows}
            rowKey={(row) => row.log_id}
            caption="Read-only system audit log"
            remote={{ page: auditPage, total: audit.data?.total ?? 0, query: auditQuery, sort: auditSort, onPage: setAuditPage, onQuery: (value) => { setAuditQuery(value); setAuditPage(1) }, onSort: (key) => { setAuditSort({ key, dir: auditSort.key === key && auditSort.dir === 1 ? -1 : 1 }); setAuditPage(1) } }}
            searchText={(row) => `${row.username} ${row.action} ${row.entity_type ?? ''} ${row.details}`}
            columns={[
              { key: 'time', label: 'Timestamp', value: (row) => row.created_at, render: (row) => <span className="tabular">{formatTimestamp(row.created_at)}</span> },
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
        footer={<><Button variant="secondary" onClick={() => setEditing(null)}>Cancel</Button><Button onClick={() => void save()} disabled={busy}>{busy ? 'Savingâ€¦' : 'Save'}</Button></>}
      >
        <form onSubmit={(event) => { event.preventDefault(); void save() }} noValidate>
          <ErrorSummary errors={summaryErrors} />
          <div className="form-columns">
            <InputField id="usr-username" label="User name" value={editing.form.username} error={errors.username} tooltip="Unique sign-in identifier (up to 40 characters)." onChange={(val) => setEditing({ ...editing, form: { ...editing.form, username: val } })} />
            <InputField id="usr-fullname" label="Full name" value={editing.form.full_name} error={errors.full_name} tooltip="Full display name." onChange={(val) => setEditing({ ...editing, form: { ...editing.form, full_name: val } })} />
            <InputField id="usr-email" label="E-mail" type="email" value={editing.form.email} error={errors.email} tooltip="Unique institutional e-mail address." onChange={(val) => setEditing({ ...editing, form: { ...editing.form, email: val } })} />
            <SelectField label="Role" id="usr-role" value={editing.form.role} onChange={(val) => setEditing({ ...editing, form: { ...editing.form, role: val as UserRole } })} options={ROLES.map((item) => ({ value: item, label: item }))} hint="Determines navigation and permissions." />
            <SelectField label="Account status" id="usr-status" value={editing.form.account_status} onChange={(val) => setEditing({ ...editing, form: { ...editing.form, account_status: val as AppUser['account_status'] } })} options={STATUSES.map((item) => ({ value: item, label: item }))} hint="Active, Locked or Deactivated." />
            {(
              <InputField id="usr-pass" label={editing.id === null ? "Initial password" : "Reset password (optional)"} type="password" value={editing.form.password ?? ''} error={errors.password} tooltip="Minimum 8 characters." onChange={(val) => setEditing({ ...editing, form: { ...editing.form, password: val } })} />
            )}
            {editing.form.role === 'Faculty' && (
              <Field label="Linked instructor" htmlFor="usr-inst" error={errors.instructor_id} tooltip="Required when the role is Faculty.">
                <select id="usr-inst" value={editing.form.instructor_id ?? ''} onChange={(event) => setEditing({ ...editing, form: { ...editing.form, instructor_id: event.target.value || null } })}>
                  <option value="">Select instructorâ€¦</option>
                  {instructors.map((item) => <option key={item.instructor_id} value={item.instructor_id}>{item.full_name} ({item.email})</option>)}
                </select>
              </Field>
            )}
            {editing.form.role === 'Student' && (
              <Field label="Linked batch" htmlFor="usr-batch" error={errors.batch_id} tooltip="Required when the role is Student.">
                <select id="usr-batch" value={editing.form.batch_id ?? ''} onChange={(event) => setEditing({ ...editing, form: { ...editing.form, batch_id: event.target.value || null } })}>
                  <option value="">Select batchâ€¦</option>
                  {batches.map((item) => <option key={item.batch_id} value={item.batch_id}>{item.program_code} {item.batch_year} Â· {item.section}</option>)}
                </select>
              </Field>
            )}
          </div>
        </form>
      </Modal>
    )}
  </div>
}
