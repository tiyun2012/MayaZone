# Module outputs · Toolkit 2.41

Open **Modular Rig → Modules** for builders and the output manager, or
**Modular Rig → Connections** for hierarchy scanning and connection plans. See
[Rig_Connections_Guide.md](Rig_Connections_Guide.md) for start message links and
native parent-constraint connections.

Every new **Root, FK, Three-Bone IK, IK/FK and Foot** module publishes named
`*_OUTPUT` transforms. These are connection points for another module or a
native Maya constraint. Outputs are separate from animator controls and from
the original skeleton joints. They are owned and removed by their module.

## Connect a child module

1. Build the parent module and a module for the lower joints. Each source joint
   belongs to one module. For example, build an upper spine FK, then a neck FK.
2. In **Modular Rig → Scene modules**, choose the parent module in **Module**.
3. Expand **Module outputs / attachment**. Select the appropriate output row
   and click **Use output as parent**. Each row also has a **Select** button.
4. Choose the child module in the Module dropdown. The parent output stays
   loaded in its field. Click **Attach selected module · keep offset**.
5. Animate the parent. The child follows position, orientation and global scale.
   Keep the child module's own `globalScale` at 1 unless you want another local
   scale multiplier.

**Get selected** accepts a published output selected in Maya. The picked object
is cached by UUID, so renaming the output or its parents does not break the
connection or the loaded field. Refresh repopulates the saved module/output list.

Attachment uses a native matrix connection on an owned `INPUT` buffer. It
maintains the child's current offset and leaves its controllers' local channels,
keys, driven keys and stored defaults untouched. Skeleton joints keep their
existing parents, jointOrient, rotateAxis and local channel definitions.
The output's world transform supplies parent global scale once; the actual DAG
parent inverse compensates an existing parent hierarchy.

## What each output represents

| Module | Published frames |
| --- | --- |
| Root | A **Placement** output under Root_ctrl; an additional joint-aligned output when Root joint is provided. A different placement frame retains the skeleton joint's bind offset. |
| FK | One joint-aligned output per FK joint, below the corresponding FK controller. New FK source constraints target these outputs. Branching chains are supported. |
| Three-Bone IK | Three final joint-aligned frames, including solved segment translation, orientation and module global scale. |
| IK/FK | Three **final blended frames**, after the local rotation / explicit length blend. Outputs follow `ikFkBlend` throughout 0–1. They are independent of the raw IK buffers and either branch's controllers. |
| Foot | Ankle and ball frames from the reverse-foot/FK solution. With **Drive ankle joint** off, the list still includes an **Ankle target** output for an external IK goal; only ball is a driven source joint. |

New matrix-based rigs route the final frame through the published output before
their source joint's local/parent compensation. A published frame therefore has
the module's final world position, rotation and deliberate global scale, without
reading that source joint's worldMatrix back into its own solve.

All output transforms and controller channels remain unlocked. Use controllers
for animation; output transforms provide stable rig connection points. Constraints
made manually from an output can use the toolkit's **Constraint** tab. An external
manual connection is protected when its producing module is removed.

## Saved rigs

Replace the complete folder, reload the toolkit and confirm **v2.41**. A Maya
restart is not needed for this Python/native-node update.

```python
import importlib
import master_rigging_toolkit as toolkit
importlib.invalidate_caches()
toolkit = importlib.reload(toolkit)
toolkit.show()
```

Choose a saved rig and click **Publish outputs · saved rigs** once. Loading or
refreshing the list alone never edits the scene. Publishing adds its input and
outputs in place, retains the metadata identity, existing controls, default
values and current evaluated joint pose, and is one Undo action. Repeat publishes
reuse the existing outputs.

For saved FK and older native-constraint IK rigs, publishing adds output frames
alongside their existing solvers. Those original constraints remain intact. A
legacy constraint-blended IK/FK rig exposes its evaluated joint frames; current
matrix IK/FK rigs expose the upstream final blend. Rebuilding an old rig is only
needed to change its solver architecture, not to obtain outputs.

## Detach, delete and mirror

**Detach · keep pose** disconnects only the registered module attachment. Its
current input matrix is retained, so the child holds this frame and its animator
channels/defaults remain unchanged. This does not bake a time range. An existing
manual DAG parent, including Foot's optional Parent control, remains its parent.
For new chains, leave Foot's Parent control blank and use the output attachment.

Delete child modules first, or detach them before deleting the producing parent.
Attempting to delete a parent lists its dependent child. Deleting a child keeps
its original joints at the current evaluated pose and leaves its parent module
intact. Unrecorded external output consumers and foreign DAG children remain
protected by the existing removal preflight.

Self attachments and dependency cycles are rejected before editing the scene.
The check follows actual upstream evaluation inputs and DAG parents, ignoring
ownership-only message links. Attaching an upper module to one of its dependent
lower modules is rejected.

Mirror creates the mirrored module's own outputs. A child attached to a central
Root output keeps that shared attachment. A side-specific parent output is
matched through its counterpart **source joint**, module type and output role;
custom output names do not affect matching. Mirror/publish the parent first.
A missing or ambiguous counterpart stops Mirror before building anything.

The supported scaling contract remains positive uniform scale without shear.
Attachments preserve the current frame rather than a historical bind/default
pose. Existing animation curves are retained; mirroring does not copy animation.

## Reverse-foot IK goal

To use Foot as an existing leg IK's goal, disable **Drive ankle joint** when the
leg already owns ankle. Select Foot's **Ankle target** output. Attach the leg's
IK end target/ZERO through your normal rig setup, with offset retained; the
generic **Attach selected module** action attaches the *entire module*, not a
single IK branch control. Keep Foot attached independently upstream of the leg
goal. Feeding Foot from that same driven leg goal creates a cycle.

## Python API

```python
import master_rigging_toolkit as toolkit

outputs = toolkit.list_rig_outputs(parent_module)  # read-only; [] on older rigs
outputs = toolkit.publish_rig_outputs(parent_module)  # upgrade once if needed
for output in outputs:
    print(output['label'], output['node'], output['joint'], output['role'])

toolkit.attach_rig_module(child_module, outputs[-1]['node'])
toolkit.detach_rig_module(child_module)

# Build-and-attach is one action; source joint pose is retained.
child = toolkit.build_fk_module(
    ['neck_JNT', 'head_JNT'], name='Neck', parent_output=outputs[-1]['node'])
```

All module builders accept optional `parent_output`. Build results include
`input` and `outputs`; Root also returns `placement_output`. The legacy Root
`attachment` return value still selects Root_ctrl for existing scripts.

Scene data uses the existing version-1 ownership contract with optional
`output_version: 1`, an `outputs` registry and `input`/attachment records.
`meta.outputs[]`, `meta.input`, output `rtkOutputOwner` and `rtkOutputJoint`
are message links; `rtkRigOutput` stores the role. UUIDs preserve identity after
renaming or reparenting. No per-frame Python, expression, plugin or UI callback
is needed to evaluate outputs or their attachments.

Run the supplied native fixture inside Maya after reloading:

```python
import maya_module_outputs_smoke
maya_module_outputs_smoke.run()
```

It creates a unique fixture, checks native output frames, scale, FK/IK/FK/Foot
connections, cycle prevention, posed detach/removal and Undo/Redo, then cleans
its own nodes. It does not open a scene or clear Undo. Host command/matrix and
real Qt regressions are separate from this native Maya test.
