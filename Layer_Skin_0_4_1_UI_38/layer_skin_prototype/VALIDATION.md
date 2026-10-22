# Layer Skin 0.4.1 · Authoring UI 38 validation

Date: 2026-10-22. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen,
NumPy 2.3.5.

**978/978 automated checks pass**, with no skips, errors or failures, in 51.569
seconds (51.860 seconds including runner/report overhead). All 88 Python files
parse with Python 3.10 grammar. `LOCAL_TEST_RESULTS.txt` contains the full run.

The 21 new checks are in `test_layer_skin_sparse_edits.py`: sparse/dense paint
equivalence, coverage and redistribution, joint-lock budgets, compact/narrow
storage selection, invalid-value rejection, persistence and native-command
Undo/Redo, revalidation after nested/manual dictionary changes, operation-local
memo reuse and release, packed-cache byte/entry limits and low-reuse disabling,
fractional sparse composition, mixed-layer equivalence, arbitrary requested
vertex order, bounded scattered gathers and small selections, float32 and
non-finite semantics, lists/noncontiguous buffers and missing NumPy.

The proposal was parsed and compared function by function against UI 37. Its
core replacement fails to import as supplied. An isolated copy correcting only
the indentation reproduced acceptance of negative coverage after the new
persistent sample cache was warmed; UI 37 rejected it. Those changes and the
first-sample memory estimate were excluded. Review details and scope decisions
are in `PROPOSAL_REVIEW_UI38.md`.

CPU policies are compared in `SPARSE_EDITS_BENCHMARK.json`, including shared and
unique sparse-row composition, dense/compact manual serialization, and small
and large scattered selections. These exclude native Maya skin/DG/viewport
work. Native Maya/Windows checks remain unavailable on this host.

The native command, skin read/write, storage codec, receipt implementation,
Relax geometry/solver/session, assignment, value-operation planner, installer,
VP2/viewport and IO sources stay byte-identical to UI 37. Registered plug-in
version remains 0.4.1. The UI warm refresh loads the updated core and performance
helpers without replacing the command class or existing Undo objects.

## Retained UI 37 validation

Date: 2026-10-22. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen,
NumPy 2.3.5.

**957/957 automated checks pass**, with no skips, errors or failures, in 46.826
seconds (47.032 seconds including report/runner overhead). All 86 Python files
parse with Python 3.10 grammar. `LOCAL_TEST_RESULTS.txt` contains the full run.

The 21 added checks cover grid/connected-walk equivalence over randomized
positions, graph connectivity, screen clips and dynamic radii; local reads on
a 250k-vertex fixture; candidate limits; chunk-aligned dirty scans, candidate
order/duplicates/scope, lists/generators, fallback and float32/non-finite rules;
Relax command receipts and action mismatches; external edits outside the brush;
write failure rollback; native Undo/Redo and runtime replacement; real Qt preview
coalescing, final publication, timer expiry, cancellation and upload failure;
canonical hash/composite reuse and stale staged views; and the queued UI refresh
consuming an exact Relax result without additional skin/context/buffer work.

`PAINT_LATENCY_BENCHMARK.json` records isolated CPU phases and actual publication
counts against UI 36 policies. `PAINT_PERFORMANCE_UI37.md` explains their limits.
Native Maya/Windows/VP2/GPU timing and behavior still require a native check.

Core/serialization, storage, skin reads/writes, Relax solver/planner, assignment,
operations, optional NumPy installer, viewport/VP2 and IO sources are unchanged
from UI 36. The native command's change only exposes the new receipt entry point
in `editor_api`; command planning, persistence and Undo code remain unchanged.
The cache-key assertion in the warm-refresh test now runs inside its isolated
module-dictionary patch so it is independent of prior helper loading.

## Retained UI 36 validation

Date: 2026-10-22. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen.

**936/936 automated checks pass**, with no skips, errors or failures, in 45.227
seconds. All 84 Python files parse with Python 3.10 grammar. The 29 new checks
for dependency planning, backend retry and real Qt installer controls pass in
0.299 seconds. Existing command/guard, Undo/Redo, painting, selection/VP2, cache,
assignment, Relax, IO and warm-refresh checks remain in the full suite.

The installer launches no download or package installation until an explicit
Install click. Tests cover Python/ABI checks and mayapy discovery; pinned,
binary-only target arguments; matching staged-version/file verification; atomic
activation and failed-publication rollback; invalid manifest and removal paths;
negative import-cache retry and binary-import fallback; persistent Maya user-root
configuration; active command-helper selection; successful installation and
Recheck; failed child start, pip and verification; timeout, Cancel and close;
unsupported Python and a verified installation requiring a Maya restart.

The separate installation integration test starts a fresh CPython process with
site-packages disabled. Real QProcess/pip install a local NumPy 1.26.4 Linux wheel
into an isolated staging folder, verify it in a child, activate it and import it
in the running parent without a restart. A 20,000-value tolerance comparison
passes and 351 Qt heartbeat events run over 3.646 seconds. This is an installation
functionality check, not a Maya performance benchmark. Its report is included.

The 1280×940 Utilities layout was visually inspected. The Performance group
fits at the top, progress/details are available during installation, and the
existing primary import actions remain outside the scrolling options.

The registered plug-in remains 0.4.1. Native command, core/serialization, skin
read/write, paint commit, Relax, assignment, storage, VP2 and IO sources remain
byte-identical to UI 35. Performance helper changes are limited to optional
dependency path configuration, import retry and import-error fallback; the
comparison math, guards, tolerances and guard-cache revision are unchanged.

Native Maya/Windows/PySide2 integration remains pending. The integration run
used matching CPython as a stand-in for unavailable mayapy and did not test
Maya's DLL environment or network policy. NUMPY_INSTALL_UI36.md records usage,
supported versions, failure behavior, reload and native verification scope.

---

## Previous UI 35 validation

Date: 2026-10-22. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen.

**907/907 automated checks pass**, with no skips, errors or failures, in 44.872
seconds. All 80 Python files parse with Python 3.10 grammar. The focused VP2,
component-selection and refresh run passed 57 checks in 2.723 seconds.

Before changing production code, the viewport fixture was corrected to model
MHUDRender's zero-argument constructor separately from named present operations.
The existing scene-preservation test then reproduced the TypeError at the old
MHUDRender('rtkLayerSkinHUD') call. UI 35 uses the default constructor. The
stricter fixture now exercises the complete viewport suite.

Four new checks cover a HUD constructor TypeError while heat-map triangles still
draw, unchanged artist/skin/scene state and complete panel/callback cleanup;
required scene/present constructor failures propagating; real default factories
loading both new helper keys despite cached pre-fix modules; and the actual Qt
Select vertices flow retaining a visible preview with the optional HUD omitted.
The existing operation-iterator check now verifies the separate default HUD.
Warm refresh, Q/Y/F9, Undo/Redo, brush and external-edit checks remain in the suite.

Paint info reports renderer revision 35, HUD availability and any HUD constructor
error. A HUD binding TypeError no longer blocks the scene/present passes. The
fallback may omit the standard HUD while the selection view is attached. It
does not create color sets, history or scene nodes. Required rendering failures
are not suppressed. The optional native smoke script checks renderer revision
instead of rejecting current windows because their title is no longer UI 33.

The registered plug-in remains 0.4.1. Skin command, core, weight guards,
serialization, Relax, assignment, storage and IO sources remain byte-identical
to UI 34. Existing registered commands and native Undo objects are retained.

Native Maya/VP2/PySide2/GPU checks remain pending because Maya is unavailable on
this host. These tests reproduce the constructor contract and record draw/API
calls; they do not verify native raster colors, picking or HUD layout. See
HUD_CONSTRUCTOR_UI35.md for the correction, fallback, reload and native checks.

---

## Previous UI 34 validation

Date: 2026-10-22. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen.

**903/903 automated checks pass**, with no skips, errors or failures, in 27.255
seconds. All 80 Python files parse with Python 3.10 grammar. The unchanged
uploaded UI 33 package also passed its 886 checks on this host before editing.

Seventeen additional checks cover multi-layer/Base summary reuse, generated
replacement and zero-coverage manual overrides, mask/property/membership edits,
influence ordering, new mesh/base snapshots, selective invalidation, inactive
snapshot release, deleted layers, full-stack bounds, missing IDs, actual Qt
layer revisits, paint plus Undo/Redo and memory-cache cleanup. Topology-cache
checks cover incremental cost, repeated/duplicate scopes, cancellation and
native-query exceptions, cache clearing during cancellation, LRU/byte limits,
empty requests and a zero-item budget.

The CPU benchmark uses identical results and warm caches over nine repetitions.
At 200k vertices / 16 influences, three summary revisits changed from 383.994
to 0.011 ms. A 64-vertex topology lookup after caching 100k rows changed from
6.072 to 0.007 ms, retaining the same 26,000,000-byte estimate and zero new native
neighbor reads. These measure the affected CPU phases only, excluding native
skin/command/DG/Artisan/viewport work and complete action latency. The benchmark
script, JSON results and scope are included in WORKFLOW_REFRESH_UI34.md.

The registered plug-in remains 0.4.1. Production changes are limited to the
window-owned hierarchy summary cache, read-only topology-cache accounting and
the UI/refresh revision label. The Relax solver math is unchanged. Skin command,
weight guards, persistence, brush footprint, painting, VP2 and IO files remain
byte-identical to the uploaded UI 33 package. Existing native Undo objects
remain registered.

Native Maya/VP2/PySide2/GPU checks remain pending because Maya is unavailable
on this host. WORKFLOW_REFRESH_UI34.md includes reload and native checks. The
automated suite records API calls and uses actual offscreen Qt widgets; it
does not establish end-to-end Maya performance or native viewport correctness.

---

## Previous UI 33 validation

Date: 2026-10-22. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen.

**886/886 automated checks pass**, with no skips, errors or failures, in 26.251
seconds. All 78 Python files parse with Python 3.10 grammar. The prior CPV display
checks now test the VP2 display contract; there are 16 additional checks overall.

Eighteen display-adapter checks exercise the real WeightView and VP2 renderer
classes against recording API objects. No DG modifiers, color-set operations,
mesh-history edits or shader/display plug writes are used. Artist scene state
is unchanged. The draw uses indexed vertex colors, nonselectable geometry,
enabled depth testing and a fill priority below native wire/point priorities.
The scene/HUD/present operations and default picking are retained. Viewport
registration/cleanup, custom-renderer preservation, hidden/isolated objects,
polygon filtering, failed restore retry, deleted-node callbacks, geometry
invalidation, bounded palettes and unchanged versioned views are covered.
A 250,000-vertex fixture reuses geometry across multiple clean draws without
getPoints/getTriangles rereads or skin access.

Nine Qt regressions cover Select before any Paint buffer is created, one saved
pending stroke, repeated Select, component setup invalidating outgoing feedback,
Q/Y handoff and mode indicators, coalesced mode events without skin/array/encode
work, joint changes that preserve selected components, and cancellation on
Stop, Paint or close. The color-transition guard avoids repeated publication
when the correct passive view is already visible. The 1280x940 offscreen UI was
visually inspected; the Paint/Select/Stop row fits and the selection state is
shown. This verifies the actual widget layout, not native viewport pixels.

All earlier command, Undo/Redo, high-resolution guard/persistence, external-edit,
assignment, painting, Relax, influence lock, hierarchy, IO and warm-refresh checks
remain. Native skin/core/performance/read-write/brush/Relax/assignment/IO files
are byte-identical to UI 32. No skin solver or command registration change.

The registered plug-in remains 0.4.1. The refresh uses a new viewport helper key
so a previously imported CPV implementation is not reused. The old live window
can roll back its owned preview before the new window is shown. No global
color-node deletion, plug-in force unload or Undo reset is introduced. The
existing Artisan paint buffer remains for native Undo and is not created by
vertex selection.

