import { useEffect, useState } from 'react'
import { AppShell, getAllowedPaths, type Role } from './components/AppShell'
import { AvailabilityPage } from './pages/AvailabilityPage'
import { ConflictReportPage } from './pages/ConflictReportPage'
import { ConstraintsSettingsPage } from './pages/ConstraintsSettingsPage'
import { DashboardPage } from './pages/DashboardPage'
import { DataManagementPage } from './pages/DataManagementPage'
import { ExamSchedulePage } from './pages/ExamSchedulePage'
import { GeneratePage } from './pages/GeneratePage'
import { ImportWizardPage } from './pages/ImportWizardPage'
import { LoginPage } from './pages/LoginPage'
import { PlaceholderPage } from './pages/PlaceholderPage'
import { ReviewPublishPage } from './pages/ReviewPublishPage'
import { TimetablePage } from './pages/TimetablePage'
import { UsersAuditPage } from './pages/UsersAuditPage'
import { API_URL, USE_MOCK } from './services/api'
import type { AppUser } from './types'

const validPaths = [
  '/',
  '/generate',
  '/timetable',
  '/exams',
  '/conflicts',
  '/approvals',
  '/availability',
  '/teaching',
  '/my-schedule',
  '/data',
  '/import',
  '/settings',
  '/users',
  '/login',
]

function useRoute() {
  const [path, setPath] = useState(() => (validPaths.includes(window.location.pathname) ? window.location.pathname : '/'))
  useEffect(() => {
    const onPopState = () => setPath(validPaths.includes(window.location.pathname) ? window.location.pathname : '/')
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])
  const navigate = (nextPath: string) => {
    const safePath = validPaths.includes(nextPath) ? nextPath : '/'
    if (safePath !== window.location.pathname) window.history.pushState({}, '', safePath)
    setPath(safePath)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
  return { path, navigate }
}

export default function App() {
  const { path, navigate } = useRoute()
  const [role, setRole] = useState<Role>('Administrator')
  const [currentUser, setCurrentUser] = useState<AppUser | null>(null)
  const [statusMessage, setStatusMessage] = useState(
    USE_MOCK ? 'System ready · Mock data mode enabled' : `System ready · Connected to ${API_URL}`,
  )
  const notify = (message: string) => setStatusMessage(message)

  useEffect(() => {
    if (!getAllowedPaths(role).includes(path)) {
      navigate('/')
      notify(`Route not available for ${role}. Returned to the dashboard.`)
    }
  }, [path, role])

  const onLoginSuccess = (user: AppUser) => {
    setCurrentUser(user)
    setRole(user.role)
    notify(`Signed in as ${user.full_name} (${user.role}).`)
    navigate('/')
  }

  const page =
    path === '/' ? <DashboardPage onNavigate={navigate} onStatus={notify} />
    : path === '/generate' ? <GeneratePage onNavigate={navigate} onStatus={notify} />
    : path === '/timetable' || path === '/my-schedule' ? <TimetablePage onStatus={notify} role={role} />
    : path === '/exams' ? <ExamSchedulePage onStatus={notify} role={role} />
    : path === '/conflicts' ? <ConflictReportPage onStatus={notify} />
    : path === '/data' ? <DataManagementPage role={role} onNavigate={navigate} onStatus={notify} />
    : path === '/import' ? <ImportWizardPage onNavigate={navigate} onStatus={notify} />
    : path === '/settings' ? <ConstraintsSettingsPage onStatus={notify} />
    : path === '/availability' || path === '/teaching' ? <AvailabilityPage role={role} facultyInstructorId={currentUser?.instructor_id} onStatus={notify} />
    : path === '/approvals' ? <ReviewPublishPage onNavigate={navigate} onStatus={notify} />
    : path === '/users' ? <UsersAuditPage onStatus={notify} />
    : path === '/login' ? <LoginPage onSuccess={onLoginSuccess} onCancel={() => navigate('/')} />
    : <PlaceholderPage path={path} onNavigate={navigate} />

  return (
    <AppShell
      path={path}
      role={role}
      userName={currentUser?.full_name ?? 'Alex Roy'}
      onRoleChange={(nextRole) => {
        setRole(nextRole)
        notify(`Role switched to ${nextRole}. Navigation updated.`)
      }}
      onNavigate={navigate}
      statusMessage={statusMessage}
    >
      {page}
    </AppShell>
  )
}
