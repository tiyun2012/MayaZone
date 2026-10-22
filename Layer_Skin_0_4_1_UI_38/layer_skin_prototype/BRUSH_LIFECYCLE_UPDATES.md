# Layer Skin UI 30 · Feedback review and implementation

## Brush sizing

The UI 29 filter armed its guard only on KeyPress. Qt can deliver
ShortcutOverride before invoking a registered shortcut, and that shortcut can
consume the key without a viewport KeyPress. UI 30 arms the guard at either
event without accepting or consuming Maya's B shortcut. Auto-repeat does not
repeatedly commit. A shortcut delivered to the main QWidget/QWindow uses its
focused viewport; a text editor's B shortcut is left alone.

The settings callback returns while B or the radius mouse button is held. Both
release orders are supported; the final idle sync updates scalar UI controls
once both are released. Mouse movement during sizing does not schedule those
queries. A real pending Paint or Relax stroke retains its one normal save before
sizing. The radius field keeps its existing scalar-only edit path.

## Surface and state cache

Preparing a target stages full shape/transform paths and uniquely resolved
short/namespaced aliases. Known callbacks use set membership with no cmds
lookup. Unknown spellings are resolved once; rejected/ambiguous names are cached
too. Retargeting clears the cache. Component spellings use their object prefix.
The existing fullpaths setting stays enabled. Reload the target after DAG changes
to restage its paths; this is a staged authoring cache, not a scene-name tracker.

An editable view stages a canonical state hash. `_begin_stroke` reuses that hash
and the existing layer values rather than calling prepare, reading all skin
weights, re-uploading the native array and encoding the stack again. Existing
immutable state objects reuse their hash. Readonly view changes do not encode a
new stack. Undo/Redo mark the authoring cache dirty; the next refresh/stroke
prepares it before accepting samples.

The feedback's suggested raw_metadata hash is not used as the command guard.
Raw metadata can contain a different influence order; the existing command
compares against the encoded canonical state after UUID remapping. Caching that
canonical hash retains this protection. Real commits still compare saved layer
data, check native skin weights, read back the array, validate the result and
remain undoable. An external change after staging is rejected and reloaded.

This removes redundant work at ready native stroke startup. It does not make
actual commits, geometry queries or Shift-Relax initialization constant-time.
Those operations retain their own real data/geometry and validation costs.

## Component mode and returning from Select

F8-F11 no longer force selectSuperContext. Native mode/mask commands run normally,
and the loaded mesh is hilited when needed. Paint and in-place joint changes
preserve existing component selections. A selected-vertex/edge scope is captured
once per stroke and applies to saved native painting and custom Shift-Relax.
With no components, no full-mesh index list is allocated for that brush scope.

Q and the Select vertices button remain actual selection-tool actions with
retained colors. Tool cleanup releases transient brush resources but leaves
the session armed. A MEL setup notification plus the existing ToolChanged event
reconnects on Maya's explicit return to the Layer Skin context, such as Y.
ToolChanged also covers builds that delay toolSetupCmd until the first surface
click. The queued return checks session generation, ownership and current tool.
It never forces Paint over Select/Move or after Stop, close or scene reset.

Stop/shaded view disarms re-entry. Internal actions that retain the color view
can pause without disarming; changes to their current viewed layer/joint are
used on return. Re-entry stages current data and checks external skin edits.
The canonical guard, joint locks, skin IO and layer composition are preserved.

## Completed host checks

The full count/timing is in VALIDATION.md and LOCAL_TEST_RESULTS.txt. New coverage
includes a real Qt QShortcut consuming B without a viewport KeyPress, window
shortcut routing and text-field isolation, zero sizing sync while either button
is held, staged headers and aliases without heavy reads, canonical remapping,
Undo invalidation, selected-scope native and Shift painting, rejected-scope
recovery, Q/Y settings and selection restoration, cancelled re-entry and
external-edit rejection.

PAINT_LIFECYCLE_BENCHMARK.json contains CPU replays at 100,000 and 250,000 vertices
with eight influences. Each runs 500 iterations of cached surface/array callbacks
and an unpainted native header after staging. Both record zero skin-context,
metadata, array read/write, encode, name-resolution and parent-query calls.
Run `python benchmark_paint_lifecycle.py` outside Maya to reproduce it.

The recording Undo adapter uses balanced chunk markers for this unpainted replay,
avoiding its test-only full-scene deepcopy at every marker. No real paint, array
diff, commit, Maya event scheduling, native brush drawing or VP2/GPU time is
measured. The host timings are not a Maya frame-rate claim.

## Install and native tests

Replace the complete folder, run layer_skin_ui_refresh.py and confirm **UI 33**.
The registered plug-in stays at **0.4.1**. Brush/selection helpers use a new cache
revision; existing command classes and Undo objects remain loaded. The reload
snippet and native Maya checklist are in COMPONENT_SELECTION.md. Native Maya,
VP2 and PySide2 testing remain pending on this host.

## Primary API references

- [Qt QEvent: ShortcutOverride](https://doc.qt.io/qt-6/qevent.html)
- [Maya artUserPaintCtx callbacks and fullpaths](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/CommandsPython/artUserPaintCtx.html)
- [Maya MEventMessage](https://help.autodesk.com/cloudhelp/2024/ENU/MAYA-API-REF/py_ref/class_open_maya_1_1_m_event_message.html)
- [Maya selectType](https://help.autodesk.com/cloudhelp/2024/ENU/Maya-Tech-Docs/CommandsPython/selectType.html)
- [Maya hilite](https://help.autodesk.com/cloudhelp/2024/ENU/Maya-Tech-Docs/CommandsPython/hilite.html)
