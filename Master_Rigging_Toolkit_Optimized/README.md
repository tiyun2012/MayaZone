# Master Rigging Toolkit — optimized revision 2.41

## Revision 2.41: start joints and hierarchy connection planning

**Modular Rig** now contains **Modules** and **Connections** tabs. Each new rig
module links its logical first joint to its start/root controller with message
attributes. Joint, controller, output and metadata renames preserve the links.
For a placement-only Root, Connections can register a skeleton scan anchor
without constraining that joint.

Choose Root in **Connections** to scan its joint hierarchy. The left list finds
missing connections and separates existing matrix/native attachments, manual
parenting and external drivers. The right side suggests the nearest ancestor
module and joint output. Review or override the parent/output and choose a method.
**Parent constraint** is the default, with optional scale follow. **Matrix parent**
retains the previous behavior; **Space switch (planned)** is disabled for now.

Scan is read-only. **Connect selected** and **Connect checked modules · one Undo**
keep current offsets and controller values. Plans are preflighted for dependency
cycles and rolled back in full if an operation fails. Detach holds the current
pose; parent deletion protects connected children. Mirror retains the method and
scale-follow choice. Native solver nodes use each module's constraintNode group.

For saved rigs, **Prepare saved modules** adds missing output/start registration
without rebuilding; the Modules tab's Publish outputs action also registers the
start. Replace the complete folder, reload and confirm **v2.41**. No Maya restart
is needed. See [Rig_Connections_Guide.md](Rig_Connections_Guide.md) for the workflow,
message layout, methods, compatibility, native smoke script and Python API.

**1,049 automated host checks pass**, including 48 new registration, hierarchy,
connection, saved-scene and Qt checks. Native Maya execution remains pending;
`maya_rig_connections_smoke.run()` is supplied for testing inside Maya.

## Revision 2.40: named module outputs and attachments

Every new **Root, FK, Three-Bone IK, IK/FK and Foot** module publishes named
`*_OUTPUT` transforms. Each joint output represents the final module frame
before driving the source joint. IK/FK outputs follow the final length-preserving
blend. Root also offers Placement; Foot with Drive ankle off still offers an
Ankle target for an external leg IK goal.

Open **Modular Rig → Scene modules → Module outputs / attachment**. Choose the
parent module and an output row, click **Use output as parent**, choose the child
module above, then **Attach selected module · keep offset**. The child follows
translation, rotation and global scale through its own INPUT buffer. Its animator
channels, keys, driven keys and defaults stay intact. **Detach · keep pose** holds
the current frame; detach children before deleting their parent. Dependency
cycles are rejected. Mirror uses counterpart source joints to find side-specific
parent outputs and shares a central Root output.

For saved rigs, **Publish outputs · saved rigs** adds outputs/input in place,
retaining the current pose and existing rig. Refresh alone never edits the scene.
Replace the complete folder, reload and confirm **v2.40**; no Maya restart is
needed for this update. See [Module_Outputs_Guide.md](Module_Outputs_Guide.md) for
connections, removal, compatibility and the Python API.

**1,001 host tests pass**, including 43 new output/attachment/upgrade/Qt checks.
Native Maya execution is pending. Run `maya_module_outputs_smoke.run()` in Maya
for the real constraint/IK, scaling, posed cleanup and Undo/Redo checks.

## Revision 2.39: wave position falloff

**waveJoints → Position falloff** adds unlocked, keyable
`waveFalloffPosition` and `waveFalloffPower` attributes (using your chosen prefix).
Position runs from 0 at the first listed joint to 1 at the last. The falloff
weight is 1 at that position and decreases with distance:

```python
distance = min(1, abs(joint_position - falloff_position))
weight = 1 if falloff_power == 0 else 1 - distance ** max(.001, falloff_power)
output = rest_value + wave_contribution * weight
```

Power 1 is linear. Higher values keep a wider area strong; Power 0 disables
falloff and retains the previous wave. Values default to Position .5, Power 0.
The multiplier affects both translation and rotation contributions while
retaining saved local rest values and existing envelope/taper controls.

For a saved 2.38 wave, **Load**, set the falloff fields, then **Apply settings /
order**. This adds the native nodes in place, retaining the original nodes,
rest values and animated controls. Loading alone makes no scene edits. Apply
with Power 0 retains the existing wave. Updates and removal remain undoable.

Replace the complete folder, reload and confirm **v2.39**. See
[Wave_Joints_Guide.md](Wave_Joints_Guide.md) for the equation, examples and native
Maya test. **958 host checks pass**, including 16 new falloff/upgrade checks.
Native Maya execution remains pending; the supplied smoke fixture includes
the new falloff math.

## Revision 2.38: waveJoints

Open **waveJoints**. Get a driver controller, load an ordered joint list or an
unbranched chain, then choose any combination of **TX / TY / TZ / RX / RY / RZ**.
Build creates unlocked, keyable wave attributes on the driver and native Maya
`sin`/math nodes. New attributes start at Envelope 0 to retain the current pose;
press **Enable wave**, then animate Offset or enable Automatic time motion.

Each output adds to its joint's saved local value. Translation and rotation
have separate amplitudes. Per-axis gain/phase supports direction changes and
circular motion; first/last amplitude weights taper the wave. List order can
be dragged or moved with buttons. Apply settings / order updates the same
joint/channel set without accumulating rest offsets. Existing time animation
and Channel Box changes are retained unless the corresponding UI field is edited.

The native graph remains active when the window closes. Scene setups can be
loaded after reopening. **Delete wave** keeps the current joint pose and
orientation and removes only owned nodes. Unused created attributes can be
removed; animated/shared/reused driver attributes are retained. Occupied joint
channels are protected. See [Wave_Joints_Guide.md](Wave_Joints_Guide.md) for the
equation, controller attributes, circular-motion example and Python API.

Requires Maya 2024+ with native `sin`. Replace the complete folder, including
`wave_joints.py` and `wave_joints_ui.py`, then reload:

```python
import importlib
import master_rigging_toolkit as toolkit
importlib.invalidate_caches()
toolkit = importlib.reload(toolkit)
toolkit.show()
```

Confirm **v2.38**. **942 host tests pass**, including 34 new wave graph/Qt
checks. Native Maya is unavailable here. The supplied
`maya_wave_joints_smoke.run()` checks the real sine graph, units, time, posed
removal and Undo/Redo inside Maya.

## Revision 2.37: constraint groups and actions beside each module

New native Maya constraints go under the existing `constraintNode` transform,
or the toolkit creates it. Rig modules own separate subgroups inside this shared
container. Guide IK, Locator View, PoseDriver and the other constraint tools use
the same grouping helper. Solver connections remain intact; matrix math nodes
keep their existing organization. Matrix-only Root/Foot modules need no empty
constraint subgroup.

Open **Modular Rig → Scene modules**. Every module row has **Constraints**,
**Mirror** and **Delete Rig** buttons. Constraints also organizes native solvers
from modules built with earlier versions. Mirror uses the Search / Replace
fields below the table and existing counterpart joints. A Root bound to a
side-specific joint can mirror; a placement-only character Root stays shared.
Delete Rig removes that module's owned subgroup and solvers while retaining
the source joints' current pose and orientation definitions. Other modules
and an existing user-created `constraintNode` remain.

Replace the complete folder, then reload while no tool action is running:

```python
import importlib
import master_rigging_toolkit as toolkit
importlib.invalidate_caches()
toolkit = importlib.reload(toolkit)
toolkit.show()
```

Confirm **v2.37**. **908 host tests pass**, including real Qt row actions,
ownership, renaming, rollback and cross-module cleanup. Native Maya is not
available on this host; run `maya_constraint_groups_smoke.run()` inside Maya
for the supplied grouping, pose, mirror and Undo/Redo fixture. See
[Constraint_Groups_Guide.md](Constraint_Groups_Guide.md).

## Revision 2.36: optional skeleton joint for the Root module

Open **Modular Rig → Root module → Root joint (optional)**. Use Get for one
existing skeleton root, or Clear for placement controls only. Blank Placement
uses that joint's frame; a separate placement object maintains its bind offset.
The joint follows `Root_ctrl` and `Main_ctrl.globalScale` through a native matrix
output, without reparenting the skeleton or connecting its local scale channels.

Source joint drivers and locked channels are preflighted. Defaults, metadata,
controller names and shared removal remain available. Removal keeps the source
joint's current pose, local TRS and orientation definitions. Existing Root
modules without a joint remain compatible; add the new binding by rebuilding.
See [Root_Foot_Modules_Guide.md](Root_Foot_Modules_Guide.md).

Replace the complete folder, then reload while no tool action is running:

```python
import importlib
import master_rigging_toolkit as toolkit
importlib.invalidate_caches()
toolkit = importlib.reload(toolkit)
toolkit.show()
```

Confirm **v2.36**. **889 host tests pass** (10 new Root-joint tests). Checks
cover the matrix graph, source/child scale,
placement offsets, driver protection, defaults, removal/Undo and real Qt input
pickers. Native Maya remains unavailable here; the updated
`maya_root_foot_smoke.run()` fixture includes a driven skeleton root.

## Revision 2.35: Pose weight SDK and per-channel curve mirror

Expand **PoseDriver → Set Driven Key · pose weights and curve mirror**. Select
Raw or the existing Weight / Normalize blend output, Get a neutral driven
transform and author local TRS samples with native driven keys. The table's
Driven value cells let you edit further samples after SDKs are connected.

Mirror rules are explicit for each channel: Keep delta, Flip delta, Keep values
or Skip, plus optional driver 0↔1 reversal and same-type axis remapping. Source
and opposite neutrals are separate, so mirrored controls need not start at the
same local values. Preview is read-only; Mirror copies complete animation curves
and saves the mapping in one Undo action. Saved bindings survive renames and
scene/toolkit reloads. Removal retains current driven values.

This first version supports one direct SDK driver per channel; existing foreign
animation, constraints and blends are protected. Weight uses cone.normalize;
set that to 1 above for fully normalized output. The SDK does not change it.
See [PoseDriver_SDK_Guide.md](PoseDriver_SDK_Guide.md) for the full workflow,
first-version boundaries and native smoke test. Native Maya testing is pending.

Replace the complete folder, including both pose_driver_sdk helper files,
reload `master_rigging_toolkit`, and call `show()`. Confirm **v2.35**.

## Revision 2.34: Root and Foot modules

The Modular Rig tab now has collapsible **Root module** and **Foot module**
sections. Root creates `Main_ctrl > Root_ctrl`; Main owns globalScale and Root
is the attachment for character modules. Foot supports IK reverse pivots
(roll, heel/ball/toe, side bank, twists, toe tap) or an ankle/ball FK hierarchy.
Each field has a Get button, with optional Root parent and custom names.

Foot source outputs use matrix offsets; they do not connect joint scale
channels. Drive ankle can be disabled for an existing leg, exposing an ankle
target for its IK attachment. Shared name/default/mirror/remove actions cover
both module types; Foot mirror reverses bank direction. Existing scene modules
remain compatible. See [Root_Foot_Modules_Guide.md](Root_Foot_Modules_Guide.md)
for setup, roll math, leg attachment and safe removal. Native Maya validation
is pending; `maya_root_foot_smoke.run()` supplies the scene test.

