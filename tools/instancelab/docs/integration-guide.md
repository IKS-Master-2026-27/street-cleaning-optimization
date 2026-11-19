# Shared-repository integration guide

InstanceLab is developed and reviewed in its personal repository first. The
shared class repository remains read only until the completed module is brought
in through a focused feature branch and pull request.

## Recommended destination

The shared repository currently has no root Python dependency or packaging
configuration. Preserve that boundary by adding InstanceLab as a self-contained
tool:

```text
street-cleaning-optimization/
├── data/
├── clipp/
├── tools/
│   └── instancelab/
│       ├── app.py
│       ├── pyproject.toml
│       ├── src/instancelab/
│       ├── tests/
│       └── docs/
└── ...
```

The repository-specific code stays in
`src/instancelab/adapters/shared_repository.py` and
`src/instancelab/adapters/shared_results.py`. Parsing, validation, feature
extraction, PCA, diagnostics, reporting and performance relationships remain
independent of the shared repository.

When launched from the shared repository or from a nested `tools/instancelab`
directory, InstanceLab can detect the nearest parent containing `data/input`.
`CLIPP_SHARED_REPO` remains an explicit override.

## Behaviour when instances change

- Synthetic files matching `data/input/syntetic_generated/instance_*.txt` and
  real files matching `data/input/real_instances/*/instance.txt` are discovered
  dynamically. There is no fixed expected instance count.
- A lightweight fingerprint uses relative path, file size and modification time.
  Adding, removing or editing a recognized file invalidates the cached analysis
  on the next Streamlit rerun. The Reload button forces an immediate rerun.
- Every discovered file is parsed and semantically validated.
- Valid reference instances are re-analysed together. PCA is intentionally
  re-fitted because the reference dataset changed, so existing point positions
  and explained variance may also change.
- Invalid files are excluded explicitly and displayed with their validation
  reason. They are also recorded in the reproducibility JSON report.
- An uploaded one-off instance behaves differently: it is projected onto the
  existing fitted axes and does not change the reference PCA.

## Behaviour when algorithm results change

- Algorithm folders containing `*_solution.txt` files under `data/output` are
  discovered dynamically; algorithm names are not hard-coded in the dashboard.
- Every stored route is parsed, validated and re-scored in memory using the
  shared objective definition reproduced by the standalone adapter.
- An algorithm enters the comparison only when it has one valid solution for
  every current reference instance. Incomplete or invalid result sets are named
  and excluded instead of biasing the comparison.
- A newly added instance without any published solution is listed as "no
  published results yet": it enters validation, features and PCA immediately,
  and the score comparison continues on the instances that have results. An
  algorithm that covers only some of the instances with results stays excluded.
- When a published solution changes, its old execution time is no longer shown;
  `python -m instancelab.timing --resume` re-times exactly the changed pairs.
- Execution times are not inferred from solution files. `python -m
  instancelab.timing` re-runs only published pairs from a read-only checkout,
  writes into InstanceLab's own `results/timing/`, and reports a time only
  when the re-run reproduces the published score. When a published solution
  is regenerated with newer code, re-run the timing command.

## Dependency boundary in the shared repository

InstanceLab keeps its own `pyproject.toml` under `tools/instancelab`. From that
directory, reviewers can create an isolated Python 3.11 environment and install
only the tool's dependencies:

```powershell
cd tools\instancelab
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
$env:CLIPP_SHARED_REPO = (Resolve-Path ..\..)
python -m unittest discover -s tests -v
streamlit run app.py
```

This avoids adding Streamlit, Plotly, Pandas or NumPy requirements to the shared
solver package itself.

## Pull-request process

1. Create or link a shared-repository issue with scope and acceptance criteria.
2. Create `feature/instance-lab` from the latest shared `main`.
3. Copy only the reviewed InstanceLab module into `tools/instancelab`.
4. Re-run unit tests and read-only integration tests against the shared branch's
   current `data/input` collection.
5. Document exact setup, test and Streamlit commands in the shared README.
6. Confirm no virtual environment, cache, downloaded CSV, local path or generated
   analysis output is staged.
7. Push the feature branch and open a draft pull request targeting `main`.
8. Request administrator review. Do not self-merge or push directly to `main`.

The integration PR should not refactor the shared parser or solver code unless a
separate reviewed issue requires it. Keeping the first PR additive makes review
and rollback safer.

## Pull-request acceptance checklist

- Python 3.11 installation succeeds from `tools/instancelab/pyproject.toml`.
- Deterministic unit tests and read-only shared-data integration tests pass.
- The largest current class instance parses, validates and extracts features.
- The dashboard loads the current reference collection and names excluded data.
- Adding or editing a recognized instance invalidates the cached analysis.
- Complete algorithm result folders are compared; incomplete folders are named
  and excluded.
- No `.venv`, cache, secret, downloaded export, generated analysis data or local
  absolute path is included.
- The PR changes only the additive InstanceLab tool and explicitly documented
  shared README instructions.
