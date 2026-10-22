"""Run inside Maya: import maya_smoke_test; maya_smoke_test.run().

Creates and cleans only temporary test nodes in a unique namespace. Does not
open a new scene. Opens/closes the toolkit and exercises native undo/redo.
"""
import uuid
import maya.cmds as cmds
import master_rigging_toolkit as toolkit


def run_modular_actions():
    """Native naming, old-rig removal spelling, default reset and FK/IK mirroring."""
    import math
    prefix='rtkActionsSmoke_'+uuid.uuid4().hex[:8]
    namespace=cmds.namespaceInfo(currentNamespace=True)
    selection=cmds.ls(selection=True,long=True) or []
    active=[]
    def angle(degrees):return math.radians(degrees) if cmds.currentUnit(query=True,angle=True) in ('rad','radian') else degrees
    def matrix(n):return cmds.xform(n,query=True,worldSpace=True,matrix=True)
    def close(a,b):return all(abs(x-y)<1e-5*max(1,abs(x),abs(y)) for x,y in zip(a,b))
    try:
        cmds.namespace(setNamespace=':');cmds.namespace(addNamespace=prefix)
        for kind in ('FK','IK3'):
            chains={}
            for side,sign in (('L',1),('R',-1)):
                joints=[]
                for index,translation in enumerate(((0,0,0),(3,2*sign,0),(5,-2*sign,0))):
                    joint=cmds.createNode('joint',name=prefix+':'+kind+str(index)+'_'+side+'_JNT',skipSelect=True,
                                          **({'parent':joints[-1]} if joints else {}))
                    cmds.setAttr(joint+'.translate',*translation,type='double3')
                    if joints:cmds.connectAttr(joints[-1]+'.scale',joint+'.inverseScale')
                    joints.append(joint)
                chains[side]=joints
            rig=toolkit.build_fk_module(chains['L'],name=kind+'_L') if kind=='FK' else toolkit.build_ik_module(*chains['L'],name=kind+'_L',pole_distance=1.5)
            active.append(rig['module'])
            _meta,state=toolkit._rig_module_read(rig['module'])
            assert all('_L' in name and not 'IK3_' in name for name in state['controller_names'].values())
            bind={toolkit._guide_ik_uuid(n):matrix(n) for n in chains['L']}
            controls=[toolkit._rig_module_node(identity) for role,identity in toolkit._rig_module_controller_roles(state).items() if role!='root']
            if kind=='FK':cmds.setAttr(controls[0]+'.rotateY',angle(20))
            else:cmds.setAttr(controls[0]+'.translateX',-1)
            toolkit.goto_rig_default(rig['module'])
            assert all(close(matrix(n),bind[toolkit._guide_ik_uuid(n)]) for n in chains['L'])
            cmds.setAttr(rig['root']+'.globalScale',1.5)
            toolkit.goto_rig_default(rig['module'],include_root=True)
            assert abs(cmds.getAttr(rig['root']+'.globalScale')-1)<1e-8
            assert all(close(matrix(n),bind[toolkit._guide_ik_uuid(n)]) for n in chains['L'])
            toolkit.rename_rig_controllers(rig['module'],{'root':prefix+':'+kind+'_master_L_CTL'})
            _meta,state=toolkit._rig_module_read(rig['module'])
            assert state['controller_names']['root'].endswith(kind+'_master_L_CTL')
            assert all(close(matrix(n),bind[toolkit._guide_ik_uuid(n)]) for n in chains['L'])
            mirrored=toolkit.mirror_rig_module(rig['module'])
            active.append(mirrored['module'])
            _meta,mirror_state=toolkit._rig_module_read(mirrored['module'])
            assert mirror_state['type']==kind and all('_R' in name for name in mirror_state['controller_names'].values())
            if kind=='IK3':assert mirror_state['pole_distance']==1.5
            # Default on keyed channels is explicit and retains the animation.
            cmds.setKeyframe(controls[0],attribute='rotateY',value=angle(25))
            curve=cmds.listConnections(controls[0]+'.rotateY',source=True,destination=False)[0]
            toolkit.goto_rig_default(rig['module'],keyframe=True)
            assert curve in cmds.listConnections(controls[0]+'.rotateY',source=True,destination=False)
            # Change only the saved plug spelling, reproducing stale long/short
            # constraint attribute/path strings without changing its UUID.
            for row in state['controls']:
                for value in row['inputs'].values():
                    node=toolkit._rig_module_node(value['node'])
                    value['attribute']=cmds.attributeName(node+'.'+value['attribute'],short=True)
            cmds.setAttr(rig['module']+'.rtkRigModuleState',__import__('json').dumps(state),type='string')
            posed={toolkit._guide_ik_uuid(n):matrix(n) for n in chains['L']}
            toolkit.remove_rig_module(rig['module']);active.remove(rig['module'])
            assert all(close(matrix(n),posed[toolkit._guide_ik_uuid(n)]) for n in chains['L'])
            assert cmds.objExists(mirrored['module'])
            toolkit.remove_rig_module(mirrored['module']);active.remove(mirrored['module'])
        print('PASS: FK/IK joint-based and custom names, default reset/keying, counterpart mirroring, alias-safe removal and source-pose preservation.')
    finally:
        for module in active:
            try:
                _meta,state=toolkit._rig_module_read(module)
                toolkit._guide_ik_delete_owned([row['uuid'] for row in state['members']])
            except Exception as exc:cmds.warning('Module actions cleanup: '+str(exc))
        if cmds.namespace(exists=prefix):cmds.namespace(removeNamespace=prefix,deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace)
        existing=[n for n in selection if cmds.objExists(n)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)


def run_modular_xik():
    """Native v2.24 X-axis/OPM rig, arbitrary source frames and skin-safe scales.

    Explicitly run in Maya. The local arithmetic fake does not solve RP IK.
    """
    import math
    prefix='rtkXMatrixSmoke_'+uuid.uuid4().hex[:8]
    namespace=cmds.namespaceInfo(currentNamespace=True)
    selection=cmds.ls(selection=True,long=True) or []
    linear=cmds.currentUnit(query=True,linear=True);active=[]
    def angle(d):return math.radians(d) if cmds.currentUnit(query=True,angle=True) in ('rad','radian') else d
    def position(n):return cmds.xform(n,query=True,worldSpace=True,translation=True)
    def matrix(n):return cmds.xform(n,query=True,worldSpace=True,matrix=True)
    def close(a,b):return all(abs(x-y)<2e-4*max(1,abs(x),abs(y)) for x,y in zip(a,b))
    def lengths(matrix):return [math.sqrt(sum(v*v for v in matrix[i:i+3])) for i in (0,4,8)]
    try:
        cmds.currentUnit(linear='cm');cmds.namespace(setNamespace=':');cmds.namespace(addNamespace=prefix)
        for kind in ('IK3','IKFK'):
            for compensate in (False,True):
                label=prefix+':'+kind+str(int(compensate));joints=[]
                for i,t in enumerate(((2,3,-1),(3,2,1),(4,-2,.5))):
                    joint=cmds.createNode('joint',name=label+'_'+str(i)+'_JNT',skipSelect=True,**({'parent':joints[-1]} if joints else {}))
                    cmds.setAttr(joint+'.translate',*t,type='double3')
                    cmds.setAttr(joint+'.jointOrient',*[angle(v) for v in ((10,20,5) if i==0 else (-5,9,3))],type='double3')
                    cmds.setAttr(joint+'.rotateAxisY',angle(7))
                    cmds.setAttr(joint+'.segmentScaleCompensate',compensate)
                    value=1.15 if i==0 else .9 if i==2 else 1
                    cmds.setAttr(joint+'.scale',value,value,value,type='double3')
                    if joints:cmds.connectAttr(joints[-1]+'.scale',joint+'.inverseScale')
                    joints.append(joint)
                original={n:matrix(n) for n in joints}
                local={n:{a:cmds.getAttr(n+'.'+a) for a in ('translate','rotate','scale','jointOrient','rotateAxis','segmentScaleCompensate')} for n in joints}
                world_scales={n:lengths(original[n]) for n in joints}
                builder=toolkit.build_ikfk_module if kind=='IKFK' else toolkit.build_ik_module
                rig=builder(*joints,name=label);active.append(rig['module'])
                _meta,state=toolkit._rig_module_read(rig['module'])
                assert state['ik']['solver']=='x_translate_v1'
                assert len(state['ik']['orientation_buffers'])==2
                assert sum(row['type']=='locator' for row in state['members'])==2
                assert not any(row['type'] in ('parentConstraint','scaleConstraint') for row in state['members'])
                drivers=[toolkit._rig_module_node(identity) for identity in state['ik']['drivers']]
                for n in joints:assert close(matrix(n),original[n]),('bind pose',n)
                for i in (0,1):
                    direction=[position(drivers[i+1])[j]-position(drivers[i])[j] for j in range(3)]
                    norm=math.sqrt(sum(v*v for v in direction));x=matrix(drivers[i])[:3]
                    assert close(x,[v/norm for v in direction]),'Driver +X must aim at child'
                    assert cmds.getAttr(drivers[i+1]+'.translateX')>0
                    assert close((cmds.getAttr(drivers[i+1]+'.translateY'),cmds.getAttr(drivers[i+1]+'.translateZ')),(0,0))
                def check_blended_lengths(equal=False):
                    def segment_lengths():
                        points=[position(n) for n in joints]
                        return [math.sqrt(sum((x-y)**2 for x,y in zip(a,b))) for a,b in zip(points,points[1:])]
                    toolkit.set_ikfk_blend(rig['module'],0);fk_lengths=segment_lengths()
                    toolkit.set_ikfk_blend(rig['module'],1);ik_lengths=segment_lengths()
                    if equal:assert close(fk_lengths,ik_lengths)
                    for weight in (.1,.25,.5,.75,.9):
                        toolkit.set_ikfk_blend(rig['module'],weight)
                        expected=[a*(1-weight)+b*weight for a,b in zip(fk_lengths,ik_lengths)]
                        assert close(segment_lengths(),expected),('Blended segment length',weight,segment_lengths(),expected)
                    toolkit.set_ikfk_blend(rig['module'],1)
                if kind=='IKFK':
                    # Distinct equal-length branch poses must keep their lengths.
                    cmds.setAttr(rig['fk_controllers'][0]+'.rotateZ',angle(35))
                    cmds.setAttr(rig['fk_controllers'][1]+'.rotateZ',angle(-20))
                    check_blended_lengths(equal=True)
                toolkit.set_ik_length_controls(rig['module'],{'stretch':1,'antiPop':.5,'upperSlide':.2,'lowerSlide':-.1,'slide':.3})
                cmds.setAttr(rig['end_controller']+'.translateX',5)
                assert close(position(joints[2]),position(rig['end_controller']))
                toolkit.set_ik_length_controls(rig['module'],{'poleLock':1})
                assert close(position(joints[1]),position(rig['pole_controller']))
                assert close(position(joints[2]),position(rig['end_controller']))
                for n in joints:
                    assert close(lengths(matrix(n)),world_scales[n]),'Length features must preserve bind world scale'
                    for a,v in local[n].items():assert cmds.getAttr(n+'.'+a)==v,('Source channels changed',n,a)
                    assert not (cmds.listConnections(n+'.scale',source=True,destination=False) or [])
                for n in drivers:
                    assert close(cmds.getAttr(n+'.scale')[0],(1,1,1))
                    for a in 'XYZ':assert not (cmds.listConnections(n+'.scale'+a,source=True,destination=False) or [])
                if kind=='IKFK':
                    check_blended_lengths()  # Stretched IK vs unchanged FK lengths.
                    # BASE scale is filtered; it cannot stretch or scale solver bones.
                    cmds.setAttr(rig['base_controller']+'.scale',2,2,2,type='double3')
                    for n in drivers:assert close(lengths(matrix(n)),(1,1,1))
                    for blend in (0,.5,1):
                        toolkit.set_ikfk_blend(rig['module'],blend)
                        for n in joints:assert close(lengths(matrix(n)),world_scales[n])
                posed={n:matrix(n) for n in joints};pivot=position(rig['root'])
                cmds.setAttr(rig['root']+'.globalScale',2)
                for n in joints:
                    expected=posed[n][:]
                    for i in (0,1,2,4,5,6,8,9,10):expected[i]*=2
                    for i in range(3):expected[12+i]=pivot[i]+2*(expected[12+i]-pivot[i])
                    assert close(matrix(n),expected)
                posed={n:matrix(n) for n in joints};owned=[row['uuid'] for row in state['members']]
                toolkit.remove_rig_module(rig['module']);active.remove(rig['module'])
                for n in joints:
                    assert close(matrix(n),posed[n]),'Removal must retain current pose'
                    assert not (cmds.listConnections(n+'.offsetParentMatrix',source=True,destination=False) or [])
                    for a,v in local[n].items():assert cmds.getAttr(n+'.'+a)==v
                assert all(toolkit._guide_ik_resolve_uuid(identity) is None for identity in owned)
                cmds.undo();active.append(rig['module'])
                for n in joints:assert close(matrix(n),posed[n])
                cmds.redo();active.remove(rig['module'])
                for n in joints:assert close(matrix(n),posed[n])
        print('PASS: native X-aim solver, two orientation locators, arbitrary JO/RA/axes, SSC on/off, translateX-only lengths, stable source scales, IK/FK local rotation and explicit length blending, BASE scale filtering, globalScale, frozen-OPM removal and Undo/Redo.')
    finally:
        for module in active:
            try:
                _meta,state=toolkit._rig_module_read(module)
                toolkit._guide_ik_delete_owned([row['uuid'] for row in state['members']])
            except Exception as exc:cmds.warning('X-axis matrix IK smoke cleanup: '+str(exc))
        if cmds.namespace(exists=prefix):cmds.namespace(removeNamespace=prefix,deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace);cmds.currentUnit(linear=linear)
        existing=[n for n in selection if cmds.objExists(n)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)


