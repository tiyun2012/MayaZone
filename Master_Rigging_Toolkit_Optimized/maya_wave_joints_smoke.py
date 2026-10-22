"""Run in Maya 2024+: import maya_wave_joints_smoke; maya_wave_joints_smoke.run().

Creates a unique fixture without opening a scene or clearing Undo. Requires the
native sin node. Native execution is pending on the build host.
"""
import math
import uuid

import maya.cmds as cmds
import maya.api.OpenMaya as om
import wave_joints as wave


def run(keep=False):
    prefix = 'rtkWaveSmoke_'+uuid.uuid4().hex[:8]
    previous_namespace = cmds.namespaceInfo(currentNamespace=True)
    previous_units = {key: cmds.currentUnit(query=True, **{key: True}) for key in ('linear', 'angle')}
    previous_time = cmds.currentTime(query=True)
    selection = cmds.ls(selection=True, long=True) or []
    members, checks = set(), []
    system_id = None

    def near(a, b):
        assert abs(a-b) <= 3e-5*max(1., abs(a), abs(b)), (a, b)

    def pose(joints):
        return [cmds.xform(joint, query=True, worldSpace=True, matrix=True) for joint in joints]

    def same_pose(joints, expected):
        for actual, saved in zip(pose(joints), expected):
            for a, b in zip(actual, saved):
                near(a, b)

    def samples(joints):
        return [[cmds.getAttr(joint+'.'+wave.CHANNELS[channel][0])*
                 (wave._linear_factor() if channel.startswith('t') else wave._angle_factor())
                 for channel in ('ty', 'rz')] for joint in joints]

    try:
        assert cmds.undoInfo(query=True, state=True), 'Enable Maya Undo before testing.'
        assert 'sin' in cmds.allNodeTypes(), 'This test requires Maya native sin.'
        cmds.namespace(setNamespace=':'); cmds.namespace(addNamespace=prefix)
        driver = cmds.circle(name=prefix+':wave_ctrl', constructionHistory=False)[0]
        joints = []
        for index in range(4):
            kwargs = {'parent': joints[-1]} if joints else {}
            joint = cmds.createNode('joint', name=prefix+':wave_{:02d}_JNT'.format(index+1), skipSelect=True, **kwargs)
            if joints:
                cmds.connectAttr(joints[-1]+'.scale', joint+'.inverseScale', force=True)
                cmds.setAttr(joint+'.translateX', 3.)
            cmds.setAttr(joint+'.jointOrient', 7.*math.pi/180./wave._angle_factor(), -4.*math.pi/180./wave._angle_factor(), 0., type='double3')
            cmds.setAttr(joint+'.rotateAxis', 2.*math.pi/180./wave._angle_factor(), 0., 0., type='double3')
            cmds.setAttr(joint+'.rotateZ', 5.*math.pi/180./wave._angle_factor())
            joints.append(cmds.ls(joint, long=True)[0])
        initial = pose(joints)
        definitions = [(cmds.getAttr(j+'.jointOrient'), cmds.getAttr(j+'.rotateAxis')) for j in joints]
        result = wave.build(driver, joints, channels={'ty': {}, 'rz': {'gain': .5, 'phase': 90.}},
                            settings={'frequency': .25, 'translation_amplitude': 2., 'rotation_amplitude': 20.})
        meta, state = wave.read(result['system']); system_id = wave.identity(meta)
        members.update(row['uuid'] for row in state['members']); members.add(system_id)
        same_pose(joints, initial)
        assert not any(cmds.getAttr(driver+'.'+attribute, lock=True) for attribute in state['attributes'].values())
        checks.append('neutral build and unlocked driver attributes')

        wave.update(meta, settings={'envelope': 1.})
        for offset in (0., 35., 90., -120., 360.):
            cmds.setAttr(driver+'.waveOffset', offset)
            for index, joint in enumerate(joints):
                phase = offset+90.*index/3.
                near(cmds.getAttr(joint+'.translateY'), 2.*math.sin(math.radians(phase)))
                expected = 5.+10.*math.sin(math.radians(phase+90.))
                near(cmds.getAttr(joint+'.rotateZ')*wave._angle_factor(), math.radians(expected))
        checks.append('native sine local translation and rotation samples with independent phase')

        # Falloff multiplies only the wave delta. Higher power broadens its peak.
        for power in (0., 1., 4.):
            wave.update(meta, settings={'offset': 90., 'frequency': 0.,
                                        'falloff_position': .5, 'falloff_power': power})
            for index, joint in enumerate(joints):
                expected = 1. if power == 0. else 1.-abs(index/3.-.5)**power
                near(cmds.getAttr(joint+'.translateY'), 2.*expected)
                # Axis phase 90 makes the rotation contribution zero here.
                near(cmds.getAttr(joint+'.rotateZ')*wave._angle_factor(), math.radians(5.))
                item = state['joints'][index]['falloff']
                near(cmds.getAttr(wave.resolve(item['node'])+'.'+item['attribute']), expected)
        wave.update(meta, settings={'falloff_position': 1./3., 'falloff_power': 2.})
        item = state['joints'][1]['falloff']
        near(cmds.getAttr(wave.resolve(item['node'])+'.'+item['attribute']), 1.)
        wave.update(meta, settings={'falloff_power': 0.})
        checks.append('falloff peak, linear/broad power and zero-power bypass retain the local base')

        physical = samples(joints)
        cmds.currentUnit(linear='m', angle='rad')
        for actual, expected in zip(samples(joints), physical):
            for a, b in zip(actual, expected):
                near(a, b)
        near(wave.current_settings(meta)['settings']['rotation_amplitude'], 20.)
        cmds.currentUnit(**previous_units)
        checks.append('physical motion retained when Maya linear and angular UI units change')

        wave.update(meta, joints=list(reversed(joints)), spacing='distance', settings={'root_weight': 0., 'tip_weight': 1.})
        assert wave.current_settings(meta)['joints'] == list(reversed(joints))
        wave.update(meta, settings={'envelope': 0.})
        same_pose(joints, initial)
        checks.append('order and cached rest-distance updates; muting restores the saved local pose')

        wave.update(meta, settings={'envelope': 1., 'frequency': 0., 'root_weight': 1., 'tip_weight': 1.,
                                    'auto_time': True, 'speed': .7, 'offset': 0.})
        cmds.currentTime(previous_time+7., edit=True)
        seconds = om.MTime(cmds.currentTime(query=True), om.MTime.uiUnit()).asUnits(om.MTime.kSeconds)
        near(cmds.getAttr(joints[0]+'.translateY'), 2.*math.sin(math.tau*.7*seconds))
        checks.append('automatic motion uses native scene time in seconds')

        # A normal time animation curve remains outside wave ownership.
        wave.update(meta, settings={'auto_time': False})
        cmds.setKeyframe(driver, attribute='waveOffset', time=previous_time, value=20.)
        cmds.setKeyframe(driver, attribute='waveOffset', time=previous_time+10., value=130.)
        curves = cmds.listConnections(driver+'.waveOffset', source=True, destination=False) or []
        curve_ids = [wave.identity(curve) for curve in curves]
        members.update(curve_ids)  # Fixture cleanup only; wave.remove never owns these curves.
        wave.update(meta, joints=joints)  # Does not set the connected Offset attribute.
        posed = pose(joints)
        renamed = cmds.rename(meta, prefix+':renamed_wave_META')
        wave.remove(renamed)
        same_pose(joints, posed)
        assert cmds.objExists(driver+'.waveOffset') and all(wave.resolve(uid) for uid in curve_ids)
        assert not wave.resolve(system_id)
        for joint, definition in zip(joints, definitions):
            assert (cmds.getAttr(joint+'.jointOrient'), cmds.getAttr(joint+'.rotateAxis')) == definition
        checks.append('renamed setup removal retains pose, orientation and driver animation')

        cmds.undo(); assert wave.resolve(system_id); wave.read(wave.resolve(system_id)); same_pose(joints, posed)
        cmds.redo(); assert not wave.resolve(system_id); same_pose(joints, posed)
        checks.append('native removal Undo and Redo')
        if keep:
            cmds.undo()  # Leave the built native graph for inspection.
        report = {'passed': len(checks), 'checks': checks, 'fixture_namespace': prefix, 'kept': keep}
        print('waveJoints native smoke:', report)
        return report
    finally:
        try:
            cmds.currentUnit(**previous_units)
            cmds.currentTime(previous_time, edit=True)
            if not keep:
                generated = [node for uid in members if (node := wave.resolve(uid))]
                if generated:
                    cmds.delete(generated)
                nodes = cmds.ls(prefix+':*', long=True) or []
                if nodes:
                    cmds.delete(nodes)
                if cmds.namespace(exists=prefix):
                    cmds.namespace(removeNamespace=prefix)
        finally:
            cmds.namespace(setNamespace=previous_namespace)
            restored = [node for node in selection if cmds.objExists(node)]
            cmds.select(restored, replace=True) if restored else cmds.select(clear=True)
