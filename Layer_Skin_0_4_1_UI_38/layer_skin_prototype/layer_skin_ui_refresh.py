"""Open or refresh authoring UI; retain the loaded command, buffers and Undo.

Run with runpy.run_path, whether or not a Layer Skin window is already open.
An absent window is opened by this folder's path/version-aware launcher first.
Valid pending strokes in an existing window are saved before replacement. The
new window keeps its mesh/layer/joint and controls; click Paint to resume.
"""
import importlib.util
import os
import sys


class RefreshedAPI:
    """Forward live API state and the refreshed core/session implementation."""
    def __init__(self,source,session_module,owner):
        self._layer_skin_source_api=getattr(source,'_layer_skin_source_api',source)
        self._layer_skin_command_owner=owner
        self._session_module=session_module
    def __getattr__(self,name):
        if name=='core':return self._layer_skin_command_owner.get('core',self._layer_skin_source_api.core)
        if name in ('context','metadata','same','state_hash') and callable(self._layer_skin_command_owner.get(name)):
            return self._layer_skin_command_owner[name]
        if name=='commit_paint' and self._layer_skin_command_owner.get('_layer_skin_paint_runtime') is not None:
            return lambda data,scope:self._layer_skin_command_owner['sibling']('layer_skin_paint_commit').commit(self._layer_skin_command_owner,data,scope)
        if name=='commit_edit' and self._layer_skin_command_owner.get('_layer_skin_paint_runtime') is not None:
            return lambda action,data,scope:self._layer_skin_command_owner['sibling']('layer_skin_paint_commit').commit(self._layer_skin_command_owner,data,scope,action)
        return getattr(self._layer_skin_source_api,name)
    def make_session(self):
        return self._session_module.Session(self)


def current_window():
    try:
        from PySide6 import QtWidgets
        import shiboken6 as shiboken
    except ImportError:
        from PySide2 import QtWidgets
        import shiboken2 as shiboken
    app = QtWidgets.QApplication.instance()
    windows = []
    # Include hidden and embedded windows. A visible/top-level-only search can
    # miss a live editor and accidentally create another authoring session.
    for window in app.allWidgets() if app else []:
        try:
            if (shiboken.isValid(window)
                    and window.objectName() == 'rtkLayerSkinPrototypeWindow'
                    and hasattr(window, 'api') and hasattr(window, 'session')
                    and not getattr(window, '_closed', False)
                    and not getattr(window.session, 'closed', False)):
                windows.append(window)
        except RuntimeError:
            continue  # A deleted Qt wrapper is not an open editor.
    if len(windows) > 1:
        raise RuntimeError('More than one Layer Skin window is open. Close the extra windows, then run the UI refresh again.')
    return windows[0] if windows else None


def _source_folder():
    location = globals().get('__file__') or refresh.__code__.co_filename
    return os.path.dirname(os.path.abspath(location))


