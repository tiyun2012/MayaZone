# Facial System 1.1 — first cage-fitting test

One Maya window for the native facial rig, neutral vertex attachments, fitting,
validation, and project saving. Cage Wrap adds one mirrored coarse layer using
Maya's native Proximity Wrap. The system includes the working native scene and
the corrected upper-nose neutral check from Drive Neutral Data Tool 1.1.1.

## Start in Maya

Extract the complete `FacialSystem` folder, close the previous standalone tool
window, and run this in Maya's **Python** Script Editor. Change the path to the
folder containing `launch_facial_system.py` and the `facial_system` package:

```python
import sys
sys.path.insert(0, r"C:\maya_tools\FacialSystem")
import facial_system
facial_system.show()
```

You can also drop `launch_facial_system.py` into Maya's viewport. Opening the
window neither opens a different scene nor captures new defaults.

After replacing files with a later version, reload with:

```python
import importlib, facial_system
importlib.reload(facial_system)
facial_system.reload_ui(step="wrap")
```

Reload respects the window's unsaved neutral-data prompt. The package uses its
own namespace and does not depend on an installed copy of the older scripts.

## Resume your current Head_FitTarget test

1. Keep your current native rig scene open and save a test copy. Keep facial and
   neck/head inputs neutral. `noseWrinkleUpperL/R` at 1 is accepted while the
   main `noseWrinkleL/R` controls remain zero.
2. In **1 Scene Setup**, click **Load Existing Neutral JSON...** and choose your
   existing `driveNeutralData.json`. This opens the fitting page.
3. In **4 Fit Joints**, confirm that `head_meshShape` maps to `Head_FitTarget`.
   Use **Use Selected** if needed. Your existing JSON requires no conversion.
4. Click **Preview Positions** and review the green joint markers.
5. Leave **Install edited rest mesh and retain existing skin weights** enabled.
   Click **Apply Neutral Fit**. A successful operation reports PASS; failed or
   cancelled operations use the fitting transaction's rollback.
6. In **5 Check & Save**, run **Check Fit Geometry**, then **Run Behavior Check**.
   The default behavior check covers all 107 included reference poses.
7. Review jaw opening, lips, blink, eyes, mixed expressions, neck movement, and
   playback in the viewport. Return the controls to neutral for geometry checks.
8. Choose a project folder, use **Save Character Scene As...**, then
   **Save Project + Reports**.

Keep the original neutral capture. Fitting never replaces its saved default
positions with fitted positions. Save Project writes a copy of the same neutral
document into the chosen project's `data` folder.

## First cage test

Open **3 Cage Wrap**. Choose the original head as Template / source head and
your new face as the optional visual reference. Leave Custom cage blank for the
small automatic seed. Click **Create Coarse Layer**, then **Bind Cage** before
moving vertices. Keep **Offset** mode and weight 1 for the first test.

Click **Test Cage Response**. It moves one cage control briefly, measures the
preview's response, and restores the previous cage/preview state. Then use
**Enable Mirror Editing**, select individual cage vertices, and fit the head
proportions manually. Use **Bake Target + Use in Fit Joints** when ready.

The new target keeps the source topology and is independent of the wrapping
history. Existing target objects are retained; Maya may name a new bake
`Head_FitTarget1`. The actual returned target is mapped explicitly to Fit Joints.
Your original neutral capture remains unchanged.

Detailed instructions and test-result meanings are in `docs/CAGE_FIRST_TEST.md`.

## The five-step workflow

| Step | Work | Result |
|---|---|---|
| 1 Scene Setup | Use the current scene or open the bundled native template; check neutral inputs; optionally create an independent target copy | A prepared rig and editable target |
| 2 Vertex Groups | Detect the connected-joint scope, inspect groups, select vertices, replace groups with Update, save/load JSON | One original neutral attachment document |
| 3 Cage Wrap | Create/load a coarse cage, bind, mirror-edit, test response, and bake | An independent Head_FitTarget with template vertex IDs |
| 4 Fit Joints | Map matching meshes, preview positions, apply neutral fit, or reset to the captured template | Updated joint translations, rest geometry, and bind data |
| 5 Check & Save | Check fit geometry and solver behavior, inspect playback, save the scene and project | A character scene plus portable data and reports |

Back and Next change pages without discarding data. All five pages share one
document and target mapping. Editing groups, targets, or fit options clears old
results. There are no background tasks left running after a failed check.

### Defining groups

For a new template capture, first put the original rig in neutral. In Vertex
Groups, **Auto-detect Groups** seeds attachments from skin weights and marks
nearest-vertex fallback groups for review. The native scene has 331 connected
facial joints, including joints with no useful skin weights.

Each row has a joint field, group label, vertex count, Select Verts, Update, and
Joint selection. Select source vertices and click that row's Update button to
replace its group. Updating membership recalculates its center from the saved
default vertex positions. Review lips, eyelids, jaw, and fallback groups.

The fitting rule is translation only:

```text
fitted joint = saved joint + fitted group center - saved group center
```

Unassigned joints keep their saved world position. Blank target rows use saved
default mesh positions for calculating attachments. Separate eyes, teeth, and
other parts need corresponding targets if they must move with the new shape.

### Target copies

An existing `Head_FitTarget` can be used directly. It must be unskinned,
independent of the original deformation history, aligned with the captured
source, and retain vertex IDs, count, and connectivity.

