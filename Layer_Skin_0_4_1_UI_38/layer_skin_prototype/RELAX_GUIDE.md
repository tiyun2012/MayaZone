# Relax: equations, controls and workflow

Applies to Layer Skin 0.4.1, Authoring UI 19. Relax is an authoring operation;
the result is saved in the layer and composed into the native skinCluster.
There is no runtime smoothing solver on every animation frame.

UI 15's Falloff menu controls Replace/Add/Scale only. Relax and Shift keep the
smooth curve below; the menu is disabled while regular Relax is selected.

UI 18 keeps locked influence contributions fixed on every Relax pass. Selected
joint groups exclude their locked members; locked zero values cannot receive
neighbor weights. Masks remain independent. Relax retains its topology average
instead of equalizing contributions with the scalar-operation redistribution
menu. See INFLUENCE_GUIDE.md for the distinction between layer and final weights.

Utilities imports create normal full-coverage layers that can be relaxed with
these controls. Optional imported DQ/method settings belong to the whole native
skinCluster and are not smoothed by Relax or blended by the layer alpha.

## Shift + paint

UI 12 retains Maya's native Artisan brush outline. The old painted Qt overlay was
removed after the black viewport/gold-ring trail report. Hover-only feedback
keeps the native outline positioned while the custom Shift solver owns the
stroke. No painted Qt child, custom OpenGL draw call or renderer change is
used. See VIEWPORT_FIX.md for the update and native verification steps.

UI 11 redraws the active view during a held drag, rather than waiting for Maya
idle. Immediate requests are throttled to 30/second; release/cancel forces the
final frame. This is a redraw limit, not a guaranteed frame rate on large meshes.

UI 12 holds panel repaints during color-changing UI actions, so a pending Relax
stroke can finish and the next joint/mask view can load before the next frame.
During an ordinary held brush gesture the existing UI 11 preview/redraw path
continues. The solver and coverage default have not changed in this update.

1. Select an editable layer and a joint, choose Weights or Mask, then click Paint.
2. Hold Shift and drag the left mouse button over the mesh to relax under the
   brush. Release the mouse to save the stroke as one Undo step.
3. Without Shift, the next stroke uses the group's Use brush selection: Replace,
   Add, Scale or regular Relax. B + drag uses
   Maya's native radius adjustment; the UI radius follows the native setting.
4. Escape cancels the current Relax gesture and restores its starting colors.
   Releasing Shift before the mouse saves once; release the mouse before
   starting a normal stroke. Changing tools also completes a pending stroke.

The brush previews the selected layer's values while moving and writes native
skin weights on release. In Mask mode it previews and smooths the mask in
grayscale. A final-skin read-only view must be turned off before editing.
Strength, Max new influences, Keep coverage and hierarchy joint selection are
shared with Relax Execute. Brush passes applies per brush stamp; Iterations
applies only to Execute. Flood selection controls do not restrict the brush
footprint. The four operation groups are described in OPERATIONS_GUIDE.md.

## What is averaged

For vertex v and influence j, the layer stores a normalized distribution
`w[v,j]` and an authored coverage `c[v]` between 0 and 1. Relax operates on
their contribution:

    q[v,j] = c[v] * w[v,j]
    mu[v,j] = sum(q[u,j] for u in edge_neighbors(v)) / neighbor_count(v)
    q_next[v,j] = (1 - s[v]) * q[v,j] + s[v] * mu[v,j]

Each pass reads one previous-iteration snapshot and then applies all updates
together (Jacobi). Neighbor order therefore does not bias the result. Every
mesh-edge neighbor has equal weight; world-space edge length is not used.
An isolated vertex remains unchanged. Values outside the operation's scope
stay fixed but immediate outside neighbors can contribute to the average.

For Flood relax, `s[v] = Strength`. With the Shift brush:

    rw = world_distance(vertex, brush_hit) / native_world_radius
    rs = projected_distance(vertex, brush_hit) / projected_brush_radius
    falloff(r) = (1 - r*r)^2       when 0 <= r < 1, otherwise 0
    s[v] = Strength * BrushOpacity * min(falloff(rw), falloff(rs))

