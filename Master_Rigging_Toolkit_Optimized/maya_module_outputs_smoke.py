"""Inside Maya: import maya_module_outputs_smoke; maya_module_outputs_smoke.run().

Checks native outputs and attachments. Uses unique fixtures, not a new scene.
Native Maya is required; this file is not a host-side solver simulation.
"""
import math
import uuid
import maya.cmds as cmds
import master_rigging_toolkit as toolkit


def run(keep=False):
    prefix='rtkModuleOutputSmoke_'+uuid.uuid4().hex[:8]
    namespace=cmds.namespaceInfo(currentNamespace=True)
    selected=cmds.ls(selection=True,long=True) or []
    members=set();rigs=[];checks=[]
    def world(node):return cmds.xform(node,query=True,worldSpace=True,matrix=True)
    def close(a,b):return len(a)==len(b) and all(abs(x-y)<3e-5*max(1,abs(x),abs(y)) for x,y in zip(a,b))
    def angle(value):return math.radians(value) if cmds.currentUnit(query=True,angle=True) in ('rad','radian') else value
    def capture(rig):
        rigs.append(rig)
        members.update(row['uuid'] for row in toolkit._rig_module_read(rig['module'])[1]['members'])
        return rig
    def joint(label,point,parent=None):
        node=cmds.createNode('joint',name=prefix+':'+label,skipSelect=True,**({'parent':parent} if parent else {}))
        cmds.setAttr(node+'.jointOrient',angle(5),angle(-8),angle(11),type='double3')
        cmds.setAttr(node+'.rotateAxis',angle(2),angle(3),angle(-4),type='double3')
        if parent:cmds.connectAttr(parent+'.scale',node+'.inverseScale',force=True)
        cmds.xform(node,worldSpace=True,translation=point)
        return cmds.ls(node,long=True)[0]
    def outputs_match(rig):
        for row in toolkit.list_rig_outputs(rig['module']):
            assert row['available'],row
            assert cmds.getAttr(row['node']+'.rtkRigOutput')==row['role']
            if row['joint']:assert close(world(row['node']),world(row['joint'])),row
    def pose(nodes):return {toolkit._guide_ik_uuid(n):world(n) for n in nodes}
    def same_pose(snapshot):
        for identity,matrix in snapshot.items():assert close(world(toolkit._rig_module_node(identity)),matrix),identity
    try:
        cmds.namespace(setNamespace=':');cmds.namespace(addNamespace=prefix)
        skeleton=joint('root_JNT',(0,0,0))
        spine=joint('spine_JNT',(0,4,0),skeleton)
        neck=joint('neck_JNT',(0,8,0),spine)
        head=joint('head_JNT',(0,10,0),neck)
        chain=[skeleton,spine,neck,head]
        orientation={toolkit._guide_ik_uuid(j):(cmds.getAttr(j+'.jointOrient'),cmds.getAttr(j+'.rotateAxis')) for j in chain}
        parents={toolkit._guide_ik_uuid(j):tuple(cmds.listRelatives(j,parent=True,fullPath=True) or []) for j in chain}
        root=capture(toolkit.build_root_module(root_joint=skeleton,name=prefix+'_Character',control_size=2,
            controller_names={'root':prefix+':Main_ctrl','placement':prefix+':Root_ctrl'}))
        upper=capture(toolkit.build_fk_module([spine],name=prefix+'_Spine',parent_output=root['placement_output']))
        output=toolkit.list_rig_outputs(upper['module'])[0]['node']
        before=pose(chain)
        lower=capture(toolkit.build_fk_module([neck,head],name=prefix+'_Neck',parent_output=output))
        same_pose(before)
        for rig in (root,upper,lower):outputs_match(rig)
        checks.append('Root placement and FK outputs connect modules without a bind-pose jump')
        initial=pose(chain)
        cmds.setAttr(root['main_controller']+'.globalScale',1.8)
        for identity,matrix in initial.items():
            assert close(world(toolkit._rig_module_node(identity))[12:15],[v*1.8 for v in matrix[12:15]])
        cmds.setAttr(root['root_controller']+'.translateX',3)
        cmds.setAttr(upper['controls'][0]+'.rotateZ',angle(14))
        for rig in (root,upper,lower):outputs_match(rig)
        checks.append('nested native FK outputs inherit global scale once')
        try:toolkit.attach_rig_module(upper['module'],toolkit.list_rig_outputs(lower['module'])[-1]['node'])
        except ValueError as exc:assert 'cycle' in str(exc)
        else:raise AssertionError('An attachment dependency cycle was accepted')
        try:toolkit.remove_rig_module(upper['module'])
        except ValueError as exc:assert 'Detach child module' in str(exc)
        else:raise AssertionError('A parent with an attached child was removed')
        checks.append('dependency cycles and parent deletion are rejected')
        before=pose(chain)
        toolkit.detach_rig_module(lower['module']);same_pose(before)
        cmds.undo();same_pose(before)
        assert toolkit._rig_module_read(lower['module'])[1]['attachment']
        cmds.redo();same_pose(before)
        assert not toolkit._rig_module_read(lower['module'])[1].get('attachment')
        checks.append('native detach Undo/Redo holds the current pose')
        before=pose(chain);toolkit.remove_rig_module(lower['module']);same_pose(before)
        cmds.undo();same_pose(before);assert cmds.objExists(lower['module'])
        cmds.redo();same_pose(before);assert not cmds.objExists(lower['module'])
        checks.append('native module removal Undo/Redo retains joints and current pose')

        # A separate limb checks the final blended frame rather than an IK-only
        # branch. All source joints have nonzero jointOrient and rotateAxis.
        a=joint('upper_L_JNT',(8,6,0),skeleton)
        b=joint('middle_L_JNT',(11,4,1),a)
        c=joint('end_L_JNT',(15,4,0),b)
        limb=capture(toolkit.build_ikfk_module(a,b,c,name=prefix+'_Limb_L',parent_output=root['placement_output']))
        for value in (0,.25,.5,.75,1):
            toolkit.set_ikfk_blend(limb['module'],value)
            cmds.setAttr(limb['end_controller']+'.translateY',1.1)
            outputs_match(limb)
        toolkit.set_ikfk_blend(limb['module'],0)
        cmds.setAttr(limb['fk_controllers'][1]+'.rotateY',angle(18));outputs_match(limb)
        checks.append('three IK/FK outputs follow the final native blend')
        # Mirror finds central Root's existing placement output.
        ar=joint('upper_R_JNT',(-8,6,0),skeleton)
        br=joint('middle_R_JNT',(-11,4,1),ar)
        joint('end_R_JNT',(-15,4,0),br)
        mirrored=capture(toolkit.mirror_rig_module(limb['module']))
        assert toolkit._rig_module_read(mirrored['module'])[1]['attachment']['output']==toolkit._rig_module_read(root['module'])[1]['outputs'][0]['node']
        outputs_match(mirrored);checks.append('mirrored module publishes its own outputs and shares central placement')

        ankle=joint('footAnkle_JNT',(0,4,8))
        ball=joint('footBall_JNT',(0,0,11),ankle)
        guides={}
        for key,point in (('toe_tip',(0,0,14)),('left_pivot',(-2,0,10)),('right_pivot',(2,0,10)),('heel_pivot',(0,0,6))):
            node=cmds.spaceLocator(name=prefix+':'+key)[0];cmds.xform(node,worldSpace=True,translation=point);guides[key]=node
        foot=capture(toolkit.build_foot_module(ankle,ball,name=prefix+'_Foot',parent_output=root['placement_output'],**guides))
        for roll in (-20,35,70):
            cmds.setAttr(foot['ankle_controller']+'.footRoll',roll);outputs_match(foot)
        checks.append('reverse foot outputs follow native roll and retain joint frames')
        for identity,definition in orientation.items():
            node=toolkit._rig_module_node(identity)
            assert (cmds.getAttr(node+'.jointOrient'),cmds.getAttr(node+'.rotateAxis'))==definition
            assert tuple(cmds.listRelatives(node,parent=True,fullPath=True) or [])==parents[identity]
        checks.append('skeleton parents and orientation definitions retained')
        report={'passed':len(checks),'checks':checks,'fixture_namespace':prefix,'kept':keep}
        print('Module outputs native smoke:',report)
        return report
    finally:
        if not keep:
            # Children were built after parents. Capture any later attachment
            # members before removal; an error still deletes only this fixture.
            for rig in reversed(rigs):
                if cmds.objExists(rig['module']):
                    try:
                        members.update(row['uuid'] for row in toolkit._rig_module_read(rig['module'])[1]['members'])
                        toolkit.remove_rig_module(rig['module'])
                    except (ValueError,RuntimeError):pass
            toolkit._constraint_delete_owned(members)
            remaining=cmds.ls(prefix+':*',long=True) or []
            if remaining:cmds.delete(remaining)
            if cmds.namespace(exists=prefix):cmds.namespace(removeNamespace=prefix)
        cmds.namespace(setNamespace=namespace)
        restored=[node for node in selected if cmds.objExists(node)]
        cmds.select(restored,replace=True) if restored else cmds.select(clear=True)


if __name__=='__main__':run()
