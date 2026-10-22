# Viewport color updates · UI 20

UI 20 retains the UI 19 footprint changes while updating skin-file storage and
native weight batching. Paint info now identifies `ui20_production_skin_io`.
The new sparse rows and packed bases still expose numeric vertex weights to
the existing view; native GPU/viewport validation remains pending.

UI 19 adds a native screen-radius limit and samples radii after positioning
each interpolated Relax stamp. It also preserves fractional input coordinates
and replaces cached authoring helpers during a safe refresh. No painted Qt
overlay is added. This is a footprint update; it does not claim native GPU
or DPI verification. See RELAX_GUIDE.md for the fallback and diagnostics.

UI 18 adds layer influence padlocks and redistribution settings. Settings
changes hold the complete color handoff through pending paint, metadata save,
view refresh and any resumed brush. Locked weight views use zero opacity.
No painted viewport overlay is added. See INFLUENCE_GUIDE.md for lock scope.

UI 17 removes the hierarchy's manual scope controls and loads all skinCluster
joint branches together. The enabled color feedback and brush boundary changes
below are retained.

UI 16 adds the Relax footprint boundary described in RELAX_GUIDE.md. It uses
the native effective world radius and a projected-circle clip; no painted Qt
overlay or new viewport renderer is introduced. Outside neighbors remain read
only. Earlier context reuse, falloff preferences and enabled feedback remain.

UI 15 retains the context-reuse fix below and adds an explicit native brush
falloff choice. Feedback publication preserves that choice instead of forcing
Gaussian. Changing falloff does not disable color feedback or restart the tool.

## Remaining active-paint flash

UI 13 still stopped the brush for every Paint click and hierarchy-joint change.
It also disabled native color feedback before enabling it again. The UI 12
QWidget repaint gate hid those intermediate states from Qt repaint checks, but
does not establish that Maya's native viewport cannot present them. The user's
continued report prompted direct-draw probes independent of that gate. Both
reported paths exposed material/default states in the old lifecycle.

UI 14 changes the lifecycle for an active, matching paint surface:

- Repeated Paint keeps the existing context, buffer, gesture controller and
  return tool. An unchanged view does not rewrite the array or reconfigure its
  callbacks, selection or tool.
- A hierarchy-joint change saves the outgoing stroke first, validates the next
  view and replaces the complete array in place. Its callbacks remain guarded
  during transfer. Native color feedback stays enabled.
- Feedback reloads now publish enabled flags directly, with no explicit off
  step. Rejected saves retain the old joint; failed array/feedback transfers
  restore its view. Saved layers, skin weights and Undo do not change for a
  display-only action.
- Changing mesh/buffer resources or losing the selected paint object still
  requires normal activation. Stop / shaded view, leaving the native tool,
  close and scene cleanup continue to disable colors intentionally.

Run the updated layer_skin_ui_refresh.py with the existing window open. Confirm
the title ends in **UI 20**. Paint info reports
`authoring_revision: ui20_production_skin_io` and `native_view_updates` with
`starts`, `reuses`, `last` and `feedback_refresh: enable_only`. On an active,
unchanged mesh, repeated Paint and hierarchy picks should increase reuses
without increasing starts. These diagnostics describe the path taken, not GPU
pixel verification.

Paint info also reports `brush_falloff`, actual `stampProfile`, `value`,
`selectedattroper`, `usepressure` and `accopacity`. Each native stroke receipt
records the falloff active when it began. These settings help distinguish a
soft-edge value from a saved-value or display error.

In Maya, paint different nonuniform values on two joints, then repeatedly pick
them in the hierarchy and click Paint. Check that only the old/new weight colors
appear, without a material/black/default flash. Also verify continued brush
response, one pending-stroke Undo/Redo, B-radius and Shift Relax, rejected writes,
multiple viewports and explicit Stop. If the flash remains, the Paint info
revision and starts/reuses values distinguish an unexpected restart from a
native feedback-cache redraw. Maya/VP2 execution is unavailable in this build
environment; direct API-state probes and real Qt regressions pass locally.

