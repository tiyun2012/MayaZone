# Script entry points

The public `facial_system` module imports Maya only when an operation needs it.
Tools and future automation can use the same functions as the workflow window.
No operation below requests an AI service or installs a plug-in.

```python
import facial_system as fs

fs.show()                 # One shared window
fs.show(step="groups")    # setup / groups / wrap / fit / check
fs.reload_ui(step="fit")  # After replacing this package's files
```

## Fit an existing saved capture

Run in Maya with the correct native rig open and controls neutral:

```python
document = fs.load_neutral(r"C:\characters\original\driveNeutralData.json")

# Use the saved mesh ID as the key; use the exact target DAG path as the value.
head_id = next(key for key, mesh in document["meshes"].items()
               if mesh["identity"]["name"] == "head_meshShape")
mapping = {head_id: "Head_FitTarget"}

preview = fs.preview_fit(document, mapping)
result = fs.apply_fit(document, mapping, install_mesh=True)
geometry = fs.check_fit(document, mapping, install_mesh=True)
behavior = fs.check_rig(limit=None)  # All 107 poses
```

Choose the correct head mesh ID explicitly if the original mesh has been
renamed or multiple matching names exist. `preview_fit` creates native locator
markers. `apply_fit` edits the scene only after preflight and checks; the other
checks return structured dictionaries. No call mutates the saved default data.
Capture and edit groups with the UI or `facial_system.scene_adapter` and `core`.

`check_rig` temporarily overrides internal raw inputs and restores them. It
validates raw input to local joint channels, including fitted neutral offsets;
it does not validate the facial GUI or skin quality. It raises on interruption
or restoration failure. Check the returned `passed` field for numerical failure.

## Save or load project data

```python
from facial_system import project
from facial_system import scene_ops

scene_path = scene_ops.save_scene(r"C:\characters\new\scenes\face.ma")
manifest = project.save(r"C:\characters\new", document, mapping,
                        scene=scene_path, fit_result=result,
                        behavior_report=behavior, fit_check=geometry)
loaded = project.load(manifest)
```

Saving to an existing scene requires `overwrite=True` explicitly. The bundled
template path is protected. Project loading returns data and paths and does not
open or replace the Maya scene. Saving a project does not save Maya scene edits.

## First coarse cage layer

Run in Maya with a neutral source head. Source geometry is copied; the reference
is only a visual guide. One session is supported in this first test.

```python
from facial_system import cage

marks = cage.suggest_landmarks("head_mesh")             # review proposals
# Optional: select one source vertex and override a landmark:
# marks = cage.assign_landmark("head_mesh", marks, "upper_lip")
layer = cage.create("head_mesh", reference="NewFace", seed="reduced",
                    target_vertices=400, landmarks=marks, protected_rings=0)
layer = cage.bind(layer)                              # bind before editing
test = cage.test_response(layer)                      # brief move and restore

# Edit layer['cage'] in Maya. Resume fresh metadata after Maya Undo/reopening:
layer = cage.load()
layer = cage.set_layer(layer, weight=1.0, enabled=True, mode="Offset")
target = cage.bake(layer, name="Head_FitTarget")
```

`bake` returns the actual target shape path, including any suffix needed to
preserve an existing target. Programmatic callers must map that returned path
to the appropriate saved mesh ID before applying the joint fit. The UI does
this automatically when one captured source can be identified.

`cage.reset(layer)` restores saved cage points and its bind transform.
`cage.mirror(layer, direction="positive")` copies +X to -X using saved vertex
pairs; `negative` reverses the direction. `cage.export(layer)` returns data for
`project.save(..., wrap_data=...)`. Save the Maya scene to retain native graph
objects. `cage.remove(layer)` removes the owned work group; baked targets remain.

`cage.select_landmark(layer, "mouth_corner_L")` selects a retained cage control.
`cage.move_landmark(layer, "mouth_corner_L", [x_cm, y_cm, z_cm], mirror=True)`
matches it to a world-space point after binding. Source assignment data can be
saved with `project.save(..., landmark_data=marks)` before a cage exists.
The source identity/topology/positions must still match when reusing a draft.
`seed="sphere"` is the default for legacy script compatibility; the UI defaults
to Reduced neutral head. Custom cages take priority over generation settings.
Reduced mode alone applies the protected landmark assignments.

## Package layers

| Module | Responsibility |
|---|---|
| `core` | Schema, grouping, absolute fitting math, JSON, transaction orchestration |
| `scene_adapter` | Maya identities, source snapshots, skin-weight group detection, selections |
| `fit` | Native translation writers, preview, rest mesh/bind updates, verification, reset |
| `cage_core` | Symmetry pairs, rest-state validation, enum labels, portable snapshots |
| `cage_landmarks` | Named landmark definitions, protected faces, retained source-ID decoding |
| `landmark_ui` | Landmark authoring and reference matching window |
| `cage` | Native coarse cage, binding, response test, reset, bake, cleanup |
| `cage_ui` | Cage Wrap page and native symmetry editing controls |
| `validation` | Current-neutral ROM references and read-only fit geometry checks |
| `project` | Portable project manifests, capture copies, report persistence |
| `scene_ops` | Scene inspection, protected template opening, independent targets, scene saving |
| `neutral_editor` | Shared group and fitting page widgets |
| `ui` | Five-step workflow, shared state, project controls, progress, user-facing errors |

Runtime rig evaluation remains in the Maya scene. Closing the tool removes no
rig nodes and changes no animation behavior.
