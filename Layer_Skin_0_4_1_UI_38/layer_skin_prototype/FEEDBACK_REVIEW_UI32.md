# UI 32: brush-release performance review

The remaining command cost is real. UI 32 reduces it without switching to
painted-region-only external-edit detection. It does not promise instant
strokes or a 90% end-to-end reduction in Maya.

## Decisions on the feedback

| Suggestion | UI 32 decision |
| --- | --- |
| Avoid encoding state again for the expected-state guard | Implemented with a bounded digest cache keyed by exact metadata bytes, influence UUID order and encoder. Session stages the same guard used by the command. Legacy encoding and influence remapping canonicalize once. |
| Cache a digest using only id(state) | Replaced by the byte-based key. Object IDs can be reused, and decoding/remapping can create a different state object. Digest entries retain no state or weight buffer. Reload discards the previous encoder's keys. |
| Change compression level 6 to 1 | Implemented for both the outer state and its packed base buffer. Existing zlib-v1/schema-2 data remains readable. A first edit can rewrite legacy metadata using the new compression even when resulting weights are unchanged. File size can increase; the measured fixture grew about 4.6%. |
| Speed up the full tolerance comparison | Optional NumPy views and bounded chunks use the original absolute tolerance, without a relative tolerance. Float32 inputs are promoted before subtraction. Without NumPy the standard-library path remains available. No installation is required. |
| Pass dirty vertices to preflight | Already present in UI 31 and retained. |
| Skip child lock scans when the weightList parent is unlocked or has no connection | Rejected. A child can be locked or driven independently of its parent. Small strokes now inspect the parent, row, weights array and all allocated weight leaves only in changed rows. Large operations retain the bulk guard. |
| Reuse cached weights and read only touched vertices | Not enabled. That would miss an external edit elsewhere on the mesh. A receipt token or matching metadata does not prove that native skin weights are unchanged. Full live skin reads and full external-edit comparison remain. |

The original command commits at brush release rather than once per stamp.
Context also checks mesh history, input/output topology and influence identity;
those costs are separate from the listed weight and persistence operations.

## Implemented paths

### One encode for a staged native command

`layer_skin_performance.py` installs ordinary Python helpers around the loaded
0.4.1 owner. It keeps the registered MPxCommand class and existing Undo objects.
The planner verifies the expected hash, then removes that already-checked field
before invoking an older planner that would encode it again. Native editing,
full live-weight comparison, write verification and transactional rollback still
execute normally. New command source uses the same canonical guard directly.

A metadata wrapper associates the decoded/remapped state with exact live scene
bytes. Only that association can use the digest cache; an arbitrary new or
edited state must be encoded. The cache holds at most 128 entries. It does not
trust the newest decoded entry, retain only an object ID, or use raw hashes from
legacy encoding as if they were the current canonical hash.

The successful command's existing `remember(raw,state,weights)` publication seeds
the next canonical digest. Session's initial preparation uses that same helper.
UI 31 receipts still update the displayed delta and queued UI snapshot. Missing
receipts and newly bound joints keep their existing verified fallback paths.

### Reuse immutable packed bases within bounded memory

The base and reference are immutable snapshots under the existing `core.edit`
contract. Edits copy layer dictionaries and share that base; import/remapping
creates a new base. Large packed bases now cache their validation through a
weak reference, so validation does not pin those large buffers. A new base
object must validate; an invalid replacement is rejected.

A separate cache retains only the encoded immutable packed base, not mutable
samples, masks or a complete layer state. It has a 16 MiB payload budget and
four-entry limit. Weak ownership removes the payload when the base is no longer
in use. Changed samples and masks are serialized on every save. Clearing the
native transient cache clears these payloads and the digest cache too.

The decoded/composite cache still has its existing 64 MiB estimate cap. Its cost
estimate now counts packed float64 buffers at their allocation size plus one
float64 composite buffer rather than using the old Python-list estimate of 80
bytes per value. The conservative list/layer/reference estimates remain. The
200k/16 fixture fits at about 51.4 MB; a large reference or layer stack can exceed
the cap and use the normal decode/composition fallback. This is bounded reuse,
not a claim that all production scenes fit the cache.

Code that calls the pure core directly must respect its existing immutable-base
contract. Do not mutate a saved state's base array in place; construct/remap a
new state. The Maya UI/command path already follows this rule.

### Compare all live weights efficiently

Exact list/packed-array equality remains a cheap first path. For a large
near-equal buffer, optional NumPy compares chunks of at most 262,144 values in C;
packed arrays are viewed without a full conversion copy. Each comparison still
uses `abs(a-b) <= tolerance`. NaN differences fail rather than being accepted by
an inverted comparison. Small arrays and unavailable NumPy use the ordinary
Python calculation.

