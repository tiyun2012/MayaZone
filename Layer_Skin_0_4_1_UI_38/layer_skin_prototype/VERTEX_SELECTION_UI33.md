# UI 33: vertex selection and retained weight colors

## Updated flow

Click **Select vertices** to save the pending stroke and enter Maya's vertex
selection mode. The current joint/layer heat map is shown immediately and
republished after Maya completes the incoming tool and component setup. No
second click on Paint is required. Repeated Select clicks re-show the current
view. The Paint and Select buttons indicate which mode is active.

**Q** keeps the armed layer view while selecting. **Y** or **Paint** returns to
Artisan and removes the passive preview first. **F9 / right-click Vertex while
painting** continues to use the native brush in component mode, as in UI 32.
Choose another joint or a mask while selecting to update that displayed data.
**Stop / shaded view** restores normal viewport rendering and cancels queued
re-entry or display callbacks.

The delayed display uses a generation check and coalesces repeated mode events.
Closing, Stop, scene reset or returning to Paint makes an older queued callback
ineligible. Re-showing retained values does not reread skin weights, serialize
layer data or upload the native paint array. Unchanged versioned preview data
also avoids rescanning/remapping the full displayed list.

## What changed in the Node Editor

The earlier selection preview used `MFnMesh.createColorSet` and
`setVertexColors` with retained modifiers. Maya could add color-set/CPV history
nodes even though the tool later rolled those edits back. UI 33 replaces that
path with a transient Viewport 2.0 draw pass. There are no color-set operations,
DG modifiers, mesh plug writes, shader assignments or scene-node creations in
the new selection renderer.

The preview stores positions, triangle indices and per-vertex colors in Python/
Maya API arrays. A standard scene-render operation adds nonselectable colored
triangles through `MUIDrawManager`; native scene geometry, default picking,
components and HUD still render. Depth testing remains enabled. Its fill depth
priority is above the ordinary surface and below the native wire/point priorities.
This is a VP2 draw pass, not a Qt widget painted over the viewport.

The existing **rtkLayerSkinPaintBuffer** network node may still appear after
painting. Artisan's array-paint Undo records can reference it, so it is reused
and kept alive. Saved layer metadata also remains. Select vertices does not
create another paint buffer or another metadata node. Removing live paint
buffers just to hide them would break the native Undo assumptions.

Updating a live UI 32 window lets its old preview clean up the color edits it
still owns before the new window opens. Orphan nodes from an older crashed or
unavailable owner are not deleted by type or guessed ownership. Do not delete
all `polyColorPerVertex` or color-set nodes: artist data may use those types.

## Viewport lifetime and performance

A preview temporarily attaches its renderer to existing standard VP2 model
panels. It restores those settings on Paint, Stop, close, retargeting and before
save/export. It changes a panel only while that panel still points to its own
renderer. Another custom renderer is preserved rather than overwritten. If no
standard VP2 panel is available, the status reports why colors cannot be shown;
there is no fallback that silently creates color-history nodes.

Colors are rebuilt when the displayed values/ramp change. Positions and
triangles are read once and reused across clean camera/selection redraws.
Dirty notifications from the mesh and transform invalidate that geometry; the
next render setup reads the evaluated world-space positions and triangles.
This reads mesh geometry, not skin weights. Deleted-node callback IDs do not
block cleanup of the remaining callbacks and renderer.

DAG visibility, the panel polygon filter and object isolation gate the draw.
Existing artist color sets, shaders, display attributes, skin weights, scene
history and the modified flag are not edited by the preview. The standard
scene/HUD/present pass and default selection are retained. GPU behavior,
transparency/depth interactions, color management, specialized viewport
filters and component-isolation variants still require native Maya testing.

Skin command validation, Undo/Redo, write verification, brush/Relax math,
assignment, IO and UI 32's performance work are unchanged.

## Verification

The automated suite exercises the real display and VP2 classes against recording
API objects and the actual Qt workflow. It checks that graph/color/history edits
are never called, the scene snapshot remains unchanged, only one renderer stays
registered over repeated joint/ramp changes, custom renderers are preserved,
arrays are reused, deformations invalidate geometry, and failed restores retain
a registered renderer for cleanup retry. A 250,000-vertex fixture reuses geometry
on repeated draws. These checks validate API calls and lifecycle; they do not
simulate rasterization, occlusion, picking accuracy or GPU performance.

The Qt regression reproduces the reported timing problem by clearing the
outgoing feedback during incoming component/tool setup. Colors return without
Paint. Pending strokes are saved once, repeated mode events coalesce, Select
works before any Paint buffer is created, joint changes preserve selection, and
Stop/Paint/close cancel delayed previews. Mode buttons update on Q/Y handoff.

`VALIDATION.md` records the complete results and native-runtime limitation.

## Load and check in Maya

Replace the complete folder and run:

```python
import runpy
runpy.run_path(
    r"D:/dev/MayaZone/layer_skin_prototype/layer_skin_ui_refresh.py",
    run_name="__main__"
)
```

Confirm **UI 33**. The registered plug-in version remains **0.4.1**. A warm UI
refresh preserves the registered command, existing Undo objects and paint buffer.

In a working scene copy, choose a mesh, layer and joint, then test:

1. Click Select vertices before painting; verify the heat map and component
   picking. Observe the Node Editor and confirm no new color-history nodes.
2. Paint a stroke, click Select, select vertices, change joint, use Q/Y and
   repeat Select several times. Colors should follow the current data.
3. Check vertex/edge visibility and picking, occlusion behind another mesh,
   polygon display filters, object isolation, camera movement and deformation.
4. Stop, save/reopen, close and warm-refresh. Verify viewport restoration and
   native Undo/Redo, including paint records created before the refresh.
5. Repeat with a representative high-resolution mesh using your VP2 device.

An optional **native** smoke check is included. It requires an open UI 33 with a
mesh and joint loaded, finishes a pending stroke, enters vertex selection and
requests a real VP2 frame. It compares node UUIDs, history, artist color-set
names and the scene modified flag, and asserts that the VP2 draw callback ran:

```python
import runpy
runpy.run_path(
    r"D:/dev/MayaZone/layer_skin_prototype/maya_layer_skin_viewport_smoke.py",
    run_name="__main__"
)
```

The check leaves the heat map visible. Its callback count is not a substitute
for inspecting the actual colors, depth and picking. This host has no Maya
runtime, so this native check has not been run here.

## Autodesk API references

- [MSceneRender UI drawables and scene filter](https://help.autodesk.com/cloudhelp/2024/ENU/MAYA-API-REF/py_ref/class_open_maya_render_1_1_m_scene_render.html)
- [MUIDrawManager indexed meshes, colors and selectability](https://help.autodesk.com/cloudhelp/2024/ENU/MAYA-API-REF/py_ref/class_open_maya_render_1_1_m_u_i_draw_manager.html)
- [MRenderOverride default selection](https://help.autodesk.com/cloudhelp/2024/ENU/MAYA-API-REF/py_ref/class_open_maya_render_1_1_m_render_override.html)
- [MRenderer registration](https://help.autodesk.com/cloudhelp/2024/ENU/MAYA-API-REF/py_ref/class_open_maya_render_1_1_m_renderer.html)
