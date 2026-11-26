# clipp_cpsat: the CLIPP competition MILP model (OR-Tools CP-SAT)

Copy of the existing CLIPP MILP model, the base model for the cold/warm start
experiment (`tools/milp/run.py`, documentation in `tools/milp/README.md`).

- Source: https://github.com/CLIPP-Optimization-Competition/milp-solver
- Commit: `cf6ed8a` (2026-10-29, "Add MIT License to the project")
- Licence: MIT, see `LICENSE`
- Formulation: `MILP_EXPLANATION.md` (copied from `docs/formulation/`; the
  LaTeX/PDF versions are in the source repository)

Files copied from the source `clipp/` package: `__init__.py`, `parser.py`,
`graph.py`, `model.py`, `reconstruction.py`, `validator.py`, `scoring.py`,
`io.py`.

**Only change:** the imports `from clipp.<module> import ...` became
`from .<module> import ...`, because this repository already has its own
package called `clipp`. Nothing else was edited.

Requires `ortools` (see `tools/milp/requirements.txt`).
