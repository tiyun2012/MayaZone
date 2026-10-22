# Start joints and module connections · Toolkit 2.41

**Modular Rig** now has two tabs:

- **Modules** contains the existing builders, scene modules, outputs, defaults,
  mirror and removal actions.
- **Connections** scans a Root's joint hierarchy and proposes missing module
  connections. The list is on the left; the selected module's parent, output
  and method are on the right.

## Stable start registration

New modules register their first joint with message connections. No matching by
joint name, controller name or suffix is used for connection discovery.

| Module | Start joint | Linked start controller |
| --- | --- | --- |
| Root | Its supplied Root joint, or an explicitly chosen scan anchor for a placement-only Root. | Root_ctrl, the second placement control. |
| FK | The first/root joint of its connected joint tree. | Module ROOT/globalScale control. |
| Three-Bone IK / IK/FK | First joint from the module inputs. | Module ROOT/globalScale control. |
| Foot | Ankle, including when Drive ankle joint is off. | Foot module ROOT/globalScale control. |

The direct link is:

```text
start_joint.message → start_controller.rtkModuleStartJoint
```

The metadata also stores `startJoint` and `startController` message connections;
the controller's `rtkStartModule` message points back to that metadata. UUIDs are
cached alongside the links and checked when reading the module. Names are only
display labels. Joint, controller, output and metadata renames retain these
relationships. The start joint receives no custom attributes and is never
owned/deleted by the module because it is a registration anchor.

For a placement-only Root, **Set Root start** adds a scan anchor without adding
a skeleton driver or changing the module's source-joint ownership. For a bound
Root and other module types, registration must match the original input joint.
Registering a different joint does not silently retarget the existing rig.

## Workflow

1. Build Root and the other modules in **Modules**. A supplied Root joint also
   becomes its scan start automatically.
2. Open **Connections** and choose the character's Root module. If Root has no
   joint, select a skeleton joint, click **Get joint**, then **Set Root start**.
3. The tool scans automatically when a Root with a valid start is selected.
   **Scan hierarchy** reruns discovery after scene changes. Scan and tab changes
   do not create attributes, constraints or Undo entries.
4. The left list shows modules that need attention. Select a row and review the
   suggested **Parent module**, **Parent output** and **Method** on the right.
   **Select joint** and **Select controller** use the cached identities.
5. Click **Connect selected · keep offset**, or review the checked rows and click
   **Connect checked modules · one Undo**.

The default parent is the module that drives the nearest ancestor joint, with
that joint's published output. For Foot with ankle drive disabled, the module
already driving its logical ankle can provide that frame. A placement-only Root
acts as the fallback parent through its Placement output. Modules outside the
selected joint hierarchy are excluded from the child list. Other valid scene
modules are available as explicit parent choices.

The suggestion is a starting point. A reverse foot that drives a leg IK goal
may need an independent Root parent rather than a leg output. Review that choice;
actual dependency cycles are rejected before applying the plan.

## Connection states

| State | Meaning |
| --- | --- |
| Missing | No recorded connection, registered module DAG parent or foreign transform driver was found. Prepared rows with a suggested output are checked initially. |
| Connected | A recorded matrix or native parent connection is present. Its actual parent/output/method are displayed; it is not overwritten. |
| DAG parent | The module already sits under another module's hierarchy. An extra constraint is not added. |
| External driver | A frame has an external driver, manual parent or an altered INPUT hierarchy. Inspect it before making an automatic connection. |
| Broken | A node from a recorded connection is missing. Inspect/detach it, or use module removal as appropriate. |
| Ambiguous | More than one module claims the nearest driven ancestor. Ownership needs review. |
| prepare suffix | This saved module or its parent still needs output/start registration. |

**Needs attention only** hides already connected and module-parented rows.
Disable it to inspect their recorded methods or detach a connection. Metadata
problems appear in a separate read-only issue list rather than causing another
module's driver to be overwritten. Root controller animation or direct driven
keys remain local animation; they are not treated as an attachment by themselves.

## Methods

**Parent constraint** is the default. It constrains an owned connection space
above the module INPUT. **Follow parent scale** also creates a scale constraint.
An owned matched target below the parent's output carries the bind offset through
its transform matrix, allowing translation, orientation and uniform global scale
to follow together. Controllers retain their local values, keys and defaults;
source joint parents, jointOrient and rotateAxis definitions remain unchanged.
The new scale constraint drives rig space, not IK bone scale channels.

