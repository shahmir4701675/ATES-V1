import { Card, PageHeader } from '../components/ui'
import type { Role } from '../components/AppShell'
import help from '../locales/help.en.json'
import { t } from '../locales'
export function HelpPage({ role }: { role: Role }) {
  return <div className="page-stack">
    <PageHeader eyebrow="Help" title={t('help.title')} description={t('help.timezone')} />
    <Card title={`Your role: ${role}`}><p>{help.intro}</p><ol>{help.roles[role].map((step) => <li key={step}>{step}</li>)}</ol></Card>
    <Card title="Downloads"><ul><li><a href="/help/user-manual.pdf" download>Role-based user manual (PDF)</a></li><li><a href="/help/quick-start.pdf" download>Two-page quick start (PDF)</a></li><li><a href="/help/installation.pdf" download>Installation and administration guide (PDF)</a></li><li><a href="/help/installation.md" download>Installation and administration guide</a></li><li><a href="/help/csv-fields.md" download>CSV field reference and examples</a></li></ul><p>Manual screenshots and full cross-browser/mobile accessibility acceptance are still pending.</p></Card>
    {help.screens.map(([title, body]) => <Card title={title} key={title}><p>{body}</p></Card>)}
  </div>
}
