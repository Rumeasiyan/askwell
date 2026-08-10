# Screen: First run

The first ten minutes, which decide everything. `../success-metrics.md` §4 names install-to-first-answer as the metric most likely to kill the product quietly.

> **This document is the specification. Any mockup is a reference.**

**Route:** `/welcome` — shown until a first source is indexed, then never again.
**Phase:** 1

---

## 1. What it is for

Getting someone from a fresh install to their first cited answer in under 30 minutes, most of which is a model download they cannot avoid.

A free download has no sunk cost holding anyone. Someone who hits friction here closes the window and does not come back, and nothing else in the product gets a chance.

---

## 2. The sequence

Four steps, visible as a list from the start so the end is in sight.

**1 — What this is.** One screen, no scrolling: Askwell reads your files and answers questions about them, on this machine. Nothing is uploaded. It asks when it cannot work something out.

Two facts stated here rather than discovered later: **it works offline**, and **your files stay where they are** — Askwell indexes in place and does not copy your library.

**2 — Check the machine.** Hardware probe → profile (`../architecture.md` §6) with what to expect: *16 GB, no GPU. Answers in about 15 seconds. Voice will work.*

Below the `light` floor it **warns and continues**. Refusing a free download is just a lost user.

**3 — Get the model.** The unavoidable wait. Real progress, real size, real estimate, and honest about the number: *2.4 GB — about 6 minutes on this connection.*

The user can **add sources while this runs**. Ingestion does not need the model, and parallelising the two is most of the reason 30 minutes is achievable.

**4 — Add something and ask.** One source, then a question generated from what was actually ingested — real filenames, real column names.

---

## 3. Interactions

| Action | Result |
| ------ | ------ |
| Skip setup | Straight to Ask. Everything here is reachable later from Settings |
| Add sources during download | Ingestion starts immediately; asking unlocks when the model lands |
| Set a passphrase | Offered once, explained plainly: encrypts your library so a stolen laptop is not a data breach. **Skippable, and the consequence of skipping is stated** |
| Cancel the download | Keeps what has arrived; resumable |

---

## 4. States

| State | What is shown |
| ----- | ------------- |
| **Downloading, no sources yet** | Progress plus a live prompt to add files now rather than wait |
| **Downloading, sources indexing** | Both progress bars. This is the good path and should feel like it |
| **Download failed** | What failed and a retry. Offer a manual model file for someone on a bad connection or an air-gapped machine — this is the install path for the users who need Askwell most |
| **Below hardware floor** | Warned, told what will be slow, allowed to continue |
| **No disk space** | Refused before download, with the space needed |
| **Model ready, no sources** | *"Ready. Add something to ask about."* Not an empty chat box |
| **First answer delivered** | The one celebratory moment: the citation is pointed out explicitly, because the citation is the product and users need to know to click it |
| **Returning before finishing** | Resumes where it stopped, never restarts |

---

## 5. What it must not do

- **No account, no email, no sign-in.** There is nothing to sign into. Any field here would contradict the entire product.
- **No sample or demo corpus.** It teaches the wrong thing — the value is answers about *their* files, and a demo delays that.
- **No feature tour.** The clarification loop introduces itself the first time it asks something.
- **No telemetry consent dialogue**, because there is no telemetry (`../success-metrics.md` §6).

---

## 6. Open

1. **Manual model install** needs a real path — the offline user is a core case and cannot be an afterthought.
2. **Suggested first questions** must come from the corpus without an expensive model call at exactly the moment the machine is busy indexing.
