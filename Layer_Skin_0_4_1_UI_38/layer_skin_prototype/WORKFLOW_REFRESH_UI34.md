# UI 34: layer switching and Relax preparation

## Changes

Revisiting Base or an unchanged layer reuses its weighted-joint summary instead
of scanning that layer again to determine which hierarchy rows should be gray.
The first visit still builds the summary. This reduces repeated summary work
when moving between layers, painting a mask or adjusting layer opacity.

The cache belongs to the window and holds at most one summary for each live
layer plus Base. Source buffers are immutable core snapshots. Each lookup drops
entries whose sample/generated/base buffers were replaced, including inactive
layers. Mesh UUID, topology, vertex count, influence order and core changes
invalidate the scope. Deleted layers and superseded sample snapshots are not
retained. A manual zero-coverage override still hides its generated sample.

Painting or reassigning a layer updates its weighted rows on the next refresh.
Mask, name, alpha, enable and membership edits reuse the summary; membership and
locks continue to update separately in the joint hierarchy. Clear memory
caches, scene reset, close and warm UI replacement release these summaries.

Relax's topology cache now updates its memory estimate when a new neighbor row
is read. Previously, a 64-vertex lookup could recount all 100,000 already cached
rows. Cached lookups now visit the requested vertices. Topology invalidation,
LRU order and the existing byte/item limits remain. Successfully read neighbor
rows can be reused after a canceled or failed lookup; the exception still
propagates, and this read-only cache never changes skin or layer data. Clearing
the cache during cancellation prevents the old request from refilling it.

The skin command, solver, Relax math, brush radius/footprint, persistence,
write verification, native Undo/Redo and VP2 renderer have no behavioral changes
in this update. Native skin reads and external-edit validation still run.

## Measurements

Python 3.12.14, Linux, nine repetitions, median CPU phase time. Fixtures warm
the caches before measuring repeated access and verify identical results.

| Phase | Fixture | UI 33 | UI 34 |
| --- | --- | ---: | ---: |
| Revisit three weight summaries | 200,000 vertices, 16 influences; Base and two layers | 383.994 ms | 0.011 ms |
| Cached topology lookup for selected Relax | 64 requested vertices after caching 100,000 rows | 6.072 ms | 0.007 ms |

Warm summary revisits perform zero weight-summary scans rather than three.
Both topology versions perform zero native neighbor reads after warmup; the
improvement removes the full cache recount. The topology cache's estimated
retained size remains 26,000,000 bytes in this fixture.

These measurements exclude Maya skin reads/writes, command validation,
dependency-graph work, Artisan, rendering and the other parts of layer switching
or Relax. A first visit or a replaced source still requires a summary scan.
The recorded values and host details are in `WORKFLOW_REFRESH_BENCHMARK.json`.
`benchmark_workflow_refresh.py` reproduces the comparison without Maya, using
the UI 33 accounting policy and the current policy on identical data. PySide is
needed to import the UI helper; no widget or Maya scene is created.

## Load in Maya

Replace the complete `layer_skin_prototype` folder, then run:

```python
import runpy
runpy.run_path(
    r"D:/dev/MayaZone/layer_skin_prototype/layer_skin_ui_refresh.py",
    run_name="__main__"
)
```

Confirm **UI 34** in the title. Adjust the path if your folder is elsewhere.
The registered plug-in remains **0.4.1**. The included refresh preserves the
registered command, existing native Undo objects and the paint buffer.

Native Maya testing is pending on this host. In a working scene copy:

1. Visit several layers and Base twice. Check the gray/weighted joint rows and
   that the chosen paint joint and component selection stay as expected.
2. Paint a weight, erase it, assign a layer, edit a mask and use Undo/Redo. Check
   both the saved result and the hierarchy's weighted-joint rows after revisits.
3. Run whole-mesh Relax, then Relax on a small component selection. Verify the
   existing selection/brush limits and that Undo restores the prior result.
4. Clear memory caches, warm-refresh the UI and repeat the layer round trip.

Automated coverage and runtime limits are recorded in `VALIDATION.md`.
