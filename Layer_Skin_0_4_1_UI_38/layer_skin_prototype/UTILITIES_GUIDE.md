# Utilities: skin export and import

Layer Skin 0.4.1, Authoring UI 20 provides the **Utilities** tab beside **Layers**.
It transfers the final native skin result through a `.rtkskin` file. It adds
no runtime deformer, expression, per-frame solver or extra skinCluster layer.

## Production-size meshes in UI 20

The former **2 million vertex × influence values** restriction is removed from
all normal export/import stages. The default budget is 1,024 MiB per packed
float64 buffer, or 134,217,728 values. A 100,000-vertex mesh with 339 influences
uses 33.9 million values and about 258.6 MiB for one packed native/base buffer.
Total RAM can be higher because the base, current skin, composed result and
Undo snapshots coexist. The archive's uncompressed contents have a separate
1,024 MiB guard; a corrupt manifest cannot request an unbounded allocation.

- Large file weights remain compressed-sparse rows in memory. Vertex ID
  planning shares this read-only data rather than expanding a dense matrix.
- Large closest-surface transfers accumulate nonzero source contributions and
  retain sparse output. The same interpolation and mapping rules apply.
- Large layer bases use packed doubles. Imported rows retain nonzero values.
  Saved Maya layer metadata can contain checksummed compressed float64 blocks
  and sparse-row records. Small legacy scenes retain their list representation;
  previous scene metadata is still readable. Use UI 20 to reopen large scenes
  saved with these compact records.
- Native weights are read and written in batches of at most 262,144 values.
  Native reads during file operations check cancellation between batches.
  Writes/readback keep the same guarded Undo transaction; a failed later batch
  restores the earlier batches as well.
- Archive binary arrays are streamed in 1 MiB blocks with the existing v1
  layout and SHA-256 checksums. No weight rounding or pruning is introduced.
- Picking a mesh does not load its complete weights. Export with **Include
  transfer geometry** disabled also skips point/triangle extraction.

Export/import use the existing workflow below; no new memory settings are
required. Load the complete UI 20 package or run the UI refresh with the old
window open. Replacing files alone does not update already loaded Python
helpers. The refresh retains the native 0.4.1 command and existing Undo objects;
a fresh session additionally uses the newest full-mesh command allocation path.
Do not force-unload the plugin or reset Undo for this update.

### Reproducible checks

`python skin_io_benchmark.py --production` runs a CPU-only 100,000 × 339
export/read/import/save/reload/compose/verify fixture. Results are in
`PRODUCTION_IO_BENCHMARK.json`; the test uses four nonzero weights per vertex.
These measurements exclude Maya API/skinCluster, native Undo and viewport work.

In Maya, open UI 20 and run:

```python
import maya_skin_io_smoke
maya_skin_io_smoke.run_large()
```

The default fixture creates 25,921 vertices and 128 influences (3,317,888
values) in a unique test namespace, exports/imports and checks native Undo/Redo.
It removes only its own fixture by default. It does not open a new scene or
clear Undo. This native test was supplied but has not been run here.

## Export

1. Choose **Utilities**. Valid pending paint is saved before leaving Layers.
2. Under Export skinning, use **Use selected mesh** or **Use layer mesh**.
3. Keep **Pre-deformed / base** for the geometry immediately entering the
   skinCluster. Choose **Current deformed** to save the current output shape.
   Weights always come from the current native skinCluster in either mode.
4. Keep **Include transfer geometry** for closest-surface imports. Turn it off
   for a smaller file usable only with matching vertex IDs/topology.
5. Browse for a `.rtkskin` path and click **Export skin file**. Replacing an
   existing file requires the overwrite dialog. A failed/cancelled export keeps
   the previous file intact and removes its incomplete temporary file.

Export saves final normalized weights, influence UUIDs/full paths, bind positions
and reference bind matrices, topology fingerprint, native DQ blend weights and
skinning method. Optional geometry contains mesh-object points and triangulation.
It exports one mesh per file, with no selected-vertex restriction.

This is a final-skin backup/transfer file. Layer names, order, masks, Base,
assignment references and painted/generated distinctions remain in the Maya
scene; the file does not serialize the editable layer stack. Save the Maya
scene to retain that stack.

## Import

1. Browse to a `.rtkskin` file and click **Load file**. The validated contents
   are cached until Unload, close or changing the path. A changed file must be
   loaded again before Preview/Import.
2. Get the **Target mesh** using selection or the loaded layer mesh. It can
   already have a skinCluster, or be unskinned.
3. Choose the transfer method and a name for the new layer.
4. Optionally scope joint candidates to a hierarchy. Click **Preview import**.
5. Review the Source influence / Target influence / Match table. For an
   unresolved or unwanted match, select its row, select the intended joint in
   Maya, then click **Map row to selected joint**. Clear row override returns
   that row to automatic matching; Reset mapping clears all manual choices.
6. Once every weighted source influence has a unique target, click **Import
   as new layer**. Return to Layers to edit, mask, disable or change its alpha.

Preview computes mapping and interpolation without creating a skinCluster,
adding influences, altering weights or saving layer data. Beginning a Utilities
operation still saves/stops any valid pending brush stroke through its normal
paint transaction. Changes to options, source file, target topology/points,
weights, membership, saved layers, DQ/method or mapped bind data invalidate the
plan. Preview again after changing these inputs.

### Transfer methods and geometry space

| Method | Requirement | Result |
| --- | --- | --- |
| Vertex ID | Same vertex count and topology fingerprint | Exact saved rows, remapped into target influence order. |
| Closest surface | Saved transfer geometry; arbitrary target topology | Closest source triangle per target vertex, barycentric interpolation of weights and optional DQ. |