def run_modular_ikfk():
    """Run explicitly in Maya: native IK/FK blend, matching, keys and removal."""
    import math
    prefix='rtkIKFKSmoke_'+uuid.uuid4().hex[:8]
    namespace=cmds.namespaceInfo(currentNamespace=True)
    selection=cmds.ls(selection=True,long=True) or []
    linear=cmds.currentUnit(query=True,linear=True)
    active=[];test_curves=set()
    def angle(degrees):return math.radians(degrees) if cmds.currentUnit(query=True,angle=True) in ('rad','radian') else degrees
    def matrix(node):return cmds.xform(node,query=True,worldSpace=True,matrix=True)
    def position(node):return cmds.xform(node,query=True,worldSpace=True,translation=True)
    def close(a,b):return all(abs(x-y)<2e-4*max(1,abs(x),abs(y)) for x,y in zip(a,b))
    def capture(joints):return {toolkit._guide_ik_uuid(n):matrix(n) for n in joints}
    def verify(joints,pose):assert all(close(matrix(n),pose[toolkit._guide_ik_uuid(n)]) for n in joints)
    try:
        cmds.currentUnit(linear='cm');cmds.namespace(setNamespace=':');cmds.namespace(addNamespace=prefix)
        for compensate in (True,False):
            chains={}
            for side,sign in (('L',1),('R',-1)):
                joints=[]
                for index,translation in enumerate(((0,0,0),(4,sign,0),(4,-sign,0))):
                    joint=cmds.createNode('joint',name=prefix+':ssc'+str(int(compensate))+'_'+str(index)+'_'+side+'_JNT',skipSelect=True,
                                          **({'parent':joints[-1]} if joints else {}))
                    cmds.setAttr(joint+'.translate',*translation,type='double3')
                    cmds.setAttr(joint+'.segmentScaleCompensate',compensate)
                    cmds.setAttr(joint+'.jointOrientY',angle(10 if index==0 else 0))
                    if joints:cmds.connectAttr(joints[-1]+'.scale',joint+'.inverseScale')
                    joints.append(joint)
                chains[side]=joints
            joints=chains['L'];bind=capture(joints)
            definitions={toolkit._guide_ik_uuid(n):(cmds.getAttr(n+'.jointOrient'),cmds.getAttr(n+'.rotateAxis'),cmds.getAttr(n+'.segmentScaleCompensate')) for n in joints}
            rig=toolkit.build_ikfk_module(*joints,name='leg_L');active.append(rig['module'])
            _meta,state=toolkit._rig_module_read(rig['module'])
            assert state['type']=='IKFK' and len(state['ui_controls'])==6
            verify(joints,bind)
            for blend in (1,.5,0):
                toolkit.set_ikfk_blend(rig['module'],blend);verify(joints,bind)
                assert cmds.getAttr(toolkit._rig_module_node(state['ikfk']['fk_group'])+'.visibility')==(blend<1)
                zero=cmds.listRelatives(rig['end_controller'],parent=True,fullPath=True)[0]
                assert cmds.getAttr(zero+'.visibility')==(blend>0)
            cmds.setAttr(rig['fk_controllers'][0]+'.rotateZ',angle(15))
            cmds.setAttr(rig['fk_controllers'][1]+'.rotateZ',angle(-15))
            cmds.setAttr(rig['fk_controllers'][0]+'.translateY',1)
            fk_pose=capture(joints)
            toolkit.switch_ikfk(rig['module'],'IK');verify(joints,fk_pose)
            assert cmds.getAttr(rig['root']+'.ikFkBlend')==1
            toolkit.set_ik_length_controls(rig['module'],{'stretch':1,'antiPop':.5})
            cmds.setAttr(rig['end_controller']+'.translateX',cmds.getAttr(rig['end_controller']+'.translateX')+5)
            assert close(position(joints[2]),position(rig['end_controller']))
            ik_pose=capture(joints)
            toolkit.switch_ikfk(rig['module'],'FK');verify(joints,ik_pose)
            assert cmds.getAttr(rig['root']+'.ikFkBlend')==0
            # Roundtrip must retain the stretched output pose, including orientation.
            toolkit.switch_ikfk(rig['module'],'IK');verify(joints,ik_pose)
            cmds.currentUnit(linear='m')
            unit_pose=capture(joints)
            toolkit.switch_ikfk(rig['module'],'FK');verify(joints,unit_pose)
            toolkit.switch_ikfk(rig['module'],'IK');verify(joints,unit_pose)
            cmds.currentUnit(linear='cm')
            root_position=position(rig['root'])
            baseline=capture(joints)
            for scale in (.5,2,1):
                cmds.setAttr(rig['root']+'.globalScale',scale)
                for n in joints:
                    expected=baseline[toolkit._guide_ik_uuid(n)][:]
                    for i in (0,1,2,4,5,6,8,9,10):expected[i]*=scale
                    for i in range(3):expected[12+i]=root_position[i]+scale*(expected[12+i]-root_position[i])
                    assert close(matrix(n),expected)
            toolkit.goto_rig_default(rig['module']);verify(joints,bind)
            assert cmds.getAttr(rig['root']+'.ikFkBlend')==0
            toolkit.rename_rig_controllers(rig['module'])
            _meta,state=toolkit._rig_module_read(rig['module'])
            assert len(state['controller_names'])==7
            mirrored=toolkit.mirror_rig_module(rig['module']);active.append(mirrored['module'])
            assert toolkit._rig_module_read(mirrored['module'])[1]['type']=='IKFK'
            assert cmds.getAttr(mirrored['root']+'.ikFkBlend')==0
            toolkit.remove_rig_module(mirrored['module']);active.remove(mirrored['module'])
            # Matching keys preserve direct time curves and evaluate at this frame.
            toolkit.switch_ikfk(rig['module'],'IK',keyframe=True);verify(joints,bind)
            toolkit.switch_ikfk(rig['module'],'FK',keyframe=True);verify(joints,bind)
            for identity in toolkit._rig_module_controller_roles(state).values():
                control=toolkit._rig_module_node(identity)
                for curve in cmds.listConnections(control,source=True,destination=False,type='animCurve') or []:
                    test_curves.add(toolkit._guide_ik_uuid(curve))
            assert cmds.listConnections(rig['root']+'.ikFkBlend',source=True,destination=False,type='animCurve')
            posed=capture(joints);owned=[row['uuid'] for row in state['members']]
            toolkit.remove_rig_module(rig['module']);active.remove(rig['module']);verify(joints,posed)
            assert all(toolkit._guide_ik_resolve_uuid(identity) is None for identity in owned)
            for n in joints:assert (cmds.getAttr(n+'.jointOrient'),cmds.getAttr(n+'.rotateAxis'),cmds.getAttr(n+'.segmentScaleCompensate'))==definitions[toolkit._guide_ik_uuid(n)]
            cmds.undo();active.append(rig['module']);verify(joints,posed)
            cmds.redo();active.remove(rig['module']);verify(joints,posed)
        print('PASS: native IK/FK endpoints/midblend, visibility, moved-base FK-to-IK match, stretched IK-to-FK roundtrip, meter-unit matching, globalScale, defaults, naming, mirror, keyed matching and pose-preserving removal/Undo/Redo.')
    finally:
        for module in active:
            try:
                _meta,state=toolkit._rig_module_read(module)
                toolkit._guide_ik_delete_owned([row['uuid'] for row in state['members']])
            except Exception as exc:cmds.warning('IK/FK smoke cleanup: '+str(exc))
        for identity in test_curves:
            node=toolkit._guide_ik_resolve_uuid(identity)
            if node and not (cmds.listConnections(node,source=False,destination=True) or []):cmds.delete(node)
        if cmds.namespace(exists=prefix):cmds.namespace(removeNamespace=prefix,deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace);cmds.currentUnit(linear=linear)
        existing=[n for n in selection if cmds.objExists(n)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)


def run_modular_ik_lengths():
    """Native stretch/soft reach/slide/pole-lock, units, defaults and removal.

    Call explicitly inside Maya; local graph-math tests do not simulate IK.
    """
    import math
    prefix='rtkLengthSmoke_'+uuid.uuid4().hex[:8]
    namespace=cmds.namespaceInfo(currentNamespace=True)
    selection=cmds.ls(selection=True,long=True) or []
    linear=cmds.currentUnit(query=True,linear=True)
    module=None
    def position(node):return cmds.xform(node,query=True,worldSpace=True,translation=True)
    def matrix(node):return toolkit._rig_module_length_matrix(node)
    def distance(a,b):return math.sqrt(sum((x-y)**2 for x,y in zip(position(a),position(b))))
    def close(a,b):return all(abs(x-y)<2e-4*max(1,abs(x),abs(y)) for x,y in zip(a,b))
    try:
        cmds.currentUnit(linear='cm')
        cmds.namespace(setNamespace=':');cmds.namespace(addNamespace=prefix)
        joints=[]
        for index,translation in enumerate(((0,0,0),(4,1,0),(4,-1,0))):
            joint=cmds.createNode('joint',name=prefix+':length'+str(index)+'_JNT',skipSelect=True,
                                  **({'parent':joints[-1]} if joints else {}))
            cmds.setAttr(joint+'.translate',*translation,type='double3')
            if joints:cmds.connectAttr(joints[-1]+'.scale',joint+'.inverseScale')
            joints.append(joint)
        rig=toolkit.build_ik_module(*joints,name=prefix+'_lengths');module=rig['module']
        _meta,state=toolkit._rig_module_read(module)
        end,pole=rig['end_controller'],rig['pole_controller']
        drivers=[toolkit._rig_module_node(identity) for identity in state['ik']['drivers']]
        goal=toolkit._rig_module_node(state['ik']['length_system']['goal'])
        rest=state['ik']['length_system']['rest_lengths'];total=sum(rest)
        scales={n:cmds.getAttr(n+'.scale') for n in joints+drivers}
        for name in toolkit._RIG_MODULE_IK_LENGTH_ATTRS:
            assert cmds.getAttr(end+'.'+name,keyable=True) and not cmds.getAttr(end+'.'+name,lock=True)
        cmds.setAttr(end+'.translateX',4)
        toolkit.set_ik_length_controls(module,{'stretch':1})
        assert close(position(joints[2]),position(end)), 'Full stretch should reach END'
        assert cmds.getAttr(end+'.upperLength')+cmds.getAttr(end+'.lowerLength')>total
        toolkit.set_ik_length_controls(module,{'stretch':0,'antiPop':1})
        assert distance(joints[0],goal)<total, 'Anti-pop should soften full extension'
        assert abs(cmds.getAttr(end+'.upperLength')+cmds.getAttr(end+'.lowerLength')-total)<1e-4
        toolkit.set_ik_length_controls(module,{'stretch':1})
        assert close(position(joints[2]),position(end))
        assert cmds.getAttr(end+'.upperLength')+cmds.getAttr(end+'.lowerLength')>distance(joints[0],end)
        lengths=(cmds.getAttr(end+'.upperLength'),cmds.getAttr(end+'.lowerLength'))
        for scale in (.5,2,1):
            cmds.setAttr(rig['root']+'.globalScale',scale)
            assert close(lengths,(cmds.getAttr(end+'.upperLength'),cmds.getAttr(end+'.lowerLength')))
            assert close(position(joints[2]),position(end))
        toolkit.goto_rig_default(module)
        toolkit.set_ik_length_controls(module,{'upperSlide':.25,'lowerSlide':-.1,'slide':.3})
        assert abs(cmds.getAttr(end+'.upperLength')+cmds.getAttr(end+'.lowerLength')-(rest[0]*1.25+rest[1]*.9))<1e-4
        assert abs(distance(joints[0],joints[1])-cmds.getAttr(end+'.upperLength'))<2e-4
        assert abs(distance(joints[1],joints[2])-cmds.getAttr(end+'.lowerLength'))<2e-4
        toolkit.set_ik_length_controls(module,{'poleLock':1})
        assert close(position(joints[1]),position(pole)), 'Full pole lock should pin middle joint'
        assert close(position(joints[2]),position(end)), 'Full pole lock should reach END'
        assert all(close(cmds.getAttr(n+'.scale')[0],scales[n][0]) for n in joints+drivers), 'Length features must not change joint scale'
        before_units={n:matrix(n) for n in joints}
        cmds.currentUnit(linear='m')
        for n in joints:assert close(matrix(n),before_units[n]), 'Changing UI linear units must preserve world pose'
        toolkit.goto_rig_default(module)
        for name in toolkit._RIG_MODULE_IK_LENGTH_ATTRS:assert abs(cmds.getAttr(end+'.'+name))<1e-8
        cmds.currentUnit(linear='cm')
        toolkit.set_ik_length_controls(module,{'stretch':1,'antiPop':.5,'slide':.2})
        cmds.setAttr(end+'.translateX',4)
        posed={n:matrix(n) for n in joints};owned=[row['uuid'] for row in state['members']]
        toolkit.remove_rig_module(module);module=None
        assert all(close(matrix(n),posed[n]) for n in joints)
        assert all(toolkit._guide_ik_resolve_uuid(identity) is None for identity in owned)
        cmds.undo();module=rig['module']
        assert all(close(matrix(n),posed[n]) for n in joints)
        cmds.redo();module=None
        assert all(close(matrix(n),posed[n]) for n in joints)
        print('PASS: native IK stretch, anti-pop, upper/lower/overall slide, pole lock, unchanged bone scales, global scale, units, default reset and pose-preserving removal/Undo/Redo.')
    finally:
        if module and cmds.objExists(module):
            try:
                _meta,state=toolkit._rig_module_read(module)
                toolkit._guide_ik_delete_owned([row['uuid'] for row in state['members']])
            except Exception as exc:cmds.warning('IK length smoke cleanup: '+str(exc))
        if cmds.namespace(exists=prefix):cmds.namespace(removeNamespace=prefix,deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace);cmds.currentUnit(linear=linear)
        existing=[n for n in selection if cmds.objExists(n)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)


