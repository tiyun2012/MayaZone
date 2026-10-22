"""Run inside Maya after reload: maya_rig_connections_smoke.run().

Unique fixture only; never opens a new scene or resets the Undo queue.
"""
import math
import uuid
import maya.cmds as cmds
import master_rigging_toolkit as toolkit


def run(keep=False):
    prefix='rtkConnectionsSmoke_'+uuid.uuid4().hex[:8]
    namespace=cmds.namespaceInfo(currentNamespace=True)
    selection=cmds.ls(selection=True,long=True) or []
    rigs=[];members=set();checks=[]
    node=toolkit._rig_module_node
    def state(rig):return toolkit._rig_module_read(rig['module'])[1]
    def world(identity):return cmds.xform(node(identity),query=True,worldSpace=True,matrix=True)
    def close(a,b):return len(a)==len(b) and all(abs(x-y)<3e-5*max(1,abs(x),abs(y)) for x,y in zip(a,b))
    def angle(value):return math.radians(value) if cmds.currentUnit(query=True,angle=True) in ('rad','radian') else value
    def capture(rig):
        rigs.append(rig);members.update(row['uuid'] for row in state(rig)['members']);return rig
    def joint(label,point,parent=None):
        result=cmds.createNode('joint',name=prefix+':'+label,skipSelect=True,**({'parent':node(parent)} if parent else {}))
        identity=toolkit._guide_ik_uuid(result)
        cmds.setAttr(result+'.jointOrient',angle(5),angle(-8),angle(11),type='double3')
        cmds.setAttr(result+'.rotateAxis',angle(2),angle(3),angle(-4),type='double3')
        if parent:cmds.connectAttr(node(parent)+'.scale',result+'.inverseScale',force=True)
        cmds.xform(result,worldSpace=True,translation=point)
        return identity
    def pose(identities):return {identity:world(identity) for identity in identities}
    def same_pose(saved):
        for identity,matrix in saved.items():assert close(world(identity),matrix),node(identity)
    def outputs_match(rig):
        for row in toolkit.list_rig_outputs(rig['module']):
            if row['joint']:assert close(world(row['uuid']),cmds.xform(row['joint'],query=True,worldSpace=True,matrix=True)),row
    try:
        cmds.namespace(setNamespace=':');cmds.namespace(addNamespace=prefix)
        root_joint=joint('skeleton_JNT',(0,0,0))
        spine=joint('spine_JNT',(0,4,0),root_joint)
        neck=joint('neck_JNT',(0,8,0),spine)
        head=joint('head_JNT',(0,10,0),neck)
        chain=[root_joint,spine,neck,head]
        definitions={identity:(cmds.getAttr(node(identity)+'.jointOrient'),cmds.getAttr(node(identity)+'.rotateAxis'),
                              tuple(toolkit._guide_ik_uuid(parent) for parent in cmds.listRelatives(node(identity),parent=True,fullPath=True) or [])) for identity in chain}
        root=capture(toolkit.build_root_module(root_joint=node(root_joint),name=prefix+'_Character',control_size=2,
            controller_names={'root':prefix+':Main_ctrl','placement':prefix+':Root_ctrl'}))
        body=capture(toolkit.build_fk_module([node(spine)],name=prefix+'_Body'))
        upper=capture(toolkit.build_fk_module([node(neck),node(head)],name=prefix+'_Neck'))
        root_state=state(root)
        for rig in (root,body,upper):
            data=state(rig);ctrl=node(data['start_controller'])
            assert toolkit._rig_module_link(ctrl+'.rtkModuleStartJoint')==[data['start_joint']]
        checks.append('all module starts are linked to their root controllers by message')
        report=toolkit.scan_rig_connections(root['module'])
        expected={state(body)['meta']:root_state['meta'],state(upper)['meta']:state(body)['meta']}
        assert {row['module']:row['parent_module'] for row in report['rows']}==expected
        plans=[dict(module=row['module'],output=row['output'],method='parent_constraint',follow_scale=True) for row in report['rows'] if row['ready']]
        before=pose(chain)
        # Rename after planning; applying must resolve the stored UUIDs again.
        cmds.rename(node(spine),prefix+':renamedSpineInput')
        cmds.rename(node(state(body)['start_controller']),prefix+':renamedBodyRootCtrl')
        socket=next(row['output'] for row in report['rows'] if row['module']==state(upper)['meta'])
        cmds.rename(node(socket),prefix+':renamedBodyOutput')
        toolkit.connect_rig_modules(plans);same_pose(before)
        assert all(row['status']=='connected' for row in toolkit.scan_rig_connections(root['module'])['rows'])
        checks.append('hierarchy suggestions and batch apply survive joint/controller/output renames')
        cmds.undo();same_pose(before)
        assert all(not state(rig).get('attachment') for rig in (body,upper))
        cmds.redo();same_pose(before)
        assert all(state(rig)['attachment']['method']=='parent_constraint' for rig in (body,upper))
        checks.append('native connection plan is one Undo/Redo action')
        root_ctrl=node(state(root)['roles']['placement']);main=node(state(root)['root'])
        bind=pose(chain);cmds.setAttr(main+'.globalScale',1.7)
        for identity,matrix in bind.items():assert close(world(identity)[12:15],[v*1.7 for v in matrix[12:15]])
        cmds.setAttr(root_ctrl+'.translateX',3);cmds.setAttr(root_ctrl+'.rotateY',angle(20))
        for rig in (root,body,upper):outputs_match(rig)
        checks.append('native matched-target constraints carry global scale once through nested modules')
        try:toolkit.remove_rig_module(body['module'])
        except ValueError as exc:assert 'Detach child module' in str(exc)
        else:raise AssertionError('Parent deletion accepted an attached child')
        before=pose(chain);toolkit.detach_rig_module(upper['module']);same_pose(before)
        cmds.undo();same_pose(before);assert state(upper)['attachment']
        cmds.redo();same_pose(before);assert not state(upper).get('attachment')
        checks.append('posed native detach Undo/Redo keeps controller and joint frames')
        before=pose(chain);toolkit.remove_rig_module(upper['module']);same_pose(before)
        cmds.undo();same_pose(before);cmds.redo();same_pose(before)
        checks.append('module deletion retains source joints after native connection')

        a=joint('upper_L_JNT',(8,6,0),root_joint)
        b=joint('middle_L_JNT',(11,4,1),a)
        c=joint('end_L_JNT',(15,4,0),b)
        limb=capture(toolkit.build_ikfk_module(node(a),node(b),node(c),name=prefix+'_Arm_L',
            parent_output=node(root_state['outputs'][0]['node']),parent_method='parent_constraint'))
        for blend in (0,.25,.5,.75,1):
            toolkit.set_ikfk_blend(limb['module'],blend)
            cmds.setAttr(limb['end_controller']+'.translateY',1)
            outputs_match(limb)
        checks.append('matrix IK/FK source outputs remain valid with a native module connection')
        ar=joint('upper_R_JNT',(-8,6,0),root_joint)
        br=joint('middle_R_JNT',(-11,4,1),ar);joint('end_R_JNT',(-15,4,0),br)
        mirrored=capture(toolkit.mirror_rig_module(limb['module']))
        assert state(mirrored)['attachment']['method']=='parent_constraint'
        assert state(mirrored)['attachment']['output']==state(limb)['attachment']['output']
        outputs_match(mirrored);checks.append('mirror preserves the method and central parent output')
        # Renamed joints are compared by identity, including their actual parent.
        for identity,(orient,rotate_axis,old_parents) in definitions.items():
            actual=node(identity)
            assert (cmds.getAttr(actual+'.jointOrient'),cmds.getAttr(actual+'.rotateAxis'))==(orient,rotate_axis)
            assert tuple(toolkit._guide_ik_uuid(parent) for parent in cmds.listRelatives(actual,parent=True,fullPath=True) or [])==old_parents
        checks.append('joint orientation definitions are retained')
        result={'passed':len(checks),'checks':checks,'fixture_namespace':prefix,'kept':keep}
        print('Rig connections native smoke:',result);return result
    finally:
        if not keep:
            for rig in reversed(rigs):
                if cmds.objExists(rig['module']):
                    try:
                        members.update(row['uuid'] for row in state(rig)['members'])
                        toolkit.remove_rig_module(rig['module'])
                    except (ValueError,RuntimeError):pass
            toolkit._constraint_delete_owned(members)
            remaining=cmds.ls(prefix+':*',long=True) or []
            if remaining:cmds.delete(remaining)
            if cmds.namespace(exists=prefix):cmds.namespace(removeNamespace=prefix)
        cmds.namespace(setNamespace=namespace)
        restored=[n for n in selection if cmds.objExists(n)]
        cmds.select(restored,replace=True) if restored else cmds.select(clear=True)


if __name__=='__main__':run()
