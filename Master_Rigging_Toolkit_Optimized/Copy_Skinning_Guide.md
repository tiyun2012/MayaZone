# Copy Skinning — toolkit v2.26 · plug-in 0.4.3

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

## Update 0.4.2 — reject unskinned sources before geometry evaluation

An unskinned mesh is not a valid copy source. Previously, source loading attached
`MFnMesh` before checking for a skinCluster, which could evaluate geometry before
the invalid source was rejected. The revised path checks mesh wiring first:

- A mesh with no incoming `inMesh` connection is rejected before a progress
  window or interrupt monitor starts. No mesh geometry, weights or cache is read.
- With construction/deformer history, an unfiltered OpenMaya upstream plug walk
  checks for skinClusters before `MFnMesh`, skin input evaluation or cache building.
  It checks Escape/time limits between steps and stops after 10,000 visited plugs
  or 120 seconds, independently of the general calculation budget. Unknown history
  nodes and multiple skins fail with explicit errors.
- A failed Load marks the mesh as failed, clears the Preview result and displays
  the error in details. Progress and busy state are released through cleanup.
- Load now uses the Calculation time limit setting. A native Maya API call must
  return before Python can observe cancellation or a timeout.

Use a source mesh that already has skin weights. **Prepare target / refresh
mapping** can bind an unskinned target; Load never binds the source automatically.
Replace the complete folder, save and restart Maya to load **0.4.2**.

278 local skinning tests pass, including 20 tests for unskinned loading, discovery
limits, ordering and cleanup. The reported native Maya hang remains unverified
in this environment. Run `maya_copy_skinning_smoke.run_unskinned()` inside Maya
for bare/history-only source rejection and a valid skinned retry.

## UI update · easier access to Copy Skinning

Open **Skinning Tools → Copy Skinning**. It now has a separate tab beside Weight
Editor. Meshes and essential transfer settings appear first. **Mesh setup and
cache** holds Prepare target / refresh mapping, Refresh meshes and Clear cache.
**Advanced transfer options** holds distance/time limits, topology verification,
DQ and optional base references. Masks appear for the Faces / painted masks
method, and the influence map remains collapsible and editable.

Preview, Select preview vertices and Copy skinning stay in a fixed bottom bar
while settings scroll. A compact status shows the result and changed counts;
expand **Transfer details** for the full report. Errors open details automatically.
The skin input path is in each loaded mesh's tooltip. The UI redesign shipped with backend 0.4.1; the current package requires 0.4.2.
Replace the complete package and restart Maya to load both updates.
Real Qt6 layout and signal checks pass at 540px and 780px widths; native Maya
visual verification remains pending.

## Update 0.4.1 — Preview and Select waiting fixes

Preview and Select now use a read-only calculation. They do not allocate Copy's
before/after Undo buffers or inspect individual target weight plugs. The report
marks write checks as deferred; **Copy** always checks current locks, drivers,
held influences and other write restrictions before changing weights. Lock and
incoming-connection inspection is batched instead of creating a Python MPlug for
every vertex/influence pair.

**Select preview vertices** validates live geometry, weights, influence mapping,
masks and DQ values before reusing an unchanged Preview summary. Changed inputs
invalidate it. It selects up to 5,000 changed vertices with one native API
component selection; the full changed count and subsequent Copy remain uncapped.
Only the small immutable report is cached, without Maya objects or Undo buffers.

Progress remains open through native selection and Copy's write, verification
and rollback. Cleanup runs on success, errors and cancellation. Escape uses
Maya's native interrupt monitor as well as the progress-window flag, without
adding another wait cursor. Cancellation stops before the atomic weight write.

**Calculation time limit (seconds)** defaults to **120**; set **0** for unlimited.
This limits cooperative calculation work. A single native Maya evaluation or
selection/write call must return before Python can react to Escape or a timeout;
this cannot forcibly interrupt a blocked native Maya call.

Local regression tests cover these changes. The reported hang has not been
reproduced in Maya in this environment. Replace the complete folder and
save/restart Maya to load plug-in **0.4.3**, then test Preview and Select on the
problem scene. `maya_copy_skinning_smoke.run_actions()` supplies native checks.

