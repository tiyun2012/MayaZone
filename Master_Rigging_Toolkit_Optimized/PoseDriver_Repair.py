"""Select one PoseDriver cone, setup group or source joint, then run this file.
Reads the updated toolkit from disk without reloading an existing Qt window.
"""
import importlib.util
import os
import maya.cmds as cmds


def repair_selected_pose_driver():
    candidates=[repair_selected_pose_driver.__code__.co_filename,globals().get('__file__')]
    try:
        import master_rigging_toolkit as loaded
        candidates.append(getattr(loaded,'__file__',None))
    except ImportError:pass
    filename=None
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            path=os.path.join(os.path.dirname(os.path.abspath(candidate)),'master_rigging_toolkit.py')
            if os.path.isfile(path):filename=path;break
    if filename is None:raise RuntimeError('Keep this repair script beside the updated master_rigging_toolkit.py, or add its folder to sys.path.')
    spec=importlib.util.spec_from_file_location('_rtk_pose_division_repair_228',filename)
    toolkit=importlib.util.module_from_spec(spec);spec.loader.exec_module(toolkit)
    if not hasattr(toolkit,'_pd_build_normalization_divisor'):
        raise RuntimeError('Older toolkit at '+filename+'. Replace master_rigging_toolkit.py with v2.28.')
    selected=cmds.ls(selection=True,long=True,objectsOnly=True) or []
    identities=set(cmds.ls(selected,uuid=True) or []) if selected else set()
    matches=[]
    for group in toolkit.list_pose_drivers():
        try:_,state=toolkit._pd_read(group)
        except ValueError:
            if toolkit._pd_uuid(group) in identities:raise
            continue
        if identities & (set(state['members'])|{state['joint']}):matches.append(group)
    if len(matches)!=1:raise ValueError('Select the cone, setup group or source joint of exactly one PoseDriver, then run again.')
    result=toolkit.repair_pose_driver_division(matches[0])
    print('PoseDriver v2.28: {} · {} pose(s) protected. {} Source: {}'.format(matches[0],result['normalizers'],
          'Upgrade applied; Undo restores the previous graph.' if result['changed'] else 'Already upgraded.',filename))
    return result


if __name__=='__main__':repair_selected_pose_driver()
