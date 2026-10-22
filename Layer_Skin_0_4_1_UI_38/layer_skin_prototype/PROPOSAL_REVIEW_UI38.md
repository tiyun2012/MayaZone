# UI 38: review of the three-file proposal

The proposal contains useful optimizations, but its three complete replacements
should not be installed as supplied. UI 38 selectively merges tested parts into
UI 37 and retains the existing native validation, save and Undo behavior.

| Proposed file | Finding | UI 38 decision |
| --- | --- | --- |
| `layer_skin_core.py` | Indentation error; persistent sample validation can accept changed invalid data; unbounded per-call packed-row cache. Sparse rows and operation-local reuse are useful. | Merge sparse manual rows, local validation/encoding reuse and bounded adaptive packed-row reuse; retain ordinary dictionaries and revalidate manual data on every call. |
| `layer_skin_performance.py` | Scattered C-buffer batching is useful. The first-row memory estimate can undercount mixed and densely populated sparse rows. | Merge bounded scattered batches, preserve the existing state estimate and small-scope/fallback paths. |
| `layer_skin_paint_commit.py` | Expanding the list alone does not change the UI's direct command/refresh calls. Keeping revision 37 also skips wrapper replacement in a UI 37 session. | Keep the verified Paint/Relax receipt implementation unchanged. |

## Core findings and selective merge

The supplied core cannot import: the `painted = rules.paint(...)` block is
misindented before the following `if compact` line (extracted source line 668).
After correcting only this indentation in an isolated review copy, the new
`_VALID_SAMPLES` cache accepted a sample whose coverage was changed to `-.25`
after its first validation. The same sample was rejected by UI 37.

`_TrackableDict` provides weak references; it does not track writes to itself,
sample dictionaries, or nested weight lists. Weak ownership solves a lifetime
problem but cannot prove data stayed valid. The proposed fallback also retains
large ordinary dictionaries strongly, including dictionaries loaded by JSON.
This removes UI 37's refusal to pin dictionaries over 8,192 entries. Neither
change is included.

UI 38's row-validation memo lives only for one `_validate_samples` call and
retains at most 256 row references. Shared distributions are checked once in
that call; every sample's vertex key and coverage are still checked. The next
validation starts fresh. The JSON sparse-descriptor memo also lasts for one
encode call and holds at most 256 entries. Metadata and layer dictionaries are
still serialized and saved on each authoring action.

Manual weight painting uses the existing `sparse-v1` representation when the
logical skin exceeds 2,000,000 values and has at least 16 influences. Newly
calculated rows are compacted only if fewer than one quarter of their entries
are nonzero. Dense/narrow rows keep lists; existing dense rows are not rewritten
merely by opening a scene. One-hot distributions can be shared by multiple
new samples. Mask values, coverage, redistribution order and lock math are
unchanged. Invalid nonzero entries are never filtered out during compaction.
Replace/Add/Scale planners that use the existing paint edit inherit this storage
choice; this does not add a new receipt or skip their UI refresh.

Sparse composition now scales the background row once and adds only nonzero
contributions. Full-alpha rows can reuse packed expansions inside one composite
call. That memo retains at most 256 entries and a 1 MiB allowance including
estimated entry overhead. It fills without repeated eviction and disables
itself when misses show little reuse. The additional unique-row benchmark
checks this case. No packed-row memo survives a composite call or modifies a
source distribution while composing later layers.

The schema stays **2**. UI 37 already understands sparse rows; encoded output
for an unchanged existing sparse state stays canonical. The immutable packed
base cache and all persistent validation-cache policies remain as in UI 37.

## Performance helper findings and selective merge

The proposed estimate treats an entire source as sparse when its first sample
is sparse, then charges a fixed 240 bytes per sample. Sources may contain both
dense and sparse rows, and each sparse row owns entry tuples and a lookup
dictionary of varying size. This estimate can therefore admit much more data
than the configured cache allowance. UI 38 keeps the existing conservative
per-row estimate. It may still evict compact states sooner than an exact
allocation analysis would, but does not adopt this new underestimate.

