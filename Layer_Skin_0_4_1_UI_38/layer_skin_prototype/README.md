# Layer Skin 0.4.1 — Authoring UI 38

## New in UI 38: selective merge of the three-file proposal

Wide production skins can store new sparse manual paint rows compactly and
share one-hot distributions. Sparse composition uses nonzero entries, with
bounded packed-row reuse inside one operation; the memo disables itself when
rows show little sharing. Validation and JSON row reuse are local to each call,
so later edits to manual samples are checked again.

Larger scattered vertex selections use bounded NumPy gathers, while small
scopes retain direct row checks. The proposed first-row memory estimate and
persistent sample-validation cache are excluded. Paint/Relax receipts remain
unchanged: adding more action names alone would not speed up the current UI.

**978/978 automated checks pass.** See
[PROPOSAL_REVIEW_UI38.md](PROPOSAL_REVIEW_UI38.md) for the three-file review,
accepted changes, excluded issues and remaining Maya checks. CPU measurements
are in `SPARSE_EDITS_BENCHMARK.json`. Replace the complete folder, run
`layer_skin_ui_refresh.py` as `__main__`, and confirm **UI 38**. Plug-in version
remains **0.4.1**; previous viewport, NumPy installer and Relax improvements stay.

## Retained UI 37 feature: painting latency

Shift/Relax reads positions around the connected brush footprint instead of
building a whole-mesh spatial grid at each press. Every solver stamp is retained;
full preview uploads and feedback reloads are coalesced to 30 per second, with
the latest values published when the cursor stops or on release. Cancellation restores the
baseline and clears the pending preview.

Relax release now reuses its exact verified command result for the session and
queued UI refresh. Canonical state-hash and expected-composite caches avoid
repeated startup serialization/composition. Contiguous dirty-row checks use
bounded optional NumPy blocks. Full live skin validation, write verification,
transactional metadata save and native Undo/Redo remain enabled.

Replace the complete folder, run `layer_skin_ui_refresh.py` as `__main__`, and
confirm **UI 37**. The registered plug-in stays **0.4.1**. UI 36's NumPy installer
and UI 35's viewport constructor fix remain available. **957/957 automated checks
pass.** See [PAINT_PERFORMANCE_UI37.md](PAINT_PERFORMANCE_UI37.md) for measured
CPU phases, retained release costs and native Maya checks. Full Maya painting
and release timings have not been measured on this host.

## Retained UI 36 feature: optional NumPy installation

Open **Utilities → Performance** to check the active NumPy backend. If it is
unavailable, **Install NumPy** runs matching Maya `mayapy` processes in the
background, using a separate user package folder. A compatible binary wheel is
verified before activation. **Recheck NumPy** retries a previously failed import;
installation also performs this recheck automatically.

Existing NumPy is reused. The installer downloads pinned NumPy 1.26.4 for Python
3.9–3.12, with no source build or other package upgrades. Progress, install
details and Cancel are available. Failed or canceled attempts are not activated.
If a verified installation cannot load in the running Maya process, the status
explains the error and requests a restart. The ordinary comparison stays usable.

Replace the complete folder, run `layer_skin_ui_refresh.py` as `__main__`, and
confirm **UI 36**. If replacing the contents of your existing UI 34 folder, its
folder name and existing launch path can stay the same. See
[NUMPY_INSTALL_UI36.md](NUMPY_INSTALL_UI36.md) for usage and supported environments;
[VALIDATION.md](VALIDATION.md) records the 936-check suite and installation test.
The registered plug-in remains **0.4.1**, and UI 35's viewport fix is retained.

## Retained UI 35 feature: Select vertices HUD constructor fix

The passive preview now calls `MHUDRender()` without an operation name. The
previous named call could raise `MHUDRender : no matching constructor found`
before the selection heat map appeared. If the default HUD constructor itself
raises TypeError, only that optional pass is omitted; the scene heat map and
present pass remain. Paint info reports whether the HUD is enabled and any
constructor error. In that fallback, the standard HUD may be absent until Paint
or Stop restores the regular renderer.

Both viewport helper cache keys are updated so a warm refresh loads the fixed
renderer. The native smoke check now checks the renderer revision instead of
requiring the old UI 33 title. No color sets, history or scene nodes are added.

Replace the complete folder, run `layer_skin_ui_refresh.py`, and confirm **UI 35**.
The registered plug-in remains **0.4.1**. See
[HUD_CONSTRUCTOR_UI35.md](HUD_CONSTRUCTOR_UI35.md) for the cause, fallback,
reload command and native checks. [VALIDATION.md](VALIDATION.md) records results.

## Retained UI 34 feature: faster layer revisits and selected Relax preparation

Switching back to an unchanged layer or Base reuses its weighted-joint summary.
Each live layer has one cached summary; painting, assignment, a new base,
influence changes and mesh changes invalidate the affected data. Old snapshots
and deleted layers are released. Clear memory caches also clears the summaries.

Selected Relax no longer recounts every cached topology row after a whole-mesh
operation. New neighbor rows update the memory estimate incrementally. Valid
neighbor reads survive cancellation for the next action; cancellation still
raises and the operation does not author weights. Existing cache budgets remain.

The CPU phase fixtures measured 383.994 → 0.011 ms for revisiting three summaries
at 200k vertices / 16 influences, and 6.072 → 0.007 ms for a 64-vertex topology
lookup after caching 100k vertices. These exclude native skin/command/viewport
work and are not complete layer-switch or Relax timings.

Replace the complete folder, run `layer_skin_ui_refresh.py`, and confirm **UI 34**.
The registered plug-in remains **0.4.1**. Existing weight validation, painting,
Undo/Redo and viewport behavior are retained. See
[WORKFLOW_REFRESH_UI34.md](WORKFLOW_REFRESH_UI34.md) for scope, benchmarks and
Maya checks; [VALIDATION.md](VALIDATION.md) records the automated results.

## Retained UI 33 feature: vertex selection with a node-free heat map

**Select vertices** now shows the current weight/mask colors after the incoming
tool and component setup, including repeated Select clicks. **Q** retains the
view; **Y / Paint** returns to Artisan. The Paint/Select buttons show the active
mode. Stop, close and returning to Paint cancel any delayed passive preview.

The passive view now uses a Viewport 2.0 draw pass. It creates **no color sets,
CPV history or scene nodes**, and does not edit artist mesh colors, shaders or
display plugs. Positions/triangles are cached across clean redraws and updated
after deformation. Selection/picking remains native. The renderer detaches on
Paint, Stop, close and before file IO; other custom viewport renderers are kept.

An existing native paint-buffer node can remain for Artisan Undo and is reused.
The selection preview does not create another one. See
[VERTEX_SELECTION_UI33.md](VERTEX_SELECTION_UI33.md) for the flow, Node Editor
explanation, renderer limits, reload and an included native smoke-check script.
**886/886 automated checks pass.** Native Maya/VP2/GPU verification remains pending on this host.

Replace the complete folder, run `layer_skin_ui_refresh.py`, and confirm **UI 33**.
The registered plug-in remains **0.4.1**, with existing Undo objects preserved.

## Retained UI 32 feature: faster brush-release guards and persistence

Staged painting now encodes the changed layer state once instead of encoding it
again for its stale-state guard. Exact scene bytes, ordered influence UUIDs and
the current encoder key the bounded guard cache; legacy compression and remapped
influences remain supported.

Compression uses level 1 for the state and packed base. Immutable packed bases
reuse validation and their bounded encoded payload. The existing 64 MiB decoded/
composite cache now accounts for packed buffers correctly; the separate encoded-
base cache is limited to 16 MiB and releases entries with their base. NumPy,
when available, accelerates full tolerance comparisons without changing the
absolute tolerance. Standard-library fallback remains available.

Small strokes inspect weight locks/drivers in changed rows rather than scanning
every allocated weightList row. Parent, row, array, leaf and unevaluated connected
leaf checks remain. **Full live skin reads and external-edit detection remain**,
including changes outside the painted area. Undo/Redo, write verification,
rollback, F9/Q/Y, radius changes and UI 31 receipts are retained.

In the CPU 200k-vertex/16-influence fixture, near-equal comparison fell from
186.805 to 2.889 ms and one state encode from 715.721 to 290.155 ms; encoding now
runs once per staged command. These are phase measurements outside Maya, not a
complete stroke-release benchmark or a 90% performance guarantee. Encoded data
was about 4.6% larger. Native Maya/VP2/PySide2 verification remains pending.

**870/870 checks passed for UI 32**, including 34 performance and safety checks.

Replace the complete folder, run `layer_skin_ui_refresh.py`, and confirm **UI 33**.
The registered plug-in stays **0.4.1**. Read
[FEEDBACK_REVIEW_UI32.md](FEEDBACK_REVIEW_UI32.md) for implementation details,
bounded-cache behavior, benchmark limits, reload code and Maya checks.


## Retained UI 31 feature: surface binding, preview reuse and verified paint receipts

**F9 / right-click Vertex** retains both the component selection and the loaded
object-level Artisan surface binding, then restores native feedback once for
the coalesced mode change. **Q** selects with colors retained; **Y** returns to
Paint. Existing selected components remain when the object binding is added.