Replace the complete folder, reload `master_rigging_toolkit`, and call `show()`.
Confirm **v2.34** in the title. Do not reload while a tool action is running.

## Revision 2.33: Select beside every Cleanup joint

Each Cleanup result now has a **Select** button beside **Delete**. Select works
for every row, including protected joints whose Delete button is disabled.
It resolves the stored joint UUID, so renamed joints are selected correctly.
Double-click selection remains available. Replace the complete folder, reload
`master_rigging_toolkit`, and call `show()`; the title should say **v2.33**.
All 49 targeted Cleanup checks pass, including actual Qt button actions and
selection after renaming. Native Maya execution remains unverified.

## Revision 2.32: Cleanup tab for unused joints

Open **Cleanup**, load one or more meshes, load the joint root and press **Scan
unused joints**. Joints absent from those meshes' skinCluster influence lists
appear in a table with a right-hand **Delete** button. **Delete All** prunes all
eligible displayed branches from their tips upward. Each action is one Undo
step, rechecks the scene first and rolls back on failure.

Zero-weight influences are retained. Joints used by other skins, locked or
referenced joints, rig drivers and parents of retained objects are protected;
their status explains why. The tool does not reparent children out of an unused
middle joint. Delete All keeps protected rows. The root is checked too and can
be removed if its entire branch is eligible. Scanning does not read vertex
weights or open a progress window. No metadata is added to meshes or joints.

See [Joint_Cleanup_Guide.md](Joint_Cleanup_Guide.md) for workflow, status meanings,
Python entry points and the supplied native Maya smoke test.

Replace the **complete toolkit folder**, including the new `joint_cleanup.py`,
then reload `master_rigging_toolkit` and call `show()`. Check the window title is
**v2.32**. No plug-in unloading or Undo reset is required. The cleanup backend is
loaded from the companion file when the new tab opens.

Validation: **811/811 automated checks pass**, including 37 backend checks and
12 real Qt UI checks, plus the existing toolkit and Skinning Tools regressions. Maya commands are recorded in these
checks; native Maya execution remains unverified. `maya_joint_cleanup_smoke.run()`
provides the native influence/Undo/rename/skin-preservation check.

## Revision 2.31: set transform values on SDK-driven targets

**Guides & joints → Match 2 transforms** now defaults to **Set channel values ·
SDK authoring**. Load the source and target, choose Position/Rotation/Scale, then
press **Match Target to Source**. Incoming SDK connections no longer cancel this
method during preflight. The tool solves the requested match in the target's
parent/joint space and applies the resulting local channels using `setAttr`.

Inputs stay connected, and only the requested target channels are set. Locks
are respected, source transforms stay intact, and target joints retain their
jointOrient and rotateAxis definitions. Matching is one Undo step; a failed set,
changed input connection or value that Maya will not retain rolls back.

This is an SDK-authoring pose change. Set your driven key afterward to save the
new pose in the SDK curve. Changing the SDK driver can evaluate its existing
curve and replace the temporarily set values. **Native match · unconnected
channels** remains available with the previous connection/writability checks.

Python: `match_two_transforms(source, target, method="set")`. This is also the
default when `method` is omitted. Use `method="native"` for the former behavior.
Reload the toolkit and reopen it; the window title should say **v2.31**.

**456 toolkit regression tests pass**, including 12 new direct-set cases. Real
Qt method selection and SDK routing were checked offscreen. All 21 Python files
compile with Python 3.10 syntax. Native Maya execution remains unverified;
`maya_smoke_test.run_guide_match_sdk()` creates a genuine SDK relationship and
checks world matching, curve preservation, Undo/Redo and later SDK evaluation.

## Revision 2.30: cache the driver controller and return to poses

In **PoseDriver → Joint & start pose**, select the rig controller that poses the
joint and click the new **Driver controller → Get selected** button. Do this
before **Capture start / Build** to cache its default values too. Controller
selection is optional, and existing setups can bind a controller after loading.

Capturing a pose now saves that controller's current keyable numeric channels
with the pose, including editable translation, rotation, scale, boolean/enum and
custom attributes. Each target card has **Go to pose**, which restores those
values, and **Cache controller pose**, which saves them explicitly. **Go to
default pose** restores the controller values captured with the start pose.
**Set default from current joint** also updates the cached controller default.
Cache data is saved in the setup's scene metadata. UUID references survive
controller renaming; typed angles/distances convert when Maya UI units change.

If a target object defines a direction the joint has not reached, its pose is
created without a controller cache. Pose the joint at that target, then press
**Cache controller pose**. This prevents Go to pose from restoring an unrelated
controller position. Existing poses follow this same manual-cache workflow.
There is no attempt to infer controller values from a target locator alone.

Recapture refreshes the cached controller values when the joint matches the
target. Editing only the angle keeps a previously valid cache. Changing a target
direction clears an obsolete cache unless the new direction is currently posed.
Mirrored weight setups require their own destination controller cache; source-side
controller values are not assumed to produce a valid mirrored rig pose.

Restore preflights every saved channel before editing, preserves incoming
animation/SDK/constraint connections and refuses locked or driven channels. It
checks that the controller parent, rotate order and attribute types still match.
Restores use one Undo step, and a failed restore rolls back. The joint direction
is checked after restoring; a changed rig that no longer reproduces the target
also rolls back. Controller caches use local channels, so external rig/space
changes can require recaching. The tool adds no keys or attribute locks. Removing
the PoseDriver keeps the original controller. Clearing/rebinding the driver
changes future captures; existing pose caches retain their own controller link.

Python entry points: `set_pose_driver_controller(group, controller)`,
`cache_pose_driver_controller_pose(group, pose_id)`, and
`goto_pose_driver_pose(group, pose_id)`. Omit `pose_id` in Go to restore the
cached default. `build_pose_driver(joint, driver_controller=controller)` caches
the controller default during creation.

Replace the complete folder, reload `master_rigging_toolkit`, and call `show()`;
the window title should say **v2.30**. **444 toolkit regression tests pass**,
including 23 new controller-cache cases. Actual PySide6 controls were checked
offscreen. Live Maya execution remains unverified;
`maya_smoke_test.run_pose_driver_controller_cache()` supplies a native test for
controller-driven joint capture, live weights, recall, Undo/Redo, rename,
custom values, animated-input protection and controller survival after removal.

## Revision 2.29: PoseDriver automatic angles and linear defaults

New PoseDriver systems use **Linear angle** falloff and **Normalize = 0**.
New target cards and **Capture rotated joint** enable **Auto from default**.
On capture, the tool measures the angle between the saved default direction and
that target direction, then uses it as the pose's falloff angle. A supplied target
object defines the direction; a blank object field uses the current joint.

For a target 70° from the default, falloff is automatically 70°. Along that same
rotation arc, weights are 0 at the default, 0.5 at 35°, and 1 at the target.
This is a linear directional-angle response. Twist around the cone's X axis
still does not affect the weight. Normalize above 0 can change the final curve.

Each captured card shows its calculated angle. **Update pose / angle** and
recapture remeasure automatic angles while retaining existing weight attributes,
graph nodes and downstream connections. Uncheck **Auto from default** to enter a
manual angle; it stays manual on later updates. Mirror copies this choice and
remeasures automatic angles against the destination's own default. Minimum pose
distance remains a separate spacing check, with its existing 15° default.

Angles are measured in the weight graph's start-frame space, accounting for the
saved default, cone sign and reference transform. The supported range is now
0.1–180°. Automatic angles below 0.1° use a 0.1° minimum. A direction identical
to the default is rejected before creating nodes; use a manual angle if you
intentionally want a rest-direction cone.

Existing scene setups retain their saved falloff mode and angles. To update one,
load it, select **Weight falloff → Linear angle → Set falloff**, enable **Auto
from default** on the desired cards, and press **Update pose / angle**. Changing
the stored default leaves existing weights intact until automatic poses are
updated or recaptured. Old setups without an explicit saved direction use their
captured start-frame X axis as the default.

Python: omit `radius` when adding/capturing a new pose for automatic calculation.
Use `update_pose_driver_pose(group, pose_id, radius="auto")` to opt an existing
pose into automatic angles; a numeric radius selects manual mode. On update,
omitting `radius` keeps the saved mode and remeasures if it is automatic.

Replace the complete folder, reload `master_rigging_toolkit`, and reopen with
`master_rigging_toolkit.show()`. Check the window title is **v2.29**; loading a ZIP
does not replace a module already imported in Maya. See **Install and launch**
below for the reload command.

**421 toolkit regressions pass**, including 17 new automatic-angle cases. Real
PySide6 controls were checked offscreen for capture, manual overrides, draft
retention and existing-setup loading. Native Maya execution has not been run.
`maya_smoke_test.run_pose_driver_auto_falloff()` supplies a native 70° sweep,
joint display, recapture/output preservation, manual override, object capture
and Undo/Redo check.


## Revision 2.28: PoseDriver normalization without near-zero divisors

A warning was still reported after capturing and rotating despite the previous
1e-8 denominator floor. The exact Maya evaluation state has not been reproduced
here. Normalization now uses equally scaled inputs:

`(rawWeight * 1e8) / max(rawWeightSum * 1e8, 1)`

The actual Divide node's divisor is clamped to at least 1. This preserves the
v2.27 formula `rawWeight / max(rawWeightSum, 1e-8)` within floating-point precision,
without feeding a tiny denominator to Maya's Divide evaluator. Zero weights remain
zero; ordinary one-pose centers reach 1. This is a graph correction, not a global
warning filter. It uses one shared scaled-sum/clamp pair and one numerator multiply
per pose, using standard Maya nodes.

For an existing setup, load it in **PoseDriver** and click **Weight normalization
→ Repair divide protection**. It upgrades the owned graph while preserving the
existing normalizer nodes, public weight attributes and SDK consumers. New helper
nodes are recorded as owned members and cleaned by pose/system removal. Repair is
undoable and idempotent; foreign drivers or modified outputs stop it before edits.
Failures restore connections, settings and metadata and remove new nodes.
Capturing into an old setup upgrades it after validating the capture inputs.

Alternatively, select the setup's cone, group or source joint and run the bundled
**PoseDriver_Repair.py**. Keep it beside `master_rigging_toolkit.py`. It reads the
updated source from disk in a separate module without reloading an existing Qt
window and prints which path it used. For future captures, make sure the main
window title says **v2.28**; extracting a ZIP alone does not replace imported code.
Save/restart Maya after replacing the package if an older toolkit is loaded.

404 toolkit regressions pass, including 11 new scaled-graph/migration checks.
The unchanged Skinning Tools 0.4.3 release previously passed 306 tests. All 21
packaged Python files compile. Native Maya execution remains pending.
`maya_smoke_test.run_pose_driver_normalization_warnings()` captures divide warnings
for the test setup while sweeping Y70 poses, smooth/linear falloff, Normalize 0/1,
zero/tiny sums and DG/Serial/Parallel modes. Its temporary callback, evaluation mode
and warning-display setting are restored in finally. This native test has NOT run
in this environment, so warning-free behavior is not claimed as verified.

