# Layer Skin UI 27 · Assignment geometry

UI 24 captured the visible, already deformed mesh in world space together with
the current joint frames. That snapshot was frozen until recapture. A first
assignment made while the character was posed therefore used that posed shape.

UI 25 defaults all three assignment methods to the **skinCluster input mesh**.
It reads the evaluated `input[index].inputGeometry` belonging to the loaded
mesh; it does not choose an intermediate shape by its `Orig` name or position
in a list. The context reuses the input mesh function set it already resolved
for topology validation. Older loaded contexts can resolve the exact input plug.

## Geometry and frame space

Input geometry points are read in object space and mapped into the skin's bind
world space. Bound joint frames use the matching bind matrix:

```text
referencePoint = inputObjectPoint * skinCluster.geomMatrix
jointBindFrame = inverse(skinCluster.bindPreMatrix[logicalInfluenceIndex])
```

This uses Maya's row-vector convention. Sparse logical influence indices are
resolved through `indexForInfluenceObject`, independently of the physical
column order in skin weight arrays. Translation, rotation, mirrored and
nonuniform scale are retained; distances and axes are compared in one space.
The reference stores internal centimeters. The mesh and rig are not reset or
temporarily moved to a bind pose.

Maya documents `geomMatrix` as the geometry transform at binding and
`bindPreMatrix` as the inverse influence transform at binding. Authored or
connected bind matrices are sampled as they exist at capture time. This is a
snapshot of the skin's bind inputs, rather than a reconstruction of an earlier
scene state.

An unbound joint has no `bindPreMatrix` entry. Its current offset relative to
the nearest bound ancestor is placed under that ancestor's bind frame. If it
has no bound ancestor, its captured offset relative to the visible mesh's
transform is placed in the geometry bind frame. These are marked
`ancestor_bind_offset` or `mesh_relative_offset`, and the UI reports how many
unbound reference offsets were captured. Parent/global motion is removed, but
unknown historical local joint offsets cannot be inferred. Capture unbound
joints at their intended local reference placement.

## Which operations use which geometry?

| Operation | Geometry/data |
| --- | --- |
| Distance to joint | Cached pre-skin vertices and joint bind frames. |
| Distance to bone | The same cached vertices and bind frames, including buffered joint-child endpoints. |
| Joint axis | The same cached vertices and bind-space axes/branch distances. |
| Brush picking, footprint, Shift/Relax boundary | The visible, currently deformed mesh so the brush follows the surface under the cursor. |
| Weight/mask Relax solver | Vertex connectivity and neighboring weights/masks; the brush's spatial footprint remains on the visible mesh. |
| Utilities geometry transfer/export | Existing Base/Deformed geometry choices remain explicit. Base already reads the skin input. |

"Pre-skin" means the input immediately before this skinCluster. Upstream
deformers, such as a blendShape before the skin, can affect that input. It does
not mean bypassing every earlier deformer in the history. The captured reference
is frozen, so changing the visible pose or painting weights does not change the
geometry used by subsequent assignments.

## Cache, migration and recapture

First Assign or **Recapture reference** stores the input positions, geometry
matrix, bind frames, UUID hierarchy and source marker. All methods share this
reference and the existing bounded assignment cache. An unchanged Assign does
not read new reference points; a changed pre-skin shape is used after explicit
Recapture. Topology changes retain the existing safety checks.

Opening/refreshing the UI does not change saved references or weights. On the
next explicit Assign, a UI 24 or older posed reference is replaced with the new
skin-input/bind-space snapshot inside that assignment's Undo operation. Existing
paint, masks, locks, layer order and base data remain subject to their existing
assignment options. Undo restores the previous metadata and skin weights.

The UI labels the current source as **Skin input / bind space**, or identifies a
legacy reference awaiting the next Assign. Recapture updates the current input
and bind data. Repositioning a bound joint without updating its skin binding
does not create a new bind matrix; this tool reads the actual skin binding.
It never silently substitutes visible mesh positions when the input/bind data
cannot be read.

## Reload and native verification

Replace the complete folder, run `layer_skin_ui_refresh.py`, and confirm
**UI 27**. The registered command remains version 0.4.1. Its command class,
native Undo objects, brush and Relax implementations are retained.

```python
import maya_layer_skin_predeform_smoke
maya_layer_skin_predeform_smoke.run()
```

The fixture moves/scales the character and poses a joint. It checks that the
visible points change while input positions, bound frames and the three
assignment results agree across poses. Native Maya is unavailable on the build
host; this fixture remains unexecuted there.

References: [skinCluster attributes](https://help.autodesk.com/cloudhelp/2024/ENU/Maya-Tech-Docs/Nodes/skinCluster.html),
[MFnSkinCluster indices](https://help.autodesk.com/cloudhelp/2024/ENU/MAYA-API-REF/py_ref/class_open_maya_anim_1_1_m_fn_skin_cluster.html).