For already-bound painting, a verified result from the exact successful command
updates only changed displayed values. Finalize and its queued UI refresh reuse
that result, avoiding their duplicate full skin snapshots, encodes and array
uploads. The original command's native validation, persistence, locks, write
verification and Undo remain. New influences and unavailable/mismatched receipts
use the normal verified preparation path. This does not remove all whole-mesh
work from a stroke.

UI 31 used an owned temporary color-set/history preview for colored selection.
**UI 33 replaces that backend with the viewport draw pass described above.**
Exact-command receipts, surface binding, artist-data preservation and the guard
against taking the newest shared-cache entry are retained.

**836/836 checks passed for UI 31**, including seventeen new checks and a 250,000-
vertex / eight-influence fixture for the delta-only post-command display path.
Native Maya/VP2/PySide2 verification remains pending. See
[FEEDBACK_REVIEW_UI31.md](FEEDBACK_REVIEW_UI31.md) for the feedback assessment,
remaining costs, reload command and Maya checklist.

Replace the complete folder, run `layer_skin_ui_refresh.py` and confirm **UI 33**.
The registered plug-in remains **0.4.1**, and existing Undo objects are preserved.


## Retained UI 30 feature: brush shortcuts, cached startup and component painting

**B + drag** now arms the radius guard at Qt's **ShortcutOverride** event, before
Maya can consume B as a hotkey. A keypress is also supported. Settings sync waits
until both B and the sizing mouse button are released; it does not query Artisan
or update spinboxes on each sizing frame. Shortcut events sent to the main
window use its focused viewport, while text fields retain their own shortcuts.

Known full, short and namespaced surface/transform names use cached lookups.
A ready native stroke reuses its staged layer values and canonical state hash,
without rereading skin weights, uploading the array or compressing the stack.
Undo/Redo invalidate that data. Commit validation and real stroke readback remain.
Readonly display changes do not encode a new stack just to view its weights.

**F9 / right-click Vertex** now keeps the brush in component mode and highlights
the loaded mesh. Starting Paint and switching joints keep existing vertex/edge
selections. Selected vertices, or selected edge endpoints, limit saved native
painting and Shift-Relax; with no components selected, the brush is unrestricted.

Use **Q** or **Select vertices** to select components with weight colors retained.
**Y** returns to the armed brush with its values, radius, opacity and component
selection. The re-entry checks that Maya still requests this context; it never
replaces another tool. **Stop / shaded view** disarms re-entry and restores normal
shading. Closing the window or resetting the scene cancels queued re-entry.

Replace the complete folder and run `layer_skin_ui_refresh.py` using the reload
snippet below. Confirm **UI 31**. The registered plug-in remains **0.4.1**, and
existing Undo objects are preserved. See
[BRUSH_LIFECYCLE_UPDATES.md](BRUSH_LIFECYCLE_UPDATES.md) and
[COMPONENT_SELECTION.md](COMPONENT_SELECTION.md).

**819/819 checks passed for UI 30**; those checks remain in the current suite. The Qt/recording-API checks and CPU replay
are documented in VALIDATION.md.
Native Maya/VP2/PySide2 verification remains pending.

## Retained UI 28 feature: lightweight brush-radius changes

**B + drag** and the **Brush radius** field now have a settings-only path.
Sizing does not start paint-stroke setup, read skin weights/layer metadata,
encode layer state, scan the native paint array, upload all vertex values,
recompose weights or rebuild mesh/topology/brush geometry. The existing weight
colors and paint context stay active. An unchanged numeric radius does not
send a native edit.

Artisan can request surface data or issue stroke callbacks while its settings
change. A guard keeps those callbacks from authoring or preparing a stroke,
including callbacks after B or the mouse button is released. The guard ends
at idle after both are released; a genuine new paint press also ends it. The
existing coalesced settings sync updates scalar UI fields. A queued selection
refresh waits until sizing ends and is resumed only when actually pending.

A real pending paint or Relax stroke is saved once before the settings change.
That genuine save keeps its normal readback, validation and Undo behavior;
subsequent sizing updates do no additional mesh work. Brush falloff, radius
boundary/footprint calculations and painting behavior remain unchanged.

Replace the complete folder, run the refresh snippet below, and confirm
**UI 31**. A new brush-helper cache key ensures an already open editor gets the
updated handler. The registered plug-in remains **0.4.1**, and old Undo objects
are retained. See [BRUSH_RADIUS_UPDATES.md](BRUSH_RADIUS_UPDATES.md).

**783/783 checks passed for UI 28**, including eleven new radius/paint lifecycle
checks; those regressions remain in the current 797-check suite. CPU callback replays at 100,000 and 250,000 vertices performed **zero
skin reads, metadata reads, paint-array reads/writes or state encodes** during
200 guarded radius edits each. These are recording-API measurements, not Maya
viewport timings; native Maya verification remains pending.

## Retained UI 27 feature: nearest-joint / nearest-bone assignment

Assignment no longer has **Radius** or **Falloff**. Each scoped vertex receives
one selected influence at generated coverage 1. **Distance to joint** finds the
closest frozen pivot; **Distance to bone** finds the closest finite bone segment,
including every joint child beneath transform buffers. A leaf uses its pivot.

**Joint axis** uses closest-bone distance first. When bones are equally close,
it prefers a joint whose chosen local-axis coordinate is positive, then greater
logical joint depth and a stable UUID. A distant positive-axis joint cannot take
a vertex from a closer bone. If every axis test is negative or zero, the closest
bone still receives the vertex. The rule is the same for a chain and a fork.

A cached balanced spatial index prunes joint/bone candidates. Identical results
reuse the result cache, and another vertex scope reuses the joint index. Large
generated assignments use the existing compact sparse-row format through layer
editing and scene saving. All three methods retain the pre-skin/bind-space
reference, vertex scope, locks, masks, alpha, paint-preservation option and Undo.
Brush Radius and brush Falloff keep their normal painting behavior.

Replace the complete folder and run the refresh snippet below. Confirm
**UI 31**; the registered plug-in stays at **0.4.1**, with its command class and
Undo objects retained. Existing saved weights are unchanged until **Assign
selected joints** or **Rebuild layer**. Old radius/falloff/axis-overlap settings
are ignored when regenerating. See [HIERARCHY_ASSIGNMENT.md](HIERARCHY_ASSIGNMENT.md)
for the exact rules, cache behavior and native Maya test.

**772/772 automated checks pass**, including eight new nearest-search, negative
axis, sparse-storage, cache and old-planner/Undo regressions. Native Maya
execution is pending; see [VALIDATION.md](VALIDATION.md).

## Retained UI 26 feature: expand and select joint branches

**Shift + left-click** a joint row or its disclosure arrow to expand every level
under that joint. Repeating the gesture keeps it open. Click the arrow normally
to collapse it. Clicking an already selected joint keeps the other selected
joints; Ctrl + Shift-click adds a new root to the selection.

Use **Select joint + descendants**, below the hierarchy, to select the root and
every joint below it. Multiple selected roots are supported and overlapping
branches are included once. Collapsed and search-hidden children are included,
and intervening transform buffers do not interrupt the branch. The current
joint remains the paint target. The button is disabled with no selection.

These actions change the hierarchy UI only. Maya scene selection, weights and
pending paint stay intact when the paint target is unchanged. Shift-clicking a
different joint uses the normal paint-target change and stroke-saving behavior.
Padlock clicks, including Shift-clicks, still toggle only the clicked lock.
An explicit expansion made during search is retained after clearing the search.
Traversal uses the cached Qt hierarchy without extra Maya DAG queries.

Replace the complete folder, run the refresh snippet below, and confirm
**UI 31**. The registered plug-in remains **0.4.1**. See
[VALIDATION.md](VALIDATION.md) for automated checks and pending native Maya checks.

## Retained UI 25 feature: pre-skin assignment reference

**Distance to joint**, **Distance to bone** and **Joint axis** now share a cached
snapshot of the loaded skinCluster's exact input geometry. The input points use
`geomMatrix` and bound joints use inverse `bindPreMatrix`, so both are compared
in bind-world space. Assignment no longer starts from the visible posed mesh.
Intermediate shapes are resolved through the actual input connection; no
`Orig` name guessing, pose reset or scene-transform edits are used.

The UI identifies **Skin input / bind space**. Unbound joints use captured
relative offsets and are counted in that label. Brush picking and spatial brush
boundaries continue to follow the visible deformed mesh. The input may include
upstream deformers; it is specifically pre-skin, rather than before all history.

On the next explicit Assign, older posed references migrate within the same
Undo operation. Opening the editor leaves them intact. The existing paint/mask
preservation options still apply. Recapture explicitly refreshes input and bind
data; repeated assignments keep their cached reference across pose changes.

Replace the complete folder, run the refresh snippet below, and confirm
**UI 31**. The plug-in remains **0.4.1**. See
[PREDEFORM_REFERENCE.md](PREDEFORM_REFERENCE.md) for spaces, unbound joints,
cache behavior, upstream deformers and the native Maya pose test. Native Maya
execution remains pending.

**752/752 automated checks pass**, including 14 new pre-skin/bind-space,
pose-consistency, cache, migration and Undo regressions. All 62 Python files
parse with Python 3.10 grammar.

## Retained UI 24 feature: assignment on buffered and branched skeletons

Two hierarchy problems are corrected. Reference capture now finds joint roots
and joint-to-child bone segments through intervening transform groups. Joint
axis no longer gives an unrelated branch's vertices to the first joint merely
because that branch has more groups or sorts earlier by name.