## Revision 2.27: PoseDriver divide protection

New PoseDriver graphs use a positive normalization denominator:
`max(rawWeightSum, 1e-8)`. Zero active poses give zero final weights. Normalization
is unchanged when the sum is at least 1e-8; smaller positive sums are attenuated
by the floor. Scalar normalizers initialize all denominator components to 1,
connect the guarded X input and raw weight, then enable Divide. Direction-unit
dividers likewise receive safe inputs before enabling Divide.

For an existing setup, open **PoseDriver**, load its saved setup and click
**Weight normalization → Repair divide protection**. It updates the owned
condition and normalizer settings, reconnecting missing expected guard inputs.
Output nodes, cone/joint attributes and SDK connections remain in place. The
repair temporarily bypasses division while updating its guard, then enables it
last. The change is undoable and idempotent, including native float rounding.
Locked/referenced nodes, foreign drivers and custom unused-axis consumers stop
repair before mutation. Runtime failures restore modified values/connections.

This is a preventative math/construction fix. Your sampled denominators were all
1, so the reported warning's transient evaluation state was not reproduced.
Native Maya verification is still pending. 393 toolkit regressions pass, including
13 new divide/repair checks; unchanged Skinning Tools 0.4.3 previously passed 306
checks. Run `maya_smoke_test.run_pose_driver_divide_protection()` in Maya for
native zero/active evaluation, repair, connections and Undo checks.

This update does not globally suppress warnings. To hide warning messages in
Maya's Script Editor temporarily, run `cmds.scriptEditorInfo(suppressWarnings=True)`;
this hides all warnings, including unrelated ones. Restore their display with
`cmds.scriptEditorInfo(suppressWarnings=False)`.

## Skinning Tools 0.4.3: Tasks and recovery

The new Tasks tab lists the active operation and 20 recent results, with names,
stages, elapsed time, checkpoint age and errors. Cancel requests cooperative
cancellation; Force stop / reset requests cleanup for tracked calculations or
resets selected untracked progress UI when no tracked job is active. Native call
interruption and terminating arbitrary scripts are unsupported. Atomic Copy and
Weight Editor writes remain protected through verification/rollback. No arbitrary
Qt event pump or worker-thread Maya API calls are added; the task list refreshes
only while visible and Maya is responsive. Use Escape during synchronous work.

306 local tests pass. Qt task controls were verified at 540px/780px widths; native
Maya execution remains pending. Replace the complete folder, including the new
**skinning_tasks.py**, save and restart Maya for plug-in **0.4.3**.

## Copy Skinning 0.4.2: unskinned source loading

Skin discovery now precedes mesh evaluation. Bare unskinned meshes fail before
progress starts, while meshes with history use a cancellable OpenMaya upstream
walk with explicit search limits. Loading uses the calculation budget, invalid
sources cannot populate the cache, and failed loads mark the field and release
busy/progress state. A source must already have skin weights; unskinned targets
can use Prepare target / refresh mapping.

278 local regressions pass, including 20 new Load failure checks. Native Maya
reproduction remains pending; `maya_copy_skinning_smoke.run_unskinned()` supplies
native coverage. Replace the complete folder, save and restart Maya for plug-in
**0.4.2**. The main rig toolkit stays at 2.26.

## Skinning Tools UI update · backend 0.4.1

Weight Editor and Copy Skinning now have separate tabs. The editor groups mesh,
influences and Set/Nudge controls, with collapsible selection, cleanup and mirror
tools. Copy uses compact mesh inputs and transfer settings, collapsed advanced
options, and a fixed Preview / Select / Copy bar. Large reports become expandable
details with a compact status; errors open details automatically. Scoped styling
keeps the Maya palette and emphasizes the primary actions.

Real PySide6 widgets were checked at 540px and 780px widths, including expanded
sections and action signal dispatch. All 258 skinning regressions pass. Native
Maya and PySide2 layout verification remain pending. Replace the complete folder
and restart Maya. Rig and skin backends remain unchanged.

## Copy Skinning 0.4.1: Preview and Select waiting fixes

Preview and Select no longer build Copy's Undo buffers or check each weight plug.
An unchanged read-only Preview can be reused after validating live scene inputs;
Select uses one native vertex-component operation. Copy retains fresh write
checks, using batched lock/connection inspection. Progress stays open through
native selection and Copy's write/verification/rollback. Native Escape polling
and a 120-second calculation limit (0 = unlimited) stop cooperative work; a
native Maya call must return before Python can cancel it.

258 skinning tests pass. Maya execution and reproduction of the reported hang
remain pending. Replace the complete folder, save and restart Maya for plug-in
**0.4.1**. See **Copy_Skinning_Guide.md** and the new native `run_actions()` smoke.

## Copy Skinning 0.4.0: automatic pre-skin input and shared geometry cache

Load the visible deformed source and target meshes; pre-skin mode reads the
skinCluster's evaluated inputGeometry directly, including upstream tweaks and
deformers. No manually selected Orig/intermediate mesh is required. Current mode
uses evaluated deformed geometry. Mapping and explicit overrides are tucked away
until needed; closest-surface copy is the default.

Geometry, source search indices and target correspondence are cached across
Load/Preview/Copy and shared with the registered command. Content and transforms
are revalidated on use, so changed deformation/upstream history invalidates the
relevant snapshots. Weights, masks, influence mapping, preflight and Undo data
remain fresh. Cache limits: 12 entries / estimated 128 MiB, no persistent Maya
API objects or scene callbacks. Refresh and Clear cache controls are provided.

218 skinning/cache tests pass. The unchanged main toolkit previously passed 380
regressions. Native Maya/PySide execution is pending. Replace the complete folder,
including **copy_skinning_cache.py**, and save/restart Maya for plug-in **0.4.1**.
See **Copy_Skinning_Guide.md** for behavior and cache/native test details.

## Revision 2.26: unified Skinning Tools (plug-in 0.3.0)

The sidebar **Skinning Tools** page merges the new OpenMaya Weight Editor with
Copy Skinning in collapsible sections. The supplied MEL Nudge Skin workflow is
implemented with bulk weight reads/writes and snapshot Undo/Redo: combined
multi-influence Set/Nudge, explicit Hold scopes, searchable averages, vertex
copy/paste, boundary averaging, one-ring Smooth/Hammer, prune, affected-vertex
selection and name-mapped world-plane mirror. Existing locks are preserved;
weight edits never automatically lock influence attributes.

See **Skinning_Tools_Guide.md**. Replace the complete folder and restart Maya if
an older registered plug-in is loaded. Standalone: `import skinning_ui;
skinning_ui.show()`. Existing `copy_skinning_ui.show()` also opens the merged
panel. No selection callbacks, timers or worker-thread Maya API calls added.
557 local tests pass: 62 editor, 115 Copy Skinning and 380 toolkit regressions.
Native Maya/PySide validation remains pending.

This revision updates the attached Maya Python toolkit. It keeps the controller,
FK, curve-aim, distance-aim, SDK, vertex-constraint, and joint-orientation
operations in the same standalone module, with a new navigation shell and
targeted fixes to scene caching and namespace weight transfer.

## Copy Skinning (revision 2.25)

The new **Copy Skinning** sidebar tab supports:

1. Copy by vertex ID, with equal counts and optional connectivity verification.
2. Closest source triangle point with barycentrically interpolated weights.
3. The same surface transfer restricted by captured source faces, target
   faces/vertices, and independently painted source/target masks.

Methods 2 and 3 offer **Current deformed** and **Base undeformed** geometry.
Optional explicit base meshes handle complex history. Source mask support is
clipped before the nearest-surface search; target mask and source confidence
blend the copy with existing target weights. Preview shows changed vertices,
skips and influence mappings. Copy uses an undoable Python API command.

Extract the complete package and keep `copy_skinning_ui.py`,
`copy_skinning_plugin.py` and `copy_skinning_core.py` beside the main script.
See **Copy_Skinning_Guide.md** for installation, mask painting, binding a new
target, matching influences, DQ settings, limits and the native smoke test.
**115 transfer/loader/mapping/progress tests pass; the unchanged toolkit previously passed 380 checks.**
Copy Skinning 0.2.1 adds staged Preview progress, cancellation and cleanup. It reuses existing target skins and adds name/distance matching
(default joint threshold 0.01 scene units), 1–3 character name differences,
bind/current joint positions and an editable UUID mapping table. Replace the
complete folder and restart Maya if the older plug-in is already loaded.
The missing `__file__` load fix is included.
Native Maya/PySide execution and performance benchmarking remain pending.

## Revision 2.24: X-axis solver and stable blend lengths

New Three-Bone IK and IK/FK builds use three X-aligned internal joints,
two orientation locator buffers and a tip output. Stretch, anti-pop, slide
and pole lock change internal **translateX**, with solver joint scale fixed
at one. Matrix offsets preserve the original joint frames, local TRS,
jointOrient, rotateAxis and SSC settings. Source scale channels receive no
rig scale connections. ROOT.globalScale still scales the entire module.

The IK/FK blend uses local quaternion rotation interpolation and an explicit
length for each segment: `L = (1 - blend) * FK_length + blend * IK_length`.
This prevents the shortening caused by blending independent world positions.
Arbitrary opposing local translation directions use a nonzero fallback at the
midpoint; their direction can change abruptly, but the segment does not collapse.

**Existing rigs:** remove the old module with pose preservation, then rebuild
it to get this graph. Reloading the script does not replace scene connections.
“Add length controls to older IK” keeps the legacy solver. Rebuilding does not
migrate controller animation. Removal of a new matrix rig holds its current
pose in a static offsetParentMatrix and keeps its original local channels.

## IK/FK blend module

Open **Modular Rig → IK/FK blend module**. Get First, Second and Third
consecutive joints, set size/pole distance and optional controller names, then
Validate and **Build IK/FK module**. It creates three FK controls, IK BASE,
END and POLE under one ROOT with **`ikFkBlend`**:

- **0 = FK**, **1 = IK**; intermediate values blend the two branches.
- **Match & switch to FK / IK** snapshots the current output joints, matches
  destination controls, switches, then verifies the source joint world pose.
  An unrepresentable RP twist/scale pose rolls back the action.
- **Apply blend** changes only the weight; it does not match controls first.
- **Key matched controls / blend on current frame** retains direct time curves
  and keys this frame. It does not bake or protect an entire animation range.

The blend is unlocked/keyable on ROOT, clamped in the native graph to 0–1.
FK is visible at 0, IK at 1, both during a partial blend. New rigs blend
local rotations and segment lengths separately, then rebuild the chain from
root to tip. Equal FK/IK bone lengths stay constant throughout the transition;
different lengths interpolate linearly. Matrix outputs drive the source skeleton.
There is one owned IK driver chain and no second FK driver skeleton. The IK branch includes v2.22 translation-based
stretch, anti-pop, upper/lower/overall slide and pole lock. IK BASE follows the
first joint when matching; its ROOT-space measurement avoids reading solved
driver matrices. ROOT.globalScale scales both branches.

