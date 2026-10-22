# UI 37: less repeated work during painting

The registered plug-in remains **0.4.1**. Replace the complete previous folder,
run `layer_skin_ui_refresh.py` with `run_name="__main__"`, confirm **UI 37**, and
click Paint to resume. The refresh retains registered commands and existing
Undo objects. UI 35's Select vertices renderer fix and UI 36's optional NumPy
installer are retained.

## Changes

* **Relax startup:** the native geometry adapter reads world positions lazily
  through `MFnMesh.getPoint`. A connected walk from the hit face replaces the
  whole-mesh position copy and Python spatial grid. It uses the same sphere,
  falloff, native screen circle and connectivity rule. Neighbors outside the
  footprint remain read-only solver support. Positions and projections are
  owned by one gesture, then discarded; a new pose never reuses an old gesture's
  position cache. Maya's existing intersection accelerator remains in use.
* **Relax preview:** every input event still generates the same solver stamps
  and updates the owned working values. Full native buffer upload and feedback
  reload are coalesced to at most 30 per second while dragging. A single-shot Qt
  timer publishes the latest pending change if the cursor stops. Release
  publishes the final values immediately. Escape, history shortcuts, tool
  cleanup and exit discard pending timers; cancellation restores the baseline.
* **Relax release:** an exact-command receipt supplies the saved layer state,
  full verified composite, metadata bytes and canonical hash. The session and
  queued UI refresh can accept that result without a second context read,
  serialization or full buffer upload. The receipt checks the requested action,
  payload, mesh/skin/UUID/topology/influence scope, current metadata and committed
  result. Missing or mismatched receipts use the existing verified preparation.
  Saved Relax rows are still checked against the submitted brush samples.
* **Relax guard:** startup uses the canonical state hash and the command's
  bounded expected-composite cache. A changed staged state refreshes from the
  already-read snapshot before previewing. Live skin weights are still read and
  compared before the gesture, and again by the authoring command at release.
* **Dirty-row scan:** contiguous candidate runs use optional NumPy in bounded,
  row-aligned blocks of at most 262,144 values. Small/scattered scopes retain
  row checks; without NumPy the original Python comparison is used. Candidate
  order, absolute tolerances, float32 promotion and non-finite rejection are
  covered by tests. Lock and driver checks run after identifying changed rows.

Paint info includes `preview_uploads`, `preview_fps`, and geometry position/
projection counts so native reports can distinguish large footprints from
repeated preview publication. These counters describe Relax gestures; native
Artisan Replace/Add/Scale keep their existing staging and receipt path.

## Measured CPU phases

Python 3.12.14, NumPy 2.3.5, Linux; five samples, medians. The complete report is
in `PAINT_LATENCY_BENCHMARK.json`. Run `benchmark_paint_latency.py` to repeat it.

| Phase | UI 36 | UI 37 |
| --- | ---: | ---: |
| Dirty-row scan, 100k vertices × 64 influences | 199.793 ms | 67.134 ms |
| Dirty-row scan, 200k vertices × 16 influences | 208.269 ms | 41.085 ms |
| Dirty-row scan, 250k vertices × 64 influences | 491.399 ms | 81.157 ms |
| Grid construction + first 37-vertex footprint on 250k vertices | 216.680 ms | 0.088 ms |
| Position vertices read by that geometry fixture | 250,000 | 57 |
| Full preview uploads, 240 input events in one simulated second | 240 | 28 |

The geometry benchmark excludes native Maya position access, intersection and
skin reads. The preview fixture exercises the real Qt publication gate with a
CPU buffer adapter and verifies the final array. It excludes DG/render time.
These are **phase measurements and operation counts, not whole-stroke Maya
speedups**. Native `getPoint` overhead and large footprints still need measuring
in Maya; a large brush naturally visits more vertices.

## Feedback reviewed and safeguards retained

The command already patches known dirty vertices through `composite_vertices`;
UI 37 does not add a duplicate composition path. Whole-mesh edits can still
require a full composite. Topology validation, full live skin reads, influence
locks, driven/locked weight plugs, transactional persistence, write readback,
rollback and native Undo/Redo remain enabled.

The suggested dirty-only live read was not adopted: metadata matching does not
prove that a different part of the skinCluster was not edited externally.
Saving only on tool exit would change persistence and Undo behavior, so each
action continues to serialize and save its metadata. Mutable manual-sample
dictionaries are not trusted by an identity-only validation/JSON cache.
Reference/generated JSON and all painted samples are still serialized. Those
costs, full topology hashing and the full live skin read remain possible
release bottlenecks. Set Weight/value-operation buttons retain their current
stop/refresh/resume flow; receipts added here cover Relax painting.

The geometry walk applies the 50,000-candidate budget to in-sphere vertices
visited by the connected walk, rather than scanning disconnected islands in the
global spatial box. It does not jump across vertices excluded by the sphere or
screen circle. Component selection continues to restrict writable vertices.

## Native Maya checks

1. Refresh the full folder and confirm UI 37. In Utilities → Performance,
   confirm NumPy is available; install or recheck it if needed.
2. On a production mesh, compare ordinary painting and Shift Relax startup,
   continuous drag, stopping the cursor, and release. Inspect Paint info for
   the position counts and preview uploads. Large brush footprints and many
   brush passes still require more solver work.
3. Release immediately after a fast drag, then switch joints/layers. Confirm
   the saved preview is stable. Escape during a pending drag must restore the
   previous values. Undo/Redo must restore the entire stroke as one action.
4. Repeat F9, Q → Y, B radius adjustment, tool changes and closing/refreshing
   with a pending gesture. Confirm there are no late preview writes or circles.
5. Edit skin weights externally on a vertex outside the next footprint. The
   next layer command must reject the edit instead of overwriting it.

**957/957 automated checks pass** with no skips/errors/failures. They include
randomized footprint equivalence against UI 36's grid, bounded vector blocks,
candidate scope/order, actual Qt timer publication, cancellation/error paths,
exact receipt validation, queued UI refresh, warm refresh and Undo/Redo.
Native Maya/Windows/VP2/GPU checks are unavailable on this host.

API reference used for lazy position access:
https://help.autodesk.com/cloudhelp/2024/ENU/MAYA-API-REF/py_ref/class_open_maya_1_1_m_fn_mesh.html