The reference includes all nearest joint-child relationships, even through
transform buffers. UI 27 now uses closest-bone distance for both chains and
branches, with axis preference only for equally close candidates; the older
positive-only and child-first ownership rules have been replaced.

Old frozen references gain UUID parent links and corrected endpoints on the
next assignment. Their saved vertex positions, joint positions, axes and frame
are retained; upgrading never mixes in the current animated pose. Assignment
and its reference update remain one Undo operation. Duplicate short joint names
are supported through full paths and UUIDs. Assign reports how many scoped
vertices received generated samples. UI 27 covers all scoped vertices with a
nearest candidate. Layer locks, masks and paint-preservation choices still apply.

Replace the complete folder, run the refresh snippet below, and confirm
**UI 31**. Select the desired joints/branches and click **Assign selected
joints** to apply the fix to existing generated weights. Use **Recapture
reference** at the intended reference pose if the skeleton/mesh has since been
edited, or a chosen joint did not exist in the old snapshot. The plug-in version
stays **0.4.1**; the registered command is retained during UI refresh.

See [HIERARCHY_ASSIGNMENT.md](HIERARCHY_ASSIGNMENT.md) for selection, methods,
scope, caching and native verification. Native Maya execution remains pending.

**738/738 automated checks pass**, including 17 new hierarchy-assignment,
frozen-reference, spatial-index and Qt regressions. All 60 Python files parse
with Python 3.10 grammar.

## Retained UI 23 feature: hierarchy search

Use **Search** at the top of the **Joint hierarchy** dock to filter joint names
as you type. Matching is case-insensitive. Plain text such as `Shoulder` finds
that text anywhere in the name. `*` matches any text and `?` matches one
character. For example, `left*Shoulder*` and `left**Shoulder**` find names that
start with `left` and contain `Shoulder` later in the name. Namespaces are
ignored unless you include one in the query, for example `rig:left*Shoulder*`.

Matching joints keep their ancestor branches visible and expanded for context;
unmatched children and sibling branches are hidden. The count reports direct
matches. An unmatched query shows **No matching joints**. Click the field's
clear button to restore every row and the previous collapsed/expanded branches.
The complete skinCluster hierarchy is retained underneath the filter.

Search only changes Qt row visibility. It preserves the current paint joint,
hierarchy selection, gray weight status, locks and pending strokes. It does not
query Maya, recalculate skinning or refresh viewport colors while you type.
Refresh/rebuild reapplies the query; the safe UI refresh keeps its text too.

Replace the complete folder and run `layer_skin_ui_refresh.py` using the Python
snippet below. Confirm **UI 31** in the title. The plug-in stays at **0.4.1**.
All **157 focused hierarchy, painting UI and refresh checks pass**, with no
skips. Native Maya verification is pending; see [VALIDATION.md](VALIDATION.md).

## Retained UI 22 feature: one command to open or refresh

`layer_skin_ui_refresh.py` now works when no Layer Skin window is open. It uses
the sibling `layer_skin_launch.py` to open the exact folder, then refreshes the
authoring helpers. A matching registered 0.4.1 command is reused; a fresh session
loads the exact plug-in file. The normal version/path mismatch checks still apply.

Hidden and embedded editors are found and refreshed in place instead of being
missed by the previous visible/top-level-only check. If multiple live editors
exist, the error names that situation and asks you to close the extras.

Replace the complete folder, then run this in Maya's **Python** Script Editor:

```python
import runpy
runpy.run_path(
    r"D:/dev/MayaZone/layer_skin_prototype/layer_skin_ui_refresh.py",
    run_name="__main__"
)
```

Confirm **UI 31** in the window title. Existing valid pending strokes are saved
before replacing an editor; mesh, layer, joint, brush settings and Utilities
fields are retained. Click Paint to resume and Preview import again before
writing. The registered command, plug-in version, native Undo objects, paint
algorithms and saved scene schema stay at 0.4.1. The refresh does not unload a
plug-in or clear Undo. A genuine older backend or mismatched registered folder
still needs the matching package/session; it is never force-replaced.

**711 automated host checks pass**, including 20 new entry-point and real-Qt
checks. All 56 Python files parse with Python 3.10 grammar. Native Maya
launch/refresh verification remains pending; see [VALIDATION.md](VALIDATION.md).

## Retained UI 21 feature: Maya native lock icons

Hierarchy padlocks now load Maya's built-in `Lock_ON.png` / `Lock_OFF.png`
resources, with generic native alternatives when needed. Native artwork keeps
its own colors. The previous drawn icons remain only for hosts without those
resources, such as standalone Qt. Row icons are cached per browser; drawing a
row never queries Maya. The 16-pixel click area, layer-local protection, Undo,
selection, gray zero-weight rows and existing paint tools are unchanged.

Replace the complete folder and run the refresh command above. An existing
0.4.1 window is preserved until replacement. Confirm **UI 31** in the title. The refresh reloads the
joint view helper so a previously open hierarchy also receives the new icons.

## Retained UI 20 feature: production-size skin export/import

The two-million vertex × influence stop has been removed from mesh loading,
skin-file validation, transfer planning and binding checks. Large native buffers
now use packed float64 storage, file weights remain sparse through loading and
ID planning, and large imported layers store nonzero row weights rather than a
full Python list for every vertex. Native weight reads/writes are batched and
archive arrays are streamed. Export/import still use the v1 `.rtkskin` format,
UUID/name/distance mapping and one native Undo transaction.

The supported packed-buffer budget is **1024 MiB per dense buffer** (134,217,728
values), with a separate **1024 MiB uncompressed archive** budget. For example,
100,000 vertices × 339 influences is 33.9 million values and a 258.6 MiB packed
buffer, inside the supported range. Several buffers and Undo snapshots can be
live together; this is not a whole-process RAM limit.

**691 automated checks pass.** A CPU-only 100,000 × 339 workflow with four
nonzero weights per vertex completed export, load, ID planning, layer import,
metadata save/load, composition and full result verification. Peak process RSS
was about 1.03 GiB on this host. This excludes native Maya IO, binding, Undo and
viewport/GPU work. See `PRODUCTION_IO_BENCHMARK.json` and
[UTILITIES_GUIDE.md](UTILITIES_GUIDE.md). Native Maya validation is pending;
`maya_skin_io_smoke.run_large()` provides an above-limit native fixture.

For an already open 0.4.1 window, replace the **complete folder**, including the
new `layer_skin_storage.py` and `layer_skin_memory.py`, then run the refresh
command below. Confirm **UI 31** in the title. The refresh installs the new
context, core and normal Python write helpers without unloading the registered
command or clearing Undo. A fresh Maya session also uses the latest native
command's full-mesh allocation shortcuts. The registered API stays at 0.4.1.

## Retained UI 19 feature: Relax native screen boundary

Regular Relax and Shift + paint now clip against Maya's queried `screenRadius`
as well as the world-space sphere and projected world circle. The screen clip
uses the stamp cursor as its center. Each interpolated stamp positions the
native outline and queries its own radii; the drag endpoint's radius is no
longer reused for earlier samples. Fractional input coordinates are retained
when converting between Qt and viewport port coordinates.

This fixes locally reproduced oversize footprints when the native screen
circle is smaller than the reconstructed world circle, and radius sampling at
the wrong interpolated point. The solver's outside one-ring neighbors stay
read-only. Missing/invalid native screen-radius queries retain the prior
projected-world fallback, which Paint info identifies. Native Maya is not
available here, so exact outline/DPI correspondence remains to be checked.

The safe refresh uses a new authoring-helper cache key so an already open
UI 18 window cannot silently reuse the old brush implementation. Keep the
window open, replace the complete folder, then run `layer_skin_ui_refresh.py`
using the refresh command below. Check the title ends in **UI 22**,
then click Paint again. The registered plug-in stays at 0.4.1.

## Retained UI 18 feature: layer influence locks

Click the padlock before a hierarchy joint to protect its displayed weight
contribution in the selected layer. Locked rows remain selectable for read-only
weight viewing. Selecting an unlocked joint resumes painting. Locks also apply
to Replace/Add/Scale, assignment, Clear paint edits and regular/Shift Relax.

The new **Redistribution** menu chooses Proportional (default) or Equal sharing
among other unlocked weighted joints. Requested weight is capped by the budget
left after locked contributions. Settings are saved per layer and support Undo.
These are layer authoring locks; coverage, masks, alpha and other layers can
still affect final skin weights. No joint transform attributes are locked.
See [INFLUENCE_GUIDE.md](INFLUENCE_GUIDE.md) for equations and the workflow.

The safe refresh installs the updated core editing functions and tree/session
helpers while keeping the registered 0.4.1 command and native Undo objects.
Use the complete folder and the refresh instructions below.

## Retained UI 17 feature: full skinCluster hierarchy

The root dropdown and Scope to selected joint button are removed. The right
dock automatically shows every joint hierarchy containing a skinCluster
influence, including zero-weight influences. The skin's complete influence
list seeds the tree; selecting a tip joint cannot narrow it to that tip.

Joint ancestors above transform buffers are included. Buffers are skipped
visually and rows retain their nearest joint parent. Unbound descendants stay
available for direct painting; unrelated skeleton roots are not added. Gray
still means no nonzero weight in the selected layer.