Shared naming, default storage/reset, counterpart mirror and pose-preserving
removal support IK/FK. Go to Default resets blend even with ROOT placement/scale
excluded. Mirror builds a neutral FK-default system on matching joints.
Existing standalone modules keep their type; remove a previous module from the
same joints before building this new module.

**380 local regression tests pass**; all four supplied Python files compile.
Run `maya_smoke_test.run_modular_xik()` in Maya for native X-axis solver,
local blend length checks, source frame/scale preservation and removal/Undo/Redo.
Native Maya/Qt execution and runtime benchmarking remain pending.
See **Modular_Rig_Setup.md** for usage, matching limits and APIs.

## IK stretch, anti-pop, slide and pole lock (revision 2.22)

New **Modular Rig → Three-Bone IK** builds include six unlocked, keyable
attributes on **END_CTRL**. All default to zero, preserving the normal IK setup.

| Attribute | Range | Effect |
| --- | --- | --- |
| `stretch` | 0–1 | Blend into extend-only stretch to reach END. |
| `antiPop` | 0–1 | Soft IK near full extension; 1 uses a 20% soft zone. |
| `upperSlide` | −0.95–10 | Upper rest-length adjustment; 0.1 adds 10%. |
| `lowerSlide` | −0.95–10 | Lower rest-length adjustment; 0.1 adds 10%. |
| `slide` | −1–1 | Transfer length between bones; positive lengthens upper. |
| `poleLock` | 0–1 | Blend the bend joint toward POLE; 1 pins it there. |

New builds multiply each segment length factor by the internal solver's
default **translateX**. Solver joints aim +X at their children; translateY/Z
remain zero. Older saved graphs retain their signed translate XYZ backend. These features do not drive joint scale. ROOT.globalScale
continues to scale the module as before. ROOT-space measurements avoid extra
stretch during global scaling. END also shows `upperLength` and `lowerLength`
readouts, excluding ROOT global scale. Soft IK alone lets the tip lag END near
full extension; combine `stretch=1` with anti-pop to reach END while retaining
a small bend. Full pole lock takes precedence over soft reach and manual lengths.

Choose the rig in **Scene modules**, then use **Selected IK · length controls
(translation)** in the IK section: **Load values**, edit, **Apply values**, or
**Select END attributes** for Channel Box animation. The optional Key checkbox
retains direct time animation. Existing rigs need **Add length features to
selected older IK** once; the upgrade keeps their current source pose and rolls
back on failure. Custom attributes with conflicting names are kept and block
the upgrade. Go to Default now includes these six controls; Store current as
default captures them. Mirrored builds include the features at neutral values.

The system uses owned Maya DG nodes, with no Python per-frame update loop.
Removal includes its goal, math nodes and automatic unit conversions while
keeping the current source joint pose. Guide IK remains a separate tool.
See **Modular_Rig_Setup.md** for formulas and API examples.

**329 local regression checks pass** and all four Python files compile. Tests
evaluate the graph math, ownership, units, defaults, upgrade rollback and removal;
they do not simulate Maya's IK solver. Native Maya/Qt execution and runtime
benchmarking remain pending. Run `maya_smoke_test.run_modular_ik_lengths()` inside
Maya for the new native IK tests.

## Compact module layout (revision 2.21)

The Modular Rig screenshot showed oversized collapsed sections. They inherited
QGroupBox title margins/padding despite using a separate header button. Module
sections now use compact QFrame cards with full-width arrow headers and no
reserved title strip. Hidden bodies do not retain space. The page uses explicit
8-pixel section spacing, top alignment, consistent body margins and a dark
background matching the toolkit. Click a header to show/hide its existing fields.
All rig actions, defaults, naming, mirrors and native window teardown are unchanged.

**303 local regression checks pass**, all four Python files compile. The supplied
screenshot was inspected; updated native Maya/Qt rendering has not been run here.

## Module removal, naming, defaults and mirror (revision 2.20)

Both **FK** and **Three-Bone IK** now support:

- **Removal fix:** compare incoming owned constraints by UUID rather than source
  plug spelling; canonicalize outgoing destination attributes/UUIDs. Short/long
  names and aliases no longer trigger the old exact-string mismatch. Real
  external drivers remain protected and are identified in the warning. Older
  modules use the corrected removal without rebuilding.
- **Joint-based names:** e.g. `upper_L_FK_CTRL`, `ankle_L_IK_END_CTRL`,
  `knee_L_IK_POLE_CTRL`, with no random UUID fragment in controller names.
  Builder **Load controller name fields** provides per-controller overrides;
  blank names use joint defaults. In **Scene modules**, **Load selected rig name
  fields → Apply controller names** renames existing rigs without rebuilding.
- **Go to Default:** restore saved local controller values. **Include ROOT /
  globalScale** defaults off. **Store current as default** saves a new default;
  **Key default on current frame** retains direct time animation and keys the
  reset. Locked/other driven inputs stop the reset. Old modules can zero controls
  with ROOT excluded; store a default first to include an older ROOT.
- **Mirror rig to matching joints:** configurable `_L` → `_R` Search/Replace,
  Swap and Preview. Builds the same module type on existing counterpart joints;
  source rig and animation remain untouched. Names map by token or use opposite
  joint defaults; control size/new IK pole distance are reused. Destination
  joints supply the rest transforms/pole geometry. No animation or joint creation
  is included; an occupied destination is blocked.

See **Modular_Rig_Setup.md** for naming, migration, reset/keying, attachment and
mirror behavior. **303 local checks pass**, including 22 new module action
checks. Native Maya/UI checks remain pending;
`maya_smoke_test.run_modular_actions()` is supplied for native verification.

## Collapsible modules and Three-Bone IK (revision 2.19)

In **Modular Rig**, click the arrow/header on **FK module**, **Three-Bone IK
module**, or **Scene modules** to collapse/expand each body independently.
Inputs and scene rigs remain intact. FK initially collapses; IK initially opens.

The new **Three-Bone IK module** takes First, Second and Third consecutive joints
using individual pickers or **Get chain from selected first joint**. Set a module
name, control size and pole distance, Validate, then Build. It uses three
joints/two bend segments. END controls the IK goal/end orientation; POLE controls
the bend plane calculated by projecting Second onto First–Third. Straight chains
need a slight bend before building.

The native rotate-plane solver drives a separate three-joint driver chain under
ROOT. Source joints keep their hierarchy and orientation/scale definitions,
with parent/scale constraints from the drivers. ROOT.globalScale uniformly
scales the internal chain and controls; source scale compensation is preserved.
The original 2.19 IK owned 23 nodes; 2.22 adds its owned length graph and soft goal.
There is no Python per-frame update loop. Controller
attributes are not explicitly locked. Overlapping FK/IK modules are blocked.

The shared manager discovers FK/IK modules, selects ROOT or **module controls**
(FK controls or END/POLE), and removes the selected module while preserving this
frame's evaluated source joint pose. It remains compatible with 2.18 FK modules.
The IK section also has a removal shortcut for the selected scene module.

See **Modular_Rig_Setup.md** for both workflows, node structures and constraints.
**281 local tests pass** (24 FK + 13 new IK/collapse checks). Native Maya solver,
visual UI checks and runtime benchmarking remain pending. The supplied
`maya_smoke_test.run_modular_ik()` checks END/POLE, globalScale, JO, source SSC
on/off, removal and Undo/Redo inside Maya.

## Modular Rig: FK module (revision 2.18)

Open **Modular Rig**. Get a root joint with **Include descendant joints**, or
**Use selected joints** for an explicit connected joint tree. Set the module
name and control size, **Validate joints**, then **Build FK module**. Branches
are supported; selection order is not important. Each control drives one joint.

The generated ROOT controller has an unlocked, keyable **globalScale** (1 =
original size). It scales the FK control hierarchy; native parent and scale
constraints drive the source joints. The source skeleton stays in its original
hierarchy. Joint orientation definitions and scale compensation are preserved.
Positive uniform scale is supported; nonuniform/negative/sheared transforms and
already animated/driven joint channels are blocked before building.

**Scene modules** discovers saved modules. Select ROOT/globalScale, select all
module controls, or **Remove module · keep current joint pose**. Removal keeps this
frame's evaluated T/R/S and verifies world transforms; it does not bake animation.
Source joints and unrelated objects are never owned module nodes. Protected
members, foreign descendants/output consumers and replacement drivers block
removal with a specific message. Build/removal each use one Undo step.

The FK rig uses native DAG/constraint evaluation, with **5N + 3 owned nodes**
for N joints and no Python update loop, duplicate skeleton or curve history.
Runtime performance has not been benchmarked. See **Modular_Rig_Setup.md** for
setup, node structure, scale rules, module attachments, metadata/API, removal
and extension strategy. This original FK module remains available with the IK
module added in revision 2.19; automatic sockets and FK/IK blending are pending.

**268 local regression tests pass**, including 24 modular FK checks. Native
Maya evaluation and UI checks remain pending. `maya_smoke_test.run_modular_fk()`
checks native FK/scale with branches, jointOrient, segmentScaleCompensate on/off,
pose-preserving removal and Undo/Redo.

## Guide: match two transforms (revision 2.17)

Open **Guides & joints → Match 2 transforms**. Load **Source (reference)** and
**Target (move)** individually, or select Source first and Shift-select Target,
then **Get both from selection**. **Swap** reverses the fields.

Choose **Position**, **Rotation**, and/or **Scale**, then press **Match Target
to Source**. Position/Rotation default on; Scale defaults off. **Set channel
values** is the default method as of 2.31. An unconnected temporary copy of
Target is matched to Source to solve the correct local channels across parents;
it is deleted before the actual Target is changed with `setAttr`.
This is a one-time match and creates no lasting constraints or helper nodes.
Target joints retain their jointOrient and rotateAxis definitions. Unaffected
components stay unchanged, and selection is restored.

Affected locked channels block the action. Set mode attempts channel setting
with existing inputs kept connected, supporting SDK pose authoring; a driver
can recompute its value later. Native mode also rejects incoming connections
and non-writable channels. Instanced objects, identical objects and a Source below Target are
rejected; a child reference would move with Target. Maya Undo is required so a
failed match can restore Target. The entire successful match is one Undo step.

```python
master_rigging_toolkit.match_two_transforms(
    source, target, position=True, rotation=True, scale=False)
```

**244 local regression tests pass**; Maya runtime/UI verification is pending.
`maya_smoke_test.run_guide_match_transforms()` checks native matching across
parents, TRS/position-only, source/jointOrient preservation and Undo/Redo.

## Quick constraints (revision 2.16)

Open **Constraints** in the workflow sidebar. At the top, **Quick constraint ·
Driver → Driven** has individual **Get selected** fields and **Get both from
selection** (select Driver first, then Shift-select Driven), plus **Swap**.
Choose **Parent, Point, Orient, Scale, Aim**, or **Parent + Scale**, set
**Maintain Offset**, and click **Apply constraint**.