## Update 0.4.0 — load deformed meshes, automatic pre-skin input and shared cache

1. Select the visible **deformed source mesh**, click **Load selected**.
2. Select the visible **deformed target mesh**, click its **Load selected**.
3. Leave **Pre-skin · detect skin input automatically** selected, or choose
   **Current · visible deformed meshes**. Click **Preview** or **Copy**.

There is no need to find an Orig/intermediate shape manually. Pre-skin mode reads
`skinCluster.input[logicalIndex].inputGeometry` as evaluated mesh data at the
loaded output shape's index. It includes upstream tweaks and deformers and
excludes this skinCluster and anything after it. An upstream animated blendShape
therefore still affects pre-skin geometry. This is the exact input to the skin,
not a guarantee of the original bind pose. For a separate bind/rest reference,
expand **Use explicit pre-skin mesh overrides · advanced**.

The default copy method is closest surface. Influence mapping is automatic and
collapsed until a missing/ambiguous joint requires attention; the editable table
remains available. Method 3 alone shows its face/mask controls. If the target is
unskinned, bind it using Prepare target; loading never silently changes binding.

### What is cached

- **On Load:** shape/skin identity and topology are validated, pre-skin or current
  geometry is sampled, and source triangles/search index are prepared when they
  fit the cache budget. The target geometry is cached without building a second
  unused search index. Vertex-ID mode skips geometry sampling entirely.
- **Across Preview / Copy:** world points, triangle lists, source search indices
  and target vertex correspondence can be reused. The panel helper and the
  registered command share the same session service, so Copy can use Preview's
  cached correspondence.
- **On changed geometry:** evaluated local points, connectivity, skin/mesh UUIDs,
  geometry mode and world matrix are checked on use. Changed current deformation,
  object transform, upstream pre-skin geometry or binding produces a different
  key. A source change rebuilds its index and dependent correspondence. A target
  change recomputes correspondence while retaining the source index when valid.
- Source face restrictions, painted source masks and mask threshold belong to
  the source-index key. Target scope and maximum distance belong to correspondence
  keys. Black target vertices/zero strength are tracked as not yet queried, so
  later mask or strength changes can sample them correctly.
- **Always fresh:** skin weights, influence order/mapping, DQ weights, masks,
  target locks/drivers and the before snapshot for Undo on Copy. Painting and Undo/Redo
  cannot leave stale skin weights in the geometry cache. Undo retains only its changed rows and write context, not evaluated input
mesh data or whole-mesh read buffers.

Validation is performed on Load, Refresh, Preview and Copy, rather than every
frame. Reading evaluated points/connectivity and hashing them still costs time;
the cache removes repeated world conversion, triangulation, BVH build and
closest-point search when inputs agree. It does not skip scene validation or
Maya dependency-graph evaluation. Python validation/hashing loops support Escape;
a single native Maya API evaluation must return before cancellation is observed.

The session LRU is bounded to **12 entries and an estimated 128 MiB**. Large
entries can be processed without retention; Load avoids warming a source index
that cannot fit. Estimates include Python geometry/index/hit payloads and are
not a guarantee for total Maya process memory. Weight buffers and Undo snapshots
are separate. There are no persistent Maya node handles, dirty callbacks,
scriptJobs, timers or cached progress callbacks in the shared service.

**Refresh meshes** explicitly validates the active mode again. **Clear
cache** discards session snapshots; Preview/Copy rebuild as needed.
Mode changes refresh loaded meshes automatically. Cache statistics appear in
the transfer report. Save/restart Maya after replacing the complete **0.4.2**
folder, including the new `copy_skinning_cache.py`.

## Update 0.3.0 — merged Skinning Tools

The main sidebar entry is now **Skinning Tools**, containing collapsible
**Weight Editor · Nudge Skin** and **Copy Skinning** sections. The supplied MEL
Nudge Skin tool has been converted to OpenMaya bulk weight operations, using the
same snapshot-based undoable plug-in command. Copy Skinning's transfer methods,
mapping table, masks and Preview cancellation are retained.