Refresh retains UUID-based selection and collapsed branches. Influence path
changes trigger rebuilding, and the main Refresh button also discovers new
unbound descendants. The safe UI refresh replaces the loaded tree helper as
well as UI/session code, so an old single-root implementation is not reused.
The registered plug-in stays 0.4.1; existing paint, Undo and Relax fixes remain.

## Retained UI 16 feature: Relax brush boundary

Regular Relax and Shift + paint now take the effective native world radius
after moving Maya's outline. They no longer convert that radius using the
scene's display unit. Each connected world-space patch is also clipped to its
projected circle in physical viewport pixels. Foreground vertices on a curved
mesh cannot qualify solely because they are inside the world-space sphere.

Outside edge-neighbors supply smoothing values but stay unchanged, even with
many Brush passes. Each stamp writes only its own footprint; the final stroke
saves the union of the patches actually brushed. Previously brushed patches
remain edited when the cursor moves away. Vertex colors can still interpolate
across a polygon that straddles the boundary.

Position, projection and neighbor caches are reused during a gesture. Native
outline, B-radius, one-stroke Undo and the previous falloff/color fixes remain.
Paint info includes the world radius, its source and the projected radius in
port pixels. See RELAX_GUIDE.md for the updated equation and Maya check.
Local boundary/Undo tests pass; actual Maya outline/rendering validation is
still required. Refresh the open 0.4.1 window using the instructions below.

## Retained UI 15 feature: explicit brush falloff

Replace previously used a hidden, forced Gaussian stamp. Its edges received a
partial blend, so a brush pass could leave different values across its radius.
The new **Falloff** menu beside Radius and Opacity provides **Solid**, **Smooth**
and **Gaussian** for Replace/Add/Scale. Solid is the new default; use **Opacity
1** when you want the full Replace value on every affected vertex. Smooth and
Gaussian remain available for soft transitions. The chosen profile survives
feedback updates, joint changes and UI refresh. Hidden pressure modulation and
opacity accumulation are explicitly disabled in this tool's native context.

Falloff changes save pending paint before changing the brush. They retain the
UI 14 context-reuse and enable-only color updates. Relax/Shift retains its own
smooth layer solver, so its native falloff selector is disabled while Relax is
selected. Execute still applies the full group amount without brush falloff.
See [OPERATIONS_GUIDE.md](OPERATIONS_GUIDE.md) for layer/final-weight differences
and a Maya verification sequence. This update keeps native API **0.4.1**.

## Retained UI 14 feature: keep active paint feedback running

Paint no longer stops and rebuilds an already active brush on the same mesh.
Repeated clicks retain its native context, buffer, brush controller and return
tool. Changing the hierarchy joint validates and loads the next weight array
in place. Feedback updates keep native colors enabled throughout; the previous
off/on toggle has been removed.

Valid pending strokes save to the outgoing joint first. Failed saves keep that
joint, and failed transfers restore its array and view. Display-only changes
retain authoring data and Undo. A changed mesh/buffer or a selection that no
longer supplies a paint surface still uses normal activation. The four operation
groups, Shift Relax and explicit Stop behavior are retained.

The earlier Qt repaint gate remains, but the native brush reset itself is now
avoided for these active-view changes. This removes reset states caught by the
direct-draw probes; actual Maya/VP2 pixels remain to be checked. See
[VIEWPORT_FIX.md](VIEWPORT_FIX.md) for the diagnosis and verification steps.

## Retained UI 13 feature: four operation groups

**Relax | Replace | Add | Scale** share one row, with parameters above their
Execute buttons. Use brush selects the matching Paint operation; Shift always
uses the layer Relax solver. Replace, Add and Scale have separate remembered
values and work on either Weights or Mask. Relax Execute now smooths the mask
when Mask is selected. Keep coverage applies to both Relax methods.

Replace/Add/Scale Execute uses selected vertices unless whole mesh is checked.
Relax keeps selected vertices/edges, or the whole mesh with no components.
Brush radius and Opacity are shared; Execute uses the full configured amount.
The native API stays **0.4.1**, with the existing command class and Undo history.
See [OPERATIONS_GUIDE.md](OPERATIONS_GUIDE.md) for values, formulas and checks.

## Retained UI 12 feature: continuous color changes

Paint, joint/layer switches, weight/mask changes, heat-map changes and layer
editing actions now publish their completed color view together. Existing
viewport widgets hold repainting while the old feedback is cleared and the new
values are loaded, then redraw the finished view. This removes the intermediate
material/base-color frame reproduced in the Qt transition checks.

Nested actions share one handoff, failed edits restore repainting, and panels
that were already paused stay paused. Stop / shaded view still restores normal
shading explicitly. No overlay, global refresh suspension, shader change or
Undo reset is added. The working UI 11 Relax solver and coverage choices remain.
See [VIEWPORT_FIX.md](VIEWPORT_FIX.md) for native verification and diagnostics.

## Retained UI 11 feature: live Shift-smooth colors

**Preserve coverage (Shift brush)** is now off by default. This lets the brush
smooth the visible layer contribution and feather a painted edge into empty
neighboring vertices inside the brush. With preservation on, a single-joint
painted patch could remain unchanged even though the Relax solver ran.
Enable it explicitly when the coverage must stay fixed.

Native redraws now happen during the drag, with immediate redraw requests
throttled to 30/second, followed by a forced final redraw. Previously the code
only scheduled a refresh for Maya's next idle, which can be delayed during a
held stroke. The outline remains Maya's; smoothing still uses the layer solver.
No Qt overlay is reintroduced. The equations and saved schema remain unchanged.

Updating from an older UI adopts the new coverage default once. Subsequent
refreshes retain your checkbox choice. Refresh to **UI 22**, click Paint
and test a nonuniform painted edge with Preserve coverage off. Paint info now
reports mesh hits, footprint/changed counts and a reason for unchanged strokes.
See [VIEWPORT_FIX.md](VIEWPORT_FIX.md) and [RELAX_GUIDE.md](RELAX_GUIDE.md).

## Retained UI 10 feature: native brush outline

Shift-relax now uses **Maya's native Artisan outline**, with no painted Qt
widget covering the viewport. The former translucent brush-circle widget is
consistent with the supplied black viewport and repeated gold-ring trails.
It has been removed. Shift still relaxes weights/masks, ordinary strokes still
paint, B + drag still changes radius, and a completed Relax stroke remains one
Undo step. The solver and saved layer format are unchanged.

Refresh an open 0.4.1 window using the script below; its title must end in
**UI 22**. Refresh closes the old controller and requests a native viewport
redraw. Do not force-unload the plug-in. See [VIEWPORT_FIX.md](VIEWPORT_FIX.md)
for the diagnosis, update steps and native verification checklist. Maya/VP2 is
unavailable here, so the exact GPU reproduction still needs verification.

## Retained UI 9 feature: Utilities tab

The Layer Skin window now has **Layers** and **Utilities** tabs. Utilities
exports the final native skin result to a lossless `.rtkskin` file, then imports
it by matching vertex IDs or closest-surface barycentric interpolation. The
original source mesh does not need to remain in the scene.

Joint mapping combines UUID, name/search-replace and bind proximity (default
0.01 Maya units). Preview shows the mapping, and individual rows can use a
manually selected joint. Import supports existing skins or an unskinned target,
and creates a full-coverage top layer while retaining existing Base/layers/masks.
Binding, the imported layer, native weights and optional skin-wide DQ/method
settings share one Undo group. Preview does not modify skin or layer data.

Start with **Utilities → Export skinning**, then **Load file → target mesh →
Preview import → Import as new layer**. The primary Preview/Import controls stay
visible while the options scroll. See [UTILITIES_GUIDE.md](UTILITIES_GUIDE.md)
for mapping, geometry spaces, file contents, Undo behavior and the native smoke
test. The registered Maya plug-in remains **0.4.1**; use the refresh below for
an existing window. This tab is inside Layer Skin; no Master Toolkit update is
needed.

## Retained UI 8 feature: Cleanup

Saved layers and the assignment reference live on a Maya network node linked
to the mesh/skinCluster. Reopening the window or saved scene therefore reloads
the same stack. **Cleanup…**, beside Undo/Redo, now offers:

- **Clear memory caches**: keep saved layers and current skin; reset assignment,
  decoded/composed state and Relax topology caches.
- **Remove saved layers · keep current skin**: inspect and remove only this
  mesh's owned layer data, including its Base snapshot, masks and reference.
  Current skin weights and joints remain. One Maya Undo restores the data.

The metadata-only removal can handle corrupt/duplicate saved data even when
normal editor loading fails. It rechecks ownership and protected nodes before
using native Undoable deletion. Valid pending strokes are saved first. Live
paint arrays remain available for Artisan Undo and are not saved in the file.
**Save the Maya scene after removal** so reopening it does not restore old data.
The details and native verification checklist are in
[CLEANUP_GUIDE.md](CLEANUP_GUIDE.md).

## Retained UI 7 features

**Shift + paint = Relax** under the brush, for either layer weights or masks.
**B + drag** retains Maya's native radius adjustment and synchronizes the field.
The Relax group adds Brush passes and Preserve coverage; Escape cancels the
current Relax gesture. A completed gesture saves one Undo step.