def run_modular_ik():
    """Native IK end/pole evaluation, global scale and pose-preserving removal."""
    import math
    prefix='rtkModuleIKSmoke_'+uuid.uuid4().hex[:8]
    namespace=cmds.namespaceInfo(currentNamespace=True)
    selection=cmds.ls(selection=True,long=True) or []
    active=[]
    def angle(degrees):
        return math.radians(degrees) if cmds.currentUnit(query=True,angle=True) in ('rad','radian') else degrees
    def matrix(node): return cmds.xform(node,query=True,worldSpace=True,matrix=True)
    def position(node): return cmds.xform(node,query=True,worldSpace=True,translation=True)
    def close(a,b): return all(abs(x-y)<1e-5*max(1,abs(x),abs(y)) for x,y in zip(a,b))
    try:
        cmds.namespace(setNamespace=':')
        cmds.namespace(addNamespace=prefix)
        for compensate in (True,False):
            label=prefix+':ssc'+str(int(compensate))
            parent=cmds.createNode('transform',name=label+'_space',skipSelect=True)
            cmds.setAttr(parent+'.translate',4,2,1,type='double3')
            joints=[]
            for index,translation in enumerate(((0,0,0),(3,2,0),(5,-2,0))):
                joint=cmds.createNode('joint',name=label+'_joint'+str(index),parent=joints[-1] if joints else parent,skipSelect=True)
                cmds.setAttr(joint+'.translate',*translation,type='double3')
                cmds.setAttr(joint+'.segmentScaleCompensate',compensate)
                cmds.setAttr(joint+'.jointOrientY',angle(10 if index==0 else 0))
                if joints:cmds.connectAttr(joints[-1]+'.scale',joint+'.inverseScale')
                joints.append(joint)
            before={toolkit._guide_ik_uuid(n):matrix(n) for n in joints}
            definitions={toolkit._guide_ik_uuid(n):(cmds.getAttr(n+'.jointOrient'),cmds.getAttr(n+'.rotateAxis'),cmds.getAttr(n+'.segmentScaleCompensate')) for n in joints}
            result=toolkit.build_ik_module(*joints,name=prefix+'_ik'+str(int(compensate)),control_size=.7)
            active.append(result['module'])
            _meta,state=toolkit._rig_module_read(result['module'])
            assert state['type']=='IK3' and result['owned_node_count']>23
            assert state['ik']['length_system']['version']==1
            assert all(close(matrix(n),before[toolkit._guide_ik_uuid(n)]) for n in joints)
            pivot=position(result['root'])
            for scale in (.5,2,1):
                cmds.setAttr(result['root']+'.globalScale',scale)
                for n in joints:
                    original=before[toolkit._guide_ik_uuid(n)];expected=original[:]
                    for i in (0,1,2,4,5,6,8,9,10):expected[i]*=scale
                    for i in range(3):expected[12+i]=pivot[i]+scale*(original[12+i]-pivot[i])
                    assert close(matrix(n),expected),('IK globalScale',compensate,scale,n,matrix(n),expected)
            cmds.setAttr(result['end_controller']+'.translateX',-1)
            cmds.setAttr(result['end_controller']+'.translateY',1)
            assert close(position(joints[2]),position(result['end_controller'])), 'End joint should follow reachable IK goal'
            bend_before=position(joints[1])
            cmds.setAttr(result['pole_controller']+'.translateZ',2)
            assert not close(position(joints[1]),bend_before), 'Pole controller should change bend direction'
            cmds.setAttr(result['end_controller']+'.rotateZ',angle(20))
            cmds.setAttr(result['root']+'.globalScale',1.5)
            posed={toolkit._guide_ik_uuid(n):matrix(n) for n in joints}
            owned=[row['uuid'] for row in state['members']]
            toolkit.remove_rig_module(result['module'])
            active.remove(result['module'])
            assert all(close(matrix(n),posed[toolkit._guide_ik_uuid(n)]) for n in joints)
            assert all(toolkit._guide_ik_resolve_uuid(identity) is None for identity in owned)
            for n in joints:
                assert (cmds.getAttr(n+'.jointOrient'),cmds.getAttr(n+'.rotateAxis'),cmds.getAttr(n+'.segmentScaleCompensate')) == definitions[toolkit._guide_ik_uuid(n)]
            cmds.undo();active.append(result['module'])
            assert all(toolkit._guide_ik_resolve_uuid(identity) for identity in owned)
            assert all(close(matrix(n),posed[toolkit._guide_ik_uuid(n)]) for n in joints)
            cmds.redo();active.remove(result['module'])
            assert all(close(matrix(n),posed[toolkit._guide_ik_uuid(n)]) for n in joints)
        print('PASS: modular Three-Bone IK end/pole controls, nonzero JO, SSC on/off, globalScale and pose-preserving removal/Undo/Redo.')
    finally:
        for module in active:
            try:
                _meta,state=toolkit._rig_module_read(module)
                toolkit._guide_ik_delete_owned([row['uuid'] for row in state['members']])
            except Exception as exc:cmds.warning('Modular IK smoke cleanup: '+str(exc))
        if cmds.namespace(exists=prefix):cmds.namespace(removeNamespace=prefix,deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace)
        existing=[n for n in selection if cmds.objExists(n)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)


def run_modular_fk():
    """Native FK, global scale, branch hierarchy, JO/SSC and pose-safe removal."""
    import math
    prefix = 'rtkModularSmoke_' + uuid.uuid4().hex[:8]
    namespace = cmds.namespaceInfo(currentNamespace=True)
    selection = cmds.ls(selection=True,long=True) or []
    active = []
    def angle(degrees):
        return math.radians(degrees) if cmds.currentUnit(query=True,angle=True) in ('rad','radian') else degrees
    def matrix(node): return cmds.xform(node,query=True,worldSpace=True,matrix=True)
    def close(a,b): return all(abs(x-y)<1e-5*max(1,abs(x),abs(y)) for x,y in zip(a,b))
    try:
        cmds.namespace(setNamespace=':')
        cmds.namespace(addNamespace=prefix)
        for compensate in (True,False):
            label = prefix+':ssc'+str(int(compensate))
            space = cmds.createNode('transform',name=label+'_space',skipSelect=True)
            cmds.setAttr(space+'.translate',4,2,1,type='double3')
            cmds.setAttr(space+'.rotateY',angle(10))
            joints=[]
            for index in range(3):
                joint=cmds.createNode('joint',name=label+'_joint'+str(index),parent=space if index==0 else joints[-1],skipSelect=True)
                cmds.setAttr(joint+'.translate',2+index,0,0,type='double3')
                cmds.setAttr(joint+'.jointOrientY',angle(12+index*5))
                cmds.setAttr(joint+'.rotateOrder',2)
                cmds.setAttr(joint+'.segmentScaleCompensate',compensate)
                if joints: cmds.connectAttr(joints[-1]+'.scale',joint+'.inverseScale')
                joints.append(joint)
            branch=cmds.createNode('joint',name=label+'_branch',parent=joints[0],skipSelect=True)
            cmds.setAttr(branch+'.translate',0,3,0,type='double3')
            cmds.setAttr(branch+'.segmentScaleCompensate',compensate)
            cmds.connectAttr(joints[0]+'.scale',branch+'.inverseScale')
            joints.append(branch)
            bind = {toolkit._guide_ik_uuid(n):matrix(n) for n in joints}
            definitions = {toolkit._guide_ik_uuid(n):(cmds.getAttr(n+'.jointOrient'),cmds.getAttr(n+'.rotateAxis'),cmds.getAttr(n+'.segmentScaleCompensate')) for n in joints}
            parents={toolkit._guide_ik_uuid(n):cmds.listRelatives(n,parent=True,fullPath=True) for n in joints}
            result=toolkit.build_fk_module(joints[0],name=prefix+'_arm'+str(int(compensate)),include_children=True,control_size=.7)
            active.append(result['module'])
            _meta,state=toolkit._rig_module_read(result['module'])
            assert result['joint_count']==4 and result['owned_node_count']==23
            assert all(close(matrix(n),bind[toolkit._guide_ik_uuid(n)]) for n in joints)
            pivot=cmds.xform(result['root'],query=True,worldSpace=True,translation=True)
            for scale in (.5,2,1):
                cmds.setAttr(result['root']+'.globalScale',scale)
                for n in joints:
                    original=bind[toolkit._guide_ik_uuid(n)]
                    expected=original[:]
                    for index in (0,1,2,4,5,6,8,9,10): expected[index]*=scale
                    for index in range(3): expected[12+index]=pivot[index]+scale*(original[12+index]-pivot[index])
                    assert close(matrix(n),expected), ('globalScale',compensate,scale,n,matrix(n),expected)
            for row in state['controls']:
                ctrl=toolkit._rig_module_node(row['control'])
                joint=toolkit._rig_module_node(row['joint'])
                cmds.setAttr(ctrl+'.rotateZ',angle(20))
                assert close(matrix(ctrl),matrix(joint)), ('FK rotation',joint)
            cmds.setAttr(result['root']+'.globalScale',1.5)
            cmds.setAttr(result['root']+'.translateY',cmds.getAttr(result['root']+'.translateY')+2)
            posed={toolkit._guide_ik_uuid(n):matrix(n) for n in joints}
            owned=[row['uuid'] for row in state['members']]
            toolkit.remove_rig_module(result['module'])
            active.remove(result['module'])
            assert all(close(matrix(n),posed[toolkit._guide_ik_uuid(n)]) for n in joints)
            assert all(toolkit._guide_ik_resolve_uuid(identity) is None for identity in owned)
            for n in joints:
                assert (cmds.getAttr(n+'.jointOrient'),cmds.getAttr(n+'.rotateAxis'),cmds.getAttr(n+'.segmentScaleCompensate')) == definitions[toolkit._guide_ik_uuid(n)]
                assert cmds.listRelatives(n,parent=True,fullPath=True)==parents[toolkit._guide_ik_uuid(n)]
            cmds.undo()
            active.append(result['module'])
            assert all(toolkit._guide_ik_resolve_uuid(identity) for identity in owned)
            assert all(close(matrix(n),posed[toolkit._guide_ik_uuid(n)]) for n in joints)
            cmds.redo()
            active.remove(result['module'])
            assert all(close(matrix(n),posed[toolkit._guide_ik_uuid(n)]) for n in joints)
        print('PASS: native modular FK, branched hierarchy, nonzero JO, SSC on/off, scale .5/2/1, root motion, current-pose removal and Undo/Redo.')
    finally:
        for module in active:
            try:
                _meta,state=toolkit._rig_module_read(module)
                toolkit._guide_ik_delete_owned([row['uuid'] for row in state['members']])
            except Exception as exc: cmds.warning('Modular FK smoke cleanup: '+str(exc))
        if cmds.namespace(exists=prefix): cmds.namespace(removeNamespace=prefix,deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace)
        existing=[n for n in selection if cmds.objExists(n)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)


def run_guide_match_sdk():
    """Native SDK-connected joint matching with direct set values and Undo/Redo."""
    import math
    prefix='rtkMatchSDKSmoke_'+uuid.uuid4().hex[:8]
    namespace=cmds.namespaceInfo(currentNamespace=True)
    selection=cmds.ls(selection=True,long=True) or []
    curve=None
    def angle(value):
        return math.radians(value) if cmds.currentUnit(query=True,angle=True) in ('rad','radian') else value
    def matrix(node):return cmds.xform(node,query=True,worldSpace=True,matrix=True)
    def close(a,b):return all(abs(x-y)<2e-5 for x,y in zip(a,b))
    try:
        cmds.namespace(setNamespace=':')
        cmds.namespace(addNamespace=prefix)
        source_parent=cmds.createNode('transform',name=prefix+':sourceParent',skipSelect=True)
        target_parent=cmds.createNode('transform',name=prefix+':targetParent',skipSelect=True)
        source=cmds.createNode('transform',name=prefix+':source',parent=source_parent,skipSelect=True)
        target=cmds.createNode('joint',name=prefix+':target',parent=target_parent,skipSelect=True)
        driver=cmds.createNode('transform',name=prefix+':driver',skipSelect=True)
        cmds.addAttr(driver,longName='pose',attributeType='double',keyable=True)
        cmds.setAttr(source_parent+'.translateX',4)
        cmds.setAttr(source_parent+'.rotateY',angle(15))
        cmds.setAttr(target_parent+'.translateX',-4)
        cmds.setAttr(target_parent+'.rotateZ',angle(-20))
        cmds.setAttr(source+'.translate',5,2,3,type='double3')
        cmds.setAttr(source+'.rotate',angle(20),angle(30),angle(50),type='double3')
        cmds.setAttr(target+'.jointOrientY',angle(25))
        for value,rotation in ((0,0),(1,60)):
            cmds.setAttr(driver+'.pose',value)
            cmds.setAttr(target+'.rotateZ',angle(rotation))
            cmds.setDrivenKeyframe(target+'.rotateZ',currentDriver=driver+'.pose',inTangentType='linear',outTangentType='linear')
        curve=(cmds.listConnections(target+'.rotateZ',source=True,destination=False,skipConversionNodes=True,type='animCurve') or [None])[0]
        assert curve, 'Expected a real SDK animation curve.'
        keys=lambda:(cmds.keyframe(curve,query=True,floatChange=True),cmds.keyframe(curve,query=True,valueChange=True))
        inputs=lambda:{target+'.'+prefix:sorted(cmds.listConnections(target+'.'+prefix,source=True,destination=False,plugs=True) or [])
                       for prefix in ['translate','rotate','scale']+[base+axis for base in ('translate','rotate','scale') for axis in 'XYZ']}
        cmds.setAttr(driver+'.pose',.25)
        original,expected=matrix(target),matrix(source)
        old_keys,old_inputs=keys(),inputs()
        orientation=cmds.getAttr(target+'.jointOrient')
        toolkit.match_two_transforms(source,target)
        assert close(matrix(target),expected), 'Set-mode world transform did not match.'
        assert matrix(source)==expected
        assert keys()==old_keys and inputs()==old_inputs
        assert cmds.getAttr(driver+'.pose')==.25
        assert cmds.getAttr(target+'.jointOrient')==orientation
        cmds.undo()
        assert close(matrix(target),original) and keys()==old_keys and inputs()==old_inputs
        cmds.redo()
        assert close(matrix(target),expected) and keys()==old_keys and inputs()==old_inputs
        cmds.setAttr(driver+'.pose',.75)
        assert abs(cmds.getAttr(target+'.rotateZ')-angle(45))<2e-5, 'SDK driver must still evaluate its original curve.'
        print('PASS: SDK-connected joint set match across parents, world pose, original curve keys/driver/inputs/jointOrient, Undo/Redo and subsequent SDK evaluation.')
    finally:
        if curve and cmds.objExists(curve):cmds.delete(curve)
        if cmds.namespace(exists=prefix):cmds.namespace(removeNamespace=prefix,deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace)
        selected=[n for n in selection if cmds.objExists(n)]
        cmds.select(selected,replace=True) if selected else cmds.select(clear=True)