See **Skinning_Tools_Guide.md** for the new editor, Hold scopes, vertex
copy/paste, boundary averaging, one-ring smoothing, prune and mirrored weights.
`skinning_ui.show()` and the existing `copy_skinning_ui.show()` launcher both
open the combined tool. The standalone package retains its historical ZIP/folder
name and now includes all seven implementation modules. Replace the complete
folder and save/restart Maya to load registered plug-in **0.4.3**.

## Update 0.2.1 — Preview progress and cancellation

Preview now shows the current stage from mesh reading through influence matching,
triangle preparation, surface-index building, vertex sampling and target checks.
Press **Escape** to cancel. Python loops check cancellation during preparation,
tree building, nearest-point queries, matching and target-weight inspection.
The status includes elapsed seconds; progress percentages describe stages rather
than predicted time. A single native Maya API call must return before a pending
cancel can be handled (for example, evaluating a slow deformation history).

The operation owns and closes its progress window in `finally`, including read
errors, cancellation, sampling errors and target-check errors. It refuses to
start while another progress operation is open, and does not close that other
operation's window. The Preview / Select / Copy buttons disable the panel while
calculating and ignore repeated clicks. Cancellation happens before weight writes.

Replace the complete folder and save/restart Maya to load plug-in **0.4.3**.
For an already orphaned progress window from the previous version, once the
Script Editor responds and no calculation is running, you can close it with:

```python
import maya.cmds as cmds
cmds.progressWindow(endProgress=True)
```

This recovery command closes Maya's current progress window, so use it only when
that window is left over from the failed Preview. It cannot interrupt a blocked
native Maya call. No global Qt cursor stack is cleared by the updated tool.

## Update 0.2.0 — existing skins and editable influence mapping

**Prepare target / reuse existing skin + build mapping** keeps an existing
skinCluster and its weights. It binds only an unskinned target. You can go
straight to Preview / Copy when the target is already skinned.

Replace the complete extracted folder, including core, plug-in and UI files.
Save your scene and restart Maya once if an older registered plug-in is loaded.
The UI checks for plug-in 0.4.3; mismatched package files stop before copying.
The previous fix for Maya loaders without `__file__` is included.

## Implemented plan

| Stage | Implementation |
| --- | --- |
| Geometry sampling | Original undeformed shapes or current deformed shapes, in world space. Optional explicit source/target base meshes. |
| Correspondence | Vertex IDs, or closest point on triangulated source polygons using a world-space bounding-volume tree. |
| Interpolation | Barycentric interpolation of the three source vertices' influence weights. |
| Restricted transfer | Source faces and/or painted source mask; target faces/vertices and/or target mask. |
| Application | Resolve influences, preview, preflight locks/drivers, bulk write through an undoable Python API command. |
| Delivery | New main-tool Copy Skinning tab, standalone launcher, local tests and native Maya smoke test. |

No C++ build, NumPy or ngSkinTools dependency. The new transfer tools are
accompanying Python modules; keep the extracted files together.

## Open the tab

Extract the full toolkit ZIP. In Maya's Python Script Editor, change the path:

```python
import sys
sys.path.insert(0, r"C:/tools/Master_Rigging_Toolkit_Optimized")
import master_rigging_toolkit
master_rigging_toolkit.show()
```

If your existing launcher uses another entry point, it can remain unchanged;
load the new script from the extracted folder so its neighboring modules can
be found. Select **Skinning Tools** in the sidebar, then expand **Copy Skinning**. The weight-copy plug-in is
loaded lazily when you first use an operation. Existing rig workflows are kept.

For the separate Copy Skinning package, or to open only this panel:

```python
import sys
sys.path.insert(0, r"C:/tools/Copy_Skinning")
import copy_skinning_ui
copy_skinning_ui.show()
```

Keep the Python plug-in loaded while its commands remain in Maya's Undo queue.
The panel uses PySide6 or PySide2 to match Maya. No timers, scene callbacks,
scriptJobs or expressions are added by Copy Skinning.

## Common workflow

1. Select the source mesh and **Get selected** in Source.
2. Select the target mesh and get Target. Both require one skinCluster each.
   If the target is unskinned, click **Prepare target / reuse existing skin + build mapping**. Binding a
   new target is separately undoable. An existing target skin is reused.
