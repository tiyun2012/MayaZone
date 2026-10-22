"""Published module frames, acyclic attachment, pose retention and legacy data.

Uses recorded Maya commands plus independent matrix arithmetic. The companion
maya_module_outputs_smoke.py covers native constraints, JO, IK and Undo/Redo.
"""
import ast
import copy
import json
import math
from pathlib import Path
import unittest

import test_regressions as legacy
import test_root_foot_modules as fixtures


PUBLIC = {'list_rig_outputs', 'publish_rig_outputs', 'attach_rig_module', 'detach_rig_module'}


def load_api(namespace, tree):
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in PUBLIC]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<Module outputs API>', 'exec'), namespace)


class ModuleOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())

    def setUp(self):
        fixture = fixtures.RootFootTests(); fixture.tree = self.tree; fixture.setUp()
        self.fixture, self.cmds, self.ns = fixture, fixture.cmds, fixture.ns
        load_api(self.ns, self.tree)

    def root(self, suffix='', **kw):
        if suffix:
            kw.update(name='Character' + suffix, controller_names={'root': 'Main' + suffix, 'placement': 'Root' + suffix})
        return self.ns['build_root_module'](**kw)

    def foot(self, **kw):
        return self.fixture.foot(**kw)

    def state(self, rig):
        return self.ns['_rig_module_read'](rig['module'])[1]

    def node(self, identity):
        return self.ns['_rig_module_node'](identity)

    def outputs(self, rig):
        return self.ns['list_rig_outputs'](rig['module'])

    def matrix(self, node):
        return self.cmds.world(node)

    def assertMatrix(self, a, b):
        self.assertEqual(len(a), len(b))
        for x, y in zip(a, b): self.assertAlmostEqual(x, y, places=6)

    def snapshot(self):
        return copy.deepcopy((self.cmds.nodes, self.cmds.inputs, self.cmds.selection))

    def test_root_publishes_placement_and_optional_joint_as_distinct_owned_outputs(self):
        rig = self.root(root_joint=self.fixture.ankle)
        records = self.outputs(rig); state = self.state(rig)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]['role'], 'placement')
        self.assertEqual(records[1]['joint'], self.fixture.ankle)
        self.assertEqual(rig['placement_output'], records[0]['node'])
        self.assertEqual(self.ns['_rig_module_link'](rig['module'] + '.outputs[1]'), [records[1]['uuid']])
        for record in records:
            self.assertIn(record['uuid'], {r['uuid'] for r in state['members']})
            self.assertEqual(self.ns['_rig_module_link'](record['node'] + '.rtkOutputOwner'), [state['meta']])
            self.assertFalse(self.cmds.getAttr(record['node'] + '.translateX', lock=True))
        self.assertNotEqual(records[0]['uuid'], records[1]['uuid'])

    def test_foot_outputs_match_final_joint_frames_through_roll_bank_tap_and_scale(self):
        rig = self.foot()
        for roll, bank, scale in ((0,0,1), (35,-12,1), (75,20,1.8)):
            self.cmds.setAttr(rig['ankle_controller'] + '.footRoll', roll)
            self.cmds.setAttr(rig['ankle_controller'] + '.bank', bank)
            self.cmds.setAttr(rig['ankle_controller'] + '.toeTap', 9)
            self.cmds.setAttr(rig['root'] + '.globalScale', scale)
            for record in self.outputs(rig):
                self.assertMatrix(self.matrix(record['node']), self.matrix(record['joint']))
            for joint in (self.fixture.ankle, self.fixture.ball):
                self.assertEqual([self.cmds.getAttr(joint + '.scale' + a) for a in 'XYZ'], [1,1,1])

    def test_foot_without_ankle_drive_still_offers_ankle_target_output(self):
        rig = self.foot(drive_ankle=False)
        records = self.outputs(rig)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]['role'], 'ankle_target')
        self.assertIsNone(records[0]['joint'])
        self.assertMatrix(self.matrix(records[0]['node']), self.matrix(rig['ankle_target']))
        self.assertNotIn(self.fixture.ankle + '.offsetParentMatrix', self.cmds.inputs)

    def test_root_joint_output_holds_placement_bind_offset(self):
        rig = self.root(root_joint=self.fixture.ankle, placement=self.fixture.guides['toe_tip'])
        record = self.outputs(rig)[1]
        self.cmds.setAttr(rig['root_controller'] + '.rotateY', 40)
        self.cmds.setAttr(rig['root_controller'] + '.translateX', 7)
        self.cmds.setAttr(rig['main_controller'] + '.globalScale', 2)
        self.assertMatrix(self.matrix(record['node']), self.matrix(self.fixture.ankle))
        self.assertNotEqual(self.matrix(record['node'])[12:15], self.matrix(rig['placement_output'])[12:15])

    def test_fk_constraints_use_marked_outputs_before_source_joints(self):
        command_fixture = legacy.ModularRigTests(); command_fixture.tree = self.tree; command_fixture.setUp()
        ns, commands = command_fixture.ns, command_fixture.cmds
        load_api(ns, self.tree)
        rig = ns['build_fk_module'](commands.joints)
        state = ns['_rig_module_read'](rig['module'])[1]
        constraints = [call for call in commands.calls if call[0] in ('parentConstraint', 'scaleConstraint')]
        for index, row in enumerate(state['controls']):
            output = ns['_rig_module_node'](row['output'])
            for call in constraints[index*2:index*2+2]:
                self.assertEqual(call[1].rsplit('|',1)[-1], output.rsplit('|',1)[-1])
            self.assertEqual(commands.getAttr(output + '.rtkRigOutput'), 'joint:' + row['joint'])
        self.assertEqual(len(ns['list_rig_outputs'](rig['module'])), 3)

    def test_publishing_again_is_readonly_and_does_not_accumulate_nodes_or_undo(self):
        rig = self.foot(); before = self.snapshot(); chunks = self.cmds.chunks[:]
        self.assertEqual(self.ns['publish_rig_outputs'](rig['module']), self.outputs(rig))
        self.assertEqual(self.snapshot(), before); self.assertEqual(self.cmds.chunks, chunks)

    def test_output_and_owner_can_be_renamed_without_breaking_registry(self):
        rig = self.foot(); records = self.outputs(rig)
        self.cmds.rename(records[0]['node'], 'customSocket')
        self.cmds.rename(rig['root'], 'customRigRoot')
        updated = self.outputs(rig)
        self.assertEqual(updated[0]['uuid'], records[0]['uuid'])
        self.assertTrue(updated[0]['node'].endswith('|customSocket'))
        for record in updated: self.assertMatrix(self.matrix(record['node']), self.matrix(record['joint']))

    def test_modified_output_role_or_ownership_is_reported_readonly(self):
        rig = self.root(); output = self.outputs(rig)[0]['node']
        self.cmds.setAttr(output + '.rtkRigOutput', 'anotherRole', type='string')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'output link or role'):
            self.outputs(rig)
        self.assertEqual(self.snapshot(), before)

    def test_deleted_output_can_be_seen_as_missing_and_module_still_removes(self):
        rig = self.root(); output = self.outputs(rig)[0]['node']; self.cmds.delete(output)
        self.assertFalse(self.outputs(rig)[0]['available'])
        self.ns['remove_rig_module'](rig['module'])
        self.assertNotIn(rig['module'], self.cmds.nodes)

    def test_attach_keeps_pose_controller_channels_and_default_then_follows(self):
        parent = self.root(); child = self.foot()
        before = {j: self.matrix(j) for j in (self.fixture.ankle, self.fixture.ball)}
        state_before = self.state(child)
        root_channels = {base+a: self.cmds.getAttr(child['root'] + '.' + base+a)
                         for base in ('translate','rotate','scale') for a in 'XYZ'}
        self.ns['attach_rig_module'](child['module'], parent['placement_output'])
        state = self.state(child)
        for j, m in before.items(): self.assertMatrix(self.matrix(j), m)
        self.assertEqual(state['defaults'], state_before['defaults'])
        self.assertEqual(root_channels, {a:self.cmds.getAttr(child['root'] + '.' + a) for a in root_channels})
        self.cmds.setAttr(parent['root_controller'] + '.translateX', 4)
        self.cmds.setAttr(parent['main_controller'] + '.globalScale', 2)
        for j, m in before.items():
            self.assertMatrix(self.matrix(j)[12:15], [m[12]*2+8,m[13]*2,m[14]*2])
        self.assertEqual(state['attachment']['module'], self.state(parent)['meta'])

    def test_direct_build_with_parent_output_is_one_action_and_no_pose_jump(self):
        parent = self.root()
        self.cmds.setAttr(parent['root_controller'] + '.translateX', 8)
        before = {j:self.matrix(j) for j in (self.fixture.ankle, self.fixture.ball)}
        chunks = len(self.cmds.chunks)
        child = self.foot(parent_output=parent['placement_output'])
        self.assertEqual(self.cmds.chunks[chunks:], ['open','close'])
        for j,m in before.items(): self.assertMatrix(self.matrix(j),m)
        self.assertTrue(self.state(child)['attachment'])

    def test_reattach_keeps_current_pose_and_reuses_owned_matrix(self):
        a, b = self.root('A'), self.root('B')
        child = self.foot()
        self.ns['attach_rig_module'](child['module'], a['placement_output'])
        self.cmds.setAttr(a['root_controller'] + '.translateX', 3)
        self.cmds.setAttr(b['root_controller'] + '.translateX', -10)
        before = {j:self.matrix(j) for j in (self.fixture.ankle, self.fixture.ball)}
        matrix_id = self.state(child)['input_matrix']; nodes = len(self.cmds.nodes)
        self.ns['attach_rig_module'](child['module'], b['placement_output'])
        for j,m in before.items(): self.assertMatrix(self.matrix(j),m)
        self.assertEqual(self.state(child)['input_matrix'],matrix_id)
        self.assertEqual(len(self.cmds.nodes),nodes)
        self.cmds.setAttr(b['root_controller'] + '.translateX', -8)
        for j,m in before.items(): self.assertAlmostEqual(self.matrix(j)[12],m[12]+2)

    def test_detach_keeps_pose_frees_parent_and_retains_animation_channels(self):
        parent = self.root(); child = self.foot()
        self.ns['attach_rig_module'](child['module'], parent['placement_output'])
        self.cmds.setAttr(parent['main_controller'] + '.globalScale', 1.7)
        self.cmds.setAttr(parent['root_controller'] + '.rotateY', 25)
        before = {j:self.matrix(j) for j in (self.fixture.ankle, self.fixture.ball)}
        self.assertTrue(self.ns['detach_rig_module'](child['module'])['detached'])
        self.assertNotIn('attachment',self.state(child))
        self.ns['remove_rig_module'](parent['module'])
        for j,m in before.items(): self.assertMatrix(self.matrix(j),m)
        self.assertFalse(self.cmds.getAttr(child['root'] + '.translateX', lock=True))

    def test_input_local_transform_is_not_applied_twice_when_attached(self):
        parent = self.root(); child = self.foot(); input_node = child['input']
        self.cmds.setAttr(input_node + '.translateX', 2)
        self.cmds.setAttr(input_node + '.rotateZ', 15)
        before = {j:self.matrix(j) for j in (self.fixture.ankle, self.fixture.ball)}
        self.ns['attach_rig_module'](child['module'], parent['placement_output'])
        for j,m in before.items(): self.assertMatrix(self.matrix(j),m)

    def test_input_under_scaled_existing_parent_inherits_scale_once(self):
        parent = self.root(); container = self.cmds.createNode('transform',name='OtherContainer')
        self.cmds.setAttr(container + '.scaleX',2);self.cmds.setAttr(container + '.scaleY',2);self.cmds.setAttr(container + '.scaleZ',2)
        child = self.foot(parent_control=container)
        before = {j:self.matrix(j) for j in (self.fixture.ankle,self.fixture.ball)}
        self.ns['attach_rig_module'](child['module'],parent['placement_output'])
        for j,m in before.items():self.assertMatrix(self.matrix(j),m)
        self.cmds.setAttr(parent['main_controller']+'.globalScale',3)
        for j,m in before.items():self.assertMatrix(self.matrix(j)[12:15],[v*3 for v in m[12:15]])
        self.ns['detach_rig_module'](child['module'])
        posed={j:self.matrix(j) for j in before}
        for j,m in posed.items():self.assertMatrix(self.matrix(j),m)

    def test_self_attachment_and_descendant_cycle_are_rejected_without_mutation(self):
        a,b = self.root('A'), self.root('B')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError,'own output'):
            self.ns['attach_rig_module'](a['module'],a['placement_output'])
        self.assertEqual(self.snapshot(),before)
        self.ns['attach_rig_module'](b['module'],a['placement_output']);before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'dependency cycle'):
            self.ns['attach_rig_module'](a['module'],b['placement_output'])
        self.assertEqual(self.snapshot(),before)

    def test_dag_parent_dependency_is_checked_even_without_an_attachment_record(self):
        a,b = self.root('A'),self.root('B')
        bstate=self.state(b)
        self.cmds.parent(self.node(bstate['input']),a['root_controller'],relative=True)
        before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'dependency cycle'):
            self.ns['attach_rig_module'](a['module'],self.node(self.state(b)['outputs'][0]['node']))
        self.assertEqual(self.snapshot(),before)

    def test_parent_delete_lists_dependent_module_then_child_can_delete_independently(self):
        parent = self.root(); child = self.foot(name='LowerLeg')
        self.ns['attach_rig_module'](child['module'],parent['placement_output']);before=self.snapshot()
        with self.assertRaisesRegex(ValueError,"Detach child module 'LowerLeg'"):
            self.ns['remove_rig_module'](parent['module'])
        self.assertEqual(self.snapshot(),before)
        self.ns['remove_rig_module'](child['module'])
        self.assertTrue(self.cmds.objExists(parent['placement_output']))
        self.ns['remove_rig_module'](parent['module'])

    def test_manual_external_output_consumer_is_protected_on_remove(self):
        rig=self.root(); consumer=self.cmds.createNode('multMatrix',name='OtherRig')
        self.cmds.connectAttr(rig['placement_output']+'.worldMatrix[0]',consumer+'.matrixIn[0]');before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'Another system uses'):
            self.ns['remove_rig_module'](rig['module'])
        self.assertEqual(self.snapshot(),before)

    def test_foreign_input_driver_and_locked_input_are_preserved(self):
        parent=self.root();child=self.foot();plug=child['input']+'.offsetParentMatrix'
        foreign=self.cmds.createNode('multMatrix',name='Foreign');self.cmds.inputs[plug]=foreign+'.matrixSum'
        before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'another driver'):
            self.ns['attach_rig_module'](child['module'],parent['placement_output'])
        self.assertEqual(self.snapshot(),before)
        del self.cmds.inputs[plug];self.cmds.setAttr(plug,lock=True);before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'Unlock'):
            self.ns['attach_rig_module'](child['module'],parent['placement_output'])
        self.assertEqual(self.snapshot(),before)

    def test_foreign_private_matrix_input_is_not_silently_disconnected(self):
        parent=self.root();child=self.foot();self.ns['attach_rig_module'](child['module'],parent['placement_output'])
        matrix=self.node(self.state(child)['input_matrix']);foreign=self.cmds.createNode('multMatrix',name='Foreign')
        self.cmds.connectAttr(foreign+'.matrixSum',matrix+'.matrixIn[0]');before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'changed externally'):
            self.ns['detach_rig_module'](child['module'])
        self.assertEqual(self.snapshot(),before)

    def test_attach_failure_rolls_back_all_connections_and_created_nodes(self):
        parent=self.root();child=self.foot();before=self.snapshot();original=self.cmds.connectAttr
        def fail(source,destination):
            if destination.endswith('.parentOutput'):raise RuntimeError('Injected attachment failure')
            return original(source,destination)
        self.cmds.connectAttr=fail
        with self.assertRaisesRegex(RuntimeError,'rolled back'):
            self.ns['attach_rig_module'](child['module'],parent['placement_output'])
        self.assertEqual(self.snapshot(),before)

    def test_detach_failure_rolls_back_parent_link_and_pose(self):
        parent=self.root();child=self.foot();self.ns['attach_rig_module'](child['module'],parent['placement_output'])
        before=self.snapshot();original=self.ns['_rig_module_save']
        def fail(*args):raise RuntimeError('Injected metadata write failure')
        self.ns['_rig_module_save']=fail
        with self.assertRaisesRegex(RuntimeError,'rolled back'):
            self.ns['detach_rig_module'](child['module'])
        self.assertEqual(self.snapshot(),before);self.ns['_rig_module_save']=original

    def test_attach_and_detach_undo_restore_the_exact_prior_graph(self):
        parent=self.root();child=self.foot();before=self.snapshot()
        self.ns['attach_rig_module'](child['module'],parent['placement_output'])
        self.cmds.undo();self.assertEqual(self.snapshot(),before)
        self.ns['attach_rig_module'](child['module'],parent['placement_output']);attached=self.snapshot()
        self.ns['detach_rig_module'](child['module']);self.cmds.undo();self.assertEqual(self.snapshot(),attached)

    def test_short_and_full_dag_plug_spellings_are_equivalent(self):
        rig=self.root();node=rig['placement_output'];leaf=node.rsplit('|',1)[-1]
        self.assertTrue(self.ns['_rig_module_output_plugs_match']([leaf+'.worldMatrix[0]'],[node+'.worldMatrix[0]']))

    def test_non_output_selection_is_rejected_without_editing(self):
        rig=self.foot();before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'marked OUTPUT'):
            self.ns['attach_rig_module'](rig['module'],self.fixture.ankle)
        self.assertEqual(self.snapshot(),before)

    def side_root(self, side, label, x):
        joint=self.cmds.createNode('joint',name=label+side+'_JNT',skipSelect=True)
        self.cmds.xform(joint,worldSpace=True,translation=(x,5,0))
        return self.ns['build_root_module'](root_joint=joint,name=label+side,
            controller_names={'root':label+side+'_Main','placement':label+side+'_Root'})

    def test_mirror_keeps_central_root_output_attachment(self):
        central=self.root();left=self.side_root('_L','Arm',6)
        right_joint=self.cmds.createNode('joint',name='Arm_R_JNT',skipSelect=True)
        self.cmds.xform(right_joint,worldSpace=True,translation=(-6,5,0))
        self.ns['attach_rig_module'](left['module'],central['placement_output'])
        mirrored=self.ns['mirror_rig_module'](left['module'])
        self.assertEqual(self.state(mirrored)['attachment']['output'],self.state(central)['outputs'][0]['node'])
        self.assertEqual(self.state(mirrored)['root_joint'],self.ns['_guide_ik_uuid'](right_joint))
        self.assertTrue(self.outputs(mirrored))

    def test_mirror_finds_side_parent_output_by_joint_uuid(self):
        left_parent=self.side_root('_L','Upper',6);right_parent=self.side_root('_R','Upper',-6)
        left=self.side_root('_L','Lower',8)
        right_joint=self.cmds.createNode('joint',name='Lower_R_JNT',skipSelect=True)
        self.cmds.xform(right_joint,worldSpace=True,translation=(-8,5,0))
        left_output=self.outputs(left_parent)[1]['node'];right_output=self.outputs(right_parent)[1]['uuid']
        self.ns['attach_rig_module'](left['module'],left_output)
        mirrored=self.ns['mirror_rig_module'](left['module'])
        self.assertEqual(self.state(mirrored)['attachment']['output'],right_output)
        self.assertNotEqual(self.state(mirrored)['attachment']['output'],self.state(left)['attachment']['output'])

    def test_missing_mirror_parent_is_reported_before_building_any_nodes(self):
        left_parent=self.side_root('_L','Upper',6)
        self.cmds.createNode('joint',name='Upper_R_JNT',skipSelect=True)
        left=self.side_root('_L','Lower',8)
        self.cmds.createNode('joint',name='Lower_R_JNT',skipSelect=True)
        self.ns['attach_rig_module'](left['module'],self.outputs(left_parent)[1]['node']);before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'Mirror the parent module'):
            self.ns['mirror_rig_module'](left['module'])
        self.assertEqual(self.snapshot(),before)


class MatrixIKOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.tree=ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())
    def setUp(self):
        fixture=legacy.XMatrixIKTests();fixture.tree=self.tree;fixture.setUp()
        self.fixture,self.ns,self.cmds=fixture,fixture.ns,fixture.cmds;load_api(self.ns,self.tree)
    def assertMatrix(self,a,b):
        for x,y in zip(a,b):self.assertAlmostEqual(x,y,places=6)
    def test_ik_final_outputs_match_driven_joints_and_do_not_read_source_matrices(self):
        rig,state=self.fixture.build()
        for scale in (1,1.8):
            self.cmds.setAttr(rig['root']+'.globalScale',scale)
            for record in self.ns['list_rig_outputs'](rig['module']):
                self.assertMatrix(self.cmds.world(record['node']),self.cmds.world(record['joint']))
        owned={r['uuid'] for r in state['members']}
        sources={r['uuid'] for r in state['joints']}
        for receiver,driver in self.cmds.inputs.items():
            if self.ns['_guide_ik_uuid'](receiver.split('.')[0]) in owned and driver.endswith('.worldMatrix[0]'):
                self.assertNotIn(self.ns['_guide_ik_uuid'](driver.split('.')[0]),sources)
    def test_ikfk_outputs_follow_final_blend_including_preserved_lengths(self):
        rig,state=self.fixture.build('IKFK')
        fk=state['ikfk']['fk_controls']
        # Change one branch independently so a raw IK-only socket cannot pass.
        node=self.ns['_rig_module_node'](fk[1]);matrix=self.cmds.world(node);matrix[13]+=3
        self.cmds.xform(node,worldSpace=True,matrix=matrix)
        samples=[]
        for weight in (0,.35,.7,1):
            self.cmds.setAttr(rig['root']+'.ikFkBlend',weight)
            records=self.ns['list_rig_outputs'](rig['module'])
            for row in records:self.assertMatrix(self.cmds.world(row['node']),self.cmds.world(row['joint']))
            samples.append(self.cmds.world(records[1]['node'])[12:15])
        self.assertNotEqual(samples[0],samples[-1])


