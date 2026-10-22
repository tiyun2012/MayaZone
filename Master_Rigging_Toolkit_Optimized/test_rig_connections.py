"""Start message registration, hierarchy plans and transactional connections.

Native constraints are represented by ideal target-frame arithmetic here.
The included Maya smoke test remains the native constraint/IK verification.
"""
import ast
import copy
import json
import math
from pathlib import Path
import unittest
import test_root_foot_modules as fixtures
import test_regressions as legacy
from test_rig_module_outputs import load_api


PUBLIC={'register_rig_start','find_rig_starts','rig_connection_methods','scan_rig_connections',
        'prepare_rig_modules','connect_rig_modules','connect_rig_module'}


def load_connections(ns,tree):
    load_api(ns,tree)
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in PUBLIC]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<Connection API>','exec'),ns)


class AssemblyCommands(fixtures.FootCommands):
    """Ideal matched-target PC/SC behavior, independent of toolkit graph code."""
    def _weighted(self,kind,args,kw):
        result=super()._weighted(kind,args,kw)
        if not kw.get('query') and 'CONNECTION_SPACE' in args[-1].rsplit('|',1)[-1]:
            self.nodes[result[0]]['module_target']=self.nodes[args[0]]['uuid']
            self.nodes[result[0]]['module_driven']=self.nodes[args[-1]]['uuid']
        return result

    def getAttr(self,plug,**kw):
        node,attr=plug.split('.',1)
        if not kw and attr in {base+axis for base in ('translate','rotate','scale') for axis in 'XYZ'}:
            return self.evaluate(plug)
        return super().getAttr(plug,**kw)

    def evaluate(self,plug):
        if plug in self.inputs:return self.evaluate(self.inputs[plug])
        node,attr=plug.split('.',1);data=self.nodes[node]
        if data.get('module_target') and attr.startswith('constraint'):
            target=self.ls(data['module_target'])[0];driven=self.ls(data['module_driven'])[0]
            matrix=self.world(target)
            parent=(self.listRelatives(driven,parent=True) or [None])[0]
            if parent:matrix=self.product(matrix,self.inverse(self.world(parent)))
            if attr.startswith('constraintTranslate'):values=matrix[12:15]
            elif attr.startswith('constraintScale'):values=[math.sqrt(sum(v*v for v in matrix[i*4:i*4+3])) for i in range(3)]
            else:
                scales=[math.sqrt(sum(v*v for v in matrix[i*4:i*4+3])) for i in range(3)]
                r=[v/scales[i//4] if i%4<3 and i<12 else v for i,v in enumerate(matrix)]
                y=math.asin(max(-1,min(1,-r[2])))
                if abs(math.cos(y))>1e-8:x,z=math.atan2(r[6],r[10]),math.atan2(r[1],r[0])
                else:x,z=0,math.atan2(-r[4],r[5])
                values=[math.degrees(v) for v in (x,y,z)]
            return values['XYZ'.index(attr[-1])]
        return super().evaluate(plug)


class RigConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.tree=ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())
    def setUp(self):
        f=fixtures.RootFootTests();f.tree=self.tree;f.setUp()
        commands=AssemblyCommands()
        for key in ('nodes','inputs','selection','joints','serial'):setattr(commands,key,copy.deepcopy(getattr(f.cmds,key)))
        f.cmds=commands;f.ns['cmds']=commands
        self.fixture,self.cmds,self.ns=f,commands,f.ns;load_connections(self.ns,self.tree)
    def state(self,rig):return self.ns['_rig_module_read'](rig['module'])[1]
    def node(self,identity):return self.ns['_rig_module_node'](identity)
    def snapshot(self):return copy.deepcopy((self.cmds.nodes,self.cmds.inputs,self.cmds.selection))
    def root(self,**kw):return self.ns['build_root_module'](**kw)
    def foot(self,**kw):return self.fixture.foot(**kw)
    def scene(self):
        root=self.root(root_joint=self.fixture.ankle,name='Character')
        foot=self.foot(mode='FK',drive_ankle=False,name='Foot')
        leaf=self.root(root_joint=self.cmds.joints[2],name='Tip',controller_names={'root':'TipMain','placement':'TipRoot'})
        return root,foot,leaf
    def scan(self,root):return self.ns['scan_rig_connections'](root['module'])
    def plan(self,row,**kw):
        value={'module':self.node(row['module']),'output':self.node(row['output']),
               'method':row.get('method','parent_constraint'),'follow_scale':True};value.update(kw);return value
    def row(self,report,rig):return next(row for row in report['rows'] if row['module']==self.state(rig)['meta'])
    def assertMatrix(self,a,b):
        for x,y in zip(a,b):self.assertAlmostEqual(x,y,places=6)
    def poses(self):return {j:self.cmds.world(j) for j in self.cmds.joints}
    def assertPoses(self,poses):
        for joint,matrix in poses.items():self.assertMatrix(self.cmds.world(joint),matrix)

    def test_every_new_module_registers_start_on_its_root_controller(self):
        root,foot,leaf=self.scene()
        for rig,expected in ((root,self.fixture.ankle),(foot,self.fixture.ankle),(leaf,self.cmds.joints[2])):
            state=self.state(rig);controller=self.node(state['start_controller'])
            self.assertEqual(state['start_joint'],self.ns['_guide_ik_uuid'](expected))
            self.assertEqual(self.ns['_rig_module_link'](controller+'.rtkModuleStartJoint'),[state['start_joint']])
            self.assertEqual(self.ns['_rig_module_link'](controller+'.rtkStartModule'),[state['meta']])
            self.assertEqual(self.ns['_rig_module_link'](rig['module']+'.startController'),[state['start_controller']])
            self.assertFalse(self.cmds.getAttr(controller+'.translateX',lock=True))
        self.assertEqual(self.state(foot)['start_joint'],self.state(root)['start_joint'])
        self.assertNotIn(self.state(foot)['start_joint'],{r['uuid'] for r in self.state(foot)['joints']})

    def test_place_only_root_scan_anchor_does_not_drive_or_add_attributes_to_joint(self):
        root=self.root();before=copy.deepcopy(self.cmds.nodes[self.fixture.ankle]);inputs=dict(self.cmds.inputs)
        self.ns['register_rig_start'](root['module'],self.fixture.ankle)
        self.assertEqual(self.cmds.nodes[self.fixture.ankle],before)
        self.assertFalse(self.state(root)['joints'])
        self.assertEqual({k:v for k,v in self.cmds.inputs.items() if k.startswith(self.fixture.ankle+'.')},
                         {k:v for k,v in inputs.items() if k.startswith(self.fixture.ankle+'.')})
        self.assertEqual(self.scan(root)['root_start'],self.ns['_guide_ik_uuid'](self.fixture.ankle))

    def test_message_discovery_supports_multiple_modules_with_same_logical_start(self):
        root,foot,_leaf=self.scene()
        found=self.ns['find_rig_starts'](self.fixture.ankle)
        self.assertEqual(set(found),{root['module'],foot['module']})

    def test_joint_controller_output_and_meta_renames_do_not_change_scan_parent(self):
        root,foot,leaf=self.scene();first=self.scan(root)
        ids=[self.state(rig)['meta'] for rig in (root,foot,leaf)]
        root_controller=self.node(self.state(root)['start_controller'])
        self.cmds.rename(root_controller,'CompletelyDifferentController')
        self.cmds.rename(self.fixture.ankle,'renamedSkeleton')
        foot_output=self.node(self.state(foot)['outputs'][-1]['node']);self.cmds.rename(foot_output,'NoNamingPatternSocket')
        for identity,label in zip(ids,('SetupABC','SetupDEF','SetupXYZ')):self.cmds.rename(self.node(identity),label)
        second=self.ns['scan_rig_connections'](self.node(ids[0]))
        self.assertEqual({r['module']:r['output'] for r in first['rows']},{r['module']:r['output'] for r in second['rows']})
        self.assertEqual({r['module']:r['parent_module'] for r in first['rows']},{r['module']:r['parent_module'] for r in second['rows']})

    def test_scan_is_readonly_and_suggests_nearest_ancestor_joint_output(self):
        root,foot,leaf=self.scene();before=self.snapshot();chunks=self.cmds.chunks[:];report=self.scan(root)
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.cmds.chunks,chunks)
        self.assertEqual(report['joint_count'],3)
        self.assertEqual(self.row(report,foot)['parent_module'],self.state(root)['meta'])
        row=self.row(report,leaf)
        self.assertEqual(row['parent_module'],self.state(foot)['meta'])
        self.assertEqual(row['output'],self.state(foot)['outputs'][-1]['node'])
        self.assertTrue(all(r['ready'] for r in report['rows']))
        self.assertTrue(all(r['method']=='parent_constraint' for r in report['rows']))

    def test_modules_from_other_joint_hierarchy_are_not_child_rows(self):
        root,foot,_leaf=self.scene()
        other=self.cmds.createNode('joint',name='OtherSkeleton',skipSelect=True)
        unrelated=self.root(root_joint=other,name='Other',controller_names={'root':'OtherMain','placement':'OtherRoot'})
        self.assertNotIn(self.state(unrelated)['meta'],{r['module'] for r in self.scan(root)['rows']})

    def test_unbound_root_requires_explicit_scan_anchor(self):
        root=self.root();before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'Set Root start'):self.scan(root)
        self.assertEqual(self.snapshot(),before)

    def test_non_root_cannot_be_used_as_scan_scope(self):
        foot=self.foot()
        with self.assertRaisesRegex(ValueError,'Root module'):self.scan(foot)

    def test_bound_module_start_cannot_be_changed_to_another_joint(self):
        root,_foot,_leaf=self.scene();before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'original first joint'):
            self.ns['register_rig_start'](root['module'],self.cmds.joints[1])
        self.assertEqual(self.snapshot(),before)

    def test_start_registration_is_idempotent_and_undoable(self):
        root=self.root();before=self.snapshot();self.ns['register_rig_start'](root['module'],self.fixture.ankle)
        marked=self.snapshot();chunks=self.cmds.chunks[:]
        self.ns['register_rig_start'](root['module'],self.fixture.ankle)
        self.assertEqual(self.snapshot(),marked);self.assertEqual(self.cmds.chunks,chunks)
        self.cmds.undo();self.assertEqual(self.snapshot(),before)

    def test_changed_start_message_is_reported_instead_of_repaired_silently(self):
        root=self.root(root_joint=self.fixture.ankle);state=self.state(root)
        plug=self.node(state['start_controller'])+'.rtkModuleStartJoint'
        self.cmds.inputs[plug]=self.cmds.joints[1]+'.message';before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'start controller message'):
            self.ns['register_rig_start'](root['module'])
        self.assertEqual(self.snapshot(),before)

    def test_matrix_240_style_attachments_are_detected_as_connected(self):
        root,foot,leaf=self.scene();self.ns['attach_rig_module'](foot['module'],root['placement_output'])
        report=self.scan(root);row=self.row(report,foot)
        self.assertEqual(row['status'],'connected');self.assertEqual(row['method'],'matrix_parent')
        self.assertFalse(row['ready']);self.assertEqual(row['parent_module'],self.state(root)['meta'])

    def test_manual_module_dag_parent_is_detected_without_adding_another_connection(self):
        root,foot,_leaf=self.scene();self.cmds.parent(foot['input'],root['root_controller'],relative=True)
        report=self.scan(root);row=self.row(report,foot)
        self.assertEqual(row['status'],'parented');self.assertFalse(row['ready'])

    def test_foreign_input_matrix_is_external_and_is_not_overwritten(self):
        root,foot,_leaf=self.scene();other=self.cmds.createNode('multMatrix',name='ExistingRig')
        self.cmds.connectAttr(other+'.matrixSum',foot['input']+'.offsetParentMatrix')
        before=self.snapshot();row=self.row(self.scan(root),foot)
        self.assertEqual(row['status'],'external');self.assertFalse(row['ready']);self.assertEqual(self.snapshot(),before)

    def test_controller_sdk_animation_does_not_count_as_module_attachment(self):
        root,foot,_leaf=self.scene();curve=self.cmds.createNode('animCurveUL',name='SdkDriver')
        self.cmds.connectAttr(curve+'.output',foot['root']+'.translateX')
        row=self.row(self.scan(root),foot);self.assertEqual(row['status'],'missing');self.assertTrue(row['ready'])

    def test_parent_constraint_builds_owned_matched_target_and_shared_constraint_group(self):
        root,foot,_leaf=self.scene();row=self.row(self.scan(root),foot);before=self.poses()
        self.ns['connect_rig_module'](**{'module':foot['module'],'output':self.node(row['output'])})
        state=self.state(foot);attachment=state['attachment'];self.assertPoses(before)
        self.assertEqual(attachment['method'],'parent_constraint')
        self.assertEqual([self.cmds.nodeType(self.node(i)) for i in attachment['constraints']],['parentConstraint','scaleConstraint'])
        self.assertEqual(self.ns['_guide_ik_uuid'](self.cmds.listRelatives(self.node(attachment['target']),parent=True)[0]),row['output'])
        group=self.node(state['constraint_group'])
        for identity in attachment['constraints']:self.assertEqual(self.cmds.listRelatives(self.node(identity),parent=True),[group])
        self.assertEqual(self.cmds.listRelatives(group,parent=True),['|constraintNode'])
        self.assertEqual(self.row(self.scan(root),foot)['status'],'connected')

    def test_native_connection_carries_parent_rotation_translation_and_scale_once(self):
        root,foot,_leaf=self.scene();row=self.row(self.scan(root),foot)
        self.ns['connect_rig_module'](foot['module'],self.node(row['output']))
        out=self.node(row['output']);bind=self.cmds.world(out);ball_before=self.cmds.world(self.fixture.ball)
        self.cmds.setAttr(root['main_controller']+'.globalScale',1.7)
        self.cmds.setAttr(root['root_controller']+'.translateX',4)
        self.cmds.setAttr(root['root_controller']+'.rotateZ',25)
        expected=self.cmds.product(self.cmds.product(ball_before,self.cmds.inverse(bind)),self.cmds.world(out))
        self.assertMatrix(self.cmds.world(self.fixture.ball),expected)
        self.assertEqual([self.cmds.getAttr(self.fixture.ball+'.scale'+a) for a in 'XYZ'],[1,1,1])

    def test_native_detach_keeps_pose_removes_parent_dependencies_and_reuses_space(self):
        root,foot,_leaf=self.scene();row=self.row(self.scan(root),foot)
        self.ns['connect_rig_module'](foot['module'],self.node(row['output']))
        self.cmds.setAttr(root['main_controller']+'.globalScale',2);self.cmds.setAttr(root['root_controller']+'.rotateY',30)
        before=self.poses();state=self.state(foot);target=state['attachment']['target'];space=state['connection_space']
        self.ns['detach_rig_module'](foot['module']);self.assertPoses(before)
        self.assertIsNone(self.ns['_guide_ik_resolve_uuid'](target));self.assertNotIn('attachment',self.state(foot))
        self.ns['connect_rig_module'](foot['module'],self.node(row['output']))
        self.assertEqual(self.state(foot)['connection_space'],space);self.assertPoses(before)

    def test_detached_matrix_offset_can_connect_by_native_method_then_detach(self):
        root,foot,_leaf=self.scene();self.ns['attach_rig_module'](foot['module'],root['placement_output'])
        self.cmds.setAttr(root['root_controller']+'.translateX',3);self.ns['detach_rig_module'](foot['module'])
        before=self.poses();self.ns['connect_rig_module'](foot['module'],root['placement_output']);self.assertPoses(before)
        self.ns['detach_rig_module'](foot['module']);self.assertPoses(before)

    def test_native_connection_can_omit_scale_constraint(self):
        root,foot,_leaf=self.scene();self.ns['connect_rig_module'](foot['module'],root['placement_output'],follow_scale=False)
        attachment=self.state(foot)['attachment'];self.assertEqual(len(attachment['constraints']),1)
        self.assertFalse(attachment['follow_scale'])

    def test_direct_build_native_connection_is_in_same_build_undo_action(self):
        root=self.root(root_joint=self.fixture.ankle);chunks=len(self.cmds.chunks)
        foot=self.foot(mode='FK',drive_ankle=False,parent_output=root['placement_output'],parent_method='parent_constraint')
        self.assertEqual(self.cmds.chunks[chunks:],['open','close'])
        self.assertEqual(self.state(foot)['attachment']['method'],'parent_constraint')

    def test_batch_connects_parent_and_lower_child_in_one_undo_step(self):
        root,foot,leaf=self.scene();report=self.scan(root);before=self.snapshot();poses=self.poses();chunks=len(self.cmds.chunks)
        self.ns['connect_rig_modules']([self.plan(row) for row in report['rows']])
        self.assertEqual(self.cmds.chunks[chunks:],['open','close']);self.assertPoses(poses)
        self.assertTrue(all(row['status']=='connected' for row in self.scan(root)['rows']))
        self.cmds.undo();self.assertEqual(self.snapshot(),before)

    def test_cycle_in_batch_is_rejected_before_any_scene_mutation(self):
        root,foot,leaf=self.scene();before=self.snapshot();chunks=self.cmds.chunks[:]
        plans=[{'module':foot['module'],'output':leaf['placement_output']},
               {'module':leaf['module'],'output':self.node(self.state(foot)['outputs'][-1]['node'])}]
        with self.assertRaisesRegex(ValueError,'cycle'):self.ns['connect_rig_modules'](plans)
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.cmds.chunks,chunks)

    def test_batch_failure_rolls_back_previously_connected_modules(self):
        root,_foot,_leaf=self.scene();plans=[self.plan(row) for row in self.scan(root)['rows']]
        before=self.snapshot();original=self.cmds.connectAttr;counter=[0]
        def fail(source,destination):
            if destination.endswith('.parentOutput'):
                counter[0]+=1
                if counter[0]==2:raise RuntimeError('Injected second module failure')
            return original(source,destination)
        self.cmds.connectAttr=fail
        with self.assertRaisesRegex(RuntimeError,'rolled back'):self.ns['connect_rig_modules'](plans)
        self.assertEqual(self.snapshot(),before)

    def test_existing_connection_is_not_replaced_by_automatic_plan(self):
        root,foot,_leaf=self.scene();self.ns['attach_rig_module'](foot['module'],root['placement_output']);before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'already has a connection'):
            self.ns['connect_rig_module'](foot['module'],root['placement_output'])
        self.assertEqual(self.snapshot(),before)

    def test_unimplemented_space_switch_is_disabled_and_rejected_readonly(self):
        root,foot,_leaf=self.scene();methods=self.ns['rig_connection_methods']()
        self.assertFalse(next(m for m in methods if m['id']=='space_switch')['available']);before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'not implemented'):
            self.ns['connect_rig_module'](foot['module'],root['placement_output'],method='space_switch')
        self.assertEqual(self.snapshot(),before)

    def test_parent_removal_requires_detach_and_child_removal_keeps_parent(self):
        root,foot,leaf=self.scene();self.ns['connect_rig_module'](foot['module'],root['placement_output'])
        before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'Detach child module'):self.ns['remove_rig_module'](root['module'])
        self.assertEqual(self.snapshot(),before)
        self.ns['remove_rig_module'](foot['module']);self.assertTrue(self.cmds.objExists(root['module']))
        self.assertTrue(self.cmds.objExists(leaf['module']))

    def test_renamed_native_connection_members_still_detach_by_uuid(self):
        root,foot,_leaf=self.scene();self.ns['connect_rig_module'](foot['module'],root['placement_output'])
        state=self.state(foot);attachment=state['attachment']
        for i,identity in enumerate(attachment['constraints']+[attachment['target'],attachment['space']]):
            self.cmds.rename(self.node(identity),'ArbitraryNode'+str(i))
        before=self.poses();self.ns['detach_rig_module'](foot['module']);self.assertPoses(before)

    def test_matrix_ik_source_contract_allows_only_recorded_attachment_constraints(self):
        root=self.root();self.ns['register_rig_start'](root['module'],self.fixture.ankle)
        rig=self.ns['build_ik_module'](*self.cmds.joints,name='Arm',parent_output=root['placement_output'],parent_method='parent_constraint')
        state=self.state(rig)
        self.assertEqual(state['ik']['solver'],'x_translate_v1')
        self.assertEqual(state['start_joint'],self.ns['_guide_ik_uuid'](self.cmds.joints[0]))
        for row in state['controls']:self.assertEqual(self.cmds.nodeType(self.node(row['constraints'][0])),'multMatrix')
        self.assertEqual(len(state['connection_nodes']),2)
        self.ns['detach_rig_module'](rig['module']);self.state(rig)

    def test_duplicate_joint_leaf_names_still_suggest_parent_by_identity(self):
        root,foot,leaf=self.scene()
        self.cmds.rename(self.cmds.joints[0],'sameName')
        self.cmds.rename(self.cmds.joints[1],'sameName')
        self.cmds.rename(self.cmds.joints[2],'sameName')
        report=self.scan(root)
        self.assertEqual(self.row(report,leaf)['parent_module'],self.state(foot)['meta'])
        self.assertEqual(self.row(report,foot)['parent_module'],self.state(root)['meta'])

    def test_native_detach_preserves_selection_and_undo_restores_full_graph(self):
        root,foot,_leaf=self.scene();self.ns['connect_rig_module'](foot['module'],root['placement_output'])
        self.cmds.selection=[self.fixture.ball];before=self.snapshot()
        self.ns['detach_rig_module'](foot['module']);self.assertEqual(self.cmds.selection,[self.fixture.ball])
        self.cmds.undo();self.assertEqual(self.snapshot(),before)

    def test_foreign_connection_space_driver_prevents_native_detach(self):
        root,foot,_leaf=self.scene();self.ns['connect_rig_module'](foot['module'],root['placement_output'])
        space=self.node(self.state(foot)['connection_space']);other=self.cmds.createNode('animCurveUL',name='Foreign')
        self.cmds.inputs[space+'.translateX']=other+'.output';before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'another driver'):self.ns['detach_rig_module'](foot['module'])
        self.assertEqual(self.snapshot(),before)