def run_guide_match_transforms():
    """Native matching across parents, component options, joints and Undo/Redo."""
    import math
    prefix = 'rtkMatchSmoke_' + uuid.uuid4().hex[:8]
    namespace = cmds.namespaceInfo(currentNamespace=True)
    selection = cmds.ls(selection=True,long=True) or []
    def angle(degrees):
        return math.radians(degrees) if cmds.currentUnit(query=True,angle=True) in ('rad','radian') else degrees
    try:
        cmds.namespace(setNamespace=':')
        cmds.namespace(addNamespace=prefix)
        a = cmds.createNode('transform',name=prefix+':sourceParent',skipSelect=True)
        b = cmds.createNode('transform',name=prefix+':targetParent',skipSelect=True)
        source = cmds.createNode('transform',name=prefix+':source',parent=a,skipSelect=True)
        target = cmds.createNode('joint',name=prefix+':target',parent=b,skipSelect=True)
        cmds.setAttr(a+'.translateX',4)
        cmds.setAttr(a+'.rotateY',angle(15))
        cmds.setAttr(b+'.translateX',-4)
        cmds.setAttr(b+'.rotateZ',angle(-20))
        cmds.setAttr(source+'.translate',5,2,3,type='double3')
        cmds.setAttr(source+'.rotate',angle(20),angle(30),angle(10),type='double3')
        cmds.setAttr(source+'.scale',2,2,2,type='double3')
        cmds.setAttr(target+'.jointOrientY',angle(25))
        original = cmds.xform(target,query=True,worldSpace=True,matrix=True)
        expected = cmds.xform(source,query=True,worldSpace=True,matrix=True)
        orientation = cmds.getAttr(target+'.jointOrient')
        for method in ('set','native'):
            toolkit.match_two_transforms(source,target,position=True,rotation=True,scale=True,method=method)
            actual = cmds.xform(target,query=True,worldSpace=True,matrix=True)
            assert all(abs(a-b)<1e-5 for a,b in zip(actual,expected))
            assert cmds.getAttr(target+'.jointOrient') == orientation
            assert cmds.xform(source,query=True,worldSpace=True,matrix=True) == expected
            cmds.undo()
            assert all(abs(a-b)<1e-5 for a,b in zip(cmds.xform(target,query=True,worldSpace=True,matrix=True),original))
            cmds.redo()
            cmds.undo()
        rotation,scale = cmds.getAttr(target+'.rotate'),cmds.getAttr(target+'.scale')
        toolkit.match_two_transforms(source,target,position=True,rotation=False,scale=False)
        assert all(abs(a-b)<1e-5 for a,b in zip(cmds.xform(target,query=True,worldSpace=True,translation=True),cmds.xform(source,query=True,worldSpace=True,translation=True)))
        assert cmds.getAttr(target+'.rotate') == rotation and cmds.getAttr(target+'.scale') == scale
        print('PASS: Guide match Target -> Source across parents, TRS/position-only, unchanged source/jointOrient and Undo/Redo.')
    finally:
        if cmds.namespace(exists=prefix):
            cmds.namespace(removeNamespace=prefix,deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace)
        existing = [n for n in selection if cmds.objExists(n)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)


def run_pair_constraints():
    """Native Driver/Driven direction, typed channels, offset and Undo/Redo."""
    prefix = 'rtkPairSmoke_' + uuid.uuid4().hex[:8]
    namespace = cmds.namespaceInfo(currentNamespace=True)
    selection = cmds.ls(selection=True,long=True) or []
    try:
        cmds.namespace(setNamespace=':')
        cmds.namespace(addNamespace=prefix)
        for kind in ('parent','point','orient','scale','aim','parent_scale'):
            for offset in (True,False):
                driver = cmds.createNode('transform',name=prefix+':'+kind+'_driver',skipSelect=True)
                driven = cmds.createNode('transform',name=prefix+':'+kind+'_driven',skipSelect=True)
                cmds.setAttr(driver+'.translate',5,2,0,type='double3')
                cmds.setAttr(driven+'.translate',1,0,0,type='double3')
                before = cmds.xform(driven,query=True,worldSpace=True,matrix=True)
                result = toolkit.create_pair_constraint(driver,driven,kind,offset)
                assert len(result['constraints']) == (2 if kind=='parent_scale' else 1)
                assert all(cmds.objExists(node) for node in result['constraints'])
                if offset:
                    assert all(abs(a-b)<1e-5 for a,b in zip(before,cmds.xform(driven,query=True,worldSpace=True,matrix=True)))
                if kind in ('parent','point','parent_scale') and not offset:
                    assert all(abs(a-b)<1e-5 for a,b in zip(cmds.xform(driver,query=True,worldSpace=True,translation=True),cmds.xform(driven,query=True,worldSpace=True,translation=True)))
                cmds.undo()
                assert all(not cmds.objExists(node) for node in result['constraints'])
                assert all(abs(a-b)<1e-5 for a,b in zip(before,cmds.xform(driven,query=True,worldSpace=True,matrix=True)))
                cmds.redo()
                for command,node in zip(result['commands'],result['constraints']):
                    targets = getattr(cmds,command)(node,query=True,targetList=True)
                    assert len(targets)==1 and toolkit._guide_ik_uuid(targets[0]) == toolkit._guide_ik_uuid(driver)
                cmds.delete(result['constraints'])
                cmds.delete(driver,driven)
        print('PASS: all quick constraint types, Driver -> Driven, Maintain Offset on/off, snap, target lists and Undo/Redo.')
    finally:
        if cmds.namespace(exists=prefix):
            cmds.namespace(removeNamespace=prefix,deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace)
        existing = [node for node in selection if cmds.objExists(node)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)


def run_pose_driver_sdk_weights():
    """Native Set Driven Key using connected, unlocked cone/joint weight drivers."""
    import math
    prefix = 'rtkSDKWeightsSmoke_' + uuid.uuid4().hex[:8]
    namespace = cmds.namespaceInfo(currentNamespace=True)
    selection = cmds.ls(selection=True,long=True) or []
    group_id = None
    try:
        cmds.namespace(setNamespace=':')
        cmds.namespace(addNamespace=prefix)
        joint = cmds.createNode('joint',name=prefix+':driver',skipSelect=True)
        result = toolkit.build_pose_driver(joint)
        group_id = toolkit._pd_uuid(result['group'])
        def pose(degrees):
            value = math.radians(degrees) if cmds.currentUnit(query=True,angle=True) in ('rad','radian') else degrees
            cmds.setAttr(joint+'.rotateZ',value)
        pose(45)
        record = toolkit.capture_pose_driver_rotation(result['group'],name='up',radius=45)
        toolkit.set_pose_driver_falloff(result['group'],'linear')
        driven = cmds.createNode('transform',name=prefix+':driven',skipSelect=True)
        for attribute,node in [('fromJoint',joint),('fromCone',result['cone'])]:
            cmds.addAttr(driven,longName=attribute,attributeType='double',keyable=True)
            driver = node+'.upWeight'
            assert not cmds.getAttr(driver,lock=True) and cmds.getAttr(driver,keyable=True)
            for driver_value,driven_value in [(0,0),(1,20)]:
                cmds.setDrivenKeyframe(driven+'.'+attribute,currentDriver=driver,driverValue=driver_value,
                    value=driven_value,inTangentType='linear',outTangentType='linear')
        for rotation,expected in [(0,0),(22.5,10),(45,20)]:
            pose(rotation)
            assert abs(cmds.getAttr(driven+'.fromJoint')-expected)<2e-5
            assert abs(cmds.getAttr(driven+'.fromCone')-expected)<2e-5
        # Upgrade a previously locked setup, retaining its SDK fan-out.
        for node in (joint,result['cone']):
            cmds.setAttr(node+'.upWeight',lock=True,keyable=False)
        pose(22.5)
        before = cmds.listConnections(joint+'.upWeight',destination=True,source=False,plugs=True)
        toolkit.unlock_pose_driver_weights(result['group'])
        assert cmds.listConnections(joint+'.upWeight',destination=True,source=False,plugs=True) == before
        assert abs(cmds.getAttr(driven+'.fromJoint')-10)<2e-5
        cmds.undo()
        assert cmds.getAttr(joint+'.upWeight',lock=True)
        cmds.redo()
        assert not cmds.getAttr(joint+'.upWeight',lock=True)
        toolkit.remove_pose_driver(result['group'],preserve_consumers=True)
        assert abs(cmds.getAttr(driven+'.fromJoint')-10)<2e-5
        assert abs(cmds.getAttr(driven+'.fromCone')-10)<2e-5
        print('PASS: unlocked/keyable weight SDK drivers from cone/joint, live driven values, migration preserves SDK connections, removal keeps current SDK values.')
    finally:
        if group_id:
            group = toolkit._guide_ik_resolve_uuid(group_id)
            if group:
                toolkit.remove_pose_driver(group,preserve_consumers=True)
        if cmds.namespace(exists=prefix):
            cmds.namespace(removeNamespace=prefix,deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace)
        existing = [n for n in selection if cmds.objExists(n)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)


def run_pose_driver_linear_remove():
    """Native angular falloff/unit changes and removal with frozen consumers."""
    import math
    prefix = 'rtkLinearSmoke_' + uuid.uuid4().hex[:8]
    namespace = cmds.namespaceInfo(currentNamespace=True)
    selection = cmds.ls(selection=True,long=True) or []
    angle_unit = cmds.currentUnit(query=True,angle=True)
    group_id = None
    try:
        cmds.namespace(setNamespace=':')
        cmds.namespace(addNamespace=prefix)
        joint = cmds.createNode('joint',name=prefix+':driver',skipSelect=True)
        def rotation(degrees):
            value = math.radians(degrees) if cmds.currentUnit(query=True,angle=True) in ('rad','radian') else degrees
            cmds.setAttr(joint+'.rotateZ',value)
        rotation(0)
        result = toolkit.build_pose_driver(joint)
        group_id = toolkit._pd_uuid(result['group'])
        rotation(45)
        pose = toolkit.capture_pose_driver_rotation(result['group'],name='up',radius=45)
        consumer = cmds.createNode('transform',name=prefix+':consumer',skipSelect=True)
        cmds.addAttr(consumer,longName='amount',attributeType='double')
        cmds.addAttr(consumer,longName='raw',attributeType='double')
        cmds.connectAttr(result['cone']+'.upWeight',consumer+'.amount')
        cmds.connectAttr(joint+'.upWeightRaw',consumer+'.raw')
        original_output = cmds.connectionInfo(result['cone']+'.upWeight',sourceFromDestination=True)
        toolkit.set_pose_driver_falloff(result['group'],'linear')
        assert cmds.connectionInfo(result['cone']+'.upWeight',sourceFromDestination=True) == original_output
        for unit in ('deg','rad'):
            cmds.currentUnit(angle=unit)
            for distance,expected in [(0,1),(15,2/3),(30,1/3),(45,0),(60,0)]:
                rotation(45-distance)
                assert abs(cmds.getAttr(result['cone']+'.upWeightRaw')-expected)<2e-5
                assert abs(cmds.getAttr(joint+'.upWeight')-expected)<2e-5
        toolkit.set_pose_driver_falloff(result['group'],'smooth')
        rotation(30)
        smooth = cmds.getAttr(result['cone']+'.upWeightRaw')
        assert abs(smooth-2/3)>.05
        toolkit.set_pose_driver_falloff(result['group'],'linear')
        assert abs(cmds.getAttr(result['cone']+'.upWeightRaw')-2/3)<2e-5
        original_values = [cmds.getAttr(consumer+'.amount'),cmds.getAttr(consumer+'.raw')]
        original_matrix = cmds.xform(joint,query=True,worldSpace=True,matrix=True)
        toolkit.remove_pose_driver(result['group'],preserve_consumers=True)
        assert not cmds.connectionInfo(consumer+'.amount',sourceFromDestination=True)
        assert not cmds.connectionInfo(consumer+'.raw',sourceFromDestination=True)
        assert all(abs(a-b)<1e-6 for a,b in zip(original_values,[cmds.getAttr(consumer+'.amount'),cmds.getAttr(consumer+'.raw')]))
        assert all(abs(a-b)<1e-6 for a,b in zip(original_matrix,cmds.xform(joint,query=True,worldSpace=True,matrix=True)))
        cmds.undo()
        restored = toolkit._pd_node(group_id)
        assert cmds.connectionInfo(consumer+'.amount',sourceFromDestination=True)
        assert toolkit._pd_read(restored)[1]['falloff_mode'] == 'linear'
        cmds.redo()
        assert not toolkit._guide_ik_resolve_uuid(group_id)
        print('PASS: exact angular linear weights, degree/radian units, smooth/linear switching, stable outputs, frozen consumer values, unchanged joint transform and Undo/Redo.')
    finally:
        if group_id:
            group = toolkit._guide_ik_resolve_uuid(group_id)
            if group:
                toolkit.remove_pose_driver(group,preserve_consumers=True)
        if cmds.namespace(exists=prefix):
            cmds.namespace(removeNamespace=prefix,deleteNamespaceContent=True)
        cmds.currentUnit(angle=angle_unit)
        cmds.namespace(setNamespace=namespace)
        existing = [n for n in selection if cmds.objExists(n)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)


def run_pose_driver_joint_weights():
    """Check joint display plugs evaluate live and clean up with the owned rig."""
    import math
    prefix = 'rtkJointWeightsSmoke_' + uuid.uuid4().hex[:8]
    namespace = cmds.namespaceInfo(currentNamespace=True)
    selection = cmds.ls(selection=True,long=True) or []
    group_id = None
    def angle(degrees):
        return math.radians(degrees) if cmds.currentUnit(query=True,angle=True) in ('rad','radian') else degrees
    try:
        cmds.namespace(setNamespace=':')
        cmds.namespace(addNamespace=prefix)
        joint = cmds.createNode('joint',name=prefix+':arm_L',skipSelect=True)
        cmds.addAttr(joint,longName='upWeight',attributeType='double',defaultValue=.35)
        result = toolkit.build_pose_driver(joint)
        group_id = toolkit._pd_uuid(result['group'])
        cmds.setAttr(joint+'.rotateZ',angle(30))
        first = toolkit.capture_pose_driver_rotation(result['group'],name='up')
        assert first['joint_attributes']['upWeight'] == 'pd_upWeight'
        assert cmds.getAttr(joint+'.upWeight') == .35
        cmds.setAttr(joint+'.rotateZ',angle(70))
        second = toolkit.capture_pose_driver_rotation(result['group'],name='high')
        outputs = toolkit.expose_pose_driver_joint_weights(result['group'])
        assert len(outputs['attributes']) == 4
        for normalize in (0,.5,1):
            toolkit.set_pose_driver_normalize(result['group'],normalize)
            for rotation in (0,20,30,50,70,100):
                cmds.setAttr(joint+'.rotateZ',angle(rotation))
                for record in (first,second):
                    for output,attribute in record['joint_attributes'].items():
                        assert abs(cmds.getAttr(joint+'.'+attribute)-cmds.getAttr(result['cone']+'.'+output))<1e-6
                        assert not cmds.getAttr(joint+'.'+attribute,lock=True)
                        assert cmds.getAttr(joint+'.'+attribute,keyable=True)
                        assert cmds.getAttr(joint+'.'+attribute,channelBox=True)
        before = toolkit._pd_read(result['group'])[1]['poses'][0]['joint_attributes']
        cmds.setAttr(joint+'.rotateZ',angle(40))
        toolkit.update_pose_driver_pose(result['group'],first['id'],recapture=True)
        assert toolkit._pd_read(result['group'])[1]['poses'][0]['joint_attributes'] == before
        toolkit.remove_pose_driver_pose(result['group'],first['id'])
        assert not cmds.attributeQuery('pd_upWeight',node=joint,exists=True)
        assert cmds.getAttr(joint+'.upWeight') == .35
        cmds.undo()
        assert cmds.attributeQuery('pd_upWeight',node=joint,exists=True)
        assert abs(cmds.getAttr(joint+'.pd_upWeight')-cmds.getAttr(result['cone']+'.upWeight'))<1e-6
        matrix = cmds.xform(joint,query=True,worldSpace=True,matrix=True)
        toolkit.remove_pose_driver(result['group'])
        assert not cmds.attributeQuery('pd_upWeight',node=joint,exists=True)
        assert not cmds.attributeQuery('highWeight',node=joint,exists=True)
        assert cmds.getAttr(joint+'.upWeight') == .35
        assert all(abs(a-b)<1e-6 for a,b in zip(matrix,cmds.xform(joint,query=True,worldSpace=True,matrix=True)))
        cmds.undo()
        assert cmds.attributeQuery('highWeight',node=joint,exists=True)
        cmds.redo()
        print('PASS: joint weights live at multiple rotations/Normalize values, name collisions, unlocked/keyable display, stable recapture, owned cleanup, unchanged transform and Undo/Redo.')
    finally:
        if group_id:
            group = toolkit._guide_ik_resolve_uuid(group_id)
            if group:
                toolkit.remove_pose_driver(group)
        if cmds.namespace(exists=prefix):
            cmds.namespace(removeNamespace=prefix,deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace)
        existing = [n for n in selection if cmds.objExists(n)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)