Native Maya/VP2/PySide2/GPU verification remains pending because this host has
no Maya runtime. Recording tests do not emulate rasterization, depth, color
management, specialized viewport filters, component picking or GPU performance.
The new maya_layer_skin_viewport_smoke.py requests a real VP2 draw in Maya,
compares node UUIDs/history/color-set names/modified flag and checks that the
draw callback ran. It has not been run here. VERTEX_SELECTION_UI33.md includes
reload instructions, limits and the visual/native checklist.

---

## Previous UI 32 validation

Date: 2026-10-22. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen.

**870/870 automated checks pass**, with no skips, errors or failures, in 23.852
seconds. All 75 Python files parse with Python 3.10 grammar. Thirty-four checks
are new for canonical digest reuse, encoding, optional vector comparisons,
bounded immutable-base reuse and scoped native plug guards.

The real command planner and Undo run against recording Maya API objects. A
200,000-vertex / 16-influence sequential-command test uses the actual metadata,
decoded/composite cache and canonical guard. It retains the immutable base,
reuses its encoded payload and preserves write verification and Undo/Redo.
Changed staged commands call the state encoder once. Full context reads still
run for each command; edits to native weights outside the painted region reject.

Checks cover previous level-6 encoding, list and packed bases, UUID remapping,
encoder refresh invalidation without retaining old core modules, over-budget
states, weak payload ownership, invalid new bases, mutable samples saved after
base reuse, failed write rollback, and old Undo records after helper installation.
Optional NumPy comparisons retain the original absolute tolerance, promote
float32 inputs, reject NaN differences, bound temporary chunks and have a tested
standard-library fallback. Scoped plug checks cover row/array/leaf locks and
drivers, sparse logical indices, unevaluated connected elements and bulk fallback.
All prior component, F9/Q/Y, B sizing, brush, Relax, receipts, preview, hierarchy,
assignment, IO, lock, cleanup and warm-refresh tests remain.

CPU phase measurements in STROKE_GUARDS_BENCHMARK.json use 200k vertices and
16 influences. The full near-equal comparison median changed from 186.805 to
2.889 ms. One encode changed from 715.721 to 290.155 ms using level-1 compression
and a reused immutable base. Changed staged commands encode once rather than
twice. Metadata grew from 8,606,364 to 9,005,196 bytes. These exclude Maya native
skin reads/writes, topology, DG, plug scans, Artisan and VP2, and are not measured
end-to-end release timings. No 90% improvement or instant stroke is claimed.

The registered plug-in version remains 0.4.1. UI refresh installs ordinary
Python helpers and a compatible core while preserving the MPxCommand class,
old Undo objects and pending-stroke handling. No force unload or Undo reset.
Full live weights/external-edit validation, transactional writes and write
readback remain. Core schema/composition math, skin IO formats, assignment,
brush geometry and Relax math are unchanged. The packed-base encoding remains
zlib-v1; both old and new compression levels are readable.

Native Maya/VP2/PySide2 verification is pending: this host has no Maya runtime.
The previous visual layout is retained; current Qt tests verify the UI 32 title
and open/refresh behavior. Replace the complete folder, run the refresh entry
point and confirm UI 32. FEEDBACK_REVIEW_UI32.md includes the decisions, exact
cache limits, CPU fixture, remaining full-mesh costs and native checklist.

---

## Previous UI 31 validation

Date: 2026-10-21. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen.

**836/836 automated checks pass**, with no skips, errors or failures, in 23.554
seconds. All 72 Python files parse with Python 3.10 grammar. Seventeen checks
are new for exact-command receipts, surface binding and preview reuse.

The real command planner/Undo code is exercised with recording Maya API objects.
Receipts are checked against the exact saved metadata, mesh identity and scope;
wrong identities, unrelated last-cache entries, cache-budget eviction, failed
native writes and metadata changes after remember are covered. Installation is
idempotent, existing Undo objects work, unrequested commands retain their normal
single argument parse, and stale-state/external-native-edit guards still reject.

The Session/UI check prohibits another context/metadata read, prepare call or
full buffer upload after a supported successful receipt, including its queued UI
refresh. A 250,000-vertex / eight-influence fixture applies twenty displayed
entries without iterating the displayed list or encoding state in this phase.
This tests post-command bookkeeping; native validation/serialization and actual
Maya release latency are not measured or claimed constant-time.

Surface rebinding preserves native component entries, adds the loaded parent
object atomically, and restores Artisan feedback once for coalesced mode events.
Reentrant native callbacks during binding remain display-only. Preview tests
retain one private set and three owned edit objects over thirty color/ramp
changes, restore artist colors/history/settings on close, and skip value scans
when a versioned view is unchanged. All earlier painting, footprint, Relax,
assignment, IO, lock, hierarchy, callback and warm-refresh checks remain.

Changes include an ordinary Python doIt/remember wrapper installed without
re-registering the command class, native editor-API exports, refreshed UI/session
bookkeeping, viewport helper/cache revisions and focused tests/docs. The original
native doIt planning/rollback, skin read/write/verification, preflight lock checks,
core composition/schema, assignment, brush geometry, Relax math and skin IO are
retained. No scene-wide node deletion, force unload or Undo reset is introduced.

Temporary CPV history still exists while the colored passive Select view is
visible. It is reused, and its retained modifiers clear owned edits on Paint,
Stop/close and before file IO. Active F9 painting uses Artisan. This release does
not implement a completely node-free selection renderer or sparse-only native
validation. See FEEDBACK_REVIEW_UI31.md for the feedback assessment and limits.

The actual 1280 × 940 UI was inspected with Qt offscreen. Paint, Select vertices
and Stop / shaded view fit together without clipping. Native Maya/VP2/PySide2
validation remains pending because this host has no Maya. Replace the complete
folder, run layer_skin_ui_refresh.py, confirm **UI 31**, and use the checklist in
FEEDBACK_REVIEW_UI31.md, including history ownership, F9/Q/Y, Undo/Redo and
high-resolution stroke-release timings.

---

## Previous UI 30 validation


Date: 2026-10-21. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen.

**819/819 automated checks pass**, with no skips, errors or failures, in 23.558
seconds. All 70 Python files parse with Python 3.10 grammar. Twenty-two new
checks cover the feedback changes; existing component/tool tests now verify
preserved component painting instead of UI 29's forced Select handoff.

New coverage includes ready stroke startup without prepare/context/metadata/
array/encode work, passive array/surface aliases, ambiguous names and retargeting,
canonical hashes with remapped influence order, readonly/unchanged state hash
reuse, stale metadata rejection, Undo invalidation, selected-scope native array
and scalar painting, and restoring a rejected scope before another stroke.

Real Qt checks include a QShortcut that consumes B without a viewport KeyPress,
ShortcutOverride-only sizing with zero settings sync while either B or the mouse
is held, both release orders, modified keys/text fields, shortcut events at a
parent window, Q/Y component and scalar-setting restoration, external-edit
rejection on return, cancelled queued re-entry, and selected-scope Shift-Relax.
The existing suites retain pending-stroke, validation, Undo, locks, assignment,
IO, brush boundary, native-feedback recording and safe UI refresh coverage.

CPU recording-API replay after staging, eight influences and 500 iterations:

| Vertices | Cached callbacks + header, ms/iteration | Heavy data/lookup calls |
| --- | ---: | ---: |
| 100,000 | 0.005323 | 0 |
| 250,000 | 0.005191 | 0 |

Each iteration exercises known transform/shape/component surface and array
aliases and an unpainted stroke header. Both cases record zero skin-context or
metadata reads, array reads/writes, state encodes, name lookups and parent
queries. The recording Undo adapter uses balanced markers instead of its
fixture-only whole-scene deepcopy. These figures exclude real painting, array
diff, commits, geometry, Maya scheduling, Artisan drawing and VP2/GPU cost.
See PAINT_LIFECYCLE_BENCHMARK.json and benchmark_paint_lifecycle.py. Historical
UI 28 radius timings remain in their original JSON; the current radius script
uses UI 30's cached header and is no longer that historical unguarded baseline.

Changes are limited to session/cache and tool lifecycle, keyboard/settings
routing, a compatible optional-empty selection-scope utility argument, UI hints
and refresh keys, docs, tests and recording benchmarks. The native plug-in,
composition/schema, skin IO, nearest assignment, joint hierarchy and lock code
are byte-for-byte unchanged from UI 29. Relax math and brush geometry/footprints
are unchanged; selected component scope is intersected before custom Relax
stamps and enforced on saved native array changes. Commit validation remains.
No polling, scene scriptJob, per-frame solver or plug-in unload is added.

The actual 1280 × 940 UI was inspected with Qt offscreen. Paint, Select vertices
and Stop / shaded view fit together; the updated workflow text is visible.
Native Maya/VP2/PySide2 testing remains pending because this host has no Maya.
Replace the complete folder, run layer_skin_ui_refresh.py and confirm **UI 30**.
Use COMPONENT_SELECTION.md for the native checklist and
BRUSH_LIFECYCLE_UPDATES.md for the feedback assessment and implementation notes.

---

## Previous UI 29 validation


Date: 2026-10-21. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen.

**797/797 automated checks pass**, with no skips, errors or failures, in 23.603
seconds. All 68 Python files parse with Python 3.10 grammar. Fourteen new checks
exercise active Artisan to component-selection handoff using real Qt key events
and a recording Maya API.

Coverage includes F8/F9/F10/F11, right-click/programmatic component mode and
component-type events, the Select vertices button, preserving existing selected
vertices, pending paint saved once with Undo, failed-save recovery, handoff during
the radius guard, unrelated widgets/modifiers, retaining B-adjusted radius, mask
and read-only skin displays, native cleanup plus ToolChanged fallback, and color
staging before outgoing feedback disappears. Tests prohibit skin/context/array
work and display-range rescans during ordinary component clicks. A native-feedback
recording probe confirms the retained colors are ready before its context ends;
this does not validate real VP2 frame scheduling.

Changes are limited to session/tool lifecycle, two selection-mode/type event
listeners, viewport hotkey routing, a selection button, redundant display-range
work, helper refresh keys, docs and tests. Brush footprints and Relax math,
nearest assignment, layer composition/schema, the native plug-in, locks and skin
IO algorithms are unchanged. The existing callback teardown and coalesced UI
dispatch are reused; no polling or per-frame callback is added.

The actual 1280 × 940 UI was inspected with Qt offscreen. The Paint, Select
vertices and Stop / shaded view buttons fit together without clipping.
Native Maya/PySide2 verification remains pending because this host has no Maya.
Replace the complete folder, run `layer_skin_ui_refresh.py`, confirm **UI 29**
and follow [COMPONENT_SELECTION.md](COMPONENT_SELECTION.md).

---

## Previous UI 28 validation

Date: 2026-10-21. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen.

**783/783 automated checks pass**, with no skips, errors or failures, in 21.256
seconds. This is the full host suite. Eleven new real-Qt radius tests cover field
edits and B-drag, reentrant native callbacks, both key/mouse release orders,
read-only display, deferred callbacks, settings failures, queued UI refresh,
normal painting afterward, pending paint/Relax preservation, unrelated UI keys
and warm loading of the updated handler. All 67 Python files parse with Python
3.10 grammar.

During sizing, context/metadata reads, state encode/composition, paint-buffer
reads/writes, feedback reload and preparation are configured to fail in tests.
Radius interactions complete without calling them. Saved state, selected paint
joint, values, buffer object and layer Undo remain intact. A real pre-existing
stroke is saved once, after which the same no-work assertions apply while sizing.
Its queued full refresh waits until after sizing finishes. Normal native-array
painting then commits and verifies saved values as before.

CPU recording-API callback replay, eight influences:

| Vertices | Unguarded path, ms/update | Settings-only path, ms/update | Settings-only heavy calls |
| --- | ---: | ---: | --- |
| 100,000 | 51.563 | 0.062 | 0 |
| 250,000 | 245.355 | 0.171 | 0 |

