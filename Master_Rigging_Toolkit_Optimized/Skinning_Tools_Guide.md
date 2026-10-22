# Skinning Tools — toolkit 2.26 · plug-in 0.4.3

The supplied MEL Nudge Skin tool has been converted to Python and merged with
Copy Skinning under **Skinning Tools** in the main toolkit. Use the **Weight
Editor** and **Copy Skinning** tabs. Related options inside each tab can collapse.
The separate legacy **Skin weights** page still contains the existing namespace
transfer workflow.

## Update 0.4.3 — Tasks and progress recovery

Open **Skinning Tools → Tasks** to inspect tracked operations and the current
Maya progress window. The table shows operation, state, stage and elapsed time;
select an active row for checkpoint age, or any row for its full error/result. It retains the 20
most recent finished tasks, plus the active task. Copy, Preview, vertex selection,
mesh loading, influence matching and Weight Editor calculations have names in
their native progress-window titles. Copy and Weight Editor writes remain tracked
through verification and rollback.

| Control | Behavior |
| --- | --- |
| Refresh | Read task records and native progress metadata. No geometry reads. |
| Cancel | Request cancellation of the selected tracked calculation at a checkpoint. |
| Force stop / reset | For tracked calculations, request cancellation and cleanup at the next checkpoint. For an untracked Maya progress row, close only its progress UI when no tracked task is active. |
| Clear history | Remove finished records, keeping any active task. |

Maya does not provide a complete registry of arbitrary running scripts. Untracked
progress is labeled **Owner unknown**, with Maya's available title/status and an
unknown elapsed time. A missing checkpoint is not proof that a task is dead.
Force Stop does not kill arbitrary scripts, threads or Maya itself. A native Maya
call must return before Python can observe cancellation. Stop controls are disabled
during atomic weight writes, verification and rollback. Reset never releases a
tracked task early, and rechecks the selected native progress before closing it.

The task list refreshes every 500ms only while its tab is visible and Maya's event
loop is responsive. No worker thread calls Maya and no Qt/idle event pump is added.
Use Escape during synchronous calculations if UI buttons do not respond. Completed
or failed records remain inspectable after the operation returns. Progress creation
failures now say that creation failed, rather than asserting another task exists.
The Tasks view can inspect/reset progress even if the registered plug-in is older;
copy/edit actions still enforce the required version.

Replace the complete folder, including new **skinning_tasks.py**, save and restart
Maya for plug-in **0.4.3**. There are now eight implementation modules. 306 local
skinning tests pass, including 28 task/recovery tests. Real Qt6 checks cover task
listing, cancellation button dispatch, unknown progress reset, atomic stop disabling,
history and timer cleanup at 540px and 780px widths. Native Maya verification remains
pending; `maya_copy_skinning_smoke.run_tasks()` supplies native checks.

## Update 0.4.2 · unskinned source loading

Load checks for skinning before evaluating mesh geometry. Bare unskinned meshes
are rejected before progress starts; history-only meshes use a bounded,
cancellable OpenMaya plug walk before geometry and cache preparation. Invalid
sources never populate the geometry cache or bind themselves. The mesh status
shows Load failed, details display the reason, and cleanup releases the panel
and owned progress window. Select a skinned mesh as source; an unskinned target
can be bound with **Prepare target / refresh mapping**.

Load respects the calculation budget; discovery also has a 10,000-plug/120-second
limit. Native Maya calls must return before cancellation can be observed. Replace
the complete folder and restart Maya for plug-in **0.4.2**. 278 local regressions
pass. Native Maya verification, including `run_unskinned()`, remains pending.

## UI update · backend 0.4.1

The two tools now have separate tabs, so the editor no longer pushes Copy Skinning
below a long page. The standalone window opens at 780 × 860 and both tools scroll
their settings independently. Layout was checked at 540px and 780px window widths
using real PySide6 widgets with Maya calls stubbed. Native Maya and PySide2 visual
verification remain pending.

**Weight Editor:** mesh and scope are grouped at the top, followed by the influence
table and Set/Nudge controls. **Selection and Hold**, **Clipboard and cleanup**,
**Mirror weights**, and **Maya tools** are collapsible. The table has alternating
rows and a name column that expands. **Action details** replaces the large empty
report; errors open it automatically. Scope, Hold modes and all existing actions
keep their previous meaning.