Driver controls Driven. Maintain Offset defaults on; disabling it aligns the
constrained channels to Driver. Parent affects translation/rotation; Point
translation; Orient rotation; Scale scale. Aim points Driven's local +X toward
Driver, with local +Y/world +Y up. Parent + Scale creates both nodes as one
undoable action. This tool constrains only the supplied object, without walking
its hierarchy. The existing hierarchy matching tool remains below it.

Affected locked/non-writable channels and incoming animation/constraints block
creation. Unaffected channels can remain locked. Self constraints, Driver below
Driven, instances and coincident Aim positions are rejected. Creation requires
Maya Undo; a failed command rolls back this action and preserves Driven's prior
state. Selection is restored. Repeated Apply on already connected channels
does not silently add or overwrite constraints.

```python
result = master_rigging_toolkit.create_pair_constraint(
    driver, driven, constraint_type="parent", maintain_offset=True)
```

**236 local regression tests pass**; Maya runtime/UI verification is pending.
`maya_smoke_test.run_pair_constraints()` covers native types, offsets, driver
direction, snapping and Undo/Redo with temporary objects.

## Unlocked weights for Set Driven Key (revision 2.15)

Cone and joint **Weight / WeightRaw** attributes are now **unlocked, keyable and
visible in the Channel Box**. The cone's `rawWeightSum` is unlocked/keyable too.
Existing incoming weight calculations and outgoing SDK/rig connections are
preserved. Rotate the joint to change the computed driver value, then set the
driven key on the target attribute. Weight attributes can be loaded as SDK
drivers; their incoming computation remains connected.

For an older setup, load it and click **Unlock weights for SDK** once. This
updates owned cone outputs and joint weight attributes without changing values,
pose centers, connections or metadata. **Connect weights / Select joint** also
unlocks these attributes. Repurposed joint attributes and locked/referenced joint
nodes are preserved; cone weights remain available as drivers in that case.

Python: `master_rigging_toolkit.unlock_pose_driver_weights(group)`.
**225 local regression tests pass**. Maya runtime verification is pending.
`maya_smoke_test.run_pose_driver_sdk_weights()` creates native SDK relationships
from joint/cone weights, checks live driven values and verifies that unlocking,
Undo/Redo and system removal retain the expected connections/values.

## Linear weights and easier removal (revision 2.14)

Load your PoseDriver, choose **Weight falloff → Linear angle**, then **Set
falloff**. This applies to saved and future poses. Existing cone/joint output
plugs and their connections are retained. **Smooth cosine** remains available;
it was the default before revision 2.29. Existing setups keep their saved mode.

Linear raw weight is `clamp(1 - angle / radius, 0, 1)`, where angle is the angular
distance from the captured target direction. At radius 45°, distances 0°, 15°,
30°, 45° produce weights 1, 2/3, 1/3, 0. This is linear in cone-direction angle,
not necessarily in individual Euler channels when multiple axes rotate together.
Use **Normalize = 0** for the final output to follow that raw curve. Normalize 1
divides by the total and can reshape the curve; one active pose becomes 1
everywhere inside its radius. A native angleBetween node plus a controlled
radian conversion computes angular falloff without expressions or callbacks.
Changing falloff radius also updates the linear branch. A new mirrored setup
copies the source mode; an existing destination keeps its own chosen mode.

**Remove PoseDriver system** now defaults to **Keep current values on connected
targets**. It reads all numeric weight receiver values before changing anything,
disconnects cone/joint display outputs, and leaves receivers at those values.
This is a constant snapshot at the current frame, not an animation bake. Owned
display attributes and system nodes are then removed while the joint and receiver
nodes remain. Undo restores the setup, attributes and connections in one step.
Uncheck this option to use the previous behavior, which refuses connected outputs.
Foreign child objects and locked/referenced nodes remain protected. If a value
cannot be preserved, removal stops or rolls back the entire operation.

```python
master_rigging_toolkit.set_pose_driver_falloff(group, "linear")
master_rigging_toolkit.set_pose_driver_normalize(group, 0)
master_rigging_toolkit.remove_pose_driver(group, preserve_consumers=True)
```

**219 local regression tests pass**. Maya runtime verification is pending.
`maya_smoke_test.run_pose_driver_linear_remove()` checks angular weights,
degree/radian unit changes, mode switching, stable outputs, retained receiver
values, joint transforms and Undo/Redo using temporary nodes.

## View pose weights on the joint (revision 2.13)

New poses automatically expose `<poseName>Weight` and `<poseName>WeightRaw` as
unlocked, keyable custom attributes visible in the source joint's Channel Box.
The connection is **cone weight → joint display attribute**. Rotate the joint
to see the values update live; its transform channels and animation inputs are
kept intact. Normalize is still controlled on the cone.

For existing setups, load the setup and press **Connect weights / Select joint**.
This connects all saved outputs and selects the joint for inspection. Repeating
the action keeps existing output plugs and connections stable. If a joint
attribute name is already used, a new `pd_<output>` attribute is created (with a
numeric suffix if necessary); the existing attribute/value/driver is preserved.
Mirrored poses expose their outputs on the corresponding destination joint.

Pose/system removal deletes only owned display attributes still connected to
their expected cone output. Attributes disconnected or given another input are
kept. If a joint display output drives an external consumer, strict removal stops so
that connection is not lost. Locked/referenced joints keep their weights on the
cone; explicit Connect reports why custom joint attributes cannot be added.

Python: `master_rigging_toolkit.expose_pose_driver_joint_weights(group)`.
Maya smoke: `maya_smoke_test.run_pose_driver_joint_weights()` checks live values,
Normalize, unlocked/keyable Channel Box attributes, collisions, recapture, removal and
Undo/Redo. **201 local regression tests pass**; Maya runtime testing is pending.

## Capture with blank fields (revision 2.12)

In a target pose card, leave **Target pose object** empty and click **Capture
pose**. The tool samples the current joint rotation and applies the configured
minimum-distance check. Leave **Pose name** empty too to generate a name such as
`arm_L_nX20_pY10_pZ0`. No target-object warning is shown for this workflow.
A supplied name is kept. A supplied target object always takes priority over
current-joint sampling. **Update pose / angle** uses the same routing and keeps
existing output names and connections stable. The separate **Capture rotation**
section remains available.

## Capture target poses by rotating the joint (revision 2.11)

Build the start with the joint at its default rotation. In **PoseDriver → Capture
rotated joint**, rotate that joint and press **Capture rotation**. A pose is added
only when its cone direction is at least **Minimum distance** (default **15°**)
from the default and every existing target pose. If it is too close, the status
reports the nearest pose and actual angle; no nodes or attributes are created.
Exact duplicates are rejected even if Minimum distance is 0. **Falloff angle**
controls weight falloff independently of this spacing rule.

The name is optional. Blank names use the joint's basename and signed changes in
its X/Y/Z rotation channels relative to the stored default, for example:
`arm_L_nX20_pY10_pZ0`. `n` means negative and `p` positive. Values are degrees,
wrapped to [-180, 180) and rounded to whole degrees for names only. The center's
actual direction is not rounded. An automatic-name collision receives `_2`,
`_3`, etc.; existing outputs are preserved. Names remain stable during recapture.

Spacing uses the angle between cone directions, not Euler-channel distance.
Since this weight system ignores twist around X, X-only twist cannot create a
new distinct pose. The captured reference follows parent motion, so moving or
rotating the parent does not turn the default into a new target. Centers remain
fixed under the reference frame while you rotate the joint for further captures.
The joint's transform channels and animation inputs are read without modification;
pose weight display attributes are added as described above.

For existing setups built before revision 2.11, restore the original default
rotation, then press **Set default from current joint** once. Earlier versions
did not save the default rotation channels, so automatic names cannot reconstruct
them reliably. This explicit action changes the spacing/naming reference only;
existing centers and weight outputs stay intact. A supplied name can still be
used on an older setup. After changing rotateOrder, set the default again before
using automatic names.

The target-object workflow remains available. Its explicit target captures do
not use the rotation-spacing filter, but their saved centers participate in the
filter for subsequent joint captures. The cards' **Capture current joint** and
**Recapture current joint** buttons use the same Minimum distance; recapture
excludes its own saved center and preserves the output plug.

```python
pose = master_rigging_toolkit.capture_pose_driver_rotation(
    group, name="", minimum_angle=15, radius=45)
```

Revision 2.11 passes **184 local regression tests**. Maya/PySide runtime and UI
verification are pending; `maya_smoke_test.run_pose_driver_rotations()` covers
native capture, default/near-duplicate rejection, names, parent motion, weights,
jointOrient and Undo/Redo with temporary nodes.

## PoseDriver mirror (revision 2.10)

Load the source setup in **PoseDriver**, then use **Mirror / Search counterparts**:

1. Set **Search** and **Replace** (defaults `_L` and `_R`). Tokens are literal;
   namespace prefixes are preserved. **Swap tokens** reverses the direction.
2. **Search / Preview** resolves the opposite joint and each saved target object.
   Missing/ambiguous counterparts stop the operation. Objects whose names and
   ancestor paths do not contain the Search token are shared targets and reused.
3. Enable **Flip cone offset +1 ↔ −1** to use the opposite signed X offset.
   With it disabled, the destination uses the source's signed offset.
4. **Mirror / Update** builds the destination if absent or updates matching pose
   names/weight outputs. Existing plugs, downstream connections and extra
   destination poses are kept. New setups copy Normalize; existing setups keep
   their current Normalize value/driver. The source setup stays loaded.

Put a new destination joint at its intended start pose before building. Named
target poses use the matching object's current world position: the center sits
exactly one unit along the **destination joint → matched target** ray, independent
of the live cone. For poses captured without a target object, **Joint-only poses**
reflects the saved world direction across X (YZ plane), Y (XZ plane), or Z (XY
plane), then places a unit center at the destination origin. It does not recapture
the current joint direction. Target objects and joint transforms are preserved;
new mirrored weight display attributes are added to the destination joint.

Repeat Mirror from the source setup to update the same destination outputs.
To mirror back, load the opposite setup from **Saved setups**, then Swap tokens.
Capture changes in the source cards before mirroring; unsaved UI rows are omitted.
Maya Undo must be enabled so a failed edit can roll back the complete operation.

The same workflow is available through Python:

```python
plan = master_rigging_toolkit.plan_pose_driver_mirror(group, search="_L", replace="_R")
result = master_rigging_toolkit.mirror_pose_driver(group, search="_L", replace="_R",
                                                 flip_axis=True, reflection_axis="X")
```

Revision 2.10 passes **165 local regression tests**, including 15 mirror checks.
Maya/PySide runtime and UI verification are pending. In Maya, run
`maya_smoke_test.run_pose_driver_mirror()` to verify native weights, repeat/reverse
updates, exported consumers, and Undo/Redo using temporary nodes only.

## Install and launch

**When updating from revision 2.3 or earlier, replace the script and restart Maya
once before loading it.** Earlier live windows retain their old close handler and did not
record the original native parents. The new launcher refuses to destroy an old
window during hot reload and requires a fresh Maya session instead.

1. Extract this package.
2. Keep all companion Python files beside `master_rigging_toolkit.py`. Copy the
   complete folder's contents into your Maya user scripts directory, or add the
   extracted folder to `sys.path`. You can find the user scripts directory with
   `maya.cmds.internalVar(userScriptDir=True)`.