## Retained UI 12 repaint gate

The UI 11 report described a brief return to base/material color when Paint or
a joint switch loaded another color view. The code stopped/cleared old feedback
before configuring its replacement. Real Qt repaint tests reproduced a material
frame between the two views for Paint, joint switches, mask/display changes
and layer actions.

UI 12 batches the entire synchronous UI action, including nested stop/start,
selection refresh, data loading and native feedback setup. Existing model-view
widgets temporarily defer Qt updates; their previous frame remains until the
new color field is ready. Each previously enabled view is restored before the
finished native frame is requested. Views already disabled are left disabled.
Forced brush redraws defer during this handoff, while normal live strokes retain
the working UI 11 path. Failed layer actions retain their last held color values.

This uses no painted child widget, screenshot overlay, global Maya refresh
suspension, material replacement, attribute unlock or new Undo command. Native
Artisan and the held vertex-color renderer still use the same data/backends.
Only frame publication during actions changes. Stop / shaded view, close and
scene/file cleanup still intentionally restore normal shading. During Maya's
late exit, pending handoffs abandon widget/view callbacks with the existing
exit teardown policy.

Paint info also reports `color_handoff`
with its active state, handoff count, number of enabled surfaces and last redraw
error. Zero surfaces can mean there was no enabled visible model-view widget.
The diagnostics report implementation state, not proof of correct GPU pixels.

In Maya, test Paint from a held view; repeatedly switch joints/layers, weights/
masks and heat-map/grayscale; run Flood/Relax/Undo/Redo; and reject a pending
stroke on a disposable locked skin. The view should change directly to the new
colors. Confirm Stop / shaded view still shows the material. Test multi-panel,
torn-off and high-DPI views, save/reopen and Maya shutdown. Qt recording tests
pass, but actual Maya/VP2 flash behavior remains unverified in this environment.

## Live smoothing response

UI 11 fixes two paths that could hide the Shift-relax result. Fixed coverage
was on by default: smoothing a sparse patch authored for only one joint then
kept its visible contribution unchanged. Preservation is now opt-in, allowing
the brush to feather the patch into neighboring vertices inside its radius.
Its formula is still one-ring Jacobi smoothing, not Maya's native skin brush.
Only the outline comes from Artisan.

The old redraw call waited for Maya's next idle, potentially after mouse release.
UI 11 also forces native redraws during the UI-thread gesture, throttling
immediate requests to 30/second and forcing the saved/restored final frame.
No color-set rebuild or Qt overlay is added to the active brush. The existing
native doubleArray receives every changed selected-joint value before redraw.

Refresh from UI 10 or older adopts the new coverage default once; later
refreshes retain an explicit Preserve coverage choice. Paint info's Relax report
now separates mesh hits, vertices in the brush and changed preview vertices.
An unchanged result explains missed geometry, an empty radius, zero strength/
opacity, preservation or a uniform/group-limited field. A brush over a coarse
face can hit the face yet reach no vertices; increase Brush radius in that case.

Test a nonuniform edge: choose an editable layer/joint, keep Preserve coverage
off, use Strength 0.5 and positive Opacity, then Shift-drag so that vertices on
both sides of the edge lie inside the brush. Check colors during the drag,
release, switch joints and return, and Undo/Redo. Constant weights/masks have
nothing to average and correctly show no change.

## Retained UI 10 overlay diagnosis

The supplied screenshot shows a black viewport and repeated gold brush rings.
The prior Shift controller created a full-viewport QWidget named by its Python
class, BrushCircle. It enabled WA_NoSystemBackground/WA_TranslucentBackground
and painted a gold circle with QPainter while moving. This extra Qt drawing
surface sits over Maya's native graphics viewport; its retained circles and
background composition are consistent with the screenshot. This is the likely
rendering conflict identified from the image and code, not a native GPU
reproduction in the build environment.