The center receives full configured strength; the boundary receives zero.
The Value field is not used by Relax. Brush pressure, Gaussian profiles and
Maya's regular paint-operation setting do not alter this custom Relax falloff.

Example: Strength 0.5, Opacity 0.8, vertex at half-radius gives
`s = 0.5 * 0.8 * (1 - 0.5^2)^2 = 0.225`. For a contribution of 0.2 and a
neighbor average of 0.8, one unrestricted pass gives
`0.2 + 0.225 * (0.8 - 0.2) = 0.335`, before any coverage preservation or
influence-limit normalization described below.

### Brush boundary in UI 19

UI 19 corrects two gaps in UI 16's footprint adapter. It now queries native
`screenRadius` as well as `worldRadius`, and uses the smaller of the native
screen radius and the projected world radius as the screen-space limit. A
native screen circle smaller than the reconstructed world circle therefore
clips that larger footprint. Its center is the stamp's cursor position, not
the rounded projection of the ray hit. Screen-radius queries are interpreted
in viewport port pixels; native renderer/DPI behavior still needs Maya checks.

An interpolated stamp first moves the native outline to **that sample**, then
queries its radii. It no longer reuses the drag endpoint's radius at every
intermediate point. Hover-only motion still updates the outline without
creating a solver stamp. Fractional Qt input coordinates are preserved before
conversion into port coordinates. The original mouse event count does not
change the spacing along the sampled stroke.

If the native screen-radius query is missing, invalid or nonpositive, the
projected world-radius limit remains as a compatibility fallback. Paint info
identifies this explicitly; exact correspondence to the native outline is not
claimed for that fallback.

Only vertices strictly inside both boundaries can be written. The connected
patch is formed after clipping, so an outside vertex cannot bridge to another
patch. Vertices outside the stamp remain fixed across every solver pass; their
values can still contribute to an inside vertex's one-ring average. A new stamp
does not re-relax vertices just because an earlier stamp touched them. Releasing
the mouse commits the union of the changed patches as one Undo step.

Maya's outline receives a buttonless hover before the effective `worldRadius`
and `screenRadius` are queried for each actual stamp. Invalid/unavailable `worldRadius` falls back
to the native `radius` value. No extra scene-unit conversion is applied.
Mesh world points and the position hash are captured once per gesture; radius
changes alter the hash query instead of rebuilding it. Candidate projections
are cached for that gesture. Clipping and the projected radius both use
M3dView's physical port coordinates; Qt logical coordinates are used only for
mouse input and stroke spacing. This avoids mixing high-DPI coordinate systems.

Paint info reports `relax_brush.footprint` and the same footprint description
in `last_stroke`: `radius_source`, `world_radius`,
`projected_radius_pixels`, `native_screen_radius_pixels`,
`effective_screen_radius_pixels`, `screen_radius_source`, `boundary_revision: 19`,
`projected_vertices` and `neighbor_halo: read only`.
The projected radius is in physical port pixels; the UI field is not a pixel
value. Native `radius`, `worldRadius` and `screenRadius` are also queried for
diagnosis. These diagnostics measure the implementation; they do not verify
the native outline's appearance on every renderer.

