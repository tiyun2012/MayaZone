# Root and Foot modules · Toolkit 2.41

Open **Modular Rig → Modules**. **Root module** and **Foot module** are separate collapsible
sections alongside FK, Three-Bone IK and IK/FK. Their controls appear in the
shared **Scene modules** manager after building or reopening a scene.
Each module row has its own **Constraints**, **Mirror** and **Delete Rig**
actions. Root and Foot source solvers use matrices. If a module has a native
parent-constraint attachment, Constraints also organizes that attachment.
The new **Connections** tab scans start joints and suggests parent outputs; see
[Rig_Connections_Guide.md](Rig_Connections_Guide.md).

## Root: character placement

1. Expand **Root module**. Optionally Get a **Root joint** from your existing
   skeleton. Get accepts one joint; Clear disables the joint attachment.
2. Optionally Get a placement transform/locator. Blank uses the root joint's
   position/orientation when a joint is supplied, otherwise world origin.
   Placement supplies a rigid frame, not scale. A separate placement frame keeps
   the joint's current offset.
3. Set the control size and module name. Default names are `Main_ctrl` and
   `Root_ctrl`; custom-name fields can override either.
4. Validate and Build. Main is the parent of Root. Main handles character
   placement and uniform `globalScale`; Root adds a second placement offset.
   The optional skeleton root follows Root_ctrl. No transform channels are
   locked. Main scale channels receive the globalScale connection.
5. Build another module with Parent control blank. In **Scene modules → Module
   outputs / attachment**, choose Root's **Placement** output, **Use output as
   parent**, choose the child module and **Attach selected module · keep offset**.
   Existing manual Parent control connections remain supported. See
   [Module_Outputs_Guide.md](Module_Outputs_Guide.md) for named outputs and safe
   detach/mirror/removal.

The generated hierarchy is `INPUT > MAIN_ZERO > Main_ctrl > Root_ctrl`. INPUT
receives optional module attachments. ZERO stores the
placement frame; both controls start with zero local translation/rotation and
unit scale. `Main_ctrl.globalScale` starts at 1 and has a positive .001 minimum.

**Root joint is optional.** When set, exactly that joint receives a native
`offsetParentMatrix` driver with local-frame/SSC compensation and a maintained
bind offset. Child joints follow the existing skeleton hierarchy; they are not
reparented or directly connected by this module. Local translate, rotate, scale,
jointOrient, rotateAxis and segmentScaleCompensate definitions stay unchanged.
Global scale is carried by the matrix, without connecting joint scale channels.
The supplied joint is recorded as a source and is never an owned/deletable rig
member. A driven/animated/locked source, another module's source joint, or an
occupied/locked offsetParentMatrix fails Validate before creating rig nodes.
A static, writable offsetParentMatrix is supported and retained at bind time.

With Root joint blank, the previous placement-controls workflow remains
available. Existing saved Root modules without a joint remain readable. To add
this binding to a previously built Root, detach/remove child modules as needed,
then remove and rebuild that Root with the joint field filled. Build does not
silently edit an existing module or replace another system's driver.

**Delete Rig** retains the source joint and its evaluated world pose using a
static offsetParentMatrix. Its parent, descendants, local channels and joint
orientation definitions remain. Go to Default moves the joint through its
controller; Include ROOT/globalScale also restores Main. A joint-driven Root
can coexist with a Foot on its descendants: both share Main scale and the Foot
output compensates the actual source parent, avoiding a second scale factor.

The manager's **Select Root control / Foot ankle target** button selects
Root_ctrl for a Root module; **Select root / globalScale** selects Main_ctrl.

## Foot inputs

| Field | Meaning |
| --- | --- |
| Ankle joint | Start of the foot; may be left to an existing leg rig. |
| Ball joint | Must be a direct child of ankle. Always receives this module's ball output. |
| Toe tip locator | Ground pivot at the toe tip; required in IK mode. It is not a source joint. |
| Left / right side pivots | Ground positions at the two sides of the foot; required in IK mode. |
| Heel pivot | Ground pivot behind the ball; required in IK mode. |
| Parent control | Optional attachment, normally Root_ctrl. |
| Ground up axis | Y or Z. Roll uses a ground frame built from this axis and heel-to-toe direction. |
| Bank direction | +1 or -1; mirror flips it automatically. |

