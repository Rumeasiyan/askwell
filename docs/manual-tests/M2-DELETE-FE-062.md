# Manual test — M2-DELETE-FE-062, deletion confirmation and the deleted-source citation card

**Ticket:** `M2-DELETE-FE-062` — Deletion confirmation states the three facts before it commits; a deleted source stays listed, greyed and filterable; citations to it render as deleted everywhere they can appear.
**Version under test:** `0.2.49`
**Time:** about 20 minutes, plus a first stack build
**Who can run it:** anyone who can click through a web page.

**What is being checked.** That the delete confirmation names the source and states all three facts (file untouched, content gone, old citations degrade honestly); that a deleted row stays in the library, greyed, and can be filtered in/out without hiding other rows; that a citation card for a deleted source renders as deleted with a date and is not clickable, both in the margin and inline; that the document viewer shows the deleted state, including when the deletion happens while that document is already open.

**Where this stops on purpose.** No undo, no bulk delete, no archive view — see Known gaps.

---

## Before you start

You need a terminal and Podman, and one small text file to index.

### 1. Make a file to test with

```
mkdir -p ~/askwell-test/material
cd ~/askwell-test/material
printf '%s\n' '%PDF-1.7' 'The Meridian agreement renews automatically every twelve months unless either party gives ninety days notice.' > meridian-contract.pdf
```

### 2. Point Askwell at the folder and bring the stack up

In `.env`, set `ASKWELL_ROOTS_MOUNT` to the absolute path of `~/askwell-test/material`, then:

```
podman compose up -d
scripts/dev.sh inference
```

Leave the inference terminal running.

### 3. Open Askwell and index the file

Open `http://127.0.0.1:8000`. Click **Add a source** in the sidebar, add the `~/askwell-test/material` folder, and wait until the **Library** screen shows `meridian-contract.pdf` as **Ready** rather than queued or indexing.

---

## The walkthrough

### 4. Ask a question that cites the file, before deleting anything

Click **Ask** in the sidebar. Type "What is the notice period for the Meridian agreement?" and send it. **Expect:** an answer streams in, and a citation card for `meridian-contract.pdf` appears in the right-hand margin (or, on a narrow window, inline below the answer) with a passage quoting "ninety days notice." Leave this browser tab open — you will come back to it in step 9.

### 5. Open the source viewer for this file in a second tab

Click the citation card from step 4. **Expect:** a new page opens showing the document viewer for `meridian-contract.pdf`. Keep this tab open too — you will use it in step 8 to check the "deleted while open" edge case.

### 6. Go to the library and start deleting

Switch back to the first tab (or open a new one) and click **Library** in the sidebar. Find the `meridian-contract.pdf` row. **Expect:** it shows status **Ready**, with **Re-index** and **Delete** buttons beneath it.

Click **Delete**.

**Expect** the row expands in place to show this exact confirmation text, with the filename bolded:

> Delete **meridian-contract.pdf**? The file on your disk is untouched. Askwell forgets its contents and stops using it in answers. Past answers that cited it will show it as deleted rather than breaking.

Confirm all three facts are present: the original file is safe, the content is genuinely removed from Askwell, and old citations degrade rather than break. Two buttons appear: **Delete it** and **Not now**.

### 7. Back out once, then commit

Click **Not now**. **Expect:** the confirmation collapses back to the plain **Delete** button, and the row is unchanged.

Click **Delete** again, then click **Delete it**. **Expect:** the button briefly reads "Deleting…", then the whole row updates: its status badge changes to **Deleted**, the row's opacity visibly dims (greyed), the added-date/clarification line is replaced by "Deleted" followed by today's date, and the **Re-index**/**Delete** buttons disappear entirely — there is nothing left to act on for a deleted row.

### 8. Check the open viewer updates on its own

Switch to the second tab from step 5, still showing the `meridian-contract.pdf` viewer. **Do not reload it.** **Expect:** within a few seconds it updates on its own to a deleted notice reading "Deleted on `<today's date>`. Askwell no longer has the contents." — the previously-rendered PDF content is replaced by this notice rather than left on screen.

### 9. Check the earlier answer's citation card degrades

Switch to the first tab from step 4, which still shows the original answer and its citation card for `meridian-contract.pdf`. **Do not re-ask the question.** **Expect:** the card itself updates from the live quoted passage to a greyed card reading `meridian-contract.pdf` with the line "Deleted on `<today's date>`. Askwell no longer has the contents." Confirm the card is **not clickable** — hovering shows no pointer/link affordance, and clicking it does nothing (no navigation, no viewer opens).

### 10. Filter the deleted row out, then back in

Go to **Library**. **Expect:** by default the **Show deleted** checkbox at the top is unchecked, and `meridian-contract.pdf` is not in the list at all (deleted is filtered out by default).

Check **Show deleted**. **Expect:** the greyed `meridian-contract.pdf` row reappears.

### 11. Confirm filtering deleted out does not hide a newly-added source

With **Show deleted** still checked, copy the test file to a second name and add it:

```
cp ~/askwell-test/material/meridian-contract.pdf ~/askwell-test/material/second-contract.pdf
```

Go to **Add a source**, add `~/askwell-test/material/second-contract.pdf`, and wait for it to reach **Ready** in the Library. Now uncheck **Show deleted** again. **Expect:** `meridian-contract.pdf` disappears, but `second-contract.pdf` remains visible and Ready — the deleted filter only ever hides deleted rows, never a newer one.

### 12. Reach the viewer's deleted state a different way

With the first-tab viewer for `meridian-contract.pdf` from step 5 now showing "Deleted on…", refresh the page (simulating arriving at the URL fresh rather than watching it update live). **Expect:** the same deleted notice with the same date renders immediately on load — the viewer states the deletion date whether it observed the deletion live or is opened after the fact.

---

## Known gaps

- **No undo.** Once confirmed, deletion is final in the interface — there is no "undo" affordance and no restore path from the Library.
- **No bulk delete.** Only one source at a time, from its own row.
- **No archive view.** A deleted source's only visibility is the greyed row in the ordinary Library list with **Show deleted** checked — there is no separate screen listing only deleted sources.
- **Analytics are local-only by design (C1):** nothing about a deletion is transmitted anywhere; there is no way to observe this from outside the running instance, so this walkthrough does not attempt to check it.
