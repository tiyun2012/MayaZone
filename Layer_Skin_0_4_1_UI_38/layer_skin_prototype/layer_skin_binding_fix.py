"""Apply the mesh-geometry binding correction to a running 0.4.0 session.

Run this file with runpy.run_path(..., run_name='__main__'). Keep it beside the
updated layer_skin_artisan.py. This replaces only the transient buffer factory;
it does not reload/unload the registered command or reset Maya's Undo history.
The complete 0.4.1 plug-in already includes the correction on a fresh launch.
"""
import importlib.util
import json
import os
import sys
import types

RUNTIME = '_rtk_layer_skin_geometry_binding_041'


def _runtime():
    module = sys.modules.get(RUNTIME)
    if module is not None:
        if getattr(module, 'BINDING_REVISION', None) != 'mesh_geometry_1':
            raise RuntimeError('Another binding repair is loaded. Use a fresh Maya session with the complete folder.')
        return module
    location = globals().get('__file__') or _runtime.__code__.co_filename
    path = os.path.join(os.path.dirname(os.path.abspath(location)), 'layer_skin_artisan.py')
    spec = importlib.util.spec_from_file_location(RUNTIME, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if getattr(module, 'BINDING_REVISION', None) != 'mesh_geometry_1':
        raise RuntimeError('The repair requires the updated layer_skin_artisan.py beside this file.')
    sys.modules[RUNTIME] = module
    return module


def _window():
    try:
        from PySide6 import QtWidgets
    except ImportError:
        from PySide2 import QtWidgets
    app = QtWidgets.QApplication.instance()
    windows = [widget for widget in app.topLevelWidgets()
               if widget.objectName() == 'rtkLayerSkinPrototypeWindow' and widget.isVisible()
               and hasattr(widget, 'session') and not getattr(widget, '_closed', False)] if app else []
    if len(windows) != 1:
        raise RuntimeError('Keep one Layer Skin window open, choose its layer/joint and click Paint first.')
    return windows[0]


def apply(window=None):
    window = window if window is not None else _window()
    session = window.session
    version = str(window.api.VERSION)
    if version not in ('0.4.0', '0.4.1'):
        raise RuntimeError('This repair supports Layer Skin 0.4.0/0.4.1; the open window is '+version)
    if session.closed or not session.target or not session.layer:
        raise RuntimeError('Choose the layer and joint, then click Paint before running the repair.')
    # Commit valid pending data to its original scope before replacing resources.
    session.flush_pending('geometry_binding_repair')
    scope = dict(target=session.target, layer=session.layer, joint=session.joint,
                 mode=session.mode, readonly=session.readonly, joint_path=session.joint_path,
                 value=window.value.value(), radius=window.brush_radius.value(),
                 opacity=window.brush_opacity.value())
    old_helper = None
    previous_get = None
    previous_marker = None
    if version == '0.4.0':
        old_helper = sys.modules.get('_rtk_layer_skin_artisan_040')
        if old_helper is None:
            raise RuntimeError('Cannot find the active 0.4.0 buffer module. Click Paint again before running this repair.')
        runtime = _runtime()
        previous_get = old_helper.get_buffer
        previous_marker = getattr(old_helper, '_geometry_binding_patch', None)

        def bound_buffer(api):
            bridge = sys.modules.get('_rtk_layer_skin_paint_040')
            current = getattr(bridge, 'session', None)
            if current is None or current.closed or current.api is not api or not current.target:
                raise RuntimeError('No current Layer Skin mesh is available for the geometry binding.')
            return runtime.get_buffer(api, current.target)

        old_helper.get_buffer = bound_buffer
        old_helper._geometry_binding_patch = types.SimpleNamespace(runtime=runtime, revision=runtime.BINDING_REVISION)
    try:
        session.start(**scope)
        sources = session.buffer.geometry_sources()
        if sources != [session.target+'.outMesh']:
            # MPlug.name can return a short node name. Compare dependency nodes
            # through the API rather than rejecting the equivalent short path.
            api = session.api
            source = session.buffer.surface.connectedTo(True, False)
            if len(source) != 1 or source[0].node() != api.obj(session.target):
                raise RuntimeError('The working array is not linked to the loaded mesh.')
        window.update_display_range()
        window.message('Mesh binding repaired. Paint a patch, then switch joints and return.')
        report = dict(registered_backend=version, binding='mesh_geometry_1', mesh=session.target,
                      paint_array=session.buffer.attribute(), geometry_sources=sources,
                      vertex_values=len(session.buffer.read()), active=session.active)
        print('Layer Skin geometry binding repair\n'+json.dumps(report, indent=2))
        return report
    except Exception:
        if old_helper is not None:
            old_helper.get_buffer = previous_get
            if previous_marker is None:
                old_helper.__dict__.pop('_geometry_binding_patch', None)
            else:
                old_helper._geometry_binding_patch = previous_marker
        session.stop()
        raise


if __name__ == '__main__':
    apply()
