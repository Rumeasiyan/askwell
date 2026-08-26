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
*/
export const directions: Direction[] = [
  {
    id: 'v1',
    key: '1',
    label: 'V1',
    sub: 'Example Direction',
    screens: [
      { id: 'home', label: 'Home', component: lazy(() => import('../directions/v1/Page')) },
    ],
  },
]
