# Manual test — M8-KEY-FE-174, entering, replacing and removing the provider key

**Ticket:** `M8-KEY-FE-174`. **Settings → Online AI** now has a **Your key** part. Before you can
paste anything, it says what the key is for, when it is used and where it goes. Below the field
it says how the key is kept, and under **What it costs** it says the bill is between you and
your provider. You can add a key, and after that the screen says which provider it is for but
never shows the key again. You can replace it or remove it. Each button says beforehand what it
does to a conversation that is using online AI. A key that is only spaces, or has a space or
line break in it, is refused in place with the reason. On an install with a passphrase that has
not been entered this session, adding a key asks for the passphrase first.

**Version under test:** `0.7.44`. Run `cat VERSION` and update this line if the version has moved
on.

**Time:** about 35 minutes. Most of it is waiting for one file to index, one local answer on CPU,
and two restarts.

**Who can run it:** anyone with a browser and a terminal. Every Askwell screen is reached by
clicking, starting from Askwell's front page. The terminal only starts Askwell, restarts it, and
reads records and logs that no screen shows yet. Those steps are labelled **Stand-in**.

**What is being checked.**

- `web/components/settings/online-key.tsx`: the key control. It has an unset state, an entry
  form, a set state, replace, remove, and the passphrase prompt.
- `web/lib/online-key.ts`: the wording, and `entryProblem`, which refuses whitespace before
  anything is sent.
- `web/components/settings/online-ai.tsx`: where the key sits in the Online AI section, with
  its explanation above the field.
- `web/lib/passphrase.ts`: `unlockPassphrase`, which this screen is the first to call.
- The server side (`GET`/`PUT`/`DELETE /settings/online-key`) is `M8-KEY-BE-173`'s and has its
  own manual test. Here it is only observed through the screen.

---

## Read this first