Closest surface compares **mesh-object positions in centimeters**. Model shapes
must align in their respective object spaces; mesh world transforms are recorded
for reference and are not applied to align the models. This intentionally allows
duplicate mesh transforms placed elsewhere in the scene. Different object-space
pivots/shape offsets must be aligned before transfer.

The saved source geometry mode is shown after loading. Target geometry can use
its skinCluster's immediate input or current output. An unskinned target uses
its visible mesh. Current geometry makes sense when source and target are in
corresponding poses. Maximum surface distance 0 means unlimited; a vertex with
no triangle inside a positive limit stops the entire import before skin edits.
The distance limit and joint tolerance fields use the current Maya linear unit.

### Joint mapping

Only source influences with nonzero weights require a mapping. Mapping is
one-to-one; ambiguous candidates remain unresolved rather than being merged.

- Manual selections take precedence, then identical scene UUIDs and unique
  exact names. Ignore namespaces is on by default.
- Search/replace changes source names for matching, for example `_L` → `_R`.
  Max name edits defaults to 3 for small spelling/prefix differences.
- Names and Bind distance can work together. The default proximity tolerance
  is 0.01 Maya units. Bound candidates use their bind positions; unbound joints
  use current world positions. Bind-position comparison assumes corresponding
  skeletons share a world-space bind frame.
- A hierarchy root narrows scene-joint candidates and helps avoid matching the
  original source rig. Manual mapping can explicitly choose an influence outside
  that scope. Bound transform influences can also be mapped manually.
- Existing target influence order may differ, and extra target influences are
  retained. Missing mapped influences can be added at zero if enabled. The tool
  does not create missing joints, rename joints or unlock influence attributes.

### Existing skins, layers and Undo

Import creates an enabled top layer with alpha 1, full authored coverage and a
white mask. Its initial final result is the imported skin. Existing layers,
masks and Base are preserved; new influence columns are remapped by UUID. Lower
layers become visible when the imported layer is disabled, masked or faded.

For an existing skin, its bind matrices stay intact. For an unskinned target,
**Create skinCluster if missing** binds the mapped existing joints at their
current pose before importing. Source bind matrices are reference data, not
written onto the target; this is weight transfer, not skeleton/bind-pose repair.
With a new stack, Base captures the target's pre-import bound weights.

**Import DQ weights** and **Restore method** are native skinCluster-wide options.
They do not belong to the new layer, and layer opacity/mask/enable does not blend
or restore them. Turn these options off to preserve the target's current values.
Cleanup and Restore original operate on authoring data/regular skin weights;
they do not revert imported DQ or method. Undo the import to restore those too.

Binding or adding influences, layer creation, regular weights, and requested
DQ/method changes are grouped into one Maya Undo transaction. A failed write or
readback rolls that transaction back. Undo must be enabled. The native command
class/API stays 0.4.1; updating the UI does not unload it or erase Undo history.

## File format, limits and caches

Format `rtkSkin`, version 1, is a ZIP containing a JSON manifest and checksummed
little-endian binary arrays. Weights use sparse CSR rows with float64 values:
no precision rounding, threshold pruning or quantization. Vertex-ID archive
round trips are lossless; spatial interpolation is an intentional new result.
Import verifies saved layer rows and Maya's native result within numerical
tolerance. Regular weights must be finite, nonnegative and normalized.

Current guards include: 1,024 MiB per packed dense buffer,
32 editable layers, one non-instanced polygon mesh and one skinCluster. Mapping
accepts at most 4,096 candidates; scope a large scene to a joint root. Archives
are bounded to 1,024 MiB uncompressed, 1 MiB manifest and 4 million triangles.
Locked/referenced/driven data and inconsistent external native edits are
rejected; no locks or normalization settings are silently changed. Disable
Maintain Max Influences manually if it prevents the requested write.

Preview reuses the loaded source data, builds one triangle BVH per spatial
Preview and caches that plan until inputs change. Utilities uses no Maya
progressWindow. Bounded computation checks support Escape during planning and
between read/archive batches, with a 600-second file-computation deadline;
cursor and enabled state are restored in finally blocks on errors. Native API
calls and file compression cannot be interrupted mid-call. There is no promise
of background execution or constant-time performance.

**Unload** releases the external file/cache. Closing releases it too. Cleanup's
Clear memory caches invalidates the import plan but keeps the loaded file.
New/open scene clears mesh fields and manual mapping while retaining the file
for another target. Warm UI refresh keeps fields/file/manual mapping and drops
the old Preview, which must be recomputed before Import.

`IO_BENCHMARK.txt` records CPU-only file and spatial-transfer measurements.
Repeat with `python skin_io_benchmark.py`; it excludes native Maya skin I/O,
binding, layer encoding, Undo, viewport and scene-save costs.

## Native Maya verification

Local recording-API and real Qt checks are included in LOCAL_TEST_RESULTS.txt.
They do not emulate Maya's dependency graph or establish native Undo behavior.
Maya is unavailable in the build environment; run the supplied native smoke
test in a disposable Maya scene after refreshing to UI 12:

```python
import runpy
check = runpy.run_path(
    r"D:/dev/MayaZone/layer_skin_prototype41/maya_skin_io_smoke.py"
)
report = check["run"](keep=True)
```

Use your extracted folder's actual path. Keep one Layer Skin UI 12 window open.
The test creates its own namespace, checks file round trips, native vertex-ID
weights/DQ/method Undo/Redo, and a new skin with different-topology surface
transfer. It keeps its demo objects for inspection; `keep=False` removes only
its own namespace. It does not clear the scene, force-unload a plug-in or reset
Undo. Also test importing above painted/masked layers, manual renamed-joint
mapping, disabled DQ/method options, stale Preview rejection, save/reopen, and
real high-resolution production meshes before relying on the workflow.