3. Run the following in Maya's Python Script Editor, or use it as a shelf command:

```python
import master_rigging_toolkit
master_rigging_toolkit.show()
```

After replacing a previously imported copy:

```python
import importlib
import master_rigging_toolkit
importlib.reload(master_rigging_toolkit)
master_rigging_toolkit.show()
```

Alternatively, paste the complete script into Maya's Python Script Editor and
execute it. Cleanup and Skinning Tools also require their companion files in
your Maya scripts directory or another `sys.path` folder. Importing the module
alone does not open a window; `show()` does.
No extra Python packages or Maya plugins are required.

## UI changes

- Fourteen workflows share one sidebar: Controllers, Mirror shapes, Skin weights,
  Skinning Tools, Cleanup, Modular Rig, Custom attributes, Constraints, Naming & hierarchy, FK & Aim, Group SDK, Vertex
  constraints, PoseDriver, and Guides & joints.
- The search field filters workflow names and keywords. `Ctrl+K` focuses it;
  `Enter` opens the first match. Searching does not build hidden panels.
- Pages are created on first use and retained while the window is open. The
  initial window builds only the selected workflow.
- Shared colors, spacing, focus borders, primary/destructive button styles,
  and descriptive selection-button tooltips replace the PySide panels' repeated
  inline style strings.
- Guide tools and Maya command pages scroll. Frequently used fields expand with
  the available width. SDK cards have working expanded/collapsed indicators.
- Window geometry and the last workflow are remembered using local preferences.
- The binding import supports PySide6/shiboken6 and falls back to
  PySide2/shiboken2. Both binding paths require validation in the relevant Maya
  version; they were not exercised in this environment.

## Code and behavior changes

### Fixed: closing the toolkit and Maya shutdown

The earlier revision synchronously reparented/deleted Maya-owned controls inside
the dialog's `closeEvent`, restored them to the host window rather than their
original native parent, and enabled Qt automatic deletion on close. It also set
the closed guard only after cleanup. These are unsafe lifetime/event-ordering
patterns and a plausible cause of the reported Maya crash. No Maya crash log was
provided and the crash could not be reproduced in this environment, so this is
not a confirmed diagnosis of every possible native failure.

The revised lifecycle:

1. Records the exact native Qt parent when a Maya page is first constructed.
2. Marks the dialog closed before callbacks or cleanup can reenter it.
3. Stops all child timers and blocks field signals, including focus-loss
   `editingFinished` callbacks which could otherwise edit the scene on close.
4. Removes scene jobs/save callbacks and flushes pending cached settings on an
   ordinary tool close. Typed cache spin-box values are committed before the
   signals are muted. Cache/settings errors cannot prevent scheduled cleanup.
5. Accepts/hides the dialog without changing parents or deleting widgets inside
   `closeEvent`. Automatic `WA_DeleteOnClose` and `WA_QuitOnClose` are disabled.
6. On the next Qt event, removes pages from the stack and returns native widgets
   to their exact original parent. Python-created Qt pages use `deleteLater`;
   Maya-owned pages do not.
7. Queues native host deletion on Maya idle and Qt deletion of the empty shell
   after all native widgets have been detached.
   Cleanup is idempotent. If a native owner is unexpectedly invalid, the shell
   is retained rather than forcing deletion of a Maya-owned orphan.
8. On Maya shutdown, stops callbacks/timers and restores native parenting without
   performing scene writes, `deleteUI`, or late Maya callback-removal commands.
   Maya handles its own native host destruction. Already queued host deletion
   also checks the shutdown guard and skips manual deletion.

One lightweight process guard remains on QApplication across module reloads to
detect Maya exit/aboutToQuit. Per-window scene/exit hooks are removed after a
normal close. The launcher does not close the same window twice, dereference
invalid Qt wrappers, or create UI while Maya is exiting.

This fixes identified code risks. Native behavior still requires verification in
the user's Maya/Qt version. Existing rig/skin/Locator View operations are unchanged.

### New: PoseDriver

**PoseDriver** is a separate workflow. Its left pane contains the joint/start
setup and target pose cards; its right pane lists output weights, Normalize,
and the generated cone. The scene owns the setup: it uses standard Maya nodes,
with no plugins, expressions, evaluation callbacks, or UI polling. Weights
continue evaluating when the window is closed and persist in saved scenes.

Start setup:

1. Put the target joint in its start pose, then **Get selected**.
2. Choose **+X (1)** or **−X (−1)**.
3. **Capture start / Build** creates a start locator matched to the joint's
   world position/rotation. A parentConstraint follows the joint's parent with
   maintainOffset=True. A root joint has a fixed world reference instead.
4. A rotation group inside that frame follows the joint using orientConstraint;
   its child locator, named with a `cone` suffix, is offset along the chosen X
   axis. Cone transforms are locked; source joint transform channels are kept intact.

Capture targets (placement corrected in 2.7; capture routing corrected in 2.9):

- **Target pose object** defines a direction from the source joint, rather than
  the final locator position. Click **Get selected**, then **Capture pose**.
  For joint world position J and object position T, the generated center is:

  ```text
  center = J + normalize(T - J)
  ```

  This puts it exactly **1 scene unit from the joint** along that ray. The
  external object's distance is ignored; a coincident object is rejected.
  The previous implementation copied T directly and did not enforce this
  required unit offset. That placement is corrected; the reported native zero
  weight has not been reproduced here and is not claimed resolved by testing.
- **Capture pose** is the primary button. When the target-object field is filled,
  it uses that object's direction even when the source joint/cone points
  somewhere else. Earlier Capture joint button handlers ignored a filled
  field, creating a center along the current cone and giving that pose raw
  weight 1. The UI and update API now always give a supplied target priority.
  When the field is blank, the primary button captures the current joint instead
  and generates a name if blank, subject to the configured minimum pose distance.
- To intentionally sample the current source rotation, clear the target-object
  field and use **Capture current joint** (or **Recapture current joint**). That
  secondary action is disabled while the field is filled. Its center is J plus
  the normalized signed world X axis, accounting for jointOrient, world rotation
  and the axis choice. Joint scale does not change the center distance. Raw
  weight 1 immediately after this explicit current-pose capture is expected.
- Both methods create an owned center locator under the start frame. It follows
  parent motion with that frame and remains fixed relative to the reference
  while the source joint rotates. The external target object is preserved and
  is not a live input. Its UUID is retained in the card for later updates.
- **Update target / angle** recomputes the one-unit center toward the object in
  the field. **Recapture current joint** (empty target field) replaces it with the current signed joint X
  direction. Both keep the output plug and graph stable for downstream users.
  Captured pose names remain fixed; create another pose for a new output name.
- **Falloff angle** remains an angular cone half-width in degrees, from 0.1 to
  180: raw weight 1 at the target direction, 0 at/outside its radius. New poses
  calculate this angle from the default unless a manual angle is chosen.

For an existing 2.6–2.8 setup, replace/reload the script and reopen the toolkit
(verify the title says **v2.23**), **Load existing**, choose each original green
pose object again, then **Update target / angle**. Existing weight plugs and
connections are retained. If the old parented rotation group has a local position offset, capture
or update realigns that owned group to the start origin, within the same undo
chunk; locked/driven translation refuses the edit. New rotation and target
container groups explicitly start with zero translation/rotation and unit
scale. The source joint is never moved. If its translation differs from the
captured frame origin, restore that translation or rebuild the reference before
capturing rotation poses.


For Smooth cosine mode, with normalized live direction v and target direction t, radius r:

```text
u = clamp((dot(v, t) - cos(r)) / (1 - cos(r)), 0, 1)
rawWeight = u*u*(3 - 2*u)
weight = (1 - Normalize)*rawWeight + Normalize*(rawWeight / sumRaw)
```

When sumRaw is zero, all weights remain zero. Zero-length target directions
also return zero safely. Vector lengths are computed numerically so weights do
not depend on the scene's angle or distance display units.

The cone exposes `normalize` (keyable, 0–1), unlocked/keyable `rawWeightSum`, and one
`<poseName>Weight` and `<poseName>WeightRaw` attribute per pose. Spaces and
punctuation in names become underscores; collisions are rejected. These weight
plugs can drive later rig logic. **Set Normalize** saves the pane's numeric
value; you can also edit/animate `cone.normalize` directly in Maya.

At Normalize=0 weights are independent and each target center gives raw/final
weight 1. At Normalize=1 active outputs sum to 1; overlapping targets share
that total, so a final center weight may be below 1. Intermediate values blend
the two behaviors. With only one active target, full normalization gives that
pose weight 1 anywhere inside its falloff; use partial/zero normalization when
its proximity falloff should remain visible in the final output.

The method measures swing along the chosen X axis. **Twist around that axis is
ignored**, including 180-degree changes in twist. It is not a full-orientation
RBF or quaternion pose matcher. Joint translation is also not used as a pose
dimension: the cone rotates around the captured start-frame origin.

**Load existing** finds the joint-linked setup; **Saved setups** lists scene
setups. UUID records survive renames and reopen. The weights table is a
snapshot: **Refresh weights / setups** reads current values and reloads scene
pose records after posing or Undo/Redo. Refresh discards unsaved card rows;
capturing one card retains other unsaved new cards. Form drafts are not saved
in the scene. No scene edits occur on UI focus loss or window close.

**Remove pose** deletes its output attributes, center and owned utility nodes,
and removes its contribution from the raw sum. Other poses keep their output
plugs. **Remove PoseDriver system** deletes all owned DAG/DG nodes while
preserving the source joint and external center objects. Strict API removal refuses generated weights with external consumers; UI system
removal can retain those consumers' current values as described above.
Foreign objects parented into generated hierarchies, locked nodes, and invalid
metadata also block deletion. Use these buttons instead of manually deleting
just the DAG group, which can orphan utility nodes. Build, Capture, Update,
Normalize and Remove each use a single undo chunk.

To change the start reference or +X/−X axis, remove the current setup and build
at the new start pose; Load existing preserves the captured reference. If the
source joint is reparented, rebuild to follow its new parent. No automatic
reference rebasing occurs, so saved target meanings remain stable.

Python helpers: `build_pose_driver`, `find_pose_drivers`, `list_pose_drivers`,
`add_pose_driver_pose`, `update_pose_driver_pose`, `remove_pose_driver_pose`,
`set_pose_driver_normalize`, `remove_pose_driver`, and reference math
`pose_driver_weights` and `pose_driver_unit_center`.

Run native validation in Maya with:

```python
import maya_smoke_test
maya_smoke_test.run_pose_driver()
```

It tests initial setup, actual node weight evaluation against reference math,
falloff, zero directions, partial/full normalization, jointOrient, parent
motion, twist exclusion, stable recapture and output consumers, rename handling,
cleanup and Undo/Redo. Native Maya/PySide tests were not run here.

### New: Three-Joint IK in Guides & joints

The **Three-Joint IK** section has separate **First joint**, **Second joint**,
and **Third joint** fields, each with a **Get selected** button. Select one joint
at a time and load its corresponding field. Use three different joints directly
parented in that order, with a visible bend at the second joint.

