# Layer Skin UI 31 · Display and stroke-release feedback review

## Assessment

| Feedback point | Source finding and action |
| --- | --- |
| CPV history can be created | Confirmed: WeightView uses mesh-node color operations with MDGModifier. These edits are owned and temporary, but their nodes can exist while the colored Select view is visible. UI 31 reuses one private set and replaces its one color-upload edit instead of clearing/recreating the entire preview for every joint/display update. |
| Delete every createColorSet / polyColorPerVertex | Unsafe for a general scene: those types can belong to artist color data. The tool uses its retained modifiers to clear its own preview on Paint/Stop/close and before file IO. It does not delete scene-wide node types or guess ownership from a node's name. |
| Create a private color set on MObject mesh data | The documented Maya 2024 createColorSet API requires a mesh node. The suggested isHistoryOn shortcut is not an MFnMesh API 2.0 property. An unverified data-only replacement was not introduced. |
| Skip all preview when paint_armed is true | That also disables colors during Q, because Q deliberately leaves the session armed for Y. UI 31 retains the colored Select workflow. Active F9 painting uses Artisan; explicit selection handoff uses the owned temporary preview. |
| Hilite alone can leave Artisan unbound | Addressed: component mode keeps the loaded object in the active selection as well as the hilite list, while preserving the original component entries. Feedback is reasserted once for the coalesced mode transition. |
| Finalize reads/encodes/uploads again | Addressed for supported, already-bound painting: an exact successful-command receipt updates only changed displayed values and supplies the subsequent UI refresh. It avoids the duplicate Session snapshot/encoding/array upload and another queued UI snapshot. |
| Use the newest _decoded entry | Rejected: that cache is shared across meshes, may contain another result and can evict large states. The receipt is tied to the actual command, scope, mesh UUID, influence order and saved metadata. Cache ordering is never used. |
| Remove whole-mesh validation / read only dirty skin rows | Full native context reads, external-edit comparison, persistence, lock checks and write verification remain. Skipping them solely because a composite cache exists would weaken external-edit protection. This release does not claim an entirely O(brush vertices) stroke. |

The native-array backend commits on stroke release, not for every stamp during
a held stroke. Shift-Relax also stages its stamps before one command. The
remaining native command work can still dominate a high-resolution stroke.

## Exact-command result path

The UI installs an ordinary Python wrapper around future doIt calls while
keeping the registered command class and existing Undo objects. A scoped token
identifies the requesting paint operation. A capture of that command's final
remember(raw, state, after_weights) call supplies its saved result; nested
commands use separate capture frames.

A receipt is published only after the original command returns successfully.
The wrapper checks requested data, shape/skin, mesh UUID, vertex count, topology,
ordered influence IDs and the exact current metadata string. It works when the
normal decoded/composite caches reject the result for their memory budget.
Failure or a mismatch supplies no receipt and preserves the normal readback.

Session verifies its current scope and the saved contribution for each changed
vertex. It updates those displayed entries and caches the exact saved-state
hash. The existing native paint array already holds the stroke result, so it
is not uploaded again. For newly bound influences, unavailable helpers, or an
invalid receipt, the full prepare path remains. Actual write errors still roll
back the original command and never publish an optimistic result.

The saved full weight buffer and existing context handles supply one queued UI
refresh. It does not call context again or rerun prepare for that already-staged
view. Undo, tool changes, mismatched scopes and subsequent preparations invalidate
or consume this one-shot snapshot. Manual Refresh still takes a fresh snapshot.

## Display behavior and its limit

F9/right-click Vertex keeps the native brush, object surface binding, component
mode and selected components. Adding the parent uses an OpenMaya selection-list
copy in Maya, leaving component entries intact. Reentrant callbacks during
rebinding are display-only. The queued hotkey and selection-mode event share
one transition instead of reasserting feedback twice.

Q/Select vertices keeps weight colors through the owned temporary CPV preview.
Y/Paint clears that preview and returns to the brush. Stop/shaded view clears
the owned preview; before-save/export handling also clears it. The private set
and one upload modifier are reused across view updates. A versioned display
token skips even the value scan on unchanged passive selection notifications.

**This is not a completely node-free colored Select renderer.** Temporary CPV
history can still exist during the passive colored view. A separate native
viewport renderer would need Maya/VP2 development and profiling to replace it
without losing component picking, occlusion or deformed-mesh display. No such
renderer or untested history/data-block mutation is claimed here.

If generic color nodes remain after a clean Stop in a scene, inspect their
ownership rather than deleting all nodes of those types. An old orphan is not
automatically classified as tool-owned by its name.

## Completed checks

The local suite passes 836 tests with no skips/errors/failures. Seventeen checks
are new for receipts, view reuse, surface binding and cache-budget handling.
They include execution of the real command planner/Undo code against recording
Maya API objects, stale/external-edit rejection, metadata changed after commit,
native-write rollback, existing Undo objects after installation, exact receipt
selection with unrelated cache entries, and fallback after mismatched identity.

The Session/UI test prohibits duplicate context/metadata reads, prepare calls
and full array uploads after a successful receipt. A 250,000-vertex / eight-
influence fixture updates only twenty displayed entries in the receipt phase,
without scanning the full displayed list or encoding it. This measures the
post-command path, not native skin validation or actual Maya frame rate.

Native Maya/VP2/PySide2 verification remains pending. See VALIDATION.md.

## Reload and Maya checklist

Replace the complete folder and run in Maya Python:

```python
import runpy
runpy.run_path(
    r"D:/dev/MayaZone/layer_skin_prototype/layer_skin_ui_refresh.py",
    run_name="__main__"
)
```

Confirm **UI 31**. The registered plug-in stays **0.4.1**; command classes and
existing Undo objects are retained. No force unload or Undo reset is required.

1. Paint on a high-resolution mesh and inspect Paint info. After a supported
   stroke, callback_counts should include verified_commit_receipt. Confirm the
   saved values survive a joint switch, Q/Y and Undo/Redo.
2. Press F9/right-click Vertex. Confirm the heat map stays, component mode stays
   and selected vertices remain. Use Q to box-select, then Y to paint only the
   selection. Test Mask and Shift-Relax too.
3. Inspect the loaded mesh's history while painting, then while Q's colored
   preview is visible. Stop and return to Paint. Confirm only the preview's own
   history is removed and pre-existing artist color sets/nodes remain.
4. Change displayed joints/ramp while in Select. Confirm the preview does not
   grow a node chain. Test save/export with the preview visible and reopen the
   saved scene to check temporary display cleanup.
5. Measure release latency in Maya separately from brush movement and native
   validation. The host suite does not measure Artisan drawing, VP2/GPU cost,
   Maya lock enumeration or the remaining whole-skin read/comparison/encoding.

Primary API reference:
https://help.autodesk.com/cloudhelp/2024/ENU/MAYA-API-REF/py_ref/class_open_maya_1_1_m_fn_mesh.html
