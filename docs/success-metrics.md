# Success metrics

What "working" means in numbers. `docs/PRD.md` §7 defines the **model** quality gate; this document defines whether the **product** is succeeding once a real customer is using it.

Every number below is marked **derived** (traceable to a PRD statement) or **assumed** (my proposal, needs your confirmation — see §5). Do not treat an assumed number as agreed.

---

## 1. The one that matters most

**Does the pilot customer still use VaultQ in week 12, without being asked to?**

Everything else is diagnostic. A ministry that installs it, uses it enthusiastically for three weeks, and quietly returns to the filing cabinet has failed the product regardless of eval scores.

| Metric | Target | Source |
| ------ | ------ | ------ |
| Officers who asked ≥ 1 question in week 12, as a share of those who asked ≥ 1 question in week 2 | **≥ 60%** | *assumed* |
| Questions per active officer per week, weeks 8–12 | **≥ 5**, not declining week on week | *assumed* |

The trend matters more than the absolute. Five questions a week that is flat beats fifteen that is halving.

---

## 2. Answer quality in production

The eval suite (`docs/PRD.md` §7) measures the model on a fixed corpus. These measure the system on the customer's corpus, where the questions are real and the documents are worse.

| Metric | Target | Why this number | Source |
| ------ | ------ | --------------- | ------ |
| Time from question submitted to answer complete, text mode, p50 | **< 20s** | PRD §3 states the Officer's success condition is a correct sourced answer in under 20 seconds | *derived* |
| Same, p95 | **< 45s** | p50 alone hides the tail that actually drives abandonment | *assumed* |
| Voice: end of user speech → first audio out, `standard` profile | **≤ 3.5s** | PRD §4.4 latency budget | *derived* |
| Same, `edge` profile | **≤ 8s** | PRD §4.4 latency budget | *derived* |
| **Abstention rate** | **5–20% band** | See below — this is a band, not a target | *assumed band* |
| Answers where the user opened the cited source document | **track, no target** | Proxy for whether citations are trusted. A high rate means the citation is not doing its job; a rate near zero may mean nobody is checking | *assumed* |
| Analyst edits to generated SQL before accepting | **< 25% of queries** | PRD §3: the Analyst should never write SQL for a routine question but must always be able to correct it. Frequent correction means the schema annotations are inadequate | *assumed* |

### Abstention rate is a band, not a target — and it is gameable

PRD §4.5 calls abstention rate the key operational metric: a rising rate means the corpus has gaps. True, but incomplete, and the incompleteness is dangerous.

**Abstention rate can be driven to zero by lowering the retrieval threshold.** That is a one-line config change that makes the dashboard look excellent and breaks constraint C4 — the system starts answering from world-knowledge instead of saying it does not know. This is the single most likely way VaultQ quietly stops being trustworthy, because every incentive points that way and nothing in the number itself reveals it.

So:

- **Below 5%** — suspect the threshold, not the corpus. Sample answers and check they are actually grounded.
- **5–20%** — healthy. The corpus has gaps, the system is honest about them.
- **Above 20%** — real corpus gaps. Look at what is being asked and not found; that list is the ingestion backlog.

**Pair it with a counter-metric.** Abstention rate must never be reported alone:

| Counter-metric | Target | Source |
| -------------- | ------ | ------ |
| Sampled answers where every factual claim traces to a retrieved chunk | **100%** | C3 makes an uncited claim a bug, not a limitation | *derived* |

A falling abstention rate with a falling citation-correctness rate is the failure mode. Either number alone looks fine.

---

## 3. Deployment and operations

The Deployer persona (PRD §3) is a Quantum Plus engineer on a customer site, often air-gapped, usually with a return flight.

| Metric | Target | Source |
| ------ | ------ | ------ |
| Full install on clean hardware, network cable unplugged, to first successful question | **< 2 hours** | PRD §3 Deployer success condition | *derived* |
| Installs requiring a second site visit | **0** | *assumed* |
| Air-gap release test: full install and use with the cable physically unplugged | **pass, every release** | PRD §8 requires this as part of the release test | *derived* |
| Ingestion jobs that fail and are not visible in the admin console | **0** | AGENTS.md §6: a failed embedding job surfaces in the admin console; it does not silently drop the document | *derived* |
| Unplanned service restarts per month, per deployment | **≤ 1** | *assumed* |

---

## 4. What is deliberately not measured

- **Model benchmark scores beyond `docs/PRD.md` §7.** The eval gate decides whether a model may be a profile default. Tracking additional benchmarks invites optimising for them.
- **Per-user productivity or time saved.** Unmeasurable without a baseline nobody has, and the attempt produces numbers that get quoted in sales material and cannot be defended.
- **Anything requiring telemetry the customer has not opted into.** PRD §2 makes optional telemetry metadata-only and opt-in. Every metric here is computable from the customer's own audit log and visible to them in their own admin console. **If a metric here can only be obtained by sending content off-site, it is the wrong metric.**

---

## 5. Open — needs your confirmation

The *assumed* numbers above are proposals with reasoning, not agreed targets. The ones that would most change the product if wrong:

1. **Week-12 retention ≥ 60% and ≥ 5 questions/officer/week.** These set the bar for calling the pilot a success. If the real bar is "the ministry renews", say so and the metric becomes commercial rather than behavioural.
2. **The 5–20% abstention band.** Invented from reasoning about failure modes, not from data. It should be re-derived from the first month of pilot traffic — but it needs a starting value so the dashboard has something to alarm on.
3. **Pilot size.** No metric here is meaningful without knowing whether the pilot is 8 officers in one department or 150 across a ministry. It also determines whether p95 latency is measurable at all — at low volume it is noise.
4. **Analyst SQL edit rate < 25%.** A guess. If the pilot has no Analyst persona at all — plausible for a first government deployment — this metric and much of PRD §4.2's disclosure UI matter far less than assumed, and that would reorder the build.

Items 1 and 3 should be settled before the pilot customer is chosen (issue [#3](https://github.com/Rumeasiyan/vaultq/issues/3)), because the answer changes what a pilot needs to look like.