Each unguarded update performs one skin-context read, metadata read, array read,
array write and state encode. Both guarded 200-update runs perform zero of each.
The unguarded replay reproduces the previous Python callback path. These are
not measurements of Maya's actual event ordering, native circle rendering or
VP2/GPU cost. See `BRUSH_RADIUS_BENCHMARK.json` and
`benchmark_brush_radius.run()` for the reproducible fixture.

Changes are limited to session/settings lifecycle, viewport event routing,
scalar UI updates and deferral, the brush helper key, title/refresh labels,
docs and tests. Geometry/brush footprints, Relax math, nearest assignment,
composition/schema, native plug-in, layer locks and skin IO algorithms are
unchanged. The existing application event filter and coalesced idle sync are
reused; no per-frame solver, scene callback or polling timer is added.

Native Maya/PySide2 validation remains pending because this host has no Maya.
After replacing the complete folder and running `layer_skin_ui_refresh.py`,
confirm **UI 28** and use the checklist in
[BRUSH_RADIUS_UPDATES.md](BRUSH_RADIUS_UPDATES.md). It covers real B-drag and
field edits on a high-resolution mesh, Paint info counters, viewport colors,
pending strokes, normal/Shift paint, radius bounds and Undo/Redo.

---

## Previous UI 27 validation

Date: 2026-10-21. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen.

**772/772 automated checks pass**, with no skips, errors or failures, in 21.543
seconds. This is the full host suite, including assignment, composition,
production IO, locks, brush/Relax, session, hierarchy, Qt UI and safe refresh.
Eight tests are new; previous radius/positive-only expectations are updated to
the new nearest assignment contract. All 65 Python files parse with Python 3.10
grammar.

New regressions compare random nearest pivots and finite segments against a
brute-force reference, including forks and zero-length bones. They verify that
all scoped vertices are assigned even behind every axis, and that a remote
positive-axis bone cannot override a closer negative-side bone. Coincident
bones test axis preference, logical depth and UUID order. Mirrored, sheared and
rotated axes, selected scope, cancellation/timeout, cache reuse, binding rollback,
locks, masks, paint preservation and Undo/Redo are included.

A large assignment retains compact immutable rows through core edits, scene
encoding/decoding and composition. An old registered planner receives sanitized
settings before obsolete unit conversions, retains its command class and can
undo/redo the new result. Native-command behavior is exercised with a recording
API; it does not substitute for running the command inside Maya.

The CPU-only benchmark verifies every generated row for **100,000 vertices ×
339 influences**. Nearest joint took 1.253 seconds, nearest bone 1.263 seconds,
and bone + axis 1.258 seconds. Cached repeats took 0.015–0.019 seconds with no
new distance tests. Candidate tests were 257,118 for points and 284,099 for
bones/axis, against 33,900,000 full pairs. Outputs use compact sparse rows.
See `NEAREST_ASSIGNMENT_BENCHMARK.json` and
`benchmark_nearest_assignment.run()` for the exact fixture and exclusions.
Maya IO, skin writes, binding, metadata encoding and viewport time are excluded.
These times are fixture-specific; overlapping bone bounds can require more work.

Changes include the pure geometry planner/index/cache, removal of assignment
Radius/Falloff, removal/sanitizing of obsolete unit settings, one core copy path
that retains existing immutable sparse rows, UI title/refresh keys, docs and
tests. The plug-in remains 0.4.1 and saved schema remains 2. Safe refresh keeps
the registered command class and existing Undo objects. Core composition,
brush, Relax, viewport feedback, lock rules and skin IO algorithms are unchanged.
No per-frame callbacks or global progress window are introduced.

Native Maya/PySide2 validation is pending because this host has no Maya. After
replacing the complete folder, run `layer_skin_ui_refresh.py` and confirm UI 27.

1. Check that Assign weights has Method, Axis, Scope and paint-preservation
   options, with no Radius or Falloff. Brush Radius/Falloff must remain usable.
2. Select the desired hierarchy branch and assign with all three methods.
   Include vertices far from the bones and behind every chosen local axis;
   generated coverage should include every scoped vertex.
3. Use two nearby/crossing branches with opposite orientations. Check that a
   farther positive-axis bone cannot take over the closest region. At shared
   endpoints, confirm the axis preference and stable depth/UUID tie order.
4. Test Selected vertices, masks, alpha, influence locks and preserved paint.
   Check Undo/Redo, cancel during generation and a repeated cached assignment.
5. Run `maya_layer_skin_hierarchy_smoke.run()` for all three methods and
   negative-side coverage. Run `maya_layer_skin_predeform_smoke.run()` to check
   pose/reference consistency. Both actual Maya runs remain pending.

---

## Previous UI 26 validation

Date: 2026-10-21. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen.

**260/260 focused checks pass**, with no skips, errors or failures, in 7.711
seconds. The run includes the complete session, painting UI, hierarchy search,
UI refresh and new hierarchy-action suites. Twelve new checks exercise actual
Qt mouse gestures and button clicks. All 63 Python files parse with Python 3.10
grammar. This Qt-only update retains the UI 25 package's validated assignment,
composition, IO and native command code; unrelated solver/IO suites were not
rerun.

Coverage includes recursive expansion by Shift-clicking rows or arrows,
idempotent expansion and ordinary arrow collapse, Ctrl/Shift selection,
padlock precedence, inclusive branch selection across buffer transforms and
duplicate short names, overlapping roots, hidden/collapsed children, current
paint-target retention, one batched selection notification, no selection,
search clearing/rebuild and cached traversal without Maya DAG queries.
Pending strokes and feedback remain intact when the active joint is unchanged;
switching to another joint saves the previous stroke once and restores its
painted values on return.

The native plug-in, composition/schema, brush, Relax, locks, feedback, assignment
and skin IO implementations are byte-for-byte unchanged. Changes are limited
to the Qt joint-view helper, UI title, safe-refresh key/message, documentation
and tests. No new callbacks, script jobs or timers are installed in Maya.

Native Maya/PySide2 validation remains pending because this host has no Maya.
After replacing the complete folder and running `layer_skin_ui_refresh.py`,
confirm **UI 26**, then check:

1. Collapse a branching skeleton. Shift-click a row and its arrow; every child
   level opens, and a normal arrow click still collapses the branch.
2. Select a root and click **Select joint + descendants**. Confirm the root,
   child joints under buffer groups and collapsed children are selected. With
   multiple roots, confirm their combined branches and the current paint joint.
3. Search for a parent, select its branch and clear Search. The hidden children
   should now show as selected. Explicit expansion during search stays expanded.
4. Repeat on the active paint joint during a stroke. Confirm paint colors,
   pending values, viewport selection and Undo history stay intact. Shift-click
   a different joint and return; the previous stroke should be preserved.
5. Shift-click a padlock. Only the lock changes, using its usual undoable action.
   Refresh the UI and confirm both new hierarchy actions are still available.

---

## Previous UI 25 validation

Date: 2026-10-21. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen.

**752/752 automated checks pass**, with no skips, errors or failures, in 54.944
seconds. Fourteen checks are new for pre-skin reference capture. All 62 Python
files parse with Python 3.10 grammar. An earlier focused run passed 281 checks
for capture, assignment, hierarchy, native command planning, UI, refresh and
production IO.

The new recording-API tests read object-space points only from the exact skin
input and map them using the geometry bind matrix. Bound joint frames use the
inverse bind-pre matrix at the logical influence index; a fixture with holes
at indices 7 and 31 ensures physical weight columns are not mistaken for matrix
indices. A legacy context resolves its input geometry at the actual output
shape index rather than inspecting intermediate shape names.

For an unchanged input, point/bone/axis assignments agree after changing live
joint poses and the output mesh transform. Mirrored, rotated and nonuniform
bind geometry is compared in one space. Unbound child offsets are placed under
an ancestor bind frame; separate roots use a mesh-relative captured offset.
Missing input contexts, singular bind data and changed vertex counts fail
without substituting visible mesh points.

Migration tests retain old references until explicit Assign, preserve layer
data, reuse current references without live reads, invalidate on explicit
recapture of changed input points, and update an already installed planner.
The complete recording command roundtrips old/new reference metadata and skin
weights through Undo/Redo without replacing its command class. A production
context test also verifies separate input and output mesh handles.

The registered command class, composition/schema, brush, Relax, display and
skin IO modules remain unchanged. The ordinary reference helper and context
return value change, along with the UI title, source label and refresh key.
The context already resolved the input mesh for topology checks; it now retains
that function set for reference capture too.

Native Maya is unavailable on this build host. The supplied
`maya_layer_skin_predeform_smoke.run()` checks actual pre-skin points, bind
frames and assignments after moving/scaling the fixture and posing a joint.
Its native evaluation remains pending. See
[PREDEFORM_REFERENCE.md](PREDEFORM_REFERENCE.md) for geometry spaces, upstream
deformers, unbound-joint limits, cache and reload details.

---

## Previous UI 24 validation

Date: 2026-10-21. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen.

**738/738 automated checks pass**, with no skips, errors or failures, in 26.050
seconds. Seventeen checks are new for hierarchy assignment. All 60 Python files
parse with Python 3.10 grammar. An earlier focused run passed 333 existing
assignment, command, session, UI, refresh and hierarchy-search checks.

The new cases cover duplicate short names under different buffer groups,
unequal group depths, sparse selected branches, all fork bone endpoints,
single-chain child-first behavior, negative axes, scoped/unassigned vertices,
deterministic ordering and cached results. Random nearest-eligible BVH results
match a brute-force reference. A 96-branch fixture verifies spatial pruning.
Cancellation stores no partial result.

Reference tests verify traversal through transforms, unchanged frozen points,
positions, bases and time during legacy upgrade, and reuse without later scene
queries. The warm-helper test retains the registered command class, upgrades a
legacy planner, assigns the expected branch weights and roundtrips metadata and
weights through Undo/Redo. The real Qt case assigns buffered joints with
identical short names and preserves hierarchy and Maya selections.

The core composition, saved layer schema, native command class definition,
brush, Relax, locks, feedback and skin IO modules remain unchanged. The plug-in
source now delegates reference capture/root discovery and reference upgrade to
a new ordinary Python helper; safe UI refresh installs it into an existing
0.4.1 owner. Reference records gain optional UUID parent links and a hierarchy
version, using existing frozen positions rather than the current posed mesh.

Native Maya is unavailable on this build host. After replacing the complete
folder and running `layer_skin_ui_refresh.py`, confirm UI 24 and run:

```python
import maya_layer_skin_hierarchy_smoke
maya_layer_skin_hierarchy_smoke.run()
```

The native test creates its own small buffered fork with repeated names,
assigns actual skin weights and checks frozen endpoints, base fallback,
Undo/Redo and joint transforms. It does not open a new scene or clear Undo.
Test a copy of the user's complex rig after this fixture; geometry-specific
assignment quality is not established by host tests alone. See
[HIERARCHY_ASSIGNMENT.md](HIERARCHY_ASSIGNMENT.md) for the exact rules.

---

## Previous UI 23 validation

Date: 2026-10-21. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen.

**157/157 focused checks pass**, with no skips, errors or failures, in 10.442
seconds. This run includes the joint hierarchy, full painting UI and UI refresh
suites, plus ten new search checks. All 57 Python files parse with Python 3.10
grammar. This update uses the previously validated UI 22 package as its base;
the full unrelated solver/IO suite was not rerun for this Qt-only change.

The new checks cover the field above the tree, plain text, repeated wildcard
stars, case folding, namespace handling, one-character wildcards, ancestor
visibility, no matches, clear/expansion restoration, hidden multi-selection,
rebuild, click-to-paint, padlocks, pending strokes and safe UI refresh.
Typing is checked with Maya DAG query methods set to fail: the filter uses
existing rows without querying the scene or committing paint.

The command/native plug-in, core/schema, brush, Relax, locks, feedback and skin
IO algorithms are byte-for-byte unchanged. Search changes the Qt tree helper,
adds safe-refresh retention of its query, and updates the authoring title.

