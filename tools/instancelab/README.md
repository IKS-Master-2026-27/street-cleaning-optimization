# street-cleaning-instancelab

InstanceLab is a standalone, integration-ready analysis tool for CLIPP
street-cleaning optimization instances. It provides a canonical data model,
standalone parsing and semantic validation, 26 deterministic characteristics,
instance comparison, an exploratory 2D PCA feature-space projection, scientific
sensitivity diagnostics, optional descriptive algorithm-score analysis and
reproducible exports through a Streamlit and Plotly dashboard.

The implementation deliberately distinguishes this feature-space foundation
from full supervised Instance Space Analysis. It does not claim algorithm
footprints or performance prediction from the current small result set.

## Requirements

- Python 3.11+
- NumPy for PCA
- Pandas, Plotly and Streamlit for the local dashboard

## Setup and unit tests

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m unittest discover -s tests -v
```

## Run the dashboard

Point InstanceLab at a read-only checkout of the shared repository and start
Streamlit:

```powershell
$env:CLIPP_SHARED_REPO = "C:\path\to\street-cleaning-optimization"
streamlit run app.py
```

Use the sidebar Reload button after changing recognized instance or solution
files. The shared repository is treated as an input source; InstanceLab does not
write analysis data there.

The dashboard displays the 2D PCA instance space, a comparison table, feature
loadings and the explained variance retained by the projection. A new CLIPP
text file can be uploaded and validated in memory; a valid upload is projected
with the existing reference preprocessing and PCA axes without modifying either
repository or silently re-fitting the model.

Recognized repository instance files are fingerprinted by relative path, size
and modification time. On the next Streamlit rerun, additions and edits refresh
the fitted reference analysis. Invalid files are named and excluded with their
validation reason instead of silently entering the PCA or stopping all valid
instances from being inspected.

The scientific-validation tab reports selected-feature correlations,
standardized instance extremeness and leave-one-out PCA subspace stability.
These are sensitivity diagnostics for the small exploratory reference set, not
supervised algorithm-performance evidence.

## Tests against the shared class repository

The shared repository is only read. Point the integration test at an existing
checkout; test outputs are not written there.

```powershell
$env:CLIPP_SHARED_REPO = "C:\path\to\street-cleaning-optimization"
python -m unittest tests.test_shared_instances -v
```

To execute the complete suite with shared instances enabled:

```powershell
$env:CLIPP_SHARED_REPO = "C:\path\to\street-cleaning-optimization"
python -m unittest discover -s tests -v
```

GitHub Actions also runs the deterministic suite on Python 3.11 for every push
and pull request. Shared-data integration tests remain local and activate only
when `CLIPP_SHARED_REPO` is configured.

## Execution times of published results

Scores are always computed from the solutions published in the shared
repository; InstanceLab does not run algorithms to produce results. Published
files carry no timings, so the timing command re-runs only the published
(instance, algorithm) pairs and times the algorithm call:

```powershell
python -m instancelab.timing --shared-repo "C:\path\to\street-cleaning-optimization" --workers 2
```

A time is shown only when the re-run reproduces the published score.
Algorithms without published results are never executed. Output goes to
`results/timing/` (see
[`docs/performance-methodology.md`](docs/performance-methodology.md)).

## Current scientific scope

The current feature set describes five defensible aspects of an instance:

- problem size and resource budget;
- graph sparsity, directionality and degree variation;
- mandatory, optional and connector street composition;
- service length, travel time and requirement distributions;
- fleet composition, workload and capability coverage;
- time pressure: mandatory work against the fleet time budget and the
  fastest depot round trip of each mandatory street against `T`.

Validation also rejects an instance whose mandatory street cannot be
reached, cleaned and left within `T`.

Raw counts preserve scale, while ratios and coefficients of variation support
comparison between differently sized networks. Extraction validates every
instance first and runs in `O((N + M) log N + C)` time with `O(N + M)` memory, which
keeps it compatible with the largest class instance.

These are instance characteristics, not algorithm-performance claims. The 2D
PCA is an unsupervised feature-space projection, not the supervised PILOT
projection or the complete Instance Space Analysis methodology. A separate,
optional section descriptively compares the published `greedy` and `dp_simple`
scores and their measured execution times. Algorithm footprints still require more diverse outcomes and repeated,
comparable benchmark data.

The complete formulas and interpretation rules are recorded in
[`docs/feature-catalog.md`](docs/feature-catalog.md). The ordered definitions
are also available programmatically through `instancelab.FEATURE_DEFINITIONS`.

The adopted ISA principles, professor-provided references and deliberately
deferred supervised stages are documented in
[`docs/research-basis.md`](docs/research-basis.md).

The proposed shared-repository location, dynamic instance behaviour and safe
pull-request sequence are documented in
[`docs/integration-guide.md`](docs/integration-guide.md).

The optional read-only comparison of committed `greedy` and `dp_simple` scores,
including its validation procedure and scientific limits, is documented in
[`docs/performance-methodology.md`](docs/performance-methodology.md).
Complete algorithm result folders are discovered dynamically; incomplete sets
are reported but cannot silently enter the comparison.

The Scientific validation tab exports both machine-readable JSON/CSV artifacts
and a deterministic Markdown academic summary with scope, PCA evidence,
validation diagnostics, score comparison and explicit interpretation limits.

A shared-repository integration checklist is available in
[`docs/integration-guide.md`](docs/integration-guide.md).

PCA input preparation is documented in
[`docs/analysis-methodology.md`](docs/analysis-methodology.md). The full
26-feature table is preserved for comparison, while a documented 9-feature
subset is log-transformed where necessary and standardized before projection.
The 2D PCA implementation uses NumPy SVD and exposes coordinates, feature
loadings, explained variance and reproducible projection of new instances.