3. Choose a method and settings. **Preview** reports changed vertices,
   masked vertices, distance skips, source triangles and influence mappings.
   It does not write skin weights.
4. **Select preview vertices** validates the current scene, reuses a matching
   read-only Preview when available, and selects up to 5,000 changed target
   vertices. It does not limit the subsequent copy.
5. **Copy skinning** recomputes from the current scene and writes the complete
   eligible region. One Maya Undo restores the prior weights and optional DQ
   values; Redo restores the copied result. It does not edit joint transforms.

The tool copies evaluated source skin weights. It does not copy a layer stack,
bind matrices, skinning method, joint hierarchy or animation. If the target has
our active Layer Skin prototype stack, bake/detach that stack first so its data
cannot become inconsistent with weights written by this tool.

## Method 1 — Vertex ID

Target vertex `i` receives source vertex `i` weights after influence mapping.
Equal vertex counts are required. By default, face connectivity must also
match. Disabling the connectivity check permits intentional transfers between
equal-count meshes with different faces; you must ensure vertex ordering is
meaningful. Equal connectivity cannot prove semantic vertex correspondence.
Positions, pose and mesh distance are not used by this method.

Copy strength still blends the sampled weights with existing target weights.
Only method 3 uses face captures or painted masks.

## Method 2 — Closest point on mesh

For each target vertex, the tool finds the nearest point on the source's
triangles. This is a surface query, not a nearest-source-vertex lookup. If the
closest point has barycentric coordinates `(b0, b1, b2)` on vertices `(v0,v1,v2)`:

```text
sampledWeights = b0 * weights[v0] + b1 * weights[v1] + b2 * weights[v2]
```

Source samples are normalized before interpolation. Source influence columns
are remapped into target columns; additional target influences have zero weight
in the sampled distribution. Final rows remain nonnegative and normalized.
Degenerate triangles are skipped and reported. World-space queries preserve
the correct distance metric under nonuniform transforms.

**Max distance** is in the scene's current linear units; 0 means unlimited.
Vertices with no source surface inside that distance retain their exact prior
weights. Preview reports those skips. Copy strength defaults to 1.

## Method 3 — Source faces / masks to target region

Define at least one restriction on **each** side:

- Source: select polygon faces and **Get selected faces**, or enable its painted mask.
- Target: capture faces/vertices, or enable its painted mask.
- Supplying faces/components and a mask intersects their effects.
- Source capture limits which polygons can be searched. Target capture limits
  vertex IDs; a target face includes all its corner vertices.

Paint masks separately:

1. **Reset black** creates/clears that mesh's dedicated mask color set.
2. Choose **Mask brush / selected value**, then **Paint** to activate Maya's
   vertex-color brush on that color set. White is 1; black is 0. For soft masks,
   paint gray or adjust opacity in Maya Tool Settings.
3. Alternatively, select faces/vertices and **Set selected** to set their mask
   to the chosen value. **Fill white** enables the full mesh.
4. Click **Restore mask display** to return to selection mode and restore the
   prior mesh color display. Mask data stays saved in the Maya scene.
5. Ensure **Use painted source/target mask** is checked as appropriate.

The reserved color sets are `rtkCopySkin_sourceMask` and
`rtkCopySkin_targetMask`. Other color sets are not overwritten. The red channel
is the transfer value; painting grayscale keeps the viewport representation
clear. Face-vertex colors are averaged per vertex when read. Mask painting and
color-set/flood commands use Maya's native Undo.

Source mask support is clipped geometrically at **Source mask search threshold**
(default .001). Thus a masked-out nearest face/part cannot simply hide an
otherwise valid masked source region farther away. Original triangle
barycentrics are retained through clipping so weight interpolation stays correct.

At an accepted hit, the interpolated source mask also controls contribution:

```text
alpha = CopyStrength * TargetMask * InterpolatedSourceMask
result = (1-alpha) * ExistingTargetWeights + alpha * SampledSourceWeights
```

