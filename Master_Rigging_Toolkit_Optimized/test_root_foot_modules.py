"""Root/Foot transactions and native-node graph math with recorded Maya calls.

These checks do not replace the supplied Maya scene smoke test.
"""
import ast
import copy
import math
from pathlib import Path
import unittest
import test_regressions as legacy


class FootCommands(legacy.XMatrixCommands):
    def createNode(self,kind,name,**kw):
        if kind in ('transform','joint'):name='|'+name.lstrip(':|')
        node=super().createNode(kind,name,**kw)
        parent=kw.get('parent')
        if parent and (self.listRelatives(node,parent=True,fullPath=True) or [None])[0]!=parent:
            node=self.parent(node,parent,relative=True)[0]
        return node
    def local(self,node):
        result=super().local(node)
        if self.nodes[node]['type'] not in ('transform','joint'):return result
        angles=[math.radians(self.evaluate(node+'.rotate'+a)) for a in 'XYZ']
        rotation=self.ident()
        for axis,angle in enumerate(angles):
            m=self.ident();a,b=(axis+1)%3,(axis+2)%3;c,s=math.cos(angle),math.sin(angle)
            m[a*4+a]=m[b*4+b]=c;m[a*4+b]=s;m[b*4+a]=-s
            rotation=self.product(rotation,m)
        t=result[12:15];result=self.product(rotation,result);result[12:15]=t
        return result


class RootFootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.tree=ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())
    def setUp(self):
        legacy.XMatrixIKTests.setUp(self);self.cmds=FootCommands();self.ns['cmds']=self.cmds
        wanted={'plan_root_module','plan_foot_module','build_root_module','build_foot_module','foot_roll_solution'}
        nodes=[n for n in self.tree.body if isinstance(n,ast.FunctionDef) and n.name in wanted]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<Root Foot>','exec'),self.ns)
        self.ankle,self.ball=self.cmds.joints[:2]
        for node,point in ((self.ankle,(0,5,0)),(self.ball,(0,0,3)),(self.cmds.joints[2],(0,0,6))):
            self.cmds.xform(node,worldSpace=True,translation=point)
        self.guides={}
        for key,point in (('toe_tip',(0,0,6)),('left_pivot',(-2,0,2)),('right_pivot',(2,0,2)),('heel_pivot',(0,0,-2))):
            node=self.cmds.add_node('|'+key+'_L','transform');self.cmds.xform(node,worldSpace=True,translation=point);self.guides[key]=node
    def root(self,**kw):return self.ns['build_root_module'](**kw)
    def foot(self,**kw):
        options=dict(self.guides);options.update(kw)
        return self.ns['build_foot_module'](self.ankle,self.ball,**options)
    def state(self,rig):return self.ns['_rig_module_read'](rig['module'])[1]
    def matrix(self,node):return self.cmds.world(node)
    def assertMatrix(self,a,b):
        for x,y in zip(a,b):self.assertAlmostEqual(x,y,places=6)
    def test_root_has_main_parent_root_and_global_scale_without_driving_joints(self):
        before={j:self.matrix(j) for j in self.cmds.joints};rig=self.root();state=self.state(rig)
        self.assertTrue(rig['main_controller'].endswith('Main_ctrl'));self.assertTrue(rig['root_controller'].endswith('Root_ctrl'))
        self.assertEqual(self.cmds.listRelatives(rig['root_controller'],parent=True),[rig['main_controller']])
        self.assertEqual(state['joints'],[]);self.assertEqual(state['type'],'ROOT')
        self.cmds.setAttr(rig['main_controller']+'.globalScale',2.)
        self.assertAlmostEqual(sum(x*x for x in self.matrix(rig['attachment'])[:3]),4.)
        for j,m in before.items():self.assertMatrix(self.matrix(j),m)
    def test_root_placement_frame_custom_names_and_defaults(self):
        rig=self.root(placement=self.ankle,controller_names={'root':'CharacterMain','placement':'CharacterRoot'})
        self.assertEqual(self.matrix(rig['root_controller'])[12:15],[0,5,0])
        self.cmds.setAttr(rig['root_controller']+'.translateX',3.)
        self.cmds.setAttr(rig['main_controller']+'.globalScale',2.)
        self.ns['goto_rig_default'](rig['module'])
        self.assertEqual(self.cmds.getAttr(rig['root_controller']+'.translateX'),0.)
        self.assertEqual(self.cmds.getAttr(rig['main_controller']+'.globalScale'),2.)
        self.ns['goto_rig_default'](rig['module'],include_root=True)
        self.assertEqual(self.cmds.getAttr(rig['main_controller']+'.globalScale'),1.)
    def test_root_removal_retains_inputs_and_is_undoable(self):
        before=copy.deepcopy(self.cmds.nodes);rig=self.root();saved=copy.deepcopy(self.cmds.nodes)
        self.ns['remove_rig_module'](rig['module']);self.assertEqual(self.cmds.nodes,before)
        self.cmds.undo();self.assertEqual(self.cmds.nodes,saved)
    def test_root_removal_protects_attached_foot(self):
        root=self.root();self.foot(parent_control=root['attachment']);before=copy.deepcopy(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'Move'):self.ns['remove_rig_module'](root['module'])
        self.assertEqual(self.cmds.nodes,before)
    def test_optional_root_joint_follows_root_without_reparenting_or_channel_drivers(self):
        joint=self.ankle;before={j:self.matrix(j) for j in self.cmds.joints}
        parent=self.cmds.listRelatives(joint,parent=True)
        values={a:self.cmds.getAttr(joint+'.'+a) for a in ('jointOrient','rotateAxis','segmentScaleCompensate')}
        rig=self.root(root_joint=joint);state=self.state(rig)
        self.assertEqual(rig['root_joint'],joint);self.assertEqual(rig['joint_count'],1)
        self.assertEqual(state['root_joint'],self.ns['_guide_ik_uuid'](joint))
        self.assertEqual(self.matrix(rig['root_controller'])[12:15],before[joint][12:15])
        self.assertEqual(self.cmds.listRelatives(joint,parent=True),parent)
        self.assertFalse(set(row['uuid'] for row in state['members']) & {state['root_joint']})
        self.assertEqual([p.split('.',1)[1] for p in self.cmds.inputs if p.split('.',1)[0]==joint],['offsetParentMatrix'])
        self.cmds.setAttr(rig['root_controller']+'.translateX',3)
        for j in self.cmds.joints:
            self.assertAlmostEqual(self.matrix(j)[12],before[j][12]+3)
        for attr,value in values.items():self.assertEqual(self.cmds.getAttr(joint+'.'+attr),value)
        self.assertFalse(self.cmds.getAttr(rig['root_controller']+'.translateX',lock=True))

    def test_root_joint_uses_placement_override_and_keeps_bind_offset(self):
        placement=self.guides['toe_tip'];before=self.matrix(self.ankle)
        rig=self.root(root_joint=self.ankle,placement=placement)
        self.assertMatrix(self.matrix(self.ankle),before)
        self.assertEqual(self.matrix(rig['root_controller'])[12:15],self.matrix(placement)[12:15])
        self.cmds.setAttr(rig['root_controller']+'.translateX',2)
        self.assertAlmostEqual(self.matrix(self.ankle)[12],before[12]+2)

    def test_root_joint_global_scale_reaches_children_once_without_local_scale_connections(self):
        rig=self.root(root_joint=self.ankle);origin=self.matrix(self.ankle)[12:15]
        before={j:self.matrix(j)[12:15] for j in self.cmds.joints}
        self.cmds.setAttr(rig['main_controller']+'.globalScale',2)
        for joint,point in before.items():
            self.assertMatrix(self.matrix(joint)[12:15],[origin[i]+2*(point[i]-origin[i]) for i in range(3)])
            self.assertEqual([self.cmds.getAttr(joint+'.scale'+a) for a in 'XYZ'],[1,1,1])

    def test_root_joint_removal_retains_current_pose_sources_and_native_undo(self):
        original=set(self.cmds.nodes);rig=self.root(root_joint=self.ankle)
        self.cmds.setAttr(rig['main_controller']+'.globalScale',1.7)
        self.cmds.setAttr(rig['root_controller']+'.translateX',4)
        self.cmds.setAttr(rig['root_controller']+'.rotateY',27)
        before={j:self.matrix(j) for j in self.cmds.joints};saved=copy.deepcopy(self.cmds.nodes)
        self.ns['remove_rig_module'](rig['module'])
        self.assertEqual(set(self.cmds.nodes),original)
        self.assertNotIn(self.ankle+'.offsetParentMatrix',self.cmds.inputs)
        for joint,matrix in before.items():self.assertMatrix(self.matrix(joint),matrix)
        self.cmds.undo();self.assertEqual(self.cmds.nodes,saved)

    def test_root_joint_default_reset_and_child_foot_scale_do_not_double_transform(self):
        root=self.root(root_joint=self.ankle)
        foot=self.foot(parent_control=root['attachment'],drive_ankle=False)
        before={j:self.matrix(j) for j in (self.ankle,self.ball)};origin=before[self.ankle][12:15]
        self.cmds.setAttr(root['main_controller']+'.globalScale',2)
        for joint,matrix in before.items():
            self.assertMatrix(self.matrix(joint)[12:15],[origin[i]+2*(matrix[12+i]-origin[i]) for i in range(3)])
        self.cmds.setAttr(root['root_controller']+'.translateX',4)
        self.ns['goto_rig_default'](root['module'],include_root=True)
        for joint,matrix in before.items():self.assertMatrix(self.matrix(joint),matrix)
        self.ns['remove_rig_module'](foot['module']);self.ns['remove_rig_module'](root['module'])
        self.assertIn(self.ankle,self.cmds.nodes);self.assertIn(self.ball,self.cmds.nodes)

    def test_root_joint_readonly_preflight_rejects_wrong_type_and_locked_opm(self):
        before=copy.deepcopy(self.cmds.nodes)
        with self.assertRaises(ValueError):self.root(root_joint=self.guides['toe_tip'])
        self.assertEqual(self.cmds.nodes,before)
        self.cmds.setAttr(self.ankle+'.offsetParentMatrix',lock=True);before=copy.deepcopy(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'offsetParentMatrix'):self.root(root_joint=self.ankle)
        self.assertEqual(self.cmds.nodes,before)

    def test_root_joint_existing_driver_and_duplicate_module_are_protected(self):
        foreign=self.cmds.add_node('otherOutput','multMatrix');self.cmds.nodes[foreign]['attrs']['matrixIn[0]']=self.cmds.ident()
        self.cmds.inputs[self.ankle+'.offsetParentMatrix']=foreign+'.matrixSum';before=copy.deepcopy(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'offsetParentMatrix'):self.root(root_joint=self.ankle)
        self.assertEqual(self.cmds.nodes,before)
        self.assertEqual(self.cmds.inputs[self.ankle+'.offsetParentMatrix'],foreign+'.matrixSum')
        self.cmds.inputs.pop(self.ankle+'.offsetParentMatrix');self.root(root_joint=self.ankle)
        before=copy.deepcopy(self.cmds.nodes)
        with self.assertRaises(ValueError):self.root(root_joint=self.ankle)
        self.assertEqual(self.cmds.nodes,before)

    def test_root_joint_static_offset_matrix_is_preserved_and_failure_rolls_back(self):
        opm=self.cmds.ident();opm[12:15]=[2,3,4];self.cmds.setAttr(self.ankle+'.offsetParentMatrix',*opm,type='matrix')
        before={j:self.matrix(j) for j in self.cmds.joints};rig=self.root(root_joint=self.ankle)
        for joint,matrix in before.items():self.assertMatrix(self.matrix(joint),matrix)
        self.ns['remove_rig_module'](rig['module'])
        original=self.cmds.createNode;saved=copy.deepcopy(self.cmds.nodes)
        def fail(kind,*args,**kw):
            if kind=='multMatrix':raise RuntimeError('Injected root graph failure')
            return original(kind,*args,**kw)
        self.cmds.createNode=fail
        with self.assertRaisesRegex(RuntimeError,'rolled back'):self.root(root_joint=self.ankle)
        self.assertEqual(self.cmds.nodes,saved)

    def test_ik_bind_pose_and_source_channels_are_preserved(self):
        before={j:self.matrix(j) for j in self.cmds.joints};rig=self.foot();state=self.state(rig)
        self.assertEqual(state['type'],'FOOT');self.assertEqual(state['foot']['mode'],'IK')
        for j,m in before.items():self.assertMatrix(self.matrix(j),m)
        for j in (self.ankle,self.ball):
            channels=[p.split('.',1)[1] for p in self.cmds.inputs if p.split('.',1)[0]==j]
            self.assertEqual(channels,['offsetParentMatrix'])
        for attr in self.ns['_RIG_MODULE_FOOT_ATTRS']:
            self.assertFalse(self.cmds.getAttr(rig['ankle_controller']+'.'+attr,lock=True))
    def test_native_roll_graph_matches_reference_before_and_after_break(self):
        rig=self.foot();state=self.state(rig);ctrl=rig['ankle_controller']
        pivots={role:next(self.ns['_rig_module_node'](r['uuid']) for r in state['members'] if self.ns['_rig_module_node'](r['uuid']).endswith(role.upper()+'_PIVOT')) for role in ('heel','ball','toe')}
        for roll in (-45,-1,0,20,45,50,60,70,100):
            self.cmds.setAttr(ctrl+'.footRoll',roll);expected=self.ns['foot_roll_solution'](roll)
            for role,node in pivots.items():self.assertAlmostEqual(self.cmds.evaluate(node+'.rotateX'),expected[role])
        self.cmds.setAttr(ctrl+'.ballBreak',70);self.cmds.setAttr(ctrl+'.toeStraight',40)
        self.cmds.setAttr(ctrl+'.footRoll',80)
        self.assertTrue(all(math.isfinite(self.cmds.evaluate(n+'.rotateX')) for n in pivots.values()))
    def test_pivot_roll_changes_pose_retains_ankle_ball_distance_and_unit_joint_scales(self):
        rig=self.foot();before=self.matrix(self.ankle);rest=math.dist(before[12:15],self.matrix(self.ball)[12:15])
        for roll in (-20,35,60,80):
            self.cmds.setAttr(rig['ankle_controller']+'.footRoll',roll)
            self.assertNotEqual(self.matrix(self.ankle),before)
            self.assertAlmostEqual(math.dist(self.matrix(self.ankle)[12:15],self.matrix(self.ball)[12:15]),rest)
            for j in (self.ankle,self.ball):self.assertEqual([self.cmds.getAttr(j+'.scale'+a) for a in 'XYZ'],[1,1,1])
    def test_bank_selects_opposite_side_and_mirror_sign_inverts_rotation(self):
        rig=self.foot(bank_sign=-1);state=self.state(rig)
        pivots={role:next(self.ns['_rig_module_node'](r['uuid']) for r in state['members'] if self.ns['_rig_module_node'](r['uuid']).endswith(role.upper()+'_PIVOT')) for role in ('left','right')}
        for bank,expected in ((20,(-20,0)),(-20,(0,20))):
            self.cmds.setAttr(rig['ankle_controller']+'.bank',bank)
            self.assertEqual(tuple(self.cmds.evaluate(pivots[r]+'.rotateZ') for r in ('left','right')),expected)
    def test_fk_needs_no_guides_and_ball_follows_ankle(self):
        rig=self.ns['build_foot_module'](self.ankle,self.ball,mode='FK')
        before=self.matrix(self.ball)[12:15];self.cmds.setAttr(rig['ankle_controller']+'.translateX',2.)
        self.assertAlmostEqual(self.matrix(self.ball)[12],before[0]+2.)
        self.assertEqual(self.state(rig)['foot']['guides'],{})
    def test_root_scale_is_inherited_once_and_source_scale_channels_stay_one(self):
        root=self.root();rig=self.foot(parent_control=root['attachment'])
        self.cmds.setAttr(root['main_controller']+'.globalScale',2)
        self.assertMatrix(self.matrix(self.ankle)[12:15],[0,10,0]);self.assertMatrix(self.matrix(self.ball)[12:15],[0,0,6])
        for j in (self.ankle,self.ball):self.assertEqual([self.cmds.getAttr(j+'.scale'+a) for a in 'XYZ'],[1,1,1])
    def test_remove_rolled_foot_keeps_pose_joint_orient_and_foreign_children(self):
        rig=self.foot();self.cmds.setAttr(rig['ankle_controller']+'.footRoll',35)
        before={j:self.matrix(j) for j in self.cmds.joints};original=set(self.cmds.joints)|set(self.guides.values())
        self.ns['remove_rig_module'](rig['module'])
        self.assertEqual(set(self.cmds.nodes),original)
        for j,m in before.items():self.assertMatrix(self.matrix(j),m)
    def test_foot_reset_restores_all_roll_attributes(self):
        rig=self.foot();ctrl=rig['ankle_controller'];self.cmds.setAttr(ctrl+'.footRoll',50);self.cmds.setAttr(ctrl+'.bank',20)
        self.ns['goto_rig_default'](rig['module'])
        for name,values in self.ns['_RIG_MODULE_FOOT_ATTRS'].items():self.assertEqual(self.cmds.getAttr(ctrl+'.'+name),values[0])
    def test_drive_ankle_off_does_not_touch_foreign_ankle_driver(self):
        foreign=self.cmds.add_node('legOutput','multMatrix');self.cmds.nodes[foreign]['attrs']['matrixIn[0]']=self.cmds.ident()
        self.cmds.inputs[self.ankle+'.offsetParentMatrix']=foreign+'.matrixSum'
        rig=self.foot(drive_ankle=False)
        self.assertEqual(self.cmds.inputs[self.ankle+'.offsetParentMatrix'],foreign+'.matrixSum')
        self.assertEqual(len(self.state(rig)['joints']),1)
        self.ns['remove_rig_module'](rig['module']);self.assertIn(foreign,self.cmds.nodes)
    def test_invalid_guides_chain_and_parent_are_readonly(self):
        before=copy.deepcopy(self.cmds.nodes)
        for options in ({'toe_tip':None},{'heel_pivot':None},{'right_pivot':self.guides['left_pivot']},{'parent_control':self.ball},{'up_axis':'X'}):
            with self.subTest(options=options),self.assertRaises(ValueError):self.foot(**options)
        self.assertEqual(self.cmds.nodes,before)
    def test_locked_opm_stops_before_any_nodes_are_created(self):
        self.cmds.setAttr(self.ball+'.offsetParentMatrix',lock=True);before=copy.deepcopy(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'offsetParentMatrix'):self.foot()
        self.assertEqual(self.cmds.nodes,before)
    def test_graph_failure_rolls_back_all_nodes_connections_and_selection(self):
        before=copy.deepcopy(self.cmds.nodes);original=self.cmds.createNode
        def fail(kind,*args,**kw):
            if kind=='clamp':raise RuntimeError('Injected graph failure')
            return original(kind,*args,**kw)
        self.cmds.createNode=fail
        with self.assertRaisesRegex(RuntimeError,'rolled back'):self.foot()
        self.assertEqual(self.cmds.nodes,before);self.assertFalse(self.cmds.inputs)
    def test_foreign_output_consumer_blocks_removal(self):
        rig=self.foot();other=self.cmds.add_node('|attachment','transform')
        self.cmds.inputs[other+'.offsetParentMatrix']=rig['ankle_target']+'.worldMatrix[0]'
        with self.assertRaisesRegex(ValueError,'Another system'):self.ns['remove_rig_module'](rig['module'])
    def test_malformed_new_metadata_is_not_accepted(self):
        rig=self.foot();state=self.state(rig);state['foot']['ankle_target']='not-owned'
        self.cmds.setAttr(rig['module']+'.rtkRigModuleState',self.ns['json'].dumps(state),type='string')
        with self.assertRaisesRegex(ValueError,'incomplete or changed'):self.state(rig)
    def test_native_angular_conversion_factor_is_not_forced_to_one(self):
        graph=self.ns['_rig_module_extra_graph']('test_',lambda n:self.ns['_guide_ik_uuid'](n))
        conversion=self.cmds.add_node('angularConversion','unitConversion');self.cmds.nodes[conversion]['attrs']['conversionFactor']=math.pi/180
        receiver=self.cmds.add_node('|receiver','transform');original=self.cmds.connectAttr
        def connect(src,dst,**kw):
            self.cmds.inputs[conversion+'.input']=src;self.cmds.inputs[dst]=conversion+'.output'
        self.cmds.connectAttr=connect
        graph.connect(self.ankle+'.rotateX',receiver+'.rotateX')
        self.assertAlmostEqual(self.cmds.getAttr(conversion+'.conversionFactor'),math.pi/180)
        self.assertIn(self.ns['_guide_ik_uuid'](conversion),graph.members)
    def test_reference_roll_is_finite_conservative_and_continuous(self):
        solve=self.ns['foot_roll_solution']
        for r in [i/10 for i in range(-1000,1500)]:
            v=solve(r);self.assertAlmostEqual(v['ball']+v['toe'],max(r,0));self.assertGreaterEqual(v['ball'],0)
        for angle in (45,70):
            a,b=solve(angle-1e-7),solve(angle+1e-7)
            self.assertTrue(all(abs(a[k]-b[k])<1e-5 for k in a))
        with self.assertRaises(ValueError):solve(float('nan'))