class SavedConnectionTests(RigConnectionTests):
    def setUp(self):
        super().setUp()
        saved=json.loads(Path(__file__).with_name('test_data').joinpath('rig_connections_v240.json').read_text())
        for key in ('nodes','inputs','selection','joints','serial'):setattr(self.cmds,key,saved[key])
        for data in self.cmds.nodes.values():
            for key in ('locked_attrs','keyable_attrs','channel_box_attrs'):
                if key in data:data[key]=set(data[key])
        self.saved=saved;self.rigs=[{'module':name} for name in saved['modules']]

    def test_shipped_240_scan_infers_start_without_writing_scene(self):
        before=self.snapshot();report=self.scan(self.rigs[0])
        self.assertTrue(all(row['needs_prepare'] for row in report['rows']))
        self.assertFalse(any(row['ready'] for row in report['rows']))
        self.assertEqual(self.snapshot(),before)

    def test_prepare_registers_all_saved_starts_without_rebuilding_or_moving(self):
        poses=self.poses();count=len(self.cmds.nodes);old_ids={self.state(r)['meta'] for r in self.rigs}
        report=self.scan(self.rigs[0]);modules=[self.rigs[0]['module']]+[self.node(row['module']) for row in report['rows']]
        result=self.ns['prepare_rig_modules'](modules)
        self.assertEqual(result['count'],3);self.assertEqual(len(self.cmds.nodes),count);self.assertPoses(poses)
        self.assertEqual({self.state(r)['meta'] for r in self.rigs},old_ids)
        self.assertTrue(all(row['ready'] for row in self.scan(self.rigs[0])['rows']))
        before=self.snapshot();chunks=self.cmds.chunks[:]
        self.assertEqual(self.ns['prepare_rig_modules'](modules)['count'],0)
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.cmds.chunks,chunks)

    def test_prepare_is_one_undo_action_and_rolls_back_all_markers(self):
        before=self.snapshot();chunks=len(self.cmds.chunks)
        self.ns['prepare_rig_modules']([r['module'] for r in self.rigs])
        self.assertEqual(self.cmds.chunks[chunks:],['open','close'])
        self.cmds.undo();self.assertEqual(self.snapshot(),before)

    def test_prepare_failure_preserves_all_previously_registered_modules(self):
        before=self.snapshot();original=self.cmds.connectAttr;counter=[0]
        def fail(source,destination):
            if destination.endswith('.startController'):
                counter[0]+=1
                if counter[0]==2:raise RuntimeError('Injected registration failure')
            return original(source,destination)
        self.cmds.connectAttr=fail
        with self.assertRaisesRegex(RuntimeError,'rolled back'):
            self.ns['prepare_rig_modules']([r['module'] for r in self.rigs])
        self.assertEqual(self.snapshot(),before)

    def test_publish_existing_outputs_also_adds_start_message_registration(self):
        rig=self.rigs[1];outputs=self.ns['list_rig_outputs'](rig['module']);poses=self.poses()
        self.ns['publish_rig_outputs'](rig['module'])
        self.assertEqual(self.ns['list_rig_outputs'](rig['module']),outputs)
        self.assertTrue(self.state(rig)['registration_version']);self.assertPoses(poses)


for _name in list(RigConnectionTests.__dict__):
    if _name.startswith('test_') and _name not in SavedConnectionTests.__dict__:setattr(SavedConnectionTests,_name,None)


if __name__=='__main__':unittest.main()