**Flood → Assign is fixed:** Flood creates manual overrides that used to hide
new generated assignment. Assign selected joints now replaces those overrides
inside its chosen scope. Check Preserve painted / flooded edits to retain
them. Rebuild layer always retains them; layer masks remain in either case.

The equations, factor effects, examples and limits are in
[RELAX_GUIDE.md](RELAX_GUIDE.md).
See the refresh instructions below to update an open 0.4.1 window without
unloading the registered command or clearing Undo.

## Keep colors while selecting and relaxing

After **Paint**, press Q or switch to vertex/edge selection. Layer or mask colors
stay on the loaded mesh. The active selection tool and component mode remain
available. Click **Paint** to reactivate the brush. Maya has one current tool;
selecting components and dragging a paint stroke remain separate actions.

**Flood relax** refreshes the displayed weights. If you were painting, it resumes
the brush; if you were selecting components, it preserves that tool, mode and
selection. Choosing another joint/layer, toggling Mask, editing layer properties,
assignment and Undo/Redo update the held view. Mask colors remain grayscale.
**Stop / shaded view** explicitly restores normal shading and keeps saved data.
Native Paint Skin Weights keeps its own feedback and existing external-edit guard.

The held view uses one OpenMaya bulk color upload, a cached 4097-entry palette,
and skips identical uploads. Merely changing component selections does not scan
skin weights or rebuild colors. The displayed scalar data and skin weights stay
full precision; only the visual ramp lookup is quantized. No texture, replacement
material, frame solver, plug-in unload or Undo reset is added.

## High-resolution tests

`HIGH_RES_BENCHMARK.txt` records current pure Python runs: 100,000 vertices /
16 influences / 3 iterations took 1.952 s for the solver; 250,000 / 8 took
4.950 s. A 1,000-vertex ROI took 0.017 / 0.025 s. In the earlier 250k-vertex
brush case (before the projected-circle clip), 40 stamps of 437–452 vertices took 0.289 s total for footprint and
solver, plus 0.136 s to build the position grid. These exclude Maya geometry
extraction/raycasting, full preview-array uploads, skin writes/readback,
metadata encoding and GPU drawing. The 2,000,000 vertex × influence guard
remains; this is not a production memory or native brush-frame-rate guarantee.

Native Maya is unavailable in this environment. After refreshing to UI 22, run
this in Maya's Python Script Editor to check ~100k vertices with actual API
writes, brush activation, vertex/edge selection, edge-scoped Relax, Undo/Redo,
preview cleanup and viewport-refresh timings:

```python
import runpy
test = runpy.run_path(
    r"D:/dev/MayaZone/layer_skin_prototype41/layer_skin_highres_test.py"
)
result = test["run_maya"](subdivisions=316)  # 100,489 vertices
# Use subdivisions=499 for 250,000 vertices.
```

This creates a uniquely named demo namespace and keeps it selected. It saves
and stops any pending Layer Skin brush first. Click Paint in the UI for the
interactive check: paint a stroke, press Q, F9/F10, select vertices/edges, apply
Relax, Shift-paint weights/masks, B-drag radius, Escape, switch joints and Undo.
Also test Flood → Assign with the preserve checkbox off and on. Verify colors
and smooth brush response.
`keep=False` removes only the test namespace. The automated native assertions
verify data/API state; a GPU/brush visual check still requires Maya interaction.
Use Paint info to inspect `persistent_display`, upload time and any display error.

To reproduce CPU checks outside Maya: `python layer_skin_highres_test.py --pure`.

## Heat map and Relax

**Weight display** defaults to Heat map: blue at 0, cyan at 0.25, green at 0.5,
yellow at 0.75 and red at 1. Grayscale remains available. Values always map to
0–1 rather than stretching to the currently visible minimum/maximum. Both layer
weights and read-only final skin weights use the choice; masks stay grayscale.
The brush uses native Artisan feedback. When you leave the brush, a temporary
private vertex-color set keeps the same colors visible. Original artist color
sets, display flags and mesh history are restored on Stop, close, hide, scene
change and before save/export; the preview is rebuilt after file IO. These
colors do not change weights. Changing display saves a valid pending stroke.

The **Relax** group provides Iterations (1–100, default 3), Strength (default
0.5), Max new influences (0 = unlimited), Brush passes (default 1), Keep coverage
and **Execute**. See RELAX_GUIDE.md for the equations. Execute edits the selected
layer's weights or mask according to the Weights/Mask choice. Base and the layer
opacity remain unchanged. Shift strokes and the selected Relax brush use the
same mode choice.
Assign or paint layer weights first; an empty layer is a no-op. Relaxed samples
become manual overrides, so Rebuild preserves them and Clear paint edits reveals
the generated assignment underneath.

Select mesh vertices or edges to limit the write region. Edges use their two
endpoints; mixed vertex/edge selections are combined. With no components selected,
Flood relax processes the whole mesh. Neighbor values outside a selected region
remain fixed and contribute to its boundary. Face components or components
on another mesh are rejected rather than silently applying to the whole mesh.
The right hierarchy can select joints without disturbing vertex selection.

- Zero or one selected joint: relax across all neighboring influences. A single
  joint is the paint-view choice, not a restriction on the solve.
- Two or more selected joints: preserve their combined contribution at each
  vertex and redistribute only within that group using the neighbors' relative
  proportions. All unselected influence contributions remain unchanged. For
  example, selected weights 0.2/0.3 retain a total of 0.5; a neighboring 80/20
  ratio approaches 0.4/0.1. A vertex with zero group contribution stays zero.
- Max new influences limits additions relative to the start of this entire
  action, not additions per iteration. Existing influences are not pruned. The
  strongest candidates win; equal candidates use stable influence UUID order.
  This adds influences to vertex distributions, not joints to the skinCluster.

Each iteration blends the old contribution field with the mesh-edge one-ring
average. It reads a previous-iteration snapshot (Jacobi), avoiding traversal-order
bias. Strength 0.5 includes the current vertex and avoids the simple two-vertex
swap that pure neighbor replacement can cause. The solver stops early at a
fixed point. In unrestricted mode it also smooths authored coverage where a
layer is partial/empty; stored rows are normalized and coverage remains in 0–1.
Masks remain independent and final skin rows remain normalized by composition.

Native neighbor queries are cached lazily by mesh UUID, topology and vertex
count, within a 32 MiB estimate. Iterations use sparse Python data and do not
call Maya per weight. All computation finishes before a single native authoring
command commits changed rows and metadata. Existing lock/external-edit checks,
readback verification, rollback and one-step Undo remain. Escape/cancellation or
the 120-second computation limit occurs before any skin write; no Maya progress
window is opened. RELAX_BENCHMARK.txt retains the earlier 20k-vertex measurement. The current
100k/250k runs and local brush stamps are in HIGH_RES_BENCHMARK.txt. The solver
reads only scoped samples and their one-ring halo; cloning final authoring
maps, validation, native preview uploads and serialization can still involve
the full mesh. Timings exclude Maya API/skin-write/encoding and viewport costs.

## Joint axis: nearest bone with axis preference

Choose Joint axis, a local axis such as +X and the desired joints. Assignment
first finds the closest frozen bone segments. Among equally close bones it
prefers a positive local-axis coordinate, then deeper logical joints and a
stable UUID. The plus/minus axis choices reverse that preference. Vertices on
the zero plane or behind every joint still receive their nearest bone; there
is no positive-only exclusion or unbounded child-first claim.

The local-axis sign comes from a reciprocal-basis plane, retaining support for
rotation, shear, nonuniform scale and mirrored matrices. Bone distance stays
primary, so a farther positive-side branch cannot steal vertices from a closer
negative-side bone. Each vertex receives one influence at full generated
coverage. Masks, layer alpha, locks and preserved manual paint still affect the
final skin weight. Scope remains the way to restrict assignment to part of a mesh.

All methods use the cached pre-skin/bind-space reference. The joint/bone BVH is
built once per relevant reference, selected joint set, influence columns and
method/axis. Repeated scopes reuse that index; an identical assignment reuses
the generated result. Traversal makes no Maya calls inside the per-vertex loop.
See [HIERARCHY_ASSIGNMENT.md](HIERARCHY_ASSIGNMENT.md) and
`NEAREST_ASSIGNMENT_BENCHMARK.json`. `AXIS_ASSIGNMENT_BENCHMARK.txt` records the
superseded child-first implementation and is retained as historical data only.

## Switching to Maya Paint Skin Weights

The outgoing Layer Skin brush now saves its pending stroke synchronously during
tool cleanup, closes that stroke's Undo group, releases its array and disables
its feedback before the incoming tool takes over. No layer write is left in a
release timer. ToolChanged is a fallback when native cleanup is omitted, and
late callbacks cannot start another layer stroke. Picking a joint in our
hierarchy does not take control away from Maya's current brush.

Maya Paint Skin Weights changes the final skinCluster, not the selected authoring
layer. Merely opening that tool should pause layer painting; click our Paint
button to return. If you actually paint with Maya's tool, undo those native
strokes before resuming layer edits. Otherwise use Cleanup → Remove saved layers to preserve
the native result, then add a new stack if needed. Existing layer metadata is
never silently replaced with native skin edits. Read-only final-weight
inspection remains available even when the native result has changed.