For another target, select the original head mesh and use **Create Head_FitTarget
from Selected Mesh**. This duplicates its current visible shape into a separate
unskinned copy with a fresh transform, including when the source transform has
locked channels. Sculpt vertex positions without changing topology. The tool
rejects an existing target name instead of overwriting your sculpt.

### Applying and resetting

Apply modifies the native evaluator's neutral translation constants while
keeping its control connections and expression coefficients. It installs the
target as rest geometry when enabled, retains skin weights, refreshes inverse
bind matrices and bind-pose records, then checks positions and unchanged
rotation/scale state. Existing neutral skin deformation is accounted for when
rebinding. Undo reverses a successful fit in one Maya undo operation.

**Reset to Saved Template** uses the original JSON to restore captured positions
and mesh shapes. It does not delete your independent target. Repeated fitting
always starts mathematically from the capture, rather than adding offsets to
the previous fit.

## Checks after fitting

The combined **Behavior Check** reads the current neutral translation constants
and adds their offsets to the original ROM references. It still tests the
expression and neck response coefficients. It works with the original template
and with fitted neutral positions. It temporarily drives the raw input bus,
then restores its values, connections, viewport refresh, and undo state on
success, cancellation, or failure.

This check begins after the GUI-to-expression mapping and does not establish
mesh or GUI quality. **Check Fit Geometry** is a separate, read-only neutral
check against your saved attachments and mapped target points. The tolerances
are 0.0001 cm for joint positions and 0.002 cm for mesh points. Behavior tolerances
are 0.006 cm, 0.025 degrees, and 0.00001 scale.

Loaded project reports are historical; load does not show a fresh PASS for the
current Maya scene. Scene changes outside the window can also invalidate prior
results, so run checks again before saving a final character. The old standalone
`maya_tools.quick_check()` uses the original absolute translations; use the
combined Behavior Check for fitted rigs.

## Project saving

The project toolbar accepts a folder. **Save Project** writes:

| Path | Contents |
|---|---|
| `facialSystemProject.json` | Neutral JSON reference, target mapping, scene path, options, and workflow step |
| `data/driveNeutralData.json` | Original neutral defaults and current attachment groups |
| `data/wrapFitData.json` | Coarse cage rest/current state and identities, when a working layer exists |
| `reports/driveNeutralFitResult.json` | Last preview/apply result, when available |
| `reports/rigBehaviorCheck.json` | Latest behavior check, when available |
| `reports/fitGeometryCheck.json` | Latest geometry check, when available |
| `scenes/` | Default destination for Save Character Scene As |

Save Project saves data and reports; **Save Character Scene As...** saves the
Maya scene. Load Project restores data and mapping without replacing the open
Maya scene. **Open Saved Project Scene** opens its saved scene when desired.
Paths inside the project are relative so the folder can be moved together.
The cage's native graph is stored in the Maya scene; its JSON records settings
and vertex snapshots. Open the saved scene to resume a layer. JSON alone does
not reconstruct missing Maya geometry. Legacy four-page projects remain readable.

## Compatibility and current scope

- Stock Maya nodes and built-in expressions; no external Maya plug-ins or pip
  packages are needed in Maya. The UI uses Maya's bundled PySide2 or PySide6.
- The bundled template preserves 339 joints, 331 driven joints, 1,962 driven
  channels, and seven skinClusters from the cleaned rig.
- Animation playback is independent of DNA, JSON, Python tools, and this folder
  once the native character scene is saved.
- The first wrapping test provides one coarse cage layer with manual matching.
  The auto seed is a symmetric sphere partially conformed to the source, not
  an anatomical facial cage. You can provide your own low-resolution cage.
- This version fits neutral translations. Joint orientation fitting, expression
  motion adaptation to new proportions, automatic face registration, regional
  refinement layers, new topology,
  original textured/wrinkle materials, and AI animation generation are later
  work. The existing facial GUI remains the animation interface.
- The fitting checks reject unsupported source placement/topology changes,
  posed controls, external translation drivers, nonzero joint pivots,
  non-identity joint offsetParentMatrix values, and locked/connected bind matrices.
  They do not unlock or lock attributes.

## Validation and development

The merged package passed 67 portable/mocked tests. These include all 107 ROM
references with fitted translation offsets, project persistence, cancellation,
rollback, and the upper-nose neutral regression. A real Qt offscreen test
covered the five pages with 331 rows, row actions, cage creation/binding/mirror/
reset/test/bake dispatch, baked-target mapping, saving, reloading, stale-result
clearing, and failure recovery. All 977 connected
translation writers matched the serialized bundled scene.

These integration checks ran outside Maya. Actual cage creation, native Proximity
Wrap evaluation/performance, target duplication, geometry/bind/undo operations,
and the combined window still need your Maya test
copy. Your earlier 107-case original-rig Maya result passed; it did not validate
the new fitting or integrated UI operations. See `VALIDATION.json` for the
distinction.

Run the non-Maya suite from standard Python:

```text
python tests/run_tests.py
```

`docs/API.md` describes script entry points. `developer/native_rebuild` retains
the original portable decoder, model, and scene compiler for later maintenance.
Its README explains the offline rebuild command. Historical native audits are
in `docs/reference`; they are not runtime dependencies.