**Copy Skinning:** load source and target in **Meshes**, choose method, sample
geometry and strength in **Transfer settings**, then use the fixed bottom action
bar. Preview, Select preview vertices and Copy skinning remain visible while the
settings scroll. **Mesh setup and cache** contains target preparation, Refresh
meshes and Clear cache. Limits, topology verification, DQ and explicit base
references are under **Advanced transfer options**. Method-specific masks appear
only when selected. Influence mapping still opens automatically for unresolved
rows. **Transfer details** shows the full result; the compact status shows the
outcome and changed counts. Mesh input plug paths are available as tooltips.

The earlier UI-only update shipped with backend 0.4.1. The current package
requires 0.4.2; replace the complete folder and restart Maya.

## Install and open

Replace the complete extracted folder. Keep all eight implementation modules
together: `skinning_ui.py`, `skinning_backend.py`, `skinning_core.py`,
`copy_skinning_ui.py`, `copy_skinning_plugin.py`, `copy_skinning_core.py`, and
`copy_skinning_cache.py`, and `skinning_tasks.py`.
Save your scene and restart Maya if an older plug-in has been loaded; the UI
requires registered plug-in **0.4.3**. Do not force-unload a command that still
owns Undo history. No C++ build or external numerical package is required.

From the full toolkit:

```python
import sys
sys.path.insert(0, r"D:/dev/MayaZone/Master_Rigging_Toolkit_Optimized")
import master_rigging_toolkit
master_rigging_toolkit.show()
```

Choose **Skinning Tools** in the sidebar. The navigation search accepts nudge,
hold, prune, mirror, clipboard and the existing copy-skinning keywords.

From the separate package (the historical ZIP/folder name is retained):

```python
import sys
sys.path.insert(0, r"D:/dev/MayaZone/Copy_Skinning")
import skinning_ui
skinning_ui.show()
```

The previous `copy_skinning_ui.show()` launcher now also opens the combined
Skinning Tools panel. Direct `CopySkinningPanel` embedding remains available.

## Copy Skinning: Preview and Select waiting fixes (0.4.1)

Preview and Select skip Copy's Undo snapshots and per-weight write checks.
Select reuses a read-only result only after validating current scene inputs,
then selects up to 5,000 changed vertices in one native component operation.
Copy still recalculates its write data and checks locks/drivers with batched
queries before writing. Preview reports those write checks as deferred.

Progress now remains owned through selection, writes, verification and rollback.
Escape is checked with Maya's native interrupt monitor. The new **Calculation
time limit (seconds)** defaults to 120; **0** means unlimited. Python can observe
Escape or timeout only after a native Maya call returns. The reported native
hang remains unverified here; a blocked native call cannot be forcibly stopped.

## Copy Skinning: simpler loading and caching (0.4.0)

Load the visible source and target deformed meshes. **Pre-skin** automatically
resolves their evaluated skinCluster input geometry; manual Orig selection is
unnecessary. The default is closest-surface copying. Influence mapping stays
collapsed unless a row needs attention, and optional base overrides are advanced.

Load warms reusable geometry and the source search index. Preview and the
registered Copy command share an LRU cache of geometry, indices and vertex
correspondence (12 entries / estimated 128 MiB). Before use, evaluated positions,
topology, identities and world matrices are validated. Current deformation or
upstream pre-skin edits refresh only affected data. Weights, masks, influence
mapping stay fresh; Copy reads current locks and creates fresh Undo snapshots. Validation still evaluates
Maya geometry; no per-frame callbacks or API object handles are cached.

Use **Refresh meshes** or **Clear cache** when needed. See
**Copy_Skinning_Guide.md** for exact cache keys, pre-skin semantics and limits.

## Weight Editor workflow

1. Select vertices, edges, faces or one skinned polygon mesh; click **Get mesh**.
2. **Current component / object selection** reads the active selection whenever
   you apply an action. Selecting the loaded mesh object means all its vertices.
   Empty selection does not silently edit the whole mesh. **Whole loaded mesh**
   is an explicit alternate scope, independent of the active selection.
3. Select one or more influence rows. **Load all** includes unweighted influences;
   otherwise only influences contributing to the inspected vertices are listed.
4. Use **Set total**, a preset or **Nudge −/+**. **Blend strength** mixes the
   calculated edit with the old row. One weight action is one Maya Undo step.