The result still covers every vertex and influence. Neither selection nor the
current brush footprint narrows the external-edit test.

### Check all relevant locks and drivers

For a small changed scope (at most 32,768 candidate vertex/influence values),
the native API checks `weightList`, each changed row, its weights array and each
allocated leaf. Both locks and incoming drivers are rejected. The affected row's
`evaluateNumElements()` includes connected elements that ordinary `numElements()`
may omit before evaluation. No whole-skin multi or connection enumeration is
needed for this path. Large floods retain the original bulk scan and affected-
row filtering. The threshold limits the small-stroke optimization; it does not
exclude a row from validation.

Node references/locks, metadata locks/drivers, influence locks and Maintain Max
Influences guards remain. No code unlocks an attribute or disconnects a driver.

## CPU measurements, not Maya release timings

`STROKE_GUARDS_BENCHMARK.json` records Python 3.12.14 and NumPy 2.3.5 on this host,
200,000 vertices, 16 influences, 3.2 million weights, 200 layer samples and three
repetitions. The fixture contains four nonzero weights per vertex.

| Measured phase | UI 31 policy | UI 32 policy |
| --- | ---: | ---: |
| Full near-equal tolerance comparison, median | 186.805 ms | 2.889 ms |
| One state encode, median | 715.721 ms | 290.155 ms |
| Encode calls per staged changed command | 2 | 1 |
| Encoded metadata bytes | 8,606,364 | 9,005,196 |

The new encode figure includes level-1 compression, weak validation reuse and a
reused packed-base encoding. It is not the effect of compression level alone.
The first new encode sample took 450.254 ms while preparing its packed payload;
the following samples took 290.155 and 280.056 ms. The baseline encoder follows
the previous large-base validation and level-6 compression policies.

These phases exclude Maya getWeights/setWeights, topology/history checks, plug
inspection, MDGModifier work, dependency evaluation, Artisan and VP2. They cannot
be summed into a measured Maya stroke or used to claim a 90% improvement. Full
JSON/persistence and live native reads remain, so large scenes can still pause
at release. See `benchmark_stroke_guards.py` for the reproducible CPU fixture.

## Verification and reload

The current suite and runtime limitations are recorded in `VALIDATION.md`.
Checks execute real native command planning and Undo against recording API
objects. They cover a large sequential command using the actual metadata/cache
code, legacy data, UUID remapping, one encode per staged command, cache eviction,
weak ownership, stale data, external edits outside the painted rows, write
rollback, locks/drivers at every scoped level, and unevaluated connected leaves.

Replace the complete folder, then run in Maya Python:

```python
import runpy
runpy.run_path(
    r"D:/dev/MayaZone/layer_skin_prototype/layer_skin_ui_refresh.py",
    run_name="__main__"
)
```

Confirm **UI 32**. The registered plug-in remains **0.4.1**. The refresh preserves
existing Undo objects and saves a valid pending stroke before swapping helpers;
it does not force-unload the plug-in or reset Undo.

Native Maya/VP2/PySide2 testing is still pending on this host. In a working copy
of a representative high-resolution scene, verify these cases:

1. Paint weights and masks across several releases, switch joints, and Undo/Redo.
   Repeat after a warm UI refresh, including an Undo record created before it.
2. Use F9, Q/Y, B + drag, selected vertices/edges and Shift-Relax. Verify retained
   feedback, selected scope and the absence of unrelated brush changes.
3. Change native skin weights outside the next brush region. The next layer
   edit must reject the external change; it must not overwrite it silently.
4. Lock or drive an affected weight leaf, its weights array or its row. The
   command must reject it. An unrelated locked row must remain untouched.
5. Load prior level-6 metadata, paint, save/reopen and Undo/Redo. Also exercise
   large references and layer stacks that exceed the cache estimate.
6. Time complete release latency for small dabs and broader strokes. Compare
   cold preparation, sequential strokes, NumPy availability and over-budget data
   separately from the CPU figures above.

A further sparse-only native path requires reliable invalidation for changes
outside the brush, including external API writes, membership/history changes
and Undo/Redo. It should be validated in Maya before replacing the full read.

## API references

- [Maya 2024 MPlug: array elements, connections and evaluation](https://help.autodesk.com/cloudhelp/2024/ENU/MAYA-API-REF/py_ref/class_open_maya_1_1_m_plug.html)
- [Maya 2024 listAttr flags](https://help.autodesk.com/cloudhelp/2024/ENU/Maya-Tech-Docs/CommandsPython/listAttr.html)
- [NumPy frombuffer views](https://numpy.org/doc/stable/reference/generated/numpy.frombuffer.html)