- **Control size** sets the radius of the end control and the pole control size.
- **Pole distance** extends the pole outward from the second joint, in multiples
  of the total two-bone chain length (default 1).
- **Build IK** creates one separate control group, zero-offset groups, an end
  controller at the third joint, a diamond pole controller, an `ikRPsolver`
  handle, a pole-vector constraint, and an end-orientation constraint. The joint
  hierarchy stays where it is. Move the end controller to position the tip;
  rotate it to orient the third joint. Move the pole controller to set the bend.
- **Remove IK** uses **First joint** to find only this tool's linked system,
  deletes generated nodes (including the effector and the orientation constraint
  which Maya places outside the control group), and keeps the joints at their
  **current evaluated world position and orientation**. The old behavior reset
  joints to their pre-build pose; revision 2.8 removes that reset. It samples
  all joints before driver deletion, applies their current world rotations from
  root to tip after deleting the system, and verifies the world matrices and
  jointOrient/rotateAxis definitions. Temporary matched transforms and orient
  constraints compute the corresponding local FK rotations through Maya's joint
  orientation/parent math, then are removed immediately. It does not write translation or scale,
  add keys, restore old IK blend values, or reparent the joints. This allows
  normal locked translation/scale channels to remain locked. Generated control
  animation is removed with the generated controllers.
- If pose application or validation fails, a top-level Remove operation rolls
  back its own undo chunk when Maya undo is enabled, restoring the IK system.
  It never undoes a caller's open chunk or unrelated prior work. For calls
  inside another undo chunk or with undo disabled, failures are reported and
  automatic rollback is unavailable. The build-failure cleanup still restores
  its pre-build snapshot; that is distinct from the normal Remove action.
- Build and Remove are each one undo step. Repeated Build is blocked until you
  remove the existing system. UUID ownership and the first-joint message link
  allow removal after renaming joints or generated nodes and after reopening
  the saved scene. Fields themselves are not scene-cached.

Pole calculation: for world positions A, B, C, compute the projection P of B
onto the line A–C. The pole is B + normalize(B–P) × (|AB| + |BC|) × distance.
This uses the bend plane rather than a fixed world axis. Nearly straight chains
and overlapping joints are rejected before any scene edit; bend the middle
joint slightly to establish a direction first.

Build also rejects locked, instanced, referenced, animated/constrained joints
and chains overlapping any existing IK handle. Removal checks ownership and
locks before deleting: move unrelated objects out of generated groups and
remove any new external joint drivers first. Shared global solver nodes are
owned by Maya and are not deleted.

Python helpers: `calculate_guide_ik_pole`, `plan_guide_ik`, `build_guide_ik`,
`find_guide_ik_systems`, and `remove_guide_ik`.

To check the solver in Maya, run:

```python
import maya_smoke_test
maya_smoke_test.run_guide_ik()
```

This creates only temporary test nodes, exercises initial pose preservation,
end and pole motion, third-joint orientation, ownership protection, renaming,
current-pose preservation on removal, and Undo/Redo, then cleans its test nodes. Native solver and UI behavior
were not run in the development environment, which has no Maya or PySide.

### New: Locator View in Guides & joints

The **Locator View** section sits below the existing Generate Guide Locators
section. It provides a joint field with **Load selected**, a positive size
field, **Include child joints**, a matching-mode menu, and **Generate / Delete
View** buttons.

1. Select one joint and click **Load selected** in Locator View.
2. Choose the locator size. Leave **Include child joints** off for just that
   joint, or enable it for all descendant joints, including joints below
   intermediate transform groups.
3. Choose **Constraints · follow joints** or **World matrix · snapshot**.
4. Click **Generate**. All generated locators are direct children of one
   separate world-level group; the source joint hierarchy is not reparented.
5. Click **Delete View** to delete only that field's joint-linked view groups.

Matching behavior:

- Constraints first snap the locator to the joint world matrix, then use parent
  and scale constraints with no offset. Each joint drives its corresponding
  locator's translation, rotation, and scale. This mode follows later joint
  movement; it does not continuously copy arbitrary shear matrices.
- World-matrix mode copies the full current world matrix once. It is a snapshot
  and does not follow subsequent joint edits.
- Size is set on the locator shape's `localScaleX/Y/Z`. Joint world scale can
  also affect the displayed world size. This size control is separate from the
  existing guide locator Radius field.

Regenerating replaces the previous view for the chosen root joint; the old view
is kept until the new one is built. The tool tags its groups, links them to the
root joint through a message connection, and records generated member UUIDs.
Name changes do not make groups collide with unrelated objects. If unrelated
objects are added inside a view group, or the group/member node is locked,
Delete/Generate stops before deleting it. Move unrelated objects out or unlock
the generated nodes first. Existing legacy `*_GuideLoc` objects and views for
other roots are not deleted.

Each successful Generate or Delete action uses one undo chunk and restores the
existing selection. Partial build failures clean up the new group and loose
locators. An unexpected Maya failure during deletion remains in the closed undo
chunk and can be undone. Deleted source joints cannot be loaded into this field;
their orphaned view group can be deleted manually in Maya. Locator View fields
reset when the window or scene is reopened.

Direct API usage:

```python
import master_rigging_toolkit as toolkit

# One locator per joint, following the whole chain:
view = toolkit.generate_locator_view(
    'root_joint', size=0.5, include_children=True, match_mode='constraints'
)

# Current world-space snapshot of just the root:
view = toolkit.generate_locator_view('root_joint', size=1.0, match_mode='world_matrix')

toolkit.delete_locator_view('root_joint')
```

### New: Custom attributes — target drives source

Open **Custom attributes** in the sidebar:

1. Load the **Source controller**, which contains the custom attributes.
2. Load the **Target controller**, which will receive the attributes and drive
   the source. **Load both from selection** expects source first, then target.
3. Click **Scan custom attributes**, inspect the statuses, and check the desired
   attributes.
4. Click **Copy & connect · Target → Source**.

For example, copying `source_ctrl.ikBlend` creates `target_ctrl.ikBlend` and
connects `target_ctrl.ikBlend → source_ctrl.ikBlend`. Changing the target then
drives the source. Translate, Rotate, Scale, Visibility, and all other built-in
attributes are excluded using Maya's user-defined-attribute discovery. A custom
attribute cannot overwrite an identically named built-in attribute on the target.

Supported types:

- Scalar numbers, bool, enum, angle, distance, and time.
- String and matrix data.
- Numeric 2/3-component attributes (`double3`, `float3`, and corresponding
  double/float/long/short variants), with child definitions and connections.

Definitions preserve long/short/nice names, attribute types, enum choices and
explicit enum values, numeric defaults, hard/soft limits, hidden/color/filename
flags, and keyable/Channel Box settings. New target attributes receive the
source's current values by default, before connections are made.

- Compatible existing target attributes are reused and retain their current
  values. They drive source immediately, so differing target values can change
  the source on connection. Incompatible types, enums, limits, or child layouts
  are reported and skipped; existing target definitions are not overwritten.
- Existing source inputs are preserved by default. Enable **Replace existing
  incoming connections on source attributes** to replace them explicitly.
- Locked source attributes default to **Copy only** when the target attribute
  is new. This preserves locked enum separators/labels without trying to drive
  a locked plug. Enable **Unlock selected source attributes** to unlock and
  connect instead. Entire locked nodes remain blocked.
- Already connected target → source plugs are left alone. Direct reverse
  connections are blocked to avoid connecting both directions. More complex
  dependency/evaluation behavior still needs validation in the actual rig.
- Numeric compounds connect matching children. Existing compound-parent inputs
  must be disconnected separately before this tool can connect the children.
- Multi attributes, typed arrays, message attributes, arbitrary compounds,
  geometry/plugin data, and unreadable/unwritable/unconnectable attributes are
  displayed as **Unsupported**; they are not silently converted.
- On an individual attribute failure, the tool attempts to remove its new
  connections/target definition and restore touched source inputs, values, and
  locks. Other successful attributes remain in the action's single undo chunk.
- Controller fields reset on window/scene reopen; this tool adds no settings
  cache to the scene.

Direct API usage:

```python
import master_rigging_toolkit as toolkit
toolkit.copy_custom_attributes_and_connect('source_ctrl', 'target_ctrl')

# Select specific top-level custom attributes:
toolkit.copy_custom_attributes_and_connect(
    'source_ctrl', 'target_ctrl', attributes=['ikBlend', 'space']
)
```

### New: Hierarchy constraints

Open **Constraints** in the sidebar; hierarchy matching is below Quick constraint:

1. Select the old rig's root and click its **Load selected** button.
2. Select the new rig's root and click its **Load selected** button. Alternatively,
   select old then Shift-select new and click **Load both from selection**.
3. Choose a matching mode and click **Preview matches**.
4. Inspect the old → new pairs and statuses, then click **Create hierarchy constraints**.

The old hierarchy drives the new hierarchy. Parent constraints, scale constraints,
maintain offset, and inclusion of the roots are enabled by default.

- **Relative names** matches descendant paths below the roots. Root names may
  differ. Sibling order does not affect matching. Namespaces are ignored by
  default; uncheck that option to require namespace matches.
- Optional source-name search/replacement handles tokens such as `old_` →
  `new_`. It changes matching keys only; it does not rename scene objects.
- **Structure / child order** allows different descendant names. It checks the
  full branching pattern and transform/joint types, then pairs corresponding
  child positions. Reordered siblings with identical topology remain ambiguous
  in this mode: inspect the preview to confirm their intended correspondence.
- Shapes and constraint nodes are excluded. Identical/overlapping roots,
  instanced objects, ambiguous roots, duplicate normalized paths, and hierarchy
  mismatches are rejected. Equal node counts alone are insufficient.
- Locked nodes/channels and incoming channel connections, including animation,
  appear as blocked pairs. Existing constraints/connections are not replaced.
  A second run skips already constrained pairs instead of duplicating constraints.
- **Skip blocked pairs** defaults to on. Turn it off to stop before creating
  anything if preflight finds a blocked pair, or to stop at the first runtime
  failure. Earlier successful pairs remain in the single undo chunk.
- If scale creation fails after creating a parent constraint, only the newly
  created constraints from that pair are removed. Other constraints remain.
- The preview is invalidated when root fields/options change. Creation rechecks
  the current scene. Double-click a driver/driven cell to select that object in
  Maya; hover for full paths/reasons.

The API is also available directly:

```python
import master_rigging_toolkit as toolkit

# Matching descendant names, with optional namespace removal:
toolkit.constrain_matching_hierarchies('old_Root', 'Root')

# Same branching, different descendant names; explicitly use child order:
toolkit.constrain_matching_hierarchies(
    'old_Root', 'Root', match_mode='structure', maintain_offset=True
)
```

Hierarchy root fields are session UI state. They reset when the window or scene
is reopened; no hierarchy constraint settings cache is written to the scene.

### Namespace skin transfer