def run_pose_driver_controller_cache():
    """Native controller-driven joint capture, recall, persistence and Undo/Redo."""
    import math
    prefix = 'rtkControllerCacheSmoke_' + uuid.uuid4().hex[:8]
    namespace = cmds.namespaceInfo(currentNamespace=True)
    selection = cmds.ls(selection=True, long=True) or []
    group_id = None
    def angle(value):
        return math.radians(value) if cmds.currentUnit(query=True,angle=True) in ('rad','radian') else value
    def close(actual, expected):
        assert abs(actual-expected) < 2e-5, (actual,expected)
    try:
        cmds.namespace(setNamespace=':')
        cmds.namespace(addNamespace=prefix)
        parent = cmds.createNode('transform',name=prefix+':parent',skipSelect=True)
        controller = cmds.createNode('transform',name=prefix+':driver_CTRL',parent=parent,skipSelect=True)
        cmds.addAttr(controller,longName='curl',attributeType='double',defaultValue=1,keyable=True)
        joint = cmds.createNode('joint',name=prefix+':joint',parent=parent,skipSelect=True)
        cmds.setAttr(joint+'.translateX',3)
        cmds.orientConstraint(controller,joint,maintainOffset=False,name=prefix+':controllerConstraint')
        result = toolkit.build_pose_driver(joint,driver_controller=controller)
        group_id = toolkit._pd_uuid(result['group'])
        controller_id = toolkit._pd_uuid(controller)
        cmds.setAttr(controller+'.rotateY',angle(-70))
        cmds.setAttr(controller+'.curl',1.5)
        pose = toolkit.capture_pose_driver_rotation(result['group'],name='up')
        assert pose['controller_pose']['controller'] == controller_id
        assert controller_id not in toolkit._pd_read(result['group'])[1]['members']
        cmds.setAttr(controller+'.rotateY',0)
        cmds.setAttr(controller+'.curl',1)
        toolkit.goto_pose_driver_pose(result['group'],pose['id'])
        close(cmds.getAttr(controller+'.rotateY'),angle(-70))
        close(cmds.getAttr(controller+'.curl'),1.5)
        close(cmds.getAttr(result['cone']+'.upWeightRaw'),1)
        close(cmds.getAttr(joint+'.upWeight'),1)
        cmds.undo()
        close(cmds.getAttr(controller+'.rotateY'),0)
        close(cmds.getAttr(controller+'.curl'),1)
        cmds.redo()
        close(cmds.getAttr(controller+'.rotateY'),angle(-70))
        cmds.setAttr(controller+'.curl',1.8)
        toolkit.cache_pose_driver_controller_pose(result['group'],pose['id'])
        toolkit.goto_pose_driver_pose(result['group'])
        close(cmds.getAttr(controller+'.rotateY'),0)
        close(cmds.getAttr(controller+'.curl'),1)
        controller = cmds.rename(controller,prefix+':renamed_CTRL')
        restored = toolkit.goto_pose_driver_pose(result['group'],pose['id'])
        assert toolkit._pd_uuid(restored['controller']) == controller_id
        close(cmds.getAttr(controller+'.curl'),1.8)
        curve = cmds.createNode('animCurveTA',name=prefix+':animatedInput',skipSelect=True)
        cmds.connectAttr(curve+'.output',controller+'.rotateY')
        before = cmds.getAttr(controller+'.curl')
        try:
            toolkit.goto_pose_driver_pose(result['group'],pose['id'])
        except ValueError as exc:
            assert 'animated or driven' in str(exc)
        else:
            raise AssertionError('Animated controller input must be preserved.')
        assert cmds.isConnected(curve+'.output',controller+'.rotateY')
        close(cmds.getAttr(controller+'.curl'),before)
        toolkit.remove_pose_driver(result['group'])
        assert cmds.objExists(controller) and cmds.objExists(joint)
        assert cmds.isConnected(curve+'.output',controller+'.rotateY')
        print('PASS: real controller-driven joint, automatic per-pose/default caches, live recall, custom attributes, rename resolution, Undo/Redo, animated-input protection and controller survival after removal.')
    finally:
        if group_id:
            group = toolkit._guide_ik_resolve_uuid(group_id)
            if group:
                toolkit._guide_ik_delete_owned(toolkit._pd_read(group)[1]['members'])
        if cmds.namespace(exists=prefix):
            cmds.namespace(removeNamespace=prefix,deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace)
        existing = [n for n in selection if cmds.objExists(n)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)


def run_pose_driver_auto_falloff():
    """Native auto-angle defaults, linear Y70 sweep and stable update outputs."""
    import math
    prefix = 'rtkAutoFalloffSmoke_' + uuid.uuid4().hex[:8]
    namespace = cmds.namespaceInfo(currentNamespace=True)
    selection = cmds.ls(selection=True, long=True) or []
    group_id = None
    def angle(value):
        return math.radians(value) if cmds.currentUnit(query=True,angle=True) in ('rad','radian') else value
    def close(actual, expected):
        assert abs(actual-expected) < 2e-5, (actual,expected)
    try:
        cmds.namespace(setNamespace=':')
        cmds.namespace(addNamespace=prefix)
        parent = cmds.createNode('transform',name=prefix+':parent',skipSelect=True)
        cmds.setAttr(parent+'.rotateZ',angle(23))
        joint = cmds.createNode('joint',name=prefix+':driver',parent=parent,skipSelect=True)
        cmds.setAttr(joint+'.jointOrientZ',angle(17))
        cmds.setAttr(joint+'.translateX',3)
        cmds.setAttr(joint+'.rotateY',angle(10))
        result = toolkit.build_pose_driver(joint)
        group_id = toolkit._pd_uuid(result['group'])
        cmds.setAttr(joint+'.rotateY',angle(80))
        pose = toolkit.capture_pose_driver_rotation(result['group'],name='up')
        assert pose['radius_mode'] == 'auto'
        close(pose['radius'],70)
        assert toolkit._pd_read(result['group'])[1]['falloff_mode'] == 'linear'
        close(cmds.getAttr(result['cone']+'.normalize'),0)
        for rotation,expected in ((10,0),(27.5,.25),(45,.5),(62.5,.75),(80,1)):
            cmds.setAttr(joint+'.rotateY',angle(rotation))
            close(cmds.getAttr(result['cone']+'.upWeightRaw'),expected)
            close(cmds.getAttr(result['cone']+'.upWeight'),expected)
            close(cmds.getAttr(joint+'.upWeight'),expected)
        consumer = cmds.createNode('multiplyDivide',name=prefix+':receiver',skipSelect=True)
        cmds.connectAttr(joint+'.upWeight',consumer+'.input1X')
        output = cmds.listConnections(result['cone']+'.upWeight',source=True,destination=False,plugs=True)
        cmds.setAttr(joint+'.rotateY',angle(110))
        updated = toolkit.capture_pose_driver_rotation(result['group'],pose_id=pose['id'])
        close(updated['radius'],100)
        assert updated['id'] == pose['id'] and updated['nodes'] == pose['nodes']
        assert cmds.listConnections(result['cone']+'.upWeight',source=True,destination=False,plugs=True) == output
        cmds.setAttr(joint+'.rotateY',angle(60))
        close(cmds.getAttr(consumer+'.input1X'),.5)
        toolkit.update_pose_driver_pose(result['group'],pose['id'],radius=33)
        assert toolkit._pd_read(result['group'])[1]['poses'][0]['radius_mode'] == 'manual'
        cmds.setAttr(joint+'.rotateY',angle(130))
        updated = toolkit.capture_pose_driver_rotation(result['group'],pose_id=pose['id'])
        close(updated['radius'],33)
        target = cmds.createNode('transform',name=prefix+':target',skipSelect=True)
        state = toolkit._pd_read(result['group'])[1]
        frame = toolkit._pd_node(state['frame'])
        matrix = cmds.xform(frame,query=True,worldSpace=True,matrix=True)
        origin = cmds.xform(frame,query=True,worldSpace=True,translation=True)
        ray = toolkit._pd_frame_vector(matrix,(0,1,0))
        cmds.xform(target,worldSpace=True,translation=[a+25*b for a,b in zip(origin,ray)])
        external = toolkit.add_pose_driver_pose(result['group'],'external',center=target)
        close(external['radius'],90)
        assert external['radius_mode'] == 'auto'
        cmds.undo()
        assert len(toolkit._pd_read(result['group'])[1]['poses']) == 1
        cmds.redo()
        assert len(toolkit._pd_read(result['group'])[1]['poses']) == 2
        print('PASS: automatic default-to-target angles, linear 70-degree sweep, joint outputs, stable recapture/consumer links, manual override, object capture and Undo/Redo.')
    finally:
        if group_id:
            group = toolkit._guide_ik_resolve_uuid(group_id)
            if group:
                toolkit._guide_ik_delete_owned(toolkit._pd_read(group)[1]['members'])
        if cmds.namespace(exists=prefix):
            cmds.namespace(removeNamespace=prefix,deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace)
        existing = [n for n in selection if cmds.objExists(n)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)


def run_pose_driver_rotations():
    """Native separated rotation capture, naming/defaults and live evaluation."""
    import math
    prefix = 'rtkRotationSmoke_' + uuid.uuid4().hex[:8]
    namespace = cmds.namespaceInfo(currentNamespace=True)
    selection = cmds.ls(selection=True, long=True) or []
    group_id = None
    def angle(value):
        return math.radians(value) if cmds.currentUnit(query=True,angle=True) in ('rad','radian') else value
    def pose(joint, values):
        for axis,value in zip('XYZ',values):
            cmds.setAttr(joint+'.rotate'+axis,angle(value))
    try:
        cmds.namespace(setNamespace=':')
        cmds.namespace(addNamespace=prefix)
        parent = cmds.createNode('transform',name=prefix+':parent',skipSelect=True)
        joint = cmds.createNode('joint',name=prefix+':arm_L',parent=parent,skipSelect=True)
        cmds.setAttr(joint+'.jointOrientY',angle(12))
        cmds.setAttr(joint+'.translateX',3)
        pose(joint,(5,15,10))
        result = toolkit.build_pose_driver(joint)
        group_id = toolkit._pd_uuid(result['group'])
        default = toolkit._pd_read(result['group'])[1]['default_rotation_degrees']
        assert all(abs(a-b)<1e-5 for a,b in zip(default,(5,15,10)))
        for values in ((5,15,10),(50,15,10),(5,20,10)):
            pose(joint,values)
            before = set(cmds.ls(long=True))
            try:
                toolkit.capture_pose_driver_rotation(result['group'])
                raise AssertionError('Default, X twist or close direction must be rejected.')
            except ValueError:
                pass
            assert set(cmds.ls(long=True)) == before
        pose(joint,(-15,45,10))
        first = toolkit.capture_pose_driver_rotation(result['group'])
        assert first['name'] == 'arm_L_nX20_pY30_pZ0'
        assert abs(cmds.getAttr(result['cone']+'.'+first['attribute']+'Raw')-1)<2e-5
        pose(joint,(-15,50,10))
        try:
            toolkit.capture_pose_driver_rotation(result['group'])
            raise AssertionError('Pose near an existing pose must be rejected.')
        except ValueError:
            pass
        cmds.setAttr(parent+'.rotateZ',angle(20))
        pose(joint,(5,15,10))
        try:
            toolkit.capture_pose_driver_rotation(result['group'])
            raise AssertionError('Parent motion must not turn the default into a target.')
        except ValueError:
            pass
        pose(joint,(5,15,40))
        second = toolkit.capture_pose_driver_rotation(result['group'],minimum_angle=15,radius=60)
        assert second['name'] == 'arm_L_pX0_pY0_pZ30'
        assert abs(cmds.getAttr(result['cone']+'.'+second['attribute']+'Raw')-1)<2e-5
        cmds.undo()
        assert len(toolkit._pd_read(result['group'])[1]['poses']) == 1
        cmds.redo()
        assert len(toolkit._pd_read(result['group'])[1]['poses']) == 2
        print('PASS: PoseDriver rotation/default capture, minimum separation, naming, X-twist rejection, jointOrient, parent motion, live weights and Undo/Redo.')
    finally:
        if group_id:
            group = toolkit._guide_ik_resolve_uuid(group_id)
            if group:
                toolkit._guide_ik_delete_owned(toolkit._pd_read(group)[1]['members'])
        if cmds.namespace(exists=prefix):
            cmds.namespace(removeNamespace=prefix,deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace)
        existing = [n for n in selection if cmds.objExists(n)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)