Native Maya checks (pending):

1. Replace the complete folder and run `layer_skin_ui_refresh.py`. Confirm
   **UI 23** and a Search field at the top of the hierarchy dock.
2. Type `left**Shoulder**`, `Shoulder`, and a nonexistent name. Verify direct
   matches, ancestor context, count and the no-match message.
3. Filter while weights or mask colors are visible. Confirm the current joint,
   colors and skin weights stay unchanged; select a result and paint normally.
4. Toggle a visible result's padlock, refresh the hierarchy and clear the query.
   Verify filtering, saved edits, selection and collapsed branches.
5. Refresh the complete UI while a query is entered. Verify the query and current
   joint are retained. The native command version remains 0.4.1.

---

## Previous UI 22 validation

Date: 2026-10-21. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen.

**711/711 automated checks pass**, with no skips, errors or failures. The full
suite completed in 27.243 seconds. Twenty checks are new for entry-point/window
discovery. All 56 Python files parse with Python 3.10 grammar. The focused
launch/refresh/UI run also passes all 154 checks.

The refresh entry point now opens its sibling path/version-aware launcher when
no editor exists. It finds hidden and embedded editors, skips closed/deleted
Qt objects and unrelated same-named widgets, and reports multiple live editors
without selecting or closing one arbitrarily. Plug-in registration/path/version
guards remain active. An explicit-window refresh follows the previous workflow.

New entry-point and real-Qt tests cover first launch, reuse, hidden/embedded
discovery, fresh open followed by helper refresh, duplicate/deleted editors,
missing files, launch failures, version/path mismatches and existing-window
state retention. Existing pending-stroke, Utilities, session and viewport
regressions remain part of the suite. Native Maya execution is pending.

Native checks for this entry-point change:

1. In a matching 0.4.1 Maya session, close Layer Skin and run
   `layer_skin_ui_refresh.py` through `runpy.run_path`. One UI 22 editor opens.
2. Hide the editor and run the same command. The replacement is visible with
   its previous mesh/layer/joint and controls; no duplicate editor is created.
3. Paint, then refresh while the window is open. A valid pending stroke saves;
   a rejected save retains the original editor. Undo/Redo still works.
4. A different registered plug-in version or folder reports the mismatch,
   without unloading the command or clearing Undo.

The command/native plug-in, core/schema, brush, Relax, locks, feedback and skin
IO algorithms have no changes in UI 22. Only refresh discovery/entry-point
handling and the authoring title/message change.

---

## Previous UI 21 validation

Date: 2026-10-19. Python 3.12, PySide6 6.8.3, Linux Qt offscreen.

157/157 existing UI and influence checks pass, without skips or failures.
These cover real Qt hierarchy rows, padlock clicks, lock/unlock read-only
painting, pending-stroke saves, per-layer metadata, Undo/Redo, failed-save
rollback, selection retention and safe replacement of an old cached hierarchy.
The UI title check now expects UI 21. No new tests were added for the artwork
change. All 55 Python files compile and parse with Python 3.10 syntax.

Hierarchy row icons prefer :/Lock_ON.png and :/Lock_OFF.png, followed by
:/lockGeneric.png and :/unlockGeneric.png. A rendered 16-pixel pixmap must be
valid before selecting a native resource. No native files are bundled. The
existing drawn fallback remains for off-host Qt/missing resources. Two row
icons are built once per browser, retaining the joint icon and 16-pixel lock
hit area. Native Maya resources and artwork cannot be visually verified here.

The registered plug-in remains 0.4.1. Refresh loads the updated hierarchy
helper while keeping native command registration, existing Undo objects and
saved layer data. The skin IO, memory, core, brush, Relax and influence-lock
algorithms are byte-for-byte unchanged from UI 20. The UI 20 production IO
benchmark and 691-check result below belong to the preceding code revision;
only the relevant 157 checks were rerun for this icon-only revision.

---

## Previous UI 20 validation

# Layer Skin 0.4.1 · Authoring UI 20 validation

Date: 2026-10-19. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen.

**691/691 automated checks pass**, no skips or failures. Nineteen new checks
extend UI 19's 672 checks. All 55 Python files compile and parse with Python
3.10 syntax. Native Maya, VP2 and PySide2 are unavailable.

## Production storage and files

The 2-million-value stops in context loading, core validation, file validation,
projection and binding are replaced by a consistent packed-buffer budget:
1024 MiB per dense float64 buffer (134,217,728 values), with 4096 maximum
influences and a separate 1024 MiB uncompressed archive budget. These are data
budgets, not a promise that total process/Undo RAM stays under 1024 MiB.

Large native/base/composed buffers use array-backed doubles. Large imported
layer rows retain nonzero columns and values; file data stays read-only CSR
through load and Vertex ID planning. Large surface transfers accumulate sparse
source contributions. Normal scalar/row access remains supported. Small scene
lists and old encoded scene data remain readable. Compact layer metadata uses
checksummed compressed f64 blocks and sparse row records inside schema 2; large
scenes saved this way require the updated package. V1 .rtkskin archives retain
their existing typed arrays, little-endian doubles and SHA-256 descriptors.

Archive readers/writers use 1 MiB chunks. Native reads/writes use at most
262144 values per API batch. The file-operation cancellation checker reaches
native reads and is removed/restored after completion/failure. The file
computation deadline is 600 seconds. No progressWindow or new frame callback
is introduced. A failed later native write still triggers transaction rollback.

File/codec tests cover above-limit round trips, sparse ID sharing, sparse
surface interpolation and DQ, metadata persistence, packed composition, scalar
painting, UUID remap, malformed values/checksums/offsets, bounded decompression,
read-only arrays and preservation of an existing file on cancellation. Native
recorders cover bounded reads, ordered chunks, packed Undo/Redo, later-batch
failure restoration and auxiliary DQ/method Undo after helper replacement.
An unskinned target with no matches still yields a manual mapping table.

## Safe refresh and native limits

A warm API check starts with a context that raises the old prototype-limit
warning, installs the refreshed context, and reads a 6000 × 339 fixture through
bounded native API recorders. The RefreshedAPI forwards context/core lookups
to the live owner, and native write helpers are replaced without changing the
registered MPxCommand class or existing Undo objects. IO wrappers remain
idempotent and retain old auxiliary snapshots. UI 20 uses a new helper-cache key.

The API version stays 0.4.1. A fresh Maya session loads the latest doIt body,
which also avoids duplicate full-mesh scratch buffers and scalar Undo-copy
loops. Safe refresh leaves that old virtual executor intact in an already
loaded Maya session; larger buffers can therefore cause higher transient RAM
there, while the new limits, codecs, read helpers and write batching are active.
No plug-in unload, forced unlock or Undo reset is performed.

## Production-shaped CPU test

A 100000-vertex × 339-influence fixture (33.9 million logical values) with four
fixed nonzero weights per row completed export, read, ID planning, layer import,
metadata save/load, full composition and full result verification. See
PRODUCTION_IO_BENCHMARK.json for exact stage times and peak RSS. Its one packed
buffer is 271200000 bytes and measured peak process RSS was about 1.03 GiB.
The repeated coefficients compress particularly well; the archive's size is
not representative of arbitrary production geometry/weights. Native Maya
reads/writes, binding, Undo and viewport/GPU work are excluded.

maya_skin_io_smoke.run_large() provides a real Maya fixture: default 25921
vertices × 128 influences, native export/import, compact saved data and native
Undo/Redo. It creates only a unique temporary namespace, removes its own fixture
by default and does not open a new scene or flush Undo. It has NOT been run.
Production Maya memory peaks, timings and viewport behavior remain unverified.

---

## Previous UI 19 validation

# Layer Skin 0.4.1 · Authoring UI 19 validation

Date: 2026-10-18. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen.

**672/672 tests passed**, without skips or failures. Nine cases were added to
UI 18's 663 checks. Two safe-refresh scenarios also passed after the final
authoring-revision diagnostic change. All 52 Python files compile and parse
with Python 3.10 syntax. Native Maya/VP2/PySide2 remain unavailable.

## Reproductions and corrections

Before the patch, recorded native-adapter cases demonstrated vertices outside
a smaller native screen circle being included by a larger reconstructed world
circle; an interpolated move also queried every stamp's radius at the final
cursor position. Both fail-before/pass-after cases are recorded in the tests.

The adapter now queries screenRadius and worldRadius, clips using the smaller
native/projected radius, and centers the screen clip on each sample cursor.
The world sphere and connected topology restrictions remain. Invalid native
screen queries fall back to the previous projected-world rule. Each interpolated
sample receives native buttonless hover and fresh radii before its raycast.
Fractional Qt coordinates survive conversion into viewport port coordinates.
No solver iterations or write scope are added for hover-only motion.

Boundary cases cover exact edges, smaller/larger native screen bounds, a
stale/reprojected hit center, missing/invalid screen queries, high-DPI coordinate
conversion, shrinking radii without rebuilding the position hash, and weights
and masks over repeated high-pass strokes. End-to-end checks confirm clipped
outside rows remain out of staged payloads, native-command dirty lists and the
resulting composite. Outside one-ring neighbors remain read-only. Existing
lock, paint, selection, color-handoff, Undo/cancel and lifecycle checks pass.

Safe refresh uses UI/session revision 19 and a new authoring-module cache key.
A preloaded UI 18 brush helper is explicitly poisoned in a refresh test to
confirm it is not reused. The registered plugin source, API version 0.4.1,
core/Relax math, native Undo command class and scene schema remain unchanged.

## High-resolution pure brush check

100,000 vertices, 8 influences, 40 stamps, radius 12: 437–452 vertices per stamp,
797 final changed rows and 801 cached neighbor rows. Position hash creation was
0.0504 s, the working-layer snapshot 0.00132 s, all footprint/solver work 0.2253 s
(mean 0.00563 s/stamp), and payload creation 0.00208 s on this host.
These are pure Python measurements. They exclude native geometry extraction,
raycasting, hover/radius queries, color-array upload, skin writes/readback,
metadata encoding and GPU/viewport work. They are not a Maya frame-rate claim.

## Remaining native check

The screenRadius query is interpreted as viewport port pixels; Autodesk names
it the screen-space brush radius but does not detail all renderer/DPI cases.
Matching its actual outline on the user's Maya remains unverified. The
compatibility fallback is also not a guarantee of exact native correspondence.
After refreshing, confirm the UI 19 title, click Paint, make short regular and
Shift Relax strokes on a dense curved mesh, and inspect saved vertex values
outside each brushed footprint. Test 100% and high-DPI display scaling, zoom,
B-radius adjustment, perspective/orthographic views, masks and Undo/Redo.
Paint info reports the native/projected/effective radii, their source and
boundary_revision 19. Per-vertex colors can interpolate over a polygon whose
vertices lie on opposite sides of the circle; those pixels alone do not establish
an outside vertex edit. A stroke retains the union of its brushed locations.

---

## Previous UI 18 validation

# Layer Skin 0.4.1 · Authoring UI 18 validation

Date: 2026-10-18. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen.

**663 tests pass, with no skips or failures**, including 259
Qt-dependent checks (real offscreen widgets and geometry adapters). All 52
Python files compile and parse with Python 3.10 syntax. Maya, native VP2 and
PySide2 execution are unavailable here.

## Layer influence locks and redistribution

Thirty additional checks cover layer contribution budgets, partial
coverage, locked/all-locked/zero-weight cases, Proportional/Equal recipient
sharing, no unrelated influence additions, masks, serialization/remapping,
assignment/clear protection and Relax's per-pass/group/new-influence behavior.
A deterministic 120-case randomized check confirms fixed locked contributions
and nonnegative bounded rows.

Session/command checks cover native-array overshoot clamping without saved-value
verification errors, locked read-only views, prevention of unbound locked-joint
binding, metadata-only toggles, rejected metadata writes and complete native
command Undo/Redo. Earlier command objects retain their class and captured
weights across core replacement. Seven real Qt checks exercise padlock hit
testing, retained joint/vertex selection, active pending-stroke ordering,
read-only/unlocked transitions, Base, rejection and warm-refresh persistence.