Without painted masks, their values are 1. With source mask .5, target mask .5
and Copy strength 1, the sampled distribution contributes 25%. Black target
vertices and vertices outside the captured target region are never written.
All-black source masks report an empty source surface instead of copying globally.

Captured components are held in the panel and validated against mesh UUID and
topology. Get them again if the source/target mesh or its topology changes.
Painted masks persist in the scene; UI field values/captured selections are
not scene-persistent in this version.

## Current mesh or base mesh — methods 2 and 3

**Current** reads both meshes after deformation at the current frame. It is
useful when the posed source/target surfaces line up. The complete query is
planned from snapshots before any target weight changes.

**Pre-skin** (backend value `base`) reads the evaluated geometry on the
skinCluster's own `inputGeometry` plug at the correct output logical index, then
uses the visible mesh's current world transform. It includes upstream edits and
deformers and excludes this skin and downstream deformation. No joints, envelope
values or frame are changed. Geometry does not have to be an unconnected DAG
shape; mesh data is supported directly.

A missing/invalid input or changed topology stops copying. Explicit overrides
remain available under the advanced checkbox; they must preserve vertex IDs and
face connectivity. Their own world transforms determine alignment.

These choices change geometric correspondence only. Both modes read the
source's current skin weight values. The targets can have different topology
from the source for methods 2 and 3.

## Influence matching and protection

Enable **Match by name**, **Match by distance**, or both. Both are on by default.
A shared source/target joint is recognized by UUID, regardless of influence
column order. Existing target influences and skin settings are retained.

Automatic matching proceeds through:

1. Explicit manual UUID pairs, followed by the same joint UUID.
2. Unique exact names after optional namespace removal and search/replace.
3. Nearby joints within **Joint tolerance**, using similar names to distinguish
   overlapping/nearby influences. Default tolerance is **0.01 scene units**.
4. If no proximity candidate exists, a unique similar name may still match.

The distance threshold applies to proximity matching; it does not reject a
unique exact name or a valid similar-name fallback outside that distance.
Turn off name matching if every match must satisfy the distance threshold.

Similar-name matching counts character insertions, deletions and substitutions.
The default maximum is **3** (adjustable 0–10); 0 disables approximate spelling
matches. A minimum 60% similarity prevents unrelated short names from matching.
Examples: `upper_arm_L` → `Xupper_arm_L`, `XYupper_arm_L`, or
`XYZupper_arm_L`. Use Search/Replace for consistent prefix/suffix patterns.
Namespace differences are ignored by default; turn that off when namespaces
must distinguish otherwise identical names.

**Bind / rest positions** is the default for joints. It uses inverse
skinCluster bindPreMatrix entries in world space, so ordinary joint animation
does not change proximity matches. **Current joint positions** uses their
current world matrices. These options are independent of Base/Current **mesh**
geometry sampling. The tolerance is converted from scene units to internal
centimeters; the mapping table displays measured distances in centimeters.

Equal candidates and conflicting automatic assignments stay unresolved.
Mappings use mutual unique best candidates instead of source-list order.
Approximate name/distance rules do not automatically cross recognized L/R or
Left/Right side tokens. An explicit Search/Replace or manual override can do so.
The table reports the match method and character differences for each row.

### Manual adjustment

1. Get both meshes. Mapping builds automatically when both are skinned, or
   click **Build / refresh mapping**. This operation reads influences and does
   not change weights.
2. Select a source row in the table.
3. Choose a target from **Selected row target** and click **Set row mapping**.
   Alternatively select a target influence in Maya and **Use selected target joint**.
4. Choose **Automatic** to remove that row's override. Choose **Unmapped** to
   explicitly block copying until you decide its destination.
5. **Clear all manual overrides** returns all rows to automatic matching.

Each target can be used by one source influence. Duplicate manual targets and
unresolved rows stop copying before writes. If overriding a shared-joint UUID,
map any other affected row explicitly as well; the tool does not silently
redirect that joint to a different target. Already-skinned targets need the
intended destination joints as influences; add those influences in Maya if
necessary. Different joint lists are supported when a complete mapping exists.

