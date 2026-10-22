# waveJoints · Toolkit 2.39

Create a sine wave across an ordered list of joints, using the driver
controller's custom attributes. The graph uses native Maya 2024+ nodes and
evaluates after the toolkit window closes. No plug-in, expression, scriptJob or
per-frame Python callback is installed.

## First test

1. Open **waveJoints** and Get one driver controller.
2. Select the first joint of an unbranched chain and click **Get chain**, or
   use **Add selected** to append joints. Confirm the order by dragging the rows
   or using Up, Down and Reverse. Get chain reports branches for manual choice.
   Maya's tracked selection order is used when enabled; the tool does not
   change that preference.
3. Choose outputs. **TY** is enabled initially. Check any of TX, TY, TZ, RX, RY
   and RZ. Set the corresponding translation/rotation amplitude.
4. Validate and **Build wave**. A new driver has **Envelope = 0**, preserving
   the initial pose. Click **Enable wave** to see the wave.
5. Select the driver and animate **waveOffset**, or enable **Automatic time
   motion** and set Speed. Positive/negative Speed changes travel direction.
   Speed is cycles per second; Frequency is cycles across the joint list.
6. **Mute wave** returns the selected channels to their saved local values.

The wave adds to the local channel values sampled at Build. Joint orientation,
rotateAxis, rotate order, scale and parent hierarchy are retained. A rotation
wave follows each joint's local axes and Euler rotation order. A translation
along a bone axis deliberately changes that segment's length. Choose free
channels or a dedicated wave joint chain when another rig already drives the
desired channels; incoming animation/constraint connections are protected.

## Controls

The default attribute prefix is `wave`. Use another prefix for an independent
set of controls on the same controller. Compatible existing attributes are
reused with their current values, including direct time animation. Existing
values take precedence over Build's defaults; Validate reports reuse.

| Driver attribute | Meaning |
| --- | --- |
| waveOffset | Global phase in degrees. Key this to move the wave manually. |
| waveFrequency | Number of cycles from the first to the last listed joint. Fractions and negative values are supported. |
| waveEnvelope | 0–1 blend from saved local pose to full wave. Initially 0 for new attributes. |
| waveTranslateAmplitude | Translation amplitude in the scene's linear units. |
| waveRotateAmplitude | Rotation amplitude. Maya displays this typed angle in its current angular units; the toolkit UI uses degrees. |
| waveRootWeight / waveTipWeight | 0–1 amplitude multipliers at the first/last listed joint, interpolated across the list. |
| waveAutoTime | Add automatic time motion to Offset when enabled. |
| waveSpeed | Cycles per second of automatic motion. |
| waveFalloffPosition | Peak of the falloff envelope: 0 = first listed joint, 1 = last; default .5. |
| waveFalloffPower | 0 disables falloff; 1 gives linear falloff; higher values keep a wider area strong. Default 0. |
| waveTYGain / waveTYPhase | Per-axis multiplier and phase in degrees. Corresponding attributes are created for each chosen output. |

All created driver attributes are keyable and unlocked. **Offset** and
per-axis **Phase** are unitless numbers interpreted as degrees. The graph
explicitly converts angles and normalizes typed sine outputs so changing
Maya's linear/angular display units does not change physical motion.

**Even spacing by list index** distributes phase evenly over the rows.
**Spacing by rest distance** uses accumulated distances between consecutive
listed joints, sampled at Build. Subsequent updates use these cached positions,
so the active wave cannot feed back into its own spacing. With one joint the
position is zero and Offset/time still produces a normal oscillator.

## Useful setups

**Position falloff** multiplies the wave contribution by a distance weight.
Set Position .5 and Power 2 to put its peak at the middle of the ordered list.
Animate Position to move that peak from the first joint (0) toward the last (1).
Position uses the same list-index or cached rest-distance coordinates as the wave.
With an even number of evenly spaced joints, .5 lies between the middle joints;
those two receive the largest sampled weights. The continuous peak is still 1.

Higher Power reduces the loss with distance. For a joint .5 away from the peak:

| Power | Weight |
| --- | --- |
| 0 | 1, falloff disabled |
| 1 | .5 |
| 2 | .75 |
| 4 | .9375 |

Both new attributes are unlocked/keyable and can drive SDKs. Power accepts
0–1000; positive values below .001 use .001 for the calculation. The native
graph keeps its exponent positive even while bypassed, including unused Y/Z
channels, so the center with Power 0 does not require an undefined `0**0`.

For a tail, choose RY or RZ, set rotation amplitude to 10–20 degrees, first
amplitude to 0 and last amplitude to 1. Start with Frequency .5–1, Enable wave,
then key Offset. Automatic motion at Speed .25 takes four seconds per cycle.

For circular translation, enable TY and TZ with matching gains and translation
amplitude. Set TY Phase to 0 and TZ Phase to 90. Each joint describes a circle
around its saved local position. Use an axis Gain of −1 to reverse that axis.
TY and RZ can also run together, using separate distance and angle amplitudes.

