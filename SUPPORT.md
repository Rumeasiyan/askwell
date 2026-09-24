# Support

**Askwell is maintained by one person.** No company, no team, no support contract. This page says what that means in practice, so what you expect matches what exists before you need help rather than after.

Askwell shows this page too: **Settings → About → Support**. It is the same file, bundled with the app, so you can read it without a network connection.

## Where to go

| You want to | Go to |
|---|---|
| Report a security problem | **Not an issue.** See [`SECURITY.md`](SECURITY.md). It is private and treated separately |
| Report a bug | Open an issue with the **Bug report** template |
| Ask whether something is intended, or how something works | Open an issue with the **Question** template |
| Suggest a feature | Open an issue with the **Feature request** template. Read `docs/PRD.md` §8 first: it lists what Askwell deliberately is not |
| Understand a decision | `docs/decisions.md`. It records what was rejected and why |

## What is answered

- **Bugs in Askwell itself**, on a supported platform, with a version from a release.
- **Questions about intended behaviour.** Is this meant to happen, what does this setting do, why did it abstain.
- **Anything that breaks one of the ten constraints** in `AGENTS.md` §3: a network call Askwell did not ask you about, SQL that is not a single read reaching your database, an imported dump reaching outside its sandbox, a factual claim with no citation, an answer from general knowledge where Askwell should have said it did not know, or web results shown as if they came from your own files. These are treated as serious, because those constraints are the reason the product exists.

## What is promised

- Issues are read. All of them.
- Security reports are acknowledged within a week.
- Bugs that break one of the constraints above are treated as serious.

## What is not promised

- **A response time on ordinary issues.** One maintainer. Some issues will wait, and some will be closed without a fix.
- **Help with your own database, your own documents or your own hardware.** Askwell runs on a machine nobody else can see, holding material nobody else may read. A database that rejects a query, a server that will not accept a connection, a laptop that runs out of memory, a GPU driver that will not load: these belong with whoever runs that database or supports that machine. What Askwell can answer is whether *Askwell* behaved wrongly given what it was told, and the trace is how you show that.
- **Backwards compatibility before 1.0.** The data model can still change between versions.
- **Support for a model you supplied yourself.** Askwell measures citation and abstention behaviour for the models it ships. Anything else is unmeasured, and the interface says so.
- **Features on request.** A feature request is read and weighed against `docs/PRD.md`. Most will be declined; that is not a judgement on the idea.

This is a free, Apache-2.0 project. If this boundary does not work for your situation, forking is explicitly fine. That is what the licence is for.

## What a good report contains

The single most useful thing is something the maintainer can diagnose without asking you a question first. Each of these is quick to find:

| Include | Where to find it |
|---|---|
| **Version** | Settings → About → Version |
| **Platform** | Your operating system and its version, e.g. *macOS 15.4* or *Windows 11 24H2* or *Fedora 43* |
| **Profile** | Settings → Model and speed → Current profile (*light*, *standard*, *accelerated* or *workstation*) |
| **Trace** | Under the answer that went wrong, open the trace and press **Copy trace**, then paste it into the issue |
| **What you did, what happened, what you expected** | In your own words. Paste exact error text rather than a paraphrase |

**Check the trace before you paste it.** It contains your question and short passages from your own files — that is what makes it useful, and also why it is yours to review first. Remove anything you would not publish. An issue here is public.

Never paste passwords, connection strings or whole documents.

## How issues are triaged

New issues arrive labelled `needs-triage`. They are sorted **in batches, not as they arrive**. The aim is roughly weekly; a busy stretch can mean longer, and this is an aim rather than a deadline.

Triage means one of these happens, and the issue gets the label that says so:

| Outcome | Label |
|---|---|
| Confirmed as a bug in Askwell | `bug`, plus a `constraint:*` label if it breaks one of the ten constraints |
| A question, answered in the issue | `question` |
| A feature request, kept open for consideration | `enhancement` |
| Missing what is needed to diagnose it | `needs-info` — the comment names exactly what is missing, usually the version, the profile or the trace |
| About a user's own database, documents or hardware rather than Askwell | `out-of-scope`, with a pointer to where it belongs |
| Declined, or not going to be fixed | `wontfix`, with a reason |
| Already reported | `duplicate`, with a link |

An issue labelled `needs-info` with no reply after a month is closed. Reopening it with the missing information is always welcome.

A security problem reported as a public issue is removed from public view as soon as it is seen and handled through `SECURITY.md` instead.
