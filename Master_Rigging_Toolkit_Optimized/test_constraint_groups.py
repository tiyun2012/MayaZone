"""Constraint DAG ownership and row actions; recorded commands, not Maya solve."""
import ast
import copy
import json
from pathlib import Path
import unittest
from unittest import mock
import test_regressions as legacy
import test_root_foot_modules as fixtures

class GroupTests(unittest.TestCase):
    def setUp(self):
        self.fixture=legacy.ModularRigTests();self.fixture.tree=ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text());self.fixture.setUp()
        self.cmds=self.fixture.cmds;self.ns=self.fixture.ns
        self.fixture.ankle,self.fixture.ball=self.cmds.joints[:2]
        self.fixture.guides={'toe_tip':self.cmds.add_node('|Driver','transform')}
    def matrix(self,node):return self.cmds.xform(node,query=True,worldSpace=True,matrix=True)
    def fk(self,joint=None):return self.ns['build_fk_module']([joint or self.fixture.ankle])
    def state(self,rig):return self.ns['_rig_module_read'](rig['module'])[1]
    def node(self,identity):return self.ns['_rig_module_node'](identity)
    def parent(self,node):return (self.cmds.listRelatives(node,parent=True,fullPath=True) or [None])[0]
    def test_native_module_constraints_share_root_and_own_only_their_subgroup(self):
        a=self.fk();b=self.fk(self.fixture.ball);sa,sb=self.state(a),self.state(b)
        root=self.ns['_constraint_root']();self.assertEqual(root,'|constraintNode')
        self.assertNotEqual(sa['constraint_group'],sb['constraint_group'])
        for state in (sa,sb):
            group=self.node(state['constraint_group'])
            self.assertEqual(self.parent(group),root)
            self.assertNotIn(self.ns['_guide_ik_uuid'](root),{r['uuid'] for r in state['members']})
            for row in state['controls']:
                for identity in row['constraints']:self.assertEqual(self.parent(self.node(identity)),group)
    def test_delete_one_module_keeps_another_module_and_source_joints(self):
        a=self.fk();b=self.fk(self.fixture.ball);sb=self.state(b)
        group=self.node(sb['constraint_group']);sources={j:self.matrix(j) for j in self.cmds.joints}
        self.ns['remove_rig_module'](a['module'])
        self.assertIn(group,self.cmds.nodes);self.assertIn('|constraintNode',self.cmds.nodes)
        self.assertEqual(self.state(b)['constraint_group'],sb['constraint_group'])
        for joint,matrix in sources.items():self.assertEqual(self.matrix(joint),matrix)
        self.ns['remove_rig_module'](b['module']);self.assertNotIn('|constraintNode',self.cmds.nodes)
    def test_existing_user_container_and_its_user_child_are_never_owned_or_removed(self):
        group=self.cmds.createNode('transform',name='constraintNode')
        child=self.cmds.createNode('transform',name='UserData');child=self.cmds.parent(child,group,relative=True)[0]
        before=copy.deepcopy(self.cmds.nodes[group]);rig=self.fk();self.ns['remove_rig_module'](rig['module'])
        self.assertEqual(self.cmds.nodes[group],before);self.assertIn(child,self.cmds.nodes)
    def test_foreign_child_in_owned_constraint_subgroup_blocks_delete_readonly(self):
        rig=self.fk();group=self.node(self.state(rig)['constraint_group'])
        child=self.cmds.createNode('transform',name='UserData');child=self.cmds.parent(child,group,relative=True)[0];before=copy.deepcopy(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'Move'):self.ns['remove_rig_module'](rig['module'])
        self.assertEqual(self.cmds.nodes,before);self.assertIn(child,self.cmds.nodes)
    def test_renamed_solver_and_subgroup_are_removed_by_uuid(self):
        rig=self.fk();state=self.state(rig)
        self.cmds.rename(self.node(state['constraint_group']),'RenamedConstraints')
        self.cmds.rename(self.node(state['controls'][0]['constraints'][0]),'RenamedSolver')
        self.ns['remove_rig_module'](rig['module'])
        self.assertFalse(any('Renamed' in node for node in self.cmds.nodes));self.assertNotIn('|constraintNode',self.cmds.nodes)
    def test_reparenting_uses_relative_and_preserves_solver_inputs(self):
        calls=[];original=self.cmds.parent
        def parent(node,group,**kw):
            if self.cmds.nodeType(node).endswith('Constraint'):calls.append(kw)
            return original(node,group,**kw)
        self.cmds.parent=parent;rig=self.fk()
        self.assertTrue(calls);self.assertTrue(all(c.get('relative') and not c.get('absolute') for c in calls))
        state=self.state(rig)
        for channel,expected in state['controls'][0]['inputs'].items():
            source=self.cmds.inputs[self.fixture.ankle+'.'+channel]
            self.assertEqual(self.ns['_guide_ik_uuid'](source.split('.')[0]),expected['node'])
    def test_constraint_name_collision_is_handled_by_uuid_after_parent(self):
        rig=self.ns['build_fk_module']([self.fixture.ankle],include_children=True)
        state=self.state(rig);identities=[i for r in state['controls'] for i in r['constraints']]
        paths=[self.node(i) for i in identities]
        self.assertEqual(len(paths),6);self.assertEqual(len(set(paths)),6)
    def test_invalid_container_fails_before_a_native_constraint_is_created(self):
        self.cmds.createNode('joint',name='constraintNode');before=copy.deepcopy(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'transform group'):
            self.ns['_constraint_command']('parentConstraint',self.fixture.guides['toe_tip'],self.fixture.ankle,maintainOffset=True)
        self.assertEqual(self.cmds.nodes,before);self.assertFalse(self.cmds.inputs)
    def test_query_and_edit_are_passed_through_without_creating_container(self):
        native=mock.Mock(return_value=['targetW0'])
        with mock.patch.object(self.cmds,'parentConstraint',native):
            self.assertEqual(self.ns['_constraint_command']('parentConstraint','solver',query=True,weightAliasList=True),['targetW0'])
        native.assert_called_once_with('solver',query=True,weightAliasList=True)
        self.assertNotIn('|constraintNode',self.cmds.nodes)
    def test_matrix_only_root_and_foot_create_no_empty_constraint_containers(self):
        f=fixtures.RootFootTests();f.tree=self.fixture.tree;f.setUp()
        root=f.root();foot=f.foot(parent_control=root['attachment'])
        for rig in (root,foot):self.assertEqual(f.ns['organize_rig_constraints'](rig['module'])['count'],0)
        self.assertNotIn('|constraintNode',f.cmds.nodes)
    def test_legacy_module_can_be_organized_and_reorganized_without_duplicate_groups(self):
        rig=self.fk();state=self.state(rig);old=state.pop('constraint_group')
        for row in state['controls']:
            for identity in row['constraints']:self.cmds.parent(self.node(identity),self.node(row['joint']),relative=True)
        self.cmds.delete(self.node(old));state['members']=[r for r in state['members'] if r['uuid']!=old]
        meta=rig['module']
        self.cmds.inputs={k:v for k,v in self.cmds.inputs.items() if not k.startswith(meta+'.members[')}
        for index,row in enumerate(state['members']):
            if row['uuid']!=state['meta']:self.cmds.connectAttr(self.node(row['uuid'])+'.message',meta+'.members[{}]'.format(index))
        self.cmds.setAttr(meta+'.rtkRigModuleState',json.dumps(state),type='string');self.ns['_constraint_prune']()
        before={j:self.matrix(j) for j in self.cmds.joints}
        a=self.ns['organize_rig_constraints'](meta);b=self.ns['organize_rig_constraints'](meta)
        self.assertEqual(a['group'],b['group']);self.assertEqual(a['count'],2)
        for j,m in before.items():self.assertEqual(self.matrix(j),m)
        self.ns['remove_rig_module'](meta);self.assertNotIn('|constraintNode',self.cmds.nodes)
    def test_organize_failure_rolls_back_scene_and_connections(self):
        rig=self.fk();before=copy.deepcopy(self.cmds.nodes);inputs=dict(self.cmds.inputs)
        original=self.cmds.parent
        def parent(node,*args,**kw):
            if self.cmds.nodeType(node).endswith('Constraint'):raise RuntimeError('Injected parent failure')
            return original(node,*args,**kw)
        # Move one solver back under its driven joint so organize has work to do.
        state=self.state(rig);identity=state['controls'][0]['constraints'][0]
        self.cmds.parent(self.node(identity),self.fixture.ankle,relative=True)
        before=copy.deepcopy(self.cmds.nodes);inputs=dict(self.cmds.inputs);self.cmds.parent=parent
        with self.assertRaisesRegex(RuntimeError,'rolled back'):self.ns['organize_rig_constraints'](rig['module'])
        self.assertEqual(self.cmds.nodes,before);self.assertEqual(self.cmds.inputs,inputs)
    def test_all_toolkit_constraint_calls_go_through_shared_grouping(self):
        tree=ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())
        direct=[n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
                and isinstance(n.func.value,ast.Name) and n.func.value.id=='cmds' and n.func.attr.endswith('Constraint')]
        self.assertEqual(direct,[])

