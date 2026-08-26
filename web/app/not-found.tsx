import Link from "next/link";

/**
 * The not-found page.
 *
 * Next ships a default, and it is hardcoded black-on-white with its own
 * typography — so a mistyped address drops the user out of the product
 * entirely, into a page that looks like a framework error. This one is made of
 * the same tokens as everything else, which means it also follows the theme.
 *
 * The shell replaces this with something navigable in M0-SHELL-FE-017. Until
 * then it at least says what happened and does not look broken.
 */
export default function NotFound() {
  return (
    <main className="mx-auto flex max-w-xl flex-col gap-4 p-8">
      <p className="ask-micro">Not found</p>
      <h1 style={{ fontSize: "var(--t-title)", lineHeight: "var(--t-title-lh)" }}>
        There is no page at this address
      </h1>
      <p className="ask-prose" style={{ color: "var(--muted)" }}>
        Askwell serves your own material and nothing else, so this is not a page that
        exists somewhere and failed to load — there is no such page. Check the address.
      </p>
      <Link href="/" className="ask-navigates w-fit border px-3 py-2">
        Back to Askwell
      </Link>
    </main>
  );
}