Scattered candidate rows are gathered from zero-copy C-buffer views in batches
of at most 262,144 values. Float32 inputs are promoted before arithmetic.
Candidate order and duplicates are preserved, only requested rows are compared,
and the absolute-tolerance/non-finite rules are retained. Known very small scopes
use direct row comparisons without initializing NumPy. Larger contiguous runs
keep UI 37's bounded path. Lists, unsupported/noncontiguous buffers and missing
NumPy use the row fallback; no complete mesh copy or difference matrix is made
for a scattered selection.

## Receipt findings

The only functional change in the proposed receipt file is the supported-action
set. UI 37's installer returns early for an existing runtime whose revision is
37. Because the replacement keeps that revision, an already-loaded wrapper can
continue using its old Paint/Relax action set after refresh. Merely enabling
the additional names on a cold load also does not request or consume receipts
in the current Set Weight/Flood/Mask/Clear button callers.

A complete extension needs a new runtime revision, caller integration and
verified display deltas for each operation, including unchanged commands,
disabled layers and clear-to-generated fallback. This selective merge does not
claim those button refresh savings. The existing exact-command receipt for
Paint and Relax, with its scope/payload/metadata checks, stays unchanged.

## Validation and use

**978/978 automated checks pass**, with no skips, errors or failures. The 21
new checks cover sparse/dense math equivalence; lock budgets and transparency;
sparse persistence and native-command Undo/Redo; invalid-value preservation and
mutation revalidation; local memo lifetime, size and low-reuse behavior; mixed
layers, arbitrary requested vertex order and duplicate candidates; bounded
scattered gathers, float32/non-finite rules and fallback paths. Existing UI,
warm-refresh, viewport, installer, external-edit, rollback and receipt checks
remain in the full suite. `LOCAL_TEST_RESULTS.txt` contains the full run.

`SPARSE_EDITS_BENCHMARK.json` records CPU phase measurements.
`benchmark_sparse_edits.py` includes UI 37 policy references so the measurements
can be repeated. They exclude native Maya reads/writes, DG and viewport time;
they are not full stroke-release timings. The reference/generated JSON, full
topology and live skin reads, lock checks, write readback and per-action save
are still present. Maya/Windows native performance remains unmeasured here.

Five-sample medians on Python 3.12.14 / NumPy 2.3.5, Linux:

| CPU fixture | UI 37 | UI 38 |
| --- | ---: | ---: |
| Composite 100k × 64, 16 shared rows, full opacity | 186.472 ms | 119.082 ms |
| Composite 100k × 64, 16 shared rows, half opacity | 1083.790 ms | 480.188 ms |
| Composite 100k × 64, every row unique, full opacity | 196.463 ms | 197.478 ms |
| Validate + encode 40k painted rows × 64 | 520.050 ms | 99.014 ms |
| Detect 64 scattered rows in 100k × 64 | 0.119 ms | 0.051 ms |
| Detect 8,192 scattered rows in 100k × 64 | 22.662 ms | 7.853 ms |

The unique-row fixture is about 0.5% slower, rather than showing a reuse gain.
The serialization fixture compares the old dense manual representation with
the compact representation, with the packed base already cached. It reduces
raw JSON from 11,883,773 to 3,923,773 bytes; the resulting encoded text is only
about 15% shorter because repeated zeros already compress well. The four-row
selection fixture also retains a direct path without NumPy setup. See the JSON
report for exact times and all scopes.

Replace the complete folder, run `layer_skin_ui_refresh.py` as `__main__`, confirm
**UI 38**, then click Paint. Registered plug-in version **0.4.1**, existing Undo
objects, UI 35's viewport fix, UI 36's NumPy installer and UI 37's Relax preview
coalescing/geometry improvements are retained.
