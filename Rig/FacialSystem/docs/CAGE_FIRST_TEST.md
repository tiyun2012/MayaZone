# Reduced head cage: first Maya test

Facial System 1.2.0 adds a reduced neutral-head cage with named facial landmarks.
It uses built-in Maya Reduce and Proximity Wrap, then bakes an independent target
for the existing joint-fitting workflow. No external plug-in is installed.

## Update and open

1. Save a test copy of your current Maya scene.
2. Replace the complete FacialSystem folder with this release.
3. Run this in Maya's Python Script Editor, changing the folder:

```python
import sys, importlib
sys.path.insert(0, r"C:\maya_tools\FacialSystem")
import facial_system
importlib.reload(facial_system)
facial_system.reload_ui(step="wrap")
```

Load your original driveNeutralData.json from Scene Setup if needed, then open
3 Cage Wrap. Keep facial and neck/head controls neutral. The accepted upper-nose
modifier defaults remain unchanged.

If an earlier cage exists, bake/save any edits you want to retain, then use
Remove Working Layer before generating its replacement. Bound cage topology
remains fixed. This removal retains sources, references, and baked targets.

## Define the important points

1. Assign the original neutral rigged head as Template / source head. It may
   remain skinned; the tool duplicates its visible shape for working copies.
2. Optionally assign the new face as Reference face. Its topology can differ.
3. Leave Custom cage blank. Choose Reduced neutral head, target 400 vertices,
   and Extra protected rings 0.
4. Open Facial Landmarks. Click Suggest from Rig, then review the proposed
   source vertices. Choose a row and Select Source Vertex to inspect it.
5. To define or correct a row, select exactly one source-head vertex in Maya
   and click Set Source Vertex. Manual assignments survive later suggestions.
6. Save the landmark JSON, or Save Project to preserve the draft before creating
   a cage. New Landmark Set starts over from the currently chosen neutral source.

The 32 named slots cover forehead, nose bridge/tip/wings, upper/lower lip center
and sides, mouth corners, eye corners, upper/lower eyelids, brows, cheeks, jaw
angles, and chin. L/R follow the recognized rig names. Suggestions use FACIAL
joint names and nearest source vertices; they require visual review. Check upper
versus lower lip and eyelid rows carefully where surfaces touch. An unrecognized
rig can be defined entirely by selected vertices. Unassigned rows are allowed;
only assigned points receive landmark protection.

## Generate and bind

Click Create Coarse Layer. The tool makes FS_CageWork with an independent working
preview and a cage copied from the neutral source. Only the cage is reduced.

All faces incident to landmark vertices and their captured mirror partners are
excluded from reduction. Extra protected rings adds topology-based padding;
0 still protects faces touching each landmark. The remaining faces are reduced
with geometric borders preserved. The tool reads Maya's source-ID color map,
checks retained positions, and verifies every protected vertex survived. Exact
source-to-cage IDs are stored, including distinct IDs at coincident points.
A failed check rolls back the working layer creation.

Both requested and actual cage counts are shown. Protected faces, borders, and
topology constraints can keep the actual count above the target. A heavily
protected small mesh may remain unreduced. This preserves parts of existing
facial topology; it does not generate new anatomical edge loops.

Click Bind Cage before moving any cage vertices. Keep Offset mode, layer enabled,
and weight 1 for the first test. Preview and cage originals share a bind space
while preserving world positions. Rest positions are checked before/after bind.
Fresh working transforms avoid inheriting the original head's locked TRS channels.

For a hand-authored cage, supply your coarse mesh as Custom cage. That option
takes priority over generation settings. Sphere seed remains available with
Around/Height and partial source conforming. Named source landmarks apply only
to Reduced neutral head generation.

## Test the response

Click Test Cage Response. It moves one +X-side control by 0.2 cm, reads the
preview, then restores the previous control/preview state, including prior edits.
The restoration path runs even when reading deformation fails.

| Field | Expected result |
|---|---|
| passed | true |
| maximum_output_move_cm | Greater than 0.000001 cm |
| maximum_restore_error_cm | At most 0.0001 cm |
| one_control_update_and_output_read_ms | Time for this update and output read in your Maya scene |