def run_pose_driver_mirror():
    """Native mirror search, graph evaluation, stable updates and Undo/Redo."""
    import math
    prefix = 'rtkMirrorSmoke_' + uuid.uuid4().hex[:8]
    namespace = cmds.namespaceInfo(currentNamespace=True)
    selection = cmds.ls(selection=True, long=True) or []
    groups = []
    try:
        cmds.namespace(setNamespace=':')
        cmds.namespace(addNamespace=prefix)
        left = cmds.createNode('joint', name=prefix+':arm_L', skipSelect=True)
        right = cmds.createNode('joint', name=prefix+':arm_R', skipSelect=True)
        cmds.setAttr(left+'.translateX', 3)
        cmds.setAttr(right+'.translateX', -3)
        target_l = cmds.createNode('transform', name=prefix+':pose_L', skipSelect=True)
        target_r = cmds.createNode('transform', name=prefix+':pose_R', skipSelect=True)
        cmds.xform(target_l, worldSpace=True, translation=(3,5,0))
        cmds.xform(target_r, worldSpace=True, translation=(-3,0,5))
        source = toolkit.build_pose_driver(left, axis=1)
        groups.append(toolkit._pd_uuid(source['group']))
        toolkit.add_pose_driver_pose(source['group'], 'up_L', center=target_l, radius=40)
        before = set(cmds.ls(long=True))
        plan = toolkit.plan_pose_driver_mirror(source['group'])
        assert set(cmds.ls(long=True)) == before, 'Preview mutated the scene.'
        assert toolkit._pd_uuid(plan['joint']) == toolkit._pd_uuid(right)
        result = toolkit.mirror_pose_driver(source['group'])
        groups.append(toolkit._pd_uuid(result['group']))
        state = toolkit._pd_read(result['group'])[1]
        cone = toolkit._pd_node(state['cone'])
        record = state['poses'][0]
        center = toolkit._pd_node(record['center'])
        assert state['axis'] == -1 and cmds.getAttr(cone+'.translateX') == -1
        assert all(abs(a-b)<1e-5 for a,b in zip(cmds.xform(center,query=True,worldSpace=True,translation=True),(-3,0,1)))
        angle = math.pi/2 if cmds.currentUnit(query=True,angle=True)=='rad' else 90
        cmds.setAttr(right+'.rotateY', angle)
        assert abs(cmds.getAttr(cone+'.up_RWeightRaw')-1)<1e-5, 'Mirrored target weight did not evaluate.'
        consumer = cmds.createNode('transform', name=prefix+':consumer', skipSelect=True)
        cmds.addAttr(consumer,longName='weight',attributeType='double')
        cmds.connectAttr(cone+'.up_RWeight',consumer+'.weight')
        driver = cmds.connectionInfo(cone+'.up_RWeight',sourceFromDestination=True)
        cmds.xform(target_r,worldSpace=True,translation=(-3,5,0))
        again = toolkit.mirror_pose_driver(source['group'])
        updated = toolkit._pd_read(again['group'])[1]
        assert updated['poses'][0]['id'] == record['id']
        assert updated['poses'][0]['nodes'] == record['nodes']
        assert cmds.connectionInfo(cone+'.up_RWeight',sourceFromDestination=True) == driver
        exported = cmds.connectionInfo(consumer+'.weight',sourceFromDestination=True)
        exported_node, exported_attribute = exported.rsplit('.',1)
        assert toolkit._pd_uuid(exported_node) == state['cone'] and exported_attribute == 'up_RWeight'
        assert all(abs(a-b)<1e-5 for a,b in zip(cmds.xform(center,query=True,worldSpace=True,translation=True),(-3,1,0)))
        cmds.undo()
        assert all(abs(a-b)<1e-5 for a,b in zip(cmds.xform(center,query=True,worldSpace=True,translation=True),(-3,0,1)))
        cmds.redo()
        cmds.setAttr(right+'.rotateY',0)
        cmds.setAttr(right+'.rotateZ',-angle)
        assert abs(cmds.getAttr(cone+'.up_RWeightRaw')-1)<1e-5
        back = toolkit.mirror_pose_driver(result['group'], search='_R', replace='_L')
        assert toolkit._pd_uuid(back['group']) == groups[0]
        assert toolkit._pd_read(back['group'])[1]['axis'] == 1
        print('PASS: PoseDriver mirror preview, target search, signed axis flip, native weights, stable output consumers, reverse update and Undo/Redo.')
    finally:
        # Utility nodes are world-rooted and must be explicitly removed too.
        for identity in groups:
            group = toolkit._guide_ik_resolve_uuid(identity)
            if group:
                toolkit._guide_ik_delete_owned(toolkit._pd_read(group)[1]['members'])
        if cmds.namespace(exists=prefix):
            cmds.namespace(removeNamespace=prefix,deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace)
        existing = [n for n in selection if cmds.objExists(n)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)


def run():
    prefix = 'rtkSmoke_' + uuid.uuid4().hex[:8]
    selection = cmds.ls(selection=True, long=True) or []
    current_namespace = cmds.namespaceInfo(currentNamespace=True)
    namespaces = [prefix, prefix + ':src', prefix + ':dst']
    window = None
    locator_view_groups = []
    try:
        cmds.namespace(setNamespace=':')
        for namespace in namespaces:
            cmds.namespace(add=namespace)
        mesh = cmds.polyPlane(name=prefix + ':mesh', sx=1, sy=1, constructionHistory=False)[0]
        src1 = cmds.createNode('joint', name=prefix + ':src:root', skipSelect=True)
        gap = cmds.createNode('joint', name=prefix + ':gap', skipSelect=True)
        dst1 = cmds.createNode('joint', name=prefix + ':dst:root', skipSelect=True)
        src2 = cmds.createNode('joint', name=prefix + ':src:arm', skipSelect=True)
        dst2 = cmds.createNode('joint', name=prefix + ':dst:arm', skipSelect=True)
        skin = cmds.skinCluster([src1, gap, dst1, src2], mesh, name=prefix + ':skin', toSelectedBones=True)[0]
        cmds.skinCluster(skin, edit=True, removeInfluence=gap)
        for joint in (src1, src2, dst1, dst2):
            cmds.setAttr(joint + '.liw', False)
        components = mesh + '.vtx[*]'
        cmds.skinPercent(skin, components, transformValue=[(src1, .3), (dst1, .2), (src2, .5)])
        toolkit.transfer_namespace_weights(mesh, prefix + ':src', prefix + ':dst', remove_src=True)
        vtx = mesh + '.vtx[0]'
        assert abs(cmds.skinPercent(skin, vtx, query=True, transform=dst1) - .5) < 1e-6
        assert abs(cmds.skinPercent(skin, vtx, query=True, transform=dst2) - .5) < 1e-6
        assert len(cmds.skinCluster(skin, query=True, influence=True)) == 2
        cmds.undo()
        assert len(cmds.skinCluster(skin, query=True, influence=True)) == 3
        assert abs(cmds.skinPercent(skin, vtx, query=True, transform=src1) - .3) < 1e-6
        assert abs(cmds.skinPercent(skin, vtx, query=True, transform=dst1) - .2) < 1e-6
        cmds.redo()
        assert abs(cmds.skinPercent(skin, vtx, query=True, transform=dst1) - .5) < 1e-6
        assert len(cmds.skinCluster(skin, query=True, influence=True)) == 2

        old_root = cmds.createNode('transform', name=prefix + ':oldHierarchy', skipSelect=True)
        new_root = cmds.createNode('transform', name=prefix + ':newHierarchy', skipSelect=True)
        old_child = cmds.createNode('joint', name=prefix + ':src:spine', parent=old_root, skipSelect=True)
        new_child = cmds.createNode('joint', name=prefix + ':dst:spine', parent=new_root, skipSelect=True)
        cmds.createNode('joint', name=prefix + ':src:tip', parent=old_child, skipSelect=True)
        cmds.createNode('joint', name=prefix + ':dst:tip', parent=new_child, skipSelect=True)
        plan = toolkit.plan_matching_hierarchies(old_root, new_root)
        assert len(plan['rows']) == 3
        result = toolkit.constrain_matching_hierarchies(old_root, new_root)
        constraint_nodes = result['constraints'][:]
        assert len(result['created_pairs']) == 3 and len(constraint_nodes) == 6
        repeated = toolkit.constrain_matching_hierarchies(old_root, new_root)
        assert len(repeated['created_pairs']) == 0 and len(repeated['skipped']) == 3
        before = cmds.xform(new_root, query=True, worldSpace=True, translation=True)[0]
        cmds.setAttr(old_root + '.translateX', 2.0)
        after = cmds.xform(new_root, query=True, worldSpace=True, translation=True)[0]
        assert abs(after - before - 2.0) < 1e-6, 'Old root must drive the new root.'
        cmds.undo()  # Undo the driver movement first.
        cmds.undo()  # Undo the entire hierarchy constraint action.
        assert all(not cmds.objExists(node) for node in constraint_nodes)
        cmds.redo()
        assert all(cmds.objExists(node) for node in constraint_nodes)

        attr_source = cmds.createNode('transform', name=prefix + ':attrSource', skipSelect=True)
        attr_target = cmds.createNode('transform', name=prefix + ':attrTarget', skipSelect=True)
        cmds.addAttr(attr_source, longName='ikBlend', niceName='IK FK Blend', attributeType='double',
                     minValue=0.0, maxValue=1.0, defaultValue=.5, keyable=True)
        cmds.setAttr(attr_source + '.ikBlend', .75)
        cmds.addAttr(attr_source, longName='space', attributeType='enum', enumName='World=0:Body=5', defaultValue=5, keyable=True)
        cmds.setAttr(attr_source + '.space', 5)
        cmds.addAttr(attr_source, longName='note', dataType='string')
        cmds.setAttr(attr_source + '.note', 'Controller settings', type='string')
        cmds.addAttr(attr_source, longName='offset', attributeType='double3')
        for axis,value in zip('XYZ', (1.0,2.0,3.0)):
            cmds.addAttr(attr_source, longName='offset'+axis, attributeType='double', parent='offset', keyable=True)
            cmds.setAttr(attr_source + '.offset'+axis, value)
        attribute_result = toolkit.copy_custom_attributes_and_connect(attr_source, attr_target)
        assert len(attribute_result['created']) == 4 and len(attribute_result['connected']) == 6
        assert cmds.isConnected(attr_target + '.ikBlend', attr_source + '.ikBlend')
        assert abs(cmds.getAttr(attr_target + '.ikBlend') - .75) < 1e-6
        assert cmds.attributeQuery('space', node=attr_target, listEnum=True) == cmds.attributeQuery('space', node=attr_source, listEnum=True)
        assert cmds.attributeQuery('ikBlend', node=attr_target, listDefault=True) == [.5]
        assert cmds.attributeQuery('ikBlend', node=attr_target, minimum=True) == [0.0]
        assert cmds.getAttr(attr_target + '.note') == 'Controller settings'
        assert cmds.getAttr(attr_target + '.offsetY') == 2.0
        assert not cmds.isConnected(attr_target + '.translateX', attr_source + '.translateX')
        cmds.setAttr(attr_target + '.ikBlend', .25)
        assert abs(cmds.getAttr(attr_source + '.ikBlend') - .25) < 1e-6
        cmds.undo()  # Undo target value edit.
        cmds.undo()  # Undo attribute creation and all connections in one step.
        assert not cmds.attributeQuery('ikBlend', node=attr_target, exists=True)
        assert not cmds.attributeQuery('offset', node=attr_target, exists=True)
        assert abs(cmds.getAttr(attr_source + '.ikBlend') - .75) < 1e-6
        cmds.redo()
        assert cmds.isConnected(attr_target + '.ikBlend', attr_source + '.ikBlend')

        cmds.select(clear=True)
        window = toolkit.show()
        assert len(window._pages) == 1, 'Window must create only the restored workflow initially.'
        for key, _label, _description, _keywords in window.WORKFLOWS:
            window.select_workflow(key)
            assert key in window._pages, 'Failed to construct page: ' + key
        assert len(window._pages) == 10
        hierarchy_panel = window._pages['hierarchy'].widget()
        hierarchy_panel.old_root_field.setText(old_root)
        hierarchy_panel.new_root_field.setText(new_root)
        hierarchy_panel._preview()
        assert hierarchy_panel.table.topLevelItemCount() == 3
        assert not hierarchy_panel.create_button.isEnabled(), 'Existing target constraints must be reported as blocked.'
        custom_panel = window._pages['custom_attributes'].widget()
        custom_panel.source_field.setText(attr_source)
        custom_panel.target_field.setText(attr_target)
        custom_panel._scan()
        assert custom_panel.table.topLevelItemCount() == 4
        assert not custom_panel.apply_button.isEnabled(), 'Already connected attributes should need no repeat action.'
        guide_panel = window._pages['guides'].widget()
        cmds.select(old_child, replace=True)
        guide_panel._load_locator_view_joint()
        assert guide_panel.le_locator_view_joint.text() == cmds.ls(old_child, long=True)[0]
        guide_panel.spn_locator_view_size.setValue(.4)
        guide_panel.cb_locator_view_match.setCurrentIndex(1)  # World-matrix snapshot.
        guide_panel._generate_locator_view()
        locator_view_groups.extend(toolkit.find_locator_view_groups(old_child))
        assert len(locator_view_groups) == 1
        guide_panel._delete_locator_view()
        assert not toolkit.find_locator_view_groups(old_child)
        hosts = list(window.unified_tool.hosts.values())
        jobs = window._jobs[:]
        assert len(hosts) == 5
        window.close()
        assert window._closed
        # Host deletion now occurs on Maya idle, after the close event returns.
        _verify_closed_hosts_later(hosts)
        assert all(not cmds.scriptJob(exists=job) for job in jobs)
        window = toolkit.show()
        assert len(window._pages) == 1
        run_locator_view()
        print('PASS: native feature checks. Deferred host cleanup verification is pending; run_close_cycles() tests repeated teardown.')
    finally:
        if window is not None and toolkit.shiboken.isValid(window):
            window.close()
        existing_views = [group for group in locator_view_groups if cmds.objExists(group)]
        if existing_views:
            cmds.delete(existing_views)
        nodes = cmds.ls(prefix + ':*', recursive=True, long=True) or []
        if nodes:
            cmds.delete(nodes)
        for namespace in reversed(namespaces):
            if cmds.namespace(exists=namespace):
                cmds.namespace(removeNamespace=namespace, mergeNamespaceWithRoot=True)
        cmds.namespace(setNamespace=current_namespace)
        existing = [node for node in selection if cmds.objExists(node)]
        if existing:
            cmds.select(existing, replace=True)
        else:
            cmds.select(clear=True)