The locks apply to displayed layer contributions. Layer coverage, masks, alpha,
other layers and stack operations still affect final skin weights; composition
is unchanged. No native joint-channel or lockInfluenceWeights setting is edited.
Actual Maya/VP2/PySide2 validation remains pending; run INFLUENCE_GUIDE.md's native
check with dense meshes and your viewport display scale.

The UI was rendered and inspected at 1280 and 1040 pixels wide. Gray open and
gold closed padlocks precede the joint icons; the redistribution control fits
above assignment. HIGH_RES_BENCHMARK.txt includes a 250,000-vertex/8-influence
CPU brush with one locked and two unlocked weighted columns. Forty local
stamps changed 786 vertices in 0.261 s for footprint/solver; locked values were
verified in the output payload. Grid construction took 0.133 s. These exclude
native projection/raycast, preview uploads, skin writes, serialization and GPU.

## Full skinCluster hierarchy and removed scope controls

The red-marked root dropdown and Scope to selected joint button are absent.
The dock begins with the joint tree. Nine additional real offscreen Qt tests
cover a tip-only bound influence with its full ancestor chain, multiple
skinCluster roots, unrelated skeleton exclusion, ancestors across transform
buffers, zero-weight/unbound gray rows, UUID-preserving rename and same-path
joint replacement, retained collapsed branches when a new root is added,
scene selection without filtering and warm replacement of an already cached
native tree helper. The former single-root scope test now checks automatic
loading of all roots and removal of the marked controls.

The tree was rendered and inspected at 1280 x 940 with two complete branches.
Actual Maya UI execution remains pending. In Maya, refresh the open window to
UI 17; load a skin with several independent branches, zero-weight influences
and a transform buffer. Confirm all branches display together, selecting a tip
does not crop them, and Refresh retains collapsed branches and selection.
Repeat paint/joint switching, mask view, Undo/Redo, and scene save/reopen.

## Relax brush boundary

Thirteen additional tests cover native world-radius precedence without another
scene-unit conversion, invalid-query fallback, perspective foreground vertices
inside the world sphere but outside the projected circle, physical/high-DPI
port coordinates, subpixel radius handling, exact edge and clipped-vertex
exclusion, and clipping before connectivity. Mesh/hash/projection caches are
reused as the radius changes.

Weight and mask cases run many passes/stamps with a fixed outside one-ring
halo. Moving to a new stamp leaves previously touched rows fixed; only the
union of the actual stamp changes is committed. Real Qt routing verifies the
outline moves before radius sampling, handoffs during the first hover create
no edit, later handoffs finish once, and a moving footprint commits one Undo.
No painted Qt overlay or native context restart is added.

The geometry tests use documented-API-shaped adapters, not Maya or VP2. The
world-radius/projection correspondence to the actual visible native circle
remains an implementation assumption pending the native checks in
RELAX_GUIDE.md. In Maya, compare outside vertex values as well as interpolated
viewport colors, across cm/m/mm scenes, perspective/orthographic views and
high-DPI displays. Existing native command code and schema remain unchanged.

The UI 16 entry in HIGH_RES_BENCHMARK.txt adds a synthetic orthographic clip to
the 250,000-vertex/8-influence brush case. Forty 437–452-vertex stamps took
0.258 s for footprint and solver, plus 0.129 s for the position hash. The
17,896 accepted footprint samples were all inside the world bound. This is a
CPU microbenchmark; it excludes native projection/raycasting, viewport drawing,
preview upload, skin write/readback and metadata costs.

## Explicit falloff and precise Replace defaults

Fifteen new checks cover Solid/full-opacity defaults, explicit native pressure
and accumulation settings, activation preference overrides, all three supported
profile choices, persistence across feedback/joint/repeated-Paint changes,
pending-stroke commits/rejections, callback guards, supplied constant native-array
values surviving save and joint roundtrips, compact UI layout, native-setting
synchronization, warm-refresh preservation and one-time migration from the old
window contract without a falloff field. Seven use real offscreen Qt.

The stored native-array values remain absolute; no falloff is applied again on
commit. Core composition is unchanged. These tests do not sample actual Maya
brush stamps or validate the visible native Gaussian/solid footprint. Run the
Maya check in OPERATIONS_GUIDE.md with Value 0.35, Opacity 1 and Solid, then
compare the soft presets. Existing context-reuse and color-reset regressions
continue to pass.

## Native feedback resets that bypass the Qt gate

Two direct-draw probes failed against UI 13: repeated Paint and a hierarchy
joint change both passed through material/default display states during native
context teardown and feedback disabling. These probes observe API state after
mutations without relying on QWidget.update suppression; they are not VP2
pixel capture. Both pass with UI 14's active-context reuse and enable-only
feedback publication.

Thirteen new real Qt/recording-API checks cover:

- Repeated Paint, unchanged arrays and retained buffer/controller/return tool;
  joint changes show only the complete outgoing or incoming weight values.
- Pending stroke commits once on its outgoing joint, rejected saves retain
  that view, and native-array/feedback failures restore the previous scope and
  array. No display action changes saved authoring data or its Undo snapshots.
- Invalid joints and external skin edits are rejected before replacing live
  view state; readonly final-weight switches retain zero paint opacity.
- Feedback refresh, forced reload and display ramp changes never disable
  native colors. A changed factory or lost object selection still restores a
  valid paint surface through normal activation. Legacy binding repairs retain
  their original activation path.

The existing regressions retain the four operation groups, brush commits,
assignment, Relax, Utilities, save/exit cleanup and warm-refresh behavior. Native
Maya and PySide2 testing remain pending; follow VIEWPORT_FIX.md to check whether
the original visible flash is gone on the user's viewport/backend.

## Four operation groups and matching brushes

Thirty-seven new checks cover:

- Real Qt layout at 1280 and 1040 pixels wide: one row, contained controls,
  parameters above execute buttons and aligned button positions.
- Separate Replace/Add/Scale values, exclusive brush selection, signed Add,
  multipliers above 1, result clamping and unchanged 0–1 display range. Native
  tool activation preferences cannot overwrite the requested operation.
- Selected-vertex and explicit whole-mesh execution on weights/masks,
  contribution/coverage math, preservation of generated rows and lower layers,
  normalized native results, no-op values and invalid-input rejection.
- Native-array absolute results commit once; Add/Scale are not applied again
  during finalization. Mask edits persist across view changes. Binding an
  unweighted joint at zero and authoring its value share one Undo action.
- Pending stroke save before operation changes, rejected-stroke operation/radio
  rollback, Relax execution rejection after a failed pending save, and retained
  per-group values/selection across a warm UI refresh.
- Regular Relax gestures and Shift overrides for Replace/Add/Scale, retained
  B-radius and Escape behavior, and no premature Shift-release finish on a
  regular Relax stroke. Existing layer solver and native outline are reused.
- Native command planner mask Relax, cancellation cleanup, skin/metadata
  rollback, outside-edit/stale-state guards and exact Undo/Redo snapshots.
  Warm planner installation retains the registered class and earlier command
  objects. Continuous color frames survive operation changes and execution.

Autodesk's official artUserPaintCtx reference documents the native operation
and clamp flags used here. The recording adapters do not execute native brush
stamps, pressure or VP2 pixels. Run the Maya verification in OPERATIONS_GUIDE.md;
the local checks do not establish Maya 2024/PySide2 viewport behavior.

## Intermediate material/base-color frames

The new repaint adapter invokes real Qt repaint/event processing after recorded
native color/context operations. Four original handoff cases reproduced an
intermediate material frame under UI 11; the fifth pending-rejection case
already retained its old view. The fix holds updates on existing visible model
view widgets for complete synchronous UI actions, including nested stop/start,
selection refresh and feedback setup, then presents the completed color field.
Existing disabled update states are retained. It does not suspend Maya's global
refresh/evaluation state or introduce an overlay/renderer override.

Nineteen new checks cover:

- Held view → Paint, active joint switches, mask/weight/display changes,
  selected-layer changes, layer edits and Undo without a material frame in
  between. Selection refresh plus a joint change presents only the requested
  joint, not an intervening old/default-joint field.
- Exact retained scene data for display-only actions; unchanged old joint/data
  after a rejected pending stroke; retained held colors after a failed layer
  edit. Explicit Stop still publishes normal material shading.
- Nested holds present once, duplicated widgets are deduplicated, unrelated and
  already-paused widgets retain their state, and every view is restored before
  any final view is drawn. Operation/provider/presenter failures and destroyed
  widgets do not leave enabled panels held.
- Forced brush redraws defer during the action hold and resume afterward. Late
  Maya exit abandons pending widget/redraw callbacks and later abandoned scopes
  do not enumerate or touch native surfaces.

The full previous brush/Relax, native-array, Undo/rollback, session lifecycle,
Utilities, cleanup, hierarchy and warm-refresh suite remains passing. Core
composition, Relax equations, brush solver, held vertex-color renderer, native
plug-in and skin archive format are byte-identical to UI 11. Its working coverage
choice and regular live brush behavior remain; only action handoffs gate forced
brush redraws. Native API stays 0.4.1 and helper aliases use UI 18. No plug-in
unload, Undo reset, automatic unlock or data migration is part of this update.

The Qt frame sampler is a recording adapter, not a Maya renderer. **Native
Maya/VP2 flash removal still needs verification**, especially for native or
external render surfaces, torn-off/multiple panels and high-DPI displays.
VIEWPORT_FIX.md includes the checks and color_handoff diagnostic fields.
Existing real brush/Undo, production mesh, save/reopen and shutdown checks still
apply. No additional native Maya performance claim is made.

## Retained UI 11 validation (historical)

# Layer Skin 0.4.1 · Authoring UI 11 validation

Date: 2026-10-17. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen.

**527 tests pass in 8.115 seconds, with no skips or failures**, including 175
real offscreen Qt checks. All 44 Python files compile and parse with Python
3.10 syntax. There is no native Maya/PySide2/GPU runtime in this environment.

## Missing Shift-smooth color response

A single-joint painted patch reproduced a real no-op: with fixed coverage,
the three-vertex field `[1, 0, 0]` remained unchanged. The same one-ring solve
with coverage smoothing gave `[0.5, 0.25, 0]` over the first two vertices at
strength 0.5. UI 11 makes coverage preservation opt-in in both the brush default
and UI. Updating an older UI adopts the new default once; repeated UI 11
refreshes preserve an explicit checkbox choice. The equations are unchanged.

The previous M3dView.scheduleRefresh path also waited until Maya next became
idle. NativeView now performs synchronous native refreshes from the UI-thread
gesture, throttles immediate drag requests to 30/second and forces the final
saved/restored frame. Idle/native redraws may also occur; this is not a frame
rate guarantee. Reentry and failure guards prevent a stuck redraw state.
The native outline remains separate from the layer solver, with no Qt overlay.

Seven new regression checks cover:

- Default smoothing of a sparse painted patch into a neighboring empty vertex,
  and a single-influence layer whose variation is entirely in coverage.
- Native working-array changes for both the center and neighbor during the
  held gesture, with saved data unchanged before release; one Undo transaction,
  verified commit and the same values after switching joints away and back.
- Immediate refresh without an idle event, throttling, forced final refresh,
  and recovery from recursive/failed native redraw calls.
- The new UI default, one-time migration from UI 10 and retention of a later
  explicit preservation choice without editing scene data.
- Diagnostics that distinguish missing ray hits from a mesh hit with no
  vertices inside the radius. Paint info also reports changed preview counts
  and reasons for unchanged results.

