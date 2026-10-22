# UI 35: Select vertices preview constructor fix

## Cause and correction

The failing call was in `layer_skin_vp2.py`, not the WeightView facade:

```python
MHUDRender('rtkLayerSkinHUD')
```

Unlike `MSceneRender` and `MPresentTarget`, the HUD operation does not take a
custom name. UI 35 calls `MHUDRender()` with no arguments. Autodesk's public
constructor and Python API example support this initialization; subclassing or
zero-argument initialization is not generally forbidden.

The earlier recording test incorrectly gave HUD the same named constructor as
the present operation. Tightening that fixture to a zero-argument constructor
reproduced the failure before the production fix was applied. The corrected
renderer now runs against that stricter fixture throughout the viewport suite.

The weight triangles are drawn by the scene operation. The renderer attempts
the standard HUD once. If its no-argument constructor raises TypeError, only
the HUD pass is omitted, allowing the scene and present passes to continue.
Required scene/present constructor failures still propagate. No CPV/color-set
fallback or scene-node creation is introduced.

The fallback may omit Maya's standard HUD while the selection renderer is
attached. Paint, Stop, close and save/export retain the existing panel-restoration
behavior. Paint info includes these fields under `persistent_display`:

- `renderer_revision`: 35.
- `hud_enabled`: whether the HUD operation was constructed.
- `hud_constructor_error`: the binding error when the optional HUD was omitted.

Both facade and renderer helper cache keys are new. Replacing only the source
without reloading could otherwise reuse the old cached renderer. Existing
registered commands, skin weights, layer data and native Undo objects are kept.

## Load and check in Maya

Replace the complete `layer_skin_prototype` folder and run:

```python
import runpy
runpy.run_path(
    r"D:/dev/MayaZone/layer_skin_prototype/layer_skin_ui_refresh.py",
    run_name="__main__"
)
```

Confirm **UI 35**. The registered plug-in version remains **0.4.1**.

In a working scene copy, select your skinned mesh and choose a layer and joint.
Click **Select vertices** and verify the heat map and component picking. Test
repeated Select, Q/Y and F9, then Paint and Stop. Inspect the normal HUD and
the Paint info `persistent_display` fields if it is missing. Confirm Undo/Redo
and the original panel renderer after Stop.

The optional native smoke check requests a real VP2 draw and checks the renderer
revision, node UUIDs, mesh history, artist color sets and scene modified flag:

```python
runpy.run_path(
    r"D:/dev/MayaZone/layer_skin_prototype/maya_layer_skin_viewport_smoke.py",
    run_name="__main__"
)
```

It saves a valid pending stroke before taking its baseline and leaves vertex
selection and the heat map active. This host has no Maya runtime; native GPU,
HUD layout, raster colors and picking still need verification there.

## Autodesk references

- [MHUDRender public default constructor](https://help.autodesk.com/cloudhelp/2026/ENU/MAYA-API-REF/cpp_ref/class_m_h_w_render_1_1_m_h_u_d_render.html).
- [Python API 2.0 render override example](https://help.autodesk.com/cloudhelp/2027/CHS/MAYA-API-REF/py_ref/python_2api2_2py2_view_render_override_8py-example.html), `viewRenderHUDOperation.__init__` and `viewRenderPresentTarget.__init__`.

The complete automated results are in `VALIDATION.md` and `LOCAL_TEST_RESULTS.txt`.