def run_locator_view():
    """Run just the real-Maya Locator View checks, without the other workflows."""
    prefix = 'rtkLocatorSmoke_' + uuid.uuid4().hex[:8]
    selection = cmds.ls(selection=True, long=True) or []
    current_namespace = cmds.namespaceInfo(currentNamespace=True)
    generated_groups = []
    try:
        cmds.namespace(setNamespace=':')
        cmds.namespace(add=prefix)
        rig = cmds.createNode('transform', name=prefix+':rig', skipSelect=True)
        root = cmds.createNode('joint', name=prefix+':root', parent=rig, skipSelect=True)
        child = cmds.createNode('joint', name=prefix+':child', parent=root, skipSelect=True)
        cmds.createNode('joint', name=prefix+':tip', parent=child, skipSelect=True)
        cmds.setAttr(rig+'.scale', 1.25,1.25,1.25, type='double3')
        cmds.setAttr(root+'.translate', 2,3,4, type='double3')
        cmds.setAttr(root+'.rotate', 15,25,35, type='double3')
        cmds.setAttr(child+'.translateX', 5)
        cmds.select(root, replace=True)
        selected = cmds.ls(selection=True, long=True)

        snapshot = toolkit.generate_locator_view(root, size=.25, match_mode='world_matrix')
        generated_groups.append(snapshot['group'])
        assert len(snapshot['locators']) == 1 and not snapshot['constraints']
        locator = snapshot['locators'][0]
        matrix = cmds.xform(root, query=True, worldSpace=True, matrix=True)
        actual = cmds.xform(locator, query=True, worldSpace=True, matrix=True)
        assert max(abs(a-b) for a,b in zip(matrix,actual)) < 1e-5
        shape = cmds.listRelatives(locator, shapes=True, type='locator', fullPath=True)[0]
        for axis in 'XYZ':
            assert abs(cmds.getAttr(shape+'.localScale'+axis)-.25) < 1e-6
        assert cmds.ls(selection=True, long=True) == selected
        cmds.setAttr(root+'.translateX', 10)
        actual = cmds.xform(locator, query=True, worldSpace=True, matrix=True)
        assert max(abs(a-b) for a,b in zip(matrix,actual)) < 1e-5, 'Snapshot must stay fixed.'
        cmds.undo()  # Undo joint movement.
        cmds.undo()  # Undo snapshot generation.
        assert not cmds.objExists(snapshot['group'])
        cmds.redo()
        assert cmds.objExists(snapshot['group'])

        following = toolkit.generate_locator_view(root, size=.6, include_children=True)
        generated_groups.append(following['group'])
        assert len(following['locators']) == 3 and len(following['constraints']) == 6
        assert not cmds.objExists(snapshot['group']), 'Regeneration must replace the old view.'
        assert all(cmds.listRelatives(loc,parent=True,fullPath=True) == [following['group']]
                   for loc in following['locators'])
        cmds.undo()
        assert cmds.objExists(snapshot['group']) and not cmds.objExists(following['group'])
        cmds.redo()
        assert not cmds.objExists(snapshot['group']) and cmds.objExists(following['group'])
        cmds.setAttr(root+'.translateX', 7)
        matrix = cmds.xform(root, query=True, worldSpace=True, matrix=True)
        actual = cmds.xform(following['locators'][0], query=True, worldSpace=True, matrix=True)
        assert max(abs(a-b) for a,b in zip(matrix,actual)) < 1e-5, 'Constraint view must follow the root.'
        legacy = cmds.spaceLocator(name=prefix+':legacy_GuideLoc')[0]
        foreign = cmds.createNode('transform', name=prefix+':foreign', parent=following['group'], skipSelect=True)
        try:
            toolkit.delete_locator_view(root)
            raise AssertionError('Deletion must refuse foreign descendants.')
        except ValueError:
            pass
        cmds.parent(foreign, world=True)
        deleted = toolkit.delete_locator_view(root)
        assert deleted == [following['group']]
        assert not cmds.objExists(following['group'])
        assert cmds.objExists(root) and cmds.objExists(legacy) and cmds.objExists(foreign)
        cmds.undo()
        assert cmds.objExists(following['group'])
        cmds.redo()
        assert not cmds.objExists(following['group'])
        print('PASS: Locator View matrix/size, joint scope, flat grouping, constraints, replacement, ownership checks, selection, Undo/Redo.')
    finally:
        existing = list(dict.fromkeys(group for group in generated_groups if cmds.objExists(group)))
        if existing:
            cmds.delete(existing)
        nodes = cmds.ls(prefix+':*', recursive=True, long=True) or []
        if nodes:
            cmds.delete(nodes)
        if cmds.namespace(exists=prefix):
            cmds.namespace(removeNamespace=prefix, mergeNamespaceWithRoot=True)
        cmds.namespace(setNamespace=current_namespace)
        existing = [node for node in selection if cmds.objExists(node)]
        cmds.select(existing, replace=True) if existing else cmds.select(clear=True)


def _verify_closed_hosts_later(hosts):
    """Verify idle cleanup without forcing nested event processing inside close()."""
    state = {"finished": False, "error": None}

    def check(attempt=0):
        if toolkit._maya_is_exiting():
            state["error"] = "Maya exited before host cleanup verification completed."
            state["finished"] = True
            return
        if any(cmds.window(host, exists=True) for host in hosts):
            if attempt < 200:
                toolkit.QtCore.QTimer.singleShot(25, lambda: check(attempt + 1))
                return
            state["error"] = "Native UI host cleanup did not finish while Maya was idle."
            cmds.warning(state["error"])
        else:
            print("PASS: deferred Rigging Toolkit host cleanup.")
        state["finished"] = True

    toolkit.QtCore.QTimer.singleShot(25, check)
    return state


def run_close_cycles(cycles=5):
    """Asynchronously open all pages and close them repeatedly in interactive Maya.

    Does not quit Maya, open a new scene, or create rig/mesh fixture nodes. It
    retains normal idle/event ordering rather than forcing nested Qt events.
    """
    if not isinstance(cycles, int) or cycles < 1:
        raise ValueError("cycles must be a positive integer.")
    state = {"completed": 0, "running": True, "error": None}
    print("Testing toolkit close/reopen on Maya {}, Qt {}.".format(cmds.about(version=True), toolkit.QtCore.qVersion()))

    def fail(exc):
        state["running"] = False
        state["error"] = str(exc)
        if not toolkit._maya_is_exiting():
            cmds.warning("Close-cycle test failed: {}".format(exc))

    def begin_cycle():
        if toolkit._maya_is_exiting():
            fail("Maya is shutting down.")
            return
        try:
            window = toolkit.show()
            assert not window.testAttribute(toolkit.QtCore.Qt.WA_DeleteOnClose)
            assert not window.testAttribute(toolkit.QtCore.Qt.WA_QuitOnClose)
            for key, _label, _description, _keywords in window.WORKFLOWS:
                window.select_workflow(key)
                assert key in window._pages, "Page failed to open: " + key
            hosts = tuple(window.unified_tool.hosts.values())
            native_pages = tuple(window.unified_tool.pages.values())
            jobs = tuple(window._jobs)
            assert len(hosts) == 5
            assert all(toolkit._qt_object_valid(parent) for parent in window.unified_tool.original_parents.values())
            window.close()
            assert window._closed
            assert all(not cmds.scriptJob(exists=job) for job in jobs)
        except Exception as exc:
            fail(exc)
            return

        def verify(attempt=0):
            if toolkit._maya_is_exiting():
                fail("Maya is shutting down.")
                return
            try:
                pending = (any(cmds.window(host, exists=True) for host in hosts)
                           or any(toolkit._qt_object_valid(page) for page in native_pages))
                if pending:
                    if attempt >= 200:
                        raise AssertionError("Native hosts/widgets remained alive after close while Maya was idle.")
                    toolkit.QtCore.QTimer.singleShot(25, lambda: verify(attempt + 1))
                    return
                state["completed"] += 1
                print("PASS: toolkit close/reopen cycle {}/{}.".format(state["completed"], cycles))
                if state["completed"] < cycles:
                    toolkit.QtCore.QTimer.singleShot(25, begin_cycle)
                else:
                    state["running"] = False
                    print("PASS: all close cycles completed; native hosts and widgets were released.")
            except Exception as exc:
                fail(exc)

        toolkit.QtCore.QTimer.singleShot(25, verify)

    begin_cycle()
    return state


def run_guide_ik():
    """Native Maya IK/pose/ownership/undo checks in an isolated test namespace."""
    prefix = 'rtkIKSmoke_' + uuid.uuid4().hex[:8]
    selection = cmds.ls(selection=True, long=True) or []
    current_namespace = cmds.namespaceInfo(currentNamespace=True)
    systems = []
    foreign = None
    joints = []

    def position(node):
        return cmds.xform(node, query=True, worldSpace=True, translation=True)

    def near(a, b, tolerance=1e-4):
        return all(abs(x-y) < tolerance for x,y in zip(a,b))

    try:
        cmds.namespace(setNamespace=':')
        cmds.namespace(add=prefix)
        for index, point in enumerate(((1,2,3), (4,4,3), (9,2,3))):
            options = {'name':prefix+':joint'+str(index+1), 'skipSelect':True}
            if joints:
                options['parent'] = joints[-1]
            joint = cmds.createNode('joint', **options)
            joint = cmds.ls(joint, long=True)[0]
            cmds.xform(joint, worldSpace=True, translation=point)
            joints.append(joint)
        cmds.joint(joints[0], edit=True, orientJoint='xyz', secondaryAxisOrient='yup', children=True, zeroScaleOrient=True)
        original_positions = [position(j) for j in joints]
        original_rotations = [cmds.getAttr(j+'.rotate')[0] for j in joints]
        cmds.select(joints[1], replace=True)
        result = toolkit.build_guide_ik(*joints, control_size=.8, pole_distance=.7)
        systems.append(result['group'])
        for joint, expected in zip(joints, original_positions):
            assert near(position(joint), expected), 'Building IK changed the initial joint positions.'
        assert cmds.ls(selection=True, long=True) == [joints[1]]
        state = toolkit._check_guide_ik_removal(result['group'])[0]
        members = state['members'][:]
        assert any(cmds.nodeType(toolkit._guide_ik_resolve_uuid(i)) == 'ikEffector' for i in members)
        assert near(position(result['pole_controller']), result['pole_position'])
        assert all(not n.startswith(result['group']+'|') for n in joints)
        cmds.undo()  # Build is one undo step.
        assert all(not cmds.ls(i, long=True) for i in members)
        for joint, expected in zip(joints, original_positions):
            assert near(position(joint), expected)
        cmds.redo()
        assert cmds.objExists(result['group'])

        goal = (8.5, 2.5, 3.5)
        with toolkit._tool_action('SmokeMoveGuideIKControls'):
            cmds.xform(result['end_controller'], worldSpace=True, translation=goal)
            cmds.setAttr(result['end_controller']+'.rotateZ', 12)
            pv = position(result['pole_controller'])
            cmds.xform(result['pole_controller'], worldSpace=True, translation=(pv[0], pv[1], pv[2]+3))
        assert near(position(joints[2]), goal), 'End control did not move the tip joint.'
        assert abs(position(joints[1])[2]-original_positions[1][2]) > .01, 'Pole control did not change the bend plane.'
        assert not near(cmds.getAttr(joints[2]+'.rotate')[0], original_rotations[2]), 'End control rotation did not drive third-joint orientation.'
        cmds.undo()
        assert near(position(joints[2]), original_positions[2])
        cmds.redo()
        assert near(position(joints[2]), goal)

        # A user object parented into generated controls must block deletion.
        foreign = cmds.createNode('transform', name=prefix+':userObject', parent=result['group'])
        try:
            toolkit.remove_guide_ik(joints[0])
            raise AssertionError('Removal deleted a system with a foreign member.')
        except ValueError:
            assert cmds.objExists(result['group']) and cmds.objExists(foreign)
        foreign = cmds.parent(foreign, world=True)[0]

        # Member UUIDs and first-joint message link survive renaming and reparenting.
        group_uuid = toolkit._guide_ik_uuid(result['group'])
        cmds.rename(result['group'], prefix+':renamedIKGroup')
        first_uuid = toolkit._guide_ik_uuid(joints[0])
        cmds.rename(joints[0], prefix+':renamedFirstJoint')
        joints[0] = toolkit._guide_ik_resolve_uuid(first_uuid)
        joints = [toolkit._guide_ik_resolve_uuid(r['uuid']) for r in state['joints']]
        current_matrices = [cmds.xform(j,query=True,worldSpace=True,matrix=True) for j in joints]
        current_orients = [cmds.getAttr(j+'.jointOrient')[0] for j in joints]
        # Common rigs lock translation/scale. Removal should only write rotate.
        for j in joints:
            for attr in ('translateX','translateY','translateZ','scaleX','scaleY','scaleZ'):
                cmds.setAttr(j+'.'+attr,lock=True)
        removed = toolkit.remove_guide_ik(joints[0])
        assert len(removed) == 1
        assert all(not cmds.ls(i, long=True) for i in members)
        joints = [toolkit._guide_ik_resolve_uuid(r['uuid']) for r in state['joints']]
        for joint, expected, orient in zip(joints, current_matrices, current_orients):
            assert near(cmds.xform(joint,query=True,worldSpace=True,matrix=True), expected), 'Remove changed the current joint world pose.'
            assert near(cmds.getAttr(joint+'.jointOrient')[0], orient), 'Remove changed jointOrient.'
        assert cmds.objExists(foreign)
        cmds.undo()  # Undo the complete removal, including external effector.
        assert toolkit._guide_ik_resolve_uuid(group_uuid)
        assert near(position(joints[2]), goal)
        cmds.redo()
        assert not toolkit._guide_ik_resolve_uuid(group_uuid)
        for joint,expected in zip(joints,current_matrices):
            assert near(cmds.xform(joint,query=True,worldSpace=True,matrix=True),expected), 'Redo Remove changed the posed joints.'
        assert toolkit.remove_guide_ik(joints[0]) == []
        print('PASS: Three-Joint IK build, initial pose, end/pole motion, current world pose preservation on Remove, jointOrient and locked T/S, ownership, renames, Undo/Redo.')
    finally:
        # Remove only our temporary foreign object before ownership validation.
        temporary_foreign = cmds.ls(prefix+':userObject', long=True) or []
        if temporary_foreign:
            cmds.delete(temporary_foreign)
        # Delete owned systems first; generated groups use the root namespace.
        for joint in joints[:1]:
            if joint and cmds.objExists(joint):
                for group in toolkit.find_guide_ik_systems(joint):
                    state, _nodes = toolkit._check_guide_ik_removal(group)
                    toolkit._guide_ik_delete_owned(state['members'])
        if cmds.namespace(exists=prefix):
            cmds.namespace(removeNamespace=prefix, deleteNamespaceContent=True)
        cmds.namespace(setNamespace=current_namespace)
        existing = [item for item in selection if cmds.objExists(item)]
        cmds.select(existing, replace=True) if existing else cmds.select(clear=True)


