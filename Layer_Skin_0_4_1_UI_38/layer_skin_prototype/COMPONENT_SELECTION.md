# Layer Skin UI 31 · Component painting and selection

## Workflow

1. Load a mesh, choose a layer/joint and click **Paint**. If vertices or edges
   are selected, their mode and selection are preserved. The loaded mesh is
   hilited for Artisan instead of replacing the component selection.
2. Use **F9** or right-click **Vertex** to enter component mode while keeping
   the brush. F8/F10/F11 retain Maya's native mode/mask behavior. None of these
   commands forces Select or re-enters Paint over another tool.
3. To pick components, press **Q** or click **Select vertices**. The current
   weight colors stay visible. Select vertices or edges, then press **Y** or
   click **Paint** to return to the brush. Y works after an armed Paint session;
   if the tool was explicitly stopped, start it with Paint again.
4. Paint affects the selected vertices or selected edge endpoints. If no
   components are selected, the brush has its normal whole-surface scope.
   The brush still determines the radius/footprint within that selection.
5. **Stop / shaded view** saves pending paint, disarms re-entry and restores
   normal shading. Closing the window or resetting the scene also cancels any
   queued re-entry. Vertex selection and brush dragging use separate Maya tools.

Weights retain the chosen ramp; mask display remains grayscale. The existing
Whole mesh controls apply to their Flood/Assign actions. They do not override
the brush's component scope. Selected faces or components on another mesh are
rejected by the existing vertex/edge scope validation; F11 can still be used
to change Maya's selection mask without forcing a tool switch.

## Data and display

Pending real paint is saved once on a component-mode change or explicit tool
handoff. The selected component scope is captured once per genuine stroke,
using OpenMaya selection data. Native array diffs are limited to that scope on
release; any outside-scope working values are restored. Shift-Relax intersects
each geometric footprint with the same initial selection and updates only that
intersection. Its neighbors remain available as unchanged boundary values.

If scope validation fails, a rejected stroke header restores native working
values at release so they cannot leak into a subsequent valid stroke. The
existing saved-state and native skin-weight validation still run on commit.

F9 keeps native feedback and the working array active. Q/Select vertices releases
the array and publishes the retained color preview. Y reconnects only if the
session is still armed, owns the callback bridge, and Maya's current context is
the Layer Skin context. A later tool change cancels the queued return. It
restores the current layer/joint and saved scalar brush settings, and refreshes
their UI fields. It also validates external edits before accepting new paint.

The existing coalesced selection notifications handle right-click mode changes.
Ordinary component clicks do not read skin weights, upload color arrays or scan
the display range. There is no polling or frame callback. Old UI 29 behavior,
which forced Select on F9, is replaced by this workflow.

## Reload

Replace the complete `layer_skin_prototype` folder and run in Maya Python:

```python
import runpy
runpy.run_path(
    r"D:/dev/MayaZone/layer_skin_prototype/layer_skin_ui_refresh.py",
    run_name="__main__"
)
```

Confirm **UI 33** in the title. The registered plug-in remains **0.4.1**; the
refresh preserves its command class and Undo objects. The entry point also opens
the window when it is closed. No plug-in unload or Undo reset is required.

## Maya verification checklist (pending)

1. Load a high-resolution mesh and paint distinct patches on two joints. Use
   F9 and right-click Vertex: confirm the brush, heat map and values remain.
2. Press Q, select several vertices, then Y. Confirm the brush returns in
   component mode, the selection remains, and saved paint is limited to selected
   vertices. Test Replace, Add, Scale, Mask and Shift-Relax, then Undo/Redo.
3. Select edges and repeat: only their endpoints inside the brush should edit.
   Clear components and confirm normal unrestricted brush painting. Select a
   component on another mesh and confirm rejection leaves saved weights intact.
4. Use Select vertices, perform Flood/Relax, change the viewed joint and return
   to Paint. Confirm the retained view follows the current data without a
   material flash. Repeat with a locked joint and final-skin readonly view.
5. Adjust B + drag, press Q before the next settings sync, and return with Y.
   Confirm radius, opacity, value and falloff remain. Test both key/mouse release
   orders and switching mode immediately after release.
6. Stop/shaded view, close/reopen, refresh, and reset the scene. Confirm no queued
   return steals another tool. Check the full report with Paint info when a real
   Maya event sequence differs from the local Qt/recording-API tests.

Maya's real hotkey mapping, native Artisan event ordering, viewport drawing and
PySide2 remain unverified on this host. See VALIDATION.md for completed checks.

UI 31 retains the object-level Artisan binding alongside components and
reasserts feedback once per mode transition. Its colored Select preview remains
owned temporary CPV history; see FEEDBACK_REVIEW_UI31.md for this limit and the
new exact-command result path.