class LegacyModuleOutputTests(ModuleOutputTests):
    def setUp(self):
        super().setUp()
        self.saved=json.loads(Path(__file__).with_name('test_data').joinpath('rig_modules_v239.json').read_text())

    def restore(self, kind):
        row=copy.deepcopy(next(row for row in self.saved['cases'] if row['kind']==kind))
        commands=legacy.ModularRigCommands() if kind=='FK' else fixtures.FootCommands()
        for key in ('nodes','inputs','selection','joints','serial'):setattr(commands,key,row[key])
        for data in commands.nodes.values():
            for key in ('locked_attrs','keyable_attrs','channel_box_attrs'):
                if key in data:data[key]=set(data[key])
        self.cmds=commands;self.ns['cmds']=commands
        return {'module':row['module']}

    def test_all_five_shipped_239_modules_upgrade_without_resetting_pose_or_defaults(self):
        self.assertEqual(self.saved['source_version'],'2.39')
        for kind in ('ROOT','FOOT','FK','IK3','IKFK'):
            with self.subTest(kind=kind):
                rig=self.restore(kind);old=self.state(rig)
                self.assertNotIn('output_version',old)
                before={r['uuid']:self.cmds.xform(self.node(r['uuid']),query=True,worldSpace=True,matrix=True) for r in old['joints']}
                old_nodes={r['uuid'] for r in old['members']}
                records=self.ns['publish_rig_outputs'](rig['module']);new=self.state(rig)
                self.assertEqual(new['meta'],old['meta'])
                self.assertEqual(new['defaults'],old['defaults'])
                self.assertEqual(new['controller_names'],old['controller_names'])
                self.assertTrue(old_nodes.issubset({r['uuid'] for r in new['members']}))
                self.assertEqual(len(records),len(old['joints'])+(kind=='ROOT'))
                for identity,matrix in before.items():self.assertMatrix(self.cmds.xform(self.node(identity),query=True,worldSpace=True,matrix=True),matrix)
                if kind!='FK':
                    for record in records:
                        if record['joint']:self.assertMatrix(self.matrix(record['node']),self.matrix(record['joint']))
                saved=self.snapshot();self.ns['publish_rig_outputs'](rig['module']);self.assertEqual(self.snapshot(),saved)

    def test_legacy_read_and_output_list_do_not_mutate_saved_data(self):
        rig=self.restore('FOOT');before=self.snapshot();chunks=self.cmds.chunks[:]
        self.assertEqual(self.outputs(rig),[])
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.cmds.chunks,chunks)

    def test_legacy_publish_is_one_undo_action_and_can_be_repeated_after_undo(self):
        rig=self.restore('ROOT');before=self.snapshot();chunks=len(self.cmds.chunks)
        self.ns['publish_rig_outputs'](rig['module'])
        self.assertEqual(self.cmds.chunks[chunks:],['open','close'])
        self.cmds.undo();self.assertEqual(self.snapshot(),before)
        self.ns['publish_rig_outputs'](rig['module']);self.assertTrue(self.outputs(rig))

    def test_legacy_foreign_source_matrix_driver_is_rejected_before_mutation(self):
        rig=self.restore('FOOT');state=self.state(rig);joint=self.node(state['controls'][0]['joint'])
        matrix=self.cmds.createNode('multMatrix',name='Foreign')
        self.cmds.inputs[joint+'.offsetParentMatrix']=matrix+'.matrixSum';before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'another matrix driver'):
            self.ns['publish_rig_outputs'](rig['module'])
        self.assertEqual(self.snapshot(),before)

    def test_legacy_publish_failure_rolls_back_source_matrix_wiring(self):
        rig=self.restore('FOOT');before=self.snapshot();original=self.cmds.connectAttr
        def fail(source,destination):
            if '.outputs[' in destination:raise RuntimeError('Injected output registration failure')
            return original(source,destination)
        self.cmds.connectAttr=fail
        with self.assertRaisesRegex(RuntimeError,'rolled back'):
            self.ns['publish_rig_outputs'](rig['module'])
        self.assertEqual(self.snapshot(),before)


# Reuse fixture helpers, not the parent class's independent test cases.
for _name in list(ModuleOutputTests.__dict__):
    if _name.startswith('test_') and _name not in LegacyModuleOutputTests.__dict__:
        setattr(LegacyModuleOutputTests,_name,None)


if __name__=='__main__':unittest.main()
