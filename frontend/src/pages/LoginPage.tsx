import { useState } from 'react'
import { Lock, LogIn } from 'lucide-react'
import { Button, Card, ErrorSummary, InputField, Notice } from '../components/ui'
import { loginMock } from '../services/api'
import type { AppUser } from '../types'

export function LoginPage({ onSuccess, onCancel }: { onSuccess: (user: AppUser) => void; onCancel?: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [authError, setAuthError] = useState('')
  const [lockedMinutes, setLockedMinutes] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    const found: Record<string, string> = {}
    if (!username.trim()) found.username = 'User name is required.'
    if (!password) found.password = 'Password is required.'
    setErrors(found)
    setAuthError('')
    setLockedMinutes(null)
    if (Object.keys(found).length) return
    setBusy(true)
    try {
      const result = await loginMock(username.trim(), password)
      if (!result.ok || !result.user) {
        setAuthError(result.message ?? 'Sign-in failed.')
        setLockedMinutes(result.locked_minutes ?? null)
      } else {
        onSuccess(result.user)
      }
    } finally {
      setBusy(false)
    }
  }

  return <div className="login-wrap">
    <Card className="login-card" title="Sign in to ATES">
      <div className="login-brand">
        <span className="ates-mark">A</span>
        <div><strong>ATES</strong><div className="muted">Auto Timetable / Exam Scheduler</div></div>
      </div>
      <form onSubmit={(event) => { event.preventDefault(); void submit() }} noValidate className="stack-gap">
        <ErrorSummary errors={Object.values(errors)} />
        {authError && (
          <Notice tone="error" title="Sign-in blocked">
            {authError}
            {lockedMinutes !== null && (
              <div><Lock size={13} aria-hidden="true" /> Remaining lock time: <strong>{lockedMinutes} minutes</strong>.</div>
            )}
          </Notice>
        )}
        <InputField id="login-username" label="User name" value={username} error={errors.username} tooltip="Enter your ATES user name (for example aroy, coordinator, approver, mrao, or hbaig to see a locked account)." onChange={setUsername} />
        <InputField id="login-password" label="Password" type="password" value={password} error={errors.password} tooltip="Enter your account password." onChange={setPassword} />
        <p className="subtle-note">Demo accounts: <code>aroy</code> (Administrator), <code>coordinator</code> (Coordinator), <code>approver</code> (Approver), <code>mrao</code> (Faculty), <code>hbaig</code> (Locked student).</p>
        <div className="form-actions">
          {onCancel && <Button variant="secondary" onClick={onCancel}>Cancel</Button>}
          <Button type="submit" icon={LogIn} disabled={busy}>{busy ? 'Signing in…' : 'Log in'}</Button>
        </div>
      </form>
    </Card>
  </div>
}