**No online question can be sent yet, by anyone.** Every online send is refused until the owner
decides the wording of what the provider receives (#737). So this test proves that the key is
stored, shown correctly, replaced and removed. It cannot prove that the key works with a real
provider. The section says this too, under **What leaves this machine**.

**Nothing leaves this machine during this test.** The provider below, `api.provider.example:443`,
is a made-up name that does not exist. **Do not** enter a real key for a real provider. The key
used throughout is a made-up value called the **sentinel**:

```
ASKWELL-SENTINEL-KEY-7f3c9e21d4
```

It is long and unusual, so a search for it cannot match anything by accident. **If you see the
sentinel, or any part of it, anywhere on screen after you have pressed Save, that is a defect.**
Report the step number and where it appeared.

---

## Before you start

> **Warning: the cold start below deletes everything this Askwell stack holds.** That means
> sources, memory, conversations, the audit log and settings. Your original files are not touched.
> On the shared development machine, check that nobody needs what the stack holds now. If you are
> unsure, use **Settings → Your data → Export everything** first.

### 1. One test file

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. Check it:

```
cd ~/external/quantum-plus/askwell
grep ASKWELL_ROOTS_MOUNT .env
```

If it is empty, or does not contain `/tmp`, set `ASKWELL_ROOTS_MOUNT=/tmp`. Then copy one file from
the fixture corpus:

```
rm -rf /tmp/askwell-test-174
mkdir -p /tmp/askwell-test-174/files
cp eval/fixtures/corpus/handbook_a.pdf /tmp/askwell-test-174/files/
ls /tmp/askwell-test-174/files
```

**You should see:** `handbook_a.pdf`.

Also check `grep -n "ONLINE_AI_DESTINATION\|ONLINE_AI_MODEL" .env` prints nothing. If it prints
anything, delete those lines. Nothing reads them since `M8-KEY-BE-173`.

### 2. Start Askwell from nothing

```
podman compose down -v
scripts/dev.sh web-build
scripts/dev.sh build-api
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** the volumes removed, both builds finish with no red error text, the containers
start, and the migration finish without an error. Do not skip either build. The screen under test
is built into `web/out` and served from the API image. Without both builds, the old Settings
screen is what you will see.

In a **second** terminal, start the model on the host and leave it running:

```
scripts/dev.sh inference
```

**You should see:** the supervisor report that the model and the embedding model are ready.

---

## Part A — cold start, and the section before a key

1. Open a **private or fresh-profile** browser window, so no earlier session and no saved password
   carries over. Open `http://127.0.0.1:8000`. ☐

   **You should see:** the welcome screen, "Welcome to Askwell", with a **Get started** button. If
   you see the **Ask** screen instead, the stack was not cleared. Go back to *Before you start*,
   step 2.

2. Click **Get started** and follow the steps until one offers to add material. **Do not set a
   passphrase here** if the welcome steps offer one. Part E sets one on purpose. ☐

   **You should see:** a step with **Choose files** and **Choose a folder**.

3. Click **Choose files**. Open `/tmp/askwell-test-174/files`, select `handbook_a.pdf` and
   confirm. When asked **"Which folder are these files in?"**, type `/tmp/askwell-test-174/files`
   and click **Add them**. If a note offers to nominate the folder (or a parent), click it and
   then click **Add them** again. Finish the welcome steps. Skipping an optional step is fine. ☐

   **You should see:** the file accepted, with no red "Not added" note.

4. Click **Library** in the rail on the left. Wait until `handbook_a.pdf` says **ready**. ☐

5. Click **Ask** in the rail. Type `What is the notice period for resigning at Meridian Loom?` and
   press **Enter**. Wait for the answer. On CPU this can take a minute or two. ☐

   **You should see:** an answer saying sixty-three days, with a source card naming
   `handbook_a.pdf`, page 2. The top line reads `Askwell 0.7.44 · nothing leaves this machine`.
   This confirms the rest of the product still works before you touch the key.

6. Click the **Local** button to the left of **Ask**. ☐

   **You should see:** it stays **Local**, and beside it: **"Online AI is not available: no provider
   key is stored, so there is no provider to send to. Add one in Settings. Nothing has left this
   machine."**

7. Click **Settings** in the rail. Scroll to **Online AI**. It is the second section, after
   **Model and speed**. **Read it from the top as a first-time reader would**, before clicking
   anything. ☐

   **You should see,** in this order:

   - *"There is no switch here. Online AI is turned on for one conversation at a time, with the
     switch beside that conversation's Ask button, and every new conversation starts local."*
   - **What it is**: two paragraphs. One says it is a larger cloud model and an escape hatch, not
     a tier. The other says it is chosen per conversation.
   - **Your key**, and under it, **before any field or button**:
     *"The key lets Askwell ask a larger model at a provider you choose. It is used only in a
     conversation you have switched to online yourself, and only after that conversation has told
     you exactly what a question will send and you have agreed. It goes to the provider address
     you enter below and nowhere else. Every other conversation, and everything else Askwell does,
     stays on this machine and never uses it."*
   - *"Any provider that offers an OpenAI-compatible chat API."*
   - *"No key is set. Online AI cannot be switched on in any conversation."* and one button,
     **Add a key**.
   - *"The key is stored encrypted on this machine, never shown again after you save it, never
     logged and never exported. Askwell does not check it with the provider when you save it, so a
     mistyped key shows up only when an online question is refused."*
   - **What it costs**: *"What online AI costs is between you and your provider. Askwell sells
     nothing, sees no bill and takes no part in it."*
   - **What leaves this machine**: says the statement of what leaves is made in the conversation
     before anything is sent, that it has not been written yet, and that online AI sends nothing
     today.

   **Judge it as the cautious reader in the ticket.** From these words alone, could you say what
   the key is used for, when, where it goes, and who pays? If any of those is unclear, write down
   the sentence and why. This ticket carries a copy review, and that note is what the reviewer
   needs. The section deliberately does **not** list the contents of a question. That is #737's
   statement, made in the conversation (`docs/decisions.md`, 2026-09-25). Do not report its
   absence here as a defect.

   The old sentence *"Nothing on this screen asks for a key today…"* must be **gone**. If you see
   it, the web build is the old one. Go back to *Before you start*, step 2.

## Part B — entry refuses what is not a key, and says why

8. Click **Add a key**. ☐

   **You should see:** the button replaced by three fields, **Provider address** (showing
   `api.example.com:443` in grey as an example), **Model**, and **Key**, plus **Save the key** and
   **Cancel**. The Provider address and Model fields are empty. There is no sentence about
   replacing, because there is nothing to replace yet.

9. Click **Save the key** with every field empty. ☐

   **You should see:** in red below the buttons: *"Enter the provider's address, like
   api.example.com:443."* Nothing else changes.

10. Type `api.provider.example:443` into **Provider address** and `walkthrough-model` into
    **Model**. Leave **Key** empty and click **Save the key**. ☐

    **You should see:** *"Paste the key."*

11. Click into **Key** and press the space bar three times. Click **Save the key**. ☐

    **You should see:** the field shows three dots, not spaces. It is a password field. The red
    line reads *"That is only spaces or line breaks, not a key."*

12. Clear the **Key** field. Type the sentinel **with one space on the end**:
    `ASKWELL-SENTINEL-KEY-7f3c9e21d4 ` and click **Save the key**. ☐

    **You should see:** *"The key has a space or line break in it, often picked up when copying.
    Keys never contain one. Paste it again without it."* The refusal does **not** repeat the key,
    or any part of it. The key is refused, not quietly trimmed and saved.

13. Put a space in the model name: change **Model** to `walkthrough model` and click **Save the
    key**. ☐

    **You should see:** *"The model name has a space in it. Remove it and try again."* Change it
    back to `walkthrough-model`.

14. Now try two mistakes that only the server catches. Clear **Key** and type `short`. Click
    **Save the key**. ☐

    **You should see:** the button reads **Saving…** for a moment, then: *"The key must be 8 to
    512 printable characters with no spaces or line breaks."* Askwell's own check refused it. It
    is shown as the server worded it and does not contain `short`.

15. Change **Provider address** to `api.provider.example` (no `:443`). Put the sentinel, with
    no trailing space, into **Key**. Click **Save the key**. ☐

    **You should see:** *"The provider's address must be a host and port, like
    api.example.com:443."* Put `:443` back on the end.

16. Click **Cancel**. ☐

    **You should see:** the form closes, and the section is back to *"No key is set…"* and
    **Add a key**. Click **Add a key** again. **All three fields are empty.** Cancel threw the key
    away, and it did not linger in the form.

## Part C — save, and it is never shown again

17. Fill in **Provider address** `api.provider.example:443`, **Model** `walkthrough-model`, and
    **Key** `ASKWELL-SENTINEL-KEY-7f3c9e21d4`. Click **Save the key**. ☐

    **You should see:**
    - the form closes;
    - *"A key is set for api.provider.example:443, asking for walkthrough-model."*;
    - two buttons, **Replace the key** and **Remove the key**;
    - beside them, **before you press either**: *"Removing it deletes it from this machine. Any
      conversation using online AI goes back to local at once, and says so."*;
    - a small line: *"Saved. The key will not be shown again."*

    The key does not appear anywhere, not even as dots, `••••`, or its last four characters.
    The address bar still reads `http://127.0.0.1:8000/settings`, with no `?` and nothing after
    it. The key was never put in the address.

18. **Watch for the browser offering to save a password.** Some browsers offer to save any
    password field. Look for a key icon or a **Save password?** prompt near the address bar. ☐

    **You should see:** no offer. **If one appears, click Never / Not now and report it** as a
    defect of this ticket, with the browser's name and version. A provider key kept in the
    browser's password manager is a copy of the key outside Askwell, and the settings text says
    otherwise.

19. **Reload the page** (F5, or the reload button). Click **Settings** if you are not on it, and
    scroll to **Online AI**. ☐

    **You should see:** briefly *"Reading…"*, then the same set line naming
    `api.provider.example:443` and `walkthrough-model`, with **Replace the key** and **Remove the
    key**. There is no key, masked or otherwise, and no *"Saved."* line, because that line belongs to
    the moment of saving.

20. **Stand-in** — restart the whole stack **without** `-v`. With `-v` it would delete everything:
    ☐

    ```
    podman compose down
    podman compose up -d
    ```

    Wait about twenty seconds, then reload the page in the browser and scroll to **Online AI**.

    **You should see:** the same set line. The key survived a restart.

21. Click **Ask** in the rail, then click **Local**. ☐

    **You should see:** the button reads **Online AI: on**. Above the question box, a bold marker
    reads **"Online AI is on for this conversation until *(a time about four hours from now)*.
    Questions go to api.provider.example:443."** The top line now reads `online AI is on for this
    conversation`. That address came from what you typed in Settings, so the key entered on the
    screen is the one online AI now points at. **Leave this tab on the Ask screen.**

## Part D — replace, then remove

22. Open a **second tab** on `http://127.0.0.1:8000`. Click **Settings** and scroll to **Online
    AI**. Click **Replace the key**. ☐

    **You should see:**
    - **Provider address** already reads `api.provider.example:443` and **Model**
      `walkthrough-model`. They are not secret and are pre-filled;
    - the key field is labelled **New key** and is **empty**. The old key is not in it;
    - above the buttons: *"The new key takes the old one's place. If it is for a different
      provider address, every conversation using online AI goes back to local."*;
    - the button reads **Replace the key**.

23. Type `ASKWELL-SENTINEL-KEY-ROTATED-5b8a` into **New key** and click **Replace the key**. ☐

    **You should see:** the set line again, for the same address and model, and *"Replaced. The
    new key will not be shown again."*

    Switch to the first tab (the Ask screen) and wait one minute. The screen rereads the
    conversation every minute. **You should see:** the marker still says **Online AI is on**. A new
    key for the same provider keeps the conversation online, as the sentence in step 22 said.

24. Back in the Settings tab, click **Replace the key** again. Change **Provider address** to
    `api.other-provider.example:443`, and **Model** to `other-model`. Enter the sentinel
    `ASKWELL-SENTINEL-KEY-7f3c9e21d4` in **New key** and click **Replace the key**. ☐

    **You should see:** *"A key is set for api.other-provider.example:443, asking for
    other-model."* and *"Replaced…"*.

    Switch to the Ask tab and wait up to a minute. **You should see:** the button goes back to
    **Local**, and the marker turns to plain grey: **"Online AI was on in this conversation
    earlier. It is local now: nothing you ask here leaves this machine."** The key is now for a
    different provider, so the conversation ended, as step 22 warned.

25. In the Ask tab, click **Local** again. ☐

    **You should see:** **Online AI: on**, with the marker naming `api.other-provider.example:443`.

26. In the Settings tab, click **Remove the key**. Click it **once**. There is no confirmation
    box, by design. The sentence beside the button is the warning. ☐

    **You should see:** the button reads **Removing…** for a moment, then the section returns to its
    unset state: *"No key is set. Online AI cannot be switched on in any conversation."*, **Add a
    key**, and *"Removed. The key is no longer on this machine."*

27. Switch to the Ask tab and wait up to a minute. ☐

    **You should see:** the button reads **Local** and the grey *"Online AI was on in this
    conversation earlier. It is local now…"* marker. Click **Local** once more. It stays
    **Local**, with the no-key sentence from step 6 beside it. The wording shown here when the key
    is removed belongs to `M8-KEY-FE-175`. See Known gaps.

28. **Stand-in** — the decisions records of steps 17–26: ☐

    ```
    scripts/dev.sh psql -c "SELECT kind, payload FROM audit_decisions WHERE kind LIKE 'online_key_%' OR kind = 'online_ai_revoked' ORDER BY occurred_at;"
    ```

    **You should see,** in this order:
    - `online_key_stored`, naming `api.provider.example:443` and `walkthrough-model` (step 17);
    - `online_key_replaced`, same provider, with a `previous` of the same provider (step 23);
    - `online_key_replaced`, naming `api.other-provider.example:443` with `previous`
      `api.provider.example:443` (step 24), then `online_ai_revoked` with reason `key_replaced`;
    - `online_key_removed`, naming `api.other-provider.example:443` (step 26), then
      `online_ai_revoked` with reason `key_removed`.

    **No payload contains a key.** That means no sentinel, no rotated key, and nothing from Part
    B's refused entries. The refused entries in Part B left **no** record, because nothing was
    stored. An `online_ai_revoked` with reason `restart` may also appear from step 20. That is
    `M8-ONLINE-SEC-169` behaving correctly.

## Part E — a passphrase-locked install asks first

29. Click **Add a key** and save the sentinel for `api.provider.example:443` / `walkthrough-model`,
    as in step 17. ☐

    **You should see:** the set line and *"Saved…"*.

30. Scroll to **Privacy and security → Passphrase**. Click **Set a passphrase**. Type
    `correct horse battery staple` twice, tick **I understand there is no recovery.**, and click
    **Set passphrase**. ☐

    **You should see:** **Setting…**, then the controls for an install with a passphrase on.
    Askwell does not ask for the key again. Setting the passphrase re-encrypted it.

31. **Stand-in** — restart the API, which locks it: ☐

    ```
    podman compose restart api
    ```

    Wait about twenty seconds. In the browser, reload, click **Settings** and scroll to
    **Passphrase**. **You should see:** "A passphrase is set for this install but this session has
    not unlocked it yet."

32. Scroll up to **Online AI**. Click **Replace the key**. ☐

    **You should see:** the set line was still there before the click. A locked install still knows
    which provider is set. After the click, instead of the fields, you see: *"Your passphrase is
    needed first. The key is encrypted with it, like everything else you have protected, and
    Askwell cannot encrypt a new key until you enter it."*, one **Passphrase** field (dots),
    **Unlock** (greyed out while the field is empty) and **Cancel**.

33. Click **Cancel**, then click **Remove the key**. ☐

    **You should see:** no passphrase asked for. The section goes to *"No key is set…"* and
    *"Removed…"*. Deleting a key decrypts nothing, so a locked install may remove one.

34. Click **Add a key**. ☐

    **You should see:** the passphrase prompt from step 32 again, because the install is still
    locked.

35. Type `wrong passphrase here` and click **Unlock**. ☐

    **You should see:** **Unlocking…**, then in red: *"Incorrect passphrase."* The prompt stays.

36. Clear the field, type `correct horse battery staple` and click **Unlock**. ☐

    **You should see:** the prompt is replaced by the three entry fields from step 8, all empty.
    Save the sentinel for `api.provider.example:443` / `walkthrough-model`. **You should see:**
    the set line and *"Saved…"*.

    Scroll to **Passphrase**. After a reload, it no longer says this session has not unlocked
    it. Unlocking from the key form unlocks the whole of Askwell, the same as any other unlock
    (`docs/decisions.md`, 2026-09-25).

## Part F — the sentinel appears nowhere

37. **Stand-in** — search the logs of every container and the whole database: ☐

    ```
    podman compose logs 2>&1 | grep -c "ASKWELL-SENTINEL"
    podman compose exec postgres pg_dump -U askwell askwell | grep -c "ASKWELL-SENTINEL"
    ```

    **You should see:** `0` twice. If `pg_dump` says the role does not exist, use the
    `POSTGRES_USER` and `POSTGRES_DB` from your `.env`.

38. Click **Settings → Privacy and security → Network activity**. ☐

    **You should see:** `0 outbound requests permitted`. Entering, replacing and removing a key
    sent nothing anywhere. Askwell does not check the key with the provider.

39. **Stand-in** — the frontend's own tests for this ticket: ☐

    ```
    scripts/dev.sh web-check
    ```

    **You should see:** it end with no failures. Among the tests, `web/lib/online-key.test.ts` covers
    the parts you cannot see by clicking: the key goes in a request body and never a URL, the
    field is a password field emptied once the save returns, the key is never kept in the browser,
    and a refusal never repeats the key.

---

## Teardown

In the browser: **Settings → Online AI → Remove the key**, then **Privacy and security →
Passphrase** and remove the passphrase. Or wipe everything:

```
podman compose exec api askwell-verify
podman compose down -v
rm -rf /tmp/askwell-test-174
```

**You should see:** both audit chains reported intact before the wipe.

---

## Known gaps

These are deliberately not built yet. Do not report them as defects of this ticket.

- **No online question can be sent (#737), and Redis has no authentication (#730).** A saved key
  is never used yet. A wrong key is only found when an online question is refused, and today no
  online question is sent. The settings text says so.
- **The section does not list what a question sends.** That statement is made in the
  conversation before its first send, and its wording is #737's. Settings says where to find it
  rather than keeping a second copy (`docs/decisions.md`, 2026-09-25).
- **The conversation's wording when its key is removed or re-pointed** is `M8-KEY-FE-175`'s.
  Today the Ask screen shows the generic *"Online AI was on in this conversation earlier…"*
  marker, and it can take up to a minute to appear.
- **No provider-side check of the key on save.** That would be a network request before any
  conversation is switched online (C1), matching `M8-KEY-BE-173`.
- **The browser only refuses whitespace and emptiness.** Every other malformed value (too short,
  address without a port, odd characters in a model name) is refused by the server, in its own
  sentence, after a moment of **Saving…**. That is deliberate: one validator decides.
- **Remove has no confirmation dialog.** The consequence is stated beside the button before it is
  pressed, and the ticket asks for one-click removal.
- **No unlock prompt anywhere except this form.** Elsewhere, a locked install is still unlocked
  from the terminal. The passphrase's own frontend work owns that.
- **One key, one provider.** Adding a second replaces the first.
- **No screen shows the decisions records of key changes.** Step 28 reads them from the database.