Check Layer's output-read timing may be cached and is not a drag-FPS benchmark.
Bind time is reported separately. These operations have not been timed in a
native Maya runtime here; retain warnings/reports if your test fails.

## Match the new face

Use Enable Mirror Editing or Select Cage Vertices, select individual controls,
and use Maya manipulators and soft selection to match proportions. Hide the
original head if it overlaps the preview; Select Source/Select Preview identify
the meshes. The reference remains a visual guide; automatic face registration
is not part of this version.

The landmark window provides two direct matching options after binding:

1. Choose a named row and Select Cage Landmark to manipulate that control.
2. Keep the row chosen, select one reference mesh vertex or positioned locator
   transform, then click Move Cage Landmark to Selected Reference Point.

The matching button moves one cage control and optionally its saved mirror
partner in one undo operation. A center-seam control stays on cage-local X=0
when mirror matching is enabled. An unmatched control requires disabling that
option. Use Maya soft selection/manipulators for broader changes around it;
this button does not fit all neighboring controls automatically.

Native mirror editing uses Object X. Restore Previous Symmetry or closing the
tool restores prior Maya symmetry settings. Mirror +X to -X and its reverse use
saved pair IDs after asymmetric edits. Incomplete pairings are reported; complete
pairs are required for enabling native mirror editing.

Reset Cage restores the bind transform and vertex positions, retaining named
source assignments. Source assignments are fixed once the cage exists; regenerate
the working layer to change them. Reference matching can be repeated after bind.

## Bake and update joints

1. Click Bake Target + Use in Fit Joints.
2. The independent target retains full source vertex IDs and has no skinCluster
   or wrap dependency. Existing Head_FitTarget objects remain; a new bake may
   become Head_FitTarget1.
3. The actual returned target is mapped into 4 Fit Joints when one matching
   captured source is identifiable. Otherwise use that mapping row's Use Selected.
4. Preview and Apply Neutral Fit using the original driveNeutralData capture.
5. Show the original rig mesh, review expressions, and run geometry/behavior
   checks in 5 Check & Save. Save Character Scene As and Save Project.

The original neutral attachment capture is never replaced by a fitted capture.
Other meshes such as eyes/teeth need their own mapped targets when their shape
or placement must change with the head.

## Save and resume

Save the Maya scene to retain native cage/preview/deformer objects. Save Project
also writes data/wrapFitData.json for the active layer and data/cageLandmarks.json
for source assignments, including drafts before cage creation. The landmark
window also has standalone Save/Load JSON. Reusing a draft checks source identity,
topology, and captured positions.

After reopening the scene, use Resume / Refresh Scene Layer. The actions reload
session metadata after Maya Undo. JSON records settings and snapshots; it does
not reconstruct missing native mesh/deformer objects on its own.

Remove Working Layer deletes owned cage/preview/session objects. Baked targets,
sources, and references remain. The window retains the removed layer's source
landmarks for regeneration; save them to retain them across sessions. Keep an
authoring scene copy to resume the same fitted cage later.

## Validation and scope

The release passed 86 portable/mocked checks plus real Qt widget dispatch outside
Maya. Native reduction/source-ID mapping, wrap deformation/performance, actual
undo, and viewport interaction still need this first test in your Maya scene.
One coarse layer is implemented. Regional cages, polish layers, automatic face
registration, and final surface projection are future work.

Implementation references: Autodesk's
[Reduce command](https://help.autodesk.com/cloudhelp/2024/ENU/Maya-Tech-Docs/CommandsPython/polyReduce.html),
[source vertex map](https://help.autodesk.com/cloudhelp/2024/ENU/Maya-Tech-Docs/Nodes/polyReduce.html),
[Proximity Wrap command](https://help.autodesk.com/cloudhelp/2024/ENU/Maya-Tech-Docs/CommandsPython/proximityWrap.html),
[node attributes](https://help.autodesk.com/cloudhelp/2024/ENU/Maya-Tech-Docs/Nodes/proximityWrap.html),
and [mode options](https://help.autodesk.com/cloudhelp/2024/ENU/Maya-Animation/files/GUID-A5B4553F-8135-4BF5-B2F1-14CAD47A8D31.htm).