class RootMirrorTests(GroupTests):
    def setUp(self):
        self.fixture=fixtures.RootFootTests();self.fixture.tree=ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text());self.fixture.setUp()
        self.cmds=self.fixture.cmds;self.ns=self.fixture.ns
    def test_source_bound_side_root_mirrors_to_existing_joint_and_names(self):
        source=self.cmds.add_node('|root_L','joint');target=self.cmds.add_node('|root_R','joint')
        for node,x in ((source,12),(target,-12)):
            data=copy.deepcopy(self.cmds.nodes[self.fixture.ankle]);data['uuid']=self.cmds.nodes[node]['uuid'];self.cmds.nodes[node]=data
            self.cmds.xform(node,worldSpace=True,translation=(x,5,0))
        root=self.fixture.root(root_joint=source,name='Character_L',controller_names={'root':'Main_L_ctrl','placement':'Root_L_ctrl'})
        result=self.ns['mirror_rig_module'](root['module']);state=self.state(result)
        self.assertEqual(result['root_joint'],target);self.assertEqual(state['root_joint'],self.ns['_guide_ik_uuid'](target))
        self.assertTrue(result['main_controller'].endswith('Main_R_ctrl'));self.assertTrue(result['root_controller'].endswith('Root_R_ctrl'))
        self.assertIn(root['module'],self.cmds.nodes)

# Reuse the fixture only; do not run all GroupTests twice.
for name in list(GroupTests.__dict__):
    if name.startswith('test_'):setattr(RootMirrorTests,name,None)

if __name__=='__main__':unittest.main()