The first five new brush/redraw cases were run against UI 10 before the fix:
all failed or lacked the required immediate-redraw API; existing cases passed.
The previous explicit Preserve coverage, mask, joint-budget, native-array,
regular paint/B-radius, Undo, handoff, Utilities and cleanup checks still pass.
Core composition, Relax equations, held CPV renderer, native command plug-in
and skin archive format are byte-identical to UI 10. The brush default and
feedback controller changed; the registered API remains 0.4.1.

These tests verify actual Qt routing, data calculations and recording API
contracts. **They do not establish live Maya/VP2 pixels or native brush/Undo
behavior.** Verify in Maya on a nonuniform painted boundary with Preserve
coverage off and vertices on both sides inside the brush. Check color changes
before mouse release, switching joints, Undo/Redo, masks and high-resolution
meshes. VIEWPORT_FIX.md and RELAX_GUIDE.md describe those checks and the new
Paint info fields. Uniform fields correctly remain unchanged.

## Retained UI 10 validation (historical)

# Layer Skin 0.4.1 · Authoring UI 10 validation

Date: 2026-10-17. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen.

**520 tests pass in 8.912 seconds, with no skips or failures**, including 170
real offscreen Qt checks. All 44 Python files compile and parse with Python
3.10 syntax. Maya, PySide2 and a native GPU viewport are unavailable here.

## Shift-paint rendering correction

The user's screenshot shows a black viewport and repeated gold circles. The
old Shift controller created a full-viewport translucent QWidget and painted
the same gold circles with QPainter. This identifies a likely Qt/native-viewport
composition conflict. UI 10 removes the painted child and uses the native
Artisan outline, updated by guarded button-free hover events. It never sends
a native press, drag or release. Native redraw is requested after completion,
cancellation/no-hit and warm refresh; renderer/panel settings are not changed.

The new gesture/feedback checks were run against the prior implementation first:
all seven initial cases failed, with the existing sixteen cases still passing.
After the fix, those checks and two additional lifecycle checks pass. Nine new
regressions verify:

- No viewport child widget is created during a long Shift drag; native outline
  remains enabled and the feedback report identifies the native backend.
- Forwarded Qt events carry only MouseMove/NoButton/NoModifier, preserve local
  coordinates and rounded screen coordinates, and do not recursively stamp.
- Native callback reentry cannot open an extra authoring stroke or Undo chunk.
- No-hit release/cancel requests redraw without a weight edit; hover failure
  restores the preview and forwarding guard and permits a subsequent stroke.
- Deleted viewport receivers are ignored, and tool handoff during hover finishes
  once without reentering a cleared viewport or replacing the incoming tool.
- Warm UI refresh closes a legacy overlay, ignores the old cached helper,
  retains data, requests one native redraw and starts the new native-outline
  controller. A rejected pending stroke still retains the old window.

The regular paint, B-radius, Shift solver, mask, Undo, viewport color display,
Utilities and cleanup regressions remain passing. Core composition, Relax math,
brush solver, held CPV renderer, registered plug-in and skin-file format are
byte-identical to UI 9. The registered API remains 0.4.1; UI/session helper
aliases use revision 10. No plug-in unload, command re-registration, attribute
unlock or Undo reset is part of the update.

These local checks do not reproduce Maya/VP2 pixels, native Artisan hover or
GPU driver behavior. **The actual black viewport fix still needs native Maya
verification.** VIEWPORT_FIX.md includes the update command, Paint info fields
and the Windows/Maya 2024 checks for trails, mask/heat-map views, cancellation,
tool/radius changes, high-DPI/torn-off panels and high-resolution meshes.
Existing native brush/Undo, save/reopen and shutdown checks remain required.
The historical CPU benchmarks below retain their original scope and exclusions;
no additional Maya performance claim is made for this correction.

## Retained UI 9 validation (historical)

# Layer Skin 0.4.1 · Authoring UI 9 validation

Date: 2026-10-17. Python 3.12.14, PySide6 6.8.3, Linux Qt offscreen.

**511 tests pass in 8.749 seconds, with no skips or failures**, including 161
real offscreen Qt checks. All 44 Python files compile and parse with Python
3.10 syntax. This is syntax compatibility, not execution in Maya's Python 3.10.
The actual 1100 × 880 Layers/Utilities window was rendered and inspected using
the real hierarchy plus an API adapter. Utilities scrolls its options/mapping
while Preview, Import and status remain visible in a fixed footer.

## Utilities checks

62 new checks cover the following paths:

- 21 pure archive/transfer checks: exact sparse-double file round trips, optional
  geometry/DQ, atomic overwrite/cancellation, dimensions and normalization,
  malformed/checksum/size/version rejection, influence remapping, ambiguous and
  manual mappings, topology guards, barycentric weights/DQ, distance failures,
  unused influences and preservation of existing Base/layers/masks.
- 10 recording-command checks: import through the existing registered class,
  weight/metadata/DQ/method Undo/Redo, settings-only writes, lock/driver rejection,
  rollback after failed native readback, stale/consumed tokens, old Undo objects,
  warm helper refresh and repeat installation. The extension wraps the Python
  planner/write helper; MPxCommand virtual methods and registration stay intact.
- 14 backend checks: read-only Preview, existing and unskinned targets, remapped
  physical columns, missing influence binding, creation switches, state and
  geometry fingerprints, bind-data changes, disabled Undo, guarded import,
  post-commit verification and complete outer-transaction rollback.
- 17 actual Qt checks: a real second tab, lazy backend, pending-paint handoff,
  file caching/change detection/unload, automatic/manual mapping, surface and
  DQ options, cursor cleanup after failure, overwrite cancellation, retained
  refresh fields, scene reset and a fixed Preview/Import footer while scrolling.

All previous Cleanup, command, native-array, paint/session, Shift-Relax,
assignment, hierarchy, viewport and UI-refresh regressions remain passing.
The native plug-in/API version remains 0.4.1 and helper aliases use UI 9.
No plug-in unload, command re-registration, automatic unlock or Undo reset is
part of the update.

IO_BENCHMARK.txt contains one measured CPU-only run of skin_io_benchmark.py:

| Synthetic input | Write | Read | Compressed bytes | Verification |
| --- | ---: | ---: | ---: | --- |
| 100,000 vertices × 16 influences | 0.515432 s | 0.520509 s | 156,809 | Exact regular/DQ values |
| 250,000 vertices × 8 influences | 0.989374 s | 0.968983 s | 377,620 | Exact regular/DQ values |

These repeating synthetic rows have four nonzero weights per vertex; the file
sizes do not predict production compression. Closest-surface transfer from
441 vertices/800 triangles to 10,000 vertices with two influences took 1.101870 s
including BVH build. Maximum analytic linear-field error was 1.11e-16 for both
regular and DQ weights. The 2-million dense-value guard remains enabled. These
measurements exclude Maya API reads/writes, binding, authoring-data encoding,
native Undo, viewport, mesh deformation and scene save/load.

**Maya is unavailable here.** Recording objects do not emulate the DG, actual
skinCluster behavior or native Undo. The supplied maya_skin_io_smoke.py has
been compiled, but not run in Maya. It checks a native file round trip,
weights/DQ/method Undo/Redo and different-topology import with a new skin.
UTILITIES_GUIDE.md gives the command and further manual checks for existing
painted/masked layers, locks/references, renamed joints, stale previews,
save/reopen and production high-resolution meshes. The previous native brush
and shutdown checks also remain required.

## Retained UI 8 validation (historical)

# Layer Skin 0.4.1 · Authoring UI 8 validation

449 tests pass in 5.666 seconds, including 144 real offscreen Qt checks. All
34 Python files compile and parse with Python 3.10 syntax. The actual main
1100 × 850 panel and 650 × 420 Cleanup dialog were rendered and inspected
with the real product hierarchy and an API adapter. No clipping was observed;
the main panel still fits without a vertical scrollbar at that size.

## Cleanup checks

18 recording-command tests verify readonly inspection without decoding payloads
or reading skin weights, explicit mesh/skin ownership, exact attribute signature,
current-mesh scope, shared-skin foreign data retention, native paint-buffer and
artist-network retention, duplicates, unreadable-payload-independent removal,
unskinned recovery with a surviving mesh link, skipped unknown ownership,
protected/customized/driven nodes, stale plans, scene reload with reused names
and UUIDs, disabled Undo, one native delete group, metadata/connection Undo/Redo,
partial-failure rollback and leaving an unrelated prior Undo entry intact.
They also verify post-delete cache warnings, clearing old/shared caches and
pruning invalid buffer references while retaining live Undo arrays.

12 real Qt checks verify the inspector opens without a scene edit, dialog reuse,
cache clearing after a valid pending save, retained displayed colors/data,
pending-stroke commit before metadata-only removal, retained native skin edits,
new Base capture after cleanup, metadata Undo/Redo through the UI adapter,
stale-scope rejection before a stroke is stopped, rejected-paint abort,
protected-node controls, inspection after editor loading fails, removal error
reporting, scene-change closure and fresh inspection after reopening.

The previous command, paint, Shift-Relax, topology, assignment, native-array,
viewport and warm-refresh regressions remain passing. The native registered
MPxCommand class/API remains 0.4.1, and no plug-in unload or Undo reset is used.
Current UI/session helper aliases use UI 8; retained command objects remain live.

Maya is unavailable here. Native commands, dependency-graph deletion, protected
reference behavior, Undo rollback and save/reopen still require the Maya 2024
checklist in CLEANUP_GUIDE.md. Recording objects and Qt adapters do not establish
native graph behavior. The prior CPU solver/brush benchmarks remain valid as
measurements of the unchanged math, with their original Maya/GPU exclusions;
no additional performance claim is made for native cleanup.

## Retained UI 7 validation (historical)

# Layer Skin 0.4.1 · Authoring UI 7 validation

419 tests pass in 4.908 seconds, including 132 real offscreen Qt checks. All
30 Python files compile and parse with Python 3.10 syntax. The actual 1100 ×
850 dialog was rendered and inspected using the product's real joint hierarchy
and an API adapter. Brush passes, Preserve coverage and the new assignment
checkbox fit without clipping or a vertical scrollbar at that size.

## Changes covered

- Shift gesture routing: only viewport Shift-left-drag is consumed. Regular
  strokes pass through; native B-radius events pass through and synchronize
  the field. Local preview does not write skin weights before release. A
  completed stroke saves one command/Undo; no-op strokes save none.
- Escape discards preview, Shift release finishes once, tool handoff retains
  the incoming tool, Ctrl-Z cancels staging before native Undo, callback
  reentry cannot create a second native stroke, and late exit disarms the
  gesture without touching native widgets or the graph.
- Brush math: strength × opacity × smooth radial falloff, scope plus one-ring
  halo reads, connected-island restriction, bounded footprints, sampled input
  spacing, per-stroke new-influence caps, partial coverage, empty regions,
  full-strength coverage preservation, joint-group budgets and mask-only
  smoothing without changing authored joint distributions.
- Native command recordings: sparse Relax sample/mask writes, stale-state and
  invalid-payload rejection, atomic rollback after failed skin writes, and
  metadata/skin Undo/Redo. The API adapter is not a Maya DG emulator.
- Flood → Assign: default replacement of manual overrides only in the chosen
  scope, native candidate-row updates even when generated rows are unchanged,
  preserved masks/input data/outside vertices, opt-in paint preservation,
  Rebuild preservation, and Undo/Redo. Distance falloff still gives partial
  coverage; replacement does not force every generated weight to 1.
- Warm refresh: the old registered planner/core can gain scoped replacement
  and Relax strokes without replacing its MPxCommand class or invalidating
  previous Undo objects. Controls and native B-adjusted radius survive.

A strict OpenMaya adapter checks the documented four-argument viewToWorld ray,
MFloatPoint/MFloatVector intersection arguments, accelerated mesh picking and
high-DPI coordinate conversion. Offscreen Qt cannot validate OS mouse capture,
Maya event dispatch, its DG/Undo queue, Artisan feedback or GPU drawing.
**Maya is unavailable here; no native Shift-brush execution is claimed.**
RELAX_GUIDE.md contains the native manual checklist, equations and behavior.
The high-resolution harness retains native API/Undo/viewport assertions and
interactive instructions, but has not been run in Maya for this update.

