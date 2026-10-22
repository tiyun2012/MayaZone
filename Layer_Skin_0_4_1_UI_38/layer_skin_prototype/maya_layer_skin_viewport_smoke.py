"""Interactive Maya selection-view smoke check. Requires a loaded Layer Skin window.

Run in a working scene copy after saving any desired paint stroke. This selects
vertices on the loaded mesh and leaves its heat map displayed. No skin weights
are authored by this check. A real VP2 frame is requested and its callback must
execute. Correct raster colors/occlusion still need visual inspection.
"""
import importlib.util
import json
import os


def run():
    path=globals().get('__file__') or run.__code__.co_filename
    spec=importlib.util.spec_from_file_location('_rtk_ls_view_smoke_refresh',os.path.join(os.path.dirname(os.path.abspath(path)),'layer_skin_ui_refresh.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    window=module.current_window()
    if window is None or not window.target.text():raise RuntimeError('Open Layer Skin and load one skinned mesh first.')
    if not window.save_pending_paint():raise RuntimeError('Finish or discard the pending stroke before checking the view.')
    api=window.api;cmds=api.cmds;om=api.om;mesh=window.target.text()
    def snapshot():
        fn=om.MFnMesh(api.obj(mesh))
        return dict(nodes=sorted(cmds.ls(uuid=True) or []),history=cmds.listHistory(mesh,pruneDagObjects=True) or [],
                    color_sets=fn.getColorSetNames(),modified=cmds.file(query=True,modified=True))
    before=snapshot()
    if not window.select_vertices():raise RuntimeError(window.status.text())
    window.session.helper('layer_skin_brush_view').QtWidgets.QApplication.processEvents()
    cmds.refresh(force=True)
    after=snapshot();report=window.session.preview.report()
    for key in before:
        if before[key]!=after[key]:raise AssertionError('Selection preview changed '+key)
    if not report.get('visible'):raise AssertionError('The weight viewport did not attach: '+json.dumps(report))
    if report.get('renderer_revision',0)<35:raise AssertionError('The old renderer is still loaded. Replace the complete folder and run layer_skin_ui_refresh.py.')
    if report.get('last_draw_error'):raise AssertionError(report['last_draw_error'])
    if report.get('draws',0)<1:raise AssertionError('No native VP2 heat-map draw callback ran. Check viewport renderer and Maya errors.')
    if report.get('scene_nodes_created')!=0:raise AssertionError('The preview reported scene-node creation.')
    print(window.windowTitle()+' native view check\n'+json.dumps(report,indent=2))
    return report


if __name__=='__main__':run()
