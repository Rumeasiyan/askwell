# Success metrics

What "working" means in numbers. `build-plan.md` defines the **model** quality gate; this is whether the **product** is succeeding once real people use it.

Rewritten 2026-08-10. The previous version assumed a pilot deployment with officers at a named customer. There is no pilot — VaultQ is a free download for individuals, so every number had to be re-derived.

Each is marked **derived** (traceable to a stated requirement) or **assumed** (reasoned, not measured — see §7).

---

## 1. The one that matters most

**Does someone still use VaultQ three months after installing it, without being reminded?**

Everything else is diagnostic. A free tool that gets installed, used enthusiastically for two weeks and then forgotten has failed, whatever its eval scores say.

| Metric | Target | Source |
| ------ | ------ | ------ |
| Installs still asking ≥ 1 question in week 12, as a share of those active in week 2 | **≥ 35%** | *assumed* |
| Questions per active user per week, weeks 8–12 | **≥ 5**, not declining | *assumed* |
| Users who add a **second** source after the first | **≥ 60%** | *assumed* |

The third is the leading indicator and the cheapest to move. Adding one source is trying it; adding a second is deciding it works. If people add one file and stop, the problem is in the first ten minutes, not in the model.

Retention targets are lower than a paid product would carry, deliberately. A free download has no sunk cost keeping anyone around, so 35% at week 12 is a real result rather than a disappointing one.

---

## 2. Does it actually answer well

| Metric | Target | Why | Source |
| ------ | ------ | --- | ------ |
| Question → answer complete, text, p50 | **< 20s** on `standard` | Below this it competes with opening the file yourself; above it, people stop | *assumed* |
| Same, p95 | **< 60s** | p50 hides the tail that drives abandonment. Looser than a server product would allow — it is one laptop | *assumed* |
| Voice: end of speech → first audio, `accelerated` | **≤ 3.5s** | Latency budget | *derived* |
| Same, `standard` | **≤ 8s** | Latency budget | *derived* |
| **Abstention rate** | **5–20% band** | See below | *assumed band* |
| Answers where the user opened the cited source anyway | **track, no target** | Proxy for citation trust | *assumed* |
| Generated SQL edited before accepting | **< 25%** | Frequent correction means schema notes are inadequate, which means the clarification loop is underperforming | *assumed* |

### Abstention rate is a band, and it is gameable

Abstention rate is the key operational signal — a rising rate means the corpus has gaps. That is half the picture, and the missing half is dangerous.

**It can be driven to zero by lowering the retrieval threshold.** One config change, the dashboard looks excellent, and C5 is broken — the system starts answering from general knowledge instead of admitting it does not know. Every incentive points that way, and the number itself never reveals it.

- **Below 5%** — suspect the threshold, not the corpus. Sample answers and check grounding.
- **5–20%** — healthy.
- **Above 20%** — real gaps. What is being asked and not found is the list of what to add next.

**Never report it alone.** Pair with:

| Counter-metric | Target | Source |
| -------------- | ------ | ------ |
| Sampled answers where every factual claim traces to a retrieved chunk or a memory fact | **100%** | C4 makes an uncited claim a bug | *derived* |

Falling abstention with falling citation correctness is the failure signature. Either number alone looks fine.

---

## 3. Is the differentiator working

The clarification loop is the reason to choose VaultQ (`PRD.md` §5), so it needs its own measures. It also has an obvious failure mode — asking too much — that only shows up here.

| Metric | Target | Why | Source |
| ------ | ------ | --- | ------ |
| Clarifications raised per source | **≤ 5 median** | Above this, review becomes a chore and gets abandoned | *assumed* |
| Raised clarifications eventually answered | **≥ 50%** | Below half suggests the questions are not worth answering | *assumed* |
| Users who answer at least one, ever | **≥ 70%** | If most never engage, the differentiator is not landing | *assumed* |
| Memory facts per active user at week 12 | **≥ 20** | Compounding value is the whole claim; this is whether it compounds | *assumed* |
| Answer quality on the memory eval subset | **≥ 0.85** | Verifies stored facts actually change answers | *derived* |
| Users who **dismiss** the clarification queue without answering | **track, ceiling 30%** | The early warning that the loop is annoying rather than useful | *assumed* |

The last one is the one to watch first. A high dismissal rate with good retention means the loop is ignorable, which is survivable. High dismissal with falling retention means it is actively driving people away, and the per-source cap needs tightening immediately.

---

## 4. Getting started, and staying installed

| Metric | Target | Source |
| ------ | ------ | ------ |
| Install → first successful answer | **< 30 min** including model download | *assumed* |
| Installs that never reach a first answer | **< 20%** | *assumed* |
| Network calls made in local mode | **0**, verified per release with the cable unplugged | *derived* |
| Ingestion failures not visible to the user | **0** | *derived* |
| Backup restored successfully onto a clean machine | **pass, every release** | An untested restore is not a backup | *derived* |

Install-to-first-answer is the metric most likely to kill the product quietly. A model download on a slow connection can dominate it, and nothing else matters if people give up before the first answer.

---

## 5. How these are measured, and the hard limit on that

**Everything here must be computable from the user's own local data and visible to them in their own copy.** C1 forbids runtime network calls in local mode.

Which means **none of §1 is observable** — see §6, where that was decided rather than left hanging. Retention, second-source rate and dismissal rate cannot be measured without shipping telemetry, and VaultQ does not.

**Deliberately not measured:** benchmark scores beyond the quality gate (invites optimising for them); time-saved or productivity (needs a baseline nobody has, produces numbers that cannot be defended); anything requiring content to leave the machine, at any sample rate, for any reason.

---

## 6. Settled: no telemetry in v1

**VaultQ ships no telemetry, not even opt-in, through Phase 6.**

Shipping a telemetry toggle in a privacy-first free product costs trust at exactly the moment you are asking for it. "Off by default, here is precisely what would be sent" is honest and still reads to a suspicious user — the target user is a suspicious user — as the beginning of a slope. That is a bad trade for numbers that would be biased toward engaged users anyway.

Accepted consequence, stated plainly: **none of §1 is observable.** Retention, second-source rate and dismissal rate cannot be measured. The product will be built on reasoning and direct user contact rather than on a dashboard, and that is a real handicap, not a neutral choice.

What is used instead: direct contact with a small number of real users (small sample, high signal), and from Phase 7 the paying users, who are observable by necessity — with the caveat that they say nothing about the free majority.

Revisit at Phase 6, once there are users to ask.

## 7. Open

1. **Retention targets** (§1) — 35% at week 12 and ≥ 5 questions/week are reasoned, not measured. First real evidence should replace them.
2. **The 5–20% abstention band** — invented from failure-mode reasoning. Re-derive from real traffic; it exists now so there is something to alarm on.
