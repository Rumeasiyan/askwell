/*
  Minimal navigation bus so a direction can be clicked through like a prototype rather than
  browsed like a gallery. Screens call go('screen-id'); App subscribes and switches screens.

  Deliberately not a router: the harness owns which screen is showing, and a direction should
  not need to know that. This is the smallest thing that lets a rail item, a source card or a
  button behave the way it will in the real product.
*/
type Listener = (screenId: string) => void

const listeners = new Set<Listener>()

export function go(screenId: string) {
  for (const l of listeners) l(screenId)
}

export function onNavigate(l: Listener) {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}
