import { lazy, type ComponentType, type LazyExoticComponent } from 'react'

export interface Screen {
  id: string
  label: string
  component: LazyExoticComponent<ComponentType>
}

export interface Direction {
  id: string
  key: string // number-key shortcut, e.g. "1" (shortcuts only go up to "9")
  label: string
  sub?: string
  screens: Screen[] // first entry is the default screen shown when the direction opens
}

/*
  Add one entry per direction (see PROMPT_TEMPLATE.md). Each direction is its own set of
  screens under src/directions/<id>/ — screens[0] is conventionally Page.tsx, additional
  screens live in src/directions/<id>/screens/<screenId>.tsx. Committed fully to its own
  aesthetic — do not blend directions inside one component. Use scripts/new-direction.mjs
  and scripts/new-screen.mjs instead of hand-editing this file.

  "instrument" is Askwell's committed direction, described in docs/ux/design-system.md.
  Alternatives belong in a new direction, judged against this one — not blended into it.
*/

const s = (id: string, label: string, load: () => Promise<{ default: ComponentType }>): Screen => ({
  id, label, component: lazy(load),
})

export const directions: Direction[] = [
  {
    id: 'instrument',
    key: '1',
    label: 'Instrument',
    sub: 'Provenance margin · epistemic colour',
    screens: [
      // — asking, the core loop
      s('ask-answered', 'Ask · answered', () => import('../directions/instrument/Page')),
      s('ask-thinking', 'Ask · working', () => import('../directions/instrument/screens/ask-thinking')),
      s('ask-abstained', 'Ask · didn’t know', () => import('../directions/instrument/screens/ask-abstained')),
      s('ask-partial', 'Ask · partial & conflict', () => import('../directions/instrument/screens/ask-partial')),
      s('ask-clarify-inline', 'Ask · asks you first', () => import('../directions/instrument/screens/ask-clarify-inline')),
      s('ask-empty', 'Ask · nothing yet', () => import('../directions/instrument/screens/ask-empty')),
      // — asking your data
      s('sql-answer', 'Data · answered', () => import('../directions/instrument/screens/sql-answer')),
      s('sql-rejected', 'Data · refused', () => import('../directions/instrument/screens/sql-rejected')),
      // — following a citation
      s('source-viewer', 'Source · citation', () => import('../directions/instrument/screens/source-viewer')),
      s('source-missing', 'Source · moved & deleted', () => import('../directions/instrument/screens/source-missing')),
      // — adding material
      s('add-source', 'Add · choose', () => import('../directions/instrument/screens/add-source')),
      s('add-indexing', 'Add · reading', () => import('../directions/instrument/screens/add-indexing')),
      s('add-csv-review', 'Add · CSV review', () => import('../directions/instrument/screens/add-csv-review')),
      s('add-dump', 'Add · dump sandbox', () => import('../directions/instrument/screens/add-dump')),
      s('connect-db', 'Add · connect database', () => import('../directions/instrument/screens/connect-db')),
      s('library', 'Library', () => import('../directions/instrument/screens/library')),
      // — the differentiator
      s('clarifications', 'Clarifications', () => import('../directions/instrument/screens/clarifications')),
      s('clarifications-empty', 'Clarifications · none', () => import('../directions/instrument/screens/clarifications-empty')),
      s('memory', 'Memory', () => import('../directions/instrument/screens/memory')),
      // — showing the working
      s('trace', 'Trace', () => import('../directions/instrument/screens/trace')),
      s('trace-abstention', 'Trace · near miss', () => import('../directions/instrument/screens/trace-abstention')),
      s('usage', 'How it’s going', () => import('../directions/instrument/screens/usage')),
      s('conversations', 'History', () => import('../directions/instrument/screens/conversations')),
      // — voice
      s('voice', 'Voice', () => import('../directions/instrument/screens/voice')),
      s('voice-states', 'Voice · edge cases', () => import('../directions/instrument/screens/voice-states')),
      // — getting started
      s('first-run', 'First run · what it is', () => import('../directions/instrument/screens/first-run')),
      s('first-run-probe', 'First run · this machine', () => import('../directions/instrument/screens/first-run-probe')),
      s('first-run-download', 'First run · model', () => import('../directions/instrument/screens/first-run-download')),
      s('passphrase-unlock', 'Locked', () => import('../directions/instrument/screens/passphrase-unlock')),
      s('model-unavailable', 'Assistant down', () => import('../directions/instrument/screens/model-unavailable')),
      // — settings
      s('settings-model', 'Settings · model', () => import('../directions/instrument/screens/settings-model')),
      s('settings-privacy', 'Settings · privacy', () => import('../directions/instrument/screens/settings-privacy')),
      s('settings-storage', 'Settings · storage', () => import('../directions/instrument/screens/settings-storage')),
      s('settings-data', 'Settings · your data', () => import('../directions/instrument/screens/settings-data')),
      s('settings-online', 'Settings · online AI', () => import('../directions/instrument/screens/settings-online')),
      s('settings-about', 'Settings · about', () => import('../directions/instrument/screens/settings-about')),
    ],
  },
]
