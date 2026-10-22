# Relax, Replace, Add and Scale · UI 18

UI 18 adds per-layer influence padlocks and Proportional/Equal redistribution.
Locked contributions are fixed during weight edits. A locked selected joint is
read only; masks remain editable. See INFLUENCE_GUIDE.md for budgets and scope.

The four groups share one horizontal row. Each group keeps its parameters above
its Execute button. Select a group's **Use brush** radio, then click **Paint**.
Changing the radio while painting changes the operation without dropping the
weight colors. Each group remembers its own value.

| Group | Parameters | Execute result |
| --- | --- | --- |
| Relax | Iterations, Strength, Max new influences, Brush passes, Keep coverage | Smooth neighboring layer contributions, or the mask in Mask mode. |
| Replace | Value, 0–1 | Set the selected joint's layer contribution or mask to Value. |
| Add | Amount, −1–1; default 0.1 | Add Amount to the current value. Negative amounts subtract. |
| Scale | Multiplier, 0–100; default 0.5 | Multiply the current value. 0.5 halves it, 2 doubles it, 1 keeps it. |

Replace, Add and Scale clamp their result to 0–1. For current value `q` and
parameter `p`, Execute computes `p`, `clamp(q+p, 0, 1)`, or
`clamp(q*p, 0, 1)`, respectively. A zero value remains zero under Scale.
These operations affect this layer's authored contribution (distribution ×
coverage), before its mask and Alpha. They do not calculate from the final
skinCluster weight or change lower layers. When the edited contribution would
exceed the available total, other authored contributions are proportionally
reduced by the existing paint solver. The stored distributions and final skin
weights remain normalized.

## Brush falloff and a consistent Replace value

**Replace selects a target value; a soft brush blends toward it.** UI 14 and
earlier forced a Gaussian stamp, including after feedback refresh, without
showing a falloff control. This is one reason values can differ across a stroke.

UI 15 exposes the native stamp profile beside Radius and Opacity:

| Falloff | Result |
| --- | --- |
| Solid (default) | Full brush effect throughout the footprint. Use Opacity 1 for a uniform Replace value. |
| Smooth | Polynomial soft-edge profile. Edge vertices can receive a partial change. |
| Gaussian | Bell-shaped soft profile. The strongest change is near the center. |

Opacity below 1 reduces the brush effect even with Solid. Layer Skin explicitly
disables native stylus-pressure modulation and opacity accumulation; neither is
an extra hidden multiplier. The exact soft-profile samples are supplied by
Maya's Artisan engine. There is no claim that this package reproduces Maya's
Gaussian equation numerically. Committing a stroke stores the final absolute
native-array values once, without applying falloff again.

The falloff menu applies to Replace/Add/Scale. Relax and Shift use the existing
smooth layer solver and its documented `(1-r*r)^2` radial factor. The menu is
disabled when regular Relax is selected. Their strength/opacity and coverage
controls retain the previous behavior. Execute ignores brush falloff and brush
Opacity, applying its group's full configured amount to its scope.

**The paint value belongs to the selected layer.** The final skinCluster also
includes Base, layer coverage, Alpha, mask and other enabled layers. For example,
an isolated layer contribution of 0.5 over a Base weight of 0.8, with authored
coverage 0.5 and Alpha/mask 1, can produce final weight `0.5 + 0.5*0.8 = 0.9`.
That does not mean the stored selected-layer value changed. Leave Show final
skin weights off to inspect the layer's paint values; enable it to inspect the
composed skin result.

## Scope and masks

Replace/Add/Scale Execute requires selected vertices on the loaded mesh, or the
explicit **whole mesh** checkbox above the row. The checkbox also supplies the
scope for Clear paint edits and Inspect. Relax retains its existing scope:
selected vertices/edge endpoints, or the whole mesh when no components are
selected. A component from another mesh is rejected.

Choose **Weights** to edit the current hierarchy joint; choose **Mask** to edit
the selected layer's mask. Mask operations need no joint and keep weight samples
unchanged. An unpainted mask starts at 1; an unauthored joint contribution starts
at 0. To hide a new layer initially, choose Mask, whole mesh, Replace Value 0,
Execute; then paint Value 1 in the desired region. Base remains read-only.

Execute uses the group's full amount. **Brush Opacity** affects strokes only;
Relax Strength affects both Execute and its brush. Iterations controls Relax
Execute, while Brush passes controls each Relax stamp. Keep coverage now applies
to both weight Relax methods and is off by default. Joint selection and Max new
influences keep their previous behavior; see [RELAX_GUIDE.md](RELAX_GUIDE.md).

## Brush and Undo

- **Use brush → Paint** applies that group's operation and parameter. Radius and
  Opacity stay shared. Native B + drag still changes the radius.
- **Shift + paint** temporarily uses the layer Relax solver for every group.
  Without Shift, normal strokes return to the selected operation. Selecting
  Relax uses the same solver on regular left-button strokes.
- Escape cancels a Relax gesture. Native Artisan handles regular Replace/Add/
  Scale gestures; its existing key behavior is retained.
- A completed stroke or Execute is one authoring Undo step. Changing operation
  saves a valid pending stroke first; a rejected stroke keeps the old operation.
- Selecting a group or changing parameters does not edit saved layer data.
  Saved paint/mask values survive joint changes and UI refresh. A refresh keeps
  all operation parameters, the selected group and existing Undo objects.

Replace/Add/Scale use Artisan `selectedattroper` absolute/additive/scale with
result clamping at 0–1. The native doubleArray already contains final absolute
values; commit never applies Add or Scale a second time. Relax continues through
the custom layer solver, with Maya's native outline and the retained UI 12 color
handoff guard. No viewport overlay is introduced.

Native flag definitions were checked against Autodesk's
[artUserPaintCtx reference](https://help.autodesk.com/cloudhelp/ENU/MayaCRE-Tech-Docs/Commands/artUserPaintCtx.html).
Local tests use recording API adapters and real offscreen Qt. Native Maya/VP2
and tablet behavior still require verification in Maya.

## Maya verification

1. On a test mesh, Replace one joint's contribution with 0.4. Add 0.2 should
   produce 0.6; Scale 0.5 should produce 0.3. Check each action's Undo/Redo.
2. Select each Use brush radio and paint. Check negative Add, Scale above 1,
   boundaries 0/1, brush Opacity and B-radius adjustment. Switch joints and back.
3. Shift-paint from all three native operations; verify layer Relax previews,
   saves once, and returns to the selected operation. Select Relax and compare a
   regular stroke. Check Escape and releasing Shift before the mouse.
4. Repeat Replace/Add/Scale and Relax in Mask mode. Verify stored joint samples
   remain unchanged. Test selected vertices, explicit whole mesh, rejected scope
   and a locked/driven native write without losing saved layer data.
5. Run the UI refresh with different values in every group. Confirm UI 18,
   retained values, no intermediate base-color frame, and existing Undo history.
6. Set Replace Value 0.35, Opacity 1 and Solid. Paint across a sufficiently dense
   region with different starting values; inspect selected-layer values. Compare
   Smooth/Gaussian, where a soft edge is expected. Switch joints and back, then
   Undo/Redo. Check that changing falloff saves a pending stroke first and the
   chosen profile survives a UI refresh. Native Maya/VP2 testing remains pending.