Manual overrides are stored as UUID pairs rather than list indices. Preview
and Copy recompute and validate the mapping. If a previously reviewed mapping
changes because of joint edits or influence changes, Copy stops and asks you
to refresh the table. Reordering physical influence columns alone preserves
reviewed UUID pairs. Mapping fields and overrides live in the current panel;
they are not saved into the scene in this version.

The tool respects influence locks and rejects changed driven/locked weight
plugs, referenced/locked targets and active target Layer Skin metadata. Turn
off target **Maintain Max Influences** before transfer; the tool does not change
this setting or silently prune weights. There is no automatic unlock action.

Optional **DQ blend weights** are sampled using the same barycentrics, masks and
strength, and participate in Undo. The target's skinning-method setting is kept.

Current scope: polygon meshes, fixed topology within each skinCluster chain,
one skinCluster per object, non-instanced meshes, at most 4 million stored
vertex/influence values per mesh. Topology-changing post-skin history is rejected.
The source tree is built when no matching cached tree or read-only result is
available; no per-frame computation is installed.
Large meshes can require substantial Python memory/time. Runtime Maya
benchmarking and native Maya/PySide validation remain pending.

## Tests and demo

306 local skinning tests pass: 28 task/recovery tests, 20 unskinned-load tests plus 115 transfer/loader/mapping/progress, 41 input/cache,
40 Preview/Select/bulk-guard/interrupt tests and 62 Weight Editor tests. They cover nearest-point regions, barycentrics, mask clipping,
source-face restrictions, target blending, world metric, influence mapping,
vertex-ID transfer, current/base routing, distance limits, DQ and command
rollback ordering. The 380 existing toolkit checks previously passed; their implementation is unchanged. Loader regression cases execute the complete plug-in without `__file__`,
including path fallback, spaces/Unicode and missing dependencies. Mapping tests
cover repeated names, ties, side tokens, 1–3 character differences, unit conversion,
manual conflicts, stale UUIDs, bind/current matrices, existing skin reuse and
reviewed mapping validation. Local fakes do
not reproduce Maya's API internals, paint context or native Undo queue.

For a tiny demo in Maya (does not replace the current scene):

```python
import maya_copy_skinning_smoke
demo = maya_copy_skinning_smoke.make_demo()
```

Get the demo's `source` and `target` meshes in the panel. The source has one
triangle with weights `[1,0]`, `[0,1]`, `[0,1]`. The target's first point projects
to barycentrics `[.5,.25,.25]`, so method 2 should give it `[.5,.5]`.

Run the native checks explicitly inside Maya:

```python
maya_copy_skinning_smoke.run()
maya_copy_skinning_smoke.run_mapping()
maya_copy_skinning_smoke.run_progress()
maya_copy_skinning_smoke.run_cache()
maya_copy_skinning_smoke.run_actions()
maya_copy_skinning_smoke.run_unskinned()
maya_copy_skinning_smoke.run_tasks()
```

The action test checks native component selection, read-only cache reuse, deferred
locked/driven-channel rejection on Copy, calculation timeout, progress cleanup
and Copy Undo. The smoke test checks real API writes, interpolation, masks, selected regions,
ID transfer, DQ, base/current positions, transforms, scene-unit distances and
Undo/Redo. The mapping test adds separate skeletons, bind/current joint positions,
manual UUID overrides and existing skin reuse. The progress test checks native window release after success, injected cancellation and read errors. Test actual Escape input and cursor restoration interactively on a larger mesh. Each test creates/cleans only
its own temporary namespace. Interactive
brush painting and UI layout should also be tested manually on your Maya version.

Official API references:

- https://help.autodesk.com/cloudhelp/2026/ENU/MAYA-API-REF/py_ref/class_open_maya_anim_1_1_m_fn_skin_cluster.html
- https://help.autodesk.com/cloudhelp/2026/ENU/MAYA-API-REF/py_ref/class_open_maya_anim_1_1_m_fn_geometry_filter.html
- https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/artAttrPaintVertexCtx.html
- https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/polyColorPerVertex.html

Skin-discovery API reference: https://help.autodesk.com/cloudhelp/2026/ENU/MAYA-API-REF/py_ref/class_open_maya_1_1_m_it_dependency_graph.html
