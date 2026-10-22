# Saved data and cleanup

Layer Skin 0.4.1, Authoring UI 12 retains **Cleanup…** beside Undo/Redo at the
bottom of the main panel. It replaces the earlier Bake / detach button with
an explicit inspection and cleanup workflow. The registered plug-in/API version
is still 0.4.1; apply the usual UI refresh with the complete updated folder.

## Why the layers return

The scene contains a normal Maya network node with a compressed
`rtkLayerSkinData` string. Message connections identify its mesh and
skinCluster. It stores the Base snapshot, layer names/order, masks, painted and
generated samples, settings and frozen assignment reference. This saved data
is independent of the window, so opening another window or reopening the
saved Maya file intentionally finds the same stack.

There are also temporary Python caches and a native paint working array.
Clearing a memory cache does not remove the scene's saved layer data.

| Data | Saved in the Maya scene? | Cleanup behavior |
| --- | --- | --- |
| Base, layers, masks, samples, assignment reference | Yes, on the linked layer-data network node | Remove saved layers deletes the current mesh's owned data nodes. |
| Native skin weights and influence membership | Yes, on the existing skinCluster | Kept by cleanup. |
| Decoded/composed state, assignment geometry and Relax topology caches | No | Clear memory caches releases these caches; they rebuild when needed. |
| Native paint working arrays | No: marked do-not-write and transient | Valid arrays stay available for Artisan Undo. Only invalid cached references are pruned. |
| Temporary held-view color set | No persistent authoring role | Existing Stop/close/file-I/O lifecycle restores the original display. |
| Loaded Utilities file and import Preview | No | Unload releases the file/cache; close releases both. Clear memory caches invalidates the import Preview. |

## Clear memory caches

Use **Cleanup… → Clear memory caches** for the temporary caches. The right
panel's existing Clear assignment cache shortcut uses the same expanded cache
clear operation. It keeps saved layers, masks, assignment reference, native
skin weights and the displayed values. A valid pending stroke is saved first,
then the active brush stops and the held color view remains.

This action does not purge Maya Undo or guarantee that all process memory is
returned to the operating system. The window still needs its current loaded
state and displayed values. Live native paint arrays can still be referenced
by existing Maya Undo entries and remain in the session. Cache clearing itself
does not create a skin edit or a new authoring Undo entry; completing a pending
paint stroke retains its normal Undo step.

Utilities retains its loaded external skin file so another target can use it.
Use **Utilities → Unload** to release that file. Cache clearing invalidates an
old import Preview, which must be rebuilt before importing. A scene change
clears target fields and mappings but keeps the external file loaded.

Selection of a different mesh uses that mesh's own saved data. The existing
new/open scene reset now clears assignment, decoded/composed and Relax caches,
and closes any old Cleanup inspection. Layers stored in the newly opened file
remain available until explicitly removed.

## Remove saved layers and keep the current skin

1. Load the intended mesh and click **Cleanup…**.
2. Check the displayed mesh path and the listed saved-data nodes. The scope is
   this mesh only. **Inspect current mesh** updates the list after changing
   the loaded mesh or scene.
3. Click **Remove saved layers · keep current skin**. A valid pending stroke
   is saved first. If it cannot be saved, removal stops and reports the error.
4. The layer stack, its captured Base and frozen reference are removed. The
   current native skin weights, skinCluster, joints/influences and mesh remain.
   The original saved Base cannot be recovered from a detached scene file;
   Undo restores it while the deletion remains in the current Undo history.
5. Use Maya Undo or Undo + refresh to restore the exact saved layer nodes and
   their connections. Redo removes them again. Click **+** after cleanup to
   start a fresh stack whose Base is the current native skin result.
6. **Save the Maya scene after cleanup.** Reopening an older, unmodified file
   reloads the layer data stored in that file.

The removal itself is one native Maya Undo group and never resets earlier Undo
history. The helper deletes only the listed owned network nodes; it does not
call a skin-weight setter, remove influences, delete mesh attributes or inspect
every vertex. A prior pending stroke remains its own completed authoring edit.
Native skin edits made outside Layer Skin are retained by this cleanup path.

## Recovery and ownership rules

The inspector uses the tool's exact network-attribute signature and mesh/skin
message links. It does not depend on node-name prefixes and does not decode
the saved payload. Therefore corrupt compressed data, duplicate owned data
nodes, changed topology and an otherwise unsupported editor mesh can still be
cleaned without passing the editor's full skin-context validation. An unskinned
mesh can be cleaned when an explicit mesh ownership link remains.

The current mesh and candidate node identities are checked again before
deletion. Changing scenes, switching the loaded mesh, adding another data node
or removing one after inspection requires inspecting again. Protected nodes
(referenced, locked, customized attributes, unexpected external connections or
inconsistent skin ownership) block the removal as a whole. Cleanup does not
unlock attributes or edit referenced layer data.

Unrelated artist networks, data belonging to other meshes and native paint
buffers are retained. Data without an unambiguous mesh ownership link is
listed as skipped when discoverable from the mesh's skin history. There is no
scene-wide name-pattern deletion or automatic deletion on window close.

All candidate nodes are checked before native deletion. A partial delete
failure rolls back only the cleanup's own uniquely named Undo group. A failure
before it creates an Undo entry does not undo an unrelated prior edit. If a
memory-cache clear fails after a successful deletion, the panel reports the
cache warning separately; the deletion remains available in Undo.

**Restore original** is a different action. It writes the captured Base weights
back to the native skinCluster and removes the authoring data. Choose it only
when you want the original captured weights, rather than the current skin.
It does not restore DQ weights or skinning method imported through Utilities;
those are skin-wide settings. Undo the import to restore those settings.
The existing low-level `rtkLayerSkin(action='bake', ...)` API remains available
for older scripts; the new Cleanup panel uses the lighter metadata-only path.

## Verification

The UI 8 cleanup baseline passed 449 local tests, including 18 cleanup
ownership/transaction checks and 12 real offscreen Qt cleanup checks. These
remain in the UI 12 suite; see VALIDATION.md for current totals. Tests use recording API objects;
they do not emulate Maya's native dependency graph or Undo implementation.
Maya is unavailable in this build environment. Check in Maya 2024 before
relying on native recovery behavior:

1. Paint weights and a mask, inspect Cleanup, then clear caches. Switch joints
   and return; verify the authored data still displays.
2. Remove saved layers; verify the skinCluster, influence list, weights and
   deformation are unchanged. Undo/Redo and check that layers/masks return.
3. Remove, then click +; verify the new Base is the current skin and the first
   assignment captures a fresh reference pose.
4. Save a copy after removal and reopen it. Verify the old layers do not return.
5. On disposable scene copies, test duplicate/corrupt payloads and protected
   nodes. Change the loaded mesh while Cleanup is open; stale removal must
   stop until the current mesh is inspected again.
