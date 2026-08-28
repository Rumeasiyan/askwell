"""Prompt files live here as versioned, non-Python text — never inline in application logic.

A change to a prompt file is a prompt change and requires an eval run
(`AGENTS.md` §4, `docs/build-plan.md`). Nothing in this package imports the
model-facing text directly; `askwell.agent.compose` reads it by path so the
text stays plain, diffable prose rather than a Python string literal.
"""
