"""Model-generated SQL never runs untrusted. C2.

`docs/architecture.md` §5's own table names this package as C2's enforcement
point. `askwell.sql.validate` is the only module here so far — limit
injection (`M4-SQL-VAL-105`) and the `EXPLAIN` dry run (`M4-SQL-VAL-106`) are
later tickets in the same `SQL` epic and belong in this package too, once
built.
"""
