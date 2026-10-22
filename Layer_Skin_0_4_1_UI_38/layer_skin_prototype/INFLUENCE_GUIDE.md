# Influence locks and redistribution · UI 21

Each hierarchy row now has a clickable padlock before its joint icon. Gray open
means unlocked; gold closed means locked. UI 21 uses Maya's native
`:/Lock_OFF.png` and `:/Lock_ON.png` resources, with its generic unlock/lock
icons as alternatives. They are loaded once per browser, keeping the existing
16-pixel click area and cached joint/lock row icons. A drawn fallback is used
only when the host resources are unavailable (including standalone Qt tests).
The lock belongs to the selected
editable layer. A gray joint name still means no nonzero weight in that layer;
the padlock is independent of that weight-status color.

Clicking a padlock keeps joint/vertex selection and changes only layer settings.
Pending paint saves before the settings change. The toggle is one Undo action.
A failed save leaves the previous icon and data. Base has no editable locks.

Select a locked joint to view its saved weights. Paint opens a read-only view
for that joint, using zero native brush opacity. Unlock it or select an unlocked
joint to paint again. Mask painting remains available independently. A lock on
an unbound descendant prevents paint/assignment from automatically binding it.

## What a lock protects

The displayed layer contribution for joint j at vertex v is

    q[v,j] = sample.weights[j] * sample.coverage

Weight editing preserves q for locked joints. Painting/Flood, Replace/Add/Scale,
assignment/rebuild, Clear paint edits and both Relax paths respect these locks.
Relax excludes locked columns from its solve on every pass, not just at the
final save. Its outside one-ring halo is still read only. Joint-group budgets,
new-influence limits and the UI 16 brush footprint limits remain in effect.

Assignment skips selected locked joints before binding/generation. Where a new
assignment or clearing an override would alter a locked contribution, a manual
override retains that contribution. Unlock and clear/rebuild when you want to
replace the protected data.

Locks protect this layer's contribution, rather than freezing the final native
skinCluster result. Layer coverage, lower/upper layers, mask, alpha, Enabled,
stack order and deleting a layer can still change final skin weights. Reducing
an unlocked contribution can reduce coverage and expose lower-layer weights.
The original composition formula is retained. No transform channels, Maya
lockInfluenceWeights attributes or native normalization settings are changed.
Existing native locks/driver checks remain separate preflight guards.

## Redistribution

The right dock has a **Redistribution** choice saved per layer:

| Choice | Replace/Add/Scale, brush and Execute |
| --- | --- |
| Proportional (default) | Retain the ratios of other unlocked, currently weighted joints. |
| Equal | Share their combined available contribution equally among those joints. |

Neither choice assigns weight to unrelated zero-weight influences. Both retain
locked contributions. Let L be the locked contribution sum, t the requested
selected-joint value, and U the previous sum of other unlocked contributions:

    selected = min(t, max(0, 1-L))
    others_total = min(U, max(0, 1-L-selected))

Proportional shares others_total using their old ratios. Equal shares it evenly
among the other unlocked joints with positive existing contributions. A zero
recipient sum needs no division. For example, with locked weight 0.3, requesting
1 for another joint is capped at 0.7. No negative remainder is created.

Reducing a value can leave transparent coverage, preserving the previous layer
workflow. The choice does not fill missing coverage to one. Relax uses its
topology average instead of equalizing all its neighbor-derived contributions;
assignment retains its generated distribution within the unlocked budget.

## Save, Undo and refresh

Settings use optional influence_locks (joint UUID list) and redistribution fields
in each layer's existing schema-2 data. Existing layers default to unlocked and
Proportional. UUIDs retain locks through renaming, influence reordering and new
zero-weight columns. A recreated joint has a new UUID and starts unlocked.
Scene save/reopen, UI close/reopen and the safe UI refresh retain settings.

UI 18's refresh loads the updated core editing/validation functions alongside
the UI/session/tree helpers. The registered command class, native Undo objects
and weight snapshots stay live. Do not unload the plug-in or clear Undo to
apply this update. Use the complete UI 18 folder when editing lock-enabled data;
earlier UI/core implementations do not enforce the optional locks.

Utilities exports final skin weights and imports a new layer; it is not a
layer-settings archive. Existing layers' locks remain unchanged by import.

## Verification

Local tests cover budgets, partial coverage, empty/all-locked cases, randomized
weight rows, assignment/clear protection, regular/Shift Relax, masks, persistence,
unbound binding prevention, actual offscreen Qt hit testing, pending-stroke
ordering, rejected saves, warm refresh and command/weight Undo/Redo.

Maya/VP2 and PySide2 cannot be run in the build environment. In Maya 2024, refresh
to UI 18 and test padlock clicks at your display scale. With two or more painted
joints, lock one, paint another above the remaining budget, then switch back and
compare its displayed layer values. Test both redistribution choices, mask
painting, Shift/regular Relax, assignment, Clear paint edits and Undo/Redo.
Save/reopen a test scene and confirm the layer settings and values return.
