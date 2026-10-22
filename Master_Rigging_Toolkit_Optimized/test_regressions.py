"""Dependency-free orchestration tests; these do not emulate Maya's solver or Qt."""
import ast
import contextlib
import io
import json
from pathlib import Path
import unittest
from functools import wraps


class FakeCommands:
    def __init__(self):
        self.nodes = {
            '|mesh': {'type': 'transform'}, '|mesh|shape': {'type': 'mesh'},
            '|B:root': {'type': 'joint', 'liw': False},
            '|A:root': {'type': 'joint', 'liw': False},
            '|B:arm': {'type': 'joint', 'liw': False},
            '|A:arm': {'type': 'joint', 'liw': False},
            'skin': {'type': 'skinCluster'},
        }
        self.influences = ['|B:root', '|A:root', '|B:arm']
        self.enabled = True
        self.chunks = []
        self.calls = []
        self.warnings = []
        self.history = ['skin']
        self.fail_transfer = False

    def undoInfo(self, **kw):
        if kw.get('query'):
            return self.enabled
        if 'stateWithoutFlush' in kw:
            self.enabled = kw['stateWithoutFlush']
        if kw.get('openChunk'):
            self.chunks.append('open')
        if kw.get('closeChunk'):
            self.chunks.append('close')

    def ls(self, names=None, long=False, type=None, **kw):
        if isinstance(names, (list, tuple)):
            result = names
        else:
            result = [n for n in self.nodes if n == names or n.rsplit('|', 1)[-1] == names or self.nodes[n].get('uuid')==names]
        return [n for n in result if n in self.nodes and (type is None or self.nodes[n]['type'] == type)]

    def referenceQuery(self,node,**kw):
        return self.nodes[node].get('referenced',False)

    def group(self,empty,name):
        leaf=name.lstrip(':').replace('#',str(len(self.nodes)+1))
        node='|'+leaf
        self.nodes[node]={'type':'transform','uuid':'group-'+str(len(self.nodes)+1)}
        self.calls.append(('group',node))
        return node

    def parent(self,node,group,**kw):
        new=group+'|'+node.rsplit('|',1)[-1]
        remap={n:new+n[len(node):] for n in self.nodes if n==node or n.startswith(node+'|')}
        self.nodes={remap.get(n,n):data for n,data in self.nodes.items()}
        if hasattr(self,'children'):
            self.children={remap.get(n,n):[remap.get(c,c) for c in values] for n,values in self.children.items()}
            for values in self.children.values():
                if new in values:values.remove(new)
            self.children.setdefault(group,[]).append(new)
        if hasattr(self,'connected'):self.connected={k:remap.get(v,v) for k,v in self.connected.items()}
        self.calls.append(('parent',node,group,kw))
        return [new]

    def objExists(self, node):
        return node in self.nodes

    def nodeType(self, node):
        return self.nodes[node]['type']

    def objectType(self, node, isAType):
        return self.nodes[node]['type'] in ('joint', 'transform') and isAType == 'transform'

    def listRelatives(self, node, **kw):
        return ['|mesh|shape'] if node == '|mesh' else []

    def listHistory(self, node, **kw):
        return self.history

    def skinCluster(self, skin, **kw):
        if kw.get('query'):
            return self.influences[:]
        self.calls.append(('skinCluster', skin, kw))
        if 'addInfluence' in kw:
            self.influences.append(kw['addInfluence'])
        if 'removeInfluence' in kw:
            self.influences.remove(kw['removeInfluence'])

    def skinPercent(self, *args, **kw):
        if self.fail_transfer:
            raise RuntimeError('native transfer failed')
        self.calls.append(('skinPercent', args, kw))

    def attributeQuery(self, attr, node, **kw):
        return attr in self.nodes[node]

    def getAttr(self, plug, **kw):
        node, attr = plug.split('.', 1)
        return self.nodes[node][attr]

    def createNode(self, kind, name, **kw):
        self.calls.append(('createNode', kind, name, kw))
        self.nodes[name] = {'type': kind}
        return name

    def addAttr(self, node, longName, **kw):
        self.calls.append(('addAttr', node, longName))
        self.nodes[node][longName] = ''

    def setAttr(self, plug, value, **kw):
        self.calls.append(('setAttr', plug, value))
        node, attr = plug.split('.', 1)
        self.nodes[node][attr] = value

    def warning(self, message):
        self.warnings.append(message)


class RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())

    def setUp(self):
        self.cmds = FakeCommands()
        wanted = {'_begin_tool_undo', '_end_tool_undo', '_non_undoable_cache_write',
                  '_tool_action', '_read_scene_cache', '_write_scene_cache', 'transfer_namespace_weights'}
        nodes = [node for node in self.tree.body if isinstance(node, ast.FunctionDef) and (node.name in wanted or node.name.startswith("_constraint_"))]
        self.ns = {'cmds': self.cmds, 'json': json, 'wraps': wraps,
                   'contextmanager': contextlib.contextmanager, '_TOOL_UNDO_DEPTH': 0}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<toolkit helpers>', 'exec'), self.ns)

    def transfer(self, *args, **kw):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.ns['transfer_namespace_weights'](*args, **kw)

    def test_bulk_transfer_has_explicit_components_and_one_chunk(self):
        result = self.transfer('mesh', remove_src=False)
        self.assertEqual(len(result['pairs']), 2)
        moves = [c for c in self.cmds.calls if c[0] == 'skinPercent']
        self.assertEqual(len(moves), 2)
        self.assertEqual(moves[0][1], ('skin', '|mesh|shape.vtx[*]'))
        self.assertEqual(moves[0][2]['transformMoveWeights'], ['|B:root', '|A:root'])
        self.assertFalse(moves[0][2]['normalize'])
        self.assertEqual(self.cmds.chunks, ['open', 'close'])
        added = [c for c in self.cmds.calls if c[0] == 'skinCluster' and 'addInfluence' in c[2]]
        self.assertEqual(len(added), 1)

    def test_all_moves_finish_before_source_removal(self):
        self.transfer('mesh')
        moves = [i for i, c in enumerate(self.cmds.calls) if c[0] == 'skinPercent']
        removals = [i for i, c in enumerate(self.cmds.calls) if c[0] == 'skinCluster' and 'removeInfluence' in c[2]]
        self.assertLess(max(moves), min(removals))

    def test_transfer_failure_closes_chunk_and_does_not_remove_sources(self):
        self.cmds.fail_transfer = True
        with self.assertRaises(RuntimeError):
            self.transfer('mesh')
        self.assertEqual(self.ns['_TOOL_UNDO_DEPTH'], 0)
        self.assertEqual(self.cmds.chunks, ['open', 'close'])
        self.assertIn('|B:root', self.cmds.influences)

    def test_locked_influence_blocks_all_mutation(self):
        self.cmds.nodes['|A:arm']['liw'] = True
        self.assertIsNone(self.transfer('mesh'))
        self.assertEqual(self.cmds.calls, [])
        self.assertEqual(self.cmds.chunks, [])

    def test_identical_namespaces_block_all_mutation(self):
        self.assertIsNone(self.transfer('mesh', ':B:', 'B'))
        self.assertEqual(self.cmds.calls, [])

    def test_components_are_rejected(self):
        self.assertIsNone(self.transfer('mesh.vtx[0]'))
        self.assertEqual(self.cmds.calls, [])

    def test_multiple_skin_clusters_are_rejected(self):
        self.cmds.nodes['skin2'] = {'type': 'skinCluster'}
        self.cmds.history.append('skin2')
        self.assertIsNone(self.transfer('mesh'))
        self.assertEqual(self.cmds.calls, [])

    def test_namespace_is_matched_at_leaf_prefix(self):
        self.cmds.nodes['|otherB:root'] = {'type': 'joint', 'liw': False}
        self.cmds.influences = ['|otherB:root']
        self.assertIsNone(self.transfer('mesh'))
        self.assertEqual(self.cmds.calls, [])

    def test_missing_target_leaves_unmatched_source_influence(self):
        del self.cmds.nodes['|A:arm']
        self.transfer('mesh')
        self.assertIn('|B:arm', self.cmds.influences)
        self.assertNotIn('|B:root', self.cmds.influences)

    def test_nested_actions_use_one_chunk_and_unwind_exception(self):
        with self.assertRaises(ValueError):
            with self.ns['_tool_action']('outer'):
                with self.ns['_tool_action']('inner'):
                    raise ValueError('test')
        self.assertEqual(self.cmds.chunks, ['open', 'close'])
        self.assertEqual(self.ns['_TOOL_UNDO_DEPTH'], 0)

    def test_cache_write_creates_network_and_writes_once(self):
        self.ns['_write_scene_cache']('cache', 'data', [{'targets': 'root'}])
        self.assertEqual(self.cmds.nodes['cache']['type'], 'network')
        self.assertEqual(len([c for c in self.cmds.calls if c[0] == 'setAttr']), 1)
        self.assertTrue(self.cmds.enabled)

    def test_unchanged_cache_is_not_written_again(self):
        self.ns['_write_scene_cache']('cache', 'data', [{'a': 1, 'b': 2}])
        self.cmds.calls.clear()
        self.assertFalse(self.ns['_write_scene_cache']('cache', 'data', [{'b': 2, 'a': 1}]))
        self.assertEqual(self.cmds.calls, [])

    def test_existing_cache_transform_type_is_preserved(self):
        self.cmds.nodes['cache'] = {'type': 'transform'}
        self.ns['_write_scene_cache']('cache', 'data', [])
        self.assertEqual(self.cmds.nodes['cache']['type'], 'transform')
        self.assertEqual(self.ns['_read_scene_cache']('cache', 'data'), [])

    def test_bad_cache_schema_is_reported(self):
        self.cmds.nodes['cache'] = {'type': 'network', 'data': '{"targets": 12}'}
        with self.assertRaises(ValueError):
            self.ns['_read_scene_cache']('cache', 'data')

    def test_cache_write_restores_undo_state_on_exception(self):
        @self.ns['_non_undoable_cache_write']
        def failing():
            raise RuntimeError('write failed')
        with self.assertRaises(RuntimeError):
            failing()
        self.assertTrue(self.cmds.enabled)
        self.assertEqual(failing.__name__, 'failing')

    def test_disabled_undo_stays_disabled_after_cache_write(self):
        self.cmds.enabled = False
        self.ns['_write_scene_cache']('cache', 'data', [])
        self.assertFalse(self.cmds.enabled)


class HierarchyCommands(FakeCommands):
    def __init__(self):
        super(HierarchyCommands, self).__init__()
        self.nodes = {
            '|old': {'type': 'transform'}, '|new': {'type': 'transform'},
            '|old|arm': {'type': 'joint'}, '|old|arm|tip': {'type': 'joint'},
            '|old|leg': {'type': 'joint'}, '|new|arm': {'type': 'joint'},
            '|new|arm|tip': {'type': 'joint'}, '|new|leg': {'type': 'joint'},
            '|old|shape': {'type': 'mesh'},
        }
        self.children = {
            '|old': ['|old|arm', '|old|leg', '|old|shape'],
            '|old|arm': ['|old|arm|tip'],
            '|new': ['|new|leg', '|new|arm'],  # Deliberately different sibling order.
            '|new|arm': ['|new|arm|tip'],
        }
        self.connected = {}
        self.locked = set()
        self.fail_scale_on = set()
        self.serial = 0
        self.deleted = []

    def ls(self, names=None, **kw):
        if kw.get('uuid'):
            return [self.nodes[names].get('uuid', names)]
        return super(HierarchyCommands, self).ls(names, **kw)

    def listRelatives(self, node, **kw):
        if kw.get('parent'):
            parent=node.rsplit('|',1)[0]
            return [parent] if parent else []
        return self.children.get(node, [])[:]

    def lockNode(self, node, **kw):
        return [self.nodes[node].get('node_locked', False)]

    def listConnections(self, plug, **kw):
        return [self.connected[plug]+'.output'] if plug in self.connected else []

    def getAttr(self, plug, **kw):
        if kw.get('settable'):
            return plug not in self.locked and plug not in self.connected
        if kw.get('lock'):
            return plug in self.locked
        return super(HierarchyCommands, self).getAttr(plug, **kw)

    def _constraint(self, kind, old, new, kw):
        self.serial += 1
        name = new + '|testConstraint' + str(self.serial)
        self.nodes[name] = {'type':kind,'uuid':'constraint-'+str(self.serial)}
        self.children.setdefault(new, []).append(name)
        axes = ['scale'] if kind == 'scaleConstraint' else ['translate', 'rotate']
        for prefix in axes:
            for axis in 'XYZ':
                self.connected[new+'.'+prefix+axis] = name
        self.calls.append((kind, old, new, kw))
        return [name]

    def parentConstraint(self, old, new, **kw):
        return self._constraint('parentConstraint', old, new, kw)

    def scaleConstraint(self, old, new, **kw):
        if new in self.fail_scale_on:
            raise RuntimeError('Scale command failed')
        return self._constraint('scaleConstraint', old, new, kw)

    def delete(self, nodes):
        for node in nodes:
            self.deleted.append(node)
            self.nodes.pop(node, None)
            for children in self.children.values():
                if node in children:
                    children.remove(node)
            self.connected = {plug: owner for plug, owner in self.connected.items() if owner != node}


class HierarchyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())

    def setUp(self):
        self.cmds = HierarchyCommands()
        wanted = {'_begin_tool_undo', '_end_tool_undo', '_tool_action',
                  '_resolve_hierarchy_root', '_hierarchy_snapshot', '_hierarchy_target_blockers',
                  'plan_matching_hierarchies', 'constrain_matching_hierarchies'}
        nodes = [node for node in self.tree.body if isinstance(node, ast.FunctionDef) and (node.name in wanted or node.name.startswith("_constraint_"))]
        self.ns = {'cmds': self.cmds, 'contextmanager': contextlib.contextmanager, '_TOOL_UNDO_DEPTH': 0}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<hierarchy helpers>', 'exec'), self.ns)

    def plan(self, old='old', new='new', **kw):
        return self.ns['plan_matching_hierarchies'](old, new, **kw)

    def create(self, old='old', new='new', **kw):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.ns['constrain_matching_hierarchies'](old, new, **kw)

    def rename(self, old, new):
        changed = {key: new + key[len(old):] for key in self.cmds.nodes if key == old or key.startswith(old+'|')}
        self.cmds.nodes = {changed.get(key, key): value for key, value in self.cmds.nodes.items()}
        self.cmds.children = {changed.get(key, key): [changed.get(child, child) for child in value]
                              for key, value in self.cmds.children.items()}

    def test_names_match_correctly_despite_reordered_siblings(self):
        rows = self.plan()['rows']
        self.assertEqual([(r['old'], r['new']) for r in rows], [
            ('|old','|new'), ('|old|arm','|new|arm'), ('|old|arm|tip','|new|arm|tip'), ('|old|leg','|new|leg')])
        self.assertEqual(self.cmds.calls, [])

    def test_shapes_are_excluded_from_preview(self):
        self.assertEqual(self.plan()['old_count'], 4)

    def test_equal_count_with_different_branching_is_rejected(self):
        self.cmds.children['|new'] = ['|new|arm', '|new|leg']
        del self.cmds.children['|new|arm']
        self.rename('|new|arm|tip', '|new|leg|tip')
        self.cmds.children['|new|leg'] = ['|new|leg|tip']
        self.assertEqual(len(self.cmds.nodes), 9)
        with self.assertRaises(ValueError):
            self.plan(match_mode='structure')

    def test_structure_mode_handles_different_names(self):
        self.cmds.children['|new'] = ['|new|arm', '|new|leg']
        self.rename('|new|arm', '|new|renamedArm')
        self.rename('|new|leg', '|new|renamedLeg')
        rows = self.plan(match_mode='structure')['rows']
        self.assertEqual(rows[1]['new'], '|new|renamedArm')

    def test_names_mode_ignores_namespaces(self):
        self.rename('|new|arm|tip','|new|arm|rig:tip')
        self.rename('|new|arm','|new|rig:arm')
        self.rename('|new|leg','|new|rig:leg')
        self.assertEqual(len(self.plan()['rows']), 4)
        with self.assertRaises(ValueError):
            self.plan(ignore_namespaces=False)

    def test_source_search_replace_applies_to_relative_names(self):
        self.rename('|old|arm|tip','|old|arm|old_tip')
        self.rename('|old|arm','|old|old_arm')
        self.rename('|old|leg','|old|old_leg')
        rows = self.plan(search='old_', replace='')['rows']
        self.assertEqual(rows[2]['new'], '|new|arm|tip')

    def test_duplicate_normalized_relative_names_are_rejected(self):
        self.cmds.nodes['|new|other:arm'] = {'type': 'joint'}
        self.cmds.children['|new'].append('|new|other:arm')
        with self.assertRaisesRegex(ValueError, 'Duplicate relative path'):
            self.plan()

    def test_identical_and_overlapping_roots_are_rejected(self):
        for old,new in [('old','old'), ('old','|old|arm'), ('|old|arm','old')]:
            with self.assertRaises(ValueError):
                self.plan(old,new)

    def test_shared_instances_are_rejected(self):
        self.cmds.nodes['|new|arm']['uuid'] = '|old|arm'
        with self.assertRaisesRegex(ValueError, 'share instanced'):
            self.plan()

    def test_node_type_mismatch_is_rejected(self):
        self.cmds.nodes['|new|leg']['type'] = 'transform'
        with self.assertRaisesRegex(ValueError, 'Node type mismatch'):
            self.plan()

    def test_optional_root_is_excluded(self):
        rows = self.plan(include_root=False)['rows']
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['old'], '|old|arm')

    def test_no_constraint_types_selected_is_rejected(self):
        with self.assertRaises(ValueError):
            self.plan(parent_constraint=False,scale_constraint=False)

    def test_locked_target_channels_are_reported(self):
        self.cmds.locked.add('|new|arm.translateX')
        row = next(row for row in self.plan()['rows'] if row['new'] == '|new|arm')
        self.assertEqual(row['status'], 'Blocked')
        self.assertIn('translateX is locked', row['reason'])

    def test_animated_target_is_blocked_even_if_maya_reports_settable(self):
        plug = '|new|arm.translateX'
        self.cmds.connected[plug] = 'existingAnimCurve'
        previous = self.cmds.getAttr
        self.cmds.getAttr = lambda path, **kw: True if path == plug and kw.get('settable') else previous(path, **kw)
        row = next(row for row in self.plan()['rows'] if row['new'] == '|new|arm')
        self.assertEqual(row['status'], 'Blocked')
        self.assertIn('incoming connection',row['reason'])

    def test_stop_mode_preflights_all_pairs_before_mutations(self):
        self.cmds.locked.add('|new|arm.translateX')
        with self.assertRaisesRegex(ValueError,'No changes made'):
            self.create(skip_blocked=False)
        self.assertEqual(self.cmds.calls, [])
        self.assertEqual(self.cmds.chunks, [])

    def test_skip_mode_creates_only_unblocked_pairs(self):
        self.cmds.locked.add('|new|arm.translateX')
        result = self.create()
        self.assertEqual(len(result['created_pairs']),3)
        self.assertEqual(len(result['constraints']),6)
        self.assertEqual(len(result['skipped']),1)
        self.assertEqual(self.cmds.chunks,['open','close'])
        self.assertTrue(all(c[3]['maintainOffset'] for c in self.cmds.calls if c[0].endswith('Constraint')))

    def test_scale_only_ignores_locked_translate_channels(self):
        self.cmds.locked.add('|new|arm.translateX')
        result = self.create(parent_constraint=False,maintain_offset=False)
        self.assertEqual(len(result['created_pairs']),4)
        self.assertTrue(all(c[0]=='scaleConstraint' and not c[3]['maintainOffset'] for c in self.cmds.calls if c[0].endswith('Constraint')))

    def test_failure_removes_only_current_pairs_new_parent_constraint(self):
        self.cmds.nodes['unrelated']={'type':'parentConstraint'}
        self.cmds.fail_scale_on.add('|new|arm')
        result = self.create()
        self.assertEqual(len(result['created_pairs']),3)
        self.assertEqual(len(result['failed']),1)
        self.assertEqual(len(self.cmds.deleted),1)
        self.assertTrue(self.cmds.deleted[0].startswith('|constraintNode|'))
        self.assertIn('unrelated',self.cmds.nodes)
        self.assertNotIn('|new|arm.translateX',self.cmds.connected)

    def test_runtime_failure_stops_later_pairs_in_stop_mode(self):
        self.cmds.fail_scale_on.add('|new|arm')
        result = self.create(skip_blocked=False)
        self.assertEqual(len(result['created_pairs']),1)
        self.assertEqual(len(result['failed']),1)
        self.assertEqual(len(result['not_run']),2)
        self.assertEqual(self.cmds.chunks,['open','close'])

    def test_repeated_run_skips_existing_connections_and_creates_no_duplicates(self):
        self.create()
        count = len(self.cmds.calls)
        result = self.create()
        self.assertEqual(result['created_pairs'], [])
        self.assertEqual(len(result['skipped']),4)
        self.assertEqual(len(self.cmds.calls),count)


class CustomCommands(HierarchyCommands):
    def __init__(self):
        super(CustomCommands, self).__init__()
        self.nodes = {'|source': {'type':'transform'}, '|target': {'type':'transform'}, '|other': {'type':'transform'}}
        self.definitions = {node:{} for node in self.nodes}
        self.inputs = {}
        self.fail_on = set()
        for node in ('|source','|target'):
            self.define(node,'translateX',dynamic=False)
            self.define(node,'rotateX',dynamic=False)
            self.define(node,'scaleX',value=1,dynamic=False)
        self.define('|other','output',value=.9)

    def define(self,node,attr,kind='double',value=0,dynamic=True,**extra):
        schema={'type':kind,'definition_type':'typed' if kind in ('string','matrix') else kind,
                'value':value,'dynamic':dynamic,'parent':None,'children':[], 'shortName':attr,
                'niceName':attr,'keyable':True,'channelBox':False,'lock':False,'hidden':False,
                'readable':True,'writable':True,'connectable':True,'storable':True,
                'usedAsColor':False,'usedAsFilename':False,'multi':False,'default':0,'limits':{},'enum':''}
        schema.update(extra)
        self.definitions[node][attr]=schema
        if schema['parent']:
            self.definitions[node][schema['parent']]['children'].append(attr)

    def objExists(self,name):
        if '.' in name:
            node,attr=name.split('.',1)
            return attr in self.definitions.get(node,{})
        return name in self.nodes

    def listAttr(self,node,**kw):
        return [name for name,spec in self.definitions[node].items() if spec['dynamic']]

    def attributeQuery(self,attr,node,**kw):
        aliases={s['shortName']:name for name,s in self.definitions[node].items()}
        attr=aliases.get(attr,attr)
        if kw.get('exists'):
            return attr in self.definitions[node]
        spec=self.definitions[node][attr]
        if kw.get('attributeType'): return spec['definition_type']
        if kw.get('listChildren'): return spec['children'][:]
        if kw.get('listParent'): return [spec['parent']] if spec['parent'] else []
        if kw.get('listDefault'): return [spec['default']]
        if kw.get('listEnum'): return [spec['enum']]
        for flag,creation in [('minExists','minValue'),('maxExists','maxValue'),('softMinExists','softMinValue'),('softMaxExists','softMaxValue')]:
            if kw.get(flag): return creation in spec['limits']
        for flag,creation in [('minimum','minValue'),('maximum','maxValue'),('softMin','softMinValue'),('softMax','softMaxValue')]:
            if kw.get(flag): return [spec['limits'][creation]]
        return spec[next(flag for flag,value in kw.items() if value)]

    def getAttr(self,plug,**kw):
        node,attr=plug.split('.',1); spec=self.definitions[node][attr]
        for flag in ('type','keyable','channelBox','lock'):
            if kw.get(flag): return spec[flag]
        if plug in self.inputs: return self.getAttr(self.inputs[plug])
        return spec['value']

    def setAttr(self,plug,*values,**kw):
        node,attr=plug.split('.',1); spec=self.definitions[node][attr]
        self.calls.append(('setAttr',plug,values,kw))
        for flag in ('keyable','channelBox','lock'):
            if flag in kw: spec[flag]=kw[flag]
        if values:
            if spec['lock']: raise RuntimeError('Attribute locked')
            spec['value']=values[0] if len(values)==1 else tuple(values)

    def addAttr(self,node,**kw):
        name=kw['longName']; kind=kw.get('dataType',kw.get('attributeType','double'))
        self.calls.append(('addAttr',node,kw))
        self.define(node,name,kind=kind,value=kw.get('defaultValue',0),
            definition_type='typed' if 'dataType' in kw else kind,parent=kw.get('parent'),
            shortName=kw.get('shortName',name),niceName=kw.get('niceName',name),
            keyable=kw.get('keyable',False),hidden=kw.get('hidden',False),
            readable=kw.get('readable',True),writable=kw.get('writable',True),storable=kw.get('storable',True),
            usedAsColor=kw.get('usedAsColor',False),usedAsFilename=kw.get('usedAsFilename',False),
            default=kw.get('defaultValue',0),enum=kw.get('enumName',''),
            limits={key:value for key,value in kw.items() if key in ('minValue','maxValue','softMinValue','softMaxValue')})

    def isConnected(self,driver,driven):
        return self.inputs.get(driven)==driver

    def listConnections(self,plug,**kw):
        return [self.inputs[plug]] if plug in self.inputs else []

    def connectionInfo(self,plug,**kw):
        return plug in self.inputs

    def connectAttr(self,driver,driven,**kw):
        if driven in self.fail_on: raise RuntimeError('Connection failed')
        if self.getAttr(driven,lock=True): raise RuntimeError('Source destination locked')
        if driven in self.inputs and not kw.get('force'): raise RuntimeError('Existing input')
        self.inputs[driven]=driver
        self.calls.append(('connectAttr',driver,driven,kw))

    def disconnectAttr(self,driver,driven):
        if self.inputs.get(driven)==driver: del self.inputs[driven]

    def deleteAttr(self,plug):
        node,attr=plug.split('.',1)
        names=[attr]+self.definitions[node][attr]['children']
        for name in names:
            self.definitions[node].pop(name,None)
        self.inputs={driven:driver for driven,driver in self.inputs.items() if driver not in {node+'.'+name for name in names}}


class CustomAttributeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree=ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())

    def setUp(self):
        self.cmds=CustomCommands()
        wanted={'_begin_tool_undo','_end_tool_undo','_tool_action','_resolve_hierarchy_root',
                '_custom_attr_schema','_custom_attr_parts','_custom_attr_leaves','_custom_attr_signature',
                'plan_custom_attribute_transfer','_create_custom_attr_definition','_copy_custom_attr_value',
                '_set_custom_attr_value','copy_custom_attributes_and_connect'}
        nodes=[n for n in self.tree.body if isinstance(n,ast.FunctionDef) and (n.name in wanted or n.name.startswith("_constraint_"))]
        constants=[n for n in self.tree.body if isinstance(n,ast.Assign) and any(getattr(t,'id','').startswith('_CUSTOM_') for t in n.targets)]
        self.ns={'cmds':self.cmds,'contextmanager':contextlib.contextmanager,'_TOOL_UNDO_DEPTH':0}
        exec(compile(ast.Module(body=constants+nodes,type_ignores=[]),'<custom helpers>','exec'),self.ns)

    def plan(self,**kw):
        return self.ns['plan_custom_attribute_transfer']('source','target',**kw)

    def apply(self,**kw):
        return self.ns['copy_custom_attributes_and_connect']('source','target',**kw)

    def vector(self,node='|source'):
        self.cmds.define(node,'offset',kind='double3')
        for child,value in [('offsetX',1),('offsetY',2),('offsetZ',3)]:
            self.cmds.define(node,child,parent='offset',value=value)

    def test_builtin_transform_attributes_are_never_listed_or_copied(self):
        self.cmds.define('|source','blend',value=.4)
        self.assertEqual([r['attribute'] for r in self.plan()['rows']],['blend'])
        self.apply()
        self.assertFalse(any('translateX' in str(c) or 'rotateX' in str(c) or 'scaleX' in str(c) for c in self.cmds.calls))

    def test_target_drives_source_and_initial_values_match(self):
        self.cmds.define('|source','blend',value=.8)
        result=self.apply()
        self.assertEqual(result['connected'],[('|target.blend','|source.blend')])
        self.assertEqual(self.cmds.getAttr('|target.blend'),.8)
        self.cmds.setAttr('|target.blend',.25)
        self.assertEqual(self.cmds.getAttr('|source.blend'),.25)
        self.assertEqual(self.cmds.chunks,['open','close'])

    def test_numeric_definition_defaults_limits_and_ui_flags_are_preserved(self):
        self.cmds.define('|source','blend',value=.8,default=.5,shortName='blnd',niceName='IK FK Blend',
                         keyable=False,channelBox=True,limits={'minValue':0,'maxValue':1,'softMinValue':.1,'softMaxValue':.9})
        self.apply()
        s=self.cmds.definitions['|source']['blend'];t=self.cmds.definitions['|target']['blend']
        for key in ('type','default','limits','shortName','niceName','keyable','channelBox'): self.assertEqual(s[key],t[key])

    def test_enum_choices_with_explicit_values_are_preserved(self):
        self.cmds.define('|source','space',kind='enum',enum='World=0:Body=5:Hand=10',default=5,value=10)
        self.apply()
        self.assertEqual(self.cmds.definitions['|target']['space']['enum'],'World=0:Body=5:Hand=10')
        self.assertEqual(self.cmds.getAttr('|target.space'),10)

    def test_strings_and_matrices_use_typed_attributes(self):
        self.cmds.define('|source','label',kind='string',value='left controller',keyable=False)
        matrix=tuple(range(16));self.cmds.define('|source','customMatrix',kind='matrix',value=matrix,keyable=False)
        self.apply()
        self.assertEqual(self.cmds.getAttr('|target.label'),'left controller')
        self.assertEqual(self.cmds.getAttr('|target.customMatrix'),matrix)

    def test_numeric_vector_is_one_row_and_child_connections_match(self):
        self.vector()
        self.assertEqual(len(self.plan()['rows']),1)
        result=self.apply()
        self.assertEqual(len(result['connected']),3)
        self.assertEqual(self.cmds.definitions['|target']['offset']['children'],['offsetX','offsetY','offsetZ'])
        self.assertEqual(self.cmds.getAttr('|target.offsetY'),2)

    def test_selected_attributes_only(self):
        self.cmds.define('|source','one');self.cmds.define('|source','two')
        result=self.apply(attributes=['two'])
        self.assertEqual(result['created'],['two'])
        self.assertFalse(self.cmds.objExists('|target.one'))
        with self.assertRaises(ValueError): self.apply(attributes=['translateX'])

    def test_compatible_existing_target_retains_its_value(self):
        self.cmds.define('|source','blend',value=.8);self.cmds.define('|target','blend',value=.2)
        result=self.apply()
        self.assertEqual(result['created'],[])
        self.assertEqual(self.cmds.getAttr('|source.blend'),.2)

    def test_target_builtin_name_collision_is_blocked(self):
        self.cmds.define('|source','radius');self.cmds.define('|target','radius',dynamic=False)
        self.assertEqual(self.plan()['rows'][0]['status'],'Blocked')
        self.assertFalse(self.apply()['changed'])

    def test_incompatible_existing_type_is_blocked(self):
        self.cmds.define('|source','blend');self.cmds.define('|target','blend',kind='bool')
        self.assertEqual(self.plan()['rows'][0]['status'],'Blocked')
        self.assertFalse(self.apply()['changed'])

    def test_existing_source_input_is_preserved_unless_replace_enabled(self):
        self.cmds.define('|source','blend');self.cmds.inputs['|source.blend']='|other.output'
        self.assertEqual(self.plan()['rows'][0]['status'],'Blocked')
        self.assertFalse(self.apply()['changed'])
        self.apply(replace_source_inputs=True)
        self.assertEqual(self.cmds.inputs['|source.blend'],'|target.blend')

    def test_locked_source_can_be_copied_without_connecting(self):
        self.cmds.define('|source','heading',kind='enum',enum='Controls',lock=True,keyable=False,channelBox=True)
        result=self.apply()
        self.assertEqual(result['created'],['heading'])
        self.assertEqual(result['connected'],[])
        self.assertTrue(self.cmds.getAttr('|target.heading',lock=True))

    def test_unlock_option_enables_target_to_drive_locked_source(self):
        self.cmds.define('|source','blend',lock=True)
        result=self.apply(unlock_source=True)
        self.assertEqual(len(result['connected']),1)
        self.assertFalse(self.cmds.getAttr('|source.blend',lock=True))
        self.assertFalse(self.cmds.getAttr('|target.blend',lock=True))

    def test_reverse_connection_is_reported_without_creating_a_cycle(self):
        self.cmds.define('|source','blend');self.cmds.define('|target','blend')
        self.cmds.inputs['|target.blend']='|source.blend'
        self.assertEqual(self.plan()['rows'][0]['status'],'Blocked')
        self.assertFalse(self.apply()['changed'])

    def test_repeat_run_makes_no_extra_changes(self):
        self.cmds.define('|source','blend');self.apply();count=len(self.cmds.calls)
        result=self.apply()
        self.assertFalse(result['changed'])
        self.assertEqual(len(self.cmds.calls),count)
        self.assertEqual(result['plan']['rows'][0]['status'],'Connected')

    def test_multi_and_message_attributes_are_reported_unsupported(self):
        self.cmds.define('|source','weights',multi=True);self.cmds.define('|source','owner',kind='message')
        self.assertTrue(all(r['status']=='Unsupported' for r in self.plan()['rows']))
        self.assertFalse(self.apply()['changed'])

    def test_failed_vector_connection_removes_new_attribute_and_closes_chunk(self):
        self.vector();self.cmds.fail_on.add('|source.offsetY')
        result=self.apply()
        self.assertEqual(result['failed'],['offset'])
        self.assertFalse(self.cmds.objExists('|target.offset'))
        self.assertFalse(self.cmds.inputs)
        self.assertEqual(self.cmds.chunks,['open','close'])
        self.assertEqual(self.ns['_TOOL_UNDO_DEPTH'],0)

    def test_failed_existing_vector_restores_prior_source_input(self):
        self.vector();self.vector('|target')
        self.cmds.inputs['|source.offsetX']='|other.output';self.cmds.fail_on.add('|source.offsetY')
        result=self.apply(replace_source_inputs=True)
        self.assertEqual(result['failed'],['offset'])
        self.assertEqual(self.cmds.inputs['|source.offsetX'],'|other.output')
        self.assertTrue(self.cmds.objExists('|target.offset'))

    def test_same_controller_is_rejected(self):
        with self.assertRaises(ValueError):
            self.ns['plan_custom_attribute_transfer']('source','source')


class LocatorViewCommands(FakeCommands):
    def __init__(self):
        super(LocatorViewCommands, self).__init__()
        self.nodes = {}
        self.serial = 0
        self.inputs = {}
        self.selection = []
        self.fail_parent = False
        self.fail_scale = False
        self.add_node('|rig', 'transform')
        self.add_node('|rig|root', 'joint', matrix=self.matrix(1, 2, 3))
        self.add_node('|rig|root|middle', 'transform')
        self.add_node('|rig|root|middle|child', 'joint', matrix=self.matrix(4, 5, 6))
        self.add_node('|rig|root|middle|child|tip', 'joint', matrix=self.matrix(7, 8, 9))
        self.selection = ['|rig|root']

    @staticmethod
    def matrix(x,y,z):
        return [1,0,0,0, 0,1,0,0, 0,0,1,0, x,y,z,1]

    def add_node(self, path, kind, **extra):
        self.serial += 1
        self.nodes[path] = {'type':kind, 'uuid':'uuid-'+str(self.serial),
                            'attrs':{'message':None}, 'matrix':self.matrix(0,0,0)}
        self.nodes[path].update(extra)
        return path

    def ls(self, names=None, **kw):
        if kw.get('selection'):
            return self.selection[:]
        matches = [node for node,spec in self.nodes.items()
                   if node == names or spec['uuid'] == names or node.rsplit('|',1)[-1] == names]
        if kw.get('type'):
            matches = [node for node in matches if self.nodes[node]['type'] == kw['type']]
        return [self.nodes[node]['uuid'] for node in matches] if kw.get('uuid') else matches

    def objExists(self, name):
        if '.' in name:
            node,attribute = name.rsplit('.',1)
            return node in self.nodes and attribute in self.nodes[node]['attrs']
        return name in self.nodes or bool(self.ls(name))

    def listRelatives(self, node, **kw):
        if kw.get('allParents'):
            if self.nodes[node].get('instanced'):
                return ['|parent1','|parent2']
            parent = node.rsplit('|',1)[0]
            return [parent] if parent else []
        if kw.get('allDescendents'):
            matches = [other for other in self.nodes if other.startswith(node+'|')]
        else:
            matches = [other for other in self.nodes if other.rsplit('|',1)[0] == node]
        if kw.get('type'):
            matches = [other for other in matches if self.nodes[other]['type'] == kw['type']]
        return matches

    def attributeQuery(self, attribute, node, **kw):
        return attribute in self.nodes[node]['attrs']

    def addAttr(self, node, longName, **kw):
        self.nodes[node]['attrs'][longName] = '' if kw.get('dataType') == 'string' else None

    def getAttr(self, plug, **kw):
        node,attribute = plug.rsplit('.',1)
        return self.nodes[node]['attrs'][attribute]

    def setAttr(self, plug, *values, **kw):
        node,attribute = plug.rsplit('.',1)
        if values:
            self.nodes[node]['attrs'][attribute] = values[0]
        self.calls.append(('setAttr',plug,values,kw))

    def group(self, empty, name):
        name = name.lstrip(':').replace('#',str(self.serial+1))
        path = self.add_node('|'+name,'transform')
        self.selection = [path]
        self.calls.append(('group',path))
        return path

    def spaceLocator(self, name):
        name = name.lstrip(':').replace('#',str(self.serial+1))
        locator = self.add_node('|'+name,'transform')
        shape = self.add_node(locator+'|'+name+'Shape','locator')
        self.nodes[shape]['attrs'].update({'localScaleX':1,'localScaleY':1,'localScaleZ':1})
        self.selection = [locator]
        self.calls.append(('spaceLocator',locator))
        return [locator]

    def parent(self, node, group, **kw):
        if self.fail_parent:
            raise RuntimeError('Parent failed')
        new = group+'|'+node.rsplit('|',1)[-1]
        if new!=node and new in self.nodes:
            base=new;index=2
            while new in self.nodes:new=base+str(index);index+=1
        remap = {other:new+other[len(node):] for other in self.nodes if other==node or other.startswith(node+'|')}
        self.nodes = {remap.get(other,other):spec for other,spec in self.nodes.items()}
        def plug(value):
            n,a=value.split('.',1)
            return remap.get(n,n)+'.'+a
        self.inputs={plug(k):plug(v) for k,v in self.inputs.items()}
        self.selection = [remap.get(other,other) for other in self.selection]
        self.calls.append(('parent',node,group))
        return [new]

    def xform(self, node, **kw):
        if kw.get('query'):
            return self.nodes[node]['matrix'][:]
        self.nodes[node]['matrix'] = kw['matrix'][:]
        self.calls.append(('xform',node,kw))

    def connectAttr(self, driver, driven):
        self.inputs[driven] = driver

    def listConnections(self, plug, **kw):
        if kw.get('destination'):
            return [driven for driven,driver in self.inputs.items() if driver == plug]
        return [self.inputs[plug]] if plug in self.inputs else []

    def parentConstraint(self, source, target, **kw):
        node = self.add_node(target+'|parentConstraint'+str(self.serial+1),'parentConstraint')
        self.calls.append(('parentConstraint',source,target,kw))
        return [node]

    def scaleConstraint(self, source, target, **kw):
        if self.fail_scale:
            raise RuntimeError('Scale constraint failed')
        node = self.add_node(target+'|scaleConstraint'+str(self.serial+1),'scaleConstraint')
        self.calls.append(('scaleConstraint',source,target,kw))
        return [node]

    def delete(self, nodes):
        if isinstance(nodes,str): nodes = [nodes]
        removed = {node for node in self.nodes if any(node==root or node.startswith(root+'|') for root in nodes)}
        self.nodes = {node:spec for node,spec in self.nodes.items() if node not in removed}
        self.inputs = {driven:driver for driven,driver in self.inputs.items()
                       if driven.rsplit('.',1)[0] not in removed and driver.rsplit('.',1)[0] not in removed}
        self.selection = [node for node in self.selection if node not in removed]
        self.calls.append(('delete',nodes[:]))

    def select(self, objects=None, **kw):
        self.selection = [] if kw.get('clear') else objects[:]

    def lockNode(self, node, **kw):
        return [self.nodes[node].get('node_locked',False)]


class LocatorViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())

    def setUp(self):
        import math
        self.cmds = LocatorViewCommands()
        wanted = {'_begin_tool_undo','_end_tool_undo','_tool_action','_non_undoable_cache_write',
                  '_resolve_hierarchy_root','_resolve_locator_view_joint','_is_locator_view_group',
                  'find_locator_view_groups','_check_locator_view_members','_restore_locator_view_selection',
                  'generate_locator_view','delete_locator_view'}
        nodes = [node for node in self.tree.body if isinstance(node,ast.FunctionDef) and (node.name in wanted or node.name.startswith("_constraint_"))]
        constants = [node for node in self.tree.body if isinstance(node,ast.Assign)
                     and any(getattr(target,'id','').startswith('_LOCATOR_VIEW_') for target in node.targets)]
        self.ns = {'cmds':self.cmds,'json':json,'math':math,'wraps':wraps,
                   'contextmanager':contextlib.contextmanager,'_TOOL_UNDO_DEPTH':0}
        exec(compile(ast.Module(body=constants+nodes,type_ignores=[]),'<locator view helpers>','exec'),self.ns)

    def generate(self, **kw):
        return self.ns['generate_locator_view']('|rig|root', **kw)

    def test_joint_only_creates_one_grouped_locator_and_matches_matrix(self):
        result = self.generate(size=2,match_mode='world_matrix')
        self.assertEqual(len(result['locators']),1)
        loc = result['locators'][0]
        self.assertTrue(loc.startswith(result['group']+'|'))
        self.assertEqual(self.cmds.nodes[loc]['matrix'],self.cmds.nodes['|rig|root']['matrix'])
        shape = self.cmds.listRelatives(loc,type='locator')[0]
        for axis in 'XYZ': self.assertEqual(self.cmds.getAttr(shape+'.localScale'+axis),2)
        self.assertEqual(result['constraints'],[])

    def test_children_checkbox_includes_only_descendant_joints_even_under_transforms(self):
        result = self.generate(include_children=True)
        self.assertEqual(len(result['locators']),3)
        self.assertEqual(len(result['constraints']),6)

    def test_constraints_run_from_each_joint_to_its_locator_with_no_offset(self):
        result = self.generate()
        calls = [call for call in self.cmds.calls if call[0] in ('parentConstraint','scaleConstraint')]
        self.assertEqual(len(calls),2)
        for call in calls:
            self.assertEqual(call[1],'|rig|root')
            self.assertEqual(call[2],result['locators'][0])
            self.assertFalse(call[3]['maintainOffset'])

    def test_generate_and_delete_preserve_selection_and_use_one_chunk_each(self):
        self.generate()
        self.assertEqual(self.cmds.selection,['|rig|root'])
        self.assertEqual(self.cmds.chunks,['open','close'])
        self.ns['delete_locator_view']('|rig|root')
        self.assertEqual(self.cmds.selection,['|rig|root'])
        self.assertEqual(self.cmds.chunks,['open','close','open','close'])
        self.assertTrue(self.cmds.enabled)

    def test_generate_does_not_change_joint_matrices_or_parent_paths(self):
        before = {n:s['matrix'][:] for n,s in self.cmds.nodes.items() if s['type']=='joint'}
        self.generate(include_children=True)
        self.assertEqual(before,{n:s['matrix'][:] for n,s in self.cmds.nodes.items() if s['type']=='joint'})

    def test_repeat_generate_replaces_previous_view_and_keeps_one_group(self):
        first = self.generate()
        second = self.generate(size=3,include_children=True,match_mode='world_matrix')
        self.assertFalse(self.cmds.objExists(first['group']))
        self.assertEqual(self.ns['find_locator_view_groups']('|rig|root'),[second['group']])
        self.assertEqual(len(second['locators']),3)

    def test_failed_constraint_generation_preserves_previous_view(self):
        previous = self.generate(match_mode='world_matrix')
        before = set(self.cmds.nodes)
        self.cmds.fail_scale = True
        with self.assertRaises(RuntimeError): self.generate()
        self.assertEqual(set(self.cmds.nodes),before)
        self.assertTrue(self.cmds.objExists(previous['group']))
        self.assertEqual(self.ns['_TOOL_UNDO_DEPTH'],0)

    def test_failed_parent_leaves_no_loose_locator_or_group(self):
        before = set(self.cmds.nodes)
        self.cmds.fail_parent = True
        with self.assertRaises(RuntimeError): self.generate()
        self.assertEqual(set(self.cmds.nodes),before)
        self.assertEqual(self.cmds.selection,['|rig|root'])

    def test_delete_is_scoped_to_selected_root_not_legacy_or_other_views(self):
        first = self.generate()
        other = self.ns['generate_locator_view']('|rig|root|middle|child')
        legacy = self.cmds.add_node('|root_GuideLoc','transform')
        ordinary = self.cmds.add_node('|root_locatorView_grp_fake','transform')
        self.ns['delete_locator_view']('|rig|root')
        self.assertFalse(self.cmds.objExists(first['group']))
        for node in (other['group'],legacy,ordinary,'|rig|root'): self.assertTrue(self.cmds.objExists(node))

    def test_foreign_descendant_blocks_deletion_and_regeneration(self):
        result = self.generate()
        foreign = self.cmds.add_node(result['locators'][0]+'|foreignShape','mesh')
        count = len(self.cmds.calls)
        with self.assertRaisesRegex(ValueError,'unrelated object'): self.ns['delete_locator_view']('|rig|root')
        with self.assertRaisesRegex(ValueError,'unrelated object'): self.generate()
        self.assertTrue(self.cmds.objExists(foreign))
        self.assertEqual(len(self.cmds.calls),count)

    def test_invalid_sizes_and_modes_make_no_scene_changes(self):
        for size in (0,-1,float('nan'),float('inf'),'wrong'):
            with self.assertRaises(ValueError): self.generate(size=size)
        with self.assertRaises(ValueError): self.generate(match_mode='invalid')
        self.assertEqual(self.cmds.calls,[])

    def test_non_joint_root_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Choose a joint'):
            self.ns['generate_locator_view']('|rig')
        self.assertEqual(self.cmds.calls,[])

    def test_instanced_joint_is_rejected(self):
        self.cmds.nodes['|rig|root']['instanced'] = True
        with self.assertRaisesRegex(ValueError,'Instanced'): self.generate()
        self.assertEqual(self.cmds.calls,[])

    def test_corrupt_membership_does_not_delete_group(self):
        result = self.generate()
        self.cmds.setAttr(result['group']+'.rtkLocatorViewMembers','{"bad":true}',type='string')
        with self.assertRaises(ValueError): self.ns['delete_locator_view']('|rig|root')
        self.assertTrue(self.cmds.objExists(result['group']))

    def test_locked_view_group_blocks_delete_and_rebuild_before_mutations(self):
        result = self.generate()
        self.cmds.nodes[result['group']]['node_locked'] = True
        count = len(self.cmds.calls)
        with self.assertRaisesRegex(ValueError,'locked'): self.ns['delete_locator_view']('|rig|root')
        with self.assertRaisesRegex(ValueError,'locked'): self.generate()
        self.assertEqual(len(self.cmds.calls),count)

    def test_delete_when_no_view_exists_is_noop(self):
        self.assertEqual(self.ns['delete_locator_view']('|rig|root'),[])
        self.assertEqual(self.cmds.chunks,[])

    def test_duplicate_joint_leaf_names_still_create_distinct_locators(self):
        self.cmds.add_node('|rig|root|branch','joint')
        self.cmds.add_node('|rig|root|branch|tip','joint')
        result = self.generate(include_children=True,match_mode='world_matrix')
        self.assertEqual(len(result['locators']),5)
        self.assertEqual(len(set(result['locators'])),5)


from types import SimpleNamespace


class LifecycleSignal:
    def __init__(self): self.slots=[]
    def connect(self,slot): self.slots.append(slot)
    def disconnect(self,slot):
        if slot in self.slots: self.slots.remove(slot)
    def emit(self):
        for slot in self.slots[:]: slot()


class LifecycleWidget:
    def __init__(self, log, parent=None, native=False):
        self.log=log;self.parent=parent;self.native=native;self.valid=True
        self.children=[];self.deleted_later=0;self.props={};self.blocked=False
        self.on_reparent=None;self.close_calls=0
        if parent is not None: parent.children.append(self)
    def parentWidget(self): return self.parent
    def layout(self): return getattr(self,'widget_layout',None)
    def findChildren(self,kind): return [child for child in self.children if isinstance(child,kind)]
    def blockSignals(self,value): self.blocked=value
    def hide(self): self.log.append(('hide',self))
    def setParent(self,parent):
        self.log.append(('reparent',self,parent))
        if self.parent is not None and self in self.parent.children: self.parent.children.remove(self)
        self.parent=parent
        if parent is not None: parent.children.append(self)
        if self.on_reparent: self.on_reparent()
    def deleteLater(self):
        if self.native: raise AssertionError('Qt must not delete a Maya-owned widget')
        self.deleted_later+=1;self.log.append(('deleteLater',self))
    def objectName(self):
        if not self.valid: raise AssertionError('Invalid wrapper was dereferenced')
        return 'MasterRiggingToolkit'
    def property(self,key): return self.props.get(key)
    def close(self): self.close_calls+=1
    def show(self): pass
    def raise_(self): pass
    def activateWindow(self): pass


class LifecycleStack(LifecycleWidget):
    def __init__(self,log):
        super().__init__(log);self.widget_layout=self
    def removeWidget(self,page): self.log.append(('removeWidget',page))


class LifecycleTimer:
    def __init__(self,log,active=True): self.log=log;self.active=active;self.valid=True
    def stop(self): self.active=False;self.log.append(('stopTimer',self))
    def isActive(self): return self.active


class LifecycleCommands:
    def __init__(self,log,hosts,native_page,parent):
        self.log=log;self.hosts=set(hosts);self.jobs={7,8};self.idle=[]
        self.native_page=native_page;self.parent=parent
    def window(self,win,**kw):
        self.log.append(('windowQuery',win));return win in self.hosts
    def deleteUI(self,win,**kw):
        if self.native_page.parent is not self.parent:
            raise AssertionError('Native UI deleted before its original parent was restored')
        self.log.append(('deleteUI',win));self.hosts.remove(win);self.native_page.valid=False
    def evalDeferred(self,fn,**kw): self.idle.append(fn);self.log.append(('deferNative',))
    def scriptJob(self,**kw):
        if 'exists' in kw: return kw['exists'] in self.jobs
        if 'kill' in kw:
            self.jobs.discard(kw['kill']);self.log.append(('killJob',kw['kill']))
    def warning(self,message): self.log.append(('warning',message))


class LifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree=ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())

    def setUp(self):
        self.log=[];self.qt_queue=[]
        self.app=LifecycleWidget(self.log);self.app.aboutToQuit=LifecycleSignal();self.app.tops=[]
        self.app.topLevelWidgets=lambda:self.app.tops[:]
        self.original_parent=LifecycleWidget(self.log,native=True)
        self.stack=LifecycleStack(self.log)
        self.native=LifecycleWidget(self.log,self.stack,native=True)
        self.qt_page=LifecycleWidget(self.log,self.stack)
        self.cmds=LifecycleCommands(self.log,['host'],self.native,self.original_parent)
        def add_callback(message,fn):
            self.log.append(('addCallback',message));return 99
        om=SimpleNamespace(MSceneMessage=SimpleNamespace(kMayaExiting=30,addCallback=add_callback),
                           MMessage=SimpleNamespace(removeCallback=lambda cb:self.log.append(('removeCallback',cb))))
        qt_timer=type('MockQTimer',(),{'singleShot':staticmethod(lambda delay,fn:self.qt_queue.append(fn))})
        qtwidgets=SimpleNamespace(QApplication=SimpleNamespace(instance=lambda:self.app),QWidget=LifecycleWidget,
                                  QAbstractSpinBox=LifecycleWidget)
        self.ns={'cmds':self.cmds,'om':om,'QtWidgets':qtwidgets,'QtCore':SimpleNamespace(QTimer=qt_timer),
                 'shiboken':SimpleNamespace(isValid=lambda obj:getattr(obj,'valid',False))}
        names={'_qt_object_valid','_install_maya_shutdown_guard','_maya_is_exiting','_defer_maya_host_deletion','show'}
        nodes=[node for node in self.tree.body if isinstance(node,ast.FunctionDef) and node.name in names]
        for owner,wanted in [('EmbeddedUnifiedRiggingToolkit',{'dispose'}),
                             ('MasterRiggingUI',{'_cached_panels','_quiesce_ui','_remove_scene_hooks','_discard_pages',
                                                 '_on_maya_exiting','_finish_close','closeEvent','_queue_scene_reload'})]:
            cls=next(node for node in self.tree.body if isinstance(node,ast.ClassDef) and node.name==owner)
            body=[node for node in cls.body if isinstance(node,ast.FunctionDef) and (node.name in wanted or node.name.startswith("_constraint_"))]
            nodes.append(ast.ClassDef(name=owner,bases=[],keywords=[],body=body,decorator_list=[]))
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<lifecycle helpers>','exec'),self.ns)
        self.embedded=self.ns['EmbeddedUnifiedRiggingToolkit']()
        self.embedded._disposed=False;self.embedded.pages={'controllers':self.native}
        self.embedded.original_parents={'controllers':self.original_parent};self.embedded.hosts={'controllers':'host'}
        self.embedded.BUILDERS={'controllers':'build_controller_tab'}
        self.master=self.ns['MasterRiggingUI']()
        m=self.master
        m.valid=True;m._closed=False;m._cleanup_done=False;m._reset_pending=False
        m._shutdown_state=self.ns['_install_maya_shutdown_guard']()
        m._qt_app=self.app;m._jobs=[7,8];m._save_callback=1;m._exit_callback=2
        self.app.aboutToQuit.connect(m._on_maya_exiting)
        m.unified_tool=self.embedded;m.stack=self.stack;m._pages={'controllers':self.native,'sdk':self.qt_page}
        self.cache_timer=LifecycleTimer(self.log)
        self.other_timer=LifecycleTimer(self.log)
        self.qt_page._cache_timer=self.cache_timer
        self.qt_page.flush_cache=lambda:None
        self.cache_saves=[]
        def save_cache():
            self.assertTrue(m._closed,'Closed guard must be set before cache writes')
            self.cache_saves.append('saved')
        self.qt_page._save_pending_cache=save_cache
        m.findChildren=lambda kind:[self.cache_timer,self.other_timer] if kind is qt_timer else [self.native,self.qt_page]
        m._settings=SimpleNamespace(setValue=lambda key,value:self.log.append(('settings',key)))
        m.saveGeometry=lambda:b'geometry';m._active_key='sdk'
        m.deleted_later=0
        def delete_master():
            self.assertIsNot(self.native.parent,self.stack,'Shell deletion must not own native pages')
            m.deleted_later+=1;self.log.append(('deleteShellLater',))
        m.deleteLater=delete_master
        self.accepts=[];self.event=SimpleNamespace(accept=lambda:self.accepts.append(True))

    def flush_qt(self):
        while self.qt_queue: self.qt_queue.pop(0)()
    def flush_maya(self):
        while self.cmds.idle: self.cmds.idle.pop(0)()

    def test_close_event_does_not_reparent_or_delete_widgets(self):
        self.master.closeEvent(self.event)
        self.assertTrue(self.master._closed)
        self.assertEqual(self.accepts,[True])
        self.assertFalse(any(entry[0] in ('reparent','deleteUI','deleteLater','deleteShellLater') for entry in self.log))
        self.assertEqual(len(self.qt_queue),1)
        self.assertEqual(self.cache_saves,['saved'])
        self.assertFalse(self.cache_timer.active or self.other_timer.active)

    def test_original_native_parent_is_restored_before_idle_deletion(self):
        self.master.closeEvent(self.event);self.flush_qt()
        self.assertIs(self.native.parent,self.original_parent)
        self.assertTrue(self.native.blocked)
        self.assertEqual(self.cmds.hosts,{'host'})
        self.assertEqual(len(self.cmds.idle),1)
        self.assertEqual(self.native.deleted_later,0)
        self.assertEqual(self.qt_page.deleted_later,1)
        self.assertEqual(self.master.deleted_later,1)
        self.flush_maya()
        self.assertEqual(self.cmds.hosts,set())
        self.assertFalse(self.native.valid)

    def test_all_stack_pages_removed_before_native_dispose(self):
        self.master.closeEvent(self.event);self.flush_qt()
        remove_indices=[i for i,item in enumerate(self.log) if item[0]=='removeWidget']
        reparent_index=next(i for i,item in enumerate(self.log) if item[0]=='reparent')
        # Both native and Python pages have been removed from the stack first.
        self.assertEqual({entry[1] for entry in self.log[:reparent_index] if entry[0]=='removeWidget'},
                         {self.native,self.qt_page})
        self.assertGreaterEqual(len(remove_indices),2)

    def test_repeated_close_and_dispose_do_not_schedule_duplicate_deletes(self):
        self.master.closeEvent(self.event);self.master.closeEvent(self.event)
        self.assertEqual(len(self.qt_queue),1)
        self.flush_qt();self.master._finish_close();self.embedded.dispose()
        self.assertEqual(len(self.cmds.idle),1)
        self.assertEqual(self.master.deleted_later,1)

    def test_maya_exit_restores_ownership_without_native_commands_or_cache_writes(self):
        self.log.clear();self.master._on_maya_exiting()
        self.assertTrue(self.master._closed and self.master._cleanup_done)
        self.assertIs(self.native.parent,self.original_parent)
        self.assertEqual(self.cache_saves,[])
        self.assertEqual(self.cmds.idle,[])
        self.assertEqual(self.master.deleted_later,0)
        self.assertFalse(any(item[0] in ('windowQuery','deleteUI','killJob','removeCallback','settings') for item in self.log))

    def test_queued_native_cleanup_is_skipped_after_shutdown_begins(self):
        self.master.closeEvent(self.event);self.flush_qt()
        self.master._shutdown_state['exiting']=True
        self.log.clear();self.flush_maya()
        self.assertEqual(self.log,[])
        self.assertEqual(self.cmds.hosts,{'host'})

    def test_shutdown_between_close_and_qt_cleanup_takes_exit_path(self):
        self.master.closeEvent(self.event)
        self.master._shutdown_state['exiting']=True
        self.log.clear();self.flush_qt()
        self.assertIs(self.native.parent,self.original_parent)
        self.assertEqual(self.master.deleted_later,0)
        self.assertEqual(self.cmds.idle,[])
        self.assertFalse(any(item[0]=='deleteUI' for item in self.log))

    def test_close_during_shutdown_does_not_save_settings_or_cache(self):
        self.master._shutdown_state['exiting']=True
        self.log.clear();self.master.closeEvent(self.event)
        self.assertEqual(self.cache_saves,[])
        self.assertFalse(any(item[0] in ('settings','deleteUI','killJob','removeCallback') for item in self.log))

    def test_invalid_original_parent_keeps_shell_and_native_controls_alive(self):
        self.original_parent.valid=False
        self.master.closeEvent(self.event);self.flush_qt()
        self.assertEqual(self.master.deleted_later,0)
        self.assertEqual(self.cmds.idle,[])
        self.assertIs(self.native.parent,self.stack)
        self.assertFalse(self.embedded._disposed)

    def test_reentrant_scene_callback_during_reparent_cannot_start_reload(self):
        self.master._scene_timer=LifecycleTimer(self.log,active=False)
        self.master._scene_timer.start=lambda *_args:self.fail('Scene reload started during teardown')
        self.native.on_reparent=self.master._queue_scene_reload
        self.master.closeEvent(self.event);self.flush_qt()
        self.assertFalse(self.master._reset_pending)

    def test_cache_save_error_cannot_prevent_scheduled_cleanup(self):
        def fail_cache(): raise RuntimeError('Cache error')
        self.qt_page._save_pending_cache=fail_cache
        self.master.closeEvent(self.event)
        self.assertEqual(len(self.qt_queue),1)
        self.assertEqual(self.accepts,[True])
        self.flush_qt();self.flush_maya()
        self.assertEqual(self.cmds.hosts,set())

    def test_scene_hooks_are_removed_before_widget_cleanup(self):
        self.master.closeEvent(self.event)
        self.assertEqual(self.master._jobs,[])
        self.assertIsNone(self.master._save_callback)
        self.assertFalse(self.cmds.jobs)
        self.flush_qt()
        self.assertIsNone(self.master._exit_callback)
        self.assertNotIn(self.master._on_maya_exiting,self.app.aboutToQuit.slots)

    def test_shutdown_guard_is_reused_across_reloads(self):
        before=len([item for item in self.log if item[0]=='addCallback'])
        self.assertIs(self.ns['_install_maya_shutdown_guard'](),self.master._shutdown_state)
        after=len([item for item in self.log if item[0]=='addCallback'])
        self.assertEqual(before,after)
        self.app.aboutToQuit.emit()
        self.assertTrue(self.ns['_maya_is_exiting']())

    def test_launcher_does_not_call_legacy_window_close(self):
        legacy=LifecycleWidget(self.log);self.app.tops=[legacy]
        self.ns['_master_rig_ui']=legacy
        with self.assertRaisesRegex(RuntimeError,'Restart Maya'):
            self.ns['show']()
        self.assertEqual(legacy.close_calls,0)

    def test_launcher_skips_invalid_wrappers_and_closes_current_window_once(self):
        invalid=LifecycleWidget(self.log);invalid.valid=False
        current=LifecycleWidget(self.log);current.props['rtkLifecycleVersion']='2.4'
        self.app.tops=[invalid,current];self.ns['_master_rig_ui']=current
        self.ns['MasterRiggingUI']=lambda:LifecycleWidget(self.log)
        self.ns['show']()
        self.assertEqual(current.close_calls,1)

    def test_launcher_cannot_create_ui_while_maya_exits(self):
        self.master._shutdown_state['exiting']=True
        with self.assertRaisesRegex(RuntimeError,'shutting down'):
            self.ns['show']()

    def test_focus_loss_cannot_invoke_scene_edit_slots_on_close(self):
        edits=[]
        self.event.accept=lambda:edits.append('late scene edit') if not self.qt_page.blocked else None
        self.master.closeEvent(self.event)
        self.assertEqual(edits,[])
        self.assertTrue(self.qt_page.blocked and self.native.blocked)

    def test_pending_spin_text_is_committed_and_cached_before_signals_are_muted(self):
        editor=LifecycleWidget(self.log,self.qt_page)
        def interpret():
            self.assertFalse(self.qt_page.blocked)
            self.cache_timer.active=True
            self.log.append(('interpretText',))
        editor.interpretText=interpret
        self.cache_timer.active=False
        self.master.closeEvent(self.event)
        self.assertEqual(self.cache_saves,['saved'])
        self.assertTrue(any(item[0]=='interpretText' for item in self.log))


class GuideIKCommands(LocatorViewCommands):
    """Command routing fake: never claims to simulate IK solving."""
    def __init__(self):
        super().__init__()
        self.nodes = {}
        self.inputs = {}
        self.joints = ['|first', '|first|second', '|first|second|third']
        for node, position in zip(self.joints, [(0,0,0),(3,2,0),(8,0,0)]):
            self.add_node(node,'joint',matrix=self.matrix(*position))
            self.nodes[node]['attrs'].update({'rotate':[(0,0,0)],'rotateX':0,'rotateY':0,'rotateZ':0,'ikBlend':.4,'jointOrient':[(0,0,0)],'rotateAxis':[(0,0,0)]})
        self.selection = [self.joints[1]]
        self.fail_stage = None
        self.matrix_rotations = {}

    def createNode(self,kind,name,**kw):
        name=name.lstrip(':')
        return self.add_node('|'+name,kind)

    def ls(self, names=None, **kw):
        if kw.get('type') and names is None:
            return [n for n,s in self.nodes.items() if s['type'] == kw['type']]
        result = super().ls(names,**kw)
        if kw.get('allPaths') and result and self.nodes[result[0]].get('instanced'):
            return result * 2
        return result

    def listRelatives(self,node,**kw):
        node = self.ls(node)[0]
        if kw.get('parent'):
            parent = node.rsplit('|',1)[0]
            return [parent] if parent else []
        result = super().listRelatives(node,**kw)
        if kw.get('shapes'):
            result = [n for n in result if self.nodes[n]['type']=='nurbsCurve']
        return result

    def rename(self,node,label):
        new=node.rsplit('|',1)[0]+'|'+label
        remap={n:new+n[len(node):] for n in self.nodes if n==node or n.startswith(node+'|')}
        self.nodes={remap.get(n,n):data for n,data in self.nodes.items()}
        def plug_name(plug):
            n,attr=plug.rsplit('.',1)
            return remap.get(n,n)+'.'+attr
        self.inputs={plug_name(k):plug_name(v) for k,v in self.inputs.items()}
        self.joints=[remap.get(n,n) for n in self.joints]
        self.selection=[remap.get(n,n) for n in self.selection]
        for data in self.nodes.values():
            if 'joint_list' in data:
                data['joint_list']=[remap.get(n,n) for n in data['joint_list']]
                data['effector']=remap.get(data['effector'],data['effector'])
        return new

    def referenceQuery(self,node,**kw):
        return self.nodes[node].get('referenced',False)

    def getAttr(self,plug,**kw):
        node,attr = plug.rsplit('.',1)
        if kw.get('lock'):
            return attr in self.nodes[node].get('locked_attrs',set())
        return super().getAttr(plug,**kw)

    def setAttr(self,plug,*values,**kw):
        node,attr = plug.rsplit('.',1)
        if attr == 'rotate' and values:
            self.nodes[node]['attrs'][attr]=[tuple(values)]
            self.calls.append(('setAttr',plug,values,kw))
            return
        super().setAttr(plug,*values,**kw)
        if 'lock' in kw:
            locks = self.nodes[node].setdefault('locked_attrs',set())
            if kw['lock']: locks.add(attr)
            else: locks.discard(attr)

    def group(self,empty,name,parent=None):
        node = super().group(empty,name)
        return self.parent(node,parent)[0] if parent else node

    def parent(self,node,group,**kw):
        if self.fail_stage == 'parent' and any(n.startswith(node+'|') and data['type']=='nurbsCurve' for n,data in self.nodes.items()):
            raise RuntimeError('Parent failed')
        return super().parent(node,group)

    def _curve(self,name):
        node=self.add_node('|'+name.lstrip(':').replace('#',str(self.serial+1)),'transform')
        self.add_node(node+'|shape','nurbsCurve')
        return node

    def circle(self,**kw):
        self.calls.append(('circle',kw))
        return [self._curve(kw['name'])]

    def curve(self,**kw):
        self.calls.append(('curve',kw))
        return self._curve(kw['name'])

    def matchTransform(self,node,target,**kw):
        self.nodes[node]['matrix'] = self.nodes[target]['matrix'][:]
        self.calls.append(('matchTransform',node,target,kw))

    def xform(self,node,**kw):
        if kw.get('query'):
            if kw.get('matrix') or kw.get('rotation'):
                self.calls.append(('xformRead',node,kw))
            if kw.get('rotation'):
                return list(self.nodes[node].get('world_rotation',self.nodes[node]['attrs'].get('rotate',[(0,0,0)])[0]))
            matrix=self.nodes[node]['matrix'][:]
            if kw.get('matrix'):
                self.matrix_rotations[tuple(matrix)]=list(self.nodes[node].get('world_rotation',self.nodes[node]['attrs'].get('rotate',[(0,0,0)])[0]))
            return matrix[12:15] if kw.get('translation') else matrix
        if 'matrix' in kw and node.rsplit('|',1)[-1].startswith('rtkKeepIKPose_'):
            self.nodes[node]['world_rotation']=self.matrix_rotations[tuple(kw['matrix'])]
        if 'rotation' in kw:
            if self.fail_stage=='keep': raise RuntimeError('Rotation apply failed')
            self.nodes[node]['attrs']['rotate']=[tuple(kw['rotation'])]
            self.nodes[node]['world_rotation']=list(kw['rotation'])
            self.calls.append(('xformRotation',node,kw))
            return
        if 'translation' in kw:
            self.nodes[node]['matrix'][12:15] = kw['translation']
        else: super().xform(node,**kw)

    def ikHandle(self,*args,**kw):
        if kw.get('query'):
            data=self.nodes[self.ls(args[0])[0]]
            return data['joint_list'][:] if kw.get('jointList') else data['effector']
        handle=self.add_node('|'+kw['name'].lstrip(':').replace('#',str(self.serial+1)),'ikHandle')
        effector=self.add_node(self.joints[1]+'|effector'+str(self.serial+1),'ikEffector')
        self.nodes[handle].update({'joint_list':self.joints[:2],'effector':effector})
        self.calls.append(('ikHandle',kw))
        return handle,effector

    def poleVectorConstraint(self,source,target,**kw):
        if self.fail_stage == 'pole': raise RuntimeError('Pole failed')
        node=self.add_node(target+'|poleConstraint'+str(self.serial+1),'poleVectorConstraint')
        self.calls.append(('poleVectorConstraint',source,target))
        return [node]

    def orientConstraint(self,source,target,**kw):
        if kw.get('name','').startswith(':rtkKeepIKPoseConstraint_'):
            if self.fail_stage=='keep': raise RuntimeError('Rotation solve failed')
            self.nodes[target]['attrs']['rotate']=[tuple(self.nodes[source]['world_rotation'])]
            self.nodes[target]['world_rotation']=list(self.nodes[source]['world_rotation'])
            self.calls.append(('keepOrientation',target))
        if self.fail_stage == 'orient': raise RuntimeError('Orient failed')
        node=self.add_node(target+'|orientConstraint'+str(self.serial+1),'orientConstraint')
        self.inputs[target+'.rotate']=node+'.constraintRotate'
        self.calls.append(('orientConstraint',source,target,kw))
        return [node]

    def listConnections(self,plug,**kw):
        result=super().listConnections(plug,**kw)
        return result if kw.get('plugs') else [p.rsplit('.',1)[0] for p in result]


class GuideIKTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree=ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())

    def setUp(self):
        import math
        self.cmds=GuideIKCommands()
        wanted={'calculate_guide_ik_pole','find_guide_ik_systems','plan_guide_ik','build_guide_ik','remove_guide_ik','_guide_ik_current_world_pose','_guide_ik_keep_world_pose',
                '_begin_tool_undo','_end_tool_undo','_tool_action','_non_undoable_cache_write',
                '_resolve_hierarchy_root','_restore_locator_view_selection'}
        nodes=[n for n in self.tree.body if isinstance(n,ast.FunctionDef) and ((n.name in wanted or n.name.startswith("_constraint_")) or n.name.startswith('_guide_ik_') or n.name=='_check_guide_ik_removal')]
        constants=[n for n in self.tree.body if isinstance(n,ast.Assign) and any(getattr(t,'id','').startswith('_IK_GUIDE_') for t in n.targets)]
        self.ns={'cmds':self.cmds,'math':math,'json':json,'uuid':__import__('uuid'),'wraps':wraps,
                 'contextmanager':contextlib.contextmanager,'_TOOL_UNDO_DEPTH':0}
        exec(compile(ast.Module(body=constants+nodes,type_ignores=[]),'<guide IK>','exec'),self.ns)

    def build(self,**kw): return self.ns['build_guide_ik'](*self.cmds.joints,**kw)
    def remove(self): return self.ns['remove_guide_ik'](self.cmds.joints[0])

    def test_projection_and_outward_pole_on_asymmetric_chain(self):
        result=self.ns['calculate_guide_ik_pole']((0,0,0),(3,2,0),(8,0,0),2)
        self.assertEqual(result['projection'],(3,0,0))
        self.assertEqual(result['position'][0],3)
        self.assertAlmostEqual(result['position'][1],2+2*result['chain_length'])

    def test_projection_handles_arbitrary_3d_world_direction(self):
        result=self.ns['calculate_guide_ik_pole']((1,2,3),(3,5,5),(5,2,7))
        a,b,c=(1,2,3),(3,5,5),(5,2,7)
        direction=tuple(result['position'][i]-b[i] for i in range(3))
        ac=tuple(c[i]-a[i] for i in range(3))
        self.assertAlmostEqual(sum(x*y for x,y in zip(direction,ac)),0)
        self.assertGreater(direction[1],0)

    def test_straight_overlapping_and_invalid_geometry_rejected(self):
        for points in [((0,0,0),(2,0,0),(5,0,0)),((0,0,0),(0,0,0),(5,1,0)),
                       ((0,0,0),(1,2,0),(0,0,0)),((0,0,0),(float('nan'),2,0),(5,1,0))]:
            with self.subTest(points=points),self.assertRaises(ValueError):
                self.ns['calculate_guide_ik_pole'](*points)
        self.assertFalse(self.cmds.calls)

    def test_wrong_order_duplicate_and_disconnected_joints_rejected(self):
        for order in [(0,2,1),(0,1,1)]:
            with self.assertRaises(ValueError): self.ns['plan_guide_ik'](*(self.cmds.joints[i] for i in order))
        self.assertFalse(self.cmds.calls)

    def test_locked_driven_referenced_and_instanced_joints_rejected(self):
        middle=self.cmds.joints[1]
        for key,value in [('locked_attrs',{'rotateY'}),('referenced',True),('instanced',True),('node_locked',True)]:
            self.cmds.nodes[middle][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError): self.build()
            del self.cmds.nodes[middle][key]
        self.cmds.inputs[middle+'.rotate']='animation.output'
        with self.assertRaises(ValueError): self.build()
        self.assertFalse(self.cmds.calls)

    def test_invalid_sizes_and_pole_distances_fail_before_mutation(self):
        for kw in [{'control_size':0},{'control_size':float('inf')},{'pole_distance':0},{'pole_distance':float('nan')}]:
            with self.subTest(kw=kw),self.assertRaises(ValueError): self.build(**kw)
        self.assertFalse(self.cmds.calls)

    def test_build_explicit_rp_solver_controls_and_constraints(self):
        result=self.build(control_size=2,pole_distance=.5)
        handle_call=next(c for c in self.cmds.calls if c[0]=='ikHandle')
        self.assertEqual(handle_call[1]['solver'],'ikRPsolver')
        self.assertEqual(handle_call[1]['startJoint'],self.cmds.joints[0])
        self.assertEqual(handle_call[1]['endEffector'],self.cmds.joints[2])
        self.assertTrue(result['handle'].startswith(result['end_controller']+'|'))
        self.assertEqual(self.cmds.nodes[result['handle']]['attrs']['visibility'],False)
        self.assertEqual(next(c for c in self.cmds.calls if c[0]=='poleVectorConstraint')[1:3],(result['pole_controller'],result['handle']))
        self.assertTrue(next(c for c in self.cmds.calls if c[0]=='orientConstraint')[3]['maintainOffset'])
        self.assertEqual(self.cmds.chunks,['open','close'])
        self.assertEqual(self.cmds.selection,[self.cmds.joints[1]])

    def test_repeat_build_is_blocked_and_first_root_scopes_remove(self):
        self.build()
        before=set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'already exists'): self.build()
        self.assertEqual(set(self.cmds.nodes),before)
        self.assertEqual(self.ns['remove_guide_ik'](self.cmds.joints[1]),[])
        self.assertEqual(set(self.cmds.nodes),before)

    def test_remove_deletes_external_effector_and_constraint_keeps_current_pose(self):
        baseline=set(self.cmds.nodes)
        self.cmds.setAttr(self.cmds.joints[0]+'.rotate',10,20,30)
        self.build()
        self.cmds.setAttr(self.cmds.joints[0]+'.rotate',50,60,70)
        self.cmds.setAttr(self.cmds.joints[0]+'.ikBlend',1)
        self.remove()
        self.assertEqual(set(self.cmds.nodes),baseline)
        self.assertEqual(self.cmds.getAttr(self.cmds.joints[0]+'.rotate'),[(50,60,70)])
        self.assertEqual(self.cmds.getAttr(self.cmds.joints[0]+'.ikBlend'),1)
        self.assertEqual(self.cmds.chunks,['open','close','open','close'])
        self.assertEqual(self.cmds.selection,[self.cmds.joints[1]])

    def test_failed_build_removes_loose_nodes_and_preserves_originals(self):
        for stage in ('parent','pole','orient'):
            with self.subTest(stage=stage):
                self.setUp()
                baseline=set(self.cmds.nodes)
                self.cmds.fail_stage=stage
                with self.assertRaises(RuntimeError): self.build()
                self.assertEqual(set(self.cmds.nodes),baseline)
                self.assertEqual(self.cmds.chunks,['open','close'])
                self.assertEqual(self.cmds.selection,[self.cmds.joints[1]])

    def test_unrelated_descendants_prevent_entire_removal(self):
        result=self.build()
        external=self.cmds.add_node(result['group']+'|userObject','transform')
        before=set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'unrelated'): self.remove()
        self.assertEqual(set(self.cmds.nodes),before)
        self.assertIn(external,self.cmds.nodes)

    def test_external_joint_driver_prevents_pose_overwrite_and_delete(self):
        self.build()
        driver=self.cmds.add_node('|newDriver','animCurve')
        self.cmds.inputs[self.cmds.joints[0]+'.rotateX']=driver+'.output'
        before=set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'external driver'): self.remove()
        self.assertEqual(set(self.cmds.nodes),before)

    def test_locked_member_and_corrupt_metadata_prevent_delete(self):
        result=self.build()
        self.cmds.nodes[result['pole_controller']]['node_locked']=True
        with self.assertRaisesRegex(ValueError,'locked'): self.remove()
        self.cmds.nodes[result['pole_controller']]['node_locked']=False
        self.cmds.nodes[result['group']]['attrs']['rtkGuideIKState']='broken'
        with self.assertRaisesRegex(ValueError,'validate'): self.remove()
        self.assertTrue(self.cmds.objExists(result['group']))

    def test_existing_ik_overlap_is_rejected(self):
        self.cmds.ikHandle(name='existing',startJoint=self.cmds.joints[0],endEffector=self.cmds.joints[2])
        before=set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'existing IK handle'): self.build()
        self.assertEqual(set(self.cmds.nodes),before)

    def test_missing_generated_member_does_not_delete_other_objects(self):
        result=self.build()
        self.cmds.delete(result['pole_controller'])
        unrelated=self.cmds.add_node('|keep','transform')
        self.remove()
        self.assertEqual(set(self.cmds.nodes),set(self.cmds.joints+[unrelated]))

    def test_renaming_root_and_group_preserves_scoped_removal(self):
        result=self.build()
        self.cmds.rename(result['group'],'renamedGroup')
        self.cmds.rename(self.cmds.joints[0],'renamedRoot')
        self.remove()
        self.assertEqual(set(self.cmds.nodes),set(self.cmds.joints))

    def test_foreign_child_beneath_external_effector_blocks_removal(self):
        self.build()
        effector=self.cmds.ls(type='ikEffector')[0]
        self.cmds.add_node(effector+'|keep','transform')
        baseline=set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'unrelated'): self.remove()
        self.assertEqual(set(self.cmds.nodes),baseline)

    def test_removal_deletes_handle_before_its_effector(self):
        self.build()
        handle=self.cmds.ls(type='ikHandle')[0]
        effector=self.cmds.ls(type='ikEffector')[0]
        self.remove()
        deleted=[n for call in self.cmds.calls if call[0]=='delete' for n in call[1]]
        self.assertLess(deleted.index(handle),deleted.index(effector))

    def test_current_pose_is_sampled_before_deletion_and_restored_root_to_tip(self):
        self.build()
        for joint,angle in zip(self.cmds.joints,(30,50,70)):
            self.cmds.nodes[joint]['world_rotation']=[0,angle,0]
        start=len(self.cmds.calls)
        self.remove()
        calls=self.cmds.calls[start:]
        first_delete=next(i for i,c in enumerate(calls) if c[0]=='delete')
        sampled={c[1] for c in calls[:first_delete] if c[0]=='xformRead' and c[2].get('rotation')}
        self.assertEqual(sampled,set(self.cmds.joints))
        restored=[c[1] for c in calls if c[0]=='keepOrientation']
        self.assertEqual(restored,self.cmds.joints)
        self.assertEqual([self.cmds.getAttr(j+'.rotate')[0] for j in self.cmds.joints],[(0,30,0),(0,50,0),(0,70,0)])

    def test_locked_translation_and_scale_do_not_block_pose_preserving_remove(self):
        self.build()
        for joint in self.cmds.joints:
            self.cmds.nodes[joint]['locked_attrs']={'translateX','translateY','translateZ','scaleX','scaleY','scaleZ'}
            self.cmds.nodes[joint]['attrs']['jointOrient']=[(10,20,30)]
        self.remove()
        for joint in self.cmds.joints:
            self.assertEqual(self.cmds.getAttr(joint+'.jointOrient'),[(10,20,30)])
            self.assertEqual(self.cmds.nodes[joint]['locked_attrs'],{'translateX','translateY','translateZ','scaleX','scaleY','scaleZ'})

    def test_pose_apply_failure_undoes_only_the_remove_chunk(self):
        import copy
        original=self.cmds.undoInfo
        checkpoint={}
        def undo_info(**kw):
            if kw.get('query') and kw.get('undoName'): return checkpoint.get('name')
            if kw.get('openChunk') and kw.get('chunkName','').startswith('RemoveGuideIK_'):
                checkpoint.update({'name':kw['chunkName'],'nodes':copy.deepcopy(self.cmds.nodes),'inputs':copy.deepcopy(self.cmds.inputs)})
            return original(**kw)
        undos=[]
        def undo():
            self.cmds.nodes=copy.deepcopy(checkpoint['nodes'])
            self.cmds.inputs=copy.deepcopy(checkpoint['inputs'])
            undos.append(checkpoint['name'])
        self.cmds.undoInfo=undo_info
        self.cmds.undo=undo
        self.build()
        before=copy.deepcopy(self.cmds.nodes)
        self.cmds.fail_stage='keep'
        with self.assertRaisesRegex(RuntimeError,'rolled back'): self.remove()
        self.assertEqual(self.cmds.nodes,before)
        self.assertEqual(len(undos),1)
        self.assertTrue(undos[0].startswith('RemoveGuideIK_'))
        self.assertEqual(self.cmds.selection,[self.cmds.joints[1]])

    def test_removal_with_no_system_is_noop(self):
        self.assertEqual(self.remove(),[])
        self.assertFalse(self.cmds.calls)
        self.assertFalse(self.cmds.chunks)


class PoseDriverCommands(GuideIKCommands):
    def listAttr(self, node, **kw):
        return sorted(self.nodes[node].get('keyable_attrs',set())) if kw.get('keyable') else list(self.nodes[node]['attrs'])

    def attributeQuery(self, attribute, node, **kw):
        if kw.get('listParent'):
            return [attribute[:-1]] if attribute[:-1] in ('translate','rotate','scale') and attribute[-1:] in 'XYZ' else []
        return super().attributeQuery(attribute,node,**kw)

    def disconnectAttr(self, driver, driven):
        if self.inputs.get(driven) == driver:
            self.inputs.pop(driven)

    def currentUnit(self, **kw):
        if kw.get('linear'):
            return getattr(self,'linear_unit','cm')
        return getattr(self, "angle_unit", "deg")

    def __init__(self):
        super().__init__()
        self.fail_connection = None

    def listRelatives(self,node,**kw):
        if kw.get('shapes'):
            return [n for n in self.nodes if n.rsplit('|',1)[0]==node and self.nodes[n]['type'] in ('locator','nurbsCurve')]
        return super().listRelatives(node,**kw)

    def createNode(self, kind, name, **kw):
        name=name.lstrip(':').replace('#',str(self.serial+1))
        self.calls.append(('createNode',kind,name))
        return self.add_node(name,kind)

    def objectType(self,node,**kw):
        kind=self.nodes[node]['type']
        if kw.get('isAType')=='dagNode':
            return kind in ('joint','transform','locator','nurbsCurve','parentConstraint','orientConstraint','ikHandle','ikEffector')
        return super().objectType(node,**kw)

    def ls(self,names=None,**kw):
        if kw.get('objectsOnly') and names and names.startswith('*.'):
            attr=names[2:]
            return [n for n,d in self.nodes.items() if attr in d['attrs']]
        if names is None and not kw.get('selection') and not kw.get('type'):
            return list(self.nodes)
        return super().ls(names,**kw)

    def getAttr(self,plug,**kw):
        node,attr=plug.split('.',1)
        if kw.get('type'):
            fallback = 'doubleAngle' if attr.startswith('rotate') and attr[-1:] in 'XYZ' else 'doubleLinear' if attr.startswith('translate') and attr[-1:] in 'XYZ' else 'double'
            return self.nodes[node].get('attr_types',{}).get(attr,fallback)
        if kw.get('settable'):
            return attr not in self.nodes[node].get('locked_attrs',set()) and plug not in self.inputs
        if kw.get('lock'):
            return attr in self.nodes[node].get('locked_attrs',set())
        if kw.get('keyable'):
            return attr in self.nodes[node].get('keyable_attrs',set())
        if kw.get('channelBox'):
            return attr in self.nodes[node].get('channel_box_attrs',set())
        return self.nodes[node]['attrs'].get(attr,0)

    def setAttr(self,plug,*values,**kw):
        node,attr=plug.split('.',1)
        if values:
            self.nodes[node]['attrs'][attr]=values[0] if len(values)==1 else tuple(values)
            if attr in ('translate','rotate','scale','input1','input2') and len(values)==3:
                for axis,value in zip('XYZ',values):
                    self.nodes[node]['attrs'][attr+axis]=value
        if 'lock' in kw:
            locks=self.nodes[node].setdefault('locked_attrs',set())
            if kw['lock']: locks.add(attr)
            else: locks.discard(attr)
        for flag,key in [('keyable','keyable_attrs'),('channelBox','channel_box_attrs')]:
            if flag in kw:
                attributes = self.nodes[node].setdefault(key,set())
                if kw[flag]: attributes.add(attr)
                else: attributes.discard(attr)
        self.calls.append(('setAttr',plug,values,kw))

    def connectAttr(self,driver,driven):
        if self.fail_connection and self.fail_connection in driven:
            raise RuntimeError('Connection failed')
        super().connectAttr(driver,driven)

    def addAttr(self,node,longName,**kw):
        super().addAttr(node,longName,**kw)
        if kw.get('dataType')!='string':
            self.nodes[node]['attrs'][longName]=kw.get('defaultValue',0)
        if kw.get('keyable'):
            self.nodes[node].setdefault('keyable_attrs',set()).add(longName)

    def deleteAttr(self,plug):
        node,attr=plug.rsplit('.',1)
        del self.nodes[node]['attrs'][attr]
        self.nodes[node].get('locked_attrs',set()).discard(attr)
        self.nodes[node].get('keyable_attrs',set()).discard(attr)
        self.nodes[node].get('channel_box_attrs',set()).discard(attr)
        self.inputs={p:d for p,d in self.inputs.items() if p!=plug and d!=plug}
        self.calls.append(('deleteAttr',plug))

    def matchTransform(self,node,target,**kw):
        super().matchTransform(node,target,**kw)
        self.nodes[node]['world_position']=tuple(self.xform(target,query=True,worldSpace=True,translation=True))

    def xform(self,node,**kw):
        if kw.get('query') and kw.get('translation'):
            if 'world_position' in self.nodes[node]:
                return list(self.nodes[node]['world_position'])
            if self.nodes[node]['type']=='joint':
                return self.nodes[node]['matrix'][12:15]
            parent=node.rsplit('|',1)[0]
            pos=self.xform(parent,query=True,translation=True) if parent in self.nodes else [0,0,0]
            return [pos[i]+self.nodes[node]['attrs'].get('translate'+axis,0) for i,axis in enumerate('XYZ')]
        if not kw.get('query') and 'translation' in kw:
            self.nodes[node]['world_position']=tuple(kw['translation'])
            self.calls.append(('xform',node,kw))
            return
        return super().xform(node,**kw)


class PoseDriverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree=ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())

    def setUp(self):
        import math, uuid
        self.cmds=PoseDriverCommands()
        wanted={'_begin_tool_undo','_end_tool_undo','_tool_action','_non_undoable_cache_write',
                '_guide_ik_uuid','_guide_ik_resolve_uuid','_guide_ik_joint','_guide_ik_delete_owned',
                '_resolve_hierarchy_root','_restore_locator_view_selection','pose_driver_weights',
                'find_pose_drivers','list_pose_drivers','build_pose_driver','add_pose_driver_pose',
                'set_pose_driver_controller','cache_pose_driver_controller_pose','goto_pose_driver_pose',
                'update_pose_driver_pose','remove_pose_driver_pose','set_pose_driver_normalize','remove_pose_driver','pose_driver_unit_center','plan_pose_driver_mirror','mirror_pose_driver','set_pose_driver_default_rotation','plan_pose_driver_rotation','capture_pose_driver_rotation','expose_pose_driver_joint_weights','set_pose_driver_falloff','unlock_pose_driver_weights','repair_pose_driver_division'}
        nodes=[n for n in self.tree.body if (isinstance(n,ast.FunctionDef) and ((n.name in wanted or n.name.startswith("_constraint_")) or n.name.startswith('_pd_')))
               or (isinstance(n,ast.ClassDef) and n.name=='_PoseDriverBuilder')]
        constants=[n for n in self.tree.body if isinstance(n,ast.Assign) and any(getattr(t,'id','').startswith('_POSE_DRIVER_') for t in n.targets)]
        self.ns={'cmds':self.cmds,'math':math,'json':json,'uuid':uuid,'wraps':wraps,'contextmanager':contextlib.contextmanager,'_TOOL_UNDO_DEPTH':0}
        exec(compile(ast.Module(body=constants+nodes,type_ignores=[]),'<PoseDriver helpers>','exec'),self.ns)
        self.joint=self.cmds.joints[1]

    def build(self,**kw):
        self.result=self.ns['build_pose_driver'](self.joint,**kw)
        return self.result

    def capture(self,name='armUp',**kw):
        # Historical graph/cleanup cases intentionally capture a manual rest cone.
        # Automatic capture defaults are exercised separately below.
        kw.setdefault('radius',45)
        return self.ns['add_pose_driver_pose'](self.result['group'],name,**kw)

    def read(self): return self.ns['_pd_read'](self.result['group'])[1]

    def test_center_edge_outside_and_smooth_falloff(self):
        import math
        evaluate=self.ns['pose_driver_weights']
        target=[{'direction':(1,0,0),'radius':60}]
        self.assertEqual(evaluate((1,0,0),target)['weights'],[1])
        self.assertAlmostEqual(evaluate((.5,math.sqrt(.75),0),target)['weights'][0],0)
        self.assertEqual(evaluate((0,1,0),target)['weights'],[0])
        # Dot .75 is exactly halfway between cosine60=.5 and center cosine1.
        self.assertAlmostEqual(evaluate((.75,math.sqrt(1-.75**2),0),target,falloff='smooth')['weights'][0],.5)

    def test_partial_full_and_zero_sum_normalization(self):
        evaluate=self.ns['pose_driver_weights']
        targets=[{'direction':(1,0,0),'radius':45}]*2
        self.assertEqual(evaluate((1,0,0),targets,0)['weights'],[1,1])
        self.assertEqual(evaluate((1,0,0),targets,.5)['weights'],[.75,.75])
        self.assertEqual(evaluate((1,0,0),targets,1)['weights'],[.5,.5])
        self.assertEqual(evaluate((-1,0,0),targets,1)['weights'],[0,0])

    def test_direction_length_and_x_axis_twist_do_not_affect_weights(self):
        targets=[{'direction':(10,0,0),'radius':35}]
        self.assertEqual(self.ns['pose_driver_weights']((.01,0,0),targets)['weights'],[1])
        # Swing direction only: rotation around X leaves the X direction identical.
        self.assertEqual(self.ns['pose_driver_weights']((1,0,0),targets)['weights'],[1])

    def test_zero_vectors_are_safe_and_invalid_settings_rejected(self):
        target=[{'direction':(1,0,0),'radius':45}]
        self.assertEqual(self.ns['pose_driver_weights']((0,0,0),target,1)['weights'],[0])
        self.assertEqual(self.ns['pose_driver_weights']((1,0,0),[{'direction':(0,0,0),'radius':120}],1)['weights'],[0])
        for radius in (0,180.1,float('nan')):
            with self.assertRaises(ValueError): self.ns['_pd_radius'](radius)
        for amount in (-.1,1.1,float('nan')):
            with self.assertRaises(ValueError): self.ns['pose_driver_weights']((1,0,0),target,amount)

    def test_minus_axis_and_parent_constraint_offset(self):
        result=self.build(axis=-1)
        self.assertEqual(self.cmds.getAttr(result['cone']+'.translateX'),-1)
        call=next(c for c in self.cmds.calls if c[0]=='parentConstraint')
        self.assertEqual(call[1],self.cmds.joints[0])
        self.assertEqual(call[2],result['frame'])
        self.assertTrue(call[3]['maintainOffset'])
        orient=next(c for c in self.cmds.calls if c[0]=='orientConstraint')
        self.assertEqual(orient[1],self.joint)
        self.assertFalse(orient[3]['maintainOffset'])

    def test_build_and_remove_preserve_source_joints_selection_and_single_chunks(self):
        original={n:json.loads(json.dumps(d)) for n,d in self.cmds.nodes.items()}
        selected=self.cmds.selection[:]
        self.build()
        self.assertEqual(self.cmds.selection,selected)
        self.ns['remove_pose_driver'](self.result['group'])
        self.assertEqual(set(self.cmds.nodes),set(original))
        for n,d in original.items(): self.assertEqual(json.loads(json.dumps(self.cmds.nodes[n])),d)
        self.assertEqual(self.cmds.selection,selected)
        self.assertEqual(self.cmds.chunks,['open','close','open','close'])

    def test_root_joint_uses_static_start_frame(self):
        result=self.ns['build_pose_driver'](self.cmds.joints[0])
        self.assertFalse([c for c in self.cmds.calls if c[0]=='parentConstraint'])
        self.assertTrue(result['frame'])

    def test_repeated_start_capture_and_invalid_axis_are_blocked(self):
        self.build()
        before=set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'already has'): self.build()
        self.assertEqual(set(self.cmds.nodes),before)
        with self.assertRaises(ValueError): self.ns['build_pose_driver'](self.cmds.joints[0],axis=0)

    def test_target_outputs_graph_uses_raw_sum_and_normalize_blend(self):
        self.build()
        record=self.capture()
        state=self.read()
        cone=self.result['cone']
        self.assertTrue(self.cmds.attributeQuery('armUpWeight',node=cone,exists=True))
        self.assertFalse(self.cmds.getAttr(cone+'.armUpWeight',lock=True))
        self.assertTrue(self.cmds.attributeQuery('armUpWeightRaw',node=cone,exists=True))
        output=self.cmds.inputs[cone+'.armUpWeight'].rsplit('.',1)[0]
        self.assertEqual(self.cmds.nodeType(output),'blendColors')
        self.assertEqual(self.cmds.inputs[output+'.blender'],cone+'.normalize')
        normalize_node=self.cmds.inputs[output+'.color1R'].rsplit('.',1)[0]
        denominator=self.ns['_pd_node'](state['normalization_divisor'])
        self.assertEqual(self.cmds.inputs[normalize_node+'.input2X'],denominator+'.outputR')
        total=self.ns['_pd_node'](state['sum'])
        self.assertEqual(self.cmds.inputs[total+'.input1D[1]'],self.cmds.inputs[output+'.color2R'])
        self.assertEqual(record['index'],1)
        self.assertEqual(set(record['nodes']) & set(self.cmds.ls(joint,uuid=True)[0] for joint in self.cmds.joints),set())

    def test_network_has_no_expressions_or_distance_angle_unit_dependence(self):
        self.build()
        record=self.capture()
        kinds={self.cmds.nodeType(self.ns['_pd_node'](i)) for i in self.read()['members']}
        self.assertFalse(kinds & {'expression','distanceBetween'})
        self.assertIn('angleBetween',kinds)
        self.assertIn('multMatrix',kinds)
        self.assertIn('vectorProduct',kinds)
        self.assertIn('remapValue',kinds)
        ramp=self.ns['_pd_node'](record['ramp'])
        self.assertEqual(self.cmds.getAttr(ramp+'.value[0].value_Interp'),2)

    def test_capture_copies_external_center_without_owning_it(self):
        self.build()
        center=self.cmds.add_node('|externalCenter','transform')
        self.cmds.xform(center,translation=(4,5,6))
        record=self.capture(center=center)
        target=self.ns['_pd_node'](record['center'])
        import math
        position=self.cmds.xform(target,query=True,translation=True)
        for actual,expected in zip(position,(3+1/math.sqrt(46),2+3/math.sqrt(46),6/math.sqrt(46))):
            self.assertAlmostEqual(actual,expected)
        self.assertEqual(record['target_object'],self.ns['_pd_uuid'](center))
        self.assertNotIn(self.ns['_pd_uuid'](center),self.read()['members'])
        self.ns['remove_pose_driver'](self.result['group'])
        self.assertTrue(self.cmds.objExists(center))

    def test_recapture_preserves_existing_output_and_downstream_connection(self):
        self.build()
        record=self.capture()
        cone=self.result['cone']
        consumer=self.cmds.add_node('|consumer','transform')
        self.cmds.connectAttr(cone+'.armUpWeight',consumer+'.translateX')
        before=set(self.cmds.nodes)
        plug_source=self.cmds.inputs[cone+'.armUpWeight']
        self.cmds.nodes[self.joint]['matrix'][:3]=[0,0,-1]
        self.ns['update_pose_driver_pose'](self.result['group'],record['id'],radius=80,recapture=True)
        self.assertEqual(set(self.cmds.nodes),before)
        self.assertEqual(self.cmds.inputs[cone+'.armUpWeight'],plug_source)
        self.assertEqual(self.cmds.inputs[consumer+'.translateX'],cone+'.armUpWeight')
        self.assertEqual(self.read()['poses'][0]['radius'],80)
        self.assertEqual(self.cmds.xform(self.ns['_pd_node'](record['center']),query=True,translation=True),[3,2,-1])

    def test_duplicate_sanitized_names_and_invalid_centers_preserve_scene(self):
        self.build()
        self.capture(name='arm up')
        before=set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'already exists'): self.capture(name='arm-up')
        center=self.cmds.add_node('|zeroCenter','transform')
        frame_position=self.cmds.xform(self.result['frame'],query=True,translation=True)
        self.cmds.xform(center,translation=frame_position)
        with self.assertRaisesRegex(ValueError,'away'): self.capture(name='other',center=center)
        self.assertEqual(set(self.cmds.nodes),before|{center})

    def test_failed_add_removes_nodes_attributes_and_sum_ghost(self):
        self.build()
        before=set(self.cmds.nodes)
        self.cmds.fail_connection='.brokenWeightRaw'
        with self.assertRaises(RuntimeError): self.capture(name='broken')
        self.assertEqual(set(self.cmds.nodes),before)
        state=self.read()
        self.assertEqual(state['poses'],[])
        self.assertFalse(self.cmds.attributeQuery('brokenWeight',node=self.result['cone'],exists=True))
        total=self.ns['_pd_node'](state['sum'])
        self.assertEqual(self.cmds.getAttr(total+'.input1D[1]'),0)
        self.assertNotIn(total+'.input1D[1]',self.cmds.inputs)

    def test_failed_start_creation_removes_partial_scene(self):
        baseline=set(self.cmds.nodes)
        self.cmds.fail_connection='.matrixIn[0]'
        with self.assertRaises(RuntimeError): self.build()
        self.assertEqual(set(self.cmds.nodes),baseline)
        self.assertEqual(self.cmds.chunks,['open','close'])

    def test_pose_removal_keeps_other_outputs_and_sum_indices_stable(self):
        self.build()
        first=self.capture(name='firstPose')
        second=self.capture(name='secondPose')
        cone=self.result['cone']
        plug_source=self.cmds.inputs[cone+'.secondPoseWeight']
        self.ns['remove_pose_driver_pose'](self.result['group'],first['id'])
        self.assertEqual(self.cmds.inputs[cone+'.secondPoseWeight'],plug_source)
        self.assertEqual(self.read()['poses'][0]['index'],second['index'])
        self.assertFalse(self.cmds.attributeQuery('firstPoseWeight',node=cone,exists=True))
        third=self.capture(name='thirdPose')
        self.assertEqual(third['index'],3)

    def test_external_weight_consumers_block_pose_and_system_removal(self):
        self.build()
        record=self.capture()
        consumer=self.cmds.add_node('|consumer','transform')
        self.cmds.connectAttr(self.result['cone']+'.armUpWeight',consumer+'.translateX')
        before=set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'Disconnect'): self.ns['remove_pose_driver_pose'](self.result['group'],record['id'])
        with self.assertRaisesRegex(ValueError,'Disconnect'): self.ns['remove_pose_driver'](self.result['group'])
        self.assertEqual(set(self.cmds.nodes),before)

    def test_foreign_descendants_and_locked_members_block_deletion(self):
        self.build()
        unrelated=self.cmds.add_node(self.result['frame']+'|keep','transform')
        with self.assertRaisesRegex(ValueError,'unrelated'): self.ns['remove_pose_driver'](self.result['group'])
        self.cmds.delete(unrelated)
        self.cmds.nodes[self.result['cone']]['node_locked']=True
        with self.assertRaisesRegex(ValueError,'locked'): self.ns['remove_pose_driver'](self.result['group'])

    def test_missing_owned_node_allows_system_cleanup(self):
        self.build()
        self.capture()
        node=self.ns['_pd_node'](self.read()['live'])
        self.cmds.delete(node)
        self.ns['remove_pose_driver'](self.result['group'])
        self.assertEqual(set(self.cmds.nodes),set(self.cmds.joints))

    def test_normalize_range_and_existing_driver_protection(self):
        self.build()
        group=self.result['group']
        self.ns['set_pose_driver_normalize'](group,.5)
        self.assertEqual(self.cmds.getAttr(self.result['cone']+'.normalize'),.5)
        for value in (-1,2,float('nan')):
            with self.assertRaises(ValueError): self.ns['set_pose_driver_normalize'](group,value)
        driver=self.cmds.add_node('normalizeAnimation','animCurve')
        self.cmds.connectAttr(driver+'.output',self.result['cone']+'.normalize')
        with self.assertRaisesRegex(ValueError,'driven'): self.ns['set_pose_driver_normalize'](group,1)

    def test_saved_setups_and_joint_link_survive_rename(self):
        self.build()
        self.capture()
        group=self.cmds.rename(self.result['group'],'renamedSetup')
        self.joint=self.cmds.rename(self.joint,'renamedJoint')
        self.assertEqual(self.ns['find_pose_drivers'](self.joint),[group])
        self.assertEqual(self.ns['list_pose_drivers'](),[group])
        state=self.ns['_pd_read'](group)[1]
        self.assertEqual(len(state['poses']),1)
        self.ns['remove_pose_driver'](group)
        self.assertEqual(set(self.cmds.nodes),set(self.cmds.joints))

    def test_locked_or_driven_target_cannot_be_recaptured(self):
        self.build()
        record=self.capture()
        target=self.ns['_pd_node'](record['center'])
        self.cmds.nodes[target]['locked_attrs']={'translateX'}
        with self.assertRaisesRegex(ValueError,'locked'): self.ns['update_pose_driver_pose'](self.result['group'],record['id'],recapture=True)
        self.assertEqual(self.read()['poses'][0]['radius'],45)

    def test_unit_center_uses_joint_origin_and_one_unit_ray(self):
        place=self.ns['pose_driver_unit_center']
        self.assertEqual(place((10,0,0),(10,3,4)),(10,.6,.8))
        self.assertEqual(place((10,0,0),(10,30,40)),(10,.6,.8))
        self.assertEqual(place((10,0,0),(10,.3,.4)),(10,.6,.8))
        with self.assertRaises(ValueError): place((10,0,0),(10,0,0))
        with self.assertRaises(ValueError): place((0,0,0),(float('nan'),0,1))

    def test_captured_joint_axis_respects_world_matrix_and_negative_axis(self):
        # A valid rotated/scaled basis, not parallel X and Z matrix rows.
        self.cmds.nodes[self.joint]['matrix'][:12]=[0,0,-2,0, 0,1,0,0, 2,0,0,0]
        self.build(axis=-1)
        record=self.capture()
        position=self.cmds.xform(self.ns['_pd_node'](record['center']),query=True,translation=True)
        self.assertEqual(position,[3,2,1])

    def test_apply_new_target_preserves_plug_and_unit_offset(self):
        self.build()
        record=self.capture()
        cone=self.result['cone']
        output=self.cmds.inputs[cone+'.armUpWeight']
        obj=self.cmds.add_node('|targetInput','transform')
        self.cmds.xform(obj,translation=(3,8,8))
        self.ns['update_pose_driver_pose'](self.result['group'],record['id'],center=obj)
        updated=self.read()['poses'][0]
        point=self.cmds.xform(self.ns['_pd_node'](record['center']),query=True,translation=True)
        self.assertAlmostEqual(sum((a-b)**2 for a,b in zip(point,(3,2,0))),1)
        self.assertEqual(self.cmds.inputs[cone+'.armUpWeight'],output)
        self.assertEqual(updated['target_object'],self.ns['_pd_uuid'](obj))

    def test_child_groups_have_explicit_zero_origin_and_legacy_origin_is_fixed(self):
        self.build()
        state=self.read()
        aim=self.ns['_pd_node'](state['aim'])
        targets=self.ns['_pd_node'](state['targets'])
        self.assertEqual(self.cmds.getAttr(aim+'.translate'),(0,0,0))
        self.assertEqual(self.cmds.getAttr(targets+'.translate'),(0,0,0))
        self.cmds.setAttr(aim+'.translateX',8)
        self.capture()
        self.assertEqual(self.cmds.getAttr(aim+'.translate'),(0,0,0))

    def test_moved_joint_origin_is_rejected_before_capture_mutation(self):
        self.build()
        self.cmds.nodes[self.joint]['matrix'][12]+=5
        before=set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'moved away'): self.capture()
        self.assertEqual(set(self.cmds.nodes),before)

    def test_failed_capture_restores_legacy_origin(self):
        self.build()
        aim=self.ns['_pd_node'](self.read()['aim'])
        self.cmds.setAttr(aim+'.translateX',9)
        before=set(self.cmds.nodes)
        self.cmds.fail_connection='.brokenWeightRaw'
        with self.assertRaises(RuntimeError): self.capture(name='broken')
        self.assertEqual(set(self.cmds.nodes),before)
        self.assertEqual(self.cmds.getAttr(aim+'.translateX'),9)
        self.assertEqual(self.read()['poses'],[])

    def test_locked_legacy_origin_is_rejected_before_editing_pose(self):
        self.build()
        aim=self.ns['_pd_node'](self.read()['aim'])
        self.cmds.setAttr(aim+'.translateX',9)
        self.cmds.setAttr(aim+'.translateX',lock=True)
        before=set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'origin is locked'): self.capture()
        self.assertEqual(set(self.cmds.nodes),before)
        self.assertEqual(self.cmds.getAttr(aim+'.translateX'),9)

    def _ui_capture(self, target, pose_id=None, legacy_joint_button=True, name='greenPose', automatic=False):
        from types import SimpleNamespace
        panel_class=next(n for n in self.tree.body if isinstance(n,ast.ClassDef) and n.name=='TabPoseDriver')
        method=next(n for n in panel_class.body if isinstance(n,ast.FunctionDef) and n.name=='_apply_pose')
        exec(compile(ast.Module(body=[method],type_ignores=[]),'<PoseDriver capture UI>', 'exec'),self.ns)
        messages,errors=[],[]
        panel=SimpleNamespace(_group=lambda:self.result['group'],_load_group=lambda *args,**kw:None,
                              status=SimpleNamespace(setText=messages.append),_error=errors.append,
                              rotation_minimum=SimpleNamespace(value=lambda:15))
        row=SimpleNamespace(pose_id=pose_id,center=SimpleNamespace(text=lambda:target),
                            name=SimpleNamespace(text=lambda:name),radius=SimpleNamespace(value=lambda:25),
                            auto_radius=SimpleNamespace(isChecked=lambda:automatic))
        self.ns['_apply_pose'](panel,row,legacy_joint_button)
        return messages,errors

    def test_filled_target_field_wins_over_legacy_joint_capture_button(self):
        self.build()
        target=self.cmds.add_node('|greenTarget','transform')
        self.cmds.xform(target,translation=(3,12,0))
        messages,errors=self._ui_capture(target)
        self.assertEqual(errors,[])
        record=self.read()['poses'][0]
        point=self.cmds.xform(self.ns['_pd_node'](record['center']),query=True,translation=True)
        self.assertEqual(point,[3,3,0])
        self.assertEqual(record['target_object'],self.ns['_pd_uuid'](target))
        self.assertIn('cone was not sampled',messages[0])

    def test_existing_pose_ui_update_uses_target_field_not_joint_direction(self):
        self.build()
        record=self.capture(name='greenPose')
        target=self.cmds.add_node('|greenTarget','transform')
        self.cmds.xform(target,translation=(3,-8,0))
        source=self.cmds.inputs[self.result['cone']+'.greenPoseWeight']
        _messages,errors=self._ui_capture(target,record['id'])
        self.assertEqual(errors,[])
        point=self.cmds.xform(self.ns['_pd_node'](record['center']),query=True,translation=True)
        self.assertEqual(point,[3,1,0])
        self.assertEqual(self.cmds.inputs[self.result['cone']+'.greenPoseWeight'],source)

    def test_api_supplied_target_wins_even_with_recapture_flag(self):
        self.build()
        record=self.capture()
        target=self.cmds.add_node('|greenTarget','transform')
        self.cmds.xform(target,translation=(3,2,20))
        self.ns['update_pose_driver_pose'](self.result['group'],record['id'],center=target,recapture=True)
        point=self.cmds.xform(self.ns['_pd_node'](record['center']),query=True,translation=True)
        self.assertEqual(point,[3,2,1])
        self.assertEqual(self.read()['poses'][0]['target_object'],self.ns['_pd_uuid'](target))

    def test_green_centers_stay_independent_of_red_joint_direction(self):
        self.build()
        target=self.cmds.add_node('|greenTarget','transform')
        self.cmds.xform(target,translation=(3,12,0))
        record=self.capture(center=target,radius=20)
        point_before=self.cmds.xform(self.ns['_pd_node'](record['center']),query=True,translation=True)
        self.cmds.nodes[self.joint]['matrix'][:3]=[.6,.8,0]
        point_after=self.cmds.xform(self.ns['_pd_node'](record['center']),query=True,translation=True)
        self.assertEqual(point_before,point_after)
        state=self.read()
        center=self.ns['_pd_node'](record['center'])
        self.assertNotIn(self.ns['_pd_node'](state['aim']),center)
        weight=self.ns['pose_driver_weights']((.6,.8,0),[{'direction':(0,1,0),'radius':20}])
        self.assertEqual(weight['raw'],[0])

    def test_primary_capture_blank_target_and_name_uses_rotation_and_auto_name(self):
        self.build()
        self.rotate_direction(30,rotation=(-20,10,0))
        messages,errors=self._ui_capture('',legacy_joint_button=False,name='')
        self.assertEqual(errors,[])
        record=self.read()['poses'][0]
        self.assertEqual(record['name'],'second_nX20_pY10_pZ0')
        self.assertIsNone(record['target_object'])
        self.assertIn('Current joint direction captured',messages[0])

    def test_primary_capture_blank_target_keeps_supplied_name(self):
        self.build()
        self.rotate_direction(30)
        _messages,errors=self._ui_capture('',legacy_joint_button=False,name='myPose')
        self.assertEqual(errors,[])
        self.assertEqual(self.read()['poses'][0]['name'],'myPose')

    def test_primary_capture_blank_inputs_still_rejects_near_duplicate(self):
        self.build()
        self.rotate_direction(30,rotation=(0,0,30))
        _messages,errors=self._ui_capture('',legacy_joint_button=False,name='')
        self.assertEqual(errors,[])
        before=set(self.cmds.nodes)
        self.rotate_direction(35,rotation=(0,0,35))
        _messages,errors=self._ui_capture('',legacy_joint_button=False,name='')
        self.assertEqual(len(errors),1)
        self.assertIn('minimum is 15.00',str(errors[0]))
        self.assertNotIn('Get a target pose object',str(errors[0]))
        self.assertEqual(set(self.cmds.nodes),before)

    def test_primary_update_blank_target_uses_joint_and_keeps_existing_output(self):
        self.build()
        self.rotate_direction(30)
        original=self.capture_rotation(name='savedPose')
        plug=self.result['cone']+'.savedPoseWeight'
        driver=self.cmds.inputs[plug]
        self.rotate_direction(40)
        _messages,errors=self._ui_capture('',pose_id=original['id'],legacy_joint_button=False,name='')
        self.assertEqual(errors,[])
        updated=self.read()['poses'][0]
        self.assertEqual(updated['name'],'savedPose')
        self.assertEqual(updated['id'],original['id'])
        self.assertEqual(self.cmds.inputs[plug],driver)

    def test_live_cone_cannot_be_used_as_target_object(self):
        self.build()
        with self.assertRaisesRegex(ValueError,'not the live cone'): self.capture(center=self.result['cone'])
        self.assertEqual(self.read()['poses'],[])

    def test_raw_sum_external_consumer_blocks_system_removal(self):
        self.build()
        consumer=self.cmds.add_node('|sumConsumer','transform')
        self.cmds.connectAttr(self.result['cone']+'.rawWeightSum',consumer+'.translateX')
        before=set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'Disconnect'): self.ns['remove_pose_driver'](self.result['group'])
        self.assertEqual(set(self.cmds.nodes),before)

    def test_missing_pose_ramp_reference_is_a_controlled_metadata_error(self):
        self.build()
        self.capture()
        state=self.read()
        del state['poses'][0]['ramp']
        self.ns['_pd_write'](self.result['group'],state)
        with self.assertRaisesRegex(ValueError,'Cannot read'): self.read()

    def test_corrupt_pose_state_is_reported_without_deletion(self):
        self.build()
        self.cmds.nodes[self.result['group']]['attrs']['rtkPoseDriverState']='{invalid'
        before=set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'Cannot read'): self.ns['remove_pose_driver'](self.result['group'])
        self.assertEqual(set(self.cmds.nodes),before)

    def mirror_fixture(self, axis=1, external=True):
        self.joint = self.cmds.rename(self.joint, 'arm_L')
        other = self.cmds.add_node('|first|arm_R', 'joint', matrix=self.cmds.matrix(-3,2,0))
        self.cmds.nodes[other]['attrs'].update(self.cmds.nodes[self.joint]['attrs'])
        self.build(axis=axis)
        if external:
            left = self.cmds.add_node('|pose_L', 'transform')
            right = self.cmds.add_node('|pose_R', 'transform')
            self.cmds.xform(left, translation=(3,8,0))
            self.cmds.xform(right, translation=(-3,2,6))
            self.capture('up_L', center=left, radius=60)
        else:
            self.capture('up_L', radius=60)
        return other

    def mirror(self, **kw):
        return self.ns['mirror_pose_driver'](self.result['group'], **kw)

    def test_mirror_preview_resolves_inputs_without_any_mutation(self):
        other = self.mirror_fixture()
        before = json.dumps(self.cmds.nodes, sort_keys=True, default=list)
        calls = list(self.cmds.calls)
        plan = self.ns['plan_pose_driver_mirror'](self.result['group'])
        self.assertEqual(plan['joint'], other)
        self.assertEqual(plan['axis'], -1)
        self.assertEqual(plan['poses'][0]['target'], '|pose_R')
        self.assertEqual(plan['poses'][0]['position'], (-3,2,1))
        self.assertEqual(plan['poses'][0]['attribute'], 'up_RWeight')
        self.assertEqual(json.dumps(self.cmds.nodes, sort_keys=True, default=list), before)
        self.assertEqual(self.cmds.calls, calls)

    def test_mirror_creates_opposite_cone_and_uses_target_not_live_direction(self):
        other = self.mirror_fixture()
        source = json.dumps(self.read(), sort_keys=True)
        self.ns['set_pose_driver_normalize'](self.result['group'], .5)
        source = json.dumps(self.read(), sort_keys=True)
        result = self.mirror()
        state = self.ns['_pd_read'](result['group'])[1]
        cone = self.ns['_pd_node'](state['cone'])
        self.assertEqual(state['axis'], -1)
        self.assertEqual(self.cmds.getAttr(cone+'.translateX'), -1)
        self.assertTrue(self.cmds.getAttr(cone+'.translateX', lock=True))
        self.assertEqual(self.cmds.getAttr(cone+'.normalize'), .5)
        self.assertEqual(self.cmds.xform(self.ns['_pd_node'](state['poses'][0]['center']),query=True,translation=True), [-3,2,1])
        self.assertEqual(state['poses'][0]['target_object'], self.ns['_pd_uuid']('|pose_R'))
        self.assertEqual(json.dumps(self.read(), sort_keys=True), source)
        self.assertEqual(self.ns['find_pose_drivers'](other), [result['group']])

    def test_repeat_mirror_updates_stable_outputs_and_keeps_extra_poses(self):
        self.mirror_fixture()
        result = self.mirror()
        state = self.ns['_pd_read'](result['group'])[1]
        cone = self.ns['_pd_node'](state['cone'])
        record = state['poses'][0]
        consumer = self.cmds.add_node('weightConsumer', 'multiplyDivide')
        self.cmds.connectAttr(cone+'.up_RWeight', consumer+'.input1X')
        driver = self.cmds.inputs[cone+'.up_RWeight']
        self.ns['add_pose_driver_pose'](result['group'], 'extra', center='|pose_R')
        self.cmds.setAttr(cone+'.normalize', .7)
        self.cmds.xform('|pose_R', translation=(-3,8,0))
        self.ns['update_pose_driver_pose'](self.result['group'],self.read()['poses'][0]['id'],radius=30)
        again = self.mirror()
        self.assertEqual(again['group'], result['group'])
        current = self.ns['_pd_read'](result['group'])[1]
        self.assertEqual(len(current['poses']), 2)
        self.assertEqual(current['poses'][0]['id'], record['id'])
        self.assertEqual(current['poses'][0]['nodes'], record['nodes'])
        self.assertEqual(current['poses'][0]['radius'], 30)
        self.assertEqual(self.cmds.inputs[cone+'.up_RWeight'], driver)
        self.assertEqual(self.cmds.inputs[consumer+'.input1X'], cone+'.up_RWeight')
        self.assertEqual(self.cmds.getAttr(cone+'.normalize'), .7)
        self.assertEqual(self.cmds.getAttr(cone+'.translateX'), -1)
        self.assertEqual(self.cmds.xform(self.ns['_pd_node'](record['center']),query=True,translation=True), [-3,3,0])

    def test_negative_axis_flips_to_positive_and_can_disable_flip(self):
        self.mirror_fixture(axis=-1)
        result = self.mirror()
        self.assertEqual(self.ns['_pd_read'](result['group'])[1]['axis'], 1)
        self.mirror(flip_axis=False)
        self.assertEqual(self.ns['_pd_read'](result['group'])[1]['axis'], -1)

    def test_mirror_back_updates_source_outputs(self):
        self.mirror_fixture()
        result = self.mirror()
        original = self.read()['poses'][0]['id']
        back = self.ns['mirror_pose_driver'](result['group'], search='_R', replace='_L')
        self.assertEqual(back['group'], self.result['group'])
        self.assertEqual(self.read()['axis'], 1)
        self.assertEqual(len(self.read()['poses']), 1)
        self.assertEqual(self.read()['poses'][0]['id'], original)

    def test_joint_only_pose_reflects_saved_direction_and_cleans_temporary(self):
        self.mirror_fixture(external=False)
        source_pose = self.read()['poses'][0]
        source_center = self.ns['_pd_node'](source_pose['center'])
        self.cmds.xform(source_center, translation=(3.6,2.8,0))
        # Current joint direction differs from the stored target.
        self.cmds.nodes[self.joint]['matrix'][:3] = [0,0,1]
        result = self.mirror()
        state = self.ns['_pd_read'](result['group'])[1]
        pose = state['poses'][0]
        position = self.cmds.xform(self.ns['_pd_node'](pose['center']),query=True,translation=True)
        self.assertAlmostEqual(position[0], -3.6)
        self.assertAlmostEqual(position[1], 2.8)
        self.assertIsNone(pose['target_object'])
        self.assertFalse(any('rtkMirrorRay_' in n for n in self.cmds.nodes))
        # Reflect Y instead: +X survives and +Y becomes -Y.
        self.mirror(reflection_axis='Y')
        position = self.cmds.xform(self.ns['_pd_node'](pose['center']),query=True,translation=True)
        self.assertAlmostEqual(position[0], -2.4)
        self.assertAlmostEqual(position[1], 1.2)

    def test_mirror_missing_target_stops_before_destination_build(self):
        self.mirror_fixture()
        self.cmds.delete('|pose_R')
        before = set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError, 'Missing counterpart'):
            self.mirror()
        self.assertEqual(set(self.cmds.nodes), before)

    def test_mirror_missing_joint_and_unchanged_joint_are_rejected(self):
        other = self.mirror_fixture()
        self.cmds.delete(other)
        with self.assertRaisesRegex(ValueError, 'Missing counterpart'): self.mirror()
        with self.assertRaisesRegex(ValueError, 'does not contain'): self.mirror(search='_XX',replace='_YY')

    def test_mirror_resolution_preserves_namespace_and_rejects_ambiguous_leaf(self):
        a = self.cmds.add_node('|one|rig_L:arm_L', 'joint')
        b = self.cmds.add_node('|two|rig_L:arm_R', 'joint')
        self.cmds.add_node('|wrong:arm_R', 'joint')
        resolve = self.ns['_pd_mirror_object']
        self.assertEqual(resolve(a, '_L', '_R', True), b)
        self.cmds.add_node('|three|rig_L:arm_R', 'joint')
        with self.assertRaisesRegex(ValueError, 'Ambiguous'): resolve(a, '_L', '_R', True)
        # Exact replaced ancestor path takes precedence over other leaves.
        c = self.cmds.add_node('|one|rig_L:arm_R', 'joint')
        self.assertEqual(resolve(a, '_L', '_R', True), c)

    def test_mirror_shared_target_is_reused_and_custom_tokens_work(self):
        other = self.mirror_fixture()
        source_pose = self.read()['poses'][0]
        shared = self.cmds.add_node('|middleTarget', 'transform')
        self.cmds.xform(shared, translation=(0,8,0))
        self.ns['update_pose_driver_pose'](self.result['group'],source_pose['id'],center=shared)
        self.assertEqual(self.ns['plan_pose_driver_mirror'](self.result['group'])['poses'][0]['target'],shared)
        self.joint = self.cmds.rename(self.joint, 'arm_left')
        other = self.cmds.rename(other, 'arm_right')
        result = self.mirror(search='_left', replace='_right')
        self.assertEqual(result['joint'], other)
        self.assertEqual(result['poses'][0]['target'], shared)

    def test_mirror_invalid_tokens_and_reflection_axis_are_rejected(self):
        self.mirror_fixture()
        for search,replace in [('', '_R'),('_L',''),('_L','_L'),('*','_R'),('_L',':R')]:
            with self.assertRaises(ValueError): self.mirror(search=search,replace=replace)
        with self.assertRaises(ValueError): self.mirror(reflection_axis='XY')

    def test_mirror_duplicate_replaced_pose_outputs_are_rejected(self):
        self.mirror_fixture()
        self.capture('up_R', center='|pose_L')
        before = set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError, 'duplicate'): self.mirror()
        self.assertEqual(set(self.cmds.nodes), before)

    def test_mirror_existing_destination_moved_origin_is_rejected(self):
        other = self.mirror_fixture()
        self.mirror()
        self.cmds.nodes[other]['matrix'][12] = -5
        before = set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError, 'start origin'): self.mirror()
        self.assertEqual(set(self.cmds.nodes), before)

    def test_mirror_requires_undo_before_any_scene_edit(self):
        self.mirror_fixture()
        before = set(self.cmds.nodes)
        self.cmds.enabled = False
        with self.assertRaisesRegex(ValueError, 'Enable Maya Undo'): self.mirror()
        self.assertEqual(set(self.cmds.nodes), before)

    def test_mirror_failure_rolls_back_entire_destination_update(self):
        import copy
        self.mirror_fixture()
        result = self.mirror()
        before = copy.deepcopy(self.cmds.nodes)
        original_undo_info = self.cmds.undoInfo
        checkpoint = {}
        def undo_info(**kw):
            if kw.get('openChunk'):
                checkpoint.update(name=kw['chunkName'], nodes=copy.deepcopy(self.cmds.nodes), inputs=copy.deepcopy(self.cmds.inputs))
            if kw.get('query') and kw.get('undoName'): return checkpoint.get('name')
            return original_undo_info(**kw)
        def undo():
            self.cmds.nodes = checkpoint['nodes']
            self.cmds.inputs = checkpoint['inputs']
        self.cmds.undoInfo = undo_info
        self.cmds.undo = undo
        # Add an uncaptured output to force failure after existing pose edits.
        self.capture('new_L', center='|pose_L')
        before = copy.deepcopy(self.cmds.nodes)
        self.cmds.xform('|pose_R', translation=(-3,8,0))
        before = copy.deepcopy(self.cmds.nodes)
        self.cmds.fail_connection = '.new_RWeight'
        with self.assertRaisesRegex(RuntimeError, 'rolled back'): self.mirror()
        self.assertEqual(self.cmds.nodes, before)
        self.assertEqual(len(self.ns['_pd_read'](result['group'])[1]['poses']), 1)


    def rotate_direction(self, degrees, rotation=None):
        import math
        angle = math.radians(degrees)
        self.cmds.nodes[self.joint]['matrix'][:3] = [math.cos(angle),math.sin(angle),0]
        if rotation is not None:
            for axis,value in zip('XYZ',rotation):
                self.cmds.setAttr(self.joint+'.rotate'+axis,value)

    def capture_rotation(self, **kw):
        return self.ns['capture_pose_driver_rotation'](self.result['group'],**kw)

    def test_rotation_default_is_saved_when_building_and_no_joint_changes(self):
        self.cmds.setAttr(self.joint+'.rotateX',-20)
        self.cmds.setAttr(self.joint+'.rotateY',10)
        before = json.dumps(self.cmds.nodes[self.joint],sort_keys=True,default=list)
        self.build()
        self.assertEqual(self.read()['default_rotation_degrees'],[-20,10,0])
        self.assertEqual(self.read()['default_rotate_order'],0)
        self.assertEqual(json.dumps(self.cmds.nodes[self.joint],sort_keys=True,default=list),before)

    def test_rotation_at_default_or_twist_only_is_rejected_without_nodes(self):
        self.build()
        before = set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError, "from 'default'"): self.capture_rotation()
        self.cmds.setAttr(self.joint+'.rotateX',50)
        with self.assertRaisesRegex(ValueError, 'Pose not added'): self.capture_rotation()
        self.assertEqual(set(self.cmds.nodes),before)
        self.assertEqual(self.read()['poses'],[])

    def test_rotation_minimum_boundary_uses_angular_distance(self):
        self.build()
        self.rotate_direction(14.9)
        with self.assertRaises(ValueError): self.capture_rotation(name='tooClose')
        self.rotate_direction(15)
        record = self.capture_rotation(name='atBoundary')
        self.assertEqual(record['name'],'atBoundary')
        self.rotate_direction(29.9)
        with self.assertRaisesRegex(ValueError, 'atBoundary'): self.capture_rotation(name='nearOther')
        self.rotate_direction(30)
        self.capture_rotation(name='secondBoundary')
        self.assertEqual(len(self.read()['poses']),2)

    def test_rotation_custom_minimum_and_falloff_are_independent(self):
        self.build()
        self.rotate_direction(10)
        with self.assertRaises(ValueError): self.capture_rotation(name='pose')
        record = self.capture_rotation(name='pose',minimum_angle=8,radius=75)
        self.assertEqual(record['radius'],75)

    def test_rotation_blank_name_uses_signed_delta_from_nonzero_default(self):
        for axis,value in zip('XYZ',(5,15,30)):
            self.cmds.setAttr(self.joint+'.rotate'+axis,value)
        self.joint = self.cmds.rename(self.joint,'arm_L')
        self.build()
        self.rotate_direction(25,rotation=(-15,25,30))
        record = self.capture_rotation()
        self.assertEqual(record['name'],'arm_L_nX20_pY10_pZ0')
        self.assertEqual(record['attribute'],'arm_L_nX20_pY10_pZ0Weight')
        self.assertIsNone(record['target_object'])

    def test_rotation_names_wrap_and_round_without_negative_zero(self):
        name = self.ns['_pd_rotation_pose_name']
        self.assertEqual(name('|rig:arm_L',[170,0,0],[-170,360,-.1]),'arm_L_pX20_pY0_pZ0')
        self.assertEqual(name('joint',[0,0,0],[-20.5,10.4,0]),'joint_nX21_pY10_pZ0')
        for invalid in [(float('nan'),0,0),(0,0)]:
            with self.assertRaises(ValueError): name('joint',[0,0,0],invalid)

    def test_rotation_names_use_degrees_when_maya_uses_radians(self):
        import math
        self.cmds.angle_unit = 'rad'
        self.cmds.setAttr(self.joint+'.rotateY',math.radians(10))
        self.build()
        self.rotate_direction(30,rotation=(math.radians(-20),math.radians(20),0))
        record = self.capture_rotation()
        self.assertEqual(record['name'],'second_nX20_pY10_pZ0')
        self.assertAlmostEqual(self.read()['default_rotation_degrees'][1],10)

    def test_rotation_compares_against_external_object_poses_too(self):
        import math
        self.build()
        obj = self.cmds.add_node('|greenPose','transform')
        self.cmds.xform(obj,translation=(3+math.cos(math.radians(45)),2+math.sin(math.radians(45)),0))
        self.capture('external',center=obj)
        self.rotate_direction(50)
        with self.assertRaisesRegex(ValueError,'external'): self.capture_rotation(name='nearExternal')
        self.rotate_direction(70)
        self.capture_rotation(name='awayFromExternal')

    def test_rotation_collision_adds_suffix_without_replacing_existing_output(self):
        self.build()
        self.rotate_direction(30,rotation=(0,0,0))
        first = self.capture_rotation()
        output = self.cmds.inputs[self.result['cone']+'.'+first['attribute']]
        self.rotate_direction(60,rotation=(0,0,0))
        second = self.capture_rotation()
        self.assertEqual(second['name'],first['name']+'_2')
        self.assertEqual(self.cmds.inputs[self.result['cone']+'.'+first['attribute']],output)

    def test_rotation_recapture_excludes_itself_and_preserves_plugs(self):
        self.build()
        self.rotate_direction(30)
        first = self.capture_rotation(name='first')
        self.rotate_direction(70)
        second = self.capture_rotation(name='second')
        self.rotate_direction(40)
        before = self.cmds.inputs[self.result['cone']+'.firstWeight']
        updated = self.capture_rotation(pose_id=first['id'],radius=80)
        self.assertEqual(updated['id'],first['id'])
        self.assertEqual(updated['radius'],80)
        self.assertEqual(self.cmds.inputs[self.result['cone']+'.firstWeight'],before)
        self.rotate_direction(65)
        with self.assertRaisesRegex(ValueError,'second'): self.capture_rotation(pose_id=first['id'])
        with self.assertRaises(ValueError): self.capture_rotation(pose_id='missing')

    def test_rotation_legacy_named_capture_and_explicit_default_migration(self):
        self.build()
        group,state = self.ns['_pd_read'](self.result['group'])
        for key in ('default_rotation_degrees','default_rotate_order','default_direction_local'):
            del state[key]
        self.ns['_pd_write'](group,state)
        self.rotate_direction(30)
        with self.assertRaisesRegex(ValueError,'older setup'): self.capture_rotation()
        record = self.capture_rotation(name='legacyNamed')
        output = self.cmds.inputs[self.result['cone']+'.legacyNamedWeight']
        self.rotate_direction(0,rotation=(0,0,0))
        self.ns['set_pose_driver_default_rotation'](group)
        self.rotate_direction(60,rotation=(-20,10,0))
        added = self.capture_rotation()
        self.assertEqual(added['name'],'second_nX20_pY10_pZ0')
        self.assertEqual(self.cmds.inputs[self.result['cone']+'.legacyNamedWeight'],output)
        self.assertEqual(self.read()['poses'][0]['id'],record['id'])

    def test_rotation_default_follows_frame_parent_motion(self):
        self.build()
        self.rotate_direction(30)
        self.capture_rotation(name='first')
        # Rotate all saved reference directions 90 degrees in world space.
        frame = self.ns['_pd_node'](self.read()['frame'])
        self.cmds.nodes[frame]['matrix'][:12] = [0,1,0,0,-1,0,0,0,0,0,1,0]
        self.rotate_direction(90)
        with self.assertRaisesRegex(ValueError,"from 'default'"): self.capture_rotation(name='parentMotion')

    def test_rotation_vector_math_handles_rotated_scaled_and_sheared_frame(self):
        transform = self.ns['_pd_frame_vector']
        matrix = [0,2,0,0, -3,1,0,0, .5,0,4,0, 20,30,40,1]
        local = (.6,.8,-.2)
        world = transform(matrix,local)
        recovered = transform(matrix,world,inverse=True)
        for a,b in zip(local,recovered): self.assertAlmostEqual(a,b)
        matrix[:3] = [0,0,0]
        with self.assertRaises(ValueError): transform(matrix,local,inverse=True)

    def test_rotation_negative_axis_checks_default_and_other_pose(self):
        self.build(axis=-1)
        with self.assertRaises(ValueError): self.capture_rotation(name='default')
        self.rotate_direction(30)
        record = self.capture_rotation(name='negativeAxis')
        point = self.cmds.xform(self.ns['_pd_node'](record['center']),query=True,translation=True)
        self.assertLess(point[0],3)
        self.assertLess(point[1],2)

    def test_rotation_zero_threshold_still_blocks_identical_and_invalid_angles(self):
        self.build()
        with self.assertRaises(ValueError): self.capture_rotation(name='default',minimum_angle=0)
        self.rotate_direction(10)
        self.capture_rotation(name='first',minimum_angle=0)
        with self.assertRaises(ValueError): self.capture_rotation(name='duplicate',minimum_angle=0)
        for value in (-1,181,float('nan')):
            with self.assertRaises(ValueError): self.capture_rotation(name='invalid',minimum_angle=value)

    def test_rotation_changed_rotate_order_requires_explicit_new_default_for_names(self):
        self.build()
        self.rotate_direction(30)
        self.cmds.setAttr(self.joint+'.rotateOrder',2)
        with self.assertRaisesRegex(ValueError,'rotation order changed'): self.capture_rotation()
        self.capture_rotation(name='explicitName')

    def test_rotation_capture_is_one_undo_chunk_and_restores_selection(self):
        self.build()
        self.rotate_direction(30)
        selection = self.cmds.selection[:]
        self.cmds.chunks.clear()
        self.capture_rotation(name='captured')
        self.assertEqual(self.cmds.chunks,['open','close'])
        self.assertEqual(self.cmds.selection,selection)

    def test_rotation_existing_card_joint_capture_obeys_minimum(self):
        self.build()
        self.rotate_direction(10)
        _messages,errors = self._ui_capture('')
        self.assertEqual(len(errors),1)
        self.assertEqual(self.read()['poses'],[])
        self.rotate_direction(30)
        _messages,errors = self._ui_capture('')
        self.assertEqual(errors,[])
        self.assertEqual(self.read()['poses'][0]['name'],'greenPose')

    def test_rotation_corrupt_default_metadata_is_controlled_error(self):
        self.build()
        group,state = self.ns['_pd_read'](self.result['group'])
        state['default_rotation_degrees'] = 'bad'
        self.ns['_pd_write'](group,state)
        before = set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'Invalid default'): self.capture_rotation()
        self.assertEqual(set(self.cmds.nodes),before)


    def test_joint_weights_are_auto_connected_unlocked_and_transform_unchanged(self):
        self.build()
        before = dict(self.cmds.nodes[self.joint]['attrs'])
        record = self.capture()
        self.assertEqual(record['joint_attributes'],{'armUpWeight':'armUpWeight','armUpWeightRaw':'armUpWeightRaw'})
        for output,attribute in record['joint_attributes'].items():
            plug = self.joint+'.'+attribute
            self.assertEqual(self.cmds.inputs[plug],self.result['cone']+'.'+output)
            self.assertFalse(self.cmds.getAttr(plug,lock=True))
            visibility = [call for call in self.cmds.calls if call[0]=='setAttr' and call[1]==plug]
            self.assertTrue(any(call[3].get('channelBox') for call in visibility))
        for name,value in before.items():
            self.assertEqual(self.cmds.nodes[self.joint]['attrs'][name],value)

    def test_joint_weight_collisions_choose_alias_without_reusing_user_attributes(self):
        self.build()
        for attr in ('armUpWeight','pd_armUpWeight','armUpWeightRaw'):
            self.cmds.addAttr(self.joint,longName=attr,attributeType='double')
            self.cmds.setAttr(self.joint+'.'+attr,.4)
        existing_driver = self.cmds.add_node('customDriver','multiplyDivide')
        self.cmds.connectAttr(existing_driver+'.outputX',self.joint+'.armUpWeight')
        record = self.capture()
        self.assertEqual(record['joint_attributes']['armUpWeight'],'pd_armUpWeight_2')
        self.assertEqual(record['joint_attributes']['armUpWeightRaw'],'pd_armUpWeightRaw')
        self.assertEqual(self.cmds.inputs[self.joint+'.armUpWeight'],existing_driver+'.outputX')
        self.assertEqual(self.cmds.getAttr(self.joint+'.armUpWeightRaw'),.4)
        self.ns['remove_pose_driver'](self.result['group'])
        for attr in ('armUpWeight','pd_armUpWeight','armUpWeightRaw'):
            self.assertTrue(self.cmds.attributeQuery(attr,node=self.joint,exists=True))
            self.assertEqual(self.cmds.getAttr(self.joint+'.'+attr),.4)

    def legacy_joint_weight_setup(self):
        group,state = self.ns['_pd_read'](self.result['group'])
        self.ns['_pd_remove_joint_weights'](state,state['poses'])
        for pose in state['poses']: pose.pop('joint_attributes',None)
        self.ns['_pd_write'](group,state)

    def test_existing_joint_weights_connect_once_and_repeat_preserves_plugs(self):
        self.build()
        self.capture()
        self.legacy_joint_weight_setup()
        first = self.ns['expose_pose_driver_joint_weights'](self.result['group'])
        self.assertEqual(first['joint'],self.joint)
        self.assertEqual(len(first['attributes']),2)
        adds = len([c for c in self.cmds.calls if c[0]=='addAttr'])
        before = dict(self.cmds.inputs)
        self.ns['expose_pose_driver_joint_weights'](self.result['group'])
        self.assertEqual(len([c for c in self.cmds.calls if c[0]=='addAttr']),adds)
        self.assertEqual(self.cmds.inputs,before)

    def test_joint_weight_pose_removal_preserves_other_pose_and_user_attrs(self):
        self.build()
        self.cmds.addAttr(self.joint,longName='userValue',attributeType='double')
        first = self.capture('first')
        second = self.capture('second')
        self.ns['remove_pose_driver_pose'](self.result['group'],first['id'])
        self.assertFalse(self.cmds.attributeQuery('firstWeight',node=self.joint,exists=True))
        self.assertFalse(self.cmds.attributeQuery('firstWeightRaw',node=self.joint,exists=True))
        self.assertEqual(self.cmds.inputs[self.joint+'.secondWeight'],self.result['cone']+'.secondWeight')
        self.ns['remove_pose_driver'](self.result['group'])
        self.assertFalse(self.cmds.attributeQuery('secondWeight',node=self.joint,exists=True))
        self.assertTrue(self.cmds.attributeQuery('userValue',node=self.joint,exists=True))

    def test_joint_weight_external_consumers_block_pose_and_system_removal(self):
        self.build()
        record = self.capture()
        consumer = self.cmds.add_node('jointWeightConsumer','multiplyDivide')
        self.cmds.connectAttr(self.joint+'.armUpWeight',consumer+'.input1X')
        before = set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'Joint weight.*drives'):
            self.ns['remove_pose_driver_pose'](self.result['group'],record['id'])
        with self.assertRaisesRegex(ValueError,'Joint weight.*drives'):
            self.ns['remove_pose_driver'](self.result['group'])
        self.assertEqual(set(self.cmds.nodes),before)
        self.assertEqual(self.cmds.inputs[consumer+'.input1X'],self.joint+'.armUpWeight')

    def test_joint_weight_disconnected_attribute_is_kept_on_system_remove(self):
        self.build()
        self.capture()
        self.cmds.inputs.pop(self.joint+'.armUpWeight')
        self.cmds.setAttr(self.joint+'.armUpWeight',lock=False)
        self.cmds.setAttr(self.joint+'.armUpWeight',.75)
        self.ns['remove_pose_driver'](self.result['group'])
        self.assertTrue(self.cmds.attributeQuery('armUpWeight',node=self.joint,exists=True))
        self.assertEqual(self.cmds.getAttr(self.joint+'.armUpWeight'),.75)
        self.assertFalse(self.cmds.attributeQuery('armUpWeightRaw',node=self.joint,exists=True))

    def test_joint_weight_changed_input_is_not_overwritten_or_deleted(self):
        self.build()
        self.capture()
        driver = self.cmds.add_node('otherWeightDriver','multiplyDivide')
        self.cmds.inputs[self.joint+'.armUpWeight'] = driver+'.outputX'
        with self.assertRaisesRegex(ValueError,'another driver'):
            self.ns['expose_pose_driver_joint_weights'](self.result['group'])
        self.assertEqual(self.cmds.inputs[self.joint+'.armUpWeight'],driver+'.outputX')
        self.ns['remove_pose_driver'](self.result['group'])
        self.assertEqual(self.cmds.inputs[self.joint+'.armUpWeight'],driver+'.outputX')

    def test_joint_weight_locked_or_referenced_source_keeps_cone_working(self):
        self.build()
        self.cmds.nodes[self.joint]['referenced'] = True
        record = self.capture()
        self.assertNotIn('joint_attributes',record)
        self.assertTrue(self.cmds.attributeQuery('armUpWeight',node=self.result['cone'],exists=True))
        self.assertFalse(self.cmds.attributeQuery('armUpWeight',node=self.joint,exists=True))
        with self.assertRaisesRegex(ValueError,'locked or referenced'):
            self.ns['expose_pose_driver_joint_weights'](self.result['group'])

    def test_joint_weight_creation_failure_rolls_back_capture_graph_and_attrs(self):
        self.build()
        before = set(self.cmds.nodes)
        attrs = dict(self.cmds.nodes[self.joint]['attrs'])
        self.cmds.fail_connection = self.joint+'.armUpWeight'
        with self.assertRaises(RuntimeError): self.capture()
        self.assertEqual(set(self.cmds.nodes),before)
        self.assertEqual(self.cmds.nodes[self.joint]['attrs'],attrs)
        self.assertEqual(self.read()['poses'],[])

    def test_joint_weight_batch_failure_rolls_back_new_attrs_and_metadata(self):
        self.build()
        self.capture('first')
        self.capture('second')
        self.legacy_joint_weight_setup()
        before = self.read()
        attrs = dict(self.cmds.nodes[self.joint]['attrs'])
        self.cmds.fail_connection = self.joint+'.secondWeight'
        with self.assertRaises(RuntimeError):
            self.ns['expose_pose_driver_joint_weights'](self.result['group'])
        self.assertEqual(self.read(),before)
        self.assertEqual(self.cmds.nodes[self.joint]['attrs'],attrs)

    def test_joint_weight_alias_connections_survive_joint_rename(self):
        self.build()
        self.capture()
        self.joint = self.cmds.rename(self.joint,'renamedJoint')
        result = self.ns['expose_pose_driver_joint_weights'](self.result['group'])
        self.assertEqual(result['joint'],self.joint)
        self.ns['remove_pose_driver'](self.result['group'])
        self.assertFalse(self.cmds.attributeQuery('armUpWeight',node=self.joint,exists=True))

    def test_joint_weight_missing_owned_attr_is_recreated_with_same_name(self):
        self.build()
        self.capture()
        self.cmds.deleteAttr(self.joint+'.armUpWeight')
        result = self.ns['expose_pose_driver_joint_weights'](self.result['group'])
        self.assertIn(self.joint+'.armUpWeight',result['attributes'])
        self.assertEqual(self.cmds.inputs[self.joint+'.armUpWeight'],self.result['cone']+'.armUpWeight')

    def test_joint_weight_metadata_cannot_claim_builtin_attribute(self):
        self.build()
        self.capture()
        group,state = self.ns['_pd_read'](self.result['group'])
        state['poses'][0]['joint_attributes']['armUpWeight'] = 'rotateX'
        self.ns['_pd_write'](group,state)
        with self.assertRaisesRegex(ValueError,'ownership'): self.ns['remove_pose_driver'](group)
        self.assertTrue(self.cmds.attributeQuery('rotateX',node=self.joint,exists=True))

    def test_joint_weights_mirror_connects_to_destination_joint_not_source(self):
        other = self.mirror_fixture()
        result = self.mirror()
        state = self.ns['_pd_read'](result['group'])[1]
        cone = self.ns['_pd_node'](state['cone'])
        self.assertEqual(self.cmds.inputs[other+'.up_RWeight'],cone+'.up_RWeight')
        self.assertEqual(self.cmds.inputs[self.joint+'.up_LWeight'],self.result['cone']+'.up_LWeight')


    def test_linear_angular_falloff_is_proportional_to_rotation(self):
        import math
        targets = [{'direction':(1,0,0),'radius':45}]
        for angle,expected in [(0,1),(15,2/3),(30,1/3),(45,0),(60,0)]:
            vector = (math.cos(math.radians(angle)),math.sin(math.radians(angle)),0)
            result = self.ns['pose_driver_weights'](vector,targets,falloff='linear')
            self.assertAlmostEqual(result['raw'][0],expected)
            self.assertAlmostEqual(result['weights'][0],expected)

    def test_linear_normalization_still_changes_final_curve(self):
        import math
        target = [{'direction':(1,0,0),'radius':60}]
        vector = (math.cos(math.radians(30)),math.sin(math.radians(30)),0)
        raw = self.ns['pose_driver_weights'](vector,target,falloff='linear')
        normalized = self.ns['pose_driver_weights'](vector,target,normalize=1,falloff='linear')
        self.assertAlmostEqual(raw['weights'][0],.5)
        self.assertAlmostEqual(normalized['raw'][0],.5)
        self.assertEqual(normalized['weights'],[1])
        with self.assertRaises(ValueError): self.ns['pose_driver_weights'](vector,target,falloff='invalid')

    def test_linear_zero_direction_and_radius_boundaries(self):
        evaluate = self.ns['pose_driver_weights']
        for direction in [(0,0,0),(-1,0,0)]:
            self.assertEqual(evaluate(direction,[{'direction':(1,0,0),'radius':179.9}],falloff='linear')['weights'],[0])
        self.assertEqual(evaluate((1,0,0),[{'direction':(0,0,0),'radius':45}],falloff='linear')['weights'],[0])
        self.assertEqual(evaluate((1,0,0),[{'direction':(1,0,0),'radius':.1}],falloff='linear')['weights'],[1])

    def test_linear_upgrade_keeps_cone_joint_outputs_and_downstream_plugs(self):
        self.build()
        self.ns['set_pose_driver_falloff'](self.result['group'],'smooth')
        pose = self.capture()
        cone = self.result['cone']
        output = self.cmds.inputs[cone+'.armUpWeight']
        raw = self.cmds.inputs[cone+'.armUpWeightRaw']
        joint_input = self.cmds.inputs[self.joint+'.armUpWeight']
        consumer = self.cmds.add_node('linearWeightConsumer','multiplyDivide')
        self.cmds.connectAttr(cone+'.armUpWeight',consumer+'.input1X')
        self.ns['set_pose_driver_falloff'](self.result['group'],'linear')
        state = self.read()
        current = state['poses'][0]
        self.assertEqual(state['falloff_mode'],'linear')
        self.assertEqual(current['id'],pose['id'])
        self.assertEqual(self.cmds.inputs[cone+'.armUpWeight'],output)
        self.assertEqual(self.cmds.inputs[cone+'.armUpWeightRaw'],raw)
        self.assertEqual(self.cmds.inputs[self.joint+'.armUpWeight'],joint_input)
        self.assertEqual(self.cmds.inputs[consumer+'.input1X'],cone+'.armUpWeight')
        self.assertTrue(set(pose['nodes']).issubset(current['nodes']))
        self.assertTrue(set(current['nodes']).issubset(state['members']))

    def test_linear_graph_uses_radians_and_linear_ramp(self):
        import math
        self.build()
        self.capture(radius=60)
        self.ns['set_pose_driver_falloff'](self.result['group'],'linear')
        pose = self.read()['poses'][0]
        linear = self.ns['_pd_node'](pose['linear_ramp'])
        self.assertAlmostEqual(self.cmds.getAttr(linear+'.inputMax'),math.pi/3)
        self.assertEqual(self.cmds.getAttr(linear+'.outputMin'),1)
        self.assertEqual(self.cmds.getAttr(linear+'.outputMax'),0)
        self.assertEqual(self.cmds.getAttr(linear+'.value[0].value_Interp'),1)
        conversion = self.cmds.inputs[linear+'.inputValue'].rsplit('.',1)[0]
        self.assertEqual(self.cmds.nodeType(conversion),'unitConversion')
        self.assertEqual(self.cmds.getAttr(conversion+'.conversionFactor'),1)
        angle = self.cmds.inputs[conversion+'.input'].rsplit('.',1)[0]
        self.assertEqual(self.cmds.nodeType(angle),'angleBetween')
        self.assertEqual(self.cmds.inputs[angle+'.vector1'],self.ns['_pd_node'](self.read()['live'])+'.output')

    def test_linear_mode_reuses_graph_when_switching_back_and_forth(self):
        self.build()
        self.capture()
        set_mode = self.ns['set_pose_driver_falloff']
        set_mode(self.result['group'],'linear')
        pose = self.read()['poses'][0]
        before = set(self.cmds.nodes)
        blend = self.ns['_pd_node'](pose['falloff_blend'])
        set_mode(self.result['group'],'smooth')
        self.assertEqual(self.cmds.getAttr(blend+'.blender'),0)
        self.assertEqual(self.read()['falloff_mode'],'smooth')
        set_mode(self.result['group'],'linear')
        self.assertEqual(self.cmds.getAttr(blend+'.blender'),1)
        self.assertEqual(set(self.cmds.nodes),before)

    def test_new_poses_inherit_linear_mode_and_cleanup_owned_nodes(self):
        self.build()
        self.ns['set_pose_driver_falloff'](self.result['group'],'linear')
        pose = self.capture()
        self.assertIn('linear_ramp',pose)
        self.assertIn('falloff_blend',pose)
        self.ns['remove_pose_driver_pose'](self.result['group'],pose['id'])
        for identity in pose['nodes']:
            self.assertFalse(self.cmds.ls(identity,long=True))
        self.assertFalse(self.cmds.attributeQuery('armUpWeight',node=self.joint,exists=True))

    def test_linear_recapture_updates_radius_without_replacing_graph(self):
        import math
        self.build()
        original = self.capture()
        self.ns['set_pose_driver_falloff'](self.result['group'],'linear')
        pose = self.read()['poses'][0]
        nodes = pose['nodes'][:]
        self.ns['update_pose_driver_pose'](self.result['group'],original['id'],radius=90)
        current = self.read()['poses'][0]
        self.assertEqual(current['nodes'],nodes)
        self.assertAlmostEqual(self.cmds.getAttr(self.ns['_pd_node'](pose['linear_ramp'])+'.inputMax'),math.pi/2)
        linear = self.ns['_pd_node'](pose['linear_ramp'])
        self.cmds.setAttr(linear+'.inputMax',lock=True)
        with self.assertRaisesRegex(ValueError,'linear falloff radius'):
            self.ns['update_pose_driver_pose'](self.result['group'],original['id'],radius=45)

    def test_linear_mirror_new_setup_copies_mode_and_existing_setup_keeps_mode(self):
        self.mirror_fixture()
        self.ns['set_pose_driver_falloff'](self.result['group'],'linear')
        result = self.mirror()
        state = self.ns['_pd_read'](result['group'])[1]
        self.assertEqual(state['falloff_mode'],'linear')
        self.assertIn('linear_ramp',state['poses'][0])
        self.ns['set_pose_driver_falloff'](result['group'],'smooth')
        self.mirror()
        self.assertEqual(self.ns['_pd_read'](result['group'])[1]['falloff_mode'],'smooth')

    def test_linear_upgrade_checks_driven_gate_before_modifying_anything(self):
        self.build()
        self.ns['set_pose_driver_falloff'](self.result['group'],'smooth')
        pose = self.capture()
        gate = self.cmds.inputs[self.result['cone']+'.armUpWeightRaw'].rsplit('.',1)[0]
        self.cmds.setAttr(gate+'.colorIfTrueR',lock=True)
        before = set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'locked'):
            self.ns['set_pose_driver_falloff'](self.result['group'],'linear')
        self.assertEqual(set(self.cmds.nodes),before)
        self.assertNotIn('linear_ramp',self.read()['poses'][0])

    def test_linear_mode_rejects_disabled_undo_and_invalid_metadata(self):
        self.build()
        self.capture()
        self.cmds.enabled = False
        with self.assertRaisesRegex(ValueError,'Enable Maya Undo'):
            self.ns['set_pose_driver_falloff'](self.result['group'],'linear')
        self.cmds.enabled = True
        group,state = self.ns['_pd_read'](self.result['group'])
        state['falloff_mode'] = 'unknown'
        self.ns['_pd_write'](group,state)
        with self.assertRaisesRegex(ValueError,'falloff'): self.read()

    def test_linear_failed_upgrade_rolls_back_all_graph_and_connections(self):
        import copy
        self.build()
        self.ns['set_pose_driver_falloff'](self.result['group'],'smooth')
        self.capture()
        before_nodes,before_inputs = copy.deepcopy(self.cmds.nodes),dict(self.cmds.inputs)
        info = self.cmds.undoInfo
        checkpoint = {}
        def undo_info(**kw):
            if kw.get('openChunk'):
                checkpoint['name'] = kw['chunkName']
            if kw.get('query') and kw.get('undoName'): return checkpoint['name']
            return info(**kw)
        def undo():
            self.cmds.nodes = copy.deepcopy(before_nodes)
            self.cmds.inputs = dict(before_inputs)
        self.cmds.undoInfo,self.cmds.undo = undo_info,undo
        self.cmds.fail_connection = '.color1R'
        with self.assertRaisesRegex(RuntimeError,'rolled back'):
            self.ns['set_pose_driver_falloff'](self.result['group'],'linear')
        self.assertEqual(self.cmds.nodes,before_nodes)
        self.assertEqual(self.cmds.inputs,before_inputs)


    def test_easy_remove_freezes_direct_and_joint_weight_consumers(self):
        self.build()
        self.capture()
        a = self.cmds.add_node('directReceiver','multiplyDivide')
        b = self.cmds.add_node('jointReceiver','multiplyDivide')
        self.cmds.setAttr(a+'.input1X',.3)
        self.cmds.setAttr(b+'.input1X',.6)
        self.cmds.connectAttr(self.result['cone']+'.armUpWeight',a+'.input1X')
        self.cmds.connectAttr(self.joint+'.armUpWeightRaw',b+'.input1X')
        before = {name:self.cmds.nodes[self.joint]['attrs'][name] for name in ('rotateX','rotateY','rotateZ','jointOrient')}
        self.ns['remove_pose_driver'](self.result['group'],preserve_consumers=True)
        self.assertNotIn(a+'.input1X',self.cmds.inputs)
        self.assertNotIn(b+'.input1X',self.cmds.inputs)
        self.assertEqual(self.cmds.getAttr(a+'.input1X'),.3)
        self.assertEqual(self.cmds.getAttr(b+'.input1X'),.6)
        self.assertTrue(a in self.cmds.nodes and b in self.cmds.nodes and self.joint in self.cmds.nodes)
        self.assertFalse(self.cmds.attributeQuery('armUpWeight',node=self.joint,exists=True))
        for name,value in before.items(): self.assertEqual(self.cmds.nodes[self.joint]['attrs'][name],value)

    def test_easy_remove_restores_receiver_attribute_lock(self):
        self.build()
        self.capture()
        receiver = self.cmds.add_node('lockedChannelReceiver','multiplyDivide')
        self.cmds.setAttr(receiver+'.input1X',.8)
        self.cmds.connectAttr(self.result['cone']+'.armUpWeight',receiver+'.input1X')
        self.cmds.setAttr(receiver+'.input1X',lock=True)
        self.ns['remove_pose_driver'](self.result['group'],preserve_consumers=True)
        self.assertEqual(self.cmds.getAttr(receiver+'.input1X'),.8)
        self.assertTrue(self.cmds.getAttr(receiver+'.input1X',lock=True))

    def test_easy_remove_checks_all_receivers_before_editing(self):
        self.build()
        self.capture()
        a = self.cmds.add_node('allowedReceiver','multiplyDivide')
        b = self.cmds.add_node('referencedReceiver','multiplyDivide')
        self.cmds.connectAttr(self.result['cone']+'.armUpWeight',a+'.input1X')
        self.cmds.connectAttr(self.joint+'.armUpWeightRaw',b+'.input1X')
        self.cmds.nodes[b]['referenced'] = True
        inputs = dict(self.cmds.inputs)
        nodes = set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'locked/referenced'):
            self.ns['remove_pose_driver'](self.result['group'],preserve_consumers=True)
        self.assertEqual(self.cmds.inputs,inputs)
        self.assertEqual(set(self.cmds.nodes),nodes)

    def test_easy_remove_includes_normalize_and_raw_sum_receivers(self):
        self.build()
        self.capture()
        receiver = self.cmds.add_node('summaryReceiver','multiplyDivide')
        for output,attr,value in [('normalize','input1X',.7),('rawWeightSum','input2X',1.5)]:
            self.cmds.setAttr(receiver+'.'+attr,value)
            self.cmds.connectAttr(self.result['cone']+'.'+output,receiver+'.'+attr)
        self.ns['remove_pose_driver'](self.result['group'],preserve_consumers=True)
        self.assertEqual(self.cmds.getAttr(receiver+'.input1X'),.7)
        self.assertEqual(self.cmds.getAttr(receiver+'.input2X'),1.5)

    def test_easy_remove_refuses_foreign_children_and_disabled_undo(self):
        self.build()
        self.capture()
        self.cmds.enabled = False
        with self.assertRaisesRegex(ValueError,'Enable Maya Undo'):
            self.ns['remove_pose_driver'](self.result['group'],preserve_consumers=True)
        self.cmds.enabled = True
        foreign = self.cmds.add_node(self.result['group']+'|unrelated','transform')
        with self.assertRaisesRegex(ValueError,'unrelated object'):
            self.ns['remove_pose_driver'](self.result['group'],preserve_consumers=True)
        self.assertTrue(foreign in self.cmds.nodes)

    def test_easy_remove_failure_rolls_back_connections_values_and_setup(self):
        import copy
        self.build()
        self.capture()
        receiver = self.cmds.add_node('rollbackReceiver','multiplyDivide')
        self.cmds.setAttr(receiver+'.input1X',.5)
        self.cmds.connectAttr(self.result['cone']+'.armUpWeight',receiver+'.input1X')
        before_nodes,before_inputs = copy.deepcopy(self.cmds.nodes),dict(self.cmds.inputs)
        original_info = self.cmds.undoInfo
        checkpoint = {}
        def info(**kw):
            if kw.get('openChunk'): checkpoint['name'] = kw['chunkName']
            if kw.get('query') and kw.get('undoName'): return checkpoint['name']
            return original_info(**kw)
        def undo():
            self.cmds.nodes = copy.deepcopy(before_nodes)
            self.cmds.inputs = dict(before_inputs)
        def fail_delete(_state,_poses): raise RuntimeError('simulated deletion failure')
        self.cmds.undoInfo,self.cmds.undo = info,undo
        self.ns['_pd_remove_joint_weights'] = fail_delete
        with self.assertRaisesRegex(RuntimeError,'rolled back'):
            self.ns['remove_pose_driver'](self.result['group'],preserve_consumers=True)
        self.assertEqual(self.cmds.nodes,before_nodes)
        self.assertEqual(self.cmds.inputs,before_inputs)


    def test_sdk_new_weights_are_unlocked_keyable_and_visible(self):
        self.build()
        pose = self.capture()
        for node in (self.result['cone'],self.joint):
            for attribute in ('armUpWeight','armUpWeightRaw'):
                plug = node+'.'+attribute
                self.assertFalse(self.cmds.getAttr(plug,lock=True))
                self.assertTrue(self.cmds.getAttr(plug,keyable=True))
                self.assertTrue(self.cmds.getAttr(plug,channelBox=True))
        self.assertFalse(self.cmds.getAttr(self.result['cone']+'.rawWeightSum',lock=True))
        self.assertTrue(self.cmds.getAttr(self.result['cone']+'.translateX',lock=True))

    def test_sdk_existing_weights_unlock_without_changing_values_connections_or_pose(self):
        self.build()
        self.capture()
        owned = [self.result['cone']+'.armUpWeight',self.result['cone']+'.armUpWeightRaw',self.joint+'.armUpWeight',self.joint+'.armUpWeightRaw']
        for plug in owned: self.cmds.setAttr(plug,lock=True,keyable=False)
        values = [self.cmds.getAttr(p) for p in owned]
        inputs = dict(self.cmds.inputs)
        state = self.read()
        result = self.ns['unlock_pose_driver_weights'](self.result['group'])
        self.assertTrue(set(owned).issubset(result['attributes']))
        for plug in owned:
            self.assertFalse(self.cmds.getAttr(plug,lock=True))
            self.assertTrue(self.cmds.getAttr(plug,keyable=True))
        self.assertEqual(self.cmds.inputs,inputs)
        self.assertEqual([self.cmds.getAttr(p) for p in owned],values)
        self.assertEqual(self.read(),state)

    def test_sdk_connect_existing_joint_weights_also_unlocks_cone_and_joint(self):
        self.build()
        self.capture()
        for node in (self.result['cone'],self.joint):
            self.cmds.setAttr(node+'.armUpWeight',lock=True,keyable=False)
        self.ns['expose_pose_driver_joint_weights'](self.result['group'])
        for node in (self.result['cone'],self.joint):
            self.assertFalse(self.cmds.getAttr(node+'.armUpWeight',lock=True))
            self.assertTrue(self.cmds.getAttr(node+'.armUpWeight',keyable=True))

    def test_sdk_unlock_does_not_touch_repurposed_joint_attr_or_builtin_channels(self):
        self.build()
        self.capture()
        self.cmds.inputs.pop(self.joint+'.armUpWeight')
        self.cmds.setAttr(self.joint+'.armUpWeight',lock=True,keyable=False)
        self.cmds.setAttr(self.joint+'.rotateX',lock=True)
        self.ns['unlock_pose_driver_weights'](self.result['group'])
        self.assertTrue(self.cmds.getAttr(self.joint+'.armUpWeight',lock=True))
        self.assertTrue(self.cmds.getAttr(self.joint+'.rotateX',lock=True))

    def test_sdk_unlock_skips_referenced_joint_but_unlocks_cone(self):
        self.build()
        self.capture()
        self.cmds.setAttr(self.result['cone']+'.armUpWeight',lock=True)
        self.cmds.setAttr(self.joint+'.armUpWeight',lock=True)
        self.cmds.nodes[self.joint]['referenced'] = True
        result = self.ns['unlock_pose_driver_weights'](self.result['group'])
        self.assertTrue(result['skipped_joint'])
        self.assertFalse(self.cmds.getAttr(self.result['cone']+'.armUpWeight',lock=True))
        self.assertTrue(self.cmds.getAttr(self.joint+'.armUpWeight',lock=True))

    def test_sdk_driver_fanout_kept_by_unlock_and_recapture(self):
        self.build()
        pose = self.capture()
        curve = self.cmds.add_node('sdkCurve','animCurveUU')
        self.cmds.connectAttr(self.joint+'.armUpWeight',curve+'.input')
        self.ns['unlock_pose_driver_weights'](self.result['group'])
        self.ns['update_pose_driver_pose'](self.result['group'],pose['id'],radius=60)
        self.assertEqual(self.cmds.inputs[curve+'.input'],self.joint+'.armUpWeight')
        self.assertFalse(self.cmds.getAttr(self.joint+'.armUpWeight',lock=True))



    def _normalizer(self):
        cone=self.result['cone'];blend=self.cmds.inputs[cone+'.armUpWeight'].rsplit('.',1)[0]
        return self.cmds.inputs[blend+'.color1R'].rsplit('.',1)[0]

    def _legacy_division(self):
        state=self.read();denominator=self.ns['_pd_node'](state['denominator']);node=self._normalizer()
        remove=[]
        for pose in state['poses']:
            numerator=pose.pop('normalization_numerator',None);pose.pop('normalizer',None)
            if numerator:
                source=self.ns['_pd_node'](numerator);remove.append(numerator);pose['nodes'].remove(numerator)
                raw=self.cmds.inputs[self.result['cone']+'.'+pose['attribute']+'Raw']
                self.cmds.disconnectAttr(source+'.outputX',node+'.input1X');self.cmds.connectAttr(raw,node+'.input1X')
        divisor=state.pop('normalization_divisor',None);scaled=state.pop('normalization_sum',None)
        if divisor:
            self.cmds.disconnectAttr(self.ns['_pd_node'](divisor)+'.outputR',node+'.input2X')
            self.cmds.connectAttr(denominator+'.outColorR',node+'.input2X')
            remove.extend((divisor,scaled))
        self.cmds.delete([self.ns['_pd_node'](identity) for identity in remove]);state['members']=[identity for identity in state['members'] if identity not in remove]
        self.ns['_pd_write'](self.result['group'],state)
        self.cmds.setAttr(denominator+'.secondTerm',0);self.cmds.setAttr(denominator+'.colorIfFalseR',1)
        for axis in 'YZ':self.cmds.setAttr(node+'.input2'+axis,0)
        return denominator,node

    def test_divide_safe_sum_is_positive_for_zero_tiny_and_positive_totals(self):
        self.build();self.capture();den=self.ns['_pd_node'](self.read()['denominator'])
        threshold=self.cmds.getAttr(den+'.secondTerm');fallback=self.cmds.getAttr(den+'.colorIfFalseR')
        self.assertEqual(threshold,1e-8);self.assertEqual(fallback,1e-8)
        for total in (0.,1e-40,1e-10,1e-8,.1,1.,2.):
            safe=total if total>threshold else fallback
            self.assertGreater(safe,0);self.assertEqual(safe,max(total,1e-8))

    def test_divide_is_enabled_only_after_safe_inputs_are_connected(self):
        events=[];connect=self.cmds.connectAttr;set_attr=self.cmds.setAttr
        def connect_spy(a,b):events.append(('connect',b));return connect(a,b)
        def set_spy(plug,*values,**kwargs):events.append(('set',plug,values));return set_attr(plug,*values,**kwargs)
        self.cmds.connectAttr=connect_spy;self.cmds.setAttr=set_spy;self.build();self.capture()
        divides=[node for node,spec in self.cmds.nodes.items() if spec['type']=='multiplyDivide' and spec['attrs'].get('operation')==2]
        self.assertTrue(divides)
        for node in divides:
            enabled=next(i for i,event in enumerate(events) if event==('set',node+'.operation',(2,)))
            axes='X' if node==self._normalizer() else 'XYZ'
            for axis in axes:self.assertTrue(any(event==('connect',node+'.input2'+axis) for event in events[:enabled]))
        self.assertEqual(self.cmds.getAttr(self._normalizer()+'.input2Y'),1)
        self.assertEqual(self.cmds.getAttr(self._normalizer()+'.input2Z'),1)

    def test_divide_floor_keeps_zero_weights_and_regular_centers_exact(self):
        targets=[{'direction':(1,0,0),'radius':60}]
        self.assertEqual(self.ns['pose_driver_weights']((-1,0,0),targets,1)['weights'],[0])
        self.assertEqual(self.ns['pose_driver_weights']((1,0,0),targets,1)['weights'],[1])
        self.assertEqual(self.ns['pose_driver_weights']((1,0,0),targets*2,1)['weights'],[.5,.5])

    def test_divide_floor_limits_normalization_of_tiny_raw_weights(self):
        import math
        angle=math.radians(60-0.0001);target=[{'direction':(1,0,0),'radius':60}]
        result=self.ns['pose_driver_weights']((math.cos(angle),math.sin(angle),0),target,1,falloff='smooth')
        self.assertGreater(result['raw'][0],0);self.assertLess(result['sum'],1e-8)
        self.assertAlmostEqual(result['weights'][0],result['raw'][0]/1e-8)

    def test_divide_repair_preserves_output_nodes_sdk_connections_and_locks(self):
        self.build();self.capture();den,node=self._legacy_division()
        curve=self.cmds.add_node('divisionSDK','animCurveUU');self.cmds.connectAttr(self.joint+'.armUpWeight',curve+'.input')
        before_nodes=set(self.cmds.nodes);before_links=dict(self.cmds.inputs);self.cmds.calls.clear()
        result=self.ns['repair_pose_driver_division'](self.result['group'])
        self.assertTrue(result['changed']);self.assertEqual(result['normalizers'],1)
        self.assertTrue(before_nodes.issubset(set(self.cmds.nodes)))
        stable={plug:source for plug,source in before_links.items() if plug not in (node+'.input1X',node+'.input2X')}
        self.assertTrue(all(self.cmds.inputs[plug]==source for plug,source in stable.items()))
        self.assertEqual(self.cmds.getAttr(den+'.secondTerm'),1e-8)
        self.assertFalse(self.cmds.getAttr(self.joint+'.armUpWeight',lock=True))
        self.assertFalse(any(call[0]=='setAttr' and 'lock' in call[3] and call[1].rsplit('.',1)[0] in (self.result['cone'],self.joint) for call in self.cmds.calls))

    def test_divide_repair_reconnects_a_missing_guard_input(self):
        self.build();self.capture();den,node=self._legacy_division();self.cmds.disconnectAttr(den+'.outColorR',node+'.input2X')
        self.cmds.setAttr(node+'.input2X',0);self.ns['repair_pose_driver_division'](self.result['group'])
        self.assertEqual(self.cmds.inputs[node+'.input2X'],self.ns['_pd_node'](self.read()['normalization_divisor'])+'.outputR')

    def test_divide_repair_rejects_external_denominator_driver_before_changes(self):
        self.build();self.capture();den,node=self._legacy_division();external=self.cmds.add_node('divisionExternal','network')
        self.cmds.disconnectAttr(den+'.outColorR',node+'.input2X');self.cmds.connectAttr(external+'.output',node+'.input2X')
        before=dict(self.cmds.inputs);self.cmds.calls.clear()
        with self.assertRaisesRegex(ValueError,'another driver'):self.ns['repair_pose_driver_division'](self.result['group'])
        self.assertEqual(self.cmds.inputs,before);self.assertFalse(any(call[0]=='setAttr' for call in self.cmds.calls))

    def test_divide_repair_rejects_locked_guard_setting_before_changes(self):
        self.build();self.capture();den,node=self._legacy_division();self.cmds.setAttr(den+'.secondTerm',lock=True);self.cmds.calls.clear()
        with self.assertRaisesRegex(ValueError,'locked or driven'):self.ns['repair_pose_driver_division'](self.result['group'])
        self.assertFalse(any(call[0]=='setAttr' for call in self.cmds.calls))

    def test_divide_repair_leaves_custom_unused_channel_consumers_alone(self):
        self.build();self.capture();den,node=self._legacy_division();external=self.cmds.add_node('divisionUnusedConsumer','network')
        self.cmds.connectAttr(node+'.outputY',external+'.input');before=dict(self.cmds.inputs)
        with self.assertRaisesRegex(ValueError,'custom consumers'):self.ns['repair_pose_driver_division'](self.result['group'])
        self.assertEqual(self.cmds.inputs,before)

    def test_divide_repair_failure_restores_guard_values_and_operations(self):
        self.build();self.capture();den,node=self._legacy_division();before=dict(self.cmds.inputs);original=self.cmds.setAttr;raised=[]
        def fail(plug,*values,**kwargs):
            if plug==den+'.secondTerm' and values==(1e-8,) and not raised:
                raised.append(1);raise RuntimeError('repair setting failed')
            return original(plug,*values,**kwargs)
        self.cmds.setAttr=fail
        with self.assertRaisesRegex(RuntimeError,'repair setting failed'):self.ns['repair_pose_driver_division'](self.result['group'])
        self.assertEqual(self.cmds.getAttr(den+'.secondTerm'),0);self.assertEqual(self.cmds.getAttr(den+'.colorIfFalseR'),1)
        self.assertEqual(self.cmds.getAttr(node+'.operation'),2);self.assertEqual(self.cmds.getAttr(node+'.input2Y'),0)
        self.assertEqual(self.cmds.inputs,before)

    def test_divide_repair_is_idempotent_without_extra_attribute_writes(self):
        self.build();self.capture();self._legacy_division();self.ns['repair_pose_driver_division'](self.result['group']);self.cmds.calls.clear()
        self.assertFalse(self.ns['repair_pose_driver_division'](self.result['group'])['changed'])
        self.assertFalse(any(call[0]=='setAttr' for call in self.cmds.calls))

    def test_divide_repair_accepts_native_float_rounding_as_already_protected(self):
        self.build();self.capture();den=self.ns['_pd_node'](self.read()['denominator'])
        for attr in ('secondTerm','colorIfFalseR'):self.cmds.setAttr(den+'.'+attr,9.99999993922529e-9)
        self.cmds.calls.clear();self.assertFalse(self.ns['repair_pose_driver_division'](self.result['group'])['changed'])
        self.assertFalse(any(call[0]=='setAttr' for call in self.cmds.calls))

    def test_divide_repair_rejects_referenced_owned_nodes(self):
        self.build();self.capture();den,node=self._legacy_division();self.cmds.nodes[node]['referenced']=True
        with self.assertRaisesRegex(ValueError,'locked or referenced'):self.ns['repair_pose_driver_division'](self.result['group'])


    def test_scaled_normalization_factory_wires_a_divisor_clamped_to_one(self):
        self.build();pose=self.capture();state=self.read();node=self._normalizer()
        scaled=self.ns['_pd_node'](state['normalization_sum']);divisor=self.ns['_pd_node'](state['normalization_divisor'])
        numerator=self.ns['_pd_node'](pose['normalization_numerator'])
        self.assertEqual(self.cmds.getAttr(divisor+'.minR'),1)
        self.assertEqual(self.cmds.getAttr(scaled+'.input2X'),1e8)
        self.assertEqual(self.cmds.getAttr(numerator+'.input2X'),1e8)
        self.assertEqual(self.cmds.inputs[node+'.input2X'],divisor+'.outputR')
        self.assertEqual(self.cmds.inputs[node+'.input1X'],numerator+'.outputX')
        self.assertEqual(self.cmds.inputs[divisor+'.inputR'],scaled+'.outputX')

    def test_scaled_normalization_float32_divisor_never_approaches_zero(self):
        import struct,math
        self.build();pose=self.capture();state=self.read();normalizer=self._normalizer()
        raw=self.cmds.inputs[self.result['cone']+'.armUpWeightRaw'];total=self.ns['_pd_node'](state['sum'])+'.output1D'
        def f32(v):return struct.unpack('f',struct.pack('f',v))[0]
        def evaluate(plug,sources):
            if plug in sources:return f32(sources[plug])
            if plug in self.cmds.inputs:return evaluate(self.cmds.inputs[plug],sources)
            node,attr=plug.rsplit('.',1);kind=self.cmds.nodeType(node)
            if kind=='multiplyDivide' and attr=='outputX':
                a=evaluate(node+'.input1X',sources);b=evaluate(node+'.input2X',sources)
                if self.cmds.getAttr(node+'.operation')==2:
                    self.assertGreaterEqual(b,1.);return f32(a/b)
                return f32(a*b)
            if kind=='clamp' and attr=='outputR':return f32(max(self.cmds.getAttr(node+'.minR'),min(self.cmds.getAttr(node+'.maxR'),evaluate(node+'.inputR',sources))))
            return f32(self.cmds.getAttr(plug))
        for weight in (0.,1e-40,1e-12,1e-8,1e-7,1e-6,1e-4,.25,1.):
            result=evaluate(normalizer+'.outputX',{raw:weight,total:weight})
            self.assertTrue(math.isfinite(result));self.assertAlmostEqual(result,weight/max(weight,1e-8),delta=2e-7)

    def test_scaled_legacy_repair_records_owned_nodes_and_keeps_normalizer_identity(self):
        self.build();self.capture();den,node=self._legacy_division();identity=self.ns['_pd_uuid'](node)
        self.ns['repair_pose_driver_division'](self.result['group']);state=self.read();pose=state['poses'][0]
        self.assertEqual(pose['normalizer'],identity);self.assertIn(pose['normalization_numerator'],pose['nodes'])
        for key in ('normalization_divisor','normalization_sum'):
            self.assertIn(state[key],state['members']);self.assertNotIn(state[key],pose['nodes'])

    def test_scaled_legacy_repair_connection_failure_cleans_new_nodes_and_restores_graph(self):
        self.build();self.capture();den,node=self._legacy_division();before=set(self.cmds.nodes);links=dict(self.cmds.inputs);state=self.read()
        connect=self.cmds.connectAttr;failed=[]
        def fail(a,b):
            if b==node+'.input2X' and 'normalizationDivisor' in a and not failed:
                failed.append(1);raise RuntimeError('divisor connect failed')
            return connect(a,b)
        self.cmds.connectAttr=fail
        with self.assertRaisesRegex(RuntimeError,'divisor connect failed'):self.ns['repair_pose_driver_division'](self.result['group'])
        self.assertEqual(set(self.cmds.nodes),before);self.assertEqual(self.cmds.inputs,links);self.assertEqual(self.read(),state)
        self.assertEqual(self.cmds.getAttr(node+'.operation'),2)

    def test_scaled_legacy_repair_final_enable_failure_restores_metadata(self):
        self.build();self.capture();den,node=self._legacy_division();before=set(self.cmds.nodes);links=dict(self.cmds.inputs);state=self.read()
        setter=self.cmds.setAttr;failed=[]
        def fail(plug,*args,**kwargs):
            if plug==node+'.operation' and args==(2,) and not failed:
                failed.append(1);raise RuntimeError('enable failed')
            return setter(plug,*args,**kwargs)
        self.cmds.setAttr=fail
        with self.assertRaisesRegex(RuntimeError,'enable failed'):self.ns['repair_pose_driver_division'](self.result['group'])
        self.assertEqual(set(self.cmds.nodes),before);self.assertEqual(self.cmds.inputs,links);self.assertEqual(self.read(),state)

    def test_scaled_repair_rejects_foreign_raw_weight_input(self):
        self.build();self.capture();den,node=self._legacy_division();external=self.cmds.add_node('foreignNumerator','network')
        old=self.cmds.inputs[node+'.input1X'];self.cmds.disconnectAttr(old,node+'.input1X');self.cmds.connectAttr(external+'.output',node+'.input1X')
        before=set(self.cmds.nodes);links=dict(self.cmds.inputs)
        with self.assertRaisesRegex(ValueError,'another driver'):self.ns['repair_pose_driver_division'](self.result['group'])
        self.assertEqual(set(self.cmds.nodes),before);self.assertEqual(self.cmds.inputs,links)

    def test_scaled_repair_pose_removal_keeps_shared_divisor_for_other_poses(self):
        self.build();first=self.capture();self._legacy_division();self.ns['repair_pose_driver_division'](self.result['group'])
        first=self.read()['poses'][0];second=self.capture('other');state=self.read()
        self.ns['remove_pose_driver_pose'](self.result['group'],first['id']);after=self.read()
        self.assertIn(state['normalization_divisor'],after['members'])
        self.assertIsNone(self.ns['_guide_ik_resolve_uuid'](first['normalization_numerator']))
        self.assertTrue(self.ns['_pd_node'](second['normalization_numerator']))

    def test_scaled_repair_system_removal_leaves_no_new_owned_nodes(self):
        self.build();self.capture();self._legacy_division();self.ns['repair_pose_driver_division'](self.result['group'])
        state=self.read();self.ns['remove_pose_driver'](self.result['group'])
        for identity in state['members']:self.assertIsNone(self.ns['_guide_ik_resolve_uuid'](identity))
        self.assertIn(self.joint,self.cmds.nodes)

    def test_scaled_capture_upgrades_legacy_graph_before_adding_pose(self):
        self.build();self.capture();den,node=self._legacy_division();original=self.ns['_pd_uuid'](node)
        second=self.capture('newPose');state=self.read()
        self.assertTrue(state.get('normalization_divisor'));self.assertEqual(state['poses'][0]['normalizer'],original)
        self.assertIn(second['normalization_numerator'],second['nodes'])

    def test_scaled_invalid_capture_does_not_upgrade_legacy_graph(self):
        self.build();self.capture();self._legacy_division();state=self.read();before=set(self.cmds.nodes)
        with self.assertRaises(ValueError):self.capture('invalid',radius=0)
        self.assertEqual(self.read(),state);self.assertEqual(set(self.cmds.nodes),before)

    def test_scaled_normalization_metadata_rejects_foreign_base_nodes(self):
        self.build();self.capture();state=self.read();state['normalization_divisor']=state['joint']
        self.cmds.setAttr(self.result['group']+'.rtkPoseDriverState',json.dumps(state),type='string')
        with self.assertRaisesRegex(ValueError,'normalization ownership'):self.read()

    def test_default_linear_auto_radius_y70_has_half_weight_at_35(self):
        import math
        self.build()
        self.rotate_direction(70)
        pose = self.capture_rotation(name='up')
        state = self.read()
        self.assertEqual(state['falloff_mode'],'linear')
        self.assertEqual(pose['radius_mode'],'auto')
        self.assertAlmostEqual(pose['radius'],70)
        self.assertEqual(self.cmds.getAttr(self.result['cone']+'.normalize'),0)
        linear = self.ns['_pd_node'](pose['linear_ramp'])
        self.assertAlmostEqual(self.cmds.getAttr(linear+'.inputMax'),math.radians(70))
        self.assertEqual(self.cmds.getAttr(self.ns['_pd_node'](pose['falloff_blend'])+'.blender'),1)
        targets = [{'direction':(math.cos(math.radians(70)),math.sin(math.radians(70)),0),'radius':pose['radius']}]
        for angle,expected in ((0,0),(17.5,.25),(35,.5),(52.5,.75),(70,1)):
            live = (math.cos(math.radians(angle)),math.sin(math.radians(angle)),0)
            result = self.ns['pose_driver_weights'](live,targets)
            self.assertAlmostEqual(result['raw'][0],expected)
            self.assertAlmostEqual(result['weights'][0],expected)

    def test_auto_radius_uses_default_not_nearest_pose_or_minimum_spacing(self):
        self.build()
        self.rotate_direction(20)
        first = self.capture_rotation(name='near')
        self.rotate_direction(70)
        second = self.capture_rotation(name='far',minimum_angle=30)
        self.assertAlmostEqual(first['radius'],20)
        self.assertAlmostEqual(second['radius'],70)

    def test_object_auto_radius_uses_target_not_current_joint(self):
        import math
        self.build()
        self.rotate_direction(110)
        target = self.cmds.add_node('|targetDirection','transform')
        self.cmds.xform(target,translation=(3+10*math.cos(math.radians(40)),2+10*math.sin(math.radians(40)),0))
        pose = self.ns['add_pose_driver_pose'](self.result['group'],'target',center=target)
        self.assertAlmostEqual(pose['radius'],40)
        self.assertEqual(pose['radius_mode'],'auto')
        self.assertEqual(pose['target_object'],self.ns['_pd_uuid'](target))

    def test_auto_radius_negative_cone_axis(self):
        self.build(axis=-1)
        self.rotate_direction(-70)
        pose = self.capture_rotation(name='negative')
        self.assertAlmostEqual(pose['radius'],70)

    def test_auto_radius_uses_same_scaled_rotated_frame_as_graph(self):
        import math
        self.build()
        state = self.read()
        frame = self.result['frame']
        matrix = [0,2,0,0, -3,0,0,0, 0,0,.5,0, 3,2,0,1]
        self.cmds.nodes[frame]['matrix'] = matrix
        state['default_direction_local'] = [1,0,0]
        local = (math.cos(math.radians(70)),math.sin(math.radians(70)),0)
        ray = self.ns['_pd_frame_vector'](matrix,local)
        position = self.ns['pose_driver_unit_center']((3,2,0),[a+b for a,b in zip((3,2,0),ray)])
        self.assertAlmostEqual(self.ns['_pd_auto_radius'](state,position),70)
        self.assertGreater(abs(self.ns['_pd_vector_angle']((0,1,0),ray)-70),1)

    def test_auto_radius_uses_explicitly_reset_default(self):
        self.build()
        self.rotate_direction(20)
        self.ns['set_pose_driver_default_rotation'](self.result['group'])
        self.rotate_direction(70)
        self.assertAlmostEqual(self.capture_rotation(name='relative')['radius'],50)

    def test_auto_recapture_remeasures_and_keeps_nodes_outputs_sdk(self):
        self.build()
        self.rotate_direction(70)
        pose = self.capture_rotation(name='up')
        curve = self.cmds.add_node('autoSDK','animCurveUU')
        self.cmds.connectAttr(self.joint+'.upWeight',curve+'.input')
        nodes,links = set(self.cmds.nodes),dict(self.cmds.inputs)
        self.rotate_direction(110)
        updated = self.capture_rotation(pose_id=pose['id'])
        self.assertAlmostEqual(updated['radius'],110)
        self.assertEqual(updated['radius_mode'],'auto')
        self.assertEqual(updated['id'],pose['id'])
        self.assertEqual(updated['nodes'],pose['nodes'])
        self.assertEqual(set(self.cmds.nodes),nodes)
        self.assertEqual(self.cmds.inputs,links)
        self.assertFalse(self.cmds.getAttr(self.joint+'.upWeight',lock=True))

    def test_manual_override_survives_recapture_with_no_radius_argument(self):
        self.build()
        self.rotate_direction(70)
        pose = self.capture_rotation(name='custom',radius=45)
        self.rotate_direction(110)
        updated = self.capture_rotation(pose_id=pose['id'])
        self.assertEqual(updated['radius'],45)
        self.assertEqual(updated['radius_mode'],'manual')

    def test_switch_manual_to_auto_uses_saved_center_then_manual_freezes_angle(self):
        self.build()
        self.rotate_direction(70)
        pose = self.capture_rotation(name='custom',radius=45)
        self.rotate_direction(130)
        updated = self.ns['update_pose_driver_pose'](self.result['group'],pose['id'],radius='auto')
        self.assertAlmostEqual(updated['radius'],70)
        self.assertEqual(updated['radius_mode'],'auto')
        updated = self.ns['update_pose_driver_pose'](self.result['group'],pose['id'],radius=33)
        self.assertEqual(updated['radius_mode'],'manual')
        updated = self.ns['update_pose_driver_pose'](self.result['group'],pose['id'],recapture=True)
        self.assertEqual(updated['radius'],33)

    def test_auto_radius_update_remeasures_after_default_changes(self):
        self.build()
        self.rotate_direction(70)
        pose = self.capture_rotation(name='up')
        self.rotate_direction(20)
        self.ns['set_pose_driver_default_rotation'](self.result['group'])
        self.assertAlmostEqual(self.read()['poses'][0]['radius'],70)
        updated = self.ns['update_pose_driver_pose'](self.result['group'],pose['id'])
        self.assertAlmostEqual(updated['radius'],50)

    def test_legacy_setup_keeps_smooth_mode_and_unmarked_manual_angles(self):
        self.build()
        state = self.read()
        state.pop('falloff_mode')
        state.pop('default_direction_local')
        self.ns['_pd_write'](self.result['group'],state)
        self.rotate_direction(70)
        pose = self.capture_rotation(name='legacy',radius=45)
        self.assertNotIn('linear_ramp',pose)
        state = self.read()
        state['poses'][0].pop('radius_mode')
        self.ns['_pd_write'](self.result['group'],state)
        self.rotate_direction(110)
        updated = self.ns['update_pose_driver_pose'](self.result['group'],pose['id'],recapture=True)
        self.assertEqual(updated['radius'],45)
        self.assertEqual(updated['radius_mode'],'manual')
        self.assertNotIn('falloff_mode',self.read())
        # Legacy default frame remains valid for explicitly opting into auto.
        updated = self.ns['update_pose_driver_pose'](self.result['group'],pose['id'],radius='auto')
        self.assertAlmostEqual(updated['radius'],110)

    def test_auto_default_direction_rejects_before_any_scene_changes(self):
        import copy
        self.build()
        before,links = copy.deepcopy(self.cmds.nodes),dict(self.cmds.inputs)
        selection = self.cmds.selection[:]
        with self.assertRaisesRegex(ValueError,'different from the default'):
            self.ns['add_pose_driver_pose'](self.result['group'],'sameDefault')
        self.assertEqual(self.cmds.nodes,before)
        self.assertEqual(self.cmds.inputs,links)
        self.assertEqual(self.cmds.selection,selection)
        self.assertEqual(self.ns['add_pose_driver_pose'](self.result['group'],'rest',radius=45)['radius_mode'],'manual')

    def test_auto_radius_near_default_floor_and_opposite_180(self):
        self.build()
        self.rotate_direction(.05)
        small = self.capture_rotation(name='small',minimum_angle=0)
        self.assertEqual(small['radius'],.1)
        self.rotate_direction(180)
        opposite = self.capture_rotation(name='opposite')
        self.assertEqual(opposite['radius'],180)
        self.assertEqual(self.ns['pose_driver_weights']((1,0,0),[{'direction':(-1,0,0),'radius':180}])['weights'],[0])

    def test_auto_mirror_remeasures_destination_angle_and_updates_same_outputs(self):
        import math
        self.mirror_fixture()
        source = self.read()['poses'][0]
        self.ns['update_pose_driver_pose'](self.result['group'],source['id'],radius='auto')
        self.cmds.xform('|pose_R',translation=(-3-math.cos(math.radians(60)),2+math.sin(math.radians(60)),0))
        result = self.mirror()
        state = self.ns['_pd_read'](result['group'])[1]
        pose = state['poses'][0]
        self.assertAlmostEqual(pose['radius'],60)
        self.assertAlmostEqual(self.read()['poses'][0]['radius'],90)
        self.assertEqual(pose['radius_mode'],'auto')
        nodes,links = set(self.cmds.nodes),dict(self.cmds.inputs)
        self.cmds.xform('|pose_R',translation=(-3-math.cos(math.radians(30)),2+math.sin(math.radians(30)),0))
        self.mirror()
        updated = self.ns['_pd_read'](result['group'])[1]['poses'][0]
        self.assertAlmostEqual(updated['radius'],30)
        self.assertEqual(updated['id'],pose['id'])
        self.assertEqual(updated['nodes'],pose['nodes'])
        self.assertEqual(set(self.cmds.nodes),nodes)
        self.assertEqual(self.cmds.inputs,links)

    def test_failed_auto_update_restores_angle_mode_center_and_graph(self):
        import copy
        self.build()
        pose = self.capture()
        target = self.cmds.add_node('|newTarget','transform')
        self.cmds.xform(target,translation=(3,10,0))
        before,links = copy.deepcopy(self.cmds.nodes),dict(self.cmds.inputs)
        write = self.ns['_pd_write']
        calls = []
        def fail_once(*args):
            calls.append(True)
            if len(calls) == 1:
                raise RuntimeError('metadata write failed')
            return write(*args)
        self.ns['_pd_write'] = fail_once
        with self.assertRaisesRegex(RuntimeError,'metadata write failed'):
            self.ns['update_pose_driver_pose'](self.result['group'],pose['id'],radius='auto',center=target)
        self.assertEqual(self.cmds.nodes,before)
        self.assertEqual(self.cmds.inputs,links)

    def test_invalid_auto_radius_mode_is_controlled_metadata_error(self):
        self.build()
        self.capture()
        state = self.read()
        state['poses'][0]['radius_mode'] = 'unexpected'
        self.ns['_pd_write'](self.result['group'],state)
        with self.assertRaisesRegex(ValueError,'falloff angle mode'):
            self.read()

    def test_ui_auto_capture_routes_object_and_joint_with_measured_angles(self):
        self.build()
        target = self.cmds.add_node('|autoUITarget','transform')
        self.cmds.xform(target,translation=(3,12,0))
        _messages,errors = self._ui_capture(target,name='object',automatic=True)
        self.assertEqual(errors,[])
        self.assertAlmostEqual(self.read()['poses'][0]['radius'],90)
        self.rotate_direction(70)
        _messages,errors = self._ui_capture('',name='joint',automatic=True)
        self.assertEqual(errors,[])
        self.assertAlmostEqual(self.read()['poses'][1]['radius'],70)
        self.assertEqual(self.read()['poses'][1]['radius_mode'],'auto')

    def controller_fixture(self, build=True):
        import math
        controller = self.cmds.add_node('|driver_CTRL','transform')
        data = self.cmds.nodes[controller]
        data['attrs'].update({base+axis:(1 if base=='scale' else 0) for base in ('translate','rotate','scale') for axis in 'XYZ'})
        data['attrs'].update(rotateOrder=0,stretch=1.,space=0,visibility=True)
        data['keyable_attrs'] = set(data['attrs'])-{'message','rotateOrder'}
        data['attr_types'] = {'space':'enum','visibility':'bool'}
        identity = data['uuid']
        original = self.cmds.setAttr
        self.controller_moves_joint = True
        def set_attr(plug,*values,**kwargs):
            result = original(plug,*values,**kwargs)
            node,attribute = plug.rsplit('.',1)
            if (values and attribute=='rotateZ' and self.cmds.nodes[node]['uuid']==identity
                    and self.controller_moves_joint):
                value = math.degrees(values[0]) if self.cmds.currentUnit(query=True,angle=True)=='rad' else values[0]
                self.rotate_direction(value)
            return result
        self.cmds.setAttr = set_attr
        if build:
            self.build(driver_controller=controller)
        return controller

    def controller_pose(self, controller, angle=70, name='up', **kw):
        self.cmds.setAttr(controller+'.rotateZ',angle)
        return self.capture_rotation(name=name,**kw)

    def controller_undo(self):
        import copy
        original = self.cmds.undoInfo
        state = {'count':0}
        def info(**kw):
            if kw.get('openChunk'):
                state.update(name=kw['chunkName'],nodes=copy.deepcopy(self.cmds.nodes),inputs=dict(self.cmds.inputs),selection=self.cmds.selection[:])
            if kw.get('query') and kw.get('undoName'):
                return state.get('name')
            return original(**kw)
        def undo():
            self.cmds.nodes = copy.deepcopy(state['nodes'])
            self.cmds.inputs = dict(state['inputs'])
            self.cmds.selection = state['selection'][:]
            state['count'] += 1
        self.cmds.undoInfo,self.cmds.undo = info,undo
        return state

    def test_controller_binding_caches_default_and_never_owns_controller(self):
        controller = self.controller_fixture()
        state = self.read()
        self.assertEqual(state['driver_controller'],self.ns['_pd_uuid'](controller))
        self.assertEqual(state['default_controller_pose']['channels']['rotateZ']['value'],0)
        self.assertNotIn(state['driver_controller'],state['members'])
        self.ns['remove_pose_driver'](self.result['group'])
        self.assertTrue(self.cmds.objExists(controller))

    def test_controller_distinct_pose_caches_restore_channels_and_keep_graph(self):
        controller = self.controller_fixture()
        self.cmds.setAttr(controller+'.stretch',1.5)
        first = self.controller_pose(controller,70,'up')
        self.cmds.setAttr(controller+'.stretch',2.)
        second = self.controller_pose(controller,110,'high')
        links,owned = dict(self.cmds.inputs),self.read()['members'][:]
        result = self.ns['goto_pose_driver_pose'](self.result['group'],first['id'])
        self.assertEqual(result['controller'],controller)
        self.assertEqual(self.cmds.getAttr(controller+'.rotateZ'),70)
        self.assertEqual(self.cmds.getAttr(controller+'.stretch'),1.5)
        self.ns['goto_pose_driver_pose'](self.result['group'],second['id'])
        self.assertEqual(self.cmds.getAttr(controller+'.rotateZ'),110)
        self.assertEqual(self.cmds.getAttr(controller+'.stretch'),2.)
        self.assertEqual(self.cmds.inputs,links)
        self.assertEqual(self.read()['members'],owned)

    def test_controller_go_default_restores_saved_values_and_is_undoable(self):
        import copy
        controller = self.controller_fixture()
        self.controller_pose(controller)
        self.cmds.setAttr(controller+'.space',2)
        before = copy.deepcopy(self.cmds.nodes)
        undo = self.controller_undo()
        self.ns['goto_pose_driver_pose'](self.result['group'])
        self.assertEqual(self.cmds.getAttr(controller+'.rotateZ'),0)
        self.assertEqual(self.cmds.getAttr(controller+'.space'),0)
        self.cmds.undo()
        self.assertEqual(self.cmds.nodes,before)
        self.assertEqual(undo['count'],1)

    def test_controller_cache_survives_rename_and_serialized_scene_state(self):
        controller = self.controller_fixture()
        pose = self.controller_pose(controller)
        controller = self.cmds.rename(controller,'renamed_CTRL')
        self.cmds.setAttr(controller+'.rotateZ',0)
        state = json.loads(self.cmds.getAttr(self.result['group']+'.rtkPoseDriverState'))
        self.ns['_pd_write'](self.result['group'],json.loads(json.dumps(state)))
        self.assertEqual(self.ns['goto_pose_driver_pose'](self.result['group'],pose['id'])['controller'],controller)
        self.assertEqual(self.cmds.getAttr(controller+'.rotateZ'),70)

    def test_controller_can_cache_existing_pose_without_changing_weight_graph(self):
        controller = self.controller_fixture(build=False)
        self.build()
        pose = self.capture()
        self.ns['set_pose_driver_controller'](self.result['group'],controller)
        self.assertNotIn('default_controller_pose',self.read())
        links,nodes = dict(self.cmds.inputs),set(self.cmds.nodes)
        self.ns['cache_pose_driver_controller_pose'](self.result['group'],pose['id'])
        self.cmds.setAttr(controller+'.rotateZ',70)
        self.ns['goto_pose_driver_pose'](self.result['group'],pose['id'])
        self.assertEqual(self.cmds.getAttr(controller+'.rotateZ'),0)
        self.assertEqual(self.cmds.inputs,links)
        self.assertEqual(set(self.cmds.nodes),nodes)

    def test_controller_cache_rejects_unmatched_target_before_metadata_edits(self):
        controller = self.controller_fixture()
        pose = self.controller_pose(controller)
        self.cmds.setAttr(controller+'.rotateZ',0)
        before = self.read()
        with self.assertRaisesRegex(ValueError,'Pose the joint at this target'):
            self.ns['cache_pose_driver_controller_pose'](self.result['group'],pose['id'])
        self.assertEqual(self.read(),before)

    def test_controller_object_pose_not_reached_has_no_misleading_cache(self):
        self.controller_fixture()
        target = self.cmds.add_node('|targetObject','transform')
        self.cmds.xform(target,translation=(3,12,0))
        pose = self.ns['add_pose_driver_pose'](self.result['group'],'external',center=target)
        self.assertNotIn('controller_pose',pose)
        with self.assertRaisesRegex(ValueError,'No controller pose is cached'):
            self.ns['goto_pose_driver_pose'](self.result['group'],pose['id'])

    def test_controller_recapture_updates_cache_without_replacing_graph(self):
        controller = self.controller_fixture()
        pose = self.controller_pose(controller)
        links = dict(self.cmds.inputs)
        self.cmds.setAttr(controller+'.rotateZ',110)
        self.cmds.setAttr(controller+'.stretch',1.7)
        updated = self.capture_rotation(pose_id=pose['id'])
        self.assertEqual(updated['controller_pose']['channels']['rotateZ']['value'],110)
        self.assertEqual(updated['controller_pose']['channels']['stretch']['value'],1.7)
        self.assertEqual(updated['nodes'],pose['nodes'])
        self.assertEqual(self.cmds.inputs,links)

    def test_controller_angle_only_ui_update_preserves_away_pose_cache(self):
        controller = self.controller_fixture()
        pose = self.controller_pose(controller)
        self.cmds.setAttr(controller+'.rotateZ',0)
        updated = self.ns['update_pose_driver_pose'](self.result['group'],pose['id'],radius=50,center=self.ns['_pd_node'](pose['center']))
        self.assertEqual(updated['controller_pose'],pose['controller_pose'])
        self.assertEqual(updated['radius'],50)

    def test_controller_changed_target_clears_obsolete_cache(self):
        controller = self.controller_fixture()
        pose = self.controller_pose(controller)
        target = self.cmds.add_node('|targetObject','transform')
        self.cmds.xform(target,translation=(3,12,0))
        updated = self.ns['update_pose_driver_pose'](self.result['group'],pose['id'],center=target)
        self.assertNotIn('controller_pose',updated)

    def test_controller_changed_binding_preserves_pose_caches_and_clears_default(self):
        controller = self.controller_fixture()
        pose = self.controller_pose(controller)
        self.ns['set_pose_driver_controller'](self.result['group'])
        self.assertNotIn('default_controller_pose',self.read())
        self.assertEqual(self.read()['poses'][0]['controller_pose'],pose['controller_pose'])
        self.cmds.setAttr(controller+'.rotateZ',0)
        self.ns['goto_pose_driver_pose'](self.result['group'],pose['id'])
        self.assertEqual(self.cmds.getAttr(controller+'.rotateZ'),70)

    def test_controller_deleted_node_never_resolves_by_reused_name(self):
        controller = self.controller_fixture()
        pose = self.controller_pose(controller)
        self.cmds.delete(controller)
        replacement = self.cmds.add_node(controller,'transform')
        with self.assertRaisesRegex(ValueError,'missing'):
            self.ns['goto_pose_driver_pose'](self.result['group'],pose['id'])
        before = set(self.cmds.nodes)
        self.rotate_direction(110)
        with self.assertRaisesRegex(ValueError,'saved driver controller is missing'):
            self.capture_rotation(name='new')
        self.assertEqual(set(self.cmds.nodes),before)
        self.assertEqual(self.cmds.nodes[replacement]['attrs'],{'message':None})

    def test_controller_locked_compound_stops_all_writes(self):
        import copy
        controller = self.controller_fixture()
        pose = self.controller_pose(controller)
        self.cmds.setAttr(controller+'.rotateZ',0)
        self.cmds.setAttr(controller+'.rotate',lock=True)
        before = copy.deepcopy(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'locked'):
            self.ns['goto_pose_driver_pose'](self.result['group'],pose['id'])
        self.assertEqual(self.cmds.nodes,before)

    def test_controller_animation_sdk_and_constraint_inputs_are_preserved(self):
        import copy
        controller = self.controller_fixture()
        pose = self.controller_pose(controller)
        self.cmds.setAttr(controller+'.rotateZ',0)
        for kind,attribute in (('animCurveTA','rotateZ'),('animCurveUU','stretch'),('orientConstraint','rotate')):
            with self.subTest(kind=kind):
                source = self.cmds.add_node('incoming_'+kind,kind)
                self.cmds.connectAttr(source+'.output',controller+'.'+attribute)
                before,links = copy.deepcopy(self.cmds.nodes),dict(self.cmds.inputs)
                with self.assertRaisesRegex(ValueError,'animated or driven'):
                    self.ns['goto_pose_driver_pose'](self.result['group'],pose['id'])
                self.assertEqual(self.cmds.nodes,before)
                self.assertEqual(self.cmds.inputs,links)
                self.cmds.disconnectAttr(source+'.output',controller+'.'+attribute)

    def test_controller_parent_order_and_channel_schema_changes_stop_restore(self):
        controller = self.controller_fixture()
        pose = self.controller_pose(controller)
        self.cmds.setAttr(controller+'.rotateOrder',1)
        with self.assertRaisesRegex(ValueError,'parent or rotation order'):
            self.ns['goto_pose_driver_pose'](self.result['group'],pose['id'])
        self.cmds.setAttr(controller+'.rotateOrder',0)
        controller = self.cmds.parent(controller,self.cmds.joints[0])[0]
        with self.assertRaisesRegex(ValueError,'parent or rotation order'):
            self.ns['goto_pose_driver_pose'](self.result['group'],pose['id'])
        self.cmds.nodes[controller]['attr_types']['stretch']='bool'
        self.cmds.nodes[controller]['attrs']['rotateOrder']=0
        state = self.read()
        state['poses'][0]['controller_pose']['parent']=self.ns['_pd_uuid'](self.cmds.joints[0])
        self.ns['_pd_write'](self.result['group'],state)
        with self.assertRaisesRegex(ValueError,'changed type'):
            self.ns['goto_pose_driver_pose'](self.result['group'],pose['id'])

    def test_controller_requires_undo_and_rejects_nested_restore(self):
        controller = self.controller_fixture()
        pose = self.controller_pose(controller)
        self.cmds.enabled = False
        with self.assertRaisesRegex(ValueError,'Enable Maya Undo'):
            self.ns['goto_pose_driver_pose'](self.result['group'],pose['id'])
        self.cmds.enabled = True
        self.ns['_TOOL_UNDO_DEPTH']=1
        with self.assertRaisesRegex(ValueError,'outside another tool action'):
            self.ns['goto_pose_driver_pose'](self.result['group'],pose['id'])

    def test_controller_failed_restore_rolls_back_all_channels(self):
        import copy
        controller = self.controller_fixture()
        pose = self.controller_pose(controller)
        self.cmds.setAttr(controller+'.rotateZ',0)
        before = copy.deepcopy(self.cmds.nodes)
        undo = self.controller_undo()
        original = self.cmds.setAttr
        def fail(plug,*args,**kw):
            if plug==controller+'.translateY': raise RuntimeError('setter failed')
            return original(plug,*args,**kw)
        self.cmds.setAttr=fail
        with self.assertRaisesRegex(RuntimeError,'rolled back'):
            self.ns['goto_pose_driver_pose'](self.result['group'],pose['id'])
        self.assertEqual(self.cmds.nodes,before)
        self.assertEqual(undo['count'],1)

    def test_controller_no_longer_drives_target_rolls_back_the_restore(self):
        import copy
        controller = self.controller_fixture()
        pose = self.controller_pose(controller)
        self.cmds.setAttr(controller+'.rotateZ',0)
        self.controller_moves_joint=False
        before = copy.deepcopy(self.cmds.nodes)
        undo=self.controller_undo()
        with self.assertRaisesRegex(RuntimeError,'no longer reproduces'):
            self.ns['goto_pose_driver_pose'](self.result['group'],pose['id'])
        self.assertEqual(self.cmds.nodes,before)
        self.assertEqual(undo['count'],1)

    def test_controller_pose_converts_angle_and_distance_units(self):
        import math
        controller = self.controller_fixture()
        self.cmds.setAttr(controller+'.translateX',2.5)
        pose = self.controller_pose(controller)
        self.cmds.angle_unit='rad'
        self.cmds.linear_unit='m'
        self.cmds.setAttr(controller+'.rotateZ',0)
        self.cmds.setAttr(controller+'.translateX',0)
        self.ns['goto_pose_driver_pose'](self.result['group'],pose['id'])
        self.assertAlmostEqual(self.cmds.getAttr(controller+'.rotateZ'),math.radians(70))
        self.assertAlmostEqual(self.cmds.getAttr(controller+'.translateX'),.025)

    def test_controller_cache_filters_locked_computed_and_non_scalar_channels(self):
        controller=self.controller_fixture()
        self.cmds.setAttr(controller+'.stretch',lock=True)
        self.cmds.nodes[controller]['attrs'].update(computed=.7,label='name',vector=(1,2,3))
        self.cmds.nodes[controller]['keyable_attrs'].update(('computed','label','vector'))
        self.cmds.nodes[controller]['attr_types'].update(label='string',vector='double3')
        source=self.cmds.add_node('computedDriver','multiplyDivide')
        self.cmds.connectAttr(source+'.outputX',controller+'.computed')
        cache=self.ns['_pd_capture_controller'](controller)
        self.assertFalse(set(cache['channels']) & {'stretch','computed','label','vector'})
        self.assertEqual(cache['channels']['space']['type'],'enum')
        self.assertEqual(cache['channels']['visibility']['type'],'bool')
        self.assertTrue(self.cmds.getAttr(controller+'.stretch',lock=True))

    def test_controller_default_reset_caches_current_driver_pose(self):
        controller = self.controller_fixture()
        self.cmds.setAttr(controller+'.rotateZ',35)
        self.ns['set_pose_driver_default_rotation'](self.result['group'])
        self.cmds.setAttr(controller+'.rotateZ',0)
        self.ns['goto_pose_driver_pose'](self.result['group'])
        self.assertEqual(self.cmds.getAttr(controller+'.rotateZ'),35)

    def test_controller_owned_helpers_and_invalid_cache_metadata_reject(self):
        controller = self.controller_fixture()
        with self.assertRaisesRegex(ValueError,'rather than a PoseDriver helper'):
            self.ns['set_pose_driver_controller'](self.result['group'],self.result['cone'])
        pose = self.controller_pose(controller)
        state = self.read()
        state['poses'][0]['controller_pose']['controller']=state['cone']
        self.ns['_pd_write'](self.result['group'],state)
        with self.assertRaisesRegex(ValueError,'Invalid cached controller pose'):
            self.read()

    def test_controller_legacy_pose_requires_cache_and_does_not_invent_values(self):
        self.build()
        pose = self.capture()
        before = self.read()
        with self.assertRaisesRegex(ValueError,'No controller pose is cached'):
            self.ns['goto_pose_driver_pose'](self.result['group'],pose['id'])
        with self.assertRaisesRegex(ValueError,'Get the driver controller first'):
            self.ns['cache_pose_driver_controller_pose'](self.result['group'],pose['id'])
        self.assertEqual(self.read(),before)


class PairConstraintCommands(PoseDriverCommands):
    def getAttr(self,plug,**kw):
        if kw.get('settable'):
            return not super().getAttr(plug,lock=True) and plug not in self.inputs
        return super().getAttr(plug,**kw)

    def _pair(self,kind,driver,driven,options):
        self.calls.append((kind,driver,driven,options))
        if getattr(self,'fail_kind',None) == kind:
            raise RuntimeError('Constraint command failed')
        node = self.add_node(driven+'|'+options['name'].lstrip(':'),kind)
        prefixes = {'parentConstraint':('translate','rotate'),'pointConstraint':('translate',),
                    'orientConstraint':('rotate',),'scaleConstraint':('scale',),'aimConstraint':('rotate',)}[kind]
        for prefix in prefixes:
            for axis in 'XYZ': self.inputs[driven+'.'+prefix+axis] = node+'.constraint'+prefix.title()+axis
        return [node]

    def parentConstraint(self,driver,driven,**kw): return self._pair('parentConstraint',driver,driven,kw)
    def pointConstraint(self,driver,driven,**kw): return self._pair('pointConstraint',driver,driven,kw)
    def orientConstraint(self,driver,driven,**kw): return self._pair('orientConstraint',driver,driven,kw)
    def scaleConstraint(self,driver,driven,**kw): return self._pair('scaleConstraint',driver,driven,kw)
    def aimConstraint(self,driver,driven,**kw): return self._pair('aimConstraint',driver,driven,kw)


class PairConstraintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())

    def setUp(self):
        import math,uuid
        self.cmds = PairConstraintCommands()
        self.driver = self.cmds.add_node('|pairDriver','transform',matrix=self.cmds.matrix(8,2,0),world_position=(8,2,0))
        self.driven = self.cmds.joints[1]
        wanted = {'_begin_tool_undo','_end_tool_undo','_tool_action','_non_undoable_cache_write',
                  '_resolve_hierarchy_root','_guide_ik_uuid','_restore_locator_view_selection',
                  'plan_pair_constraint','create_pair_constraint'}
        nodes = [n for n in self.tree.body if isinstance(n,ast.FunctionDef) and (n.name in wanted or n.name.startswith("_constraint_"))]
        constants = [n for n in self.tree.body if isinstance(n,ast.Assign) and any(getattr(t,'id','')=='_PAIR_CONSTRAINT_TYPES' for t in n.targets)]
        self.ns = {'cmds':self.cmds,'math':math,'uuid':uuid,'wraps':wraps,'contextmanager':contextlib.contextmanager,'_TOOL_UNDO_DEPTH':0}
        exec(compile(ast.Module(body=constants+nodes,type_ignores=[]),'<Pair constraint>','exec'),self.ns)

    def create(self,kind='parent',offset=True):
        return self.ns['create_pair_constraint'](self.driver,self.driven,kind,offset)

    def test_all_constraint_types_wire_driver_to_driven_and_offset(self):
        for kind,commands in self.ns['_PAIR_CONSTRAINT_TYPES'].items():
            with self.subTest(kind=kind):
                self.setUp()
                result = self.create(kind,False)
                self.assertEqual(len(result['constraints']),len(commands))
                for command in commands:
                    call = next(c for c in self.cmds.calls if c[0]==command)
                    self.assertEqual(call[1:3],(self.driver,self.driven))
                    self.assertFalse(call[3]['maintainOffset'])

    def test_maintain_offset_defaults_on_and_one_undo_step(self):
        selected = self.cmds.selection[:]
        result = self.create('parent_scale')
        self.assertTrue(result['maintain_offset'])
        self.assertEqual(self.cmds.chunks,['open','close'])
        self.assertEqual(self.cmds.selection,selected)

    def test_pair_preflight_is_read_only(self):
        before = set(self.cmds.nodes)
        calls = list(self.cmds.calls)
        result = self.ns['plan_pair_constraint'](self.driver,self.driven,'point')
        self.assertEqual(result['commands'],('pointConstraint',))
        self.assertEqual(set(self.cmds.nodes),before)
        self.assertEqual(self.cmds.calls,calls)

    def test_locked_unaffected_channels_do_not_block_point(self):
        self.cmds.setAttr(self.driven+'.rotateX',lock=True)
        self.assertTrue(self.create('point')['constraints'])

    def test_locked_affected_channel_blocks_without_creation(self):
        self.cmds.setAttr(self.driven+'.rotateX',lock=True)
        before = set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'locked'): self.create('orient')
        self.assertEqual(set(self.cmds.nodes),before)

    def test_animation_or_compound_input_not_overwritten(self):
        driver = self.cmds.add_node('animation','animCurveTA')
        for attribute in ('rotateY','rotate'):
            self.cmds.inputs = {self.driven+'.'+attribute:driver+'.output'}
            with self.assertRaisesRegex(ValueError,'incoming connection'): self.create('parent')
            self.assertEqual(self.cmds.inputs[self.driven+'.'+attribute],driver+'.output')

    def test_self_descendant_instance_and_invalid_type_rejected(self):
        with self.assertRaises(ValueError): self.ns['plan_pair_constraint'](self.driven,self.driven)
        with self.assertRaisesRegex(ValueError,'feedback loop'):
            self.ns['plan_pair_constraint'](self.cmds.joints[2],self.driven)
        self.cmds.nodes[self.driven]['instanced'] = True
        with self.assertRaisesRegex(ValueError,'non-instanced'): self.create()
        self.cmds.nodes[self.driven]['instanced'] = False
        with self.assertRaises(ValueError): self.create('invalid')

    def test_repeat_apply_does_not_add_a_second_constraint(self):
        self.create()
        before = set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'incoming connection'): self.create()
        self.assertEqual(set(self.cmds.nodes),before)

    def test_aim_defaults_and_coincident_positions(self):
        result = self.create('aim')
        call = next(c for c in self.cmds.calls if c[0]=='aimConstraint')
        self.assertEqual(call[3]['aimVector'],(1,0,0))
        self.assertEqual(call[3]['worldUpType'],'vector')
        self.setUp()
        self.cmds.xform(self.driver,worldSpace=True,translation=(3,2,0))
        with self.assertRaisesRegex(ValueError,'different world positions'): self.create('aim')

    def test_missing_ambiguous_object_and_disabled_undo_rejected(self):
        with self.assertRaises(ValueError): self.ns['plan_pair_constraint']('missing',self.driven)
        self.cmds.add_node('|other|pairDriver','transform')
        with self.assertRaises(ValueError): self.ns['plan_pair_constraint']('pairDriver',self.driven)
        self.cmds.enabled = False
        with self.assertRaisesRegex(ValueError,'Enable Maya Undo'): self.create()

    def test_parent_scale_failure_rolls_back_everything(self):
        import copy
        before_nodes,before_inputs = copy.deepcopy(self.cmds.nodes),dict(self.cmds.inputs)
        original = self.cmds.undoInfo
        checkpoint = {}
        def info(**kw):
            if kw.get('openChunk'): checkpoint['name'] = kw['chunkName']
            if kw.get('query') and kw.get('undoName'): return checkpoint['name']
            return original(**kw)
        def undo():
            self.cmds.nodes = copy.deepcopy(before_nodes)
            self.cmds.inputs = dict(before_inputs)
        self.cmds.undoInfo,self.cmds.undo = info,undo
        self.cmds.fail_kind = 'scaleConstraint'
        with self.assertRaisesRegex(RuntimeError,'rolled back'): self.create('parent_scale',False)
        self.assertEqual(self.cmds.nodes,before_nodes)
        self.assertEqual(self.cmds.inputs,before_inputs)


class GuideMatchCommands(PairConstraintCommands):
    def duplicate(self, target, **kw):
        import copy
        self.calls.append(('duplicate',target,kw))
        path=target.rsplit('|',1)[0]+'|'+kw['name'].lstrip(':')
        data=copy.deepcopy(self.nodes[target])
        self.add_node(path,data['type'])
        data.pop('uuid')
        self.nodes[path].update(data)
        return [path]

    def matchTransform(self,target,source,**kw):
        self.calls.append(('matchTransform',target,source,kw))
        for enabled,prefix in ((kw.get('position'),'translate'),(kw.get('rotation'),'rotate'),(kw.get('scale'),'scale')):
            if enabled:
                for axis in 'XYZ':
                    self.nodes[target]['attrs'][prefix+axis] = self.nodes[source]['attrs'].get(prefix+axis,0)
        if getattr(self,'fail_match',False):
            raise RuntimeError('Native match failed')


class GuideMatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())

    def setUp(self):
        import math,uuid
        self.cmds = GuideMatchCommands()
        self.source = self.cmds.add_node('|matchSource','transform')
        self.target = self.cmds.joints[1]
        self.cmds.nodes[self.source]['attrs'].update({'translateX':8,'rotateZ':30,'scaleX':2})
        wanted = {'_begin_tool_undo','_end_tool_undo','_tool_action','_non_undoable_cache_write',
                  '_resolve_hierarchy_root','_guide_ik_uuid','_restore_locator_view_selection','match_two_transforms','_guide_match_set_channels'}
        nodes = [n for n in self.tree.body if isinstance(n,ast.FunctionDef) and (n.name in wanted or n.name.startswith("_constraint_"))]
        self.ns = {'cmds':self.cmds,'math':math,'uuid':uuid,'wraps':wraps,'contextmanager':contextlib.contextmanager,'_TOOL_UNDO_DEPTH':0}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<Guide match>','exec'),self.ns)

    def match(self,**kw): return self.ns['match_two_transforms'](self.source,self.target,**kw)

    def test_match_target_to_source_default_flags_and_selection_undo(self):
        source = dict(self.cmds.nodes[self.source]['attrs'])
        selected = self.cmds.selection[:]
        result = self.match()
        call = next(c for c in self.cmds.calls if c[0]=='matchTransform')
        self.assertNotEqual(call[1],self.target)
        self.assertEqual(call[2],self.source)
        self.assertFalse(self.cmds.objExists(call[1]))
        self.assertEqual(call[3],{'position':True,'rotation':True,'scale':False})
        self.assertEqual(self.cmds.nodes[self.source]['attrs'],source)
        self.assertEqual(self.cmds.nodes[self.target]['attrs']['translateX'],8)
        self.assertEqual(self.cmds.chunks,['open','close'])
        self.assertEqual(self.cmds.selection,selected)
        self.assertEqual(result['target'],self.target)
        self.assertEqual(result['method'],'set')
        self.assertTrue(any(c[0]=='setAttr' and c[1]==self.target+'.translateX' for c in self.cmds.calls))

    def test_match_position_only_leaves_locked_rotation_and_scale(self):
        self.cmds.setAttr(self.target+'.rotateZ',lock=True)
        self.cmds.setAttr(self.target+'.scaleX',lock=True)
        before = self.cmds.getAttr(self.target+'.rotateZ')
        self.match(rotation=False)
        self.assertEqual(self.cmds.getAttr(self.target+'.rotateZ'),before)
        self.assertTrue(self.cmds.getAttr(self.target+'.scaleX',lock=True))

    def test_match_scale_only_passes_correct_flags(self):
        self.match(position=False,rotation=False,scale=True)
        call = next(c for c in self.cmds.calls if c[0]=='matchTransform')
        self.assertEqual(call[3],{'position':False,'rotation':False,'scale':True})
        self.assertEqual(self.cmds.getAttr(self.target+'.scaleX'),2)

    def test_match_rejects_affected_locks_and_existing_connections(self):
        self.cmds.setAttr(self.target+'.translateX',lock=True)
        with self.assertRaisesRegex(ValueError,'locked'): self.match()
        self.cmds.setAttr(self.target+'.translateX',lock=False)
        self.cmds.inputs[self.target+'.rotate'] = self.source+'.worldMatrix'
        with self.assertRaisesRegex(ValueError,'incoming connection'): self.match(method='native')
        self.assertFalse(any(c[0]=='matchTransform' for c in self.cmds.calls))

    def test_match_rejects_self_empty_flags_and_moving_reference(self):
        with self.assertRaises(ValueError): self.match(position=False,rotation=False)
        with self.assertRaises(ValueError): self.ns['match_two_transforms'](self.target,self.target)
        with self.assertRaisesRegex(ValueError,'below Target'):
            self.ns['match_two_transforms'](self.cmds.joints[2],self.target)

    def test_match_rejects_missing_ambiguous_instanced_and_disabled_undo(self):
        with self.assertRaises(ValueError): self.ns['match_two_transforms']('missing',self.target)
        self.cmds.add_node('|other|matchSource','transform')
        with self.assertRaises(ValueError): self.ns['match_two_transforms']('matchSource',self.target)
        self.cmds.nodes[self.source]['instanced'] = True
        with self.assertRaisesRegex(ValueError,'non-instanced'): self.match()
        self.cmds.nodes[self.source]['instanced'] = False
        self.cmds.enabled = False
        with self.assertRaisesRegex(ValueError,'Enable Maya Undo'): self.match()

    def test_match_preserves_joint_orientation_definition(self):
        self.cmds.nodes[self.target]['attrs']['jointOrient'] = [(10,20,30)]
        self.cmds.nodes[self.target]['attrs']['rotateAxis'] = [(0,5,0)]
        self.match()
        self.assertEqual(self.cmds.getAttr(self.target+'.jointOrient'),[(10,20,30)])
        self.assertEqual(self.cmds.getAttr(self.target+'.rotateAxis'),[(0,5,0)])

    def test_failed_match_restores_target_and_inputs(self):
        import copy
        nodes,inputs = copy.deepcopy(self.cmds.nodes),dict(self.cmds.inputs)
        original = self.cmds.undoInfo
        checkpoint = {}
        def info(**kw):
            if kw.get('openChunk'): checkpoint['name'] = kw['chunkName']
            if kw.get('query') and kw.get('undoName'): return checkpoint['name']
            return original(**kw)
        def undo():
            self.cmds.nodes = copy.deepcopy(nodes)
            self.cmds.inputs = dict(inputs)
        self.cmds.undoInfo,self.cmds.undo = info,undo
        self.cmds.fail_match = True
        with self.assertRaisesRegex(RuntimeError,'rolled back'): self.match()
        self.assertEqual(self.cmds.nodes,nodes)
        self.assertEqual(self.cmds.inputs,inputs)

    def sdk_input(self,attribute='rotateZ',kind='animCurveUA'):
        curve=self.cmds.add_node('matchSDK_'+attribute,kind)
        self.cmds.nodes[curve]['attrs']['keys']=[(0,0),(1,60)]
        self.cmds.inputs[self.target+'.'+attribute]=curve+'.output'
        return curve

    def undo_checkpoint(self):
        import copy
        checkpoint={}
        original=self.cmds.undoInfo
        def info(**kw):
            if kw.get('openChunk'):
                checkpoint.update(name=kw['chunkName'],nodes=copy.deepcopy(self.cmds.nodes),inputs=dict(self.cmds.inputs))
            if kw.get('query') and kw.get('undoName'):return checkpoint['name']
            return original(**kw)
        def undo():
            self.cmds.nodes=copy.deepcopy(checkpoint['nodes'])
            self.cmds.inputs=dict(checkpoint['inputs'])
            checkpoint['undone']=True
        self.cmds.undoInfo,self.cmds.undo=info,undo
        return checkpoint

    def test_set_default_accepts_sdk_channels_and_preserves_curves_inputs_and_nodes(self):
        import copy
        curves=[self.sdk_input(attribute,kind) for attribute,kind in
                (('translateX','animCurveUL'),('rotateZ','animCurveUA'),('scaleX','animCurveUU'))]
        before={curve:copy.deepcopy(self.cmds.nodes[curve]) for curve in curves}
        inputs,nodes=dict(self.cmds.inputs),set(self.cmds.nodes)
        self.assertFalse(self.cmds.getAttr(self.target+'.rotateZ',settable=True))
        self.match(scale=True)
        self.assertEqual(self.cmds.getAttr(self.target+'.translateX'),8)
        self.assertEqual(self.cmds.getAttr(self.target+'.rotateZ'),30)
        self.assertEqual(self.cmds.getAttr(self.target+'.scaleX'),2)
        self.assertEqual(self.cmds.inputs,inputs)
        self.assertEqual(set(self.cmds.nodes),nodes)
        self.assertEqual({curve:self.cmds.nodes[curve] for curve in curves},before)
        duplicate=next(c for c in self.cmds.calls if c[0]=='duplicate')
        self.assertTrue(duplicate[2]['parentOnly'])
        self.assertFalse(duplicate[2]['inputConnections'])
        self.assertFalse(duplicate[2]['upstreamNodes'])

    def test_set_uses_solved_target_local_channels_instead_of_source_local_values(self):
        import copy
        self.cmds.nodes[self.target]['attrs'].update(rotateOrder=4,rotatePivot=(1,2,3),jointOrient=[(10,20,30)])
        original=self.cmds.matchTransform
        seen={}
        def solve(helper,source,**kw):
            seen.update(parent=helper.rsplit('|',1)[0],attrs=copy.deepcopy(self.cmds.nodes[helper]['attrs']))
            original(helper,source,**kw)
            self.cmds.nodes[helper]['attrs']['translateX']=24
        self.cmds.matchTransform=solve
        self.match()
        self.assertEqual(self.cmds.getAttr(self.target+'.translateX'),24)
        self.assertEqual(self.cmds.getAttr(self.source+'.translateX'),8)
        self.assertEqual(seen['parent'],self.target.rsplit('|',1)[0])
        self.assertEqual(seen['attrs']['jointOrient'],[(10,20,30)])
        self.assertEqual(seen['attrs']['rotateOrder'],4)
        self.assertEqual(seen['attrs']['rotatePivot'],(1,2,3))

    def test_set_position_only_preserves_sdk_rotation_and_locked_scale(self):
        self.sdk_input()
        self.cmds.setAttr(self.target+'.scaleX',lock=True)
        before=self.cmds.getAttr(self.target+'.rotateZ')
        links=dict(self.cmds.inputs)
        self.match(rotation=False)
        self.assertEqual(self.cmds.getAttr(self.target+'.rotateZ'),before)
        self.assertEqual(self.cmds.inputs,links)
        self.assertTrue(self.cmds.getAttr(self.target+'.scaleX',lock=True))

    def test_set_accepts_compound_inputs_without_detaching_them(self):
        self.cmds.inputs[self.target+'.rotate']=self.source+'.outputRotate'
        inputs=dict(self.cmds.inputs)
        self.match()
        self.assertEqual(self.cmds.inputs,inputs)
        self.assertEqual(self.cmds.getAttr(self.target+'.rotateZ'),30)

    def test_set_solver_failure_removes_helper_before_writing_target(self):
        import copy
        before=copy.deepcopy(self.cmds.nodes)
        self.cmds.fail_match=True
        with self.assertRaisesRegex(RuntimeError,'Native match failed'):
            self.match()
        self.assertEqual(self.cmds.nodes,before)
        self.assertFalse(any(c[0]=='setAttr' and c[1].startswith(self.target+'.') for c in self.cmds.calls))

    def test_set_nonfinite_solution_is_rejected_before_target_writes(self):
        import copy
        original=self.cmds.matchTransform
        def solve(helper,source,**kw):
            original(helper,source,**kw)
            self.cmds.nodes[helper]['attrs']['translateY']=float('nan')
        self.cmds.matchTransform=solve
        before=copy.deepcopy(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'non-finite'):
            self.match()
        self.assertEqual(self.cmds.nodes,before)

    def test_set_partial_write_failure_rolls_back_values_and_sdk_inputs(self):
        import copy
        self.sdk_input()
        before,inputs=copy.deepcopy(self.cmds.nodes),dict(self.cmds.inputs)
        checkpoint=self.undo_checkpoint()
        original=self.cmds.setAttr
        def setter(plug,*values,**kw):
            if plug==self.target+'.rotateY':raise RuntimeError('setAttr refused')
            return original(plug,*values,**kw)
        self.cmds.setAttr=setter
        with self.assertRaisesRegex(RuntimeError,'rolled back'):
            self.match()
        self.assertEqual(self.cmds.nodes,before)
        self.assertEqual(self.cmds.inputs,inputs)
        self.assertTrue(checkpoint['undone'])

    def test_set_unexpected_input_change_is_detected_and_rolled_back(self):
        import copy
        self.sdk_input()
        before,inputs=copy.deepcopy(self.cmds.nodes),dict(self.cmds.inputs)
        self.undo_checkpoint()
        original=self.cmds.setAttr
        def setter(plug,*values,**kw):
            result=original(plug,*values,**kw)
            if plug==self.target+'.rotateZ':self.cmds.inputs.pop(plug,None)
            return result
        self.cmds.setAttr=setter
        with self.assertRaisesRegex(RuntimeError,'incoming connection'):
            self.match()
        self.assertEqual(self.cmds.nodes,before)
        self.assertEqual(self.cmds.inputs,inputs)

    def test_set_recomputing_driver_does_not_report_false_success(self):
        import copy
        self.sdk_input()
        before,inputs=copy.deepcopy(self.cmds.nodes),dict(self.cmds.inputs)
        self.undo_checkpoint()
        original=self.cmds.getAttr
        def read(plug,**kw):
            if plug==self.target+'.rotateZ' and not kw:return 0
            return original(plug,**kw)
        self.cmds.getAttr=read
        with self.assertRaisesRegex(RuntimeError,'did not retain the set value'):
            self.match()
        self.assertEqual(self.cmds.nodes,before)
        self.assertEqual(self.cmds.inputs,inputs)

    def test_set_joint_orientation_solver_changes_are_rejected(self):
        import copy
        original=self.cmds.matchTransform
        def solve(helper,source,**kw):
            original(helper,source,**kw)
            self.cmds.nodes[helper]['attrs']['jointOrient']=[(45,0,0)]
        self.cmds.matchTransform=solve
        before=copy.deepcopy(self.cmds.nodes)
        with self.assertRaisesRegex(RuntimeError,'orientation definition'):
            self.match()
        self.assertEqual(self.cmds.nodes,before)

    def test_native_method_keeps_previous_behavior_without_temp_nodes(self):
        result=self.match(method='native')
        call=next(c for c in self.cmds.calls if c[0]=='matchTransform')
        self.assertEqual(call[1:3],(self.target,self.source))
        self.assertEqual(result['method'],'native')
        self.assertFalse(any(c[0]=='duplicate' for c in self.cmds.calls))

    def test_match_invalid_method_does_not_change_scene(self):
        import copy
        before=copy.deepcopy(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'Choose Set channel values'):
            self.match(method='invalid')
        self.assertEqual(self.cmds.nodes,before)


class ModularRigCommands(PairConstraintCommands):
    """Model command orchestration/ownership, not Maya's constraint solver."""
    def createNode(self,kind,name,**kw):
        if kind in ('transform','joint'):name='|'+name.lstrip(':|')
        return super().createNode(kind,name,**kw)

    def select(self,objects=None,**kw):
        return super().select([objects] if isinstance(objects,str) else objects,**kw)

    def addAttr(self,node,longName,**kw):
        super().addAttr(node,longName,**kw)
        self.nodes[node].setdefault('attr_types',{})[longName]=kw.get('dataType',kw.get('attributeType','double'))

    def getAttr(self,plug,**kw):
        node,attr=plug.split('.',1)
        if kw.get('type'):
            if attr=='message':return 'message'
            return self.nodes[node].get('attr_types',{}).get(attr.split('[')[0],super().getAttr(plug,**kw))
        if not kw:
            if attr=='worldMatrix[0]':return self.nodes[node]['matrix'][:]
            if attr=='offsetParentMatrix' or attr.startswith('matrixIn['):
                return self.nodes[node]['attrs'].get(attr,self.matrix(0,0,0))
            if attr=='inheritsTransform':return self.nodes[node]['attrs'].get(attr,True)
        return super().getAttr(plug,**kw)

    def add_node(self,path,kind,**extra):
        result=super().add_node(path,kind,**extra)
        if kind in ('transform','joint'):
            for prefix,value in (('translate',0),('rotate',0),('scale',1)):
                for axis in 'XYZ':self.nodes[result]['attrs'].setdefault(prefix+axis,value)
        return result

    def attributeName(self,plug,**kw):
        attribute=plug.split('.',1)[1]
        aliases={base[0]+axis.lower():base+axis for base in ('translate','rotate','scale') for axis in 'XYZ'}
        return aliases.get(attribute,attribute)

    def currentUnit(self,**kw):
        return getattr(self,'linear_unit','cm') if kw.get('linear') else getattr(self,'angle_unit','deg')

    def namespace(self,**kw): return True

    def rename(self,node,label):
        previous={self.nodes[n]['uuid']:n for n in self.nodes};inputs=dict(self.inputs)
        result=super().rename(node,label.lstrip(':'))
        current={spec['uuid']:n for n,spec in self.nodes.items()}
        remap={old:current[identity] for identity,old in previous.items()}
        def plug(value):
            n,a=value.split('.',1)
            return remap.get(n,n)+'.'+a
        self.inputs={plug(k):plug(v) for k,v in inputs.items()}
        for data in self.nodes.values():
            if 'targets' in data:data['targets']=[remap.get(n,n) for n in data['targets']]
        return result

    def setKeyframe(self,node,**kw):
        self.nodes[node]['attrs'][kw['attribute']]=kw['value']
        self.calls.append(('setKeyframe',node,kw))

    def __init__(self):
        super().__init__()
        import copy
        self.copy = copy
        self.checkpoint = None
        self.chunk_name = ''
        self.undo_count = 0
        for joint in self.joints:
            attrs = self.nodes[joint]['attrs']
            for prefix, value in (('translate',0),('rotate',0),('scale',1)):
                for axis in 'XYZ': attrs[prefix+axis] = value
            attrs.update({'segmentScaleCompensate':True,'rotateOrder':0,'inIKSolveFlag':False})

    def undoInfo(self, **kw):
        if kw.get('openChunk'):
            self.chunk_name = kw['chunkName']
            self.checkpoint = (self.copy.deepcopy(self.nodes), dict(self.inputs), self.selection[:])
        if kw.get('query') and kw.get('undoName'): return self.chunk_name
        return super().undoInfo(**kw)

    def undo(self):
        self.undo_count += 1
        self.nodes,self.inputs,self.selection = self.copy.deepcopy(self.checkpoint)

    def parent(self, node, group, **kw):
        previous = {self.nodes[n]['uuid']:n for n in self.nodes}
        result = super().parent(node,group,**kw)
        now = {spec['uuid']:n for n,spec in self.nodes.items()}
        remap = {old:now[identity] for identity,old in previous.items()}
        def plug(p):
            n,a = p.split('.',1)
            return remap.get(n,n)+'.'+a
        self.inputs = {plug(k):plug(v) for k,v in self.inputs.items()}
        for data in self.nodes.values():
            if 'joint_list' in data:
                data['joint_list']=[remap.get(n,n) for n in data['joint_list']]
                data['effector']=remap.get(data['effector'],data['effector'])
            if 'targets' in data:data['targets']=[remap.get(n,n) for n in data['targets']]
        return result

    def listConnections(self, plug, **kw):
        if '.' not in plug:
            edges = [(receiver,driver) for receiver,driver in self.inputs.items()
                     if driver.split('.',1)[0]==plug] if kw.get('destination') else [
                         (receiver,driver) for receiver,driver in self.inputs.items() if receiver.split('.',1)[0]==plug]
            return [receiver if kw.get('destination') else driver for receiver,driver in edges]
        return super().listConnections(plug,**kw)

    def delete(self, nodes):
        if getattr(self,'fail_delete',False): raise RuntimeError('Delete failed')
        return super().delete(nodes)


class ModularRigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree=ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())

    def setUp(self):
        import math,uuid
        self.cmds=ModularRigCommands()
        wanted={'_begin_tool_undo','_end_tool_undo','_tool_action','_non_undoable_cache_write',
                '_guide_ik_uuid','_guide_ik_resolve_uuid','_guide_ik_joint','_guide_ik_delete_owned',
                '_resolve_hierarchy_root','_restore_locator_view_selection','plan_fk_module',
                'build_fk_module','list_rig_modules','remove_rig_module','organize_rig_constraints'}
        nodes=[n for n in self.tree.body if (isinstance(n,ast.FunctionDef) and ((n.name in wanted or n.name.startswith("_constraint_")) or n.name.startswith('_rig_module_'))) or (isinstance(n,ast.ClassDef) and n.name=='_IKLengthGraph')]
        constants=[n for n in self.tree.body if isinstance(n,ast.Assign) and any(getattr(t,'id','').startswith('_RIG_MODULE_') for t in n.targets)]
        self.ns={'cmds':self.cmds,'math':math,'json':json,'uuid':uuid,'wraps':wraps,'contextmanager':contextlib.contextmanager,'_TOOL_UNDO_DEPTH':0}
        exec(compile(ast.Module(body=constants+nodes,type_ignores=[]),'<Modular rig>','exec'),self.ns)

    def build(self, **kw): return self.ns['build_fk_module']([self.cmds.joints[0]], include_children=True, **kw)
    def read(self,result): return self.ns['_rig_module_read'](result['module'])[1]

    def test_root_descendants_are_sorted_and_read_only(self):
        before=set(self.cmds.nodes)
        plan=self.ns['plan_fk_module']([self.cmds.joints[0]],True,2,'Arm L')
        self.assertEqual(plan['joints'],self.cmds.joints)
        self.assertEqual(plan['parents'][self.cmds.joints[1]],self.cmds.joints[0])
        self.assertEqual(plan['name'],'Arm_L')
        self.assertEqual(set(self.cmds.nodes),before)
        self.assertFalse(self.cmds.chunks)

    def test_build_controls_tree_global_scale_and_native_constraints(self):
        selected=self.cmds.selection[:]
        source_before={n:self.cmds.copy.deepcopy(self.cmds.nodes[n]) for n in self.cmds.joints}
        result=self.build(name='arm')
        state=self.read(result)
        root=result['root']
        self.assertEqual(result['joint_count'],3)
        self.assertEqual(result['owned_node_count'],23) # original 19 + three output transforms + module INPUT
        for axis in 'XYZ': self.assertEqual(self.cmds.inputs[root+'.scale'+axis],root+'.globalScale')
        self.assertEqual(self.cmds.getAttr(root+'.globalScale'),1)
        self.assertFalse(self.cmds.getAttr(root+'.globalScale',lock=True))
        self.assertTrue(self.cmds.getAttr(root+'.globalScale',keyable=True))
        for index,row in enumerate(state['controls']):
            offset=self.ns['_rig_module_node'](row['offset'])
            expected_parent=root if index==0 else result['controls'][index-1]
            self.assertEqual(offset.rsplit('|',1)[0],expected_parent)
            self.assertEqual(len(row['inputs']),9)
        calls=[c for c in self.cmds.calls if c[0] in ('parentConstraint','scaleConstraint')]
        self.assertEqual(len(calls),6)
        self.assertTrue(all(c[3]['maintainOffset'] for c in calls))
        for node in self.cmds.joints: self.assertEqual(self.cmds.nodes[node],source_before[node])
        self.assertEqual(self.cmds.selection,selected)
        self.assertEqual(self.cmds.chunks,['open','close'])

    def test_connected_branch_and_unordered_selection(self):
        branch=self.cmds.add_node('|first|branch','joint',matrix=self.cmds.matrix(1,3,0))
        attrs=self.cmds.nodes[branch]['attrs']
        attrs.update(self.cmds.copy.deepcopy(self.cmds.nodes[self.cmds.joints[1]]['attrs']))
        result=self.ns['build_fk_module']([branch]+self.cmds.joints[::-1],name='tree')
        state=self.read(result)
        branch_row=next(row for row in state['controls'] if row['joint']==self.ns['_guide_ik_uuid'](branch))
        parent_control=next(row['control'] for row in state['controls'] if row['joint']==self.ns['_guide_ik_uuid']('|first'))
        self.assertEqual(self.ns['_rig_module_node'](branch_row['offset']).rsplit('|',1)[0],self.ns['_rig_module_node'](parent_control))

    def test_missing_intermediate_multiple_roots_and_transform_inputs_rejected(self):
        for nodes in ([self.cmds.joints[0],self.cmds.joints[2]],['|first','|other'],['|transform']):
            if '|other' in nodes: self.cmds.add_node('|other','joint')
            if '|transform' in nodes: self.cmds.add_node('|transform','transform')
            with self.assertRaises(ValueError): self.ns['plan_fk_module'](nodes)
        self.assertFalse(self.cmds.chunks)

    def test_locked_animated_referenced_instanced_and_ik_joints_rejected(self):
        joint=self.cmds.joints[1]
        self.cmds.setAttr(joint+'.rotateX',lock=True)
        with self.assertRaises(ValueError): self.build()
        self.cmds.setAttr(joint+'.rotateX',lock=False)
        self.cmds.inputs[joint+'.translateX']='foreign.output'
        with self.assertRaises(ValueError): self.build()
        del self.cmds.inputs[joint+'.translateX']
        for key in ('referenced','instanced','node_locked'):
            self.cmds.nodes[joint][key]=True
            with self.assertRaises(ValueError): self.build()
            self.cmds.nodes[joint][key]=False
        self.cmds.nodes[joint]['attrs']['inIKSolveFlag']=True
        with self.assertRaisesRegex(ValueError,'IK solver'): self.build()

    def test_invalid_size_name_and_scale_are_rejected(self):
        for size in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError): self.build(control_size=size)
        with self.assertRaises(ValueError): self.build(name=' ')
        matrix=self.cmds.nodes['|first']['matrix']
        matrix[0]=2
        with self.assertRaisesRegex(ValueError,'uniform'): self.build()
        matrix[0]=-1
        with self.assertRaisesRegex(ValueError,'negative'): self.build()
        matrix[0]=1;matrix[1]=1
        with self.assertRaises(ValueError): self.build()

    def test_repeat_build_rejected_without_changing_module(self):
        result=self.build()
        before=set(self.cmds.nodes)
        with self.assertRaises(ValueError): self.build()
        self.assertEqual(set(self.cmds.nodes),before)
        self.assertEqual(self.ns['list_rig_modules'](),[result['module']])

    def test_no_children_builds_one_joint(self):
        result=self.ns['build_fk_module']('|first',name='single')
        self.assertEqual(result['joint_count'],1)
        self.assertFalse(any(p.startswith(self.cmds.joints[1]+'.') for p in self.cmds.inputs))

    def test_disabled_or_nested_undo_is_rejected(self):
        self.cmds.enabled=False
        with self.assertRaisesRegex(ValueError,'Enable Maya Undo'): self.build()
        self.cmds.enabled=True;self.ns['_TOOL_UNDO_DEPTH']=1
        with self.assertRaisesRegex(ValueError,'outside another'): self.build()

    def test_failed_constraint_rolls_back_everything(self):
        before=self.cmds.copy.deepcopy(self.cmds.nodes)
        self.cmds.fail_kind='scaleConstraint'
        with self.assertRaisesRegex(RuntimeError,'rolled back'): self.build()
        self.assertEqual(self.cmds.nodes,before)
        self.assertFalse(self.cmds.inputs)
        self.assertEqual(self.cmds.undo_count,1)

    def test_removal_restores_current_local_values_and_keeps_definitions(self):
        result=self.build()
        for n in self.cmds.joints:
            self.cmds.nodes[n]['attrs'].update({'rotateX':35,'translateY':3,'scaleZ':2})
        snapshot={n:self.cmds.copy.deepcopy(self.cmds.nodes[n]) for n in self.cmds.joints}
        removed=self.ns['remove_rig_module'](result['module'])
        self.assertEqual(removed['joint_count'],3)
        self.assertEqual(set(self.cmds.nodes),set(self.cmds.joints))
        self.assertFalse(self.cmds.inputs)
        for n in self.cmds.joints: self.assertEqual(self.cmds.nodes[n],snapshot[n])
        self.assertEqual(self.cmds.chunks,['open','close','open','close'])

    def test_failed_remove_restores_graph(self):
        result=self.build();before=self.cmds.copy.deepcopy(self.cmds.nodes);edges=dict(self.cmds.inputs)
        self.cmds.fail_delete=True
        with self.assertRaisesRegex(RuntimeError,'rolled back'): self.ns['remove_rig_module'](result['module'])
        self.assertEqual(self.cmds.nodes,before);self.assertEqual(self.cmds.inputs,edges)

    def test_foreign_child_and_output_stop_remove_before_mutation(self):
        result=self.build();root=result['root']
        child=self.cmds.add_node(root+'|userChild','transform')
        with self.assertRaisesRegex(ValueError,'Move'): self.ns['remove_rig_module'](result['module'])
        self.cmds.delete(child)
        other=self.cmds.add_node('|consumer','transform')
        self.cmds.inputs[other+'.translateX']=result['controls'][0]+'.rotateX'
        with self.assertRaisesRegex(ValueError,'Another system'): self.ns['remove_rig_module'](result['module'])
        self.assertTrue(self.cmds.objExists(root))

    def test_changed_joint_driver_is_preserved(self):
        result=self.build();other=self.cmds.add_node('|otherDriver','transform')
        plug=self.cmds.joints[1]+'.rotateX';self.cmds.inputs[plug]=other+'.rotateX'
        with self.assertRaisesRegex(ValueError,'another driver'): self.ns['remove_rig_module'](result['module'])
        self.assertEqual(self.cmds.inputs[plug],other+'.rotateX')

    def test_tampered_members_and_joint_ownership_are_rejected(self):
        result=self.build();state=self.read(result);meta=result['module']
        state['members'].append({'uuid':self.ns['_guide_ik_uuid']('|first'),'type':'joint'})
        self.cmds.setAttr(meta+'.rtkRigModuleState',json.dumps(state),type='string')
        with self.assertRaisesRegex(ValueError,'ownership'): self.ns['remove_rig_module'](meta)
        self.assertTrue(self.cmds.objExists('|first'))

    def test_renamed_joint_and_root_are_resolved_by_uuid(self):
        result=self.build()
        self.cmds.rename(result['root'],'renamedRoot')
        self.cmds.rename('|first','renamedJoint')
        state=self.read(result)
        self.assertEqual(self.ns['_rig_module_node'](state['root']).rsplit('|',1)[-1],'renamedRoot')
        self.assertEqual(self.ns['_guide_ik_uuid'](self.cmds.listRelatives(self.ns['_rig_module_node'](state['root']),parent=True)[0]),state['input'])
        self.ns['remove_rig_module'](result['module'])
        self.assertTrue(self.cmds.objExists('|renamedJoint'))

    def test_missing_owned_constraint_can_be_cleaned(self):
        result=self.build();state=self.read(result)
        self.cmds.delete(self.ns['_rig_module_node'](state['controls'][1]['constraints'][0]))
        self.ns['remove_rig_module'](result['module'])
        self.assertEqual(set(self.cmds.nodes),set(self.cmds.joints))

    def test_build_detects_solver_pose_drift_and_rolls_back(self):
        before=self.cmds.copy.deepcopy(self.cmds.nodes)
        original=self.cmds.scaleConstraint
        def scale(driver,driven,**kw):
            result=original(driver,driven,**kw)
            self.cmds.nodes[driven]['matrix'][12]+=1
            return result
        self.cmds.scaleConstraint=scale
        with self.assertRaisesRegex(RuntimeError,'pose changed'): self.build()
        self.assertEqual(self.cmds.nodes,before)

    def test_changed_source_message_link_blocks_remove(self):
        result=self.build()
        self.cmds.inputs[result['module']+'.sources[0]']=self.cmds.joints[1]+'.message'
        with self.assertRaisesRegex(ValueError,'source joint link'): self.ns['remove_rig_module'](result['module'])
        self.assertTrue(self.cmds.objExists(result['root']))

    def test_two_modules_are_independent_and_share_the_contract(self):
        first=self.build(name='arm')
        other=self.cmds.add_node('|other','joint',matrix=self.cmds.matrix(10,0,0))
        self.cmds.nodes[other]['attrs']=self.cmds.copy.deepcopy(self.cmds.nodes['|first']['attrs'])
        second=self.ns['build_fk_module'](other,name='finger')
        self.assertEqual(len(self.ns['list_rig_modules']()),2)
        self.ns['remove_rig_module'](first['module'])
        self.assertTrue(self.cmds.objExists(second['root']))
        self.assertEqual(self.read(second)['type'],'FK')
        self.ns['remove_rig_module'](second['module'])

    def test_existing_module_membership_blocks_rebuild_after_disconnection(self):
        result=self.build()
        self.cmds.inputs={receiver:driver for receiver,driver in self.cmds.inputs.items()
                          if receiver.split('.',1)[0] not in self.cmds.joints}
        with self.assertRaisesRegex(ValueError,'already belong'): self.build()
        self.assertTrue(self.cmds.objExists(result['root']))

    def test_negative_local_scale_is_rejected_even_when_world_matrix_is_proper(self):
        self.cmds.nodes['|first']['attrs']['scaleX']=-1
        self.cmds.nodes['|first']['attrs']['scaleY']=-1
        with self.assertRaisesRegex(ValueError,'positive scales'): self.build()

    def test_compound_joint_lock_and_replacement_driver_block_remove(self):
        result=self.build();joint=self.cmds.joints[1]
        self.cmds.setAttr(joint+'.rotate',lock=True)
        with self.assertRaisesRegex(ValueError,'Unlock'): self.ns['remove_rig_module'](result['module'])
        self.cmds.setAttr(joint+'.rotate',lock=False)
        foreign=self.cmds.add_node('|foreignDriver','transform')
        self.cmds.inputs[joint+'.rotate']=foreign+'.rotate'
        with self.assertRaisesRegex(ValueError,'another driver'): self.ns['remove_rig_module'](result['module'])
        self.assertTrue(self.cmds.objExists(result['root']))

    def test_owned_compound_connection_does_not_block_removal(self):
        result=self.build();state=self.read(result);joint=self.cmds.joints[1]
        constraint=self.ns['_rig_module_node'](state['controls'][1]['constraints'][0])
        self.cmds.inputs[joint+'.rotate']=constraint+'.constraintRotate'
        self.ns['remove_rig_module'](result['module'])
        self.assertEqual(set(self.cmds.nodes),set(self.cmds.joints))


class ModularIKCommands(ModularRigCommands):
    def getAttr(self,plug,**kw):
        if plug.endswith('.worldMatrix[0]'):
            return tuple(self.nodes[plug.split('.',1)[0]]['matrix'])
        return super().getAttr(plug,**kw)

    def xform(self,node,**kw):
        if 'matrix' in kw and not kw.get('query') and self.nodes[node].get('internal_driver'):
            matrix=kw['matrix']
            parent=self.listRelatives(node,parent=True)[0]
            pm=self.nodes[parent]['matrix']
            for index,axis in enumerate('XYZ'):
                self.nodes[node]['attrs']['translate'+axis]=matrix[12+index]-pm[12+index]
        return super().xform(node,**kw)

    def createNode(self,kind,name,**kw):
        node=super().createNode(kind,name,**kw)
        if kind=='joint':
            self.nodes[node]['internal_driver']=True
            self.nodes[node]['attrs'].update({'rotate':[(0,0,0)],'jointOrient':[(0,0,0)],
                'rotateAxis':[(0,0,0)],'rotateOrder':0,'segmentScaleCompensate':True,'ikBlend':1})
            for prefix,value in (('translate',0),('rotate',0),('scale',1)):
                for axis in 'XYZ':self.nodes[node]['attrs'][prefix+axis]=value
        if kw.get('parent'): node=self.parent(node,kw['parent'])[0]
        return node

    def ikHandle(self,*args,**kw):
        if kw.get('query'): return super().ikHandle(*args,**kw)
        if self.fail_stage=='handle': raise RuntimeError('IK handle failed')
        first,third=kw['startJoint'],kw['endEffector']
        second=self.listRelatives(third,parent=True)[0]
        handle=self.add_node('|'+kw['name'].lstrip(':'),'ikHandle')
        effector=self.add_node(second+'|effector','ikEffector')
        self.nodes[handle].update({'joint_list':[first,second],'effector':effector})
        self.inputs[effector+'.translate']=third+'.translate'
        self.calls.append(('ikHandle',kw))
        return handle,effector


class ModularIKTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.tree=ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())

    def setUp(self):
        import math,uuid
        self.cmds=ModularIKCommands()
        wanted={'_begin_tool_undo','_end_tool_undo','_tool_action','_non_undoable_cache_write',
                '_guide_ik_uuid','_guide_ik_resolve_uuid','_guide_ik_joint','_guide_ik_delete_owned','_guide_ik_snapshot',
                '_resolve_hierarchy_root','_restore_locator_view_selection','plan_fk_module','build_fk_module',
                'list_rig_modules','remove_rig_module','organize_rig_constraints','calculate_guide_ik_pole','find_guide_ik_systems',
                'plan_guide_ik','plan_ik_module','build_ik_module'}
        nodes=[n for n in self.tree.body if (isinstance(n,ast.FunctionDef) and ((n.name in wanted or n.name.startswith("_constraint_")) or n.name.startswith('_rig_module_'))) or (isinstance(n,ast.ClassDef) and n.name=='_IKLengthGraph')]
        constants=[n for n in self.tree.body if isinstance(n,ast.Assign) and any(getattr(t,'id','').startswith(('_RIG_MODULE_','_IK_GUIDE_')) for t in n.targets)]
        self.ns={'cmds':self.cmds,'math':math,'json':json,'uuid':uuid,'wraps':wraps,'contextmanager':contextlib.contextmanager,'_TOOL_UNDO_DEPTH':0}
        exec(compile(ast.Module(body=constants+nodes,type_ignores=[]),'<Modular IK>','exec'),self.ns)
        # Keep these historical fixtures exercising saved v2.19–2.23 graphs.
        # XMatrixIKTests below exercise the new default backend independently.
        original=self.ns['build_ik_module']
        def legacy_builder(*args,**kw):
            kw.setdefault('_matrix_solver',False)
            return original(*args,**kw)
        self.ns['build_ik_module']=legacy_builder

    def build(self,**kw): return self.ns['build_ik_module'](*self.cmds.joints,**kw)
    def read(self,result): return self.ns['_rig_module_read'](result['module'])[1]

    def test_plan_is_read_only_and_pole_extends_through_middle(self):
        before=set(self.cmds.nodes)
        plan=self.ns['plan_ik_module'](*self.cmds.joints)
        self.assertEqual(plan['pole']['projection'],(3,0,0))
        self.assertEqual(plan['pole']['position'][0],3)
        self.assertGreater(plan['pole']['position'][1],2)
        self.assertEqual(set(self.cmds.nodes),before)
        self.assertFalse(self.cmds.chunks)

    def test_build_owns_driver_chain_solver_end_pole_and_global_scale(self):
        before={n:self.cmds.copy.deepcopy(self.cmds.nodes[n]) for n in self.cmds.joints}
        selected=self.cmds.selection[:]
        result=self.build(name='armIK');state=self.read(result)
        self.assertEqual(state['type'],'IK3')
        self.assertGreater(result['owned_node_count'],23)
        self.assertIn('length_system',state['ik'])
        self.assertEqual(len(state['ik']['drivers']),3)
        self.assertTrue(set(state['ik']['drivers']).isdisjoint(row['uuid'] for row in state['joints']))
        handle=next(call for call in self.cmds.calls if call[0]=='ikHandle')
        self.assertEqual(handle[1]['solver'],'ikRPsolver')
        self.assertNotIn(handle[1]['startJoint'],self.cmds.joints)
        for identity in state['ik']['drivers']:
            node=self.ns['_rig_module_node'](identity)
            self.assertFalse(self.cmds.getAttr(node+'.segmentScaleCompensate'))
        for axis in 'XYZ':self.assertEqual(self.cmds.inputs[result['root']+'.scale'+axis],result['root']+'.globalScale')
        self.assertEqual(state['ui_controls'],[state['ik']['end'],state['ik']['pole']])
        for n in self.cmds.joints:self.assertEqual(self.cmds.nodes[n],before[n])
        self.assertEqual(self.cmds.selection,selected)
        self.assertEqual(self.cmds.chunks,['open','close'])

    def test_all_ik_control_attributes_remain_unlocked(self):
        result=self.build()
        for n in (result['root'],result['end_controller'],result['pole_controller']):
            for prefix in ('translate','rotate','scale'):
                for axis in 'XYZ':self.assertFalse(self.cmds.getAttr(n+'.'+prefix+axis,lock=True))
        self.assertTrue(self.cmds.getAttr(result['root']+'.globalScale',keyable=True))

    def test_remove_preserves_current_source_channels_and_orientation(self):
        result=self.build()
        for n in self.cmds.joints:self.cmds.nodes[n]['attrs'].update({'rotateX':45,'translateY':5,'scaleZ':1.5})
        before={n:self.cmds.copy.deepcopy(self.cmds.nodes[n]) for n in self.cmds.joints}
        self.ns['remove_rig_module'](result['module'])
        self.assertEqual(set(self.cmds.nodes),set(self.cmds.joints))
        self.assertFalse(self.cmds.inputs)
        for n in self.cmds.joints:self.assertEqual(self.cmds.nodes[n],before[n])

    def test_repeat_build_and_overlapping_fk_are_blocked(self):
        self.build();before=set(self.cmds.nodes)
        with self.assertRaises(ValueError):self.build()
        with self.assertRaises(ValueError):self.ns['build_fk_module'](self.cmds.joints,name='overlap')
        self.assertEqual(set(self.cmds.nodes),before)

    def test_fk_existing_state_is_still_readable(self):
        result=self.ns['build_fk_module'](self.cmds.joints,name='existingFK')
        self.assertEqual(self.read(result)['type'],'FK')
        with self.assertRaises(ValueError):self.build()
        self.ns['remove_rig_module'](result['module'])
        self.assertEqual(set(self.cmds.nodes),set(self.cmds.joints))

    def test_nonconsecutive_duplicate_and_straight_chains_are_rejected(self):
        with self.assertRaises(ValueError):self.ns['plan_ik_module'](self.cmds.joints[0],self.cmds.joints[2],self.cmds.joints[1])
        with self.assertRaises(ValueError):self.ns['plan_ik_module'](*([self.cmds.joints[0]]*3))
        self.cmds.nodes[self.cmds.joints[1]]['matrix'][13]=0
        with self.assertRaisesRegex(ValueError,'straight'):self.build()
        self.assertFalse(self.cmds.chunks)

    def test_invalid_size_pole_distance_and_undo_are_rejected(self):
        for options in ({'control_size':0},{'pole_distance':0},{'pole_distance':float('nan')}):
            with self.assertRaises(ValueError):self.build(**options)
        self.cmds.enabled=False
        with self.assertRaisesRegex(ValueError,'Enable Maya Undo'):self.build()

    def test_failures_at_handle_pole_and_source_constraints_roll_back(self):
        before=self.cmds.copy.deepcopy(self.cmds.nodes)
        for stage in ('handle','pole','scaleConstraint'):
            self.cmds.fail_stage=stage
            self.cmds.fail_kind=stage
            with self.assertRaisesRegex(RuntimeError,'rolled back'):self.build()
            self.assertEqual(self.cmds.nodes,before)
            self.assertFalse(self.cmds.inputs)

    def test_foreign_child_under_driver_joint_blocks_remove(self):
        result=self.build();state=self.read(result)
        driver=self.ns['_rig_module_node'](state['ik']['drivers'][1])
        child=self.cmds.add_node(driver+'|unrelated','transform')
        with self.assertRaisesRegex(ValueError,'Move'):self.ns['remove_rig_module'](result['module'])
        self.assertTrue(self.cmds.objExists(child))

    def test_damaged_ik_ownership_roles_are_rejected(self):
        result=self.build();state=self.read(result)
        state['ik']['drivers'][0]=state['joints'][0]['uuid']
        self.cmds.setAttr(result['module']+'.rtkRigModuleState',json.dumps(state),type='string')
        with self.assertRaisesRegex(ValueError,'IK records'):self.ns['remove_rig_module'](result['module'])
        self.assertTrue(self.cmds.objExists(self.cmds.joints[0]))

    def test_delete_failure_rolls_back_whole_ik_module(self):
        result=self.build();before=self.cmds.copy.deepcopy(self.cmds.nodes);edges=dict(self.cmds.inputs)
        self.cmds.fail_delete=True
        with self.assertRaisesRegex(RuntimeError,'rolled back'):self.ns['remove_rig_module'](result['module'])
        self.assertEqual(self.cmds.nodes,before)
        self.assertEqual(self.cmds.inputs,edges)


class CollapsibleRigGroupTests(unittest.TestCase):
    def test_collapse_expand_hides_body_keeps_values_and_uses_arrows(self):
        from types import SimpleNamespace
        tree=ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='_CollapsibleRigGroup')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='set_expanded')
        def make():
            state={'value':'joint_input','visible':True,'checked':True,'arrow':'down'}
            header=SimpleNamespace(setChecked=lambda v:state.update(checked=v),setArrowType=lambda v:state.update(arrow=v))
            body=SimpleNamespace(setVisible=lambda v:state.update(visible=v))
            return state,SimpleNamespace(header=header,body=body)
        namespace={'QtCore':SimpleNamespace(Qt=SimpleNamespace(DownArrow='down',RightArrow='right'))}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'<Collapse>','exec'),namespace)
        state,panel=make()
        namespace['set_expanded'](panel,False)
        self.assertFalse(state['visible']);self.assertFalse(state['checked']);self.assertEqual(state['arrow'],'right')
        namespace['set_expanded'](panel,True)
        self.assertTrue(state['visible']);self.assertTrue(state['checked']);self.assertEqual(state['arrow'],'down')
        self.assertEqual(state['value'],'joint_input')


class RigModuleActionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.tree=ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())

    def setUp(self):
        ModularIKTests.setUp(self)
        extra={'rename_rig_controllers','store_rig_default','goto_rig_default','plan_rig_mirror','mirror_rig_module',
               '_pd_mirror_tokens','_pd_mirror_name','_pd_mirror_object'}
        nodes=[n for n in self.tree.body if isinstance(n,ast.FunctionDef) and n.name in extra]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<Module actions>','exec'),self.ns)

    def build_kind(self,kind='FK',**kw):
        if kind=='FK':return self.ns['build_fk_module'](self.cmds.joints,**kw)
        return self.ns['build_ik_module'](*self.cmds.joints,**kw)

    def read(self,result):return self.ns['_rig_module_read'](result['module'])[1]

    def sides(self):
        for index,label in enumerate(('upper_L_JNT','mid_L_JNT','end_L_JNT')):
            self.cmds.rename(self.cmds.joints[index],label)
        targets=['|upper_R_JNT','|upper_R_JNT|mid_R_JNT','|upper_R_JNT|mid_R_JNT|end_R_JNT']
        for source,target,position in zip(self.cmds.joints,targets,((0,0,0),(3,-2,0),(8,0,0))):
            self.cmds.add_node(target,'joint',matrix=self.cmds.matrix(*position))
            self.cmds.nodes[target]['attrs']=self.cmds.copy.deepcopy(self.cmds.nodes[source]['attrs'])
        return targets

    def test_joint_names_replace_random_controller_names_in_fk_and_ik(self):
        for kind in ('FK','IK3'):
            self.setUp();self.sides();rig=self.build_kind(kind)
            state=self.read(rig)
            names=state['controller_names']
            self.assertEqual(names['root'],'upper_L_'+('FK' if kind=='FK' else 'IK')+'_ROOT')
            if kind=='FK':self.assertIn('mid_L_FK_CTRL',names.values())
            else:self.assertEqual(names['end'],'end_L_IK_END_CTRL');self.assertEqual(names['pole'],'mid_L_IK_POLE_CTRL')
            self.assertEqual(len(state['defaults']),4 if kind=='FK' else 3)
            self.ns['remove_rig_module'](rig['module'])

    def test_custom_names_apply_individually_and_blank_fields_use_joint_names(self):
        for kind in ('FK','IK3'):
            self.setUp();self.sides()
            key=self.ns['_guide_ik_uuid'](self.cmds.joints[1]) if kind=='FK' else 'end'
            rig=self.build_kind(kind,controller_names={'root':'master_L_CTL',key:'special_L_CTL'})
            names=self.read(rig)['controller_names']
            self.assertEqual(names['root'],'master_L_CTL');self.assertEqual(names[key],'special_L_CTL')
            self.assertTrue(any(name.startswith(('upper_L_','mid_L_','end_L_')) for name in names.values()))

    def test_invalid_duplicate_unknown_or_used_custom_names_fail_before_build(self):
        key=self.ns['_guide_ik_uuid'](self.cmds.joints[0])
        self.cmds.add_node('|used_CTL','transform')
        before=set(self.cmds.nodes)
        for values in ({'root':'bad.name'},{'root':'same',key:'same'},{'wrong':'control'},{'root':'used_CTL'}):
            with self.assertRaises(ValueError):self.build_kind(controller_names=values)
        self.assertEqual(set(self.cmds.nodes),before)
        self.assertFalse(self.cmds.chunks)

    def test_existing_rig_rename_keeps_uuid_inputs_pose_and_source(self):
        for kind in ('FK','IK3'):
            self.setUp();rig=self.build_kind(kind);state=self.read(rig)
            owned={row['uuid'] for row in state['members']}
            source={n:self.cmds.copy.deepcopy(self.cmds.nodes[n]) for n in self.cmds.joints}
            self.ns['rename_rig_controllers'](rig['module'],{'root':'renamedMaster'})
            after=self.read(rig)
            self.assertEqual({row['uuid'] for row in after['members']},owned)
            self.assertEqual(after['controller_names']['root'],'renamedMaster')
            self.assertEqual(after['defaults'],state['defaults'])
            for n in self.cmds.joints:self.assertEqual(self.cmds.nodes[n],source[n])
            self.ns['remove_rig_module'](rig['module'])
            self.assertTrue(all(self.cmds.objExists(n) for n in self.cmds.joints))

    def test_remove_accepts_short_names_aliases_and_destination_aliases(self):
        for kind in ('FK','IK3'):
            self.setUp();rig=self.build_kind(kind);state=self.read(rig)
            for index,row in enumerate(state['controls']):
                for cindex,identity in enumerate(row['constraints']):
                    self.cmds.rename(self.ns['_rig_module_node'](identity),'uniqueConstraint_'+str(index)+'_'+str(cindex))
            original=self.cmds.listConnections
            def spelling(plug,**kw):
                values=original(plug,**kw)
                out=[]
                for value in values:
                    node,attribute=value.split('.',1)
                    aliases={'translateX':'tx','rotateX':'rx','scaleX':'sx','constraintTranslateX':'ctx'}
                    leaf=node.rsplit('|',1)[-1]
                    # Maya includes enough DAG path when a leaf is ambiguous.
                    name=leaf if len(self.cmds.ls(leaf))==1 else node
                    out.append(name+'.'+aliases.get(attribute,attribute))
                return out
            self.cmds.listConnections=spelling
            self.ns['remove_rig_module'](rig['module'])
            self.assertEqual(set(self.cmds.nodes),set(self.cmds.joints))

    def test_remove_still_rejects_real_external_driver_and_keeps_graph(self):
        rig=self.build_kind();foreign=self.cmds.add_node('|newDriver','transform')
        plug=self.cmds.joints[0]+'.translateX';self.cmds.inputs[plug]=foreign+'.translateX'
        before=set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'newDriver'):self.ns['remove_rig_module'](rig['module'])
        self.assertEqual(set(self.cmds.nodes),before)
        self.assertEqual(self.cmds.inputs[plug],foreign+'.translateX')

    def test_default_resets_fk_and_ik_controls_without_root_by_default(self):
        for kind in ('FK','IK3'):
            self.setUp();rig=self.build_kind(kind);state=self.read(rig)
            roles=self.ns['_rig_module_controller_roles'](state)
            edges=dict(self.cmds.inputs)
            for role,identity in roles.items():
                node=self.ns['_rig_module_node'](identity)
                self.cmds.setAttr(node+'.rotateY',35)
                self.cmds.setAttr(node+'.translateX',3)
            self.cmds.setAttr(rig['root']+'.globalScale',2)
            self.ns['goto_rig_default'](rig['module'])
            for role,identity in roles.items():
                node=self.ns['_rig_module_node'](identity)
                self.assertEqual(self.cmds.getAttr(node+'.rotateY'),35 if role=='root' else 0)
                self.assertEqual(self.cmds.getAttr(node+'.translateX'),3 if role=='root' else 0)
            self.assertEqual(self.cmds.getAttr(rig['root']+'.globalScale'),2)
            self.assertEqual(self.cmds.inputs,edges)

    def test_default_can_include_root_global_scale_and_retains_connections(self):
        rig=self.build_kind('IK3');edges=dict(self.cmds.inputs)
        self.cmds.setAttr(rig['root']+'.translateY',10);self.cmds.setAttr(rig['root']+'.globalScale',2)
        self.ns['goto_rig_default'](rig['module'],include_root=True)
        self.assertEqual(self.cmds.getAttr(rig['root']+'.translateY'),0)
        self.assertEqual(self.cmds.getAttr(rig['root']+'.globalScale'),1)
        self.assertEqual(self.cmds.inputs,edges)

    def test_explicit_store_current_default_and_unit_changes(self):
        import math
        rig=self.build_kind();control=rig['controls'][0]
        self.cmds.setAttr(control+'.rotateY',30);self.cmds.setAttr(control+'.translateX',2)
        self.ns['store_rig_default'](rig['module'])
        self.cmds.angle_unit='rad';self.cmds.linear_unit='m'
        self.cmds.setAttr(control+'.rotateY',0);self.cmds.setAttr(control+'.translateX',0)
        self.ns['goto_rig_default'](rig['module'])
        self.assertAlmostEqual(self.cmds.getAttr(control+'.rotateY'),math.pi/6)
        self.assertAlmostEqual(self.cmds.getAttr(control+'.translateX'),.02)

    def test_legacy_default_zeroes_controls_but_root_requires_explicit_store(self):
        rig=self.build_kind();state=self.read(rig);state.pop('defaults');state.pop('default_units')
        self.cmds.setAttr(rig['module']+'.rtkRigModuleState',json.dumps(state),type='string')
        self.cmds.setAttr(rig['controls'][0]+'.rotateX',20)
        self.ns['goto_rig_default'](rig['module'])
        self.assertEqual(self.cmds.getAttr(rig['controls'][0]+'.rotateX'),0)
        with self.assertRaisesRegex(ValueError,'older module'):self.ns['goto_rig_default'](rig['module'],include_root=True)
        self.ns['store_rig_default'](rig['module'])
        self.ns['goto_rig_default'](rig['module'],include_root=True)

    def test_default_locked_driven_and_corrupt_channels_fail_before_any_writes(self):
        rig=self.build_kind();control=rig['controls'][0]
        self.cmds.setAttr(control+'.rotateX',35);self.cmds.setAttr(control+'.scaleZ',lock=True)
        with self.assertRaises(ValueError):self.ns['goto_rig_default'](rig['module'])
        self.assertEqual(self.cmds.getAttr(control+'.rotateX'),35)
        self.cmds.setAttr(control+'.scaleZ',lock=False)
        other=self.cmds.add_node('|driver','transform');self.cmds.inputs[control+'.rotateX']=other+'.rotateX'
        with self.assertRaises(ValueError):self.ns['goto_rig_default'](rig['module'],keyframe=True)
        self.assertEqual(self.cmds.inputs[control+'.rotateX'],other+'.rotateX')
        del self.cmds.inputs[control+'.rotateX']
        state=self.read(rig);state['defaults'][1]['values']['visibility']=1
        self.cmds.setAttr(rig['module']+'.rtkRigModuleState',json.dumps(state),type='string')
        with self.assertRaises(ValueError):self.ns['goto_rig_default'](rig['module'])

    def test_default_keyframe_option_keeps_existing_time_animation(self):
        rig=self.build_kind();control=rig['controls'][0]
        curve=self.cmds.add_node('timeAnimCurve','animCurveTA');self.cmds.inputs[control+'.rotateX']=curve+'.output'
        self.cmds.setAttr(control+'.rotateX',35)
        with self.assertRaises(ValueError):self.ns['goto_rig_default'](rig['module'])
        self.ns['goto_rig_default'](rig['module'],keyframe=True)
        self.assertEqual(self.cmds.inputs[control+'.rotateX'],curve+'.output')
        self.assertTrue(any(c[0]=='setKeyframe' for c in self.cmds.calls))

    def test_default_failed_setter_rolls_back_whole_pose(self):
        rig=self.build_kind();control=rig['controls'][0]
        self.cmds.setAttr(control+'.rotateX',35);before=self.cmds.copy.deepcopy(self.cmds.nodes)
        original=self.cmds.setAttr
        def fail(plug,*v,**kw):
            if plug.endswith('.scaleZ') and v:raise RuntimeError('Set failed')
            return original(plug,*v,**kw)
        self.cmds.setAttr=fail
        with self.assertRaisesRegex(RuntimeError,'rolled back'):self.ns['goto_rig_default'](rig['module'])
        self.assertEqual(self.cmds.nodes,before)

    def test_mirror_fk_and_ik_build_on_counterparts_keep_source_and_spacing(self):
        for kind in ('FK','IK3'):
            self.setUp();targets=self.sides()
            rig=self.build_kind(kind,name='arm_L',**({'pole_distance':2} if kind=='IK3' else {}))
            before={n:self.cmds.copy.deepcopy(self.cmds.nodes[n]) for n in self.cmds.nodes}
            plan=self.ns['plan_rig_mirror'](rig['module'])
            self.assertEqual(plan['joints'],targets)
            mirrored=self.ns['mirror_rig_module'](rig['module'])
            state=self.read(mirrored)
            self.assertEqual(state['type'],kind)
            self.assertTrue(all('_R' in name for name in state['controller_names'].values()))
            if kind=='IK3':self.assertEqual(state['pole_distance'],2)
            for n in before:self.assertEqual(self.cmds.nodes[n],before[n])
            self.assertEqual(len(self.ns['list_rig_modules']()),2)
            self.ns['remove_rig_module'](mirrored['module'])
            self.assertTrue(self.cmds.objExists(rig['module']))

    def test_mirror_search_replace_custom_names_and_reverse_direction(self):
        self.sides();rig=self.build_kind('IK3',controller_names={'end':'foot_L_CTL','pole':'knee_L_CTL'})
        mirrored=self.ns['mirror_rig_module'](rig['module'])
        names=self.read(mirrored)['controller_names']
        self.assertEqual(names['end'],'foot_R_CTL');self.assertEqual(names['pole'],'knee_R_CTL')
        self.ns['remove_rig_module'](rig['module'])
        reverse=self.ns['mirror_rig_module'](mirrored['module'],'_R','_L')
        self.assertEqual(self.read(reverse)['controller_names']['end'],'foot_L_CTL')

    def test_mirror_missing_ambiguous_occupied_and_repeat_targets_make_no_changes(self):
        targets=self.sides();rig=self.build_kind();mirrored=self.ns['mirror_rig_module'](rig['module'])
        before=set(self.cmds.nodes)
        with self.assertRaises(ValueError):self.ns['mirror_rig_module'](rig['module'])
        self.assertEqual(set(self.cmds.nodes),before)
        self.ns['remove_rig_module'](mirrored['module']);self.cmds.delete(targets[-1])
        before=set(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'Missing'):self.ns['mirror_rig_module'](rig['module'])
        self.assertEqual(set(self.cmds.nodes),before)

    def test_mirror_hierarchy_mismatch_is_rejected(self):
        targets=self.sides();rig=self.build_kind();self.cmds.rename(targets[1],'wrong_R_JNT')
        middle=self.cmds.add_node('|mid_R_JNT','joint',matrix=self.cmds.matrix(3,-2,0))
        self.cmds.nodes[middle]['attrs']=self.cmds.copy.deepcopy(self.cmds.nodes[self.cmds.joints[1]]['attrs'])
        with self.assertRaisesRegex(ValueError,'hierarchy differs'):self.ns['plan_rig_mirror'](rig['module'])

    def test_default_and_rename_require_undo(self):
        rig=self.build_kind();self.cmds.enabled=False
        for action in ('goto_rig_default','store_rig_default','rename_rig_controllers'):
            with self.assertRaisesRegex(ValueError,'Enable Maya Undo'):self.ns[action](rig['module'])

    def test_rename_failure_restores_names_metadata_and_graph(self):
        rig=self.build_kind();before=self.cmds.copy.deepcopy(self.cmds.nodes);edges=dict(self.cmds.inputs)
        original=self.cmds.rename;counter=[0]
        def fail(node,name):
            counter[0]+=1
            if counter[0]==2:raise RuntimeError('Rename failed')
            return original(node,name)
        self.cmds.rename=fail
        with self.assertRaisesRegex(RuntimeError,'rolled back'):self.ns['rename_rig_controllers'](rig['module'],{'root':'newMaster'})
        self.assertEqual(self.cmds.nodes,before);self.assertEqual(self.cmds.inputs,edges)

    def test_duplicate_joint_leaf_auto_names_receive_readable_numeric_suffixes(self):
        self.cmds.rename(self.cmds.joints[2],'tip')
        branch=self.cmds.add_node('|first|branch','joint',matrix=self.cmds.matrix(3,-2,0))
        tip=self.cmds.add_node(branch+'|tip','joint',matrix=self.cmds.matrix(8,0,0))
        for node in (branch,tip):self.cmds.nodes[node]['attrs']=self.cmds.copy.deepcopy(self.cmds.nodes['|first']['attrs'])
        rig=self.ns['build_fk_module']('|first',include_children=True)
        names=self.read(rig)['controller_names'].values()
        self.assertIn('tip_FK_CTRL',names);self.assertIn('tip_FK_CTRL2',names)

    def test_mirror_ambiguous_counterpart_is_reported_without_mutating_source(self):
        targets=self.sides();rig=self.build_kind();self.cmds.delete(targets[0])
        for parent in ('|A','|B'):
            self.cmds.add_node(parent,'transform')
            self.cmds.add_node(parent+'|upper_R_JNT','joint')
        before=self.cmds.copy.deepcopy(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'Ambiguous'):self.ns['mirror_rig_module'](rig['module'])
        self.assertEqual(self.cmds.nodes,before)

    def test_store_default_metadata_failure_keeps_previous_default(self):
        rig=self.build_kind();before=self.read(rig)['defaults']
        self.cmds.setAttr(rig['controls'][0]+'.rotateY',25)
        self.cmds.setAttr(rig['module']+'.rtkRigModuleState',lock=True)
        with self.assertRaisesRegex(ValueError,'metadata is locked'):self.ns['store_rig_default'](rig['module'])
        self.assertEqual(self.read(rig)['defaults'],before)


class IKLengthMathCommands(ModularIKCommands):
    """Evaluate only the installed math nodes; no RP solver/constraint emulation."""
    def connectAttr(self,source,destination):
        if getattr(self,'automatic_units',False) and destination.split('.',1)[1] in ('translateX','translateY','translateZ','upperLength','lowerLength'):
            node=self.add_node('autoLengthConversion'+str(self.serial),'unitConversion')
            self.nodes[node]['attrs']['conversionFactor']=100
            self.inputs[node+'.input']=source
            return super().connectAttr(node+'.output',destination)
        return super().connectAttr(source,destination)

    def evaluate(self,plug):
        import math
        if plug in self.inputs:return self.evaluate(self.inputs[plug])
        node,attr=plug.split('.',1);kind=self.nodes[node]['type'];stored=self.nodes[node]['attrs']
        get=lambda attribute:self.evaluate(node+'.'+attribute)
        if node in getattr(self,'sensors',{}) and attr in ('worldMatrix[0]','worldInverseMatrix[0]'):
            role=self.sensors[node]
            root=self.sensor_root;scale=self.nodes[root]['attrs']['globalScale']
            origin=[self.nodes[root]['attrs'].get('translate'+a,0) for a in 'XYZ']
            point=[0,0,0] if role=='root' else [self.sensor_points[role][i]+self.nodes[node]['attrs'].get('translate'+axis,0) for i,axis in enumerate('XYZ')]
            if attr=='worldInverseMatrix[0]':
                return [1/scale,0,0,0,0,1/scale,0,0,0,0,1/scale,0]+[-v/scale for v in origin]+[1]
            return [scale,0,0,0,0,scale,0,0,0,0,scale,0]+[origin[i]+scale*point[i] for i in range(3)]+[1]
        if kind=='multMatrix' and attr=='matrixSum':
            a,b=get('matrixIn[0]'),get('matrixIn[1]')
            return [sum(a[r*4+k]*b[k*4+c] for k in range(4)) for r in range(4) for c in range(4)]
        if kind=='pointMatrixMult' and attr.startswith('output'):
            matrix=get('inMatrix');point=[get('inPoint'+a) for a in 'XYZ']
            value=tuple(sum(point[k]*matrix[k*4+i] for k in range(3))+matrix[12+i] for i in range(3))
            return value if attr=='output' else value['XYZ'.index(attr[-1])]
        if kind=='distanceBetween' and attr=='distance':
            a,b=get('point1'),get('point2');return math.sqrt(sum((x-y)**2 for x,y in zip(a,b)))
        if kind=='multiplyDivide' and attr.startswith('output'):
            axis=attr[-1];a,b=get('input1'+axis),get('input2'+axis)
            operation=stored.get('operation',1)
            return a*b if operation==1 else a/b if operation==2 else a**b if operation==3 else a
        if kind=='plusMinusAverage' and attr=='output1D':
            a,b=get('input1D[0]'),get('input1D[1]');return a-b if stored.get('operation')==2 else a+b
        if kind=='clamp' and attr=='outputR':return max(get('minR'),min(get('maxR'),get('inputR')))
        if kind=='blendColors' and attr=='outputR':return get('color1R')*get('blender')+get('color2R')*(1-get('blender'))
        if kind=='condition' and attr=='outColorR':
            a,b=get('firstTerm'),get('secondTerm');op=stored['operation']
            test={0:a==b,1:a!=b,2:a>b,3:a>=b,4:a<b,5:a<=b}[op]
            return get('colorIfTrueR' if test else 'colorIfFalseR')
        if kind=='unitConversion' and attr=='output':return get('input')*get('conversionFactor')
        if attr in ('point1','point2'):
            if attr in stored:return tuple(stored[attr])
            return tuple(get(attr+axis) for axis in 'XYZ')
        return stored.get(attr,0)


class IKLengthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.tree=ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())

    def setUp(self):
        ModularIKTests.setUp(self)
        self.cmds=IKLengthMathCommands();self.ns['cmds']=self.cmds
        wanted={'ik_length_solution','enable_ik_length_features','set_ik_length_controls','goto_rig_default','store_rig_default',
                'mirror_rig_module','plan_rig_mirror','_pd_mirror_tokens','_pd_mirror_name','_pd_mirror_object'}
        nodes=[n for n in self.tree.body if isinstance(n,ast.FunctionDef) and (n.name in wanted or n.name.startswith("_constraint_"))]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<IK length API>','exec'),self.ns)

    def build(self):
        result=self.ns['build_ik_module'](*self.cmds.joints)
        state=self.ns['_rig_module_read'](result['module'])[1]
        self.cmds.sensor_root=result['root']
        self.cmds.sensors={result['root']:'root',result['end_controller']:'end',result['pole_controller']:'pole'}
        pole=self.ns['calculate_guide_ik_pole']((0,0,0),(3,2,0),(8,0,0))['position']
        self.cmds.sensor_points={'end':(8,0,0),'pole':pole}
        return result,state

    def solve(self,**kw):return self.ns['ik_length_solution'](4,6,8,5,7,**kw)

    def test_neutral_reference_and_extend_only_stretch(self):
        neutral=self.solve();self.assertEqual((neutral['upper'],neutral['lower'],neutral['goal']),(4,6,8))
        extended=self.ns['ik_length_solution'](4,6,15,5,7,stretch=1)
        self.assertEqual((extended['upper'],extended['lower'],extended['goal']),(6,9,15))
        inside=self.solve(stretch=1);self.assertEqual((inside['upper'],inside['lower']),(4,6))

    def test_partial_stretch_and_no_stretch_goal_clamp(self):
        half=self.ns['ik_length_solution'](4,6,15,5,7,stretch=.5)
        self.assertEqual((half['upper'],half['lower'],half['goal']),(5,7.5,12.5))
        off=self.ns['ik_length_solution'](4,6,15,5,7)
        self.assertEqual(off['goal'],10)

    def test_antipop_soft_reach_is_continuous_at_threshold(self):
        import math
        solve=self.ns['ik_length_solution'];step=1e-5
        a=solve(4,6,8-step,5,7,anti_pop=1)['goal'];b=solve(4,6,8,5,7,anti_pop=1)['goal'];c=solve(4,6,8+step,5,7,anti_pop=1)['goal']
        self.assertAlmostEqual((b-a)/step,1,places=4);self.assertAlmostEqual((c-b)/step,1,places=4)
        maximum=solve(4,6,10,5,7,anti_pop=1)
        self.assertAlmostEqual(maximum['goal'],10-2/math.e)
        self.assertLess(maximum['goal'],10)

    def test_antipop_plus_full_stretch_reaches_target_with_bend_reserve(self):
        value=self.ns['ik_length_solution'](4,6,15,5,7,stretch=1,anti_pop=.6)
        self.assertAlmostEqual(value['goal'],15)
        self.assertGreater(value['upper']+value['lower'],15)

    def test_upper_and_lower_manual_slide_are_independent(self):
        value=self.solve(upper_slide=.25);self.assertEqual((value['upper'],value['lower']),(5,6))
        value=self.solve(lower_slide=-.5);self.assertEqual((value['upper'],value['lower']),(4,3))

    def test_global_slide_preserves_total_and_extremes_stay_positive(self):
        for slide in (-1,-.5,0,.5,1):
            value=self.solve(slide=slide)
            self.assertAlmostEqual(value['upper']+value['lower'],10)
            self.assertGreater(value['upper'],0);self.assertGreater(value['lower'],0)
        self.assertGreater(self.solve(slide=.5)['upper'],4)
        self.assertLess(self.solve(slide=-.5)['upper'],4)

    def test_full_pole_lock_uses_pin_distances_and_raw_end(self):
        value=self.solve(pole_lock=1,anti_pop=1,slide=.5,upper_slide=2)
        self.assertEqual((value['upper'],value['lower'],value['goal']),(5,7,8))

    def test_zero_goal_and_coincident_pole_stay_finite(self):
        import math
        value=self.ns['ik_length_solution'](4,6,0,0,0,stretch=1,anti_pop=1,pole_lock=1)
        self.assertTrue(all(math.isfinite(v) for v in value.values()))
        self.assertGreater(value['upper'],0);self.assertGreater(value['lower'],0)

    def test_invalid_rest_or_nonfinite_data_rejected(self):
        with self.assertRaises(ValueError):self.ns['ik_length_solution'](0,6,8,5,7)
        with self.assertRaises(ValueError):self.solve(stretch=float('nan'))

    def test_built_graph_matches_reference_across_feature_combinations(self):
        import math,itertools
        rig,state=self.build();end=rig['end_controller'];pole=rig['pole_controller']
        lengths=state['ik']['length_system']['rest_lengths']
        for stretch,anti,slide,pin in itertools.product((0,.5,1),(0,.7),(-.4,.4),(0,.3,1)):
            controls={'stretch':stretch,'antiPop':anti,'upperSlide':.2,'lowerSlide':-.1,'slide':slide,'poleLock':pin}
            self.ns['set_ik_length_controls'](rig['module'],controls)
            self.cmds.setAttr(end+'.translateX',4)
            point=self.cmds.sensor_points['pole'];d=12;ap=math.sqrt(sum(v*v for v in point));pc=math.sqrt(sum((point[i]-(12 if i==0 else 0))**2 for i in range(3)))
            expected=self.ns['ik_length_solution'](*lengths,d,ap,pc,stretch=stretch,anti_pop=anti,upper_slide=.2,lower_slide=-.1,slide=slide,pole_lock=pin)
            self.assertAlmostEqual(self.cmds.evaluate(end+'.upperLength'),expected['upper'],places=7)
            self.assertAlmostEqual(self.cmds.evaluate(end+'.lowerLength'),expected['lower'],places=7)
            goal=self.ns['_rig_module_node'](state['ik']['length_system']['goal'])
            self.assertAlmostEqual(self.cmds.evaluate(goal+'.translateX'),expected['goal'],places=7)

    def test_length_outputs_drive_signed_translation_vectors_only(self):
        rig,state=self.build();end=rig['end_controller']
        self.ns['set_ik_length_controls'](rig['module'],{'upperSlide':.25,'lowerSlide':.5})
        for index,identity in enumerate(state['ik']['drivers'][1:]):
            joint=self.ns['_rig_module_node'](identity);ratio=1.25 if index==0 else 1.5
            vector=state['ik']['length_system']['rest_vectors_cm'][index]
            for axis,value in zip('XYZ',vector):self.assertAlmostEqual(self.cmds.evaluate(joint+'.translate'+axis),value*ratio)
            self.assertFalse(any(joint+'.scale'+axis in self.cmds.inputs for axis in 'XYZ'))
        # The original lower vector has negative Y; it remains negative.
        self.assertLess(self.cmds.evaluate(self.ns['_rig_module_node'](state['ik']['drivers'][2])+'.translateY'),0)

    def test_runtime_measurements_do_not_read_solved_driver_matrices(self):
        rig,state=self.build();length_nodes=set(state['ik']['length_system']['nodes'])
        drivers=set(state['ik']['drivers'])
        for destination,source in self.cmds.inputs.items():
            if self.ns['_guide_ik_uuid'](destination.split('.',1)[0]) in length_nodes and 'worldMatrix' in source:
                self.assertNotIn(self.ns['_guide_ik_uuid'](source.split('.',1)[0]),drivers)

    def test_global_scale_and_root_motion_do_not_change_normalized_lengths(self):
        rig,state=self.build();end=rig['end_controller']
        self.ns['set_ik_length_controls'](rig['module'],{'stretch':1,'antiPop':.5})
        self.cmds.setAttr(end+'.translateX',4)
        baseline=self.cmds.evaluate(end+'.upperLength'),self.cmds.evaluate(end+'.lowerLength')
        for scale in (.2,2,5):
            self.cmds.setAttr(rig['root']+'.globalScale',scale);self.cmds.setAttr(rig['root']+'.translateY',10)
            self.assertAlmostEqual(self.cmds.evaluate(end+'.upperLength'),baseline[0]);self.assertAlmostEqual(self.cmds.evaluate(end+'.lowerLength'),baseline[1])

    def test_upgrade_uses_start_joint_anchor_when_it_is_offset_from_root(self):
        rig=self.legacy();state=self.ns['_rig_module_read'](rig['module'])[1]
        start=self.ns['_rig_module_node'](state['ik']['drivers'][0])
        self.cmds.nodes[start]['matrix'][12]=2
        self.cmds.setAttr(start+'.translateX',2)
        self.cmds.setAttr(rig['end_controller']+'.translateX',6)
        self.ns['enable_ik_length_features'](rig['module'])
        state=self.ns['_rig_module_read'](rig['module'])[1]
        features=state['ik']['length_system']
        self.assertEqual(features['start_point_root_cm'],[2,0,0])
        self.cmds.sensor_root=rig['root']
        self.cmds.sensors={rig['root']:'root',rig['end_controller']:'end',rig['pole_controller']:'pole'}
        self.cmds.sensor_points={'end':(8,0,0),'pole':(3,8,0)}
        self.ns['set_ik_length_controls'](rig['module'],{'stretch':1,'antiPop':.5})
        goal=self.ns['_rig_module_node'](features['goal'])
        expected=self.ns['ik_length_solution'](*features['rest_lengths'],12,8,9,stretch=1,anti_pop=.5)
        self.assertAlmostEqual(self.cmds.evaluate(goal+'.translateX'),14)
        self.assertAlmostEqual(self.cmds.evaluate(rig['end_controller']+'.upperLength'),expected['upper'])
        self.assertAlmostEqual(self.cmds.evaluate(rig['end_controller']+'.lowerLength'),expected['lower'])

    def test_auto_unit_conversions_are_owned_and_keep_factor_one(self):
        self.cmds.automatic_units=True;rig,state=self.build()
        conversions=[row for row in state['members'] if row['type']=='unitConversion']
        self.assertTrue(conversions)
        for row in conversions:self.assertEqual(self.cmds.getAttr(self.ns['_rig_module_node'](row['uuid'])+'.conversionFactor'),1)
        self.ns['remove_rig_module'](rig['module'])
        self.assertEqual(set(self.cmds.nodes),set(self.cmds.joints))

    def test_attributes_are_keyable_unlocked_and_default_reset_restores_them(self):
        rig,state=self.build();end=rig['end_controller']
        for name in self.ns['_RIG_MODULE_IK_LENGTH_ATTRS']:
            self.assertTrue(self.cmds.getAttr(end+'.'+name,keyable=True));self.assertFalse(self.cmds.getAttr(end+'.'+name,lock=True))
        self.ns['set_ik_length_controls'](rig['module'],{'stretch':1,'antiPop':.5,'upperSlide':.2,'slide':-.2,'poleLock':.3})
        self.ns['goto_rig_default'](rig['module'])
        for name in self.ns['_RIG_MODULE_IK_LENGTH_ATTRS']:self.assertEqual(self.cmds.getAttr(end+'.'+name),0)

    def test_setter_preflights_all_channels_and_supports_direct_time_keys(self):
        rig,_state=self.build();end=rig['end_controller']
        self.cmds.setAttr(end+'.antiPop',lock=True)
        with self.assertRaises(ValueError):self.ns['set_ik_length_controls'](rig['module'],{'stretch':1,'antiPop':.5})
        self.assertEqual(self.cmds.getAttr(end+'.stretch'),0)
        self.cmds.setAttr(end+'.antiPop',lock=False)
        curve=self.cmds.add_node('lengthCurve','animCurveTU');self.cmds.inputs[end+'.stretch']=curve+'.output'
        with self.assertRaises(ValueError):self.ns['set_ik_length_controls'](rig['module'],{'stretch':1})
        self.ns['set_ik_length_controls'](rig['module'],{'stretch':1},keyframe=True)
        self.assertEqual(self.cmds.inputs[end+'.stretch'],curve+'.output')

    def test_setter_range_errors_do_not_change_any_values(self):
        rig,_state=self.build()
        for values in ({'stretch':2},{'upperSlide':-1},{'poleLock':float('inf')},{'wrong':1}):
            with self.assertRaises(ValueError):self.ns['set_ik_length_controls'](rig['module'],values)

    def test_upgrade_is_idempotent_and_fk_is_rejected(self):
        rig,_state=self.build();before=set(self.cmds.nodes)
        self.assertTrue(self.ns['enable_ik_length_features'](rig['module'])['existing'])
        self.assertEqual(set(self.cmds.nodes),before)
        self.ns['remove_rig_module'](rig['module'])
        fk=self.ns['build_fk_module'](self.cmds.joints)
        with self.assertRaises(ValueError):self.ns['enable_ik_length_features'](fk['module'])

    def test_damaged_length_ownership_stops_removal(self):
        rig,state=self.build();state['ik']['length_system']['goal']=state['joints'][0]['uuid']
        self.cmds.setAttr(rig['module']+'.rtkRigModuleState',json.dumps(state),type='string')
        with self.assertRaisesRegex(ValueError,'length ownership'):self.ns['remove_rig_module'](rig['module'])
        self.assertTrue(self.cmds.objExists(self.cmds.joints[0]))

    def test_removal_deletes_graph_and_keeps_source_channels(self):
        rig,state=self.build();self.ns['set_ik_length_controls'](rig['module'],{'stretch':1,'slide':.2})
        for joint in self.cmds.joints:self.cmds.nodes[joint]['attrs']['translateY']=7
        source={node:self.cmds.copy.deepcopy(self.cmds.nodes[node]) for node in self.cmds.joints}
        self.ns['remove_rig_module'](rig['module'])
        self.assertEqual(set(self.cmds.nodes),set(self.cmds.joints))
        for node in self.cmds.joints:self.assertEqual(self.cmds.nodes[node],source[node])

    def legacy(self):
        original=self.ns['_rig_module_install_lengths']
        self.ns['_rig_module_install_lengths']=lambda *args:None
        try:return self.ns['build_ik_module'](*self.cmds.joints)
        finally:self.ns['_rig_module_install_lengths']=original

    def test_existing_legacy_module_upgrades_preserves_source_and_default_values(self):
        rig=self.legacy();before={node:self.cmds.copy.deepcopy(self.cmds.nodes[node]) for node in self.cmds.joints}
        old=self.ns['_rig_module_read'](rig['module'])[1]
        self.cmds.setAttr(rig['end_controller']+'.translateX',2)
        result=self.ns['enable_ik_length_features'](rig['module'])
        self.assertFalse(result['existing'])
        state=self.ns['_rig_module_read'](rig['module'])[1]
        self.assertIn('length_system',state['ik'])
        self.assertEqual(state['defaults'][0],old['defaults'][0])
        self.assertEqual(self.cmds.getAttr(rig['end_controller']+'.translateX'),2)
        for node in self.cmds.joints:self.assertEqual(self.cmds.nodes[node],before[node])
        self.ns['goto_rig_default'](rig['module'])
        self.assertEqual(self.cmds.getAttr(rig['end_controller']+'.stretch'),0)
        self.ns['remove_rig_module'](rig['module'])
        self.assertEqual(set(self.cmds.nodes),set(self.cmds.joints))

    def test_upgrade_refuses_existing_custom_attribute_without_overwriting_it(self):
        rig=self.legacy();self.cmds.addAttr(rig['end_controller'],longName='stretch',attributeType='double',defaultValue=.7)
        before=self.cmds.copy.deepcopy(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'custom attribute'):self.ns['enable_ik_length_features'](rig['module'])
        self.assertEqual(self.cmds.nodes,before)

    def test_upgrade_failure_restores_legacy_parent_graph_and_attrs(self):
        rig=self.legacy();before=self.cmds.copy.deepcopy(self.cmds.nodes);edges=dict(self.cmds.inputs)
        original=self.cmds.createNode
        def fail(kind,*args,**kw):
            if kind=='clamp':raise RuntimeError('Graph failed')
            return original(kind,*args,**kw)
        self.cmds.createNode=fail
        with self.assertRaisesRegex(RuntimeError,'rolled back'):self.ns['enable_ik_length_features'](rig['module'])
        self.assertEqual(self.cmds.nodes,before);self.assertEqual(self.cmds.inputs,edges)

    def test_pose_drift_during_upgrade_rolls_back(self):
        rig=self.legacy();before=self.cmds.copy.deepcopy(self.cmds.nodes)
        original=self.ns['_rig_module_install_lengths']
        def drift(*args):
            result=original(*args);self.cmds.nodes[self.cmds.joints[1]]['matrix'][12]+=1
            return result
        self.ns['_rig_module_install_lengths']=drift
        with self.assertRaisesRegex(RuntimeError,'rolled back'):self.ns['enable_ik_length_features'](rig['module'])
        self.assertEqual(self.cmds.nodes,before)

    def test_length_control_set_failure_restores_all_prior_values(self):
        rig,_state=self.build();before=self.cmds.copy.deepcopy(self.cmds.nodes)
        original=self.cmds.setAttr
        def fail(plug,*values,**kw):
            if plug.endswith('.antiPop') and values:raise RuntimeError('Setter failed')
            return original(plug,*values,**kw)
        self.cmds.setAttr=fail
        with self.assertRaisesRegex(RuntimeError,'rolled back'):
            self.ns['set_ik_length_controls'](rig['module'],{'stretch':1,'antiPop':.5})
        self.assertEqual(self.cmds.nodes,before)


class IKFKCommands(IKLengthMathCommands):
    """Two-target constraint plumbing and simple template decomposition, not IK."""
    def _weighted(self,kind,args,kw):
        if kw.get('query'):
            return self.nodes[args[0]]['attrs']['weight_aliases'][:]
        targets,driven=list(args[:-1]),args[-1]
        result=self._pair(kind,targets[0],driven,kw)
        node=result[0]
        aliases=['driverWeight'+str(i) for i in range(len(targets))]
        self.nodes[node]['attrs']['weight_aliases']=aliases
        self.nodes[node]['targets']=targets
        for i,target in enumerate(targets):self.inputs[node+'.target['+str(i)+'].targetParentMatrix']=target+'.worldMatrix[0]'
        return result

    def parentConstraint(self,*args,**kw):return self._weighted('parentConstraint',args,kw)
    def scaleConstraint(self,*args,**kw):return self._weighted('scaleConstraint',args,kw)
    def dgdirty(self,node):self.calls.append(('dgdirty',node))

    def xform(self,node,**kw):
        result=super().xform(node,**kw)
        if not kw.get('query') and 'rtkIKFKMatch_' in node and ('matrix' in kw or 'translation' in kw):
            world=list(kw['matrix']) if 'matrix' in kw else self.nodes[node]['matrix'][:]
            if 'translation' in kw:world[12:15]=kw['translation']
            parent=(self.listRelatives(node,parent=True) or [None])[0]
            pm=self.nodes[parent]['matrix'] if parent else self.matrix(0,0,0)
            for i,axis in enumerate('XYZ'):
                self.nodes[node]['attrs']['translate'+axis]=world[12+i]-pm[12+i]
                self.nodes[node]['attrs']['scale'+axis]=sum(world[i*4+k]**2 for k in range(3))**.5
        return result


class IKFKTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.tree=ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())

    def setUp(self):
        IKLengthTests.setUp(self)
        self.cmds=IKFKCommands();self.ns['cmds']=self.cmds
        wanted={'build_ikfk_module','set_ikfk_blend','switch_ikfk','rename_rig_controllers'}
        nodes=[n for n in self.tree.body if isinstance(n,ast.FunctionDef) and (n.name in wanted or n.name.startswith("_constraint_"))]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<IKFK API>','exec'),self.ns)

    def build(self,**kw):
        rig=self.ns['build_ikfk_module'](*self.cmds.joints,**kw)
        state=self.ns['_rig_module_read'](rig['module'])[1]
        self.cmds.sensor_root=rig['root']
        self.cmds.sensors={rig['root']:'root',rig['end_controller']:'end',rig['pole_controller']:'pole',rig['base_controller']:'base'}
        pole=self.ns['calculate_guide_ik_pole']((0,0,0),(3,2,0),(8,0,0))['position']
        self.cmds.sensor_points={'end':(8,0,0),'pole':pole,'base':(0,0,0)}
        return rig,state

    def test_build_is_one_owned_module_with_seven_animator_roles(self):
        rig,state=self.build()
        self.assertEqual(state['type'],'IKFK');self.assertEqual(len(state['ui_controls']),6)
        self.assertEqual(len(self.ns['_rig_module_controller_roles'](state)),7)
        self.assertEqual(self.cmds.chunks,['open','close'])
        self.assertEqual(self.ns['list_rig_modules'](),[rig['module']])
        self.assertEqual(self.cmds.getAttr(rig['root']+'.ikFkBlend'),0)
        self.assertFalse(self.cmds.getAttr(rig['root']+'.ikFkBlend',lock=True))
        self.assertTrue(self.cmds.getAttr(rig['root']+'.ikFkBlend',keyable=True))
        self.assertEqual(self.ns['_rig_module_node'](state['ik']['driver_group']).rsplit('|',1)[0],rig['base_controller'])

    def test_each_source_has_two_weighted_targets_and_shortest_rotation(self):
        rig,state=self.build()
        for index,row in enumerate(state['controls']):
            for identity in row['constraints']:
                constraint=self.ns['_rig_module_node'](identity)
                self.assertEqual(self.cmds.nodes[constraint]['targets'],[self.ns['_rig_module_node'](row['control']),rig['fk_controllers'][index]])
                if self.cmds.nodeType(constraint)=='parentConstraint':self.assertEqual(self.cmds.getAttr(constraint+'.interpType'),2)
                for value in (0,.25,.5,1):
                    self.ns['set_ikfk_blend'](rig['module'],value)
                    weights=[self.cmds.evaluate(constraint+'.driverWeight'+str(i)) for i in (0,1)]
                    self.assertEqual(weights,[value,1-value])

    def test_visibility_fk_ik_and_both_during_blend(self):
        rig,state=self.build();fk=self.ns['_rig_module_node'](state['ikfk']['fk_group'])
        ik_zero=(self.cmds.listRelatives(rig['end_controller'],parent=True) or [None])[0]
        for value,expected in ((0,(1,0)),(.5,(1,1)),(1,(0,1))):
            self.ns['set_ikfk_blend'](rig['module'],value)
            self.assertEqual((self.cmds.evaluate(fk+'.visibility'),self.cmds.evaluate(ik_zero+'.visibility')),expected)

    def test_connected_or_animation_overshoot_cannot_make_negative_weights(self):
        rig,state=self.build();constraint=self.ns['_rig_module_node'](state['controls'][0]['constraints'][0])
        for value,expected in ((-2,[0,1]),(3,[1,0])):
            self.cmds.setAttr(rig['root']+'.ikFkBlend',value)
            self.assertEqual([self.cmds.evaluate(constraint+'.driverWeight'+str(i)) for i in (0,1)],expected)

    def test_dynamic_base_anchor_measures_without_reading_solved_joints(self):
        rig,state=self.build();end=rig['end_controller']
        self.ns['set_ik_length_controls'](rig['module'],{'stretch':1})
        self.cmds.setAttr(end+'.translateX',6);self.cmds.setAttr(rig['base_controller']+'.translateX',2)
        expected=self.ns['ik_length_solution'](*state['ik']['length_system']['rest_lengths'],12,5,6,stretch=1)
        self.assertAlmostEqual(self.cmds.evaluate(end+'.upperLength'),expected['upper'])
        goal=self.ns['_rig_module_node'](state['ik']['length_system']['goal'])
        self.assertAlmostEqual(self.cmds.evaluate(goal+'.translateX'),14)
        drivers=set(state['ik']['drivers']);nodes=set(state['ik']['length_system']['nodes'])
        for destination,source in self.cmds.inputs.items():
            if self.ns['_guide_ik_uuid'](destination.split('.',1)[0]) in nodes and 'worldMatrix' in source:
                self.assertNotIn(self.ns['_guide_ik_uuid'](source.split('.',1)[0]),drivers)

    def test_defaults_include_blend_without_moving_root_or_global_scale(self):
        rig,state=self.build();root=rig['root']
        self.ns['set_ikfk_blend'](rig['module'],.6)
        self.cmds.setAttr(root+'.translateX',7);self.cmds.setAttr(root+'.globalScale',2)
        self.cmds.setAttr(rig['base_controller']+'.translateY',3)
        self.ns['goto_rig_default'](rig['module'])
        self.assertEqual(self.cmds.getAttr(root+'.ikFkBlend'),0)
        self.assertEqual(self.cmds.getAttr(root+'.translateX'),7)
        self.assertEqual(self.cmds.getAttr(root+'.globalScale'),2)
        self.assertEqual(self.cmds.getAttr(rig['base_controller']+'.translateY'),0)

    def test_store_default_and_restore_blend_and_all_control_roles(self):
        rig,state=self.build();self.ns['set_ikfk_blend'](rig['module'],.3)
        self.cmds.setAttr(rig['fk_controllers'][1]+'.rotateY',25)
        self.ns['store_rig_default'](rig['module'])
        self.ns['set_ikfk_blend'](rig['module'],1);self.cmds.setAttr(rig['fk_controllers'][1]+'.rotateY',0)
        self.ns['goto_rig_default'](rig['module'])
        self.assertEqual(self.cmds.getAttr(rig['root']+'.ikFkBlend'),.3)
        self.assertEqual(self.cmds.getAttr(rig['fk_controllers'][1]+'.rotateY'),25)

    def test_removal_owns_fk_ik_and_blend_graph_keeps_source_definitions(self):
        rig,state=self.build();source={n:self.cmds.copy.deepcopy(self.cmds.nodes[n]) for n in self.cmds.joints}
        self.ns['set_ikfk_blend'](rig['module'],.4)
        self.ns['remove_rig_module'](rig['module'])
        self.assertEqual(set(self.cmds.nodes),set(self.cmds.joints))
        for node in self.cmds.joints:self.assertEqual(self.cmds.nodes[node],source[node])

    def test_constraint_alias_failure_rolls_back_entire_build(self):
        before=self.cmds.copy.deepcopy(self.cmds.nodes)
        original=self.cmds.parentConstraint
        def fail(*args,**kw):return [] if kw.get('query') else original(*args,**kw)
        self.cmds.parentConstraint=fail
        with self.assertRaisesRegex(RuntimeError,'rolled back'):self.build()
        self.assertEqual(self.cmds.nodes,before);self.assertFalse(self.cmds.inputs)

    def test_source_pose_drift_rolls_back_entire_build(self):
        original=self.cmds.scaleConstraint;before=self.cmds.copy.deepcopy(self.cmds.nodes)
        def drift(*args,**kw):
            result=original(*args,**kw)
            if not kw.get('query'):self.cmds.nodes[args[-1]]['matrix'][12]+=1
            return result
        self.cmds.scaleConstraint=drift
        with self.assertRaisesRegex(RuntimeError,'rolled back'):self.build()
        self.assertEqual(self.cmds.nodes,before)

    def test_custom_names_and_rename_include_base_and_fk_roles(self):
        overrides={'root':'master','base':'hip_CTL','end':'foot_CTL','pole':'knee_CTL',self.ns['_guide_ik_uuid'](self.cmds.joints[1]):'midFK_CTL'}
        rig,state=self.build(controller_names=overrides)
        for role,name in overrides.items():self.assertEqual(state['controller_names'][role],name)
        names=self.ns['rename_rig_controllers'](rig['module'])
        self.assertEqual(len(names),7);self.assertEqual(names['root'],'first_IKFK_ROOT')

    def test_mirror_builds_same_type_and_maps_fk_role_uuids(self):
        targets=RigModuleActionsTests.sides(self)
        rig,state=self.build(name='arm_L',pole_distance=2)
        before={n:self.cmds.copy.deepcopy(self.cmds.nodes[n]) for n in self.cmds.nodes}
        mirrored=self.ns['mirror_rig_module'](rig['module'])
        other=self.ns['_rig_module_read'](mirrored['module'])[1]
        self.assertEqual(other['type'],'IKFK');self.assertEqual(other['pole_distance'],2)
        self.assertTrue(all('_R' in name for name in other['controller_names'].values()))
        self.assertEqual(self.cmds.getAttr(mirrored['root']+'.ikFkBlend'),0)
        for node in before:self.assertEqual(self.cmds.nodes[node],before[node])

    def test_blend_rejects_invalid_values_foreign_inputs_and_locks(self):
        rig,state=self.build();root=rig['root'];before=self.cmds.copy.deepcopy(self.cmds.nodes)
        for value in (-1,2,float('nan')):
            with self.assertRaises(ValueError):self.ns['set_ikfk_blend'](rig['module'],value)
        self.assertEqual(self.cmds.nodes,before)
        foreign=self.cmds.add_node('|SDKDriver','animCurveUU');self.cmds.inputs[root+'.ikFkBlend']=foreign+'.output'
        with self.assertRaises(ValueError):self.ns['set_ikfk_blend'](rig['module'],1,keyframe=True)
        self.assertEqual(self.cmds.inputs[root+'.ikFkBlend'],foreign+'.output')

    def test_blend_and_switch_support_time_keys_and_dirty_destination(self):
        rig,state=self.build();root=rig['root']
        curve=self.cmds.add_node('|timeCurve','animCurveTU');self.cmds.inputs[root+'.ikFkBlend']=curve+'.output'
        self.ns['set_ikfk_blend'](rig['module'],1,keyframe=True)
        self.assertEqual(self.cmds.inputs[root+'.ikFkBlend'],curve+'.output')
        self.ns['switch_ikfk'](rig['module'],'FK',keyframe=True)
        self.assertTrue(any(call[0]=='dgdirty' for call in self.cmds.calls))
        self.assertTrue(any(call[0]=='setKeyframe' and call[1] in rig['fk_controllers'] for call in self.cmds.calls))

    def test_match_switch_fk_preserves_sources_and_leaves_no_temporary_nodes(self):
        rig,state=self.build();self.ns['set_ikfk_blend'](rig['module'],1)
        before={n:self.cmds.copy.deepcopy(self.cmds.nodes[n]) for n in self.cmds.joints}
        result=self.ns['switch_ikfk'](rig['module'],'FK')
        self.assertEqual(result['controllers'],rig['fk_controllers'])
        self.assertEqual(self.cmds.getAttr(rig['root']+'.ikFkBlend'),0)
        self.assertFalse(any('rtkIKFKMatch_' in n for n in self.cmds.nodes))
        for n in self.cmds.joints:self.assertEqual(self.cmds.nodes[n],before[n])

    def test_match_switch_ik_calculates_lengths_and_clears_soft_slide_pin(self):
        rig,state=self.build();end=rig['end_controller']
        self.ns['set_ik_length_controls'](rig['module'],{'antiPop':1,'slide':.3,'poleLock':1})
        self.ns['switch_ikfk'](rig['module'],'IK')
        self.assertEqual(self.cmds.getAttr(rig['root']+'.ikFkBlend'),1)
        for name,value in {'stretch':1,'antiPop':0,'upperSlide':0,'lowerSlide':0,'slide':0,'poleLock':0}.items():
            self.assertAlmostEqual(self.cmds.getAttr(end+'.'+name),value)
        self.assertFalse(any('rtkIKFKMatch_' in n for n in self.cmds.nodes))

    def test_match_uses_linear_typed_positions_instead_of_matrix_ui_units(self):
        rig,state=self.build();self.cmds.linear_unit='m'
        original=self.cmds.xform
        def meter_positions(node,**kw):
            result=original(node,**kw)
            if kw.get('query') and kw.get('translation'):return [v/100 for v in result]
            return result
        self.cmds.xform=meter_positions
        self.ns['switch_ikfk'](rig['module'],'IK')
        self.assertAlmostEqual(self.cmds.getAttr(rig['end_controller']+'.upperSlide'),0)
        self.assertAlmostEqual(self.cmds.getAttr(rig['end_controller']+'.lowerSlide'),0)

    def test_match_preflight_checks_all_controls_before_writing(self):
        rig,state=self.build();self.cmds.setAttr(rig['fk_controllers'][2]+'.translateX',lock=True)
        before=self.cmds.copy.deepcopy(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'locked'):self.ns['switch_ikfk'](rig['module'],'FK')
        self.assertEqual(self.cmds.nodes,before)

    def test_match_foreign_compound_driver_is_not_overwritten(self):
        rig,state=self.build();foreign=self.cmds.add_node('|foreign','transform')
        plug=rig['fk_controllers'][1]+'.rotate';self.cmds.inputs[plug]=foreign+'.rotate'
        before=self.cmds.copy.deepcopy(self.cmds.nodes)
        with self.assertRaises(ValueError):self.ns['switch_ikfk'](rig['module'],'FK',keyframe=True)
        self.assertEqual(self.cmds.nodes,before);self.assertEqual(self.cmds.inputs[plug],foreign+'.rotate')

    def test_match_write_failure_rolls_back_controls_blend_and_temporaries(self):
        rig,state=self.build();before=self.cmds.copy.deepcopy(self.cmds.nodes);inputs=dict(self.cmds.inputs)
        original=self.cmds.setAttr
        def fail(plug,*values,**kw):
            if plug==rig['fk_controllers'][1]+'.rotateZ' and values:raise RuntimeError('Control set failed')
            return original(plug,*values,**kw)
        self.cmds.setAttr=fail
        with self.assertRaisesRegex(RuntimeError,'rolled back'):self.ns['switch_ikfk'](rig['module'],'FK')
        self.assertEqual(self.cmds.nodes,before);self.assertEqual(self.cmds.inputs,inputs)

    def test_unrepresentable_solver_pose_rolls_back_instead_of_accepting_jump(self):
        rig,state=self.build();before=self.cmds.copy.deepcopy(self.cmds.nodes);inputs=dict(self.cmds.inputs)
        original=self.ns['_rig_module_ikfk_match_matrix']
        def drift(*args):
            original(*args);self.cmds.nodes[self.cmds.joints[1]]['matrix'][12]+=1
        self.ns['_rig_module_ikfk_match_matrix']=drift
        with self.assertRaisesRegex(RuntimeError,'current pose was kept'):self.ns['switch_ikfk'](rig['module'],'IK')
        self.assertEqual(self.cmds.nodes,before);self.assertEqual(self.cmds.inputs,inputs)

    def test_straight_pose_keeps_current_pole_side(self):
        pole=self.ns['_rig_module_ikfk_pole']([(0,0,0),(4,0,0),(8,0,0)],(3,-6,0),1)
        self.assertEqual(pole,[4,-8,0])
        with self.assertRaises(ValueError):self.ns['_rig_module_ikfk_pole']([(0,0,0),(4,0,0),(8,0,0)],(3,0,0),1)

    def test_matching_length_range_error_makes_no_changes(self):
        rig,state=self.build();self.cmds.nodes[self.cmds.joints[2]]['matrix'][12]=200
        before=self.cmds.copy.deepcopy(self.cmds.nodes)
        with self.assertRaisesRegex(ValueError,'slide range'):self.ns['switch_ikfk'](rig['module'],'IK')
        self.assertEqual(self.cmds.nodes,before)

    def test_damaged_fk_ownership_blocks_removal(self):
        rig,state=self.build();state['ikfk']['fk_controls'][0]=state['joints'][0]['uuid']
        self.cmds.setAttr(rig['module']+'.rtkRigModuleState',json.dumps(state),type='string')
        with self.assertRaisesRegex(ValueError,'IK/FK ownership'):self.ns['remove_rig_module'](rig['module'])

    def test_blend_and_matching_reject_other_module_types_and_disabled_undo(self):
        old=self.ns['build_ik_module'](*self.cmds.joints)
        with self.assertRaises(ValueError):self.ns['set_ikfk_blend'](old['module'],1)
        with self.assertRaises(ValueError):self.ns['switch_ikfk'](old['module'],'FK')
        self.ns['remove_rig_module'](old['module']);rig,state=self.build();self.cmds.enabled=False
        with self.assertRaises(ValueError):self.ns['switch_ikfk'](rig['module'],'FK')


class XMatrixCommands(IKFKCommands):
    """Matrix/DAG arithmetic only: no RP solve, native JO or Euler decomposition."""
    @staticmethod
    def ident():return [float(r==c) for r in range(4) for c in range(4)]
    @staticmethod
    def product(a,b):return [sum(a[r*4+k]*b[k*4+c] for k in range(4)) for r in range(4) for c in range(4)]
    @classmethod
    def inverse(cls,a):
        # Independent inverse for the uniform, orthogonal affine fixtures.
        s2=sum(v*v for v in a[:3]);out=cls.ident()
        for r in range(3):
            for c in range(3):out[r*4+c]=a[c*4+r]/s2
        out[12:15]=[-sum(a[12+k]*out[k*4+c] for k in range(3)) for c in range(3)]
        return out

    @staticmethod
    def quaternion(matrix):
        import math
        # Convert row-vector rotation via transposed column convention.
        m=[[matrix[c*4+r] for c in range(3)] for r in range(3)]
        trace=sum(m[i][i] for i in range(3))
        if trace>0:
            t=math.sqrt(trace+1)*2
            return ((m[2][1]-m[1][2])/t,(m[0][2]-m[2][0])/t,(m[1][0]-m[0][1])/t,t/4)
        i=max(range(3),key=lambda j:m[j][j]);j=(i+1)%3;k=(i+2)%3
        t=math.sqrt(1+m[i][i]-m[j][j]-m[k][k])*2;q=[0,0,0,0]
        q[i]=t/4;q[j]=(m[i][j]+m[j][i])/t;q[k]=(m[i][k]+m[k][i])/t;q[3]=(m[k][j]-m[j][k])/t
        return tuple(q)

    @classmethod
    def quaternion_matrix(cls,q):
        x,y,z,w=q;n=sum(v*v for v in q)**.5;x,y,z,w=(v/n for v in q)
        result=cls.ident()
        rows=((1-2*(y*y+z*z),2*(x*y+z*w),2*(x*z-y*w)),
              (2*(x*y-z*w),1-2*(x*x+z*z),2*(y*z+x*w)),
              (2*(x*z+y*w),2*(y*z-x*w),1-2*(x*x+y*y)))
        for i,row in enumerate(rows):result[i*4:i*4+3]=row
        return result

    @staticmethod
    def slerp(a,b,w):
        import math
        dot=sum(x*y for x,y in zip(a,b))
        if dot<0:b=tuple(-v for v in b);dot=-dot
        if dot>.9995:
            q=tuple(x*(1-w)+y*w for x,y in zip(a,b));n=sum(v*v for v in q)**.5
            return tuple(v/n for v in q)
        theta=math.acos(min(1,dot));den=math.sin(theta)
        return tuple((x*math.sin((1-w)*theta)+y*math.sin(w*theta))/den for x,y in zip(a,b))

    def __init__(self):
        super().__init__()
        for node in self.joints:
            data=self.nodes[node];parent=(self.listRelatives(node,parent=True) or [None])[0]
            local=self.product(data['matrix'],self.inverse(self.nodes[parent]['matrix'])) if parent else data['matrix'][:]
            data['local_matrix']=local
            for i,a in enumerate('XYZ'):data['attrs']['translate'+a]=local[12+i]
            data['attrs'].update({'offsetParentMatrix':self.ident(),'inheritsTransform':True,'inverseScale':[(1,1,1)]})

    def attributeQuery(self,attribute,node,**kw):
        if attribute in ('offsetParentMatrix','inheritsTransform','inverseScale') and self.nodes[node]['type'] in ('joint','transform'):return True
        return super().attributeQuery(attribute,node,**kw)

    def local(self,node):
        data=self.nodes[node];local=data.get('local_matrix',self.ident())[:]
        for i,a in enumerate('XYZ'):
            base=sum(v*v for v in local[i*4:i*4+3])**.5
            scale=self.evaluate(node+'.scale'+a)
            if base:
                for j in range(3):local[i*4+j]*=scale/base
            local[12+i]=self.evaluate(node+'.translate'+a)
        return local

    def world(self,node):
        parent=(self.listRelatives(node,parent=True) or [None])[0]
        opm=self.evaluate(node+'.offsetParentMatrix')
        result=self.product(self.local(node),opm)
        return self.product(result,self.world(parent)) if parent and self.nodes[node]['attrs'].get('inheritsTransform',True) else result

    def getAttr(self,plug,**kw):
        if kw.get('lock') or kw.get('keyable') or kw.get('settable'):return super().getAttr(plug,**kw)
        node,attribute=plug.split('.',1)
        if attribute=='worldMatrix[0]':return tuple(self.world(node))
        if attribute=='worldInverseMatrix[0]':return tuple(self.inverse(self.world(node)))
        if attribute=='matrix':return tuple(self.local(node))
        if attribute=='offsetParentMatrix':return tuple(self.evaluate(plug))
        if attribute=='inheritsTransform':return self.nodes[node]['attrs'].get(attribute,True)
        if attribute=='inverseScale':return [(1,1,1)]
        return super().getAttr(plug,**kw)

    def parent(self,node,group,**kw):
        world=self.world(node) if kw.get('absolute') else None
        result=super().parent(node,group,**kw)
        if world is not None:self.xform(result[0],worldSpace=True,matrix=world)
        return result

    def xform(self,node,**kw):
        if kw.get('query'):
            world=self.world(node)
            return world[12:15] if kw.get('translation') else world
        if 'matrix' in kw or 'translation' in kw:
            world=list(kw['matrix']) if 'matrix' in kw else self.world(node)
            if 'translation' in kw:world[12:15]=kw['translation']
            parent=(self.listRelatives(node,parent=True) or [None])[0]
            local=self.product(world,self.inverse(self.world(parent))) if parent else world[:]
            self.nodes[node]['local_matrix']=local
            self.nodes[node]['matrix']=world
            for i,a in enumerate('XYZ'):
                self.nodes[node]['attrs']['translate'+a]=local[12+i]
                self.nodes[node]['attrs']['scale'+a]=sum(v*v for v in local[i*4:i*4+3])**.5
            return
        return super().xform(node,**kw)

    def matchTransform(self,node,target,**kw):
        world=self.world(target)
        if not kw.get('scale'):
            old=self.world(node)
            for i in range(3):
                ratio=(sum(v*v for v in old[i*4:i*4+3])/sum(v*v for v in world[i*4:i*4+3]))**.5
                for j in range(3):world[i*4+j]*=ratio
        self.xform(node,worldSpace=True,matrix=world)

    def createNode(self,kind,name,**kw):
        node=super().createNode(kind,name,**kw)
        if kind=='locator' and kw.get('parent'):node=self.parent(node,kw['parent'],relative=True)[0]
        return node

    def makeIdentity(self,node,**kw):self.calls.append(('makeIdentity',node,kw))

    def evaluate(self,plug):
        if plug in self.inputs:return self.evaluate(self.inputs[plug])
        node,attr=plug.split('.',1);data=self.nodes[node];kind=data['type'];stored=data['attrs']
        get=lambda a:self.evaluate(node+'.'+a)
        if attr=='worldMatrix[0]':return self.world(node)
        if attr=='worldInverseMatrix[0]':return self.inverse(self.world(node))
        if attr=='offsetParentMatrix':return list(stored.get(attr,self.ident()))
        if attr in ('scale','inputScale','inputTranslate'):
            if attr in stored:return stored[attr]
            return tuple(get(attr+a) for a in 'XYZ')
        if kind=='multMatrix' and attr=='matrixSum':
            indices={int(key.split('[')[1].split(']')[0]) for key in stored if key.startswith('matrixIn[')}
            indices.update(int(key.split('matrixIn[')[1].split(']')[0]) for key in self.inputs if key.startswith(node+'.matrixIn['))
            value=self.ident()
            for i in sorted(indices):value=self.product(value,get('matrixIn['+str(i)+']'))
            return value
        if kind=='inverseMatrix' and attr=='outputMatrix':return self.inverse(get('inputMatrix'))
        if kind=='composeMatrix' and attr=='outputMatrix':
            result=self.quaternion_matrix(get('inputQuat')) if 'useEulerRotation' in stored and not get('useEulerRotation') else self.ident()
            scale=get('inputScale')
            for i in range(3):
                for j in range(3):result[i*4+j]*=scale[i]
            result[12:15]=get('inputTranslate')
            return result
        if kind=='decomposeMatrix' and attr.startswith('output'):
            matrix=get('inputMatrix')
            if attr.startswith('outputScale'):values=tuple(sum(v*v for v in matrix[i*4:i*4+3])**.5 for i in range(3));base='outputScale';axes='XYZ'
            elif attr.startswith('outputTranslate'):values=tuple(matrix[12:15]);base='outputTranslate';axes='XYZ'
            else:values=self.quaternion(matrix);base='outputQuat';axes='XYZW'
            return values if attr==base else values[axes.index(attr[-1])]
        if kind=='vectorProduct' and attr.startswith('output'):
            values=tuple(get('input1'+a) for a in 'XYZ');norm=sum(v*v for v in values)**.5
            if get('normalizeOutput'):values=tuple(v/norm for v in values)
            return values if attr=='output' else values['XYZ'.index(attr[-1])]
        if kind=='pickMatrix' and attr=='outputMatrix':
            result=list(get('inputMatrix'))
            for i in range(3):
                size=sum(v*v for v in result[i*4:i*4+3])**.5
                for j in range(3):result[i*4+j]/=size
            return result
        if kind=='blendMatrix' and attr=='outputMatrix':
            a,b,weight=get('inputMatrix'),get('target[0].targetMatrix'),get('target[0].weight')
            result=self.quaternion_matrix(self.slerp(self.quaternion(a),self.quaternion(b),weight))
            for i in range(3):result[12+i]=a[12+i]*(1-weight)+b[12+i]*weight
            return result
        if attr.startswith('inputScale') and attr[-1] in 'XYZ':return stored.get(attr,1)
        if kind in ('joint','transform') and attr.startswith('scale') and attr[-1] in 'XYZ':return stored.get(attr,1)
        return super().evaluate(plug)


class XMatrixIKTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.tree=ast.parse(Path(__file__).with_name('master_rigging_toolkit.py').read_text())
    def setUp(self):
        IKFKTests.setUp(self)
        self.cmds=XMatrixCommands();self.ns['cmds']=self.cmds
        previous=self.ns['build_ik_module']
        def matrix_default(*args,**kw):
            kw.setdefault('_matrix_solver',True)
            return previous(*args,**kw)
        self.ns['build_ik_module']=matrix_default
    def build(self,kind='IK3',**kw):
        rig=self.ns['build_ik_module'](*self.cmds.joints,_module_type=kind,_matrix_solver=True,**kw)
        return rig,self.ns['_rig_module_read'](rig['module'])[1]
    def assertMatrix(self,a,b):
        for x,y in zip(a,b):self.assertAlmostEqual(x,y,places=6)

    def test_default_backend_has_two_locator_buffers_and_no_source_scale_constraints(self):
        rig,state=self.build()
        self.assertEqual(state['ik']['solver'],'x_translate_v1')
        self.assertEqual(sum(row['type']=='locator' for row in state['members']),2)
        self.assertEqual(len(state['ik']['orientation_buffers']),2)
        self.assertFalse(any(row['type'] in ('scaleConstraint','parentConstraint') for row in state['members']))
        for node in self.cmds.joints:
            self.assertEqual([p.split('.',1)[1] for p in self.cmds.inputs if p.split('.',1)[0]==node],['offsetParentMatrix'])

    def test_x_frames_aim_at_children_are_unit_orthogonal_and_right_handed(self):
        points=[(2,3,-1),(-3,5,2),(-8,-2,4)]
        frames=self.ns['_rig_module_x_frames'](points)
        for i in range(2):
            direction=[points[i+1][j]-points[i][j] for j in range(3)];length=sum(v*v for v in direction)**.5
            self.assertMatrix(frames[i][:3],[v/length for v in direction])
            axes=[frames[i][k:k+3] for k in (0,4,8)]
            for a in axes:self.assertAlmostEqual(sum(v*v for v in a),1)
            for a,b in ((0,1),(1,2),(0,2)):self.assertAlmostEqual(sum(x*y for x,y in zip(axes[a],axes[b])),0)
            a,b,c=axes;self.assertAlmostEqual(a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0]),1)

    def test_second_and_third_only_have_positive_rest_tx_and_driven_tx(self):
        rig,state=self.build()
        for identity in state['ik']['drivers'][1:]:
            node=self.ns['_rig_module_node'](identity)
            self.assertGreater(self.cmds.getAttr(node+'.translateX'),0)
            for axis in 'YZ':
                self.assertEqual(self.cmds.getAttr(node+'.translate'+axis),0)
                self.assertNotIn(node+'.translate'+axis,self.cmds.inputs)
            for axis in 'XYZ':self.assertNotIn(node+'.scale'+axis,self.cmds.inputs)
        freezes=[c for c in self.cmds.calls if c[0]=='makeIdentity']
        self.assertEqual(len(freezes),3);self.assertTrue(all(c[2]['rotate'] and not c[2]['scale'] for c in freezes))

    def test_length_factors_multiply_default_tx_and_never_change_scales(self):
        rig,state=self.build();end=rig['end_controller']
        original={n:tuple(self.cmds.getAttr(n+'.scale'+a) for a in 'XYZ') for n in self.cmds.joints}
        self.ns['set_ik_length_controls'](rig['module'],{'upperSlide':.25,'lowerSlide':-.2})
        for i,factor in enumerate((1.25,.8)):
            node=self.ns['_rig_module_node'](state['ik']['drivers'][i+1])
            self.assertAlmostEqual(self.cmds.evaluate(node+'.translateX'),state['ik']['length_system']['rest_vectors_cm'][i][0]*factor)
        for n,scales in original.items():self.assertEqual(tuple(self.cmds.getAttr(n+'.scale'+a) for a in 'XYZ'),scales)
        for n in self.cmds.joints:
            world=self.cmds.world(n)
            self.assertAlmostEqual(sum(v*v for v in world[:3])**.5,1)

    def test_orientation_offsets_reproduce_original_frames_at_bind(self):
        before=[self.cmds.world(n) for n in self.cmds.joints]
        rig,state=self.build()
        for i,identity in enumerate(state['ik']['outputs']):self.assertMatrix(self.cmds.world(self.ns['_rig_module_node'](identity)),before[i])
        for i,n in enumerate(self.cmds.joints):self.assertMatrix(self.cmds.world(n),before[i])

    def test_source_trs_jo_ra_and_ssc_are_preserved(self):
        saved={n:{k:self.cmds.copy.deepcopy(v) for k,v in self.cmds.nodes[n]['attrs'].items() if k!='offsetParentMatrix'} for n in self.cmds.joints}
        rig,state=self.build()
        for n in self.cmds.joints:
            for k,v in saved[n].items():self.assertEqual(self.cmds.nodes[n]['attrs'][k],v)

    def test_matrix_compensation_handles_nonidentity_local_and_parent_frames(self):
        # Independent affine fixture includes rotation, translation, scale and
        # a preexisting offset. OPM = inv(local) * desired * inv(actual parent).
        local=[0,2,0,0,-2,0,0,0,0,0,2,0,3,4,5,1]
        parent=[0,0,-3,0,0,3,0,0,3,0,0,0,7,-2,8,1]
        desired=[1,0,0,0,0,1,0,0,0,0,1,0,-4,9,2,1]
        inv=self.ns['_rig_module_matrix_inverse'];mul=self.cmds.product
        opm=mul(mul(inv(local),desired),inv(parent))
        self.assertMatrix(mul(mul(local,opm),parent),desired)
        self.assertMatrix(inv(parent),self.cmds.inverse(parent))

    def test_matrix_graph_uses_actual_parent_inverse_and_no_source_matrix_feedback(self):
        rig,state=self.build()
        for destination,source in self.cmds.inputs.items():
            self.assertFalse(source.endswith('.parentInverseMatrix[0]'))
            if source.split('.',1)[0] in self.cmds.joints:
                self.assertFalse(source.endswith('.matrix') or source.endswith('.inverseMatrix'))
        for row in state['controls'][1:]:
            output=self.ns['_rig_module_node'](row['constraints'][0])
            parent=self.cmds.listRelatives(self.ns['_rig_module_node'](row['joint']),parent=True)[0]
            self.assertEqual(self.cmds.inputs[output+'.matrixIn[4]'],parent+'.worldInverseMatrix[0]')

    def test_global_scale_changes_world_uniformly_without_driving_joint_scale_channels(self):
        rig,state=self.build();before=[self.cmds.world(n) for n in self.cmds.joints]
        self.cmds.setAttr(rig['root']+'.globalScale',2)
        for n,original in zip(self.cmds.joints,before):
            expected=original[:]
            for i in (0,1,2,4,5,6,8,9,10,12,13,14):expected[i]*=2
            self.assertMatrix(self.cmds.world(n),expected)
            self.assertTrue(all(n+'.scale'+a not in self.cmds.inputs for a in 'XYZ'))

    def test_ikfk_blends_rigid_pose_and_base_scale_does_not_scale_solver(self):
        rig,state=self.build('IKFK')
        self.cmds.setAttr(rig['base_controller']+'.scale',3,3,3,type='double3')
        for identity in state['ik']['drivers']:
            world=self.cmds.world(self.ns['_rig_module_node'](identity));self.assertAlmostEqual(sum(v*v for v in world[:3])**.5,1)
        for value in (0,.5,1):
            self.ns['set_ikfk_blend'](rig['module'],value)
            for n in self.cmds.joints:self.assertAlmostEqual(sum(v*v for v in self.cmds.world(n)[:3])**.5,1)
        self.assertEqual(sum(row['type']=='blendMatrix' for row in state['members']),3)

    def test_blend_preserves_equal_lengths_across_different_rotations(self):
        import math
        rig,state=self.build('IKFK');fk=rig['fk_controllers']
        # Rotate the FK hierarchy 90 degrees about its first joint.
        q=self.cmds.quaternion_matrix((0,0,math.sin(math.pi/4),math.cos(math.pi/4)))
        current=self.cmds.world(fk[0]);q[12:15]=current[12:15]
        self.cmds.xform(fk[0],worldSpace=True,matrix=q)
        def measure():
            p=[self.cmds.world(n)[12:15] for n in self.cmds.joints]
            return [math.sqrt(sum((x-y)**2 for x,y in zip(a,b))) for a,b in zip(p,p[1:])]
        self.ns['set_ikfk_blend'](rig['module'],0);expected=measure()
        self.ns['set_ikfk_blend'](rig['module'],1)
        self.assertMatrix(measure(),expected)
        for w in (.1,.25,.5,.75,.9):
            self.ns['set_ikfk_blend'](rig['module'],w);self.assertMatrix(measure(),expected)
        self.assertEqual(state['ikfk']['length_mode'],'local_rotation_explicit_length_v1')

    def test_blend_interpolates_unequal_segment_lengths_without_chord_shrink(self):
        import math
        rig,state=self.build('IKFK')
        self.ns['set_ik_length_controls'](rig['module'],{'upperSlide':.6,'lowerSlide':-.2})
        def measure():
            p=[self.cmds.world(n)[12:15] for n in self.cmds.joints]
            return [math.dist(a,b) for a,b in zip(p,p[1:])]
        self.ns['set_ikfk_blend'](rig['module'],0);a=measure()
        self.ns['set_ikfk_blend'](rig['module'],1);b=measure()
        for w in (.1,.25,.5,.75,.9):
            self.ns['set_ikfk_blend'](rig['module'],w)
            self.assertMatrix(measure(),[x*(1-w)+y*w for x,y in zip(a,b)])
        self.cmds.setAttr(rig['root']+'.globalScale',2)
        self.assertMatrix(measure(),[2*(x*.1+y*.9) for x,y in zip(a,b)])

    def test_antipodal_local_directions_cannot_collapse_segment(self):
        rig,state=self.build('IKFK');fk=rig['fk_controllers']
        # Explicit opposite branch local vectors exercise safe nonzero fallback.
        parent=self.cmds.world(fk[0]);point=self.cmds.world(fk[1])
        point[12:15]=[2*parent[12+i]-point[12+i] for i in range(3)]
        self.cmds.xform(fk[1],worldSpace=True,matrix=point)
        self.ns['set_ikfk_blend'](rig['module'],.5)
        for row in state['ikfk']['segment_lengths']:
            self.assertGreater(self.cmds.evaluate(self.ns['_rig_module_node'](row['node'])+'.'+row['attribute']),0)
        points=[self.cmds.world(n)[12:15] for n in self.cmds.joints]
        import math
        self.assertTrue(all(math.dist(a,b)>1 for a,b in zip(points,points[1:])))

    def test_fk_controller_scale_is_filtered_out_of_source_world_scale(self):
        rig,state=self.build('IKFK')
        self.cmds.setAttr(rig['fk_controllers'][0]+'.scale',2,2,2,type='double3')
        for n in self.cmds.joints:self.assertAlmostEqual(sum(v*v for v in self.cmds.world(n)[:3])**.5,1)

    def test_removal_freezes_evaluated_opm_keeps_pose_and_all_local_channels(self):
        rig,state=self.build();self.ns['set_ik_length_controls'](rig['module'],{'upperSlide':.4,'lowerSlide':.2})
        before={n:self.cmds.world(n) for n in self.cmds.joints}
        attrs={n:{k:v for k,v in self.cmds.nodes[n]['attrs'].items() if k!='offsetParentMatrix'} for n in self.cmds.joints}
        self.ns['remove_rig_module'](rig['module'])
        self.assertEqual(set(self.cmds.nodes),set(self.cmds.joints))
        for n in self.cmds.joints:
            self.assertMatrix(self.cmds.world(n),before[n])
            self.assertFalse(self.cmds.inputs.get(n+'.offsetParentMatrix'))
            for k,v in attrs[n].items():self.assertEqual(self.cmds.nodes[n]['attrs'][k],v)

    def test_removal_does_not_require_unlocking_unchanged_trs(self):
        rig,state=self.build()
        for n in self.cmds.joints:self.cmds.setAttr(n+'.rotateX',lock=True)
        self.ns['remove_rig_module'](rig['module'])
        for n in self.cmds.joints:self.assertTrue(self.cmds.getAttr(n+'.rotateX',lock=True))

    def test_foreign_opm_blocks_build_and_remove_without_overwriting(self):
        foreign=self.cmds.add_node('|foreign','multMatrix');joint=self.cmds.joints[1]
        self.cmds.inputs[joint+'.offsetParentMatrix']=foreign+'.matrixSum'
        with self.assertRaisesRegex(ValueError,'offsetParentMatrix'):self.build()
        self.cmds.inputs.pop(joint+'.offsetParentMatrix');rig,state=self.build()
        self.cmds.inputs[joint+'.offsetParentMatrix']=foreign+'.matrixSum'
        with self.assertRaisesRegex(ValueError,'another driver'):self.ns['remove_rig_module'](rig['module'])
        self.assertEqual(self.cmds.inputs[joint+'.offsetParentMatrix'],foreign+'.matrixSum')

    def test_failed_matrix_build_rolls_back_sources_and_all_owned_nodes(self):
        before=self.cmds.copy.deepcopy(self.cmds.nodes);original=self.cmds.createNode
        def fail(kind,*args,**kw):
            if kind=='pickMatrix':raise RuntimeError('Matrix graph failed')
            return original(kind,*args,**kw)
        self.cmds.createNode=fail
        with self.assertRaisesRegex(RuntimeError,'rolled back'):self.build()
        self.assertEqual(self.cmds.nodes,before);self.assertFalse(self.cmds.inputs)

    def test_ssc_inverse_compensation_is_correct_for_changed_parent_scale(self):
        # Joint local = A * inverse(parentScale) * T. Check the factored inverse
        # used by the graph without reading solved/source matrix outputs.
        mul=self.cmds.product;inv=self.cmds.inverse;ident=self.cmds.ident
        a=[0,1,0,0,-1,0,0,0,0,0,1,0,0,0,0,1];t=ident();t[12:15]=[3,2,1]
        initial=ident();initial[0]=initial[5]=initial[10]=.5
        local=mul(mul(a,initial),t);tail=mul(mul(initial,t),inv(local))
        for parent_scale in (.5,1,3):
            scale=ident();scale[0]=scale[5]=scale[10]=parent_scale
            current=mul(mul(a,inv(scale)),t)
            compensated=mul(mul(inv(t),scale),tail)
            self.assertMatrix(mul(current,compensated),ident())

    def test_nonunit_bind_world_scale_is_retained_without_scale_channel_connections(self):
        for node in self.cmds.joints:
            local=self.cmds.nodes[node]['local_matrix']
            for axis in 'XYZ':self.cmds.nodes[node]['attrs']['scale'+axis]=1.2
        scales=[sum(v*v for v in self.cmds.world(n)[:3])**.5 for n in self.cmds.joints]
        rig,state=self.build();self.ns['set_ik_length_controls'](rig['module'],{'upperSlide':.2})
        for node,scale in zip(self.cmds.joints,scales):
            self.assertAlmostEqual(sum(v*v for v in self.cmds.world(node)[:3])**.5,scale)
            self.assertTrue(all(node+'.scale'+a not in self.cmds.inputs for a in 'XYZ'))

    def test_matrix_defaults_and_ownership_survive_controller_renaming(self):
        rig,state=self.build('IKFK');self.ns['set_ikfk_blend'](rig['module'],1)
        self.cmds.setAttr(rig['end_controller']+'.upperSlide',.3)
        self.ns['goto_rig_default'](rig['module'])
        self.assertEqual(self.cmds.getAttr(rig['root']+'.ikFkBlend'),0)
        self.assertEqual(self.cmds.getAttr(rig['end_controller']+'.upperSlide'),0)
        self.ns['rename_rig_controllers'](rig['module'])
        after=self.ns['_rig_module_read'](rig['module'])[1]
        self.assertEqual(state['ik']['outputs'],after['ik']['outputs'])
        self.ns['remove_rig_module'](rig['module'])

    def test_foreign_source_animation_remains_connected_after_matrix_removal(self):
        rig,state=self.build();curve=self.cmds.add_node('|foreignAnimation','animCurveTA')
        joint=self.cmds.joints[1];self.cmds.inputs[joint+'.rotateX']=curve+'.output'
        self.ns['remove_rig_module'](rig['module'])
        self.assertEqual(self.cmds.inputs[joint+'.rotateX'],curve+'.output')
        self.assertTrue(self.cmds.objExists(curve))

    def test_missing_buffer_ownership_is_rejected(self):
        rig,state=self.build();state['ik']['outputs'][0]=state['joints'][0]['uuid']
        self.cmds.setAttr(rig['module']+'.rtkRigModuleState',json.dumps(state),type='string')
        with self.assertRaisesRegex(ValueError,'X-axis matrix IK ownership'):self.ns['remove_rig_module'](rig['module'])

    def test_failed_removal_restores_graph_opm_and_local_channels(self):
        rig,state=self.build();before=self.cmds.copy.deepcopy(self.cmds.nodes);edges=dict(self.cmds.inputs)
        self.cmds.fail_delete=True
        with self.assertRaisesRegex(RuntimeError,'rolled back'):self.ns['remove_rig_module'](rig['module'])
        self.assertEqual(self.cmds.nodes,before);self.assertEqual(self.cmds.inputs,edges)

    def test_all_length_features_preserve_source_scale_and_segment_lengths(self):
        import itertools,math
        rig,state=self.build();end=rig['end_controller'];root=rig['root']
        rest=state['ik']['length_system']['rest_lengths']
        for stretch,soft,slide,pin in itertools.product((0,1),(0,.6),(-.3,.3),(0,1)):
            controls={'stretch':stretch,'antiPop':soft,'slide':slide,'upperSlide':.2,'lowerSlide':-.1,'poleLock':pin}
            self.ns['set_ik_length_controls'](rig['module'],controls)
            start=self.cmds.world(self.ns['_rig_module_node'](state['ik']['drivers'][0]))[12:15]
            target=self.cmds.world(end)[12:15];pole=self.cmds.world(rig['pole_controller'])[12:15]
            dist=lambda a,b:math.sqrt(sum((x-y)**2 for x,y in zip(a,b)))
            expected=self.ns['ik_length_solution'](*rest,dist(start,target),dist(start,pole),dist(pole,target),stretch=stretch,anti_pop=soft,slide=slide,upper_slide=.2,lower_slide=-.1,pole_lock=pin)
            points=[self.cmds.world(n)[12:15] for n in self.cmds.joints]
            self.assertAlmostEqual(dist(points[0],points[1]),expected['upper'])
            self.assertAlmostEqual(dist(points[1],points[2]),expected['lower'])
            for n in self.cmds.joints:self.assertAlmostEqual(sum(v*v for v in self.cmds.world(n)[:3])**.5,1)

    def test_mirror_keeps_new_matrix_backend_and_positive_x_lengths(self):
        for i,name in enumerate(('upper_L_JNT','mid_L_JNT','end_L_JNT')):self.cmds.rename(self.cmds.joints[i],name)
        targets=[]
        attrs=self.cmds.copy.deepcopy(self.cmds.nodes[self.cmds.joints[0]]['attrs'])
        for i,(name,point) in enumerate(zip(('upper_R_JNT','mid_R_JNT','end_R_JNT'),((0,0,0),(3,-2,0),(8,0,0)))):
            path=(targets[-1]+'|' if targets else '|')+name
            node=self.cmds.add_node(path,'joint');self.cmds.nodes[node]['attrs']=self.cmds.copy.deepcopy(attrs)
            self.cmds.xform(node,worldSpace=True,matrix=self.cmds.matrix(*point));targets.append(node)
        rig,state=self.build('IKFK',name='leg_L')
        mirrored=self.ns['mirror_rig_module'](rig['module'])
        other=self.ns['_rig_module_read'](mirrored['module'])[1]
        self.assertEqual(other['ik']['solver'],'x_translate_v1')
        self.assertTrue(all('_R' in name for name in other['controller_names'].values()))
        for identity in other['ik']['drivers'][1:]:self.assertGreater(self.cmds.getAttr(self.ns['_rig_module_node'](identity)+'.translateX'),0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