## Current CPU measurements

HIGH_RES_BENCHMARK.txt records full results from this environment:

| Case | Solver / footprint time | Other measured costs |
| --- | --- | --- |
| 100,000 vertices × 16 influences, 3 Flood iterations | 1.952 s; 93,985 changed vertices | 0.017 s for 1,000-vertex ROI; 0.017 s palette mapping |
| 250,000 × 8, 3 Flood iterations | 4.950 s; 234,748 changed vertices | 0.025 s for 1,000-vertex ROI; 0.055 s palette mapping |
| 250,000 × 8 backing mesh, 40 local brush stamps | 0.289 s total, mean 0.00723 s/stamp | 0.136 s position grid; 0.00292 s sample-map snapshot; 0.00254 s final payload |

The brush footprints contained 437–452 vertices and changed 798 distinct
vertices, with 801 neighbor rows cached. These are numerical CPU checks,
excluding native geometry extraction/raycasting, full preview-array uploads,
skin writes/readback, metadata serialization and viewport/GPU work. They are
not Maya frame-rate measurements. The two-million dense-value guard remains.
The local solver now reads scoped rows and their immediate halo, while final
metadata copying/validation/serialization and native preview upload may still
involve the loaded mesh. Whole-mesh memory remains a prototype limitation.

## Retained UI 6 validation (historical)

# Layer Skin 0.4.1 · Authoring UI 6 validation

378 tests pass in 3.695 seconds, including 112 real Qt interaction checks. All
26 Python files compile and parse using Python 3.10 syntax. The actual 1100 ×
850 dialog was inspected offscreen with the real product hierarchy and an API
adapter. The persistent-color note and Relax group fit without clipping.

New coverage verifies tool cleanup saves pending strokes synchronously once,
releases the native working array, preserves displayed scalar values and does
not switch the incoming Select tool. Joint/layer/mask changes update the held
view without changing vertex/edge selection. Relax updates colors, resumes only
a previously active brush, and keeps component mode and selected vertices when
called from Select. Failure retains the preview. Stop, close and scene changes
clear the view; Undo/Redo keeps it current. Save/export hooks remove transient
colors before file IO and restore the view afterward.

A recording OpenMaya adapter checks API signatures, one bulk upload (including
50,000 vertices), bounded native palette, unchanged-upload reuse, preserving
selection/tool/mode/skin data and artist color sets, restoring display flags and
private history, preserving the original modified flag, rollback after a failed
upload or locked display setting, topology rejection, non-finite rejection, and
avoiding dead-node API calls on teardown. This adapter does not emulate Maya's
DG, native Undo implementation or viewport. These assertions require the native
smoke test too; no Maya/GPU result is claimed here.

`HIGH_RES_BENCHMARK.txt` contains completed pure Python tests at 100,000 × 16
and 250,000 × 8 vertex/influence values. Three iterations: 2.079 s / 5.264 s for
the solver; 0.025 s / 0.047 s for palette mapping. The solves changed 93,985 and
234,748 rows respectively and validated normalized state. A 1,000-vertex ROI
also ran for each case. This excludes Maya, CPV upload, skin writes, encoding and
viewport costs. The 2,000,000 dense-value limit remains.

`layer_skin_highres_test.py` includes a native Maya harness (not run here) with
~100k and 250k demo sizes, real authoring writes, persistent color checks,
component/edge Relax, native Undo/Redo assertions, temporary color/history
cleanup, brush reactivation and forced viewport-refresh timings. It creates
only its own namespace, keeps the demo by default and never clears the scene or
Undo. Interactive mouse painting and visual feedback must be checked in Maya.
See README for the exact commands and limitations.

## Retained UI 5 validation (historical)

# Layer Skin 0.4.1 · Authoring UI 5 validation

UI 5: 354 local tests pass, including 105 real Qt interaction checks. Added tests
cover one-ring fixed-boundary smoothing, Jacobi updates, convergence/zero-strength
no-ops, single-joint unrestricted behavior, two/three-joint contribution budgets,
zero-budget retention, new-influence caps across all iterations, stable UUID ties,
partial coverage, independent masks/generated rows, isolated vertices, invalid
options/topology and cancellation without mutating the input. Scope checks
distinguish no vertices (whole mesh) from foreign/edge components (rejection).

Command tests verify a single native commit, sparse changed-row writes,
metadata/skin Undo/Redo, rollback on skin write failure, ending computation on
cancel, empty-layer no-op, and the existing external-skin-edit guard. A simulated
pre-UI5 planner gains Relax without replacing its command class or invalidating
previous Undo commands; repeated installation does not stack wrappers.

Display tests verify scalar weights/Undo remain unchanged, native colorRamp
flags with a fixed 0–1 range, grayscale masks, restoring the chosen weight ramp,
and exactly one pending-stroke save before a display switch. Qt checks cover
Relax settings, selected/whole scope, joint subset, Base rejection and retention
of ramp/Relax controls across refresh. All 23 Python files compile and parse with
Python 3.10 syntax. The actual 1100px UI was inspected offscreen with the real
hierarchy widget and an API adapter; the ramp legend and Relax group fit.

RELAX_BENCHMARK.txt records a pure-Python 20,000-vertex, 20-influence, 5-iteration
run: 0.361817 seconds for the whole mesh (190 changed rows), 0.029533 seconds for
100 selected vertices (10 changed rows). These timings exclude Maya API calls,
viewport, native skin writes and metadata encoding. Adjacency fixtures separately
verify lazy reuse, topology invalidation and cache budget behavior.

Native Maya execution is not available here. In Maya 2024, refresh to UI 5 and:

1. Paint/select a weighted layer, toggle Heat map/Grayscale and switch joints.
   Verify 0/0.5/1 appear blue/green/red and masks stay grayscale. Open Paint info
   to check authoring_revision, effective_display, useColorRamp and colorRamp.
2. Select vertices and Flood relax with 3 iterations / strength 0.5. Verify only
   those vertices change; clear vertex selection and repeat for the whole mesh.
3. Select one hierarchy joint: all neighboring influences may participate.
   Select two or three: other contributions and the group's total stay fixed.
   Check a zero group remains zero and Max new limits additions across iterations.
4. Undo/Redo, change layer, repaint mask and rebuild assignment. Check Relax
   overrides persist, masks remain unchanged and native normalized rows agree.
5. Cancel a large operation and test a locked influence. Confirm the native
   guard rejects incompatible writes with metadata/skin rollback. No progress
   window, plug-in unload or Undo reset is used by the new workflow.

Previous UI 4 validation follows for historical context; its regressions remain
in the current suite:

UI 4: 321 local tests pass, including 101 real Qt interaction checks. New/updated
checks cover unbounded positive-axis assignment, full coverage, skipped child
claims, strict zero boundary, all signed axes, rotated/transformed/sheared and
mirrored/scaled frames, rejection of singular frames, cancellation without a
partial result, cache reuse despite ignored radius/length/falloff, deepest-path
ordering independent of selection order, selected-vertex scope, generated-row
write/Undo/Redo and repeat no-op behavior. Axis rebuild preserves paint/masks.

The refresh installs new assignment/session code without reloading the native
command. Cached/shared references to the old assignment module receive the new
transient cache; saved layer metadata and native Undo objects are retained. Qt
checks verify ignored controls and Length removal, refreshed caches, continued
painting, repeated refresh, and preservation of unrelated cache entries. All
21 Python files compile and parse using Python 3.10 syntax.
The 1100px offscreen panel was inspected with the real hierarchy widget and an
API adapter. Radius/Falloff are disabled for Joint axis and Length is absent;
the reference status reserves four text lines to avoid clipping in the dock.

AXIS_ASSIGNMENT_BENCHMARK.txt records a separate local run: 20,000 vertices,
20 selected joints, 19,047 generated rows; 219,057 plane tests instead of
400,000 full pairs. First assignment took 0.072084 s; the cached repeat took
0.005902 s and performed zero additional plane tests. This excludes Maya API,
viewport, skin writes, metadata encoding and native Undo costs. Worst-case
unclaimed vertices still require O(vertices × joints) tests.

Native Maya UI/painting has not been executed here. In Maya, refresh to UI 4,
select a chain in any order, set Joint axis +X, and assign in a scoped region.
Check distal vertices stay with the child and more proximal ones reach parents;
check a far-sideways vertex still qualifies solely by its local-axis sign.
Repeat/Undo/Redo, mirror/scale the reference frame, and test Rebuild after paint
and a mask edit. Use Recapture reference if the intended reference pose changes.

The previous UI 3 validation and handoff regression checks remain applicable:

UI 3: 310 local tests pass, including 100 real Qt interaction checks. The
handoff tests cover synchronous sample/array commit before native setup,
exactly one stroke commit, closed Undo group, released array ownership, rejected
and read-only cleanup, inert late callbacks, ToolChanged fallback, no brush
takeover on joint selection, native-edit detection before accepting new paint,
and resuming after undoing the native edit. No real Maya runtime is emulated.

The refreshed API forwards live state rather than copying a stale snapshot.
Refresh checks verify pending-mask commit, retained mesh/layer/joint and brush
controls, the new Session implementation, preserved native buffer factory,
replacement of only the owner's UI/session caches, unrelated-cache retention,
repeated refresh, subsequent paint persistence, and preserving the original
window when a pending save fails. The registered command, skin readback guard,
core composition and geometry binding are unchanged. No plug-in unload,
registration, influence unlock, normalization change or Undo reset is used.
There is one additional ToolChanged event listener, removed with all others.
All 21 Python files compile and parse with Python 3.10 syntax.

Show mask remains removed, Mask → Paint displays its saved data, and Fill mask
keeps the numeric-fill behavior. UI 2's panel was inspected offscreen with the
real hierarchy and an API test adapter; UI 3 changes its title and handoff logic.
Native Maya painting/UI execution for UI 3 has not been run in this environment.

## Maya handoff validation to run

1. With the 0.4.1 window open, run the updated layer_skin_ui_refresh.py from this
   complete folder. Confirm the title ends in UI 4. Do not unload the plug-in.
2. Paint weights, then immediately open Maya Paint Skin Weights. Repeat for a
   painted mask. Verify the outgoing layer stroke is saved, our brush pauses,
   and Maya's brush stays active when a joint is chosen in our hierarchy.
3. Return with our Paint button before making native strokes: saved layer values
   must reload. Paint info should show a saved stroke and tool_change reason if
   the handoff had a pending stroke.
4. Make a native stroke. Our Paint button must explain that native skin weights
   changed, keep layer metadata, and leave the native brush selected. Undo the
   native stroke and return to our brush; layer painting must work again. The
   next Undo must undo the outgoing layer stroke separately.
5. Repeat with Show final skin weights and Stop / shaded view. Confirm no scene
   color sets, influence locks or normalization settings were changed by Layer
   Skin. If a write is still rejected, retain Paint info including skin_settings
   and last_stroke; the original readback verification remains enabled.

Previous native debugging evidence follows.

Date: 2026-10-16. Local environment: Python 3.12.14, PySide6 6.8.3,
Linux, Qt offscreen platform. No Maya installation or Maya SDK runtime.

## Evidence from the supplied Maya 2024 trace

The uploaded debug report was captured with Python 3.10.8 and Layer Skin 0.3.9.
It shows 28 accepted scalar samples, a verified save, and four nonzero authored
vertices on the original joint. After switching away and back, saved and loaded
values have the identical digest and maximum 0.988858. Decoded metadata matches
the actual scene attribute, and native skin weights match the saved composite.
No callback or scene-read errors were reported. The user still reported a black
viewport. These observations narrow this reproduction to native display feedback.
They do not establish that every prior capture/save problem had the same cause.

## Evidence from the 0.4.0 Paint info

