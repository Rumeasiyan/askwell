# Askwell

**Ask your own files anything. Nothing leaves your machine.**

**Version:** 0.2 (rewritten 2026-08-10 — supersedes the organisation-focused draft)
**Owner:** Suseenthiran Arulraj Rumeasiyan
**Status:** approved for build

> This document is the business case. It is written to be read by someone deciding whether to use Askwell or invest in it — no implementation detail. For how it is built, see `architecture.md`.

---

## 1. What Askwell is

Askwell is a personal AI that reads your own documents and databases and answers questions about them — running entirely on your own computer.

You point it at your files: PDFs, Word documents, spreadsheets, scanned images, a database dump, a CSV export, or a live connection to a database you already run. It reads them, asks you about anything it finds ambiguous, remembers your answers, and from then on you can ask questions in plain English and get answers with sources attached.

It installs as a desktop application and runs on your own machine. No account required. No files uploaded anywhere. No subscription to start. Open source, so you can check that all of that is true.

When your own files do not have the answer, Askwell says so — and can search the web if you ask it to, in that moment, for that question.

---

## 2. The problem

People accumulate information faster than they can organise it. A consultant has six years of client reports. A researcher has four hundred papers and a spreadsheet of results. A lawyer has case files. A developer has a database nobody documented.

The information is all there. Finding it is the problem — and finding it usually means remembering which file it was in, which is exactly the thing that fails.

Cloud AI tools solve the searching part and create a new problem: uploading the material. For a lot of people that is not a preference, it is a hard stop. Client confidentiality, unpublished research, patient records, contracts under NDA, a database with real customer data in it. These people are not weighing convenience against privacy — they simply cannot upload, so they get no AI help at all.

**Askwell is for them.** The alternative is not ChatGPT; it is opening files one at a time and hoping to remember the right one.

---

## 3. Who it is for

One person, working with their own material.

| | |
| --- | --- |
| **Consultants and analysts** | Years of client work, all confidential. Need to find precedent and reuse prior analysis without breaching an NDA. |
| **Researchers and academics** | Large reading piles plus their own data. Unpublished results cannot be uploaded anywhere. |
| **Lawyers and accountants** | Case and client files under professional privilege. Cloud upload is often prohibited outright. |
| **Developers and data people** | A database nobody documented and no appetite for writing SQL to answer a simple question. |
| **Writers, journalists, archivists** | Interview transcripts, source material, sensitive notes. |

**Askwell is single-user by design.** One person, one machine, one set of files. There are no teams, no shared workspaces, no roles or permissions. That is a scope decision, not an omission — it removes an enormous amount of complexity that a single user gains nothing from, and it means the privacy promise is simple enough to state in one sentence.

---

## 4. How it works, for the person using it

**1 — Add your material.** Drop in files. Import a database dump or a spreadsheet. Or connect to a database you already run, using read-only access.

**2 — Askwell reads it, and asks when it is unsure.** This is the part other tools skip. When it hits something genuinely ambiguous — a column called `st_cd`, a scan it could barely read, two documents that contradict each other — it asks you. Briefly, in plain language, and only when it matters.

**3 — It remembers your answers.** Tell it once that `st_cd` means student status code, and it knows from then on — for every future question and every future file. Askwell gets better at your material the longer you use it, because you taught it.

**4 — Ask questions.** Type or speak. Answers come back with the source attached: which document, which page, the exact passage. Database answers show the query that produced them, so you can check the number rather than trusting it.

**5 — When it does not know, it says so.** If your files do not contain the answer, Askwell tells you that and tells you what it would need. It does not fall back on general knowledge and hope you don't notice. This is the behaviour that makes the rest of it trustworthy.

**6 — Then, if you want, it can look outside.** From that same screen you can send the question to the web, or to a larger cloud model. Both are things you ask for, one question at a time. Askwell never reaches out on its own because it came up short, and anything it finds outside your files is shown separately and labelled as such — never mixed in with your own documents.

---

## 5. What makes it different

Local AI tools that search your documents already exist. Three things separate Askwell.

### It asks, and it remembers

Every other tool ingests silently and does its best with whatever it inferred. Askwell asks about the things it genuinely cannot know — abbreviations, codes, contradictions, unreadable scans — and stores the answers permanently.

This compounds. Month six is materially better than week one, on the same files, because six months of your corrections are in it. No other local tool improves on your data without retraining anything.

### Answers you can check

Every factual claim carries its source: document, page, exact passage. Every database answer shows the query that produced the number. An answer you cannot verify is worth very little when the subject is a client's contract or a patient's record — and the point of citations is not decoration, it is that you can catch it being wrong.

### It admits what it does not know

When your files do not cover a question, Askwell says so. It is the single most-tested behaviour in the product, because a confident wrong answer about your own material is worse than no answer at all — you have no external source to catch it against.

That stays true now that Askwell can search the web. **Searching is something you ask for, never something it does because it came up short.** Askwell tells you your files do not answer the question, and then offers to look further. The difference matters: a tool that quietly reaches outside stops being able to tell you what you actually have.

---

## 6. The privacy promise