The original code used `indexForInfluenceObject()` results as dense weight-array
offsets. Logical influence indices can contain gaps, so that can address the
wrong weight columns. It also called API `setWeights()` without a custom undoable
command; opening a Maya undo chunk does not make that API write undoable.

The new implementation uses `skinPercent(transformMoveWeights=[source, target])`
on an explicit full-mesh vertex range. It makes one bulk native call per matched
influence pair, eliminating the Python loop over every vertex and influence. All
influence additions, weight moves, and optional source removals are grouped into
one command-level undo chunk.

- Namespace matching uses the influence leaf's namespace prefix.
- Source/target namespaces must differ.
- Invalid component selections, ambiguous names, multiple shapes, and multiple
  skinClusters are rejected before changes begin.
- Missing target influences are reported and skipped, preserving their sources.
- Locked source/target weights block the operation before any scene changes.
- Source influences are removed only after all bulk moves finish successfully.
- If a native command fails midway, earlier changes remain in the closed undo
  chunk and can be undone. There is no automatic rollback on exception.

The smoke test verifies merging into an already weighted destination, adding a
new destination influence, sparse influence indices, and native Undo/Redo.
Those native checks have not been run here.

### Scene settings and lifecycle

- SDK and vertex cards share one cache implementation. A write serializes once,
  creates the attribute when needed, and skips an unchanged payload.
- Existing cache node names, JSON field names, and legacy node types are
  preserved. Newly created caches are `network` nodes, so they do not add
  transforms/locators to the hierarchy or alter the selection.
- Card changes save after a short debounce; pending changes flush before scene
  save and window close. Passive UI cache writes retain the existing convention
  of staying outside the scene undo history. Cache writes made during a tool
  action join that action's undo chunk.
- Malformed or unwritable caches are reported and protected from automatic
  overwrite. An explicitly saved empty list remains empty on reopen.
- New/open scene events discard the previous scene's panels and stop pending
  cache/radius timers before rebuilding the current workflow.
- Each embedded Maya page owns a unique hidden host. Closing restores its exact
  native parent, defers deletion to Maya idle, and removes the window's hooks.
  Rerunning the launcher closes the previous fixed-version window once.

### Guide controls

- Radius edits are debounced, and unchanged attributes are skipped. Only locator
  shapes on matching guide transforms are edited.
- Radius and controller-size fields require a positive value.
- The key cleanup tool now defaults to selected objects and their descendants.
  The existing all-scene option remains available.

Eight key rig-building methods were compared by Python AST and remain unchanged:
controller generation, FK generation, curve aim, distance aim, SDK execution,
vertex constraints, joint orientation, and object-axis joint rotation.
This is a focused refactor, not a complete replacement of the legacy Maya
command forms or a rewrite of the rig mathematics.

## Validation

Completed in this environment:

- Python syntax compilation of the toolkit and both test scripts.
- **303/303 dependency-free regression tests passed**, covering bulk-command
  orchestration, undo-chunk cleanup, preflight validation, namespace matching,
  missing targets, cache schema handling, redundant-write prevention, hierarchy
  pairing with reordered siblings, branching/type mismatches, normalization
  collisions, blocked/animated channels, repeat runs, failed-pair cleanup,
  custom attribute discovery/definitions, target-to-source direction, vectors,
  existing inputs, source locks, failed attribute cleanup/restoration, Locator
  View scope/grouping/size, constraint direction, snapshot matching, repeat
  generation, scoped deletion, foreign/locked descendants, failure cleanup, and
  18 lifecycle cases for ownership ordering, repeated close, shutdown, focus-loss
  callbacks, cache errors, invalid wrappers/owners, and legacy-window handling;
  plus 22 IK cases for projection geometry, input validation, explicit RP setup,
  control/constraint wiring, selection/undo grouping, failed-build cleanup,
  ownership protection, current-pose preservation, rename handling, safe handle/effector
  deletion order, locked translation/scale, sampling before deletion, guarded
  removal rollback, and existing-system detection; plus 113 PoseDriver cases for
  falloff/normalization math, graph wiring, source preservation, captures/updates,
  output stability, sum bookkeeping, failure cleanup, consumer protection,
  zero directions, source links, renames, metadata, removal, one-unit ray
  projection, signed world axes, explicit group origins, and origin repair
  rollback/locking, actual UI capture-method routing, target-field priority
  for legacy handlers/API flags, static centers independent of cone direction,
  missing target rejection, prevention of live-cone target selection, and
  15 mirror cases for counterpart search, namespace/ambiguity handling,
  axis flips, saved-direction reflection, repeat/reverse updates, stable
  consumers, collision checks, preflight failures, and full rollback; plus
  19 rotation-capture cases for default metadata, direction spacing/boundaries,
  custom thresholds, auto names, degrees/radians, wrapped deltas, suffixes,
  external-center comparisons, recapture, old setups, parent motion, matrix
  transforms, signed axes, rotateOrder, UI routing, corrupt data and undo scope.
- AST comparison of the eight rig-building methods listed above.

These regression tests use fake Maya commands. They do not render Qt, evaluate
Maya deformation, measure runtime performance, or validate native Undo/Redo.
Maya and PySide are not installed in this environment.

To run the included real-Maya smoke test, put `maya_smoke_test.py` next to the
toolkit in the scripts directory, then run:

```python
import maya_smoke_test
maya_smoke_test.run()
```

The feature test uses a unique temporary namespace and cleans up its fixture nodes.
It opens/closes the toolkit and invokes Undo/Redo for the test transfer without
opening a new scene. It exercises skin transfer, hierarchy constraint
creation/driving/Undo/Redo, custom attribute definitions/direction/Undo/Redo,
Locator View matching/following/grouping/deletion/Undo/Redo,
the hierarchy/custom previews, and page lifecycle; it does
not execute every rig-building feature. Use a test scene for the first run.

Then check visually:

1. Resize the window and inspect all twelve workflows and scrollbars.
2. Search `skin`, `orient`, and `distance`; verify `Ctrl+K` and `Enter`.
3. Add, remove, collapse, and edit SDK/vertex cards; save and reopen the scene.
4. Change guide radius; check that repeated identical values add no scene edits.
5. Generate a small controller, FK, curve-aim, and distance-aim example, then use
   Undo/Redo once per action.
6. Open a second scene with different caches and verify that old setup fields
   are not written into the new scene.
7. Reopen the window several times and confirm that it remains a single window.
8. On Constraints, test the quick Driver/Driven tool and both hierarchy root pickers, Load both, Swap roots,
   both match modes, name replacement, Preview, blocked targets, creation, and
   Undo/Redo. Verify that old drives new and that Maintain offset preserves the
   initial placement.
9. On Custom attributes, verify source/target pickers, selected attributes,
   numeric/enum/vector/string types, locks/input replacement, repeat runs, and
   Undo/Redo. Change a target attribute and verify the source follows; ensure
   built-in transform attributes remain unconnected.
10. On Guides & joints → Locator View, test root-only and child-joint scope,
    both matching modes, size, replacement, Generate/Delete Undo/Redo, and
    deletion protection for unrelated objects parented inside a view group.
11. On Guides & joints → Three-Joint IK, load the three fields individually,
    adjust size and pole distance, Build, move both controllers, and Remove.
    Verify current world pose preservation on Remove, straight-chain rejection, and one-step Undo/Redo.
12. On PoseDriver, build a +X and a −X setup; capture multiple targets, move
    their locators, recapture a used output, edit falloff, set Normalize to
    0/0.5/1, and rotate the source parent. Close the UI and verify the output
    attributes still evaluate. Save/reopen, Load existing, Refresh, and test
    pose/system removal and Undo/Redo with external consumers disconnected.

To run only the native Locator View checks:

```python
import maya_smoke_test
maya_smoke_test.run_locator_view()
```

To run only repeated native UI close/reopen checks (no rig/mesh fixtures):

```python
import maya_smoke_test
close_test = maya_smoke_test.run_close_cycles(cycles=5)
```

This test is asynchronous so normal Qt/Maya idle ordering is preserved. Wait for
the printed PASS messages. `close_test['running']` becomes False when finished;
`close_test['error']` is None on success. It checks all twelve workflows and the
five native hosts, plus actual Qt widget release and scene-job cleanup.
It does not call Maya quit or simulate app exit in the live application.

After close cycles pass, reopen the toolkit and exit Maya normally with a saved
scene. Test both the Guides page and a native page such as FK & Aim. If Maya still
crashes, capture the Maya version/OS and crash log or stack trace, and specify
whether the trigger is the toolkit X button, rerunning the script, or Maya quit.

The package includes the original uploaded source as `original_source.txt` for
comparison or rollback.

## API references

- Autodesk's [skinPercent documentation](https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Tech-Docs/CommandsPython/skinPercent.html)
  documents undo support and bulk influence transfer.
- Autodesk's [MFnSkinCluster reference](https://help.autodesk.com/cloudhelp/2024/ENU/MAYA-API-REF/cpp_ref/class_m_fn_skin_cluster.html)
  describes physical influence ordering for weight arrays.
- Autodesk's [Maya Qt6 migration guide](https://help.autodesk.com/cloudhelp/2025/ENU/Maya-DEVHELP/files/Whats-New-Whats-Changed/2025-Whats-New-in-API/Qt6Migration.html)
  describes the PySide6/shiboken6 migration.
- Autodesk's [parentConstraint documentation](https://help.autodesk.com/cloudhelp/2024/ENU/Maya-Tech-Docs/CommandsPython/parentConstraint.html)
  and [scaleConstraint documentation](https://help.autodesk.com/cloudhelp/ENU/MayaCRE-Tech-Docs/CommandsPython/scaleConstraint.html)
  document the new hierarchy action's native commands and offset/undo support.
- Autodesk's [addAttr documentation](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/addAttr.html)
  and [attributeQuery documentation](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/attributeQuery.html)
  document custom attribute definitions and metadata queries.
- Autodesk's [xform documentation](https://help.autodesk.com/cloudhelp/2024/ENU/Maya-Tech-Docs/CommandsPython/xform.html),
  [locator node documentation](https://help.autodesk.com/cloudhelp/ENU/MayaCRE-Tech-Docs/Nodes/locator.html),
  and [ls documentation](https://help.autodesk.com/cloudhelp/ENU/MayaCRE-Tech-Docs/CommandsPython/ls.html)
  describe world matrices, locator shape size, and node UUIDs used by Locator View.
- Qt's [QObject lifetime documentation](https://doc.qt.io/qt-6/qobject.html) and
  [QWidget close documentation](https://doc.qt.io/qt-6/qwidget.html), plus Autodesk's
  [MSceneMessage reference](https://help.autodesk.com/cloudhelp/2026/ENU/MAYA-API-REF/py_ref/class_open_maya_1_1_m_scene_message.html)
  and [evalDeferred documentation](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/evalDeferred.html)
  describe the event/ownership/shutdown mechanisms used by this fix.

PoseDriver node references:

- [Maya vectorProduct](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/Nodes/vectorProduct.html)
- [Maya remapValue](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/Nodes/remapValue.html)
- [Maya blendColors](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/Nodes/blendColors.html)
- [Maya multMatrix](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/Nodes/multMatrix.html)
