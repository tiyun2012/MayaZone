# PoseDriver SDK and curve mirror · Toolkit 2.35

Open **PoseDriver → Set Driven Key · pose weights and curve mirror**. The section
starts collapsed. It uses native Maya driven-key curves and separate scene
metadata; it does not change the PoseDriver weight calculation or lock attributes.

## First SDK

1. Build/load the PoseDriver and capture a target pose as usual.
2. Expand the SDK section, **Refresh poses**, choose a pose and output mode,
   then **Use pose output**.
3. Put the driven controller/SDK offset at its neutral pose. Select it and
   **Get driven**. The table captures its local neutral channels on first load.
   Loading an existing binding restores its saved neutral references instead.
4. Move that transform into its desired corrective pose and **Read driven values**.
   Alternatively edit the numeric **Driven value** cells. Neutral stays separate.
5. **Choose changed** enables only channels that differ from neutral, or toggle
   the Use checkboxes yourself. Scale is initially unchecked.
6. Set **Driver key weight**, usually 1. **Get live weight** samples the current
   PoseDriver output if you want to key its exact current weight instead.
7. **Set driven key** creates a neutral key at driver 0 and a key at the chosen
   driver weight. A new key at weight 0 must equal neutral. For an existing SDK,
   Set driven key adds/updates that sample without rebuilding the curve.

Once a channel has an SDK, Maya evaluates its value from the driver. Edit the
numeric Driven value cells to author further samples, or edit its curve in
Graph Editor. You do not need to disconnect/overwrite its driver to pose a sample.
**Read driven values** samples the currently evaluated transform, independently
of the Driver key weight field. The tool never forces the PoseDriver's live weight.
After keying, the table retains your authored sample values even if the live
weight is currently 0, so clicking Set driven key again does not silently flatten
that sample. **Key neutral at 0** explicitly updates the zero keys.

The Use checkboxes select channels for authoring/mirroring. Unchecking a row does
not disable an already connected SDK. **Select SDK curves** selects the binding's
curves for Graph Editor work. Tangent choices affect keys being authored; mirror
copies the curve data, including weighted tangent settings and infinity behavior.

## Raw versus normalized/final output

- **Raw** uses the cone's public `<pose>WeightRaw` attribute and is independent
  of the cone Normalize setting.
- **Weight · Normalize blend** uses its existing public `<pose>Weight` output.
  Set **Normalize = 1** in the normal PoseDriver section for fully normalized
  weights, or choose an intermediate blend there. Normalize 0 makes this final
  output equal the raw weight.

The SDK section deliberately preserves the setup's Normalize value. It does not
publish a second hidden solver or force every other consumer into normalization.
Choose the intended driver mode before creating the SDK. A different output is
another driver; it cannot silently take over the existing channel's curve.

## Explicit per-channel mirror rules

Local axes and neutral values can differ between sides. The mirror table stores
that relationship per channel instead of assuming every left/right pair uses
one sign pattern. Each row has an editable opposite channel of the same type:
translateX can map to translateZ, rotateX to rotateY, scaleX to scaleZ, etc.
Translation cannot map to rotation because those curves have different units.

Let f(w) be the source curve, a its **Source neutral**, and b the opposite
**Mirror neutral**:

| Value rule | Mirrored curve g(w) | Use |
| --- | --- | --- |
| Keep delta | b + (f(w) − a) | Same local direction with a different neutral offset. |
| Flip delta | b − (f(w) − a) | Opposite local direction around the two neutral values. |
| Keep values | f(w) | Copy absolute numeric curve values; neutral offsets are ignored. |
| Skip | No curve write | Leave that opposite channel alone. |

For example, a source neutral of 5 and peak of 12 has a +7 delta. With opposite
neutral 20, Keep delta gives 27; Flip delta gives 13. This avoids the incorrect
result from simply negating every absolute value around zero.

**Input axis** is a separate choice: Keep evaluates f(w); Reverse evaluates
f(1−w) before the value rule. Reverse means driver 0 ↔ 1, not a spatial side
mirror. Most corresponding PoseDriver weights use Keep. Reverse also swaps
pre/post infinity. Value rules transform the entire copied curve rather than
only its visible key values; existing source curves remain intact.

This first version uses explicit local channel mapping. It does not infer an
arbitrary reflection plane, mix several XYZ channels into one, or solve a full
world-space reflection of differently oriented Euler frames. The editable table
makes the intended local mapping reviewable for each control pair.

