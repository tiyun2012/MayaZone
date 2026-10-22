"""Planning and binding transaction tests with recording commands, no Maya DG."""
import contextlib
import copy
import json
import types
import unittest
from unittest import mock
import layer_skin_core as core
import layer_skin_io_backend as backend
import test_layer_skin_io as file_fixtures
import test_layer_skin_io_command as command_fixtures


@contextlib.contextmanager
def no_native_computation():yield lambda:None


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.fixture=command_fixtures.ImportCommandTests();self.fixture.setUp();self.case=self.fixture.case;self.ns=self.case.ns
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(backend,'computation',no_native_computation))
        self.has_skin=True;self.enabled=True;self.chunk=None;self.undo_stack=[];self.redo_stack=[];self.operations=[];self.fail_binding=False;self.corrupt_saved=False;self.dead=False
        self.records=[dict(uuid='a',path='|a',position=[0.,0.,0.]),dict(uuid='b',path='|b',position=[1.,0.,0.])]
        self.signature=file_fixtures.snapshot()['topology'];self.points=[(0.,0.,0.),(1.,0.,0.),(0.,1.,0.)]
        case=self
        class Distance:
            def __init__(self,v,unit):self.value=v
            def asCentimeters(self):return self.value
            @staticmethod
            def uiUnit():return 0
        self.ns['om'].MDistance=Distance
        self.ns['om'].MObjectHandle=lambda node:types.SimpleNamespace(isValid=lambda:not self.dead,isAlive=lambda:not self.dead)
        self.ns['cmds'].undoInfo=self.undo_info;self.ns['cmds'].undo=self.undo;self.ns['cmds'].skinCluster=self.bind
        self.ns['cmds'].attributeQuery=lambda *a,**kw:False
        old_get=self.ns['cmds'].getAttr
        self.ns['cmds'].getAttr=lambda plug:self.fixture.method if plug.endswith('.skinningMethod') else old_get(plug)
        self.ns['cmds'].ls=lambda name,**kw:[r['path'] for r in self.records if r['uuid']==name or r['path']==name]
        self.ns['cmds'].rtkLayerSkin=self.command
        self.api=types.SimpleNamespace(_layer_skin_command_owner=self.ns,core=self.ns['core'],om=self.ns['om'],cmds=self.ns['cmds'],
            clear_cache=self.ns['clear_cache'],context=self.context,metadata=self.metadata,same=self.ns['same'],obj=lambda name:name)
        class Service(backend.Backend):
            def mesh(self,target):return case.context(target)
            def geometry(self,ctx,mode='base'):return dict(points=list(case.points),triangles=[(0,1,2)],count=3,topology=case.signature)
            def candidates(self,ctx,root='',check=None):return copy.deepcopy(case.records)
        self.service=Service(self.api)
    def snapshot(self):return copy.deepcopy((self.has_skin,self.case.ids,self.case.weights,self.case.graph,self.fixture.dq,self.fixture.method))
    def restore(self,value):
        self.has_skin,self.case.ids,self.case.weights,graph,self.fixture.dq,self.fixture.method=copy.deepcopy(value);self.case.graph.clear();self.case.graph.update(graph)
    def undo_info(self,**kw):
        if kw.get('query'):
            if kw.get('state'):return self.enabled
            if kw.get('undoName'):return self.undo_stack[-1][1] if self.undo_stack else 'Unrelated previous edit'
        elif kw.get('openChunk'):self.chunk=(self.snapshot(),kw['chunkName'])
        elif kw.get('closeChunk'):
            before,name=self.chunk;self.chunk=None
            if before!=self.snapshot():self.undo_stack.append((before,name));self.redo_stack=[]
    def undo(self):
        before,name=self.undo_stack.pop();self.redo_stack.append((self.snapshot(),name));self.restore(before)
    def redo(self):
        after,name=self.redo_stack.pop();self.undo_stack.append((self.snapshot(),name));self.restore(after)
    def bind(self,*args,**kw):
        self.operations.append(('bind',args,kw))
        if kw.get('edit'):
            self.assertNotIn('lockWeights',kw)
            identity=next(r['uuid'] for r in self.records if r['path']==kw['addInfluence']);width=len(self.case.ids)
            self.case.weights=[v for row in range(3) for v in self.case.weights[row*width:(row+1)*width]+[0.]];self.case.ids.append(identity)
        else:
            self.has_skin=True;self.case.ids=[next(r['uuid'] for r in self.records if r['path']==name) for name in args[0]]
            self.case.weights=([1.]+[0.]*(len(self.case.ids)-1))*3
        if self.fail_binding:raise RuntimeError('Binding failed after mutation')
        return ['skin']
    def context(self,target):
        value=self.ns['context'](target)
        if not self.has_skin:value.update(skin=None,fn=None,ids=[],weights=[])
        return value
    def metadata(self,ctx):return self.ns['metadata'](ctx) if self.has_skin else (None,None)
    def command(self,action,data):
        parsed=json.loads(data);parsed.pop('target',None);command=self.case.command(action,**parsed)
        if self.corrupt_saved:
            value=core.decode(self.case.graph['raw']);value['layers'][-1]['mask']['0']=0.;self.case.graph['raw']=core.encode(value)
        return command.result
    def preview(self,**kw):return self.service.preview(file_fixtures.snapshot(),'mesh',**kw)
    def test_readonly_preview_preserves_scene_and_prepares_one_to_one_mapping(self):
        before=self.snapshot();plan=self.preview()
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.operations,[]);self.assertTrue(plan['report']['complete'])
        self.assertEqual(plan['payload']['mapping'],['a','b']);self.assertEqual(self.undo_stack,[])
    def test_unskinned_unmapped_preview_still_returns_rows_for_manual_mapping(self):
        self.has_skin=False;self.records=[];before=self.snapshot()
        plan=self.preview()
        self.assertFalse(plan['report']['complete']);self.assertTrue(plan['report']['rows'])
        self.assertEqual(plan['payload']['mapping'],[None,None])
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.operations,[])
    def test_existing_skin_import_commits_weights_layer_dq_and_method_in_one_outer_undo(self):
        self.case.attach();before=self.snapshot();plan=self.preview();result=self.service.commit(plan)
        self.assertIn('import_skin',result);self.assertEqual(self.case.weights,[1,0,0,1,1,0]);self.assertEqual(self.fixture.dq,[0,.5,1]);self.assertEqual(self.fixture.method,2)
        self.assertEqual(self.operations,[]);self.assertEqual(len(self.undo_stack),1);self.assertIsNone(self.chunk)
        self.undo();self.assertEqual(self.snapshot(),before);self.redo();self.assertEqual(len(core.decode(self.case.graph['raw'])['layers']),2)
    def test_unskinned_target_creates_binding_and_new_stack_then_undo_restores_unskinned(self):
        self.has_skin=False;before=self.snapshot();plan=self.preview();self.service.commit(plan)
        self.assertTrue(self.has_skin);self.assertEqual(self.operations[0][0],'bind');self.assertEqual(len(self.undo_stack),1)
        self.assertEqual(core.decode(self.case.graph['raw'])['layers'][0]['name'],'Imported skin')
        self.undo();self.assertEqual(self.snapshot(),before);self.assertFalse(self.has_skin)
    def test_missing_influence_is_added_at_zero_without_unlock_flag_and_remapped_layers_survive(self):
        self.case.ids=['a'];self.case.weights=[1.]*3;self.case.attach();before=self.snapshot()
        plan=self.preview();self.assertEqual(plan['missing'],['|b']);self.service.commit(plan)
        self.assertEqual(self.case.ids,['a','b']);self.assertEqual(self.operations[0][2]['weight'],0.)
        old=core.remap(core.decode(before[3]['raw']),['a','b']);actual=core.decode(self.case.graph['raw'])
        self.assertEqual(actual['layers'][0],old['layers'][0]);self.assertEqual(actual['base'],old['base'])
        self.undo();self.assertEqual(self.snapshot(),before)
    def test_create_and_add_switches_reject_before_binding(self):
        self.has_skin=False;plan=self.preview()
        with self.assertRaisesRegex(ValueError,'Create skinCluster'):self.service.commit(plan,create_skin=False)
        self.assertEqual(self.operations,[]);self.has_skin=True;self.case.ids=['a'];self.case.weights=[1.]*3
        plan=self.preview()
        with self.assertRaisesRegex(ValueError,'Add missing'):self.service.commit(plan,add_influences=False)
        self.assertEqual(self.operations,[])
    def test_new_influence_lock_rejects_without_automatic_unlock_or_binding(self):
        self.case.ids=['a'];self.case.weights=[1.]*3;plan=self.preview()
        self.ns['cmds'].attributeQuery=lambda *a,**kw:True
        old_get=self.ns['cmds'].getAttr;self.ns['cmds'].getAttr=lambda plug:True if plug.endswith('.lockInfluenceWeights') else old_get(plug)
        with self.assertRaisesRegex(ValueError,'mapped influence is locked'):self.service.commit(plan)
        self.assertEqual(self.operations,[]);self.assertEqual(self.case.ids,['a'])
    def test_changed_target_weights_geometry_layer_data_dq_or_method_invalidates_preview(self):
        for mode in ('weights','points','dq','method','metadata'):
            with self.subTest(mode=mode):
                self.setUp();plan=self.preview()
                if mode=='weights':self.case.weights[:2]=[.5,.5]
                elif mode=='points':self.points[0]=(.2,0,0)
                elif mode=='dq':self.fixture.dq[0]=.2
                elif mode=='method':self.fixture.method=2
                else:self.case.attach()
                with self.assertRaisesRegex(ValueError,'changed after Preview'):self.service.commit(plan)
                self.assertEqual(self.operations,[]);self.assertIsNone(self.chunk)
    def test_unbound_candidate_pose_change_and_scene_reload_reject_old_plan(self):
        plan=self.preview();self.records[0]['position'][0]=1.
        with self.assertRaisesRegex(ValueError,'joint bind data'):self.service.commit(plan)
        plan=self.preview();self.dead=True
        with self.assertRaisesRegex(ValueError,'scene changed'):self.service.commit(plan)
    def test_partial_binding_failure_rolls_back_influence_addition(self):
        self.case.ids=['a'];self.case.weights=[1.]*3;self.case.attach();before=self.snapshot();plan=self.preview();self.fail_binding=True
        with self.assertRaisesRegex(RuntimeError,'Binding failed'):self.service.commit(plan)
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.undo_stack,[]);self.assertIsNone(self.chunk)
    def test_import_failure_rolls_back_new_skin_binding_and_leaves_no_pending_token(self):
        self.has_skin=False;before=self.snapshot();plan=self.preview();self.case.fail_write=True
        with self.assertRaisesRegex(RuntimeError,'skin write failed'):self.service.commit(plan)
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.service.runtime.pending,{});self.assertEqual(self.undo_stack,[])
    def test_authoring_readback_failure_rolls_back_complete_import(self):
        before=self.snapshot();plan=self.preview();self.corrupt_saved=True
        with self.assertRaisesRegex(RuntimeError,'coverage was not retained'):self.service.commit(plan)
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.undo_stack,[])
    def test_native_edits_outside_layers_are_not_silently_absorbed(self):
        self.case.attach();self.case.weights[:2]=[.4,.6]
        with self.assertRaisesRegex(ValueError,'Native weights differ'):self.preview()
        self.assertEqual(self.operations,[])
    def test_vertex_id_topology_error_occurs_without_any_scene_write(self):
        self.signature='0'*64
        with self.assertRaisesRegex(ValueError,'Vertex ID'):self.preview()
        self.assertEqual(self.operations,[]);self.assertEqual(self.undo_stack,[])
    def test_disabled_undo_and_incomplete_mapping_prevent_commit(self):
        plan=self.preview();self.enabled=False
        with self.assertRaisesRegex(ValueError,'Enable Maya Undo'):self.service.commit(plan)
        self.enabled=True;self.records=[];plan=self.preview()
        with self.assertRaisesRegex(ValueError,'Resolve every'):self.service.commit(plan)
        self.assertEqual(self.operations,[])
