"""Unskinned-source rejection before geometry reads and Load failure cleanup."""
import ast
from pathlib import Path
import types
import unittest
from unittest import mock
import test_copy_skinning as regression


def functions(names,filename='copy_skinning_plugin.py'):
    return [n for n in ast.parse(Path(__file__).with_name(filename).read_text()).body
            if isinstance(n,ast.FunctionDef) and n.name in names]


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.nodes=[];self.created=[];self.visited=[]
        self.dag=types.SimpleNamespace(node=lambda:'meshNode',fullPathName=lambda:'|source|shape')
        self.root=types.SimpleNamespace(isDestination=True)
        def dependency(node):
            return types.SimpleNamespace(findPlug=lambda name,networked:self.root,name=lambda:node.name)
        case=self
        class Graph:
            kUpstream=1;kDepthFirst=0;kPlugLevel=1
            def __init__(self,*args):case.created.append(args);self.index=0
            def isDone(self):return self.index>=len(case.nodes)
            def currentNode(self):case.visited.append(self.index);return case.nodes[self.index]
            def next(self):self.index+=1
        self.om=types.SimpleNamespace(MFnDependencyNode=dependency,MItDependencyGraph=Graph,
            MFn=types.SimpleNamespace(kInvalid=0,kSkinClusterFilter=1))
        self.ns={'om':self.om,'time':types.SimpleNamespace(monotonic=lambda:0.)}
        exec(compile(ast.Module(body=functions({'mesh_input','no_skin','find_skin'}),type_ignores=[]),'<skin discovery>','exec'),self.ns)
    @staticmethod
    def node(name,skin=False,null=False):
        return types.SimpleNamespace(name=name,isNull=lambda:null,hasFn=lambda kind:skin)
    def find(self,check=None):return self.ns['find_skin'](self.dag,check)
    def test_bare_mesh_rejected_without_constructing_iterator(self):
        self.root.isDestination=False
        with self.assertRaisesRegex(ValueError,'no skinCluster.*source.*Prepare target'):self.find()
        self.assertEqual(self.created,[])
    def test_construction_history_without_skin_is_rejected(self):
        self.nodes=[self.node('shape'),self.node('polyCube')]
        with self.assertRaisesRegex(ValueError,'no skinCluster'):self.find()
        self.assertEqual(len(self.visited),2)
    def test_iterator_starts_from_inmesh_without_a_type_filter(self):
        self.nodes=[self.node('skin1',True)]
        self.assertEqual(self.find(),'skin1');self.assertEqual(self.created,[(self.root,0,1,0,1)])
    def test_repeated_skin_plugs_do_not_count_as_multiple_skins(self):
        self.nodes=[self.node('skin1',True),self.node('skin1',True)]
        self.assertEqual(self.find(),'skin1')
    def test_distinct_skin_clusters_rejected_before_geometry(self):
        self.nodes=[self.node('skin1',True),self.node('skin2',True)]
        with self.assertRaisesRegex(ValueError,'Multiple skinClusters'):self.find()
    def test_unknown_history_node_is_not_silently_treated_as_unskinned(self):
        self.nodes=[self.node('unknown',null=True)]
        with self.assertRaisesRegex(ValueError,'unknown node'):self.find()
    def test_cancellation_before_iterator_construction(self):
        stop=mock.Mock(side_effect=RuntimeError('cancel requested'))
        with self.assertRaisesRegex(RuntimeError,'cancel requested'):self.find(stop)
        self.assertEqual(self.created,[])
    def test_cancellation_during_history_walk(self):
        self.nodes=[self.node('poly')]*20;calls=[]
        def stop():
            calls.append(1)
            if len(calls)==5:raise RuntimeError('cancel walk')
        with self.assertRaisesRegex(RuntimeError,'cancel walk'):self.find(stop)
        self.assertEqual(len(self.visited),3)
    def test_history_walk_has_a_step_limit(self):
        self.nodes=[self.node('poly')]*10001
        with self.assertRaisesRegex(ValueError,'discovery limit'):self.find()
        self.assertEqual(len(self.visited),10000)
    def test_history_walk_has_an_elapsed_limit(self):
        self.nodes=[self.node('poly')];self.ns['time'].monotonic=mock.Mock(side_effect=[0.,121.])
        with self.assertRaisesRegex(ValueError,'discovery limit'):self.find()
        self.assertEqual(self.visited,[])