## Mirror workflow

1. Build/mirror the opposite PoseDriver setup first. Its named target pose must
   already exist. SDK mirroring does not create or recapture opposite poses.
2. Use **Find counterparts** with Search/Replace, normally `_L` → `_R`. The
   helper finds the opposite setup by joint and matches the pose name/output;
   it does not assume the generated cone's random name matches. Driver and
   transform fields can be supplied manually when automatic matching is ambiguous.
3. Review each Mirror channel and Value rule. Keep delta is the initial rule;
   the tool does not guess a sign from a joint name. Make every destination
   channel unique among enabled rows.
4. Put the opposite transform at its neutral pose and **Read mirror neutral**.
   Edit individual neutral values afterward if needed. Changing the target or
   channel mapping invalidates the previous neutral capture, requiring another
   explicit read. This prevents reusing an unrelated control's neutral offsets.
5. **Preview mirror** validates the mapping and reports the planned channel,
   sign/input rules and key counts. Preview adds no nodes or Undo action.
6. **Mirror curves** clones the source SDKs onto the opposite driver and channels.
   It saves the source mapping and creates/updates the destination binding in
   one Undo action. Source keys and actual driver values are unchanged.
7. To update an already mirrored curve, explicitly enable **Replace SDK curves
   owned by the destination binding**. Only that binding's matching curves may
   be replaced. Other animation/constraints/blends are kept.

**Save mirror map** stores rules/neutrals without writing curves. Maps and curve
ownership use UUIDs and persist when reopening the scene or toolkit. Local
rotation/translation neutral values are converted when Maya scene units change.
Use Scene SDK bindings → Refresh SDKs / Load saved to restore an authored map.

## Ownership, cleanup and first-version scope

Each native curve is one driver → animCurveUA/UL/UU → driven TRS channel.
A binding owns its created curves and `rtkPoseSDK_META` network record. It does
not own either transform, the PoseDriver, or unrelated animation. No external
runtime plug-in, expression, scriptJob or frame timer is introduced.

Capture/mirror preflight every enabled row before edits. Locked/referenced
receivers, whole-compound inputs, time animation, constraints, existing blend
networks, foreign curves and shared curve outputs are protected. The first
version supports **one direct SDK driver per channel**, including many keys
on that curve. Several pose weights cannot yet be summed onto the same channel;
use separate SDK offset transforms for separate contributions. Automatic
blendWeighted composition is a future extension, not part of this release.

Dependency checks examine upstream plugs, world-space dependencies and visited
DAG ancestors to reject a driven transform that participates in producing its
own pose weight. Choose a separate corrective/SDK offset in that case. This
check is conservative; it does not temporarily disconnect the rig to force an SDK.

**Remove created SDK · keep values** deletes the selected binding's owned curves
and leaves the currently evaluated driven values. It keeps the transforms and
PoseDriver and is Undoable. Missing curves/deleted receivers can still have their
orphaned SDK metadata cleaned; foreign replacement drivers are not deleted.
A whole PoseDriver removal with its existing Keep connected values option can
freeze an SDK curve input. The SDK binding remains removable afterward. Removing
an individual pose with an active SDK consumer still requires removing that SDK
first. Remapping or deleting unrelated source connections is not forced.

## Install and native test

Replace the complete toolkit folder, including `pose_driver_sdk.py` and
`pose_driver_sdk_ui.py`, reload `master_rigging_toolkit`, and call `show()`.
The title should be **v2.35**. No plug-in unload or Undo reset is needed.

The automated suite uses recorded native-command adapters plus real Qt controls.
It does not execute Maya's curve evaluator. A native smoke fixture is included:

```python
import maya_pose_sdk_smoke
maya_pose_sdk_smoke.run()
```

It creates unique test transforms/weights, tests typed TRS SDKs, weighted curve
mirroring across different neutrals/axes, input reversal, native Undo/Redo,
dependency checks and posed removal. It removes only its fixture and captured
SDK records and never opens a new scene. It respects current scene units.
Native Maya execution and timing remain unverified on the build host.

Native API references: [setDrivenKeyframe](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/setDrivenKeyframe.html),
[scaleKey](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/scaleKey.html),
[duplicate](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/duplicate.html),
and [MItDependencyGraph](https://help.autodesk.com/cloudhelp/2026/ENU/MAYA-API-REF/py_ref/class_open_maya_1_1_m_it_dependency_graph.html).