def run_pose_driver():
    """Run inside Maya: live weights, parent motion, update, ownership and undo."""
    import math
    prefix = 'rtkPoseSmoke_' + uuid.uuid4().hex[:8]
    selection = cmds.ls(selection=True, long=True) or []
    namespace = cmds.namespaceInfo(currentNamespace=True)
    group_id = None
    consumer = None

    def angle_value(degrees):
        return toolkit.om.MAngle(degrees, toolkit.om.MAngle.kDegrees).asUnits(toolkit.om.MAngle.uiUnit())

    def direction(node, frame):
        p = toolkit.om.MPoint(*cmds.xform(node, query=True, worldSpace=True, translation=True))
        m = toolkit.om.MMatrix(cmds.xform(frame, query=True, worldSpace=True, matrix=True))
        local = p * m.inverse()
        return (local.x, local.y, local.z)

    def assert_weights(group):
        _group, state = toolkit._pd_read(group)
        cone, frame = toolkit._pd_node(state['cone']), toolkit._pd_node(state['frame'])
        targets = [{'direction':direction(toolkit._pd_node(p['center']),frame), 'radius':p['radius']} for p in state['poses']]
        expected = toolkit.pose_driver_weights(direction(cone,frame),targets,cmds.getAttr(cone+'.normalize'),falloff=state.get('falloff_mode','smooth'))
        for index, pose in enumerate(state['poses']):
            raw = cmds.getAttr(cone+'.'+pose['attribute']+'Raw')
            weight = cmds.getAttr(cone+'.'+pose['attribute'])
            assert math.isfinite(weight) and abs(weight-expected['weights'][index]) < 2e-5, (pose['name'],weight,expected)
            assert abs(raw-expected['raw'][index]) < 2e-5, (pose['name'],raw,expected)
            joint = toolkit._pd_node(state['joint'])
            for output, attribute in pose.get('joint_attributes', {}).items():
                assert abs(cmds.getAttr(joint+'.'+attribute)-cmds.getAttr(cone+'.'+output)) < 2e-5
        assert abs(cmds.getAttr(cone+'.rawWeightSum')-expected['sum']) < 2e-5
        return expected

    try:
        cmds.namespace(setNamespace=':')
        cmds.namespace(add=prefix)
        parent = cmds.createNode('transform', name=prefix+':parent', skipSelect=True)
        joint = cmds.createNode('joint', name=prefix+':driver', parent=parent, skipSelect=True)
        joint = cmds.ls(joint,long=True)[0]
        cmds.setAttr(joint+'.translate',5,2,1,type='double3')
        cmds.setAttr(joint+'.jointOrientY',angle_value(15))
        cmds.setAttr(joint+'.jointOrientZ',angle_value(10))
        source_matrix = cmds.xform(joint,query=True,worldSpace=True,matrix=True)
        cmds.select(joint,replace=True)
        result = toolkit.build_pose_driver(joint,axis=1)
        group_id = toolkit._pd_uuid(result['group'])
        cone, frame = result['cone'], result['frame']
        assert cmds.xform(joint,query=True,worldSpace=True,matrix=True) == source_matrix
        assert cmds.ls(selection=True,long=True) == [joint]
        rest = toolkit.add_pose_driver_pose(result['group'],'rest',radius=60)
        assert abs(cmds.getAttr(cone+'.restWeight')-1) < 1e-6
        cmds.setAttr(joint+'.rotateZ',angle_value(45))
        up = toolkit.add_pose_driver_pose(result['group'],'up',radius=60)
        assert abs(cmds.getAttr(cone+'.upWeightRaw')-1) < 1e-6
        cmds.undo()  # One capture includes target locator, nodes and attributes.
        assert not cmds.attributeQuery('upWeight',node=cone,exists=True)
        cmds.redo()
        assert cmds.attributeQuery('upWeight',node=cone,exists=True)
        # An external object defines a ray; its actual distance is not copied.
        pose_object = cmds.createNode('transform',name=prefix+':poseObject',skipSelect=True)
        joint_origin = cmds.xform(joint,query=True,worldSpace=True,translation=True)
        # The green target points at REST while the current red cone is at 45°.
        # This makes an accidental current-joint capture observable.
        green_point = cmds.xform(toolkit._pd_node(rest['center']),query=True,worldSpace=True,translation=True)
        endpoint = tuple(a+25*(b-a) for a,b in zip(joint_origin,green_point))
        cmds.xform(pose_object,worldSpace=True,translation=endpoint)
        toolkit.update_pose_driver_pose(result['group'],up['id'],center=pose_object,radius=60,recapture=True)
        for pose in toolkit._pd_read(result['group'])[1]['poses']:
            point = cmds.xform(toolkit._pd_node(pose['center']),query=True,worldSpace=True,translation=True)
            assert abs(math.sqrt(sum((a-b)**2 for a,b in zip(point,joint_origin)))-1)<1e-6, 'Center must be one world-space scene unit from the joint.'
        assert cmds.getAttr(cone+'.upWeightRaw') < .999, 'A supplied green target was replaced by the current red cone direction.'
        assert_weights(result['group'])
        assert cmds.objExists(pose_object)
        for amount in (0,.5,1):
            toolkit.set_pose_driver_normalize(result['group'],amount)
            for degrees in (-150,-60,-30,0,15,30,45,75,120,150):
                cmds.setAttr(joint+'.rotateZ',angle_value(degrees))
                expected = assert_weights(result['group'])
                if amount == 1 and expected['sum'] > 0:
                    assert abs(sum(expected['weights'])-1) < 1e-6
        cmds.setAttr(joint+'.rotateZ',0)
        before_parent = assert_weights(result['group'])['weights']
        with toolkit._tool_action('PoseSmokeParentMotion'):
            cmds.setAttr(parent+'.translateX',4)
            cmds.setAttr(parent+'.rotateZ',angle_value(25))
        after_parent = assert_weights(result['group'])['weights']
        assert all(abs(a-b)<2e-5 for a,b in zip(before_parent,after_parent)), 'Parent motion changed relative pose weights.'
        cmds.undo()
        # Twist about the aim X-axis is intentionally excluded.
        cmds.setAttr(joint+'.rotateX',angle_value(30))
        after_twist = assert_weights(result['group'])['weights']
        assert all(abs(a-b)<2e-5 for a,b in zip(before_parent,after_twist))
        cmds.setAttr(joint+'.rotateX',0)
        target = toolkit._pd_node(up['center'])
        cmds.xform(target,worldSpace=True,translation=cmds.xform(frame,query=True,worldSpace=True,translation=True))
        assert cmds.getAttr(cone+'.upWeightRaw') == 0, 'A zero-length target direction must return zero.'
        assert_weights(result['group'])
        cmds.undo()
        consumer = cmds.createNode('transform',name=prefix+':consumer',skipSelect=True)
        cmds.addAttr(consumer,longName='amount',attributeType='double')
        cmds.connectAttr(cone+'.upWeight',consumer+'.amount')
        original_plug = cmds.connectionInfo(consumer+'.amount',sourceFromDestination=True)
        state = toolkit._pd_read(result['group'])[1]
        original_ids = set(state['members'])
        cmds.setAttr(joint+'.rotateZ',angle_value(20))
        toolkit.update_pose_driver_pose(result['group'],up['id'],radius=50,recapture=True)
        assert set(toolkit._pd_read(result['group'])[1]['members']) == original_ids
        assert cmds.connectionInfo(consumer+'.amount',sourceFromDestination=True) == original_plug
        assert_weights(result['group'])
        try:
            toolkit.remove_pose_driver_pose(result['group'],up['id'])
            raise AssertionError('Removing a used output should be blocked.')
        except ValueError:
            pass
        cmds.disconnectAttr(cone+'.upWeight',consumer+'.amount')
        toolkit.remove_pose_driver_pose(result['group'],rest['id'])
        assert not cmds.attributeQuery('restWeight',node=cone,exists=True)
        assert_weights(result['group'])
        cmds.undo()
        assert cmds.attributeQuery('restWeight',node=cone,exists=True)
        assert_weights(result['group'])
        # Renaming source/group does not invalidate UUID-backed centers or records.
        joint_id = toolkit._pd_uuid(joint)
        cmds.rename(result['group'],prefix+':renamedSetup')
        cmds.rename(joint,prefix+':renamedJoint')
        group = toolkit._pd_node(group_id)
        joint = toolkit._pd_node(joint_id)
        assert toolkit.find_pose_drivers(joint) == [group]
        assert_weights(group)
        state = toolkit._pd_read(group)[1]
        toolkit.remove_pose_driver(group)
        assert all(not cmds.ls(identity,long=True) for identity in state['members'])
        assert cmds.objExists(joint) and cmds.objExists(parent) and cmds.objExists(consumer)
        cmds.undo()
        assert_weights(toolkit._pd_node(group_id))
        cmds.redo()
        print('PASS: PoseDriver native weights/falloff/Normalize, jointOrient, parent motion, twist exclusion, zero centers, stable recapture, downstream guards, renames, removal and Undo/Redo.')
    finally:
        if group_id:
            remaining = toolkit._guide_ik_resolve_uuid(group_id)
            if remaining:
                state = toolkit._pd_read(remaining)[1]
                # Remove our temporary consumer before deleting exported outputs.
                if consumer and cmds.objExists(consumer):
                    cmds.delete(consumer)
                toolkit._guide_ik_delete_owned(state['members'])
        if cmds.namespace(exists=prefix):
            cmds.namespace(removeNamespace=prefix,deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace)
        existing = [n for n in selection if cmds.objExists(n)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)


def run_pose_driver_divide_protection():
    """Native zero/active weight evaluation, existing-graph repair and Undo."""
    import math
    prefix='rtkPoseDivideSmoke_'+uuid.uuid4().hex[:8]
    namespace=cmds.namespaceInfo(currentNamespace=True);selection=cmds.ls(selection=True,long=True) or [];group=None
    def angle(degrees):return math.radians(degrees) if cmds.currentUnit(query=True,angle=True) in ('rad','radian') else degrees
    try:
        cmds.namespace(setNamespace=':');cmds.namespace(addNamespace=prefix)
        joint=cmds.createNode('joint',name=prefix+':joint');target=cmds.spaceLocator(name=prefix+':target')[0]
        cmds.setAttr(target+'.translate',1,1,0,type='double3')
        result=toolkit.build_pose_driver(joint);group=result['group'];cone=result['cone']
        pose=toolkit.add_pose_driver_pose(group,'up',radius=30,center=target)
        toolkit.set_pose_driver_normalize(group,1)
        state=toolkit._pd_read(group)[1];den=toolkit._pd_node(state['denominator'])
        blend=cmds.listConnections(cone+'.'+pose['attribute'],source=True,destination=False)[0]
        node=cmds.listConnections(blend+'.color1R',source=True,destination=False)[0]
        for degrees,expected in ((45,1),(-90,0),(45,1)):
            cmds.setAttr(joint+'.rotateZ',angle(degrees));value=cmds.getAttr(cone+'.'+pose['attribute'])
            assert math.isfinite(value) and abs(value-expected)<1e-4,(degrees,value)
            assert cmds.getAttr(node+'.input2X')>0
            assert cmds.getAttr(node+'.input2Y')==1 and cmds.getAttr(node+'.input2Z')==1
        cmds.setAttr(den+'.secondTerm',0);cmds.setAttr(den+'.colorIfFalseR',1)
        before=cmds.listConnections(joint+'.'+pose['joint_attributes'][pose['attribute']],source=True,destination=False,plugs=True)
        repair=toolkit.repair_pose_driver_division(group);assert repair['changed']
        assert 0<cmds.getAttr(den+'.secondTerm')<1e-7
        assert before==cmds.listConnections(joint+'.'+pose['joint_attributes'][pose['attribute']],source=True,destination=False,plugs=True)
        cmds.undo();assert cmds.getAttr(den+'.secondTerm')==0,'One Undo restores the guard settings'
        cmds.redo();assert not toolkit.repair_pose_driver_division(group)['changed'],'Repair should be idempotent with native float attributes'
        print('PoseDriver divide protection native smoke: PASS (zero/active weights, positive inputs, repair, output links and Undo).')
    finally:
        if group and cmds.objExists(group):toolkit.remove_pose_driver(group,preserve_consumers=True)
        cmds.namespace(setNamespace=':')
        if cmds.namespace(exists=prefix):cmds.namespace(removeNamespace=prefix,deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace)
        existing=[n for n in selection if cmds.objExists(n)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)


def run_pose_driver_normalization_warnings():
    """Native warning capture across zero/tiny sums in DG, Serial and Parallel."""
    import math
    import maya.api.OpenMaya as om
    prefix='rtkPoseWarningSmoke_'+uuid.uuid4().hex[:8]
    namespace=cmds.namespaceInfo(currentNamespace=True);selection=cmds.ls(selection=True,long=True) or []
    modes=cmds.evaluationManager(query=True,mode=True);suppressed=cmds.scriptEditorInfo(query=True,suppressWarnings=True)
    callback=None;group=None;warnings=[]
    def collect(message,kind,data):
        if kind==om.MCommandMessage.kWarning and prefix in message and 'divide by zero' in message.lower():warnings.append(message)
    def angle(degrees):return math.radians(degrees) if cmds.currentUnit(query=True,angle=True) in ('rad','radian') else degrees
    try:
        cmds.scriptEditorInfo(suppressWarnings=False)
        callback=om.MCommandMessage.addCommandOutputCallback(collect)
        cmds.namespace(setNamespace=':');cmds.namespace(addNamespace=prefix)
        joint=cmds.createNode('joint',name=prefix+':Shoulder_L')
        result=toolkit.build_pose_driver(joint);group=result['group'];cone=result['cone']
        cmds.setAttr(joint+'.rotateY',angle(-70));pose=toolkit.add_pose_driver_pose(group,'nY70',radius=70)
        state=toolkit._pd_read(group)[1];normalizer=toolkit._pd_node(pose['normalizer'])
        for mode in ('off','serial','parallel'):
            cmds.evaluationManager(mode=mode)
            for falloff in ('smooth','linear'):
                toolkit.set_pose_driver_falloff(group,falloff)
                for normalize in (0.,1.):
                    toolkit.set_pose_driver_normalize(group,normalize)
                    for rotation in (-180,-140,-139.9999,-100,-70,-69.99,-35,-10,-.01,-1e-4,-1e-6,0,90):
                        cmds.setAttr(joint+'.rotateY',angle(rotation))
                        value=cmds.getAttr(cone+'.'+pose['attribute']);divisor=cmds.getAttr(normalizer+'.input2X')
                        assert math.isfinite(value) and 0<=value<=1.00001,(mode,rotation,value)
                        assert divisor>=1.,(mode,rotation,divisor)
        assert not warnings,'Captured PoseDriver divide warnings: '+repr(warnings)
        print('PoseDriver native warning sweep: PASS (negative-Y70 capture, smooth/linear, Normalize 0/1, zero/tiny sums and DG/Serial/Parallel).')
    finally:
        if callback is not None:om.MMessage.removeCallback(callback)
        if modes:cmds.evaluationManager(mode=modes[0])
        cmds.scriptEditorInfo(suppressWarnings=suppressed)
        if group and cmds.objExists(group):toolkit.remove_pose_driver(group,preserve_consumers=True)
        cmds.namespace(setNamespace=':')
        if cmds.namespace(exists=prefix):cmds.namespace(removeNamespace=prefix,deleteNamespaceContent=True)
        cmds.namespace(setNamespace=namespace)
        existing=[n for n in selection if cmds.objExists(n)]
        cmds.select(existing,replace=True) if existing else cmds.select(clear=True)