class ContextOrderingTests(unittest.TestCase):
    def setUp(self):
        self.dag=types.SimpleNamespace(node=lambda:'meshNode',fullPathName=lambda:'|source|shape')
        self.mesh=mock.Mock(side_effect=AssertionError('Geometry must not be evaluated'))
        self.ns={'mesh_path':lambda name:self.dag,'find_skin':mock.Mock(side_effect=ValueError('no skinCluster')),
            'om':types.SimpleNamespace(MFnMesh=self.mesh),'object_':lambda name:name,'oma':types.SimpleNamespace(MFnSkinCluster=mock.Mock())}
        exec(compile(ast.Module(body=functions({'context'}),type_ignores=[]),'<context ordering>','exec'),self.ns)
    def test_unskinned_rejection_precedes_mfnmesh(self):
        with self.assertRaisesRegex(ValueError,'no skinCluster'):self.ns['context']('source')
        self.mesh.assert_not_called();self.ns['oma'].MFnSkinCluster.assert_not_called()
    def test_skin_output_association_is_checked_before_geometry(self):
        self.ns['find_skin'].return_value='skin';self.ns['find_skin'].side_effect=None
        self.ns['oma'].MFnSkinCluster.return_value.indexForOutputShape.side_effect=ValueError('not this output')
        with self.assertRaisesRegex(ValueError,'not this output'):self.ns['context']('source')
        self.mesh.assert_not_called()
    def test_discovery_receives_cancellation_callback(self):
        callback=mock.Mock()
        with self.assertRaises(ValueError):self.ns['context']('source',check=callback)
        self.ns['find_skin'].assert_called_once_with(self.dag,callback)


class LoadCleanupTests(unittest.TestCase):
    def setUp(self):
        self.fixture=regression.ProgressTests();self.fixture.setUp();self.ns=self.fixture.ns
        self.dag=types.SimpleNamespace(fullPathName=lambda:'|source|shape')
        self.root=types.SimpleNamespace(isDestination=True)
        self.ns.update(mesh_path=lambda name:self.dag,mesh_input=lambda dag:self.root,
                       context=mock.Mock(side_effect=ValueError('Mesh has no skinCluster: source')),
                       cache_stats=mock.Mock(),no_skin=lambda dag:ValueError('Mesh has no skinCluster: source'))
        exec(compile(ast.Module(body=functions({'load_mesh'}),type_ignores=[]),'<load cleanup>','exec'),self.ns)
    def test_bare_mesh_does_not_create_a_progress_window(self):
        self.root.isDestination=False
        with self.assertRaisesRegex(ValueError,'no skinCluster'):self.ns['load_mesh']('source',source=True)
        self.assertEqual(self.fixture.events,[]);self.ns['context'].assert_not_called()
        self.assertFalse(self.ns['_active_plan']);self.assertEqual(self.fixture.cache.stats()['items'],0)
    def test_connected_unskinned_mesh_releases_progress_and_operation_guard(self):
        with self.assertRaisesRegex(ValueError,'no skinCluster'):self.ns['load_mesh']('source',source=True)
        self.fixture.assert_closed();self.assertEqual(self.fixture.samples,[])
        self.ns['cache_stats'].assert_not_called();self.assertEqual(self.fixture.cache.stats()['items'],0)
    def test_repeated_invalid_loads_do_not_leave_operation_busy(self):
        for i in range(3):
            with self.assertRaisesRegex(ValueError,'no skinCluster'):self.ns['load_mesh']('source',source=True)
            self.assertFalse(self.fixture.open);self.assertFalse(self.ns['_active_plan'])
        self.assertEqual(sum(bool(e.get('endProgress')) for e in self.fixture.events),3)
    def test_load_passes_interrupt_callback_into_context(self):
        with self.assertRaises(ValueError):self.ns['load_mesh']('source')
        self.assertFalse(self.ns['context'].call_args.kwargs['read_weights'])
        self.assertTrue(callable(self.ns['context'].call_args.kwargs['check']))
    def test_load_honors_calculation_budget_before_geometry_reads(self):
        with self.assertRaisesRegex(RuntimeError,'time limit'):self.ns['load_mesh']('source',max_seconds=1e-12)
        self.fixture.assert_closed();self.ns['context'].assert_not_called()
    def test_invalid_load_keeps_foreign_progress_window_untouched(self):
        self.fixture.can_open=False
        with self.assertRaisesRegex(RuntimeError,'Maya could not create a progress window'):self.ns['load_mesh']('source')
        self.assertEqual(len(self.fixture.events),1);self.assertFalse(self.ns['_active_plan'])


class LoadUIFailureTests(unittest.TestCase):
    def test_load_failure_clears_preview_and_marks_mesh_status(self):
        tree=ast.parse(Path(__file__).with_name('copy_skinning_ui.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='CopySkinningPanel')
        node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='load_role')
        api=types.SimpleNamespace(load_mesh=mock.Mock(side_effect=ValueError('no skinCluster')))
        ns={'backend':lambda:api};exec(compile(ast.Module(body=[node],type_ignores=[]),'<load UI failure>','exec'),ns)
        label=mock.Mock();data={'source':'mesh','geometry':'base','source_base':'','method':'surface','max_seconds':30}
        widget=types.SimpleNamespace(data=lambda:data,mesh_info={'source':label},preview_data='stale')
        with self.assertRaisesRegex(ValueError,'no skinCluster'):ns['load_role'](widget,'source')
        self.assertIsNone(widget.preview_data);label.setText.assert_called_with('Load failed · see details')
        label.setToolTip.assert_called_with('no skinCluster');self.assertEqual(api.load_mesh.call_args.kwargs['max_seconds'],30)


if __name__=='__main__':unittest.main(verbosity=2)