The native contracts are documented in Autodesk's
[artUserPaintCtx reference](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/Commands/artUserPaintCtx.html)
and [M3dView API reference](https://help.autodesk.com/cloudhelp/2024/ENU/MAYA-API-REF/py_ref/class_open_maya_u_i_1_1_m3d_view.html).
The native screen-radius clip, its port-pixel interpretation and the
projected-world fallback still need visual verification in Maya.

Because weights and colors are per vertex, a polygon spanning the boundary can
show an interpolated gradient outside the circle even when its outside vertex
values are unchanged. Check those values as well as the visible gradient.

If the neighbor average stays fixed and no budget/limit adjustment changes the
solve, K passes give:

    q_K = mu + (1 - s)^K * (q_0 - mu)

This is not a closed-form solution for an entire changing mesh: neighbors
usually change too. Repeated stamps also accumulate smoothing. More passes,
higher Strength, higher Opacity and slower overlapping strokes all increase
the effect. Strength 0 is a no-op. Strength 1 directly replaces with the neighbor
average and can oscillate on a two-vertex graph; 0.5 is the default.

## Joint selection and conserved budgets

| Hierarchy selection | Weight solve |
| --- | --- |
| No joints or one joint | All neighboring influences can participate. One joint selects the color view; it does not isolate that influence in the solve. |
| Two or more joints | Redistribute only among those joints. Their combined contribution at each vertex stays fixed; other joints stay unchanged. |

For a selected group G, the starting combined contribution is:

    B[v] = sum(q_start[v,j] for j in G)
    M[v] = sum(mu[v,j] for j in G)
    desired[v,j] = B[v] * mu[v,j] / M[v]
    q_next[v,j] = (1 - s[v]) * q[v,j] + s[v] * desired[v,j]

This division is used only when both B and M are positive. A zero group budget
stays zero; if neighbors contain none of the selected group, the vertex stays
unchanged. For selected contributions 0.2 and 0.3, the budget is 0.5. A neighbor
ratio of 80/20 gives a desired 0.4/0.1, approached according to Strength.

## Coverage, influence limits and masks

**Keep coverage** (previously Preserve coverage) is off by default. In unrestricted
mode, the brush smooths contribution and its total coverage, so a painted edge
can feather into empty neighboring vertices inside the footprint. For example,
on a three-vertex line with one painted joint `[1, 0, 0]`, a strength-0.5 pass
over the first two vertices with full falloff gives `[0.5, 0.25, 0]`.

Enable preservation to rescale each candidate distribution back to its starting
authored coverage. An empty vertex then stays empty. A patch containing just
one joint can show no change because all variation lives in its fixed coverage.
This remains an intentional option. A two-or-more-joint solve always preserves
its group budget, independent of this checkbox. The checkbox now applies to
Relax Execute as well as both Relax brush gestures. Uniform fields have no gradient to smooth and
remain unchanged in either mode.

**Max new influences** is 0 for Unlimited. Otherwise, candidate additions are
ranked by contribution, with stable influence UUID ordering for ties; only the
strongest permitted additions survive. This cap is measured against each
vertex's support at the start of the entire Flood action or Shift gesture,
not against each pass or stamp. Existing influences are not deliberately
pruned, though zero-valued results can disappear. Remaining candidates are
rescaled to the appropriate contribution budget. This is a limit on newly
participating vertex influences, not a total influence count or a method of
adding new joints to the native skinCluster.

Stored weights are normalized after relaxation:

    coverage_next = sum(q_next)
    weight_next[j] = q_next[j] / coverage_next     if coverage_next > 0

A zero-coverage sample retains a valid normalized row but contributes nothing.
Manual samples take precedence over generated assignment samples, including
explicit zero-coverage edits. Relax writes manual samples, so Rebuild layer
preserves them. Clear paint edits reveals generated assignment underneath.

The layer's mask and opacity control composition after the weight solve:

    alpha[v] = layer_opacity * mask[v] * coverage[v]
    output[v,j] = (1 - alpha[v]) * lower_stack[v,j] + alpha[v] * weight[v,j]

Weight Relax does not use the layer mask as a protection mask: it can change
stored weights at a vertex currently hidden by a zero mask. It does not change
the mask or layer opacity. In Mask mode, Shift relaxes the scalar mask itself:

    mask_next[v] = mask[v] + s[v] * (average_neighbor_mask[v] - mask[v])

An unspecified mask value is 1. Joint selection, Max new influences and
Keep coverage have no effect on mask smoothing. In UI 13, Relax Execute also
smooths the mask when Mask mode is chosen. Replace Execute in Mask mode sets a
constant value instead of smoothing it.

## Flood, Assign and Rebuild

Flood influence and painting create manual layer overrides. Previously Assign
preserved them, so it could successfully generate new weights underneath a
Flood while the old Flood stayed visible. UI 7 makes this explicit:

| Action | Manual paint/Flood/Relax edits | Layer mask |
| --- | --- | --- |
| Assign selected joints, default | Replaced only inside the assignment scope. Outside that scope is kept. | Kept |
| Assign with Preserve painted / flooded edits checked | Kept; overrides can hide generated assignment. | Kept |
| Rebuild layer | Kept; regenerates using all joints used by the layer. | Kept |
| Clear paint edits | Removed inside the Flood selection scope; generated weights show through. | Kept |

Assignment scope is its own Whole mesh / Selected vertices control. Outside
distance support, clearing manual edits reveals lower layers, because there is
no generated sample there. Distance falloff can deliberately produce partial
coverage. Disabled layers, zero opacity and a zero mask can hide valid edits;
select the layer's own weight view to inspect its stored contribution.

The low-level `assign` command keeps the old preserve behavior unless
`replace_manual=True` is explicitly supplied. This avoids silently changing
existing scripts. The updated UI supplies that option by default.

## Performance and safe lifecycle

At Shift-press, the tool captures world positions once and prepares a spatial
hash and Maya's ray-intersection acceleration. A stamp considers only vertices
inside the world-space sphere connected to the hit face within that sphere.
Disconnected nearby mesh islands are excluded. This is a connected sphere
footprint, not a geodesic-distance brush; a connected fold inside the sphere
may participate. Positions stay fixed during the gesture; start a new stroke
after changing the pose or mesh shape.

One-ring topology is cached lazily during the gesture. The numerical solver
reads only each stamp's scope and immediate halo. Stamps are spaced at 20% of
the initially projected brush radius, with at most eight per mouse event to
bound work during very fast moves. Excess stamps are skipped for those moves,
so very fast strokes can be less dense. Holding still does not airbrush.
A footprint above 50,000 candidate vertices is rejected; reduce Radius or use
Flood relax for large areas.

Transient preview-array uploads still cover the loaded mesh, and final
metadata validation/serialization and native readback are not brush-local.
The prototype's two-million vertex-by-influence limit remains. CPU benchmarks
exclude Maya/GPU/skin-write costs and do not establish native brush frame rate.

On release, one guarded authoring command verifies that metadata and native
weights have not changed underneath the stroke, commits the final values, and
supports Undo/Redo. Escape discards staged values without a skin write. Normal
Artisan painting, native B-radius adjustment and Select/component workflows
retain their existing ownership. Closing, changing tools and refreshing the
UI release the gesture controller; late Maya exit avoids native UI/graph edits.

## Native Maya check

The package's local tests cover the math, real Qt event routing with a viewport
adapter, command rollback and UI refresh. A real Maya viewport is not available
in the build environment. After applying UI 18, check in Maya 2024:

1. Paint different weights, Shift-drag to smooth a boundary, release, switch
   joints and return. Verify saved colors, native deformation and one Undo/Redo.
2. B-drag the radius, then Shift-paint. Check the field and footprint agree.
   Test Escape and releasing Shift before releasing the mouse.
3. Paint a nonuniform mask, Shift-smooth it, switch modes and return. Check
   one Undo/Redo and that joint weights remain authored as before.
4. Flood one joint, select another in the hierarchy, and Assign selected
   joints. Check replacement; Undo; enable Preserve painted / flooded edits
   and assign again. This time the Flood should remain visible.
5. Test selected-vertex assignment, incoming Select/native Paint Skin tools,
   close/reopen, save/export, high-DPI and multiple viewports, and the supplied
   high-resolution harness. Inspect Paint info if a callback reports an error.
6. On a dense curved mesh, make one short Relax dab at a nonuniform boundary.
   Compare unchanged outside vertex values, including the immediate one-ring
   halo, with the inside patch. Repeat in perspective and orthographic views,
   with cm/m/mm scene units, high-DPI scaling, B-adjusted radius and Mask mode.
   Drag to a second patch: the first patch must keep its previous result while
   the second changes. Increase Brush passes and confirm the write boundary
   stays fixed. One Undo/Redo must restore/reapply the whole gesture.

Possible future controls include distance-weighted topology averaging, explicit
protection masks and alternative brush ramps. They are not part of this update.

Saved-layer/cache cleanup is documented in [CLEANUP_GUIDE.md](CLEANUP_GUIDE.md).