Use the Get button beside each field. Pivot guides contribute their **positions**
only. Their rotations need not be frozen or aligned. Guides stay in the scene,
are not owned/deleted by the module and can be hidden. Positions are sampled at
build time; moving a guide later does not edit the rig. Rebuild to change pivots.
Keep the guide objects if you want mirror to find their counterparts by name.

Ankle/ball must have positive uniform, unsheared world transforms. Driven source
TRS, locked channels and an occupied offsetParentMatrix are preflighted. Maya
2020+ is required for the matrix outputs. Arbitrary nonuniform/negative scale
is not supported. Source joint parents and orientation definitions are retained.

## IK foot: reverse-foot controls

Choose **IK**, fill all six joint/guide fields and Build. The foot creates a
module ROOT/globalScale control, an ankle/foot control, and a smaller ball control.
Select the ankle/foot control to view the following unlocked, keyable attributes.

| Attribute | Behavior |
| --- | --- |
| footRoll | Negative rocks back on heel; positive rises on ball then continues onto toe. |
| ballBreak | Ball roll peak and start of transition; default 45 degrees. |
| toeStraight | End of transition onto toe; default 70 degrees. Set above ballBreak. |
| heelRoll / ballRoll / toeRoll | Independent additive adjustments at those pivots. |
| bank | Positive uses the left pivot; negative uses right. Bank direction reverses rotation sign. |
| heelTwist / toeTwist | Twist around the chosen ground-up axis at heel / toe. |
| toeTap | Ball rotation about the ground-frame roll axis. |

The ball control also allows an independent FK toe/ball rotation. Foot module
ROOT.globalScale is a local multiplier; leave it at 1 when Main controls the
character scale. Use the ankle/foot control for normal foot placement/rotation.

This is a **reverse-foot pivot module**, not another full leg IK solver. Native
transform pivots and math nodes produce ankle/ball target matrices directly;
it does not create another RP or SC leg chain, an expression or a frame callback.
No stretch or bone-length change is added. Joint local scale channels are not
driven; deliberate global scale is carried in the output world matrices.

The pivot order is heel > left bank > right bank > toe > ball. The ankle target
is below ball; the ball target is below toe, with toeTap around ball. This keeps
the ankle-to-ball distance constant during automatic roll. Independent animator
translations/scales on the ball control can change that relationship intentionally.

For positive roll r, b=max(.001,ballBreak), d=max(.001,toeStraight-b):

    t = clamp((max(r,0)-b)/d, 0, 1)
    ball = min(max(r,0),b) * (1-t)
    toe = max(r,0) - ball
    heel = min(r,0)

The result is continuous at ballBreak and toeStraight, with ball+toe=max(r,0).
Manual adjustments are added afterward. The safe span prevents zero division
even if the artist moves toeStraight below ballBreak. Foot attributes are numeric
**degrees**, independent of Maya's scene angle unit; owned angular conversion
nodes use degrees-to-radians for the actual rotate plugs.

## Connect to an existing leg

If a Three-Bone IK or IK/FK leg already drives ankle, turn **Drive ankle joint**
**off**. The foot then drives only ball. Ankle remains connected to its leg.
In **Module outputs / attachment**, select Foot's **Ankle target** output. The
legacy **Select Root control / Foot ankle target** button still selects the
internal target for existing setups.

For the existing module architecture, parent the leg's IK END **ZERO group**
below this ankle target with world transforms preserved, at the neutral/default
foot pose. The foot itself must be attached independently through Root's Placement output
(or an existing Root_ctrl parent).
Do not parent the foot under the leg END or under a joint controlled by the foot.
That would feed the leg back into its own foot target. In an IK/FK leg, this
attachment affects the IK branch; FK foot is a separate build mode, not a runtime
foot IK/FK switch or an automatically matched extension of the leg blend.

The tool deliberately leaves the existing leg graph untouched. When ankle is
free, leave Drive ankle on and the Foot drives both joints. For an integrated
character, both the leg module and foot should share the Root placement hierarchy.

## FK foot