**By default, Askwell makes no network connections at all.** Your files, the AI model, the database and the record of everything you asked all sit on your machine. Disconnect from the internet and it works identically. This is verified as part of every release, not asserted.

**Two things can reach outside, and both are deliberate acts.**

*Online AI* — a larger cloud model for a hard question. Bought with credits, enabled per conversation, and Askwell tells you exactly what will be sent before it sends anything.

*Web search* — asked for per question, from the screen where Askwell has just told you your files do not cover it. What goes out is your question. What comes back is shown separately from your own material, labelled, and dated, because a web page can change after the answer and a document on your disk cannot.

Neither is sticky. Neither happens on its own. Turning one on for a question does not turn it on for the next.

**You never hand Askwell an API key from another provider**, and Askwell never asks for one. Credits are bought from us; we handle the provider relationship and the usage limits. That keeps a stolen key from becoming your problem and keeps the cost predictable.

**Local mode remains the default forever.** Online is an upgrade you choose per question, not a direction the product drifts in.

---

## 7. What it costs, and who owns it

**Askwell is open source under Apache-2.0, and free to install.** Unlimited files, unlimited questions, no account, no time limit. Read the code, audit it, fork it, run it forever without paying anyone.

Revenue comes from optional online-AI credits — bought in advance, spent per question, with a limit you set so a bad afternoon cannot produce a surprise bill. That service is the one part that is not open.

### Why open source is not a giveaway here

For a product whose entire claim is *nothing leaves your machine*, **the source is the proof.** A closed-source local AI asking to be trusted is strictly weaker — the user has only a promise. An open one can be audited by anyone, and the people this product is for are exactly the people who will want that, or who know someone who will check for them.

The business is not the code. It is the credit service: the provider contracts, the metering, the billing relationship. Forking the client gives none of that. Someone who wants to run a competing credit business has to go and build a credit business, and the code was never the hard part of that.

### The honest risks

- **Someone forks it and points it at their own credit service.** Nothing prevents this. What protects the position is the trademark, the brand, and the fact that operating a paid inference service means provider contracts, compliance and support — not a weekend's work.
- **The entire revenue line is the optional feature**, and it is built last. Everything shipping first is free and open, so v1 earns nothing. That is deliberate — build the thing people want, charge for the upgrade — but it means adoption has to come first, and the credit system is the business rather than an add-on.
- **Free and open sets a support expectation** that a single maintainer cannot meet. Issue triage and a stated support boundary need to exist before the first release, not after.

## 8. What Askwell is not

- **Not a team or collaboration tool.** Single user, single machine. No sharing, no workspaces, no permissions.
- **Not a cloud service.** There is no hosted version holding your files. Ever. It is an application you install.
- **Not a chatbot builder or prompt tool.**
- **Not a coding assistant.**
- **Not a BI tool.** It answers questions; it does not build dashboards.
- **Not a model trainer.** It runs existing open models. Your corrections are remembered as facts, not by retraining anything.
- **Not multilingual yet.** English only in v1. Tamil, then possibly Sinhala, come later — and the components for both need re-sourcing, see `architecture.md`.

---

## 9. What success looks like

Someone installs Askwell, points it at their real files, and is still using it three months later without being reminded — because it answers questions they would otherwise have spent twenty minutes hunting for, and because it has learned enough about their material to be worth keeping.

Detailed measures in `success-metrics.md`.

---

## 10. Roadmap

Ordered by what makes the product usable soonest, not by what is easiest.

| Stage | What you get |
| ----- | ------------ |
| **1. Ask your documents** | Add files, get cited answers, told honestly when it doesn't know |
| **2. It learns your material** | The clarification loop and permanent memory |
| **3. Ask your data** | Database dumps, spreadsheets, live connections; answers with the query shown |
| **4. Harder questions** | Combining documents and data in one answer, with the reasoning visible |
| **5. Speak to it** | Voice questions and spoken answers |
| **6. Ready to hand out** | Installers, updates, backup and restore, export |
| **7. Online AI credits** | The paid upgrade, with limits and an account |

Stages 1–6 are free and local. Stage 7 is the business.

Build detail, estimates and acceptance criteria: `build-plan.md`.

---

## 11. Still open

*Each is a tracked issue with an owner — a question recorded only here is a question nobody is answering.*

1. **Web search provider** ([#43](https://github.com/Rumeasiyan/askwell/issues/43)). An open-source application cannot ship a shared API key, so the question is who holds one — and that decides whether search is free, metered, or keyless.
2. **Trademark** ([#47](https://github.com/Rumeasiyan/askwell/issues/47)). "Askwell" needs registering if the brand is what protects the position against a fork.
3. **Support boundary** ([#47](https://github.com/Rumeasiyan/askwell/issues/47)). What a single maintainer promises to answer, stated before release rather than discovered afterwards.
4. **Code signing certificates** ([#42](https://github.com/Rumeasiyan/askwell/issues/42)). Apple Developer enrolment and a Windows certificate. Not a decision — a purchase with a lead time.

---

_Name alternatives considered, if Askwell does not survive a trademark check: **SiloQ**, **AnchorQ**, **KeepQ**._
