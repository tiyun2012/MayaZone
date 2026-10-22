# Layer Skin UI 27 · Hierarchy assignment

Assignment uses the actual cached skinCluster input mesh and matching bind-space
joint frames. Bone endpoints follow the nearest joint children through transform
buffers. Full DAG paths identify scene joints and UUIDs identify saved frames;
duplicate short names and extra groups do not change ownership.

## Apply the update

Replace the complete `layer_skin_prototype` folder, then run in Maya's Python
Script Editor:

```python
import runpy
runpy.run_path(
    r"D:/dev/MayaZone/layer_skin_prototype/layer_skin_ui_refresh.py",
    run_name="__main__"
)
```

Confirm **UI 27**. The registered plug-in version remains **0.4.1**. Existing
weights are retained until an explicit Assign or Rebuild.

Select an editable layer, select the desired joints in **Joint hierarchy**, choose
Method and Scope, then click **Assign selected joints**. To assign a whole branch,
select its root and click **Select joint + descendants** first. This includes the
root and collapsed/search-hidden children across transform buffers. Multiple
selected roots are combined once. Shift-click a row or arrow to open all levels.

Selecting only one root assigns to that root's influence; descendants do not
become candidate influences until selected too. Bone endpoints still include all
nearest joint children, even when those children are not selected.

## Methods

| Method | Assignment rule |
| --- | --- |
| Distance to joint | The closest selected joint pivot in the frozen reference. |
| Distance to bone | The closest finite segment from a selected joint to any nearest joint child. A leaf or zero-length bone uses its pivot. The selected joint owns its outgoing segments. |
| Joint axis | Closest bone first. Among equally close bones, prefer a positive chosen local-axis coordinate, then greater logical joint depth, then a stable UUID. |

All three methods assign **one selected influence at weight 1 and coverage 1**
to every scoped vertex. There is no assignment Radius, Length or Falloff. Brush
Radius and brush Falloff still control painting. Use layer masks, alpha and
Relax to shape the generated assignment afterward.

For a point `p`, joint pivot `s` and segment end `e`, bone distance is:

```text
u = e - s
q = clamp(dot(p - s, u) / dot(u, u), 0, 1)
distanceSquared = dot(p - (s + q*u), p - (s + q*u))
```

A zero-length segment uses point distance. Every outgoing child segment is
considered; the nearest one determines that joint's distance. Point assignment
uses the same spatial search with point-sized bounds.

## Combining bone distance and axis

Distance stays primary, preventing a far-away positive-side branch from taking a
vertex from a closer bone. Axis direction resolves shared endpoints, coincident
bones and other distance ties. The chosen axis may be ±X, ±Y or ±Z. A reciprocal
basis retains the correct local sign through rotation, shear and mirrored or
nonuniform scale. A zero local coordinate is not positive.

If all candidate local coordinates are negative or zero, the nearest bone still
owns the vertex. There is no positive-only rejection, no global first-joint claim,
and no difference between a chain and multiple branches. At a straight chain's
joint boundary, a positive parent is preferred over the child's zero coordinate;
beyond that boundary the closer outgoing bone wins. Singular frames are rejected
before skin writes instead of producing an unreliable axis sign.

Numerically equal squared distances use relative tolerance `1e-12 * max(1, d²)`
in the internal centimeter reference. Without an axis preference, distance ties
prefer deeper logical joints and then UUID. Pick order and transform-buffer
depth do not decide ties. Custom references without parent links use stable UUIDs.

The Assign status counts generated rows as **N of M scoped vertices assigned**.
That count describes generated coverage. Masks, alpha, retained manual paint and
layer locks can still change the final skin weights. Assign replaces manual
paint/Flood/Relax overrides inside Scope by default; enable **Preserve painted /
flooded edits** to retain them. Rebuild always retains manual overrides and uses
all existing layer joints. Both keep masks and vertices outside Scope.

## Reference and caches

All methods use the same frozen **skin input / bind-world** snapshot. Bound
joints use inverse bind-pre matrices; unbound joints use captured offsets under
a bound ancestor, or relative to the mesh when no bound ancestor exists. Older
posed snapshots migrate only on explicit Assign. Recapture explicitly refreshes
input points and joint frames without changing weights until regeneration.
See [PREDEFORM_REFERENCE.md](PREDEFORM_REFERENCE.md).

A balanced bounding-volume tree indexes joint pivots or individual finite bone
segments. Squared distances avoid square roots in the per-vertex search. Bounds
prune candidates beyond the current nearest distance. Forks have separate bounds
for each outgoing bone. Overlapping bones can still require many candidate
checks; worst-case queries can scan every segment.

The transient LRU cache is bounded to 64 MiB / eight entries. Reference content,
selected UUIDs, influence columns and method/axis identify the joint index;
changing vertex scope can reuse it. Scope also identifies generated results.
An identical assignment reuses its result with no new distance tests; validating
the reference hash still reads reference content. Pick order is canonicalized.
Large assignments use existing immutable sparse rows, including layer edit and
scene save/load, instead of allocating one dense row per vertex.

Cancellation and the 120-second budget are checked during index construction and
vertex traversal, before skin writes. Incomplete results and newly built indices
are not published to caches. No per-frame solver, global progress window or Maya
queries are added inside the geometry loop. Clear assignment cache removes only
transient data, retaining saved layers, reference, paint and masks.

Old `radius`, `length`, `falloff` and `axis_overlap` settings are ignored on
regeneration. Assignment metadata records `algorithm: 2` and the current rule.
Old generated rows remain unchanged until Assign/Rebuild. Safe refresh installs
the new helpers/cache and sanitizes old settings ahead of an already registered
planner, while retaining the 0.4.1 command class, native Undo objects and saved
layer schema. The existing sparse row format is reused.

## Verification

**772 automated checks pass**, including random nearest-joint/bone results
compared against brute force, forks, zero-length bones, all-negative axis cases,
remote positive branches, signed/rotated/sheared axes, buffered duplicate names,
scopes, cancellation, spatial pruning, compact rows through save/load, old
registered planners, binding rollback, masks, locks and native-command Undo/Redo
through a recording API. Native Maya execution is still pending.

The CPU-only `benchmark_nearest_assignment.run()` verifies every generated row
for 100,000 vertices and 339 influences. On this host, each method took about
1.3 seconds, with 0.015–0.019-second cached repeats. There were 257,118 joint or
284,099 bone candidate tests versus 33,900,000 full pairs. These fixture-specific
times exclude Maya IO, binding, metadata encoding and viewport work. Full values
are in `NEAREST_ASSIGNMENT_BENCHMARK.json`.

After opening/refreshing UI 27 in Maya, run:

```python
import maya_layer_skin_hierarchy_smoke
maya_layer_skin_hierarchy_smoke.run()
# run(keep=True) leaves the fixture for inspection.
```

The fixture checks all three methods, buffered branches with repeated leaf names,
negative-side generated coverage, frozen endpoints, joint poses and native
Undo/Redo. The separate `maya_layer_skin_predeform_smoke.run()` checks reference
consistency across pose/mesh transform changes. These scripts do not open a new
scene or clear Undo; their actual Maya execution remains pending.