Choose **FK**. Only ankle and ball joints are required; pivot fields are disabled.
The ankle control parents the ball control, with separate zero groups matching
the source bind frames. Animate their rotations normally. The same matrix outputs,
module ROOT/globalScale, optional parent, name fields and manager actions apply.
FK/IK are chosen at build time. No constraint-weight switch is introduced.

## Reset, names, mirror, removal

- **Go to Default** resets the two foot controls and all roll parameters. Include
  ROOT/globalScale also restores placement/scale. For the Root module, the usual
  reset restores Root_ctrl; Include ROOT additionally restores Main_ctrl.
- **Store current as default** saves current local control/parameter values.
- **Load selected rig name fields / Apply controller names** supports both types.
  Foot names derive from ankle/ball; Root defaults use Main_ctrl and Root_ctrl.
- **Mirror** builds a separate Foot on existing counterpart joints and guide
  objects using Search/Replace, e.g. `_L` to `_R`. Bank sign reverses. A central
  Root parent remains shared; a side-specific parent must have a counterpart.
  Animation and posed controller values are not copied. Limb mirroring reuses
  a central Root parent.
- **Root Mirror** is available when that module has a source Root joint. The
  source joint name must map to an existing, writable counterpart. An explicitly
  supplied side-specific placement guide must also have a counterpart; a central
  guide is shared. Older Root metadata without a saved guide uses the counterpart
  joint's frame. A placement-only Root has Mirror disabled and stays shared.
- **Delete Rig** samples the current joint matrices, removes only owned nodes,
  and retains the evaluated pose with static offsetParentMatrix values. Local
  TRS, jointOrient, rotateAxis and SSC definitions remain. Removal is not a bake.
- Detach a leg END ZERO or other foreign objects from the foot before removing it.
  Remove/detach child modules before removing their Root. The manager protects
  foreign children/output users instead of deleting them. Build/Remove are Undo
  actions; failure rolls back the current action without clearing existing Undo.

## Python example

```python
import master_rigging_toolkit as toolkit

root = toolkit.build_root_module(
    name='Character', control_size=10, root_joint='SkeletonRoot_JNT')
# Omit root_joint to build placement controls without driving a skeleton.
foot = toolkit.build_foot_module(
    'ankle_L_JNT', 'ball_L_JNT',
    toe_tip='toeTip_L_LOC', left_pivot='leftPivot_L_LOC',
    right_pivot='rightPivot_L_LOC', heel_pivot='heel_L_LOC',
    mode='IK', name='Foot_L', parent_control=root['attachment'])

# foot['ankle_controller'] holds roll/bank; foot['ankle_target'] is the leg target.
# Root_ctrl is root['attachment']; Main_ctrl is root['main_controller'].
```

## Verification

Revision 2.37 passed **908 host tests**, including Root-joint, per-row action
and constraint-group checks. All Python files compile with the Python 3.10
grammar. The module manager was checked with real PySide6 offscreen.
Maya's native evaluation and the updated smoke fixture remain unexecuted on
this host.


The package includes recorded-command matrix/graph tests and actual Qt checks.
They cover both build modes, neutral pose, roll values, positive/negative bank,
root-scale inheritance, guide validation, existing leg preservation, defaults,
mirroring, metadata ownership, failure rollback and posed removal. Root-joint
checks cover maintained offsets, placement override, child scale inheritance,
source-driver protection, defaults and retained pose after removal. These are not
Maya's dependency graph or solver. Native Maya is unavailable on the build host.

Run the supplied native fixture in Maya:

```python
import maya_root_foot_smoke
maya_root_foot_smoke.run()
```

It tests the optional skeleton Root joint with nonzero JO/RA, unchanged local
channels and hierarchy, roll/length/scale, Main scale, defaults, posed removal,
native Undo/Redo and FK. It uses a unique test namespace and removes its fixture
by default without opening a scene or resetting Undo. `run(keep=True)` retains
the successful fixture for inspection. Native results and timing remain pending.

Native math references: [multMatrix](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/Nodes/multMatrix.html)
and [transform](https://help.autodesk.com/cloudhelp/2024/ENU/Maya-Tech-Docs/Nodes/transform.html).