To keep length unchanged, use rotation outputs and leave translation outputs
unchecked. Positive root/tip weights let the corresponding ends participate;
setting one end's amplitude to zero anchors that end's wave contribution.

## Equation

Let `s_i` be the joint's position from 0 to 1 in the chosen ordering/spacing,
`t` native scene time in seconds, and `k` a selected output channel:

```text
phase(i, k) = Offset + 360 * (Frequency * s_i + AutoTime * Speed * t) + AxisPhase(k)
weight(i)   = Envelope * ((1 - s_i) * RootWeight + s_i * TipWeight)
distance(i) = min(1, abs(s_i - FalloffPosition))
falloff(i)  = 1                                  # when FalloffPower = 0
            = 1 - distance(i)**max(.001, FalloffPower)  # otherwise
output(i,k) = savedLocal(i,k) + amplitude(k) * AxisGain(k) * weight(i)
                              * falloff(i) * sin(radians(phase(i,k)))
```

`amplitude(k)` is the translation or rotation amplitude. The graph shares
time/phase/frequency and channel-amplitude calculations and creates sine branches
only for selected outputs. There are no scale drivers or constraints to group.
Generated DG nodes are registered by UUID and message links on a network node.

## Update and removal

Scene setups are saved with the Maya scene. Refresh and **Load** one to restore
its controller, ordered list and UI values. **Apply settings / order** supports
the same joint and channel set. You can reorder the joints, change spacing,
gain, phase, taper and wave values. Only edited parameter fields are applied;
untouched live/animated values remain. Edit or key an animated parameter in the
Channel Box rather than overwriting its incoming animation through Apply.
Changing the driver, joint membership or output channel set requires a new setup.

**Existing 2.38 waves:** Load reads them without changing the scene. The new
falloff fields display Position .5 and Power 0. Apply settings / order installs
the falloff branch in place, then applies your edited settings. It retains
the system UUID, original graph nodes, saved rest values and driver animation.
With Power 0, the wave keeps its previous result. Repeated Apply reuses the
falloff nodes. The upgrade is part of the same Undo action. An edited legacy
output or rest-value sum is reported before conversion. New attributes that
already exist with compatible types are reused with their live values.

**Delete wave · keep current joint pose** samples the current driven channel
values, removes only the owned graph, restores those values, then verifies
world poses and orientation definitions. Source joints and driver controllers
are retained. This keeps the current frame; it does not bake animation.
Renamed nodes and partly deleted graphs are supported when ownership can be
verified. Another driver on an affected joint channel, locked members or a
foreign consumer of a wave output are reported before removal.

With **Remove unused attributes when deleting** enabled, unconnected attributes
created by this setup are removed. Animated attributes, SDK drivers, shared
attributes and attributes reused at Build remain. Disable this option to keep
all wave controls. Build, Update and Delete each use one Undo step and roll back
on failure. Closing or reloading the UI does not delete the graph.

## Python

```python
import wave_joints as wave

result = wave.build(
    'wave_ctrl', ['tail_01_JNT', 'tail_02_JNT', 'tail_03_JNT'],
    channels={'ry': {'gain': 1, 'phase': 0}},
    settings={'frequency': .5, 'rotation_amplitude': 15,
              'root_weight': 0, 'tip_weight': 1})

wave.update(result['system'], settings={'envelope': 1, 'auto_time': True, 'speed': .25})
wave.update(result['system'], settings={'falloff_position': .5, 'falloff_power': 4})
print(wave.current_settings(result['system']))
wave.remove(result['system'])  # keep this frame's evaluated joint pose
```

## Verification

958 host checks pass, including 50 wave graph/transaction/Qt checks.
Numerical checks cover sine samples, circular phases, rest values,
cached distance/order updates, Maya's legacy distance/new unitless sine outputs,
cm/m and deg/rad conversion, time, falloff peak/power, upgrade from a fixed
2.38 command-graph fixture, ownership and rollback. These use a command
adapter and do not execute Maya's native dependency graph.

Run the supplied native fixture in Maya:

```python
import maya_wave_joints_smoke
maya_wave_joints_smoke.run()
# run(keep=True) leaves its unique fixture and wave graph for inspection.
```

Native Maya is unavailable on the build host; this fixture remains unexecuted
there. It checks neutral build, actual sine evaluation, units, time, reorder,
animation preservation, posed removal and native Undo/Redo. It never opens a
scene or clears Undo.

Maya references: [2024 native math nodes](https://help.autodesk.com/cloudhelp/2024/ENU/Maya-SDK/files/What-s-New-What-s-Changed-/Maya_SDK_What_s_New_What_s_Changed_2024_Whats_New_in_API_html.html),
[sin in 2025](https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Tech-Docs/Nodes/sin.html),
[sin in 2026](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Tech-Docs/Nodes/sin.html),
[unitConversion](https://help.autodesk.com/cloudhelp/2022/ENU/Maya-Tech-Docs/Nodes/unitConversion.html).