def _open_current_folder():
    """Use the actual sibling launcher, including its registration guards."""
    folder = _source_folder()
    path = os.path.join(folder, 'layer_skin_launch.py')
    if not os.path.isfile(path):
        raise RuntimeError('Missing layer_skin_launch.py. Replace the complete layer_skin_prototype folder.')
    spec = importlib.util.spec_from_file_location('_rtk_layer_skin_refresh_launcher_041', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.open_ui(folder=folder)


def _refresh_window(window=None):
    if window is not None:
        return window
    found = current_window()
    if found is None:
        _open_current_folder()
        found = current_window()
        if found is None:
            raise RuntimeError('Layer Skin launched but no live editor was found. Check the launcher output and extract the complete folder.')
    return found


def refresh(window=None):
    window = _refresh_window(window)
    original_api = window.api
    if original_api.VERSION != '0.4.1':
        raise RuntimeError('This authoring update requires the 0.4.1 API. Open the complete 0.4.1 folder in a fresh Maya session.')
    path = os.path.join(_source_folder(), 'layer_skin_ui.py')
    spec = importlib.util.spec_from_file_location('_rtk_layer_skin_ui_refresh_38', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    session_path = os.path.join(os.path.dirname(path), 'layer_skin_session.py')
    session_spec = importlib.util.spec_from_file_location('_rtk_layer_skin_session_memory_20', session_path)
    session_module = importlib.util.module_from_spec(session_spec)
    session_spec.loader.exec_module(session_module)
    joint_spec=importlib.util.spec_from_file_location('_rtk_layer_skin_joint_view_21',os.path.join(os.path.dirname(path),'layer_skin_joint_view.py'))
    joint_module=importlib.util.module_from_spec(joint_spec);joint_spec.loader.exec_module(joint_module)
    core_spec=importlib.util.spec_from_file_location('_rtk_layer_skin_core_locks_18',os.path.join(os.path.dirname(path),'layer_skin_core.py'))
    core_module=importlib.util.module_from_spec(core_spec);core_spec.loader.exec_module(core_module)
    memory_spec=importlib.util.spec_from_file_location('_rtk_layer_skin_memory_20',os.path.join(os.path.dirname(path),'layer_skin_memory.py'))
    memory_module=importlib.util.module_from_spec(memory_spec);memory_spec.loader.exec_module(memory_module)
    assignment_spec = importlib.util.spec_from_file_location('_rtk_layer_skin_assignment_041',os.path.join(os.path.dirname(path),'layer_skin_assignment.py'))
    assignment_module = importlib.util.module_from_spec(assignment_spec)
    assignment_spec.loader.exec_module(assignment_module)
    assignment_scene_spec=importlib.util.spec_from_file_location('_rtk_layer_skin_assignment_hierarchy_27',os.path.join(os.path.dirname(path),'layer_skin_assignment_scene.py'))
    assignment_scene_module=importlib.util.module_from_spec(assignment_scene_spec);assignment_scene_spec.loader.exec_module(assignment_scene_module)
    relax_spec=importlib.util.spec_from_file_location('_rtk_layer_skin_relax_041',os.path.join(os.path.dirname(path),'layer_skin_relax.py'))
    relax_module=importlib.util.module_from_spec(relax_spec);relax_spec.loader.exec_module(relax_module)
    io_spec=importlib.util.spec_from_file_location('_rtk_layer_skin_io_backend_9',os.path.join(os.path.dirname(path),'layer_skin_io_backend.py'))
    io_module=importlib.util.module_from_spec(io_spec);io_spec.loader.exec_module(io_module)
    operations_spec=importlib.util.spec_from_file_location('_rtk_layer_skin_operations_13',os.path.join(os.path.dirname(path),'layer_skin_operations.py'))
    operations_module=importlib.util.module_from_spec(operations_spec);operations_spec.loader.exec_module(operations_module)
    performance_spec=importlib.util.spec_from_file_location('_rtk_layer_skin_performance_38',os.path.join(os.path.dirname(path),'layer_skin_performance.py'))
    performance_module=importlib.util.module_from_spec(performance_spec);performance_spec.loader.exec_module(performance_module)
    commit_spec=importlib.util.spec_from_file_location('_rtk_layer_skin_paint_commit_37',os.path.join(os.path.dirname(path),'layer_skin_paint_commit.py'))
    commit_module=importlib.util.module_from_spec(commit_spec);commit_spec.loader.exec_module(commit_module)
    # Keep the registered command's API/buffer factories. Only the replacement
    # dialog receives a new Session; existing Undo command objects stay intact.
    factory = getattr(original_api.make_session, '__func__', original_api.make_session)
    owner = getattr(original_api,'_layer_skin_command_owner',getattr(factory, '__globals__', {}))
    api = RefreshedAPI(original_api,session_module,owner)
    # Validate/load the new UI before closing the old dialog. Its new Session
    # remains inactive until showEvent, after the previous dialog is closed.
    target, layer, joint = window.target.text(), window.selected_id(), window._active_joint_path
    geometry = window.saveGeometry()
    window.sync_brush_settings()
    operation=getattr(window,'_brush_operation','replace')
    # Older UIs hid a forced Gaussian stamp. Adopt precise Solid once; later
    # refreshes keep the explicit falloff choice and native tool-setting edits.
    profile=window.brush_falloff.currentData() if hasattr(window,'brush_falloff') else 'solid'
    values = dict(value=window.value.value(), radius=window.brush_radius.value(),
                  opacity=window.brush_opacity.value(), mode=window.paint_mode.currentIndex(),
                  pin=window.pin.isChecked(), whole=window.whole.isChecked())
    controls={name:getattr(window,name).value() for name in ('relax_iterations','relax_strength','relax_max_new','brush_passes','add_value','scale_value') if hasattr(window,name)}
    checks={name:getattr(window,name).isChecked() for name in ('preserve_coverage','keep_paint') if hasattr(window,name)}
    # Earlier UIs defaulted to fixed coverage, which hides smoothing on a
    # single-joint painted patch. Adopt the visible-smoothing default once;
    # subsequent UI 11 refreshes keep the user's explicit checkbox choice.
    if getattr(window,'relax_brush_revision',0)<11:checks['preserve_coverage']=False
    if window.session.active and original_api.cmds.currentCtx()==original_api.paint_context:
        for flag,key in (('radius','radius'),('opacity','opacity')):
            if flag=='opacity' and window.session.readonly:continue
            native=original_api.cmds.artUserPaintCtx(original_api.paint_context,query=True,**{flag:True})
            if native is not None:values[key]=float(native)
    display=window.weight_display.currentIndex() if hasattr(window,'weight_display') else 0
    active_tab=window.tabs.currentIndex() if hasattr(window,'tabs') else 0
    utilities_state=window.utilities.capture_ui() if hasattr(window,'utilities') else None
    previous_search=getattr(getattr(window,'browser',None),'search',None)
    joint_search=previous_search.text() if previous_search is not None else ''
    if not window.stop_paint():
        raise RuntimeError('The UI was kept open because a pending paint stroke could not be saved.')
    replacement = module.LayerUI(api, window.parentWidget())
    replacement.setWindowFlags(window.windowFlags())
    replacement.target.setText(target)
    replacement.value.setValue(values['value'])
    replacement.brush_radius.setValue(values['radius'])
    replacement.brush_opacity.setValue(values['opacity'])
    replacement.brush_falloff.setCurrentIndex(replacement.brush_falloff.findData(profile))
    replacement.paint_mode.setCurrentIndex(values['mode'])
    replacement.pin.setChecked(values['pin'])
    replacement.whole.setChecked(values['whole'])
    replacement.weight_display.setCurrentIndex(display)
    for name,value in controls.items():getattr(replacement,name).setValue(value)
    for name,value in checks.items():getattr(replacement,name).setChecked(value)
    replacement.operation_radios[operation].setChecked(True)
    if utilities_state is not None:replacement.utilities.restore_ui(utilities_state)
    module._dialog = replacement
    sys.modules[spec.name] = module
    sys.modules[session_spec.name] = session_module
    # editor_api.make_session is a closure owned by the loaded command's module.
    # Replace UI/session/assignment caches; registered code and Undo stay live.
    if owner.get('VERSION') == api.VERSION and owner.get('WINDOW') == api.WINDOW and '_ui_module' in owner:
        owner['_ui_module'] = module
        # Command objects use their original class and captured native arrays.
        # The new core accepts the same schema and retains the same composite;
        # only layer editing/validation adds the optional lock settings.
        owner['core']=core_module
        memory_module.install(owner)
        if isinstance(owner.get('_modules'), dict):
            # Other helper APIs may still hold the shared assignment module.
            # Replace its transient cache too, so they use the new generator;
            # saved layer rows and native Undo objects do not depend on it.
            for previous in (sys.modules.get(assignment_spec.name),owner['_modules'].get('layer_skin_assignment')):
                if previous is not None and hasattr(previous,'CACHE'):previous.CACHE=assignment_module.CACHE
            owner['_modules']['layer_skin_session'] = session_module
            owner['_modules']['layer_skin_memory'] = memory_module
            owner['_modules']['layer_skin_performance'] = performance_module
            owner['_modules']['layer_skin_paint_commit'] = commit_module
            owner['_modules']['layer_skin_joint_view'] = joint_module
            sys.modules[joint_spec.name] = joint_module
            owner['_modules']['layer_skin_assignment'] = assignment_module
            sys.modules[assignment_spec.name] = assignment_module
            owner['_modules']['layer_skin_assignment_scene']=assignment_scene_module
            sys.modules[assignment_scene_spec.name]=assignment_scene_module
            assignment_scene_module.install(owner)
            owner['_modules']['layer_skin_relax']=relax_module
            sys.modules[relax_spec.name]=relax_module
            relax_module.install(owner)
            owner['_modules']['layer_skin_io_backend']=io_module;io_module.install(owner)
            owner['_modules']['layer_skin_operations']=operations_module;operations_module.install(owner)
            sys.modules[operations_spec.name]=operations_module
        performance_module.install(owner)
        commit_module.install(owner)
    parent = window.parentWidget()
    if not window.isWindow() and parent is not None and parent.layout() is not None:
        parent.layout().replaceWidget(window, replacement)
    window.close()
    replacement.show()
    ready = not target or replacement.refresh(layer)
    if ready and joint and target:
        replacement.choose_joint(joint)
    search=getattr(getattr(replacement,'browser',None),'search',None)
    if search is not None:search.setText(joint_search)
    replacement.restoreGeometry(geometry)
    replacement.tabs.setCurrentIndex(active_tab)
    replacement.raise_()
    replacement.activateWindow()
    if ready:
        replacement.message('UI 38 · Open / refresh ready. Click Paint to resume. Preview import again before writing.')
    # Redraw after closing an older controller's Qt overlay, including when it
    # left a stale black frame. This does not change renderer or panel settings.
    redraw=getattr(api.cmds,'refresh',None)
    if callable(redraw):
        try:redraw(force=True)
        except RuntimeError as exc:api.cmds.warning('Layer Skin UI refreshed; viewport redraw failed: '+str(exc))
    return replacement


if __name__ == '__main__':
    refresh()
