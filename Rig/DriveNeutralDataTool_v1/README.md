# Drive Neutral Data Tool 1.1.1

A Maya table for defining and saving **translation-only vertex attachments**
for facial joints, plus fitting those joints and the native rig to an edited
head with the same vertex IDs. The capture filename defaults to `driveNeutralData.json`.

## Open in Maya

1. Extract this ZIP into a folder. Keep all four Python modules together.
2. Open your native facial rig and return the facial GUI and neck/head controls
   to neutral before capturing defaults.
3. In Maya's **Python** Script Editor, run the following, changing the folder to
   the one containing `drive_neutral_data_tool.py`:

```python
import sys
sys.path.insert(0, r"C:\maya_tools\DriveNeutralDataTool")
import drive_neutral_data_tool
drive_neutral_data_tool.show()
```

The window finds skinned meshes and initially detects joint vertex groups.
For the rebuilt facial scene, Auto scope uses the connected native facial
joint outputs. It should discover the 331 driven joints, including driven
joints that have no skin weights. On other rigs, Auto scope uses skin joint
influences. You can also choose selected joints and their children.

To open the window for loading saved data without capturing the current pose:

```python
drive_neutral_data_tool.show(auto_detect=False)
```


## You already have Head_FitTarget

1. Save your Maya rig as a separate test copy and put its facial and neck/head
   controls in neutral. Keep `Head_FitTarget` unskinned and aligned with the
   original head.
2. Close the previous tool window and replace all Python files with this version.
3. Open directly at the new fitting tab:

```python
import sys, importlib
sys.path.insert(0, r"C:\maya_tools\DriveNeutralDataTool")
for name in ("drive_neutral_core", "drive_neutral_maya", "drive_neutral_fit", "drive_neutral_data_tool"):
    importlib.reload(importlib.import_module(name))
import drive_neutral_data_tool
dialog = drive_neutral_data_tool.show_fit()
```

4. Click **Load Neutral JSON...** and select your original `driveNeutralData.json`.
5. In **Fit New Shape**, map the original head row to `Head_FitTarget`. A uniquely
   matching target with that name is filled automatically. Otherwise select
   `Head_FitTarget` in Maya and click **Use Selected** on the head's source row.
6. Click **Preview Positions**. Green locators under `DN_FitPreview` show the
   fitted joint positions. Preview does not reposition the original rig.
7. When the preview is appropriate, click **Apply Neutral Fit**. The default
   option installs the edited rest mesh and keeps the existing skin weights.
8. Save the fitted rig as a new Maya ASCII file. The neutral behavior is in the
   scene; no fitting script or JSON is needed for animation playback.

Keep the original capture JSON. Do not recapture it from the fitted character.
Use **Export Fit Result...** for a separate `driveNeutralFitResult.json`.

Version 1.1.1 fixes a false non-neutral warning for raw indices 53 and 54:
`CTRL_expressions.noseWrinkleUpperL/R`. The supplied GUI stores these modifiers
at 1. Their range 0..1 is accepted while the main `noseWrinkleL/R` controls
remain zero. These modifiers alone change neither joint channels nor animated
maps; they do not require resetting or recapturing your saved JSON. Warnings
for other non-neutral inputs now include their connected control names and values.

The per-row **Update** button in Define Vertex Groups still changes which
vertices drive a joint; **Apply Neutral Fit** performs the character fitting.

### What Apply changes

- Computes absolute joint positions from the original saved group centers.
- Updates joint local neutral translations in parent-first order. For connected
  native facial channels, it edits the constant matrix cells instead of
  disconnecting animation inputs.
- Optionally installs the edited target as pre-skin rest geometry. Existing
  neutral skin deformation is baked before rebinding, and mesh tweaks are retained.
  Geometry is checked afterward, including on unchanged source meshes.
- Refreshes inverse bind matrices and the connected bind-pose records.
- Retains vertex IDs, weights, joint rotations, joint orientations, scales, and
  the existing facial control connections.

Blank mapping rows use saved default geometry when calculating joint positions.
Joints with no assigned group retain their saved world position. If your edits
also require moved eyes, teeth, or other separate parts, supply fitting copies
and map those source rows too.

Uncheck **Install edited rest mesh** for a joint-position-only test. The original
skin shape is retained while neutral joint translations and binding are updated.
**Reset to Saved Template** restores all captured joint positions and mesh shapes.
The independent target copy remains available for further sculpting.

Apply is grouped into one Maya Undo action. Cancellation or failed postconditions
runs that Undo automatically. Fit verification checks joint positions, visible
mesh points, and unchanged rotations/scales. A successful status reports PASS.
The tolerances are 0.0001 cm for joint positions and 0.002 cm for mesh points.

This fitting stage targets the reconstructed `NFRv1` rig. It rejects changed
source topology/placement, posed controls, unsupported translation drivers,
nonzero joint pivots, non-identity joint offsetParentMatrix values, and connected
or locked inverse-bind attributes before editing. Targets must be independent
unskinned meshes with matching vertex IDs/connectivity.

This is the neutral-position stage: expression response coefficients have not
been adapted to the new proportions. The old `maya_tools.quick_check()` includes
absolute positions for the original template; those translation references are
not the expected values for a fitted character. Use the fit verification and
visual GUI/skin tests for this stage.

