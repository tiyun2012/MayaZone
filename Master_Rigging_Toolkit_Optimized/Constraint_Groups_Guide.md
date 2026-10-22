# Constraint groups · Toolkit 2.37

New native Maya constraints are placed inside the shared `constraintNode`
transform. The toolkit reuses `|constraintNode`, or one unambiguous existing
transform with that name. If none exists, it creates a top-level container.
A locked, referenced, wrong-type or ambiguous container is reported before
creating a new solver.

## What appears in the Outliner

Each rig module with native constraints gets a subgroup named from its source
joint and module, ending in `_constraintNode` with Maya's numeric suffix.
The subgroup and its solvers are recorded as owned members by UUID and message
links. The shared container is not owned by any individual module. Renaming a
solver or its subgroup does not break removal.

Guide IK, Locator View and PoseDriver also use their own constraint subgroups.
Quick constraints and other standalone actions use the shared container.
The Auto Controllers tool can use its custom constraint subgroup name.
Root and Foot currently use matrix outputs; they create no empty constraint
subgroup. Utility nodes such as multMatrix, blendMatrix and multiplyDivide are
not DAG constraints and keep their existing graph organization.

Solvers are reparented relatively with their input connections retained. This
does not reparent the driven joint, change the chosen constraint type or alter
Maintain Offset. The grouping is applied by toolkit helpers, not a global
override of Maya commands. Constraints created outside the toolkit are not
automatically moved.

## Actions for each rig module

Open **Modular Rig → Scene modules**. The table provides these actions beside
each module, independently of the module selected in the combo box.

| Button | Result |
| --- | --- |
| Constraints | Organizes that module's recorded native solvers. Also works on compatible modules saved before 2.37. Repeating it reuses the same subgroup. Disabled for matrix-only modules. |
| Mirror | Builds a new default setup on existing counterpart joints using Search / Replace below the table. Keeps the source rig. |
| Delete Rig | Removes that module's owned solvers, controls and subgroup. Keeps source joints at their current evaluated pose, with their orientation definitions. |

Use **Preview mirror joints** to inspect name mapping before mirroring.
The default tokens are `_L` and `_R`; **Swap** reverses the direction. Existing
counterpart joints must pass normal build validation. Mirroring does not create
joints or copy controller animation. Root Mirror requires a source Root joint
whose name maps to a different existing joint; a placement-only central Root
remains shared.

Old scene modules are not changed merely by opening the UI. Use **Constraints**
on each existing module you want to organize. Its current pose is verified;
organization is one Undo action, with rollback on failure. This is a module
operation, not a scene-wide search for unrelated constraints.

## Deletion and ownership

Removing one module leaves the other constraint subgroups and rigs intact.
An existing user-created constraintNode is never deleted by module cleanup.
A container created by the toolkit is deleted only when empty and without
outgoing consumers. Empty tool subgroups are likewise pruned only when unused.

An unrelated object placed inside an owned subgroup, or an external consumer of
an owned output, stops module removal before edits. Move or detach the reported
item and retry. Keep user organization under the shared container beside module
subgroups rather than inside a module's owned group. No new transform channels
are locked. Removal retains this frame; it does not bake animation.

## Python and verification

```python
import master_rigging_toolkit as toolkit

result = toolkit.organize_rig_constraints(module)
print(result['count'], result['group'])
other_side = toolkit.mirror_rig_module(module, search='_L', replace='_R')
toolkit.remove_rig_module(module)
```

908 host tests pass, including recorded Maya-command regressions and real Qt
row actions. These do not execute Maya's native solver. The package includes
a native fixture for use in Maya; it does not open a scene or reset Undo:

```python
import maya_constraint_groups_smoke
maya_constraint_groups_smoke.run()
# run(keep=True) retains the unique test fixture for inspection.
```

It checks shared-container reuse, separate ownership, input preservation,
group-transform independence, mirror, posed removal and Undo/Redo. Maya was
not available on the build host, so native execution remains pending.

Maya references: [parentConstraint node](https://help.autodesk.com/cloudhelp/2024/ENU/Maya-Tech-Docs/Nodes/parentConstraint.html),
[scaleConstraint node](https://help.autodesk.com/cloudhelp/2022/ENU/Maya-Tech-Docs/Nodes/scaleConstraint.html)
and [parent relative flag](https://help.autodesk.com/cloudhelp/2022/ENU/Maya-Tech-Docs/CommandsPython/parent.html).