The warning `Maya changed the requested weights; operation cannot be accepted`
is the command's readback verification: Maya did not retain the requested
weights. Source inspection found deferred handoff writes which could run after
the incoming brush setup. UI 3 removes that timing problem; it does not disable
verification, unlock influences, change normalization or suppress real errors.
Paint info also reports the skinCluster's normalization, maximum-influence and
skinning settings for further diagnosis if native Maya still rejects a write.

## Simpler mask controls

**Show mask** has been removed. Choose **Mask → Paint**, double-click an editable
layer's mask icon, or right-click that layer and choose **Paint mask**. The mask
appears automatically while painting. Editable-layer menus no longer have a
separate View mask action. Base remains read-only and can preview its white mask.

**Stop / shaded view** saves valid pending strokes, leaves the brush and turns
off the weight/mask colors and removes the temporary viewport display. Use it to inspect the model with normal viewport
shading and check the resulting deformation. It keeps all painted weights and
masks; returning to Mask → Paint reloads the saved values.

To set a layer mask, choose **Mask**, set Replace **Value** and click its
**Execute** button. Enable **whole mesh** to apply it everywhere. Mask 0
hides this layer there, mask 1 reveals its authored weights, and intermediate
values blend its contribution with lower layers. It changes the spatial mask,
not joint-weight samples. Alpha is the layer-wide amount; the mask controls
where that amount applies.

For a regional layer, fill the whole mask with 0, then paint 1 where the layer
should contribute. Fill with 1 to restore the layer's coverage everywhere, or
fill selected vertices with 0.5 for a uniform partial contribution. A mask alone
does not assign any joint weights to an empty layer.

This updates the UI and paint-session code; the registered plug-in remains
**0.4.1**. Replace the complete folder and run the refresh script from that
folder. It refreshes an existing editor or opens one first when needed:

```python
import runpy
runpy.run_path(
    r"D:/dev/MayaZone/layer_skin_prototype/layer_skin_ui_refresh.py",
    run_name="__main__"
)
```

Use the folder where you extracted this package. The refresh saves valid pending
strokes and retains the mesh/layer/joint and brush controls. Click Paint to resume.
The title ends in **UI 22**. It replaces UI/session helpers, transient assignment
caches and planning helpers for value operations, Relax/scoped assignment and skin import. The registered
native command class, current paint buffers/geometry binding and Undo history
remain live. A rejected pending save leaves the original window open; read
the error before retrying. This session refresh requires the 0.4.1 API. For an
older backend, use the usual launcher below with the complete 0.4.1 folder in a
matching session. A fresh session can also use the open/refresh command above.
Do not force-unload the plug-in or clear Undo to update UI 22.

Refresh also keeps the Utilities fields, cached skin file and manual mappings.
Its old Preview is discarded; click Preview import again before writing.

Current regression counts, CPU timings and the native Maya checklist are in
VALIDATION.md and LOCAL_TEST_RESULTS.txt. Local checks use recording API
objects and real offscreen Qt; they do not establish actual Maya viewport or
DG behavior. The registered API stays 0.4.1. The refresh extends its planner
without unloading/re-registering the MPxCommand class, so existing Undo
instances remain usable.

## Authoring prototype

A standalone Python 3 plug-in for layer skinning on a native Maya skinCluster.
Choose any joint in the right hierarchy and paint it directly. The first
completed stroke registers it with the selected layer and, if necessary, binds
it at zero before applying the weight. Gray joints remain selectable. Automatic
Base capture, Artisan painting and cached assignments remain.
No C++ build, NumPy or ngSkinTools installation is required.

The Maya 2024 trace supplied for 0.3.9 confirmed that painting saved four
nonzero vertices and loaded exactly the same values after switching back to the
original joint (maximum 0.988858). Native skin weights also matched the saved
composite. The reported black viewport therefore concerns display feedback.

0.4.0 introduced the native `doubleArray` backend. Its Maya report showed an
active userPaint brush, 13 unchanged strokes and an array host without any
geometry link. 0.4.1 adds a generic `surface` input on that host and connects
the selected mesh's `outMesh` before Artisan binds the values. Paint info now
includes `paint_array_geometry`. The correction follows a first-hand developer
reproduction of the same disconnected-host failure.

The backend binds Artisan to a native `doubleArray` containing the complete selected
joint or mask values. The buffer is populated before tool activation and when
views change. Native brush edits are collected at release and committed through
the existing layer command. Scalar get/set callbacks remain callable for older
scripts and tests, but they are not registered as the native brush backend.
Autodesk documents that an array-attribute callback disables those scalar hooks.

Before/after stroke hooks group the native working-array edit and layer command.
Repeated begin callbacks keep the current stroke. The window's release timer
also collects the array if an end hook is missing. Joint/layer/view changes save
pending edits to their original scope; rejected saves stop the change. A
read-only mask or final-skin view uses zero brush opacity and restores the loaded
array after a gesture. Layer data and skinCluster influences are never locked
by this feature.

One built-in network node per mesh holds its transient working array. Geometry
flows from the mesh into its generic input; the node never drives the mesh or
skinCluster. Buffers are cached by mesh UUID so different meshes/vertex counts
do not share a native Undo array. Each is marked `doNotWrite`, reused across
views, and retained after UI close so that
native paint Undo entries keep a valid object. New/open scenes discard it. Its
data is not the saved layer state, and it adds no deformation nodes or playback
solver. Existing schema-2 layer data is unchanged.

**Local recording-API and real Qt tests pass; Maya is unavailable here.**
The supplied trace establishes persistence in 0.3.9. The new native-array binding,
actual viewport colors, real brush Undo, and scene-save omission still need a
Maya check. `run_array_feedback()` exercises native plug readback, grouped
setAttr/layer Undo and joint/mask switching in Maya; real mouse strokes are a
separate check.

**Stroke saved** means the layer command succeeded and the values were read
back. **Values min–max** is the current loaded range. **Paint info** reports the
native feedback backend, working-array plug, selected view and save receipt.
The included `layer_skin_debug.py` traces both array and legacy scalar sessions.
No texture assignment is required.

The download is named `Layer_Skin_0_4_1_UI_15.zip`. It contains the complete folder.

## Repair a running 0.4.0 session

Extract the complete updated folder, for example to
`D:/dev/MayaZone/layer_skin_prototype41`. Keep the existing Layer Skin window
open with its layer/joint selected, then run:

```python
import runpy
runpy.run_path(
    r"D:/dev/MayaZone/layer_skin_prototype41/layer_skin_binding_fix.py",
    run_name="__main__"
)
```

The script saves valid pending edits, redirects the 0.4.0 transient buffer
factory, and restarts the selected paint view with a geometry-connected buffer.
It does not reload/unload the registered command or reset Undo. It also applies
to future 0.4.0 windows in this Maya session. Re-running reuses the repair's
buffer pool. The registered backend still reports 0.4.0; the repair report shows
`binding: mesh_geometry_1`, the selected mesh and geometry source.

After repair, paint a nonzero patch, switch joints and return. Check both visible
colors and weight changes, plus one Undo/Redo. This native Maya result is not
established by the local tests. `layer_skin_binding_fix.py` must remain beside
its updated `layer_skin_artisan.py`.

For future Maya sessions use the complete 0.4.1 folder and the launcher below.

## Install and open

Replace the **complete** `layer_skin_prototype` folder. Keep all its Python files
together; loading only `layer_skin_test.py` is insufficient. The launcher finds
the plug-in that owns `rtkLayerSkin`, then checks its actual version and full path
against the requested folder. If they match, it reopens the window. If nothing
is registered, it loads that exact file. A mismatch reports both versions and
paths, without unloading a plug-in or clearing Undo. Use the matching folder or
start a fresh Maya session with the intended folder when there is a real mismatch.

Run in Maya's Script Editor, **Python** tab:

```python
import runpy
runpy.run_path(
    r"D:/dev/MayaZone/layer_skin_prototype/layer_skin_launch.py",
    run_name="__main__"
)
```

To reopen the window in the same session:

```python
import maya.cmds as cmds
cmds.rtkLayerSkin(action="ui")
```

The previous example `assert version == "0.3.2"` rejected 0.3.3 and later versions
as well. Its message, "An older plug-in is loaded", was misleading; restarting
does not change that Python assertion. Remove it from old shelf/console scripts.
The launcher reads the expected version from the requested source file, so its
version check does not need editing for every update. Reloading a Python module
does not replace a registered Maya command. Keep the plug-in loaded while its
commands remain in Maya's Undo history.

The missing-`__file__` loader fix is retained. The loader resolves sibling files
from the compiled source filename or Maya's plug-in load path. It does not need a
`sys.path` change. The UI uses Maya's installed PySide6 or PySide2.

For the display/array regression in Maya, import `maya_layer_skin_demo` from
this folder and run `run_array_feedback()`. It creates and removes a small
demo namespace without replacing the current scene.

## First layer

1. Select one skinned polygon mesh in Maya. The window follows mesh selection.
   Selecting joints retains this mesh. **Pin mesh** prevents switching meshes.
2. Click **+**. One Undo step captures the current skin as **Base · 0** and adds
   an empty editable layer. Simply selecting a mesh creates no scene data.
3. Choose any joint in the right **Joint hierarchy** dock or the viewport.
   **Paint joint** shows the active joint. Choose Weights and click **Paint**;
   the first released stroke registers the joint automatically.
4. For automatic weights, select one or more hierarchy joints, choose a Method
   under **Assign weights**, set its range/scope and click **Assign selected joints**.