## Define the groups

Each row has:

| Column | Action |
|---|---|
| Joint | Editable joint field; changes the association, not the Maya node name |
| Vertex group | Editable group label; hover to inspect mesh and vertex IDs |
| Verts | Number of selected driving vertices |
| Select Verts | Select this row's vertices in the Maya viewport |
| Update | Replace this group with your currently selected source vertices |
| Joint | Select this joint in the Maya scene |
| Source | Skin weights, nearest fallback, manual, or unassigned |

To correct a group:

1. Find the joint using the filter.
2. Click **Select Verts** to inspect its current group.
3. Select the vertices you want in the viewport.
4. Click **Update on that joint's row**. The row becomes Manual.
5. Click **Save JSON**.

You can select vertices from several captured source meshes for one group.
Faces and edges are also accepted by Update and are converted to vertices.
Selecting an object alone does not replace a group with its entire mesh.

The vertex-group names are labels stored in the data, rather than extra Maya
objects or object sets. Select Verts uses the saved mesh/vertex IDs directly.

## Automatic detection

- **Source meshes:** use all skin meshes, or select specific meshes and click
  Use Selected Meshes. Restricting the sources can help seed a joint from the
  head rather than teeth or an eye shell.
- **Max auto vertices:** defaults to 32. Manual groups can contain more.
- **Min / peak weight:** defaults to 0.25, meaning samples must have at least
  25% of that influence's largest weight on the candidate mesh.
- Skin-weight samples are ranked by weight, then proximity to the captured
  joint. The connected island containing the strongest sample is retained.
- If several source meshes have weights for a joint, one candidate mesh is
  selected by peak weight, mean selected weight, then proximity.
- Joints without useful weights can use a connected nearby patch. These rows
  are marked **Nearest - REVIEW**. Turn off Nearest fallback to leave them
  unassigned instead.

These are initial seed groups, not an anatomical guarantee. Review the jaw,
upper/lower lips, eyelids, and any orange fallback rows. A small automatic group
can be valid for translation; use Update when you want a different patch.

Auto-detect preserves **Manual** rows and keeps all originally captured neutral
positions. To replace a manual group, use that row's Update button. To capture
a completely new default mesh/pose, choose New Capture and detect again.
Add Selected Joints captures additional rows without replacing existing ones.

## What is saved

`driveNeutralData.json` includes:

- Mesh names, paths, UUIDs, vertex counts, and topology fingerprints.
- Original mesh vertex positions in world-space centimeters.
- Joint identities and parents, original world positions, and local translations.
- Per-joint vertex IDs, group centers, and joint offsets from those centers.
- Detection method/settings and flags for rows needing review.
- Original world matrices as reference metadata; this version performs no
  rotation fitting.

Defaults are captured once. Updating a group recalculates its center from those
saved defaults, even if you have since sculpted the live mesh. Saving does not
recapture the default. Validate Scene checks that objects can be resolved and
that vertex IDs/connectivity still match.

This data supports the next fitting stage:

```text
new joint position = default joint position
                   + new group center - default group center
```

Keep vertex count, ordering, and face connectivity unchanged for this first
workflow. Positions may change. The file stores world-space positions, so
later fitting must account for any differences in object placement or units.

## Scope and compatibility

Define Vertex Groups captures the attachment data. Fit New Shape uses it to
update neutral joint positions, the native evaluator constants, optional rest
geometry, and bind data. No DNA is required. Rotation fitting and expression
motion adaptation are separate later stages.

There are no external Maya plug-ins or pip dependencies. The GUI uses Maya's
bundled PySide2 or PySide6; the adapter uses Maya Python API 2.0. Target:
Maya 2024, with a PySide6 compatibility path for newer Maya releases.

The portable data logic and simulated fit transactions passed 32 tests. A 331-row Qt table was checked
outside Maya for row actions, filtering, group replacement, and JSON save/load.
The translation writer lookup was checked against all 977 connected translation
channels in the emitted native Maya file. Fit target mapping and Preview/Apply/Reset
GUI dispatch were checked outside Maya. The actual Maya geometry/bind updates and
undo execution have not been run in this environment; they need your first test
in a saved copy of your scene.

## Files and development

Keep these four modules together:

- `drive_neutral_data_tool.py`: GUI and `show()` entry point.
- `drive_neutral_maya.py`: Maya scene queries and selection.
- `drive_neutral_core.py`: data schema, grouping, JSON persistence, and fit transaction orchestration.
- `drive_neutral_fit.py`: native-rig preview, apply, verification, and reset.

`examples/driveNeutralData.example.json` is a small synthetic schema example,
not attachments for your actual head. Generate your actual file in Maya.
`VALIDATION.json` records the checks performed.

To run the included non-Maya tests with standard Python:

```text
python -m unittest discover -s tests -v
```

After replacing source files during development, save your data and close the
tool before reloading:

```python
import importlib
import drive_neutral_core
import drive_neutral_maya
import drive_neutral_fit
import drive_neutral_data_tool
importlib.reload(drive_neutral_core)
importlib.reload(drive_neutral_maya)
importlib.reload(drive_neutral_fit)
importlib.reload(drive_neutral_data_tool)
drive_neutral_data_tool.show(auto_detect=False)
```

Then use Load JSON to resume editing your saved table.
