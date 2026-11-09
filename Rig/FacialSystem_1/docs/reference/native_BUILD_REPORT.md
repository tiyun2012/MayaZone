# Build report

This package reconstructs the connected output scope of the cleaned Maya scene,
using the supplied binary DNA as the behavior source. It does not add the many
DNA joints absent from, or unconnected in, that scene.

## Source identity

| Source | SHA-256 |
|---|---|
| `facialRig(1).ma` | `15df57be12cf2da04a94266971be02187e5430eda9bb5cbea6beddcc935b45df` |
| `head.dna` | `8738fed173be08b5000486991e7e75958163279f0cc2d29fae94373e965d1722` |

Original attachments were read without executing their scene scripts and were
not modified. Their paths are not needed by the reconstructed runtime.

## Evaluation

The existing GUI continues to drive its 251 expression inputs. Local Euler
rotations on `neck_01`, `neck_02`, and `head` are converted to 12 quaternion
components, respecting all six Maya rotation orders. The supplied DNA uses one
38-target interpolative quaternion RBF solver, 545 product corrective controls,
and 18 RBF pose outputs. It has no active machine-learning or twist/swing
behavior extension.

The 1,962 selected joint channels use 325,282 nonzero linear coefficients.
Translation is neutral translation plus a delta; Euler rotation is a delta
with the original joint orientations preserved; scale is one plus a delta.
The selected rows have no overlapping joint group contributions.

The runtime graph contains three numeric network buses, 218 `wtAddMatrix`
nodes, 654 `pointMatrixMult` row extractors, 1,962 explicit final channel unit
conversions, and 22 built-in expressions. The expressions cover local
Euler-to-quaternion conversion, the RBF, product correctives, and 82 connected
animated material multipliers. Original native nodes and their connections
are retained. Native expressions contain arithmetic and direct attribute
references, with no `getAttr`, `setAttr`, `eval`, or Python callbacks.

The old `embeddedNodeRL4`, four `dx11Shader` nodes, Arnold configuration nodes,
and two source script nodes are removed. DirectX materials are replaced with
four Lambert materials. The output file declares only Maya 2024 as a
requirement. Texture files were not supplied; material parity is not claimed.

## Reference and validation boundary

Reference: Epic Games OpenRigLogic, stable 5.8, commit
`55756aca0c4c55adc56ad68a796bcc1c0bf6fa5a`:
<https://github.com/EpicGames/OpenRigLogic>

A scalar float C++ reference evaluator was built offline to decode the DNA,
extract interpolative RBF coefficients, and generate reference output cases.
The portable behavior and final generated matrix payload were checked against
those outputs. That C++ evaluator is not required by or bundled into the Maya
runtime. The DNA reader and the runtime builder use only Python's standard
library. The interpolative RBF coefficient matrix is baked into the portable
behavior; regenerating a new DNA's coefficient matrix is not exposed as a
general user tool in this version.

The original scene declared `embeddedRL4` version `2.10.3.6`. That plug-in was
not run. Validation against a modern official evaluator verifies the decoded
behavior and formulas, and is not a substitute for an A/B test against the
original plug-in. The generated scene has not been opened in Maya in this
environment. Timing and GUI/mesh playback therefore remain unmeasured.

`VALIDATION.json` reports portable evaluator comparison. `ARTIFACT_CHECKS.json`
reports preservation of original native nodes and links, exact emitted matrix
coefficients and channel units, all six quaternion rotation orders, and a
separate evaluation of the generated expression arithmetic over the same
1,491 cases. The expression arithmetic was translated and checked outside
Maya, rather than compiled by Maya.

The supplied optional Maya check uses tolerances of 0.006 cm translation,
0.025 degrees rotation, and 0.00001 scale. A pass should be followed by visual
tests of the GUI, lip/eyelid contact, combined expressions, and neck motion.