5. Rename, reorder, enable or adjust layer alpha. Changes immediately update the
   native skinCluster. Save the Maya scene normally to retain the editable stack.

The layer list has four columns:

| Column | Action |
| --- | --- |
| Drag handle | Drag above or below a row to change the order. |
| Layer name | Double-click, F2, or right-click Rename. The small mask icon opens mask painting. |
| Enabled | Include or exclude the layer. |
| Alpha | 0–1 opacity; Enter or focus loss commits the value. |

Top layers override layers below them. Base remains at the bottom with alpha 1
and mask 1. Its weights are the original capture, and its row cannot be renamed,
reordered, painted or deleted. Select Base to inspect its influences or view its
white mask. Duplicate editable-layer names are safe because operations use IDs.
Unchanged values, refreshes and repeated identical assignments add no Undo entry.
Keyboard Undo/Redo refresh the visible window automatically.

## Layer joints and hierarchy

The single joint hierarchy is docked on the right and shows all joint branches
containing skinCluster influences at once. It reads Maya's full DAG paths and renders its own Qt tree;
it no longer reparents a native Maya Outliner editor. There is no second list.
The root dropdown and Scope to selected joint button have been removed.
All skin influences seed the hierarchy, including those with zero weight.
Joint ancestors are followed across transform buffers, and all descendant
joints beneath those roots remain available. Unrelated roots are excluded.
The browser supports selection/navigation; renaming, deletion, reparenting and
drag/drop are blocked in this panel. The first three levels start expanded.
Intermediate transform buffers are skipped visually while the nearest joint
parent is retained. Refresh preserves existing expansion and selected joints.
Its selection is separate from viewport
selection so it does not replace a selected vertex scope.

**Gray joint name** means that the selected layer has no authored nonzero weight
for that joint. It stays selectable and can be painted immediately. It may be
bound to the skin already, used by another layer, or not yet bound at all.
When it has weight, the row uses normal text and joint icon appearance,
including a joint's custom Outliner text color captured when the tree is rebuilt.
Colors update on layer changes, painting, rebuilds and Undo/Redo. Base uses the
captured Base weights to determine its gray rows.

Status measures the layer's weight samples times coverage. A zero-coverage paint
erase overrides an earlier generated sample. Mask, layer alpha and Enabled do
not erase authored weight status; disabling a layer does not make its data empty.
The UI uses a local delegate to gray names, without changing joint attributes,
global Outliner colors or the scene's Undo history. Duplicate joint names are
resolved using cached full DAG paths stored on the rows. No scene objects are
created to display the tree. If the skin hierarchy has no readable joints, the dock
explains that state instead of staying blank. Use Refresh after scene renaming
or reparenting, or after adding unbound descendants, to rebuild the tree from
current paths. Changed influence UUIDs/paths also trigger rebuilding on refresh.

Selection does not register a joint or edit the scene. A completed changed
weight stroke adds membership automatically. A previously unbound joint is first
added to the native skinCluster at zero weight, preserving existing weights and
remapping all saved buffers by influence UUID. Binding, membership and the stroke
form one Undo step; Undo removes the new influence and weights while retaining
the scene joint. Canceling a stroke, activating the brush without painting, or
painting zero over an untouched unbound joint creates no influence or membership.
Failed binding/paint transactions roll back their own additions. Existing locks
and references remain respected; the tool does not lock or unlock attributes.

## Paint weights and masks

No material, texture file or UV assignment is required for Layer Skin painting.
It edits per-vertex layer values through Artisan's Paint Scripts context. Use
**Paint in the Layer Skin window** to activate it. Maya's Texturing > 3D Paint
Tool paints material textures and has a different setup.

Select an editable layer, a joint in the right hierarchy for weight painting, and **Weights** or
**Mask**. Set **Value**, **Brush radius** and **Opacity**, then click **Paint**.
Drag on the mesh using Maya's native Artisan brush. This prototype uses Replace;
set Value to 0 to erase. A completed stroke becomes one layer command and one Undo
step. Native grayscale brush feedback updates during the stroke; actual
skinCluster weights commit when the stroke is released.

- **Weights** edits the selected joint's authored contribution to this layer.
  Choose any hierarchy joint; no separate membership action is required.
  For a layer with one joint, painting 0.4 produces that joint's distribution with
  coverage 0.4, blending over the layers below. Erasing reveals lower layers.
  With multiple authored joints, lowering one preserves the others; values above
  the remaining budget proportionally reduce the other contributions.
- **Mask** controls where this layer contributes, independently of its weights.
  White is 1 (show the layer), black is 0 (reveal layers below), gray is a blend.
  An unspecified mask value is 1. A new empty layer is transparent until it has
  weight samples, even though its mask is white.
- **Mask → Paint** displays the current layer mask automatically; no separate
  Show mask toggle is needed. Base's white mask is available as a read-only preview.
- **Show final skin weights** displays the selected joint's actual native
  skinCluster weights in grayscale. It works on Base preview before adding a
  layer and follows joint changes. It is read-only and does not bind unbound
  joints; an unbound joint displays zero. Click Paint to return to layer editing.
  This view and Mask painting are mutually exclusive. Black is 0 and white is 1.
- **Stop / shaded view** restores the previous tool and disables this context's
  grayscale feedback after saving valid pending edits. Switching joints, layers,
  modes or views also saves pending edits before changing their target. A failed
  save reports rejection and stops the action. Choosing a joint during mask
  painting leaves that mask active. Undo/Redo, scene replacement and dialog
  teardown explicitly discard pending previews and cancel deferred writes.

Artisan paints the transient native array directly. Python reads it at release,
then applies one layer command; there is no Python callback per dab or vertex. If metadata changes while painting, the unfinished stroke
is rejected rather than overwriting another edit.

### Paint appears while dragging, then disappears

The brush preview is temporary until its layer command succeeds on release.
A Maintain Max Influences warning rejects that stroke before its weights are
saved. Turn that skinCluster setting off yourself before painting again; the
tool never changes it or unlocks influences automatically. In 0.3.7, the next
gesture can recover without reopening Paint.

When changing actions, the mask or joint values should return unchanged when
you reopen that view. Feedback reloads explicitly and the loaded range
appears beside Show final skin weights. For example, a saved mask containing
0.25 and 1.0 shows **Values 0.25–1.00** after stopping and reopening Mask → Paint.
Paint info retains the previous verified save receipt even after switching
views. Compare its mesh/layer/joint with the current view when diagnosing a
black viewport; the receipt may describe a different joint or mode.

Check the status after release. **Stroke saved** means the requested layer
values were read back successfully; **Stroke rejected** explains the failure.
**Paint info** reports the stored-value check separately from viewport feedback.
If a saved stroke still displays black, include that report when diagnosing the
display. Show final skin weights reads the composite; Paint displays the selected
layer. Mask, Alpha and higher layers affect the composite without erasing saved
layer paint.

### Red X / brush troubleshooting

1. Select a skinned polygon mesh, click **+**, and select an editable layer.
2. Choose **Mask**, set Value 0 and Opacity 1, then click **Paint** in this window.
   A new mask defaults to white (1), so painting Value 1 over it has no visible
   effect. Paint mode shows the mask automatically while editing it.
3. Weight painting requires an active joint chosen in the hierarchy; membership
   and binding are handled automatically when a changed stroke is committed.
   Mask painting does not require a joint. Base can only be viewed.
4. If an X still appears, click **Paint info** and inspect the Script Editor.
   `active_context` should equal `layer_skin_context` (`rtkLayerSkinPaint041`).
   `whichTool` should be `userPaint`, `stampProfile` should be `gaussian`, and
   outline/color feedback should be enabled. The report includes the actual
   registered plug-in version/path, selected paint surface, callback settings,
   native paint-node query, display source/range and last callback error.
   It does not start a stroke, read all skin weights, change selection or
   commit a pending edit. Unsupported query flags are reported separately.

An X in Maya's **3D Paint Tool** can mean that its material attribute has no file
texture assigned. That is a texture-paint requirement, not a setup step for this
layer mask. Click Layer Skin's Paint button to activate the intended context.
An X by itself does not establish which tool or callback failed; use Paint info.
Starting this brush enters object mode and selects the loaded mesh transform.

For numeric edits, select Weights or Mask, set a group's value and click its
**Execute** button. **Whole mesh** is an explicit separate checkbox;
otherwise these operations require selected vertices. **Clear paint edits**
removes manual weight overrides in that scope, exposing generated samples if
present; masks are retained. **Inspect selected influence weights** reports
min/max/mean from the actual skinCluster, using the same flood scope checkbox.

## Generate and rebuild

In the right hierarchy dock, select one or more joints and choose a Method enum
under **Assign weights**. **Assign selected joints** registers those joints if
needed, then generates weights using only that selection, as one Undo step.
It replaces generated samples and manual paint/Flood/Relax overrides inside
the chosen vertex scope by default, while keeping masks and vertices outside
that scope. Check **Preserve painted / flooded edits** to keep manual overrides;
these can hide newly generated weights. **Rebuild layer** preserves manual
overrides and instead generates using
every joint already used by the layer. Use it to redistribute weights across
all previously painted/assigned joints with the current method/settings.

