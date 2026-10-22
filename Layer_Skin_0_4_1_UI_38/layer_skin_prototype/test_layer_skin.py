"""Local tests: python -m unittest discover -s layer_skin_prototype -p test_layer_skin.py -v"""
import ast
import copy
import math
from pathlib import Path
import random
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

import layer_skin_core as core


class LayerTests(unittest.TestCase):
    def setUp(self):
        self.state = core.create([1,0, .2,.8, 0,1], 3, ['a','b'], 'topology')

    def add(self, state=None):
        state = core.edit(state or self.state, 'add', {'name':'Arm'})
        return state, state['layers'][-1]['id']

    def assertWeights(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for a,b in zip(actual, expected):self.assertAlmostEqual(a,b)

    def test_empty_stack_is_exact_base(self):
        self.assertEqual(core.composite(self.state), self.state['base'])
    def test_explicit_assignment_replaces_flood_in_scope_and_preserves_mask_and_input(self):
        state,layer=self.add()
        state=core.edit(state,'paint',dict(layer=layer,mode='weights',joint='a',values={'0':1.,'1':1.,'2':1.}))
        state=core.edit(state,'paint',dict(layer=layer,mode='mask',values={'1':.5}));before=copy.deepcopy(state)
        result=core.edit(state,'assign',dict(layer=layer,joints=['b'],generated={'1':dict(weights=[0.,1.],coverage=1.)},scope=[1],replace_manual=True))
        self.assertEqual(set(result['layers'][0]['samples']),{'0','2'});self.assertEqual(result['layers'][0]['mask'],{'1':.5})
        self.assertAlmostEqual(core.composite(result)[3],.9);self.assertEqual(state,before)
    def test_assignment_can_preserve_manual_overrides_and_unmatched_scope_falls_through(self):
        state,layer=self.add();state=core.edit(state,'paint',dict(layer=layer,mode='weights',joint='b',values={'0':1.}))
        keep=core.edit(state,'assign',dict(layer=layer,generated={},scope=[0],replace_manual=False))
        self.assertEqual(core.composite(keep)[:2],[0.,1.])
        replace=core.edit(state,'assign',dict(layer=layer,generated={},scope=[0],replace_manual=True))
        self.assertEqual(core.composite(replace)[:2],[1.,0.]);self.assertEqual(replace['layers'][0]['samples'],{})

    def test_empty_layer_does_not_override(self):
        state, _ = self.add()
        self.assertEqual(core.composite(state), self.state['base'])

    def test_flood_only_selected_vertices(self):
        state, layer = self.add()
        result = core.edit(state,'flood',{'layer':layer,'vertices':[0],'influence':1,'value':1})
        self.assertWeights(core.composite(result),[0,1,.2,.8,0,1])
        self.assertFalse(state['layers'][0]['samples'])

    def test_partial_flood_redistributes_remainder(self):
        state, layer = self.add()
        state = core.edit(state,'flood',{'layer':layer,'vertices':[1],'influence':0,'value':.6})
        self.assertWeights(core.composite(state),[1,0,.6,.4,0,1])

    def test_three_influence_proportional_redistribution(self):
        state=core.create([.2,.3,.5],1,['a','b','c'],'t');state,layer=self.add(state)
        state=core.edit(state,'flood',{'layer':layer,'vertices':[0],'influence':0,'value':.6})
        self.assertWeights(core.composite(state),[.6,.15,.25])

    def test_opacity_mask_coverage_multiply(self):
        state,layer=self.add()
        state['layers'][0].update(opacity=.5, mask={'0':.4}, samples={'0':{'weights':[0,1],'coverage':.5}})
        self.assertWeights(core.composite(state),[.9,.1,.2,.8,0,1])

    def test_mask_zero_reveals_base(self):
        state,layer=self.add();state=core.edit(state,'flood',{'layer':layer,'vertices':[0],'influence':1,'value':1})
        state=core.edit(state,'mask',{'layer':layer,'vertices':[0],'value':0})
        self.assertEqual(core.composite(state),state['base'])

    def test_mask_reset_removes_sparse_override(self):
        state,layer=self.add();state=core.edit(state,'mask',{'layer':layer,'vertices':[0],'value':0})
        state=core.edit(state,'mask',{'layer':layer,'vertices':[0],'value':1})
        self.assertEqual(state['layers'][0]['mask'],{})

    def test_disabled_layer_transparent(self):
        state,layer=self.add();state=core.edit(state,'flood',{'layer':layer,'vertices':[0],'influence':1,'value':1})
        state=core.edit(state,'properties',{'layer':layer,'enabled':False})
        self.assertEqual(core.composite(state),state['base'])

    def test_stack_order_changes_result(self):
        state,a=self.add();state=core.edit(state,'flood',{'layer':a,'vertices':[1],'influence':0,'value':1})
        state,b=self.add(state);state=core.edit(state,'flood',{'layer':b,'vertices':[1],'influence':1,'value':1})
        self.assertWeights(core.composite(state)[2:4],[0,1])
        state=core.edit(state,'move',{'layer':b,'direction':-1})
        self.assertWeights(core.composite(state)[2:4],[1,0])

    def test_lower_layer_edit_does_not_capture_upper_layer(self):
        state,a=self.add();state,b=self.add(state)
        state=core.edit(state,'flood',{'layer':b,'vertices':[1],'influence':0,'value':1})
        state=core.edit(state,'flood',{'layer':a,'vertices':[1],'influence':1,'value':.6})
        self.assertWeights(state['layers'][0]['samples']['1']['weights'],[.4,.6])
        self.assertWeights(core.composite(state)[2:4],[1,0])

    def test_clearing_edit_retains_mask(self):
        state,layer=self.add();state=core.edit(state,'mask',{'layer':layer,'vertices':[0],'value':.2})
        state=core.edit(state,'flood',{'layer':layer,'vertices':[0],'influence':1,'value':1})
        state=core.edit(state,'clear',{'layer':layer,'vertices':[0]})
        self.assertEqual(core.composite(state),state['base'])
        self.assertEqual(state['layers'][0]['mask'],{'0':.2})

    def test_delete_restores_lower_stack(self):
        state,layer=self.add();state=core.edit(state,'flood',{'layer':layer,'vertices':[0],'influence':1,'value':1})
        state=core.edit(state,'delete',{'layer':layer})
        self.assertEqual(core.composite(state),state['base'])

    def test_serialization_roundtrip(self):
        state,layer=self.add();state=core.edit(state,'flood',{'layer':layer,'vertices':[1],'influence':1,'value':.9})
        self.assertEqual(core.decode(core.encode(state)),state)

    def test_invalid_values_are_rejected_without_mutation(self):
        state,layer=self.add();before=copy.deepcopy(state)
        for value in (-.1,1.1,math.nan,math.inf):
            with self.assertRaises(ValueError):core.edit(state,'properties',{'layer':layer,'opacity':value})
        self.assertEqual(state,before)

    def test_invalid_vertices_rejected(self):
        state,layer=self.add()
        for vertices in ([],[-1],[3],[True],[1.2]):
            with self.assertRaises(ValueError):core.edit(state,'mask',{'layer':layer,'vertices':vertices,'value':1})

    def test_invalid_base_rejected(self):
        for base in ([0,0],[.2,.3],[-1,2],[math.nan,1]):
            with self.assertRaises(ValueError):core.create(base,1,['a','b'],'t')

    def test_unavailable_remainder_rejected(self):
        state,layer=self.add()
        with self.assertRaisesRegex(ValueError,'remainder'):core.edit(state,'flood',{'layer':layer,'vertices':[0],'influence':0,'value':.5})

    def test_single_influence(self):
        state=core.create([1],1,['a'],'t');state,layer=self.add(state)
        state=core.edit(state,'flood',{'layer':layer,'vertices':[0],'influence':0,'value':1})
        self.assertEqual(core.composite(state),[1])
        with self.assertRaises(ValueError):core.edit(state,'flood',{'layer':layer,'vertices':[0],'influence':0,'value':.5})

    def test_move_out_of_bounds_rejected(self):
        state,layer=self.add()
        with self.assertRaises(ValueError):core.edit(state,'move',{'layer':layer,'direction':1})

    def test_reorder_changes_composition_and_preserves_samples(self):
        state,a=self.add();state=core.edit(state,'flood',{'layer':a,'vertices':[1],'influence':0,'value':1})
        state,b=self.add(state);state=core.edit(state,'flood',{'layer':b,'vertices':[1],'influence':1,'value':1})
        before=copy.deepcopy(state);result=core.edit(state,'reorder',{'order':[b,a]})
        self.assertWeights(core.composite(result)[2:4],[1,0]);self.assertEqual(state,before)
        self.assertEqual(result['layers'],list(reversed(state['layers'])))

    def test_reorder_rejects_stale_duplicate_missing_and_foreign_ids(self):
        state,a=self.add();state,b=self.add(state);before=copy.deepcopy(state)
        for order in ([a,a],[a],[a,b,'foreign'],[a,'foreign'],'ab',[[],b],None):
            with self.subTest(order=order),self.assertRaises(ValueError):core.edit(state,'reorder',{'order':order})
        self.assertEqual(state,before)

    def test_reorder_uses_identity_with_duplicate_names(self):
        state,a=self.add();state,b=self.add(state)
        result=core.edit(state,'reorder',{'order':[b,a]})
        self.assertEqual([r['id'] for r in result['layers']],[b,a])

    def test_empty_and_unchanged_orders_are_valid(self):
        self.assertEqual(core.edit(self.state,'reorder',{'order':[]}),self.state)
        state,a=self.add();self.assertEqual(core.edit(state,'reorder',{'order':[a]}),state)

    def test_randomized_stack_keeps_nonnegative_normalized_weights(self):
        rng=random.Random(718)
        for _ in range(40):
            n,k=5,4;base=sum((core.normalized([rng.random() for _ in range(k)]) for _ in range(n)),[])
            state=core.create(base,n,[str(i) for i in range(k)],'t')
            for i in range(6):
                state,layer=self.add(state)
                state['layers'][-1]['opacity']=rng.random()
                for v in range(n):
                    if rng.random()>.3:
                        state['layers'][-1]['samples'][str(v)]={'weights':core.normalized([rng.random() for _ in range(k)]),'coverage':rng.random()}
                        state['layers'][-1]['mask'][str(v)]=rng.random()
            result=core.composite(core.validate(state))
            for v in range(n):
                self.assertAlmostEqual(sum(result[v*k:(v+1)*k]),1)
                self.assertTrue(all(x>=0 for x in result[v*k:(v+1)*k]))


class PluginLoaderTests(unittest.TestCase):
    """Execute the complete plugin with Maya's missing-__file__ namespace."""
    def setUp(self):
        self.path=Path(__file__).with_name('layer_skin_test.py').resolve()
        self.source=self.path.read_text();self.registered=[]

    def execute(self,filename=None,file_global=None,load_path=None):
        maya=types.ModuleType('maya');maya.__path__=[]
        api=types.ModuleType('maya.api');api.__path__=[]
        cmds=types.ModuleType('maya.cmds');om=types.ModuleType('maya.api.OpenMaya');oma=types.ModuleType('maya.api.OpenMayaAnim')
        om.MPxCommand=object;registered=self.registered;plugin_path=self.path
        class Plugin:
            def __init__(self,*args):self.arguments=args
            def loadPath(self):return str(load_path or plugin_path)
            def registerCommand(self,*args):registered.append((self.arguments,args))
        om.MFnPlugin=Plugin
        maya.cmds=cmds;maya.api=api;api.OpenMaya=om;api.OpenMayaAnim=oma
        modules={'maya':maya,'maya.cmds':cmds,'maya.api':api,'maya.api.OpenMaya':om,'maya.api.OpenMayaAnim':oma}
        ns={'__name__':'_maya_layer_skin_loader_test'}
        if file_global is not None:ns['__file__']=str(file_global)
        with mock.patch.dict(sys.modules,modules):
            exec(compile(self.source,str(filename or self.path),'exec'),ns)
        return ns

    def test_complete_plugin_registers_without_file_global(self):
        ns=self.execute();self.assertNotIn('__file__',ns)
        self.assertEqual(ns['core'].normalized([2,2]),[.5,.5])
        ns['initializePlugin']('plugin')
        self.assertEqual(self.registered[0][0][2],ns['VERSION'])
        self.assertEqual(self.registered[0][1][0],'rtkLayerSkin')

    def test_normal_import_resolves_file_global(self):
        ns=self.execute(filename='<wrapper>',file_global=self.path)
        self.assertIsNotNone(ns['core'])

    def test_deferred_initialization_uses_plugin_load_path(self):
        ns=self.execute(filename='<Maya loader>');self.assertIsNone(ns['core'])
        ns['initializePlugin']('plugin')
        self.assertIsNotNone(ns['core']);self.assertEqual(len(self.registered),1)

    def test_directory_load_path_is_supported(self):
        ns=self.execute(filename='<Maya loader>',load_path=self.path.parent)
        ns['initializePlugin']('plugin');self.assertEqual(len(self.registered),1)

    def test_unusable_file_global_falls_back_to_compiled_filename(self):
        ns=self.execute(file_global='/missing/layer_skin_test.py')
        self.assertIsNotNone(ns['core'])

    def test_spaces_and_unicode_in_plugin_path(self):
        with tempfile.TemporaryDirectory(prefix='layer skin ') as temporary:
            folder=Path(temporary)/'MayaZone_测试';folder.mkdir()
            plugin=folder/'layer_skin_test.py';plugin.write_text(self.source)
            shutil.copyfile(self.path.with_name('layer_skin_core.py'),folder/'layer_skin_core.py')
            ns=self.execute(filename=plugin,load_path=plugin)
            ns['initializePlugin']('plugin');self.assertEqual(len(self.registered),1)

    def test_missing_core_fails_before_command_registration(self):
        with tempfile.TemporaryDirectory() as temporary:
            ns=self.execute(filename='<Maya loader>',load_path=temporary)
            with self.assertRaisesRegex(ImportError,'keep its Python files together'):
                ns['initializePlugin']('plugin')
            self.assertEqual(self.registered,[])

    def test_core_is_reused_for_helper_imports(self):
        ns=self.execute();first=ns['core']
        self.assertIs(ns['_load_core']('/missing'),first)


class CommandTransactionTests(unittest.TestCase):
    """Command ordering/failure recovery only; no simulation of Maya API internals."""
    def setUp(self):
        tree=ast.parse(Path(__file__).with_name('layer_skin_test.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LayerCommand')
        ns={'om':types.SimpleNamespace(MPxCommand=object)}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<command transaction>','exec'),ns)
        self.command=ns['LayerCommand']();self.command.skip_create_once=False
        self.command.before='before';self.command.after='after';self.command.undoable=True
        self.log=[];self.command.write=lambda weights:self.log.append(('weights',weights))
        self.command.mods=[self.mod('graph')]

    def mod(self,name,fail=False):
        log=self.log
        class Modifier:
            def doIt(self):
                log.append(('do',name))
                if fail:raise RuntimeError('graph failure')
            def undoIt(self):log.append(('undo',name))
        return Modifier()

    def test_redo_then_undo_order(self):
        self.command.redoIt();self.command.undoIt()
        self.assertEqual(self.log,[('do','graph'),('weights','after'),('weights','before'),('undo','graph')])

    def test_initial_creation_skipped_once_but_redone_after_undo(self):
        self.command.skip_create_once=True;self.command.mods=[self.mod('create'),self.mod('data')]
        self.command.redoIt();self.command.undoIt();self.command.redoIt()
        self.assertEqual(self.log.count(('do','create')),1)
        self.assertEqual(self.log.count(('do','data')),2)

    def test_write_failure_restores_before_and_graph(self):
        def write(value):
            self.log.append(('weights',value))
            if value=='after':raise RuntimeError('write failed')
        self.command.write=write
        with self.assertRaises(RuntimeError):self.command.redoIt()
        self.assertEqual(self.log[-2:],[('weights','before'),('undo','graph')])
        self.assertFalse(self.command.undoable)

    def test_partial_graph_failure_attempts_recovery(self):
        self.command.mods=[self.mod('create'),self.mod('data',True)]
        with self.assertRaises(RuntimeError):self.command.redoIt()
        self.assertEqual(self.log[-3:],[('weights','before'),('undo','data'),('undo','create')])


if __name__=='__main__':unittest.main(verbosity=2)
