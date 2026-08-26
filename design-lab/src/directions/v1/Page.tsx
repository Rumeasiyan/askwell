export default function V1Page() {
  return (
    <div
      className="flex min-h-full flex-col items-center justify-center gap-4 p-12 text-center"
      style={{ borderRadius: 'var(--radius)' }}
    >
      <h1
        className="text-5xl font-bold"
        style={{ color: 'var(--color-accent)', fontFamily: 'var(--font-display)' }}
      >
        Direction V1
      </h1>
      <p style={{ color: 'var(--color-muted)', fontFamily: 'var(--font-mono)' }}>
        Replace this page with your direction's real layout. Bind every color/font/radius
        to the CSS custom properties in src/tokens.css so the tweak bar can adjust it live.
      </p>
    </div>
  )
}