The table shows average influence weights over the inspected vertices and the
current Hold state. The selected combined average is displayed below the list.
Click **Refresh** after changing selection or using Undo/Redo. **Refresh after
actions** refreshes after edits and Hold changes. No selection scriptJobs,
timers, per-frame callbacks or automatic Maya selection changes are installed.

**Filter influence name** searches full DAG paths. **Include joint neighbors**
adds immediate parent/child joints only if they already influence this skin.
**Show selected joints** adds existing bound joints to the displayed list;
**Hide rows** removes only list entries. Neither adds/removes skin influences.
After selecting joints, reselect mesh components before editing in current
selection scope.

## Set / Nudge and normalization

With one influence selected, Set controls that influence's weight. With several
selected, Set controls their **combined total**, preserving their existing
relative ratios when possible. This avoids applying the same value to every
selected influence and accidentally exceeding a total of one.

For example, `[.1, .2, .7]` with the first two influences selected and Set `.6`
becomes `[.2, .4, .4]`. Nudge adds/subtracts from that combined total. It clamps
to the budget left by held influences. Remaining unlocked influences receive
the remaining weight in proportion to their old values. If an eligible group
has zero old weight, its share is divided equally.

Held values remain exact. If the selection contains held influences, their
fixed values count toward the selected total. If every selected influence is
held, editing stops and asks you to unhold explicitly. If all unlocked
influences are selected, their total cannot be reduced without somewhere to put
the remainder; the operation stops rather than silently dropping weight.

Input rows must be finite, nonnegative and normalized (sum approximately one).
Target **Maintain Max Influences** must be off, as in Copy Skinning, so Maya
cannot silently change the calculated columns. Referenced/locked targets,
driven weight plugs and an active Layer Skin stack are rejected before writes.

## Hold and selection controls

Hold, Unhold and Toggle are **explicit** actions. Their scope can be selected
rows, all other influences, visible rows or all skin influences. No weight edit
automatically changes a Hold state. Each Hold action uses one native Undo
chunk and preflights the affected attributes first. The joint's standard
`lockInfluenceWeights` attribute is used, so it can affect other skins using
that same joint, matching Maya's normal influence-lock behavior.

**Select joints** selects the listed influences. **Select affected**, **Add
affected**, and **Deselect affected** operate on loaded-mesh vertices with
nonzero weights for the selected rows. **Influence set** creates a uniquely
named set containing all this skin's influences; it does not delete an existing
set with the same requested name. **Component Editor** and **Paint Skin Weights**
open Maya's native UI.

## Vertex copy/paste, averaging, smoothing and prune

| Action | Behavior |
| --- | --- |
| Copy vertex weights | Copies the arithmetic mean of the scoped vertices to the panel's in-memory clipboard. It divides by the actual vertex count, fixing the averaging issue in the MEL source. |
| Paste average | Applies that distribution to each scoped vertex. Nonzero clipboard influences must map by UUID or unique exact name (namespaces ignored). Missing/ambiguous influences stop the edit. Held destination weights remain fixed; unlocked pasted values are fitted to their remaining budget. |
| Average boundary | Finds the one-ring vertices outside the selected region, computes their common mean and applies it to the selection. A selection without an outside boundary reports an error. |
| Smooth / Hammer | One pass of uniform one-ring neighbor averaging, per selected vertex, using one original snapshot. Adjacent edits do not depend on processing order. This is a documented replacement, not an exact reproduction of Maya's proprietary Weight Hammer command. |
| Prune | Zeros unlocked values below the threshold and redistributes the unlocked budget. Held tiny weights remain intact. If all unlocked candidates would be removed, the greatest old unlocked influence receives that budget. |

**Blend strength** applies to every weight edit, including smoothing and mirror.
No clipboard or panel field state is saved into the scene. Recopy after closing
or rebuilding the panel. Undo restores written weights, not the clipboard.

## Mirror weights

Expand **Mirror weights**. Choose the world-origin plane (YZ/XZ/XY), source side
(positive → negative or negative → positive), name tokens and geometry mode.
For example, default `_L ↔ _R` swaps side influences while untagged center
influences keep their own columns. Name matching uses the leaf including its
namespace; side partners must be unique, reciprocal and one-to-one. Missing or
ambiguous partners stop the operation before writes.