UI 10 removes that widget entirely. It leaves the native Artisan outline
enabled and sends a passive MouseMove to the original viewport receiver to
update its position. These feedback events contain no pressed buttons or
keyboard modifiers, and never send a press, drag or release to Artisan. A
reentry guard separates feedback from the custom Relax gesture. Maya owns the
outline rendering; no replacement QPainter surface or raw OpenGL calls are used.

The Relax equations, influence budgets, mask behavior, native array, saved
schema and registered 0.4.1 command remain unchanged. UI 11 changes the default
coverage option described above. One completed
gesture still saves one authoring command. Heat map/grayscale display remains
available. Release, cancel and no-hit paths request a native viewport redraw.
Tool handoff during feedback completes the edit once and retains the incoming
tool. Existing normal Paint and B + drag routing are retained.

## Update an open window

1. Release the mouse to complete the current stroke, or press Escape to cancel
   its unfinished Shift preview.
2. Replace the complete extracted folder with this package. Keep the existing
   Layer Skin 0.4.1 window open.
3. Run the refresh script using your actual extracted path:

```python
import runpy
runpy.run_path(
    r"D:/dev/MayaZone/layer_skin_prototype41/layer_skin_ui_refresh.py",
    run_name="__main__"
)
```

4. Confirm the title ends in **UI 12**, then click Paint to resume.

Refresh saves valid pending data, closes the old controller/overlay, loads a
fresh brush helper and forces one native redraw. A rejected pending save keeps
the existing window open so that the error can be resolved first. It does not
unload the registered plug-in, clear Undo, change the viewport renderer, alter
materials or reset panel display settings. For a fresh Maya session, use the
normal layer_skin_launch.py launcher from the complete folder.

## Native checks still required

Maya is unavailable in the build environment. The local tests exercise real
Qt events with recording Maya adapters; they cannot validate VP2 pixels, GPU
drivers or real Artisan outline movement. In Maya 2024/Windows:

1. Reproduce on the same mesh/camera that previously went black. Move the brush
   normally, hold Shift and drag across the mesh for several seconds. The mesh
   must remain visible and the outline must follow the pointer without trails.
2. Release and make a normal stroke. Check one Undo/Redo per completed edit.
   Repeat Shift-relax in both heat-map and grayscale views, and in Mask mode.
3. Test a drag with no mesh hit, Escape cancellation, releasing Shift before
   the mouse, changing tools and B + drag radius adjustment.
4. Switch joints/layers, select vertices/edges, flood Relax, then resume Paint.
   Confirm the held colors and saved layer values still reload correctly.
5. Refresh with the old UI open, including after a failed black-frame stroke.
   Check the old widget disappears, data survives and the UI 12 brush resumes.
6. Test high-DPI displays, a torn-off model panel and production high-resolution
   meshes. Check real native paint/Undo and Maya close/open lifecycle as before.

Paint info now reports authoring_revision `ui12_color_handoff` and,
while painting, relax_brush.feedback_backend `Maya Artisan outline`,
qt_viewport_overlay false, and the passive hover-event count. These diagnostics
describe the active implementation; they do not independently prove correct
GPU rendering.

## References used to check the integration

- Qt mouse event constructors, coordinate spaces and button state:
  https://doc.qt.io/archives/qt-5.15/qmouseevent.html
- Qt widget translucency and painting behavior:
  https://doc.qt.io/qt-6.5/qwidget.html
- Maya Artisan outline/feedback flags:
  https://help.autodesk.com/cloudhelp/ENU/MayaCRE-Tech-Docs/Commands/artUserPaintCtx.html
- Maya M3dView refresh and idle-scheduled refresh:
  https://help.autodesk.com/cloudhelp/2024/ENU/MAYA-API-REF/py_ref/class_open_maya_u_i_1_1_m3d_view.html
- Qt viewport-widget update state and batched painting:
  https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QWidget.html
