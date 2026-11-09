# First Maya cage-fitting test

This release adds one coarse fitting layer. It uses built-in Maya Proximity
Wrap in Offset mode, with a small symmetric cage, then bakes an independent
target for the existing joint-fitting workflow. No external plug-in is installed.

## Update and open

1. Save a test copy of your current Maya scene.
2. Extract the complete updated FacialSystem folder over your previous copy.
3. Run this in Maya's Python Script Editor, changing the folder:

```python
import sys, importlib
sys.path.insert(0, r"C:\maya_tools\FacialSystem")
import facial_system
importlib.reload(facial_system)
facial_system.reload_ui(step="wrap")
```

The window is now Facial System 1.1.0 with five workflow pages. Load your
original `driveNeutralData.json` from Scene Setup if it is not already loaded,
then return to **3 Cage Wrap**. Keep facial and neck/head controls neutral.
The accepted upper-nose modifier defaults remain unchanged.

## Create and bind

1. Select the original head mesh in Maya. Click **Use Selected** beside
   **Template / source head**. This is the mesh whose vertex IDs we will retain.
2. Optionally select the new face and assign **Reference face**. Its topology
   can differ; this version uses it as a visual guide and does not project or
   register automatically.
3. Leave **Custom cage** blank for the automatic seed. Defaults are Around 12,
   Height divisions 12, and Fit seed cage to source surface enabled.
4. Click **1 Create Coarse Layer**. The tool makes an independent working
   preview and a symmetric cage under `FS_CageWork`. The original rig is retained.
5. Click **2 Bind Cage before moving cage vertices**. Keep mode Offset, layer
   enabled, and weight 1 for this first test.

The auto cage is a small sphere shaped to the source bounds and partially
conformed to its surface. Some seed spacing is retained to reduce coincident
controls in narrow regions. It is intended for head proportions and silhouette,
not detailed anatomical matching. You can instead select your own low-resolution
face cage in Custom cage; the tool copies it and retains the original.

The preview and driver originals are put into the same bind coordinate space
while preserving world positions. Their rest mesh is checked before and after
binding. Changing cage or preview topology invalidates this binding.
Working copies use fresh transforms, so the original head's locked transform
channels do not prevent this setup. The source's locks remain as saved.

## Verify the native response

Click **Test Cage Response**. It briefly moves one +X-side control by 0.2 cm,
reads the deformed preview, and restores the previous control/preview state.
It also works after manual cage edits and preserves those existing edits.

The report should contain:

| Field | Expected meaning |
|---|---|
| `passed: true` | The preview responded and restored within tolerance |
| `maximum_output_move_cm` | Greater than 0.000001 cm |
| `maximum_restore_error_cm` | At most 0.0001 cm |
| `one_control_update_and_output_read_ms` | Measured time for this one test update in your Maya scene |

The separate Check Layer output-read timing can be cached and is not a dragging
frame-rate benchmark. Bind time is reported separately. This release has not
been timed in an actual Maya runtime here; this button provides the first local
response/performance measurement.

If a command errors or the report fails, retain the warning/report for debugging.
The test's control-restoration path runs even when reading deformation fails.

## Match the new face

1. Use **Select Cage Vertices** or **Enable Mirror Editing**. These enter vertex
   selection mode. Click individual cage vertices, then use Maya manipulators
   and soft selection to match the reference.
2. If the original head overlaps the working preview, hide the original head
   in the viewport while editing. Select Source and Select Preview help identify
   them. Keep the reference visible as needed.
3. Native mirror editing uses cage-local Object X. The prior Maya symmetry
   settings are restored by Restore Previous Symmetry or when closing the tool.
4. The manual **Mirror +X to -X** and reverse buttons use saved pair IDs. They
   remain useful after asymmetric edits. A custom cage with unmatched vertices
   reports their count and supports manual editing; live mirror enabling requires
   complete pairs. Center-seam vertices retain their Y/Z edits on mirroring.
5. **Reset Cage** restores its original bind transform and vertex positions.
   Maya Undo can reverse the reset. It does not modify source mesh or joints.

Offset is the lightweight coarse-fitting default. Surface mode additionally
accounts for the driver's surface orientation and may suit larger bends. Both
are built-in Maya modes; switching can change the deformation result.

## Bake and update joints

1. Click **3 Bake Target + Use in Fit Joints**.
2. The new mesh has source vertex IDs and no skinCluster or wrap dependency.
   If Head_FitTarget already exists, it is retained and the new bake receives
   a suffix, such as Head_FitTarget1.
3. The tool opens **4 Fit Joints** and maps the actual returned target when it
   can identify one matching captured source. Otherwise use that row's Use Selected.
4. Preview joint positions and Apply Neutral Fit using the original capture.
5. Show the original rig mesh for deformation review. Go to **5 Check & Save**
   for geometry/behavior checks and Save Character Scene As.

## Save and resume

Save the Maya scene to retain the cage, preview, native deformer, and saved
rest-state metadata. Save Project also writes `data/wrapFitData.json` when a
layer exists. That JSON records settings and snapshots; it does not reconstruct
missing mesh/deformer objects by itself.

After reopening the saved scene, use **Resume / Refresh Scene Layer**. Read
fresh session data after undoing creation or binding; the UI actions do this
automatically. The stage is optional when a fitting target already exists.

**Remove Working Layer** removes only the owned cage/preview work group and its
session. Existing sources, the reference, and baked targets remain. Use it after
baking when saving a scene without the authoring layer. Keep an authoring scene
copy if you want to resume fitting later.

## Current test scope

Only one coarse layer is implemented here. Regional cages, polish layers,
automatic correspondence, anatomical masks, and final surface projection are
later work. Native deformation, actual undo, and interaction quality need the
first test in your Maya scene; portable/mocked tests and real Qt widget dispatch
were checked outside Maya.

Implementation references: Autodesk's
[Proximity Wrap command](https://help.autodesk.com/cloudhelp/2024/ENU/Maya-Tech-Docs/CommandsPython/proximityWrap.html),
[node attributes](https://help.autodesk.com/cloudhelp/2024/ENU/Maya-Tech-Docs/Nodes/proximityWrap.html),
and [mode options](https://help.autodesk.com/cloudhelp/2024/ENU/Maya-Animation/files/GUID-A5B4553F-8135-4BF5-B2F1-14CAD47A8D31.htm).