Only vertices on the destination side within the current scope are changed;
source-side and center-plane vertices remain unchanged. Each destination point
is reflected across the chosen world-origin plane. The closest point on the
triangulated mesh supplies barycentric interpolated weights, then influence
columns are swapped and held values preserved. The sample comes from one
unchanged weight snapshot. No joint or mesh transform is modified.

Use **Pre-skin** for the evaluated geometry entering the skinCluster, or
**Current** for the visible deformed positions. Upstream tweaks/deformers are
included in the pre-skin input; no unconnected Orig shape is required.
An explicit base mesh override must preserve vertex IDs/connectivity. Base-mode
validation is the same as Copy Skinning. The mirror plane is fixed at world
origin in this version; put the character's symmetry plane there or use another
workflow for an offset plane. There is no automatic joint creation or influence
rebinding.

## OpenMaya implementation

The core weight path uses Python API 2.0:

- `MFnSkinCluster.getWeights` reads a bulk component × influence buffer.
- `influenceObjects()` order defines physical weight columns; UUIDs preserve
  meaning if an influence list is reordered. Bind-matrix logical indices are
  never substituted for physical weight indices.
- `MSelectionList`, component function sets and mesh iterators resolve scopes,
  adjacency and affected vertices without converting selection through MEL.
- `MFnSkinCluster.setWeights(..., normalize=False)` writes changed rows in bulk.
- The shared `rtkCopySkin` MPxCommand retains before/after rows for Undo/Redo and
  restores the old snapshot if a write or verification fails.

Weight arithmetic and triangle searches are Python; OpenMaya performs scene
access and bulk writes. Small `maya.cmds` operations handle metadata, explicit
Hold changes, object sets, UI launchers and progress. There is no per-vertex
`skinPercent` query/write loop and no MEL evaluation for weight editing.

The existing four-million vertex × influence value guard remains. Whole-mesh
averages stream over the stored rows instead of building a second full table.
Copy Skinning's owned progress cleanup and Escape cancellation are retained for
editor operations. Python loops cooperate with cancellation; a native Maya API
call must return before a pending cancel can be handled. No Qt/idle event pump
or worker-thread Maya API call is introduced.

## Verification

306 skinning tests pass (62 editor, 115 Copy Skinning, 41 cache, 40 Preview/Select actions, 20 unskinned Load, 28 tasks).
The unchanged main toolkit previously passed 380 regressions.
Local math/orchestration tests cover row budgets, held values, multi-influence
totals, clipboard averages, prune, snapshot smoothing, mirror correspondence,
scope conversion, stale UUIDs/topology, explicit Hold rollback, command dispatch
and navigation. The existing Copy Skinning and toolkit regressions are also run.
These tests use fakes for scene interfaces and do not validate Maya/Qt internals.

Inside Maya, with the complete folder on `sys.path`, run:

```python
import maya_skinning_smoke
maya_skinning_smoke.run()

import maya_copy_skinning_smoke
maya_copy_skinning_smoke.run()
maya_copy_skinning_smoke.run_mapping()
maya_copy_skinning_smoke.run_progress()
maya_copy_skinning_smoke.run_cache()
maya_copy_skinning_smoke.run_actions()
maya_copy_skinning_smoke.run_unskinned()
maya_copy_skinning_smoke.run_tasks()
```

The native editor test creates and cleans its own temporary namespace. It checks
real component scopes, average clipboard, edits, held values, smoothing, pruning,
mirror and Undo/Redo. It never opens/replaces the current scene. Native Maya,
PySide layout, actual Escape input and cursor behavior have **not been executed
in this environment**.

API references:

- https://help.autodesk.com/cloudhelp/2026/ENU/MAYA-API-REF/py_ref/class_open_maya_anim_1_1_m_fn_skin_cluster.html
- https://help.autodesk.com/cloudhelp/2026/ENU/MAYA-API-REF/py_ref/class_open_maya_1_1_m_fn_single_indexed_component.html
- https://help.autodesk.com/cloudhelp/2026/ENU/MAYA-API-REF/py_ref/class_open_maya_1_1_m_it_mesh_vertex.html
- https://help.autodesk.com/cloudhelp/2026/ENU/MAYA-API-REF/py_ref/class_open_maya_1_1_m_global.html