The user's next report showed an active userPaint context, no callback error,
382 loaded values, four array-binding callbacks and 13 array reads/finalizations.
Every reported stroke was unchanged and paintNodeArray was empty; the mesh
remained shaded despite the visible brush. Source inspection showed the array
host had no geometry input. The missing host-to-surface association is consistent
with a first-hand developer reproduction resolved by a generic geometry input.
Empty paintNodeArray alone is not used as proof that binding failed.

## Changes in 0.4.1

The native array host now has a generic `surface` attribute accepting mesh data.
The mesh's outMesh connects to it before context activation. The host never
drives mesh geometry. Buffers are cached per mesh UUID, preserving independent
arrays/Undo references across meshes with different vertex counts. Reuse verifies
and repairs the owned incoming geometry link. Paint info exposes the source plug.
The Python API 2.0 method is MFnGenericAttribute.addDataType, confirmed against
Maya 2024 documentation; it differs from older C++ API examples.

The included live repair redirects only a running 0.4.0 buffer factory and
refreshes its active view, while keeping the registered command and Undo history.
Recording tests with real Qt verify scope preservation, no authoring changes,
pending-save ordering, repeat repair and factory rollback after activation errors.

## Retained native-array backend

The context now registers `getArrayAttrCommand` and clears its scalar
initialize/finalize/get/set registrations. Autodesk documents that the array
callback overrides those four scalar callbacks. Before/after-stroke hooks still
collect and commit native array changes. A complete array is loaded before tool
activation and for each selected joint/mask/final-skin view.

One transient built-in network node per mesh holds its doubleArray and receives
the mesh geometry through its generic surface input. Its
`doNotWrite` flag excludes it from scene files. It remains alive after UI close
because native paint Undo commands can retain its object. The handle is checked
before reuse, and scene replacement creates a new buffer as needed. It has no
per-frame callbacks, new skinClusters or joint attribute locks. Authoring data
continues to use the existing schema and layer command.

Nested Undo chunks include native array edits, new influence binding and the
layer command. Failed binding rolls back only the owned transaction. Display
writes are guarded against reentrant stroke events. Read-only views use zero
opacity and do not submit authoring commands. Pending samples are scoped to the
original view; another session must flush an inactive pending stroke before
claiming the shared array.

## Completed locally

**299 tests passed with no skips or failures. All 20 Python sources compile.**
The included LOCAL_TEST_RESULTS.txt is the full recording/API and real Qt log.
The archive is checked for CRC errors and its source files compiled directly.

| Module | Coverage |
| --- | --- |
| test_layer_skin.py | Composition, persistence, validation, loader fallbacks, transaction ordering and rollback. |
| test_layer_skin_assignment.py | Cached assignment, generated/manual regions, coverage, remapping, schema migration and authored-weight summaries. |
| test_layer_skin_command.py | Recording native-weight transactions, membership, vertex scope, locking/reference checks and failure recovery. |
| test_layer_skin_session.py | Native array configuration, legacy scalar bridge, save guards, first-stroke binding, selection, view and callback lifecycle. |
| test_layer_skin_launch.py | Exact path/version checks, duplicate installations, incomplete folders and command-registration failures. |
| test_layer_skin_ui.py | Actual offscreen hierarchy clicks, per-joint array round trips, array release timer, masks, final weights, dock and teardown. |
| test_layer_skin_binding_fix.py | Repair of 0.4.0 without command reload; repeat use; rejected versions; pending-save scope and rollback. |
| test_layer_skin_native_array.py | Array-only painting without scalar setters; joint/mask round trips; missing end hooks; nested native-array/binding/layer Undo; stale owners; invalid data; guarded feedback reentry; safe buffer reuse, geometry connection, separate mesh arrays, UUID-preserving rename and creation failure. |

The new array-only tests never call Session.set_value. Their adapter models an
undoable native working-array write inside the stroke, independent of the layer
command, so one Undo can be checked against both buffers. Actual Qt checks paint
only the working array, wait with the mouse held, release, and confirm the timer
commits once. A real joint-tree click round trip restores the entire native-array
input, not just the session's scalar getter.

These tests do not emulate Maya's dependency graph or render VP2 feedback. They
do not establish real brush Undo ordering or whether the geometry-linked array repairs
the reported nonpaintable viewport. The supplied native run_array_feedback geometry check and
manual mouse-stroke checks have not been executed here. No Maya runtime is
installed in this environment. The composition, assignment and joint-tree
modules are byte-identical to 0.3.9.

## Historical bounded-axis performance check from the uploaded update

The assignment timings below were included with your uploaded optimization
update. They describe the earlier bounded axis algorithm, not UI 4's positive
half-space method. Use AXIS_ASSIGNMENT_BENCHMARK.txt for the current axis path.
Capturing descendant frames is Maya-side work outside these Python timings.

The internal pure-Python benchmark used a 20,000-vertex synthetic point set,
one axis-assignment joint and two influence columns. Its log is included as
`ASSIGNMENT_BENCHMARK.txt`.

| Measurement | Baseline (0.3.1) | Optimized |
| --- | ---: | ---: |
| Generated samples | 12,080 | 12,080 |
| First assignment | 0.136 seconds | 0.054 seconds |
| Cached identical assignment | 0.014 seconds | 0.010 seconds |
| Vertex-distance tests, before/after cached repeat | 16,200 / 16,200 | 15,100 / 15,100 |
| One-row composition | 0.000017 seconds | 0.000015 seconds |
| Estimated retained assignment-cache bytes | 12,614,400 | 12,614,400 |

The repeated request performed no additional distance tests. Results depend on
hardware and input geometry. This measures the pure assignment/composition code;
it excludes Maya skin reads/writes, JSON scene attributes, the viewport, native
Undo and playback. It does not establish production rig performance or total
Maya memory usage.

## Native Maya checks — supplied, not run

Load `layer_skin_test.py` and import `maya_layer_skin_demo` as described in
README.md. Run these separately on a test scene:

0. `run_array_feedback()`: real native doubleArray plug readback, grouped
   setAttr/layer Undo and Redo, complete joint/mask array reloads, single working
   node reuse and read-only opacity. It simulates a native stamp with setAttr;
   real Artisan mouse-stroke Undo and viewport pixels are separate checks.

1. `run_smoke()`: native skin weights, selected edits, masks, reorder, serialization,
   external-edit protection, bake/restore and native Undo/Redo.
2. `run_authoring()`: automatic Base capture, selected-joint generation without
   membership setup, cached generation, frozen unbound descendants, direct first
   stroke binding/membership and grouped Undo/Redo, actual MEL scalar callbacks,
   paint preservation, repeated mask/joint view reloads and save-receipt retention,
   userPaint/Gaussian/feedback settings, a Maintain Max
   Influences rejection followed by a successful stroke without reactivation,
   repeated initialization, release-hook commit/readback, and read-only actual
   skin weights. This invokes callbacks directly; it does not test actual mouse
   strokes, cursor appearance or mesh shading.
3. `run_capture_recovery()`: deliberately omits initialization and completion
   callbacks, saves pending native weights/masks on a view change, returns to the
   original joint, and checks native readback plus Undo/Redo. It does not exercise
   actual mouse delivery or the Qt timer.
4. `run_ui_lifecycle()`: close the existing Layer Skin window first. Checks three
   open/close cycles, selection follow, Base, visible nested scene joint rows, right
   docking, one joint selector, weight-status updates, unchanged scene Outliner
   colors, active mask-view Undo/Redo, browser deletion and callback removal.

Each check owns its temporary namespace and restores the previous selection.
They do not create a new scene or save a file. They require native Maya Undo.
Avoid overlapping a manual brush session with automated authoring tests.

## Manual Maya checks still required

- Reproduce the supplied 8-vertex cube case: paint the first joint, select the
  second, then return to the first. Confirm the old patch is visible immediately,
  and the Values range still includes the saved maximum. Repeat with Mask and
  final-skin views, mouse drag strokes and a tablet if used.
- On a real brush stroke, confirm one Undo restores the layer AND skin weights,
  then one Redo restores both. Repeat after binding a previously unbound joint,
  switching joints and closing/reopening the window.
- Save/reopen a test scene and confirm authored layers persist while the
  rtkLayerSkinPaintBuffer network nodes are omitted from the saved file. Do not
  delete its live node while native paint Undo entries may refer to it.

- Select a skinned mesh, click + and confirm Base creation and one-step Undo.
  Selecting joints must retain the mesh; Pin must block another mesh pick.
- Load all skin influence hierarchies. Verify selection and expansion,
  with no rename, delete, middle-drag reparent or context-menu scene edits.
- Confirm that only one joint selector appears in the right dock. Drag its
  divider, float/redock it, and select gray joints to add/paint. Check names with
  namespaces and duplicated short names under different parents. Empty members
  should stay gray; painted/generated nonzero rows should regain normal color.
- Select an unused bound joint and paint without an add step. Choose an unbound
  descendant; activating/abandoning the brush must leave skin membership intact.
  Commit a changed stroke and verify binding, membership and weights undo/redo
  together while the scene joint remains. Force an actual Maya failure and check
  rollback. Painting on locked/referenced/held data must still be rejected.
- Switch hierarchy joints while weight painting; the brush must continue on
  the new joint. Choosing joints during mask painting must keep the mask active.
- Select multiple hierarchy joints, choose each assignment method and test whole
  mesh/selected-vertex scopes. Confirm only chosen joints generate samples,
  painted edits/masks survive, and Rebuild layer uses all layer members.
- Paint actual strokes on the visible mesh; release commits one Undo. Check
  **Stroke saved**, `last_stroke.layer_values_verified`, retained joint/layer
  selection, and persistence of several consecutive strokes. On a disposable
  test skin, enable Maintain Max Influences, trigger a rejection, turn it off
  manually and paint again without reopening Paint; the next stroke must save.
  Confirm that saved data and viewport values agree after release and Undo/Redo. Stop a
  stroke before release using explicit discard/Undo and verify no deferred write.
  Switch joints immediately after painting, before waiting for native callbacks;
  return and verify the values remain. Check Paint info's accepted-sample counts
  and commit reason. Hold the brush and verify the release fallback does not
  write until release. Stop/shaded view must save pending edits once. Test
  weight Value 0/0.4/1.
- Paint a nonuniform mask (for example 0.25 and 1), Stop and reopen Mask → Paint,
  and verify the same grayscale pattern and loaded range return. Paint a joint,
  choose another joint and return; the original joint values must return. Switch
  through mask/final-skin/Paint views, close/reopen the UI and reopen a saved
  test scene. Compare Paint info's current display values with saved layer data.
- Paint/view masks, including Base's white mask; verify grayscale feedback,
  restoration of shaded view and unchanged materials/color sets.
- Enter Paint from selected vertices, a joint selection and object selection.
  Confirm Paint info shows the intended context/surface. Switch to Maya's 3D
  Paint Tool, then use this window's Paint button to reactivate Layer Skin.
  Verify no texture or UV assignment is needed for this per-vertex mask.
- Verify the native brush circle appears and the mesh actually draws grayscale
  values. In an empty layer, confirm authored values display zero. Show final
  skin weights must instead match the selected joint's actual skinCluster rows,
  follow joint changes and remain read-only. Check Base preview without adding
  a layer, return to Paint, and restoration of shaded view on Stop/tool switch.
- Assign using bone, pivot and +/- axis methods on whole/selected scope. Rotate
  the character, rebuild and confirm the frozen snapshot is used. Recapture must
  be explicit and rebuild must retain paint and masks.
- Save a separate test scene, reopen it, load the plug-in and select the mesh.
  Confirm layers, memberships, references and final skin weights persist.
- Bake/detach and confirm the character deforms with native skinCluster weights.
  Restore original must restore Base without changing joint transforms.
- Close/reopen the dialog repeatedly, change scenes, switch tools and exit Maya
  with the dialog/paint context active. Confirm there are no stale callbacks,
  native UI leaks or exit crashes.

Until these native checks run, this release remains an integration prototype.
