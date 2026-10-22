"""Inside Maya: import maya_constraint_groups_smoke; maya_constraint_groups_smoke.run().

Builds a unique fixture without opening a scene or resetting Undo. Native Maya
is unavailable on the build host; this script is supplied for user validation.
"""
import math
import uuid

import maya.cmds as cmds
import master_rigging_toolkit as toolkit


def run(keep=False):
    prefix = 'rtkConstraintSmoke_' + uuid.uuid4().hex[:8]
    previous_namespace = cmds.namespaceInfo(currentNamespace=True)
    selection = cmds.ls(selection=True, long=True) or []
    members, rigs, checks = set(), [], []
    created_container = None
    fixture_child = None

    def node(identity):
        return toolkit._guide_ik_resolve_uuid(identity)

    def matrix(item):
        return cmds.xform(item, query=True, worldSpace=True, matrix=True)

    def close(a, b):
        return all(abs(x-y) <= 3e-5 * max(1., abs(x), abs(y)) for x, y in zip(a, b))

    def angle(degrees):
        return math.radians(degrees) if cmds.currentUnit(query=True, angle=True) in ('rad', 'radian') else degrees

    def state(rig):
        return toolkit._rig_module_read(node(rig['identity']))[1]

    def record(result):
        result['identity'] = toolkit._guide_ik_uuid(result['module'])
        rigs.append(result)
        members.update(row['uuid'] for row in state(result)['members'])
        return result

    def chain(label, x):
        first = cmds.createNode('joint', name=prefix+':'+label+'_JNT', skipSelect=True)
        cmds.setAttr(first+'.translate', x, 3., 0., type='double3')
        cmds.setAttr(first+'.jointOrient', angle(8), angle(-12), angle(5), type='double3')
        cmds.setAttr(first+'.rotateAxis', angle(2), angle(3), angle(-4), type='double3')
        second = cmds.createNode('joint', name=prefix+':'+label+'_tip_JNT', parent=first, skipSelect=True)
        cmds.connectAttr(first+'.scale', second+'.inverseScale', force=True)
        cmds.setAttr(second+'.translateX', 4.)
        cmds.setAttr(second+'.jointOrient', angle(6), angle(9), angle(-3), type='double3')
        return cmds.ls([first, second], long=True)

    def parent(item):
        return (cmds.listRelatives(item, parent=True, fullPath=True) or [None])[0]

    def solvers(rig):
        return [node(row['uuid']) for row in state(rig)['members'] if row['type'].endswith('Constraint')]

    def input_links(rig):
        # Canonical node UUIDs survive reparenting and possible name collisions.
        result = {}
        for solver in solvers(rig):
            pairs = cmds.listConnections(solver, source=True, destination=False, connections=True, plugs=True) or []
            result[toolkit._guide_ik_uuid(solver)] = sorted(
                (toolkit._rig_module_plug_key(pairs[index]), toolkit._rig_module_plug_key(pairs[index+1]))
                for index in range(0, len(pairs), 2))
        return result

    def pose(joints):
        return {toolkit._guide_ik_uuid(joint): matrix(joint) for joint in joints}

    def same_pose(saved):
        for identity, expected in saved.items():
            assert node(identity) and close(matrix(node(identity)), expected), 'Source pose changed: '+str(node(identity))

    def grouped(rig, shared):
        data = state(rig)
        group = node(data['constraint_group'])
        assert parent(group) == shared, 'Module subgroup is outside constraintNode'
        assert toolkit._guide_ik_uuid(shared) not in {row['uuid'] for row in data['members']}
        assert all(parent(solver) == group for solver in solvers(rig))
        return group

    try:
        assert cmds.undoInfo(query=True, state=True), 'Enable Maya Undo before the fixture.'
        cmds.namespace(setNamespace=':')
        # A pre-existing user group must be reused and retained, including its
        # unrelated children. Do not alter a real scene's container attributes.
        shared = toolkit._constraint_root(False)
        if not shared:
            shared = cmds.group(empty=True, name=':constraintNode')
            created_container = toolkit._guide_ik_uuid(shared)
        shared = cmds.ls(shared, long=True)[0]
        cmds.namespace(addNamespace=prefix)
        fixture_child = cmds.createNode('transform', name=prefix+':unrelatedSibling', parent=shared, skipSelect=True)
        fixture_child = toolkit._guide_ik_uuid(fixture_child)

        left, right, other = chain('arm_L', 8.), chain('arm_R', -8.), chain('other_L', 20.)
        definitions = {toolkit._guide_ik_uuid(joint):
                       (cmds.getAttr(joint+'.jointOrient'), cmds.getAttr(joint+'.rotateAxis'))
                       for joint in left+right+other}
        a = record(toolkit.build_fk_module([left[0]], name=prefix+':Arm_L', include_children=True))
        b = record(toolkit.build_fk_module([other[0]], name=prefix+':Other_L', include_children=True))
        ga, gb = grouped(a, shared), grouped(b, shared)
        assert ga != gb and node(fixture_child)
        checks.append('reuse user container, distinct owned module subgroups and foreign sibling')

        cmds.setAttr(a['controls'][0]+'.rotateY', angle(23))
        cmds.setAttr(a['root']+'.globalScale', 1.3)
        posed = pose(left+other)
        links = input_links(a)
        cmds.setAttr(ga+'.translate', 3., -4., 2., type='double3')
        cmds.setAttr(ga+'.rotate', angle(17), angle(8), angle(-6), type='double3')
        cmds.setAttr(ga+'.scale', 1.5, .8, 1.2, type='double3')
        same_pose(posed)
        assert input_links(a) == links
        checks.append('organizational group transforms leave solver inputs and source poses unchanged')

        # Simulate one constraint from an older layout, then retrofit in place.
        solver_id = toolkit._guide_ik_uuid(solvers(a)[0])
        cmds.parent(node(solver_id), left[0], relative=True)
        same_pose(posed)
        first = toolkit.organize_rig_constraints(a['module'])
        second = toolkit.organize_rig_constraints(a['module'])
        members.update(row['uuid'] for row in state(a)['members'])
        assert first['group'] == second['group'] == ga
        assert first['count'] == second['count'] == 4
        assert input_links(a) == links
        grouped(a, shared)
        same_pose(posed)
        checks.append('organize is idempotent, preserves links and verifies current pose')

        mirrored = record(toolkit.mirror_rig_module(a['module'], search='_L', replace='_R'))
        gm = grouped(mirrored, shared)
        assert gm not in (ga, gb)
        assert {row['uuid'] for row in state(mirrored)['joints']} == {toolkit._guide_ik_uuid(j) for j in right}
        same_pose(posed)
        checks.append('mirror uses existing counterpart joints and a separate constraint subgroup')

        group_identity = state(a)['constraint_group']
        before_remove = pose(left+right+other)
        toolkit.remove_rig_module(a['module'])
        assert not node(a['identity']) and not node(group_identity)
        assert node(b['identity']) and node(mirrored['identity']) and node(fixture_child)
        same_pose(before_remove)
        for identity, expected in definitions.items():
            assert (cmds.getAttr(node(identity)+'.jointOrient'), cmds.getAttr(node(identity)+'.rotateAxis')) == expected
        checks.append('delete one rig keeps all source poses, orientation definitions and other modules')

        cmds.undo()
        assert node(a['identity']) and node(group_identity)
        grouped(a, shared)
        same_pose(before_remove)
        cmds.redo()
        assert not node(a['identity']) and not node(group_identity)
        same_pose(before_remove)
        checks.append('native removal Undo/Redo restores and removes only the selected rig')

        if not keep:
            toolkit.remove_rig_module(node(b['identity']))
            toolkit.remove_rig_module(node(mirrored['identity']))
            same_pose(before_remove)
            assert cmds.objExists(shared) and node(fixture_child)
            checks.append('last module removal retains the user container and unrelated sibling')
        report = {'passed': len(checks), 'checks': checks, 'fixture_namespace': prefix, 'kept': keep}
        print('Constraint groups native smoke:', report)
        return report
    finally:
        if not keep:
            # Only captured module UUIDs and this unique fixture namespace are
            # removed. The shared real scene container and its users are kept.
            toolkit._constraint_delete_owned(members)
            for identity in (fixture_child,):
                item = node(identity) if identity else None
                if item:
                    cmds.delete(item)
            fixture_nodes = cmds.ls(prefix+':*', long=True) or []
            if fixture_nodes:
                cmds.delete(fixture_nodes)
            if cmds.namespace(exists=prefix):
                cmds.namespace(removeNamespace=prefix)
            shared = node(created_container) if created_container else None
            if shared and not (cmds.listRelatives(shared, children=True) or []):
                cmds.delete(shared)
        cmds.namespace(setNamespace=previous_namespace)
        restored = [item for item in selection if cmds.objExists(item)]
        cmds.select(restored, replace=True) if restored else cmds.select(clear=True)