| Method | Ownership rule |
| --- | --- |
| Distance to joint | Closest selected joint's frozen pivot. |
| Distance to bone | Closest finite segment to any nearest joint child, including children under buffers. A leaf uses its pivot. |
| Joint axis | Closest bone first; positive local-axis preference resolves distance ties, followed by logical depth and UUID. Negative-side vertices remain assigned. |

All methods give one selected influence weight 1 with generated coverage 1.
There is no assignment Radius, Length or Falloff. Use masks, alpha, paint and
Relax to shape the resulting distribution. A preserved manual override takes
precedence over the new generated row; locks can preserve existing layer
contributions. A lower-layer contribution can therefore remain in the final
skin weights even though the generated assignment covers that vertex.

**Scope** explicitly chooses Whole mesh or Selected vertices. Rebuilding a
selection replaces generated samples only in that scope. Manual painted
samples and masks survive Rebuild. Assign replaces manual samples in its scope
unless **Preserve painted / flooded edits** is enabled.

The first valid assignment freezes the actual **skinCluster input geometry**
and matching bind-space joint frames, including captured unbound descendants.
Bound joints use inverse bind-pre matrices; unbound joints use captured offsets
beneath bound ancestors or relative to the mesh. Older posed references migrate
on explicit Assign. See [PREDEFORM_REFERENCE.md](PREDEFORM_REFERENCE.md).

**Recapture reference** explicitly refreshes that snapshot. It leaves current
weights, generated data, paint and masks intact until the next assignment or
rebuild. A joint created after capture, or missing from the captured roots,
requires recapture before generation. Painting does not need that reference.

Reference contents, influence UUID order, selected joints, method/axis and scope
identify cached results. Identical assignments reuse generated rows without
repeating nearest-distance tests. Changed scopes can reuse the joint/bone
index. **Clear assignment cache** drops transient caches, leaving saved layers
and reference intact. Generation checks Escape and has a 120-second computation
budget before skin writes. No global Maya progress window is opened.

## Composition, storage and playback

The tool uses **one skinCluster**. Layers are weight data with masks/opacity;
they are composed into that skinCluster's final influence weights. A skinCluster
for every layer would form a stack of deformers, a different deformation model.
The paint cursor and grayscale feedback belong to Artisan's context and do not
require additional skinClusters. This prototype currently accepts exactly one
skinCluster in the loaded mesh history.

Each layer stores generated samples, manual overrides, membership, sparse masks,
opacity and enabled state. A sample holds a normalized joint distribution and
coverage. Manual overrides take precedence over generated samples for that vertex.
For each layer, `alpha = opacity * mask * coverage`; composition is
`(1 - alpha) * below + alpha * layer`, from Base upward. Lower layers remain live
when an upper painted layer has partial coverage.

The authoring command computes changed rows and writes those rows to the native
skinCluster through OpenMaya. Weight Undo buffers store only changed rows.
Changing layer order/alpha/enable state recomposes affected vertices. Full bulk
weight reads and validation still protect against external edits; this is not a
constant-time operation on large meshes.

The layer stack runs during explicit editing. Animation plays through the native
skinCluster without Python layer evaluation, expressions, frame callbacks or a
custom deformer. This implementation does not add a runtime solver node.

Compressed, versioned JSON is stored on one normal network node connected by
message attributes to the mesh and skinCluster. Save/reopen the Maya scene, load
the plug-in and select the mesh to continue. Schema 1 data from 0.1/0.2 remains
readable; the next edit saves schema 2. Keep 0.3.6 for these edited scenes.
Joint renames/reordering resolve by UUID. Removing a joint that has saved weight
is rejected; changed topology is also rejected.

Selection, Undo/Redo and scene-change listeners belong to the visible window.
A single-shot Qt timer coalesces UI refresh requests; there is no polling timer
or scriptJob. Hiding/closing removes listeners. Close/deletion releases browser
and paint resources. The Maya-exit handler drops callbacks and Python buffers
without switching tools or deleting native UI during teardown.

## Remove saved layers or restore

- **Cleanup… → Remove saved layers · keep current skin** preserves the current
  native weights and removes the owned authoring nodes after inspection.
  The skinCluster continues deforming without Layer Skin. See CLEANUP_GUIDE.md.
- **Restore original** restores Base weights and removes authoring data. It does
  not restore joint transforms or remove newly bound influences; their Base
  columns are zero.
- Both actions are undoable. Their dialogs describe the requested finish action.
  Do not manually delete the network node to restore weights.
- External skin edits are detected before another layer edit. To keep them,
  use Cleanup → Remove saved layers, then click + for a fresh Base. Restore original explicitly replaces
  them with the captured Base instead.

## Demo and native verification

Load the plug-in first, then run:

```python
import sys
sys.path.insert(0, r"D:/dev/MayaZone/layer_skin_prototype")
import maya_layer_skin_demo

demo = maya_layer_skin_demo.make_demo()
```

The demo creates its own plane and two independent joints in a unique namespace.
It selects the mesh and leaves your existing scene intact. Click +, add
`right_JNT` to the layer and paint Value 1. Moving that joint should deform the
painted region. Mask 0 should reveal Base there; alpha 0.5 should blend it halfway.
The demo intentionally disables Maintain Max Influences on its own skinCluster.

Run the included automated Maya checks individually:

```python
maya_layer_skin_demo.run_array_feedback()
maya_layer_skin_demo.run_smoke()
maya_layer_skin_demo.run_authoring()
# Deliberately omit begin/end callbacks; test native save-before-switch.
maya_layer_skin_demo.run_capture_recovery()
# Close the existing Layer Skin window before the GUI lifecycle check:
maya_layer_skin_demo.run_ui_lifecycle()
```

These scripts create/clean their own temporary namespace, restore selection and
do not open a new scene. They check native weights/Undo, auto Base, the legacy MEL scalar
paint bridge, cached assignment, paint preservation, influence addition and
repeated UI opening/closing. **They have not been run in this environment.**
Also manually test real brush gestures, grayscale feedback, joint-tree navigation,
save/reopen persistence and closing Maya with the window/paint tool active.

## Limits and local verification

- Python 3 Maya; array/API contracts were checked against Autodesk documentation,
  including Maya 2024 (the version in the supplied trace).
  Native compatibility across Maya/PySide versions remains unverified.
- Exactly one skinCluster and one non-instanced polygon mesh; fixed topology.
- Skin weights must be nonnegative and normalized. Painting/Relax leaves native
  DQ blend weights intact; Utilities can explicitly import DQ and skinning method
  as skin-wide settings, independently of layer opacity. Do not layer this over
  another active layer-skinning tool.
- Locked/referenced/driven data is rejected. Influence locks are respected.
  Disable **Maintain Max Influences** yourself when edits change weights.
- Packed-buffer budget: 1024 MiB per dense buffer, and 32 editable layers.
  Base is dense; generated/manual samples are sparse. Large Undo histories and
  reference snapshots still consume memory. Cache limits are estimates, not a
  hard limit on total Maya process memory.
- Assignment cache: up to 8 entries with an estimated 64 MiB budget; decoded
  state cache: up to 3 states with an estimated 64 MiB budget. The expected-output
  cache is separate and retains at most one eligible result.
- One-ring weight Relax, Shift-mask smoothing and final-skin file import/export
  are implemented. Files do not serialize the editable layer stack. Mirroring,
  merge-down and layer groups remain outside this prototype. This is a standalone
  package; the main Master Rigging Toolkit is not modified by this release.

The included suite covers pure composition/assignment/Relax, serialization,
recording-API command transactions, callback/session lifecycle, real Qt gesture
routing and UI refresh. All Python files parse with Python 3.10 syntax. See
VALIDATION.md for current counts, limits and the native Maya test checklist.

```text
python -m unittest discover -s layer_skin_prototype -p 'test_layer_skin*.py' -v
```

Qt tests need PySide2 or PySide6 and otherwise skip. No extra Qt installation is
needed inside Maya. The package includes the full local test log.

Implementation references:

- https://help.autodesk.com/cloudhelp/2022/ENU/Maya-CharEffEnvBuild/files/GUID-048A5F9C-FA4F-4F4C-A15A-5054F9C3FD1A.htm
- https://help.autodesk.com/cloudhelp/2024/ENU/MAYA-API-REF/py_ref/class_open_maya_1_1_m_fn_dependency_node.html
- https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/artUserPaintCtx.html
- https://help.autodesk.com/cloudhelp/2015/CHS/Maya-Tech-Docs/PyMel/generated/functions/pymel.core.general/pymel.core.general.artAttrTool.html
- https://help.autodesk.com/cloudhelp/2024/ENU/Maya-CharacterAnimation/files/GUID-54F26F2A-A512-44DB-9B8C-EAED0AD80664.htm
- https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QTreeWidget.html
- https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/skinCluster.html
- https://help.autodesk.com/cloudhelp/2026/ENU/MAYA-API-REF/py_ref/class_open_maya_anim_1_1_m_fn_skin_cluster.html
- https://help.autodesk.com/cloudhelp/2026/ENU/MAYA-API-REF/py_ref/class_open_maya_1_1_m_px_command.html

Geometry binding references:

- https://forum.highend3d.com/t/painting-doublearray-attribute-with-artisan/38016
- https://help.autodesk.com/cloudhelp/2024/ENU/MAYA-API-REF/py_ref/class_open_maya_1_1_m_fn_generic_attribute.html