All native solvers use the shared `constraintNode` container and that module's
owned subgroup. They participate in the existing Constraints/Mirror/Delete Rig
actions. Matrix-based source IK/IKFK/Root/Foot solvers retain their source-joint
matrix connections.

**Matrix parent** uses the previous output-to-INPUT matrix method and always
carries scale. The direct `attach_rig_module` API and the existing Modules tab
attachment button retain that behavior for compatibility.

**Space switch (planned)** is a disabled entry. This version does not build or
switch spaces. Methods have stable IDs in a shared registry, so later methods
can share the same scan/list/review workflow.

Connections maintain the current offset. Existing connections must be detached
before changing their parent or method in the Connections workflow. No foreign
constraint, connection or animation is forced away. The supported scale contract
remains positive uniform scale without shear.

## Detach, remove and mirror

**Detach selected · keep pose** removes only the recorded connection and holds
the current evaluated frame in the module's own input/connection space. Native
constraints and their matched target are removed. The module and skeleton stay
in place; controller channels and defaults remain available. Detach does not
bake animation over time, and an unrelated manual DAG parent remains its parent.

Delete children first, or detach them before deleting their producing parent.
Parent removal names the dependent child. Deleting a child retains its joints
and leaves the parent rig intact. Foreign consumers of connector nodes remain
protected. Owned nodes are identified by UUID after renaming.

Mirror now preserves the connection method and scale-follow option as well as
the counterpart output. Central Root outputs stay shared; side-specific parent
outputs are located through counterpart source joints and roles. Mirror retains
its existing Search/Replace workflow for finding counterpart skeleton joints.

Batch connection preflights every proposed edit and checks both existing driver
dependencies and cycles created by the combined plan. The complete action is one
Undo step. A failed connection rolls the entire plan back. Joint and controller
world frames are verified before accepting the operation.

## Existing scenes and reload

Replace the complete folder, reload and confirm **v2.41**. No Maya restart or
plug-in unload is needed for this Python/native-node update.

```python
import importlib
import master_rigging_toolkit as toolkit
importlib.invalidate_caches()
toolkit = importlib.reload(toolkit)
toolkit.show()
```

For saved rigs, choose Root and scan, then click **Prepare saved modules**.
It adds the missing start links and, when needed, publishes outputs/INPUTs in
one Undo action. Existing 2.40 rigs retain their original nodes and poses; only
their message registration is added. Already prepared modules are left alone.
The Modules tab's **Publish outputs · saved rigs** also registers the start.

## Python API

```python
import master_rigging_toolkit as toolkit

# A scan anchor for a placement-only Root; this does not constrain the joint.
toolkit.register_rig_start(root_module, 'skeletonRoot_JNT')

report = toolkit.scan_rig_connections(root_module)  # read-only
if any(row['needs_prepare'] for row in report['rows']):
    toolkit.prepare_rig_modules(
        [report['root_module']] + [row['module'] for row in report['rows']])
    report = toolkit.scan_rig_connections(root_module)

plans = [dict(module=row['module'], output=row['output'],
              method='parent_constraint', follow_scale=True)
         for row in report['rows'] if row['ready']]
toolkit.connect_rig_modules(plans)

# One explicit connection, or the existing matrix attachment API:
toolkit.connect_rig_module(child_module, parent_output,
                           method='parent_constraint', follow_scale=True)
toolkit.detach_rig_module(child_module)
print(toolkit.find_rig_starts('skeletonRoot_JNT'))
```

Every builder also accepts `parent_output`, `parent_method` and
`parent_follow_scale`. Direct builds default to the existing matrix method;
choose `parent_method='parent_constraint'` for a native connection in the same
build action. Registration is automatic for new builds and mirrored modules.

Native Maya validation is supplied separately:

```python
import maya_rig_connections_smoke
maya_rig_connections_smoke.run()
```

The smoke fixture checks native constraints, renames, nested global scale,
connection Undo/Redo, final IK/FK outputs and posed detach/removal. It creates a
unique fixture and cleans only its captured nodes; it does not open a scene or
reset Undo. Host command/matrix and real Qt checks do not replace that native test.
