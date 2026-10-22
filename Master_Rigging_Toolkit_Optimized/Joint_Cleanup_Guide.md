# Cleanup — unused joints

Open **Master Rigging Toolkit v2.33 → Cleanup**.

1. Select your mesh transforms or output mesh shapes and press **Get selected meshes**.
   Repeat to add more meshes. Duplicate inputs are combined. **Remove selected**
   and **Clear** only change this input list; they do not delete meshes.
2. Select the top joint and press **Joint root → Get selected**. You can also
   type its full path. The root and all descendant joints are checked.
3. Press **Scan unused joints**. The table lists joints absent from the union
   of the loaded meshes' skinCluster influence lists. Hover to see full paths;
   click its **Select** button to select the joint in Maya, including protected
   rows with Delete disabled. Double-click selection also works. Selection
   tracks the original joint by UUID even after renaming.
4. Press **Delete** at the right of a ready joint, or **Delete All** to prune
   all eligible branches, from their tips upward. Results refresh after deleting.

| Status | Meaning |
| --- | --- |
| Ready to delete | An unbound leaf joint that can be deleted individually. |
| Delete children first | All children are eligible unused joints. Delete All removes these children first, then this joint. |
| Keeps retained children | Deleting this joint would delete another joint, transform or shape that must be retained. This row is protected. |
| Used by other skin | The joint is not used by the input meshes, but another skinCluster in the scene still uses it. Protected. |
| Drives … | A non-message outgoing connection drives another node. Protected. |
| Locked / Referenced / Instanced joint | Protected; the tool does not unlock, import or split it. |

## Scope and removal

This checks **influence membership**, not nonzero vertex weights. A registered
influence stays out of the unused list even when all its weights are zero.
All skinClusters in the mesh history are considered, including multiple skins.
A mesh with no skin is identified in the summary. If none of the loaded meshes
has a skinCluster, scanning stops rather than offering the whole joint chain.
Mesh components, intermediate shapes and non-mesh inputs are rejected.

Delete All means **all eligible displayed joints**. Protected rows stay listed,
with their reasons. The tool does not reparent children or collapse an unbound
joint out of the middle of a retained chain. This preserves those objects'
parenting, transforms and animation basis. The root can be removed if its
entire branch is unused and eligible. No skin weights or skinCluster influence
lists are edited, and no cleanup metadata is added to the scene.

Native joint scale → child inverseScale connections are compatible with
tip-first pruning. Message, bind-pose and set membership links do not by
themselves prevent deletion. Other downstream consumers protect the joint.
For example, a joint that drives a constraint is retained even if it is not
listed in any skinCluster.

Before deleting, the tool rechecks meshes, the root, influence membership and
joint protections. Inputs and results use UUIDs so renaming does not redirect
an action to another object with the old name. A changed/deleted input stops
the action. Newly created joints absent from the displayed results are not
deleted. New scene/open scene events discard the old page's inputs and results.

Each Delete or Delete All action is one Maya **Undo** step. Undo must be
enabled. An unexpected failure rolls back that action, and an empty failed
action never undoes an earlier user operation. After Maya Undo/Redo or external
scene edits, press **Scan unused joints** again to update the table.

## Python

Keep `joint_cleanup.py` beside the toolkit in your Maya Python path:

```python
import joint_cleanup

report = joint_cleanup.scan_unused_joints(["body_geo", "clothes_geo"], "root_JNT")
for row in report["rows"]:
    print(row["path"], row["reason"])

# These functions modify the scene, just like the corresponding UI buttons:
# result = joint_cleanup.delete_unused_joints(report)  # Delete All eligible
# result = joint_cleanup.delete_unused_joints(report, [one_row["uuid"]])
```

The scan reads skin membership and DAG/dependency relationships; it does not
iterate vertex weights, evaluate point positions or open a progress window.
Influence identities shared across skins are resolved once per scan.

`test_joint_cleanup.py` exercises the backend with recorded Maya commands.
`test_joint_cleanup_ui.py` exercises actual Qt widgets with the same backend.
Native Maya has not been available in the development environment. In Maya,
run the supplied temporary-fixture check with:

```python
import maya_joint_cleanup_smoke
maya_joint_cleanup_smoke.run()
```

It checks real Undo/Redo, zero-weight influence membership, other-skin
protection, native inverseScale connections, rename handling and preservation
of retained joint transforms/orientation and skin weights. It creates a unique
temporary namespace, cleans only its test objects and does not open a new scene.

Maya command references: [skinCluster influence query](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/skinCluster.html),
[listRelatives](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/listRelatives.html),
[lockNode](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/lockNode.html).
