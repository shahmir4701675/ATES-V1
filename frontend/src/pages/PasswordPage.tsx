import { useState } from 'react'
import { Button, Card, InputField, Notice, PageHeader } from '../components/ui'
import { changePassword, errorMessage } from '../services/api'

export function PasswordPage({ onStatus }: { onStatus: (message: string) => void }) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const save = async () => {
    if (next !== confirm) { setError('New passwords must match.'); return }
    setBusy(true); setError('')
    try { await changePassword(current, next); onStatus('Password changed. Sign in again; previous sessions have ended.') }
    catch (reason) { setError(errorMessage(reason)) }
    finally { setBusy(false) }
  }
  return <div className="page-stack"><PageHeader eyebrow="Account" title="Change password" description="Changing your password ends all existing sessions." />
    <Card><form onSubmit={(event) => { event.preventDefault(); void save() }}>
      {error && <Notice tone="error" title="Password could not be changed">{error}</Notice>}
      <InputField id="pw-current" label="Current password" type="password" value={current} onChange={setCurrent} />
      <InputField id="pw-new" label="New password" type="password" value={next} onChange={setNext} tooltip="At least 8 characters, at most 72 UTF-8 bytes." />
      <InputField id="pw-confirm" label="Confirm new password" type="password" value={confirm} onChange={setConfirm} />
      <Button onClick={() => void save()} disabled={busy}>{busy ? 'Saving…' : 'Change password'}</Button>
    </form></Card></div>
}
