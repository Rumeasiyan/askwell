"""Model-generated SQL never runs untrusted. C2.

`docs/architecture.md` §5's own table names this package as C2's enforcement
point. `askwell.sql.validate` and `askwell.sql.limit` (`M4-SQL-VAL-105`) are
built; the `EXPLAIN` dry run (`M4-SQL-VAL-106`) is the remaining ticket in
the same `SQL` epic and belongs in this package too, once built.
"""
