# Layer Skin UI 28 · Brush radius performance

Changing radius affects the brush outline and the size of the next footprint.
It does not change mesh topology, positions, skin weights, layer data or the
chosen joint's colors.

## Work removed from sizing

| Work | When needed |
| --- | --- |
| Native radius edit / outline update | When radius changes. A repeated unchanged field value is skipped. |
| Scalar UI synchronization | Coalesced at idle; reads radius, opacity, brush value and profile only. |
| Skin weights / layer metadata read | A real paint stroke or explicit data/view action, not sizing. |
| Layer-state encoding / stale-data hash | A real stroke, not sizing callbacks. |
| Full paint-array scan and upload | Actual paint/data changes, not sizing. |
| Weight-color reload / range calculation | A genuine view/data change, not every radius update. |
| Topology, mesh points and spatial brush grid | A real custom Relax gesture, not B-drag or radius-field edits. |
| Full editor/hierarchy refresh | Deferred if queued during sizing; resumed after sizing only when already pending. |

The previous initializer could call stroke setup when Artisan refreshed its
surface association while radius changed. Stroke setup takes a scene snapshot,
rebuilds displayed values, writes the array and hashes layer state. A subsequent
empty finalizer can also scan the entire paint array. At high vertex counts
that turns a scalar setting into repeated mesh-sized work.

## New interaction path

B press in a supported viewport establishes a settings guard before finishing
any real pending paint/Relax stroke. B-drag remains native; it does not run the
Relax solver, build geometry or create an overlay. The numeric field uses a
scoped scalar edit with the same callback guard. Only changed native setting
flags are sent; a radius edit does not resend opacity or operation flags.

While guarded, surface and array-attribute callbacks still return the existing
binding and saved values. Native before/after-stroke, sample and finalize
callbacks do not create a new stroke, read/rewrite the array or open layer Undo.
The guard survives both release orders and callbacks after the Qt event filter.
The existing idle sync clears it only after B and the tracked mouse button are
up. A genuine new paint press can clear it immediately so painting remains
responsive even before the idle sync runs. Focus loss and cleanup release it.

If a real stroke is pending before sizing, saving it once is required to keep
painted data. That save retains its existing readback, conflict checks and Undo;
it can still take time on a high-resolution mesh. There is no additional save
or whole-mesh pass for each subsequent radius update. A completed-stroke UI
refresh waits until sizing is finished. No scene changes or additional mesh
reads occur when there was no real pending work.

The cached full surface name has a direct binding lookup; aliases still use the
existing Maya path resolver. Normal painting continues to validate its snapshot
and save through the same native command. Brush radius boundaries, screen/world
clipping and Relax footprint math are unchanged.

## Reload

Replace the complete `layer_skin_prototype` folder and run in Maya Python:

```python
import runpy
runpy.run_path(
    r"D:/dev/MayaZone/layer_skin_prototype/layer_skin_ui_refresh.py",
    run_name="__main__"
)
```

Confirm **UI 31** and click Paint to resume. The registered plug-in is still
0.4.1; the safe refresh keeps its command class and old Undo objects. The new
brush-helper cache key avoids an already loaded older handler. UI 30 also
catches ShortcutOverride, defers scalar sync until both releases, and preserves
component painting; see [BRUSH_LIFECYCLE_UPDATES.md](BRUSH_LIFECYCLE_UPDATES.md).

## Native verification (pending)

1. Load a high-resolution mesh, choose a layer/joint and click Paint. Click
   Paint info once before sizing and note the array-read / accepted-sample
   counters and last-stroke receipt.
2. Hold B and drag repeatedly, then edit Brush radius directly. Weight colors,
   paint target, layer values and mesh deformation should stay stable. Unchanged
   field values should not send another edit. Maya may still spend time drawing
   its native outline; that is outside the Python callback optimization.
3. Release B before the mouse, then try the opposite order. Paint afterward with
   no extra click to re-enter the tool. Confirm the new radius and normal paint
   behavior, including small-radius boundary checks.
4. Compare Paint info after sizing. `array_read` / `accepted_sample` should not
   grow merely from radius changes, and the last stroke should stay unchanged.
   Surface-association and ignored-settings callback counts may increase; those
   callbacks are lightweight. `brush_settings_updates.edits` counts UI/API scalar
   edits; native B-drag is not routed through that edit counter.
5. Start with a real pending regular or Shift/Relax stroke and press B. That
   stroke should save once; its UI refresh should occur after sizing. Test
   Undo/Redo, read-only final weights, mask mode and normal/Shift painting again.

## Host verification

The UI 28 reference run passed 783 tests; those checks remain in the current suite. Eleven new Qt tests exercise actual key and
mouse routing with a recording viewport/API. Heavy mesh/array methods are set to
fail during sizing. Tests retain values, native buffer object, state and Undo,
then verify that normal painting still commits saved values. Both pending native
array paint and pending custom Relax are saved once before sizing.

`benchmark_brush_radius.run()` replays native settings callbacks with 100,000 and
250,000 vertices, eight influences. At 250,000 vertices the former unguarded
Python path took about 245 ms/update, versus 0.171 ms/update for the new guarded
path. The new path performs zero skin-context reads, metadata reads, array
reads/writes or state encodes during 200 updates. See
`BRUSH_RADIUS_BENCHMARK.json` for both cases. This is CPU callback replay with a
recording API, not an actual Maya/viewport benchmark. Native Maya testing is
still pending on the build host.

UI 30 note: BRUSH_RADIUS_BENCHMARK.json records the historical UI 28 replay.
The current replay script also uses cached stroke startup, so its unguarded
path is no longer that historical baseline. PAINT_LIFECYCLE_BENCHMARK.json
measures the current surface/header cache separately. Native Maya timings
remain unmeasured.
