"""Run inside Maya: import maya_root_foot_smoke; maya_root_foot_smoke.run().

Creates a unique fixture; never opens a scene or resets Undo. Native test is
provided for user execution because Maya is unavailable in the build host.
"""
import math
import uuid
import maya.cmds as cmds
import master_rigging_toolkit as toolkit


def run(keep=False):
    prefix='rtkRootFootSmoke_'+uuid.uuid4().hex[:8]
    previous=cmds.namespaceInfo(currentNamespace=True)
    selection=cmds.ls(selection=True,long=True) or [];rigs=[];members=set();checks=[]
    def matrix(node):return cmds.xform(node,query=True,worldSpace=True,matrix=True)
    def close(a,b):return all(abs(x-y)<2e-5*max(1,abs(x),abs(y)) for x,y in zip(a,b))
    def angle(v):return math.radians(v) if cmds.currentUnit(query=True,angle=True) in ('rad','radian') else v
    def record(rig):
        rigs.append(rig);members.update(r['uuid'] for r in toolkit._rig_module_read(rig['module'])[1]['members']);return rig
    try:
        cmds.namespace(setNamespace=':');cmds.namespace(addNamespace=prefix)
        skeleton_root=cmds.createNode('joint',name=prefix+':SkeletonRoot_JNT',skipSelect=True)
        cmds.setAttr(skeleton_root+'.jointOrient',angle(9),angle(-13),angle(6),type='double3')
        cmds.setAttr(skeleton_root+'.rotateAxis',angle(2),angle(3),angle(-4),type='double3')
        root_definitions=(cmds.getAttr(skeleton_root+'.jointOrient'),cmds.getAttr(skeleton_root+'.rotateAxis'))
        root_local={attr:cmds.getAttr(skeleton_root+'.'+attr) for base in ('translate','rotate','scale') for attr in (base+'X',base+'Y',base+'Z')}
        ankle=cmds.createNode('joint',name=prefix+':ankle_L_JNT',parent=skeleton_root,skipSelect=True)
        cmds.connectAttr(skeleton_root+'.scale',ankle+'.inverseScale')
        cmds.setAttr(ankle+'.jointOrient',angle(11),angle(-7),angle(16),type='double3')
        cmds.setAttr(ankle+'.rotateAxis',angle(3),angle(4),angle(2),type='double3')
        cmds.xform(ankle,worldSpace=True,translation=(0,5,0))
        ball=cmds.createNode('joint',name=prefix+':ball_L_JNT',parent=ankle,skipSelect=True)
        cmds.connectAttr(ankle+'.scale',ball+'.inverseScale',force=True)
        cmds.setAttr(ball+'.jointOrient',angle(4),0,angle(11),type='double3');cmds.xform(ball,worldSpace=True,translation=(0,0,3))
        guides={}
        for key,point in (('toe_tip',(0,0,6)),('left_pivot',(-2,0,2)),('right_pivot',(2,0,2)),('heel_pivot',(0,0,-2))):
            guides[key]=cmds.spaceLocator(name=prefix+':'+key+'_L')[0];cmds.xform(guides[key],worldSpace=True,translation=point)
        root=record(toolkit.build_root_module(name=prefix+':Character',control_size=3,root_joint=skeleton_root,
             controller_names={'root':prefix+':Main_ctrl','placement':prefix+':Root_ctrl'}))
        assert root['root_joint']==skeleton_root and root['joint_count']==1
        assert (cmds.listRelatives(ankle,parent=True,fullPath=True) or [None])[0]==cmds.ls(skeleton_root,long=True)[0]
        checks.append('optional Root joint bind and unchanged skeleton hierarchy')
        bind=[matrix(ankle),matrix(ball)];definitions=[(cmds.getAttr(j+'.jointOrient'),cmds.getAttr(j+'.rotateAxis')) for j in (ankle,ball)]
        foot=record(toolkit.build_foot_module(ankle,ball,name=prefix+':Foot_L',parent_control=root['attachment'],**guides))
        assert all(close(matrix(j),m) for j,m in zip((ankle,ball),bind));checks.append('bind pose and nonzero JO/RA')
        ctrl=foot['ankle_controller'];rest=math.dist(bind[0][12:15],bind[1][12:15])
        for roll in (-25,35,45,60,70,90):
            cmds.setAttr(ctrl+'.footRoll',roll)
            assert abs(math.dist(matrix(ankle)[12:15],matrix(ball)[12:15])-rest)<rest*2e-5
            assert close(cmds.getAttr(ankle+'.scale')[0],[1,1,1]);assert close(cmds.getAttr(ball+'.scale')[0],[1,1,1])
        checks.append('roll samples retain bone length and local scale')
        cmds.setAttr(ctrl+'.bank',20);cmds.setAttr(ctrl+'.heelTwist',10);cmds.setAttr(ctrl+'.toeTap',15)
        assert not close(matrix(ankle),bind[0]);toolkit.goto_rig_default(foot['module'])
        assert all(close(matrix(j),m) for j,m in zip((ankle,ball),bind));checks.append('roll/bank/tap default reset')
        cmds.setAttr(root['main_controller']+'.globalScale',2)
        assert close(matrix(ankle)[12:15],[v*2 for v in bind[0][12:15]])
        assert close(matrix(ball)[12:15],[v*2 for v in bind[1][12:15]]);checks.append('Main scale reaches source once')
        cmds.setAttr(ctrl+'.footRoll',35);posed=[matrix(ankle),matrix(ball)]
        toolkit.remove_rig_module(foot['module'])
        assert all(close(matrix(j),m) for j,m in zip((ankle,ball),posed));checks.append('posed removal')
        cmds.undo();assert cmds.objExists(foot['module']);assert all(close(matrix(j),m) for j,m in zip((ankle,ball),posed))
        cmds.redo();assert not cmds.objExists(foot['module']);assert all(close(matrix(j),m) for j,m in zip((ankle,ball),posed));checks.append('native Undo/Redo')
        for j,d in zip((ankle,ball),definitions):assert (cmds.getAttr(j+'.jointOrient'),cmds.getAttr(j+'.rotateAxis'))==d
        fk=record(toolkit.build_foot_module(ankle,ball,mode='FK',name=prefix+':FKFoot',parent_control=root['attachment']))
        before=matrix(ball);cmds.setAttr(fk['ankle_controller']+'.rotateX',angle(15));assert not close(matrix(ball),before)
        toolkit.goto_rig_default(fk['module']);assert close(matrix(ball),before);checks.append('FK ankle / ball hierarchy')
        if not keep:
            toolkit.remove_rig_module(fk['module'])
            root_pose=matrix(skeleton_root);child_pose=matrix(ankle)
            toolkit.remove_rig_module(root['module'])
            assert close(matrix(skeleton_root),root_pose) and close(matrix(ankle),child_pose)
            assert (cmds.getAttr(skeleton_root+'.jointOrient'),cmds.getAttr(skeleton_root+'.rotateAxis'))==root_definitions
            assert all(cmds.getAttr(skeleton_root+'.'+attr)==value for attr,value in root_local.items())
            cmds.undo();assert cmds.objExists(root['module']) and close(matrix(skeleton_root),root_pose)
            cmds.redo();assert not cmds.objExists(root['module']) and close(matrix(skeleton_root),root_pose)
            checks.append('Root joint removal retains pose, channels, orientation, native Undo/Redo')
        report={'passed':len(checks),'checks':checks,'fixture_namespace':prefix,'kept':keep}
        print('Root / Foot native smoke:',report);return report
    finally:
        if not keep:
            # Delete only captured module members and the unique fixture nodes.
            owned=[toolkit._guide_ik_resolve_uuid(i) for i in members]
            owned=[n for n in owned if n and cmds.objExists(n)]
            if owned:cmds.delete(owned)
            nodes=cmds.ls(prefix+':*',long=True) or []
            if nodes:cmds.delete(nodes)
            if cmds.namespace(exists=prefix):cmds.namespace(removeNamespace=prefix)
        cmds.namespace(setNamespace=previous)
        cmds.select([n for n in selection if cmds.objExists(n)],replace=True) if selection else cmds.select(clear=True)