class RootFootMirrorTests(RootFootTests):
    """Only mirror-specific methods are discovered (reuse the fixture helpers)."""
    def right(self):
        # Mirror fixture at a second existing ankle/ball branch.
        a=self.cmds.add_node('|ankle_R','joint');b=self.cmds.add_node(a+'|ball_R','joint')
        template=copy.deepcopy(self.cmds.nodes[self.ankle]);template['uuid']=self.cmds.nodes[a]['uuid'];self.cmds.nodes[a]=template
        template=copy.deepcopy(self.cmds.nodes[self.ball]);template['uuid']=self.cmds.nodes[b]['uuid'];self.cmds.nodes[b]=template
        self.cmds.xform(a,worldSpace=True,translation=(10,5,0));self.cmds.xform(b,worldSpace=True,translation=(10,0,3))
        for key,node in self.guides.items():
            p=self.cmds.world(node)[12:15];n=self.cmds.add_node('|'+key+'_R','transform')
            self.cmds.xform(n,worldSpace=True,translation=(10-p[0],p[1],p[2]))
        return a,b
    def test_mirror_uses_existing_counterparts_preserves_parent_and_flips_bank(self):
        targets=self.right();root=self.root();rig=self.foot(name='Foot_L',parent_control=root['attachment'])
        # Fixtures use generic first/second names. The real mapper below uses
        # guide counterparts; supply the ankle/ball counterparts explicitly.
        original=self.ns['_pd_mirror_object']
        def mapped(node,*args,**kw):
            if node==self.ankle:return targets[0]
            if node==self.ball:return targets[1]
            return original(node,*args,**kw)
        self.ns['_pd_mirror_object']=mapped
        mirrored=self.ns['mirror_rig_module'](rig['module']);state=self.state(mirrored)
        self.assertEqual(state['foot']['bank_sign'],-1)
        self.assertEqual(state['foot']['parent_control'],self.ns['_guide_ik_uuid'](root['attachment']))
        self.assertEqual([r['uuid'] for r in state['joints']],[self.ns['_guide_ik_uuid'](n) for n in targets])
    def test_root_mirror_reports_central_module_without_creating_nodes(self):
        rig=self.root();before=copy.deepcopy(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'central placement'):self.ns['mirror_rig_module'](rig['module'])
        self.assertEqual(self.cmds.nodes,before)

# Avoid rerunning the inherited twenty cases in this mirror-only subclass.
for _name in list(RootFootTests.__dict__):
    if _name.startswith('test_'):setattr(RootFootMirrorTests,_name,None)

if __name__=='__main__':unittest.main()
