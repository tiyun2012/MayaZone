"""Real command planning with recording graph/skin objects, not a Maya emulator."""
import copy
import unittest
import layer_skin_core as core
import layer_skin_io_backend as backend
import test_layer_skin_command as command_fixture


class ImportCommandTests(unittest.TestCase):
    def setUp(self):
        self.case=command_fixture.CommandTests();self.case.setUp();self.ns=self.case.ns
        context=self.ns['context']
        def ctx(target):value=context(target);value['uuid']='mesh-id';return value
        self.ns['context']=ctx;self.dq=[0.,0.,0.];self.method=0;self.fail_dq=False;self.locked=set();self.driven=set()
        case=self;old_plug=self.case.skin.findPlug
        class Plug:
            def __init__(self,name):self.value=name
            @property
            def isLocked(self):return self.value in case.locked
            @property
            def isDestination(self):return self.value in case.driven
            def name(self):return 'skin.'+self.value
            def asInt(self):return case.method
            def setInt(self,v):case.method=v
            def getExistingArrayAttributeIndices(self):return [0,1,2]
            def elementByLogicalIndex(self,i):return Plug('blendWeights[{}]'.format(i))
        self.case.skin.findPlug=lambda name,*args:Plug(name) if name in ('skinningMethod','blendWeights') else old_plug(name,*args)
        self.case.skin.getBlendWeights=lambda dag,component:[self.dq[v] for v in component]
        def dq_write(dag,component,values):
            for v,value in zip(component,values):self.dq[v]=value
            if self.fail_dq:self.fail_dq=False;raise RuntimeError('DQ write failed')
        self.case.skin.setBlendWeights=dq_write
        self.runtime=backend.install(self.ns)
    def payload(self,**extra):
        return dict(target_uuid='mesh-id',count=3,topology='topology',source_ids=['sA','sB'],mapping=['a','b'],
                    weights=[0.,1.,.4,.6,1.,0.],name='File import',**extra)
    def imported(self,payload=None):
        token=self.runtime.register(payload or self.payload());return self.case.command('import_skin',io_token=token)
    def test_import_new_stack_has_native_undo_redo_and_keeps_command_class(self):
        cls=self.ns['LayerCommand'];before=list(self.case.weights);command=self.imported()
        self.assertIs(self.ns['LayerCommand'],cls);self.assertEqual(self.case.weights,[0,1,.4,.6,1,0])
        self.assertEqual(core.decode(self.case.graph['raw'])['layers'][-1]['name'],'File import')
        command.undoIt();self.assertFalse(self.case.graph['exists']);self.assertEqual(self.case.weights,before)
        command.redoIt();self.assertTrue(self.case.graph['exists']);self.assertEqual(self.case.weights,[0,1,.4,.6,1,0])
    def test_import_preserves_previous_layer_metadata_base_and_old_undo_objects(self):
        layer=self.case.attach();previous=self.case.command('paint',layer=layer,mode='mask',values={'0':.5})
        before=core.decode(self.case.graph['raw']);command=self.imported();after=core.decode(self.case.graph['raw'])
        self.assertEqual(after['layers'][:-1],before['layers']);self.assertEqual(after['base'],before['base'])
        command.undoIt();self.assertEqual(core.decode(self.case.graph['raw']),before)
        previous.undoIt();self.assertEqual(core.decode(self.case.graph['raw'])['layers'][0]['mask'],{})
    def test_dq_only_and_method_change_are_in_the_same_command_undo(self):
        payload=self.payload(dq=[.2,.4,.8],skinning_method=2);payload['weights']=[1,0]*3
        command=self.imported(payload);self.assertEqual(command.vertices,[]);self.assertEqual(self.dq,[.2,.4,.8]);self.assertEqual(self.method,2)
        command.undoIt();self.assertEqual(self.dq,[0,0,0]);self.assertEqual(self.method,0);self.assertFalse(self.case.graph['exists'])
        command.redoIt();self.assertEqual(self.dq,[.2,.4,.8]);self.assertEqual(self.method,2)
    def test_failed_dq_write_rolls_back_weights_settings_and_metadata(self):
        before=self.case.weights[:];self.fail_dq=True
        with self.assertRaisesRegex(RuntimeError,'DQ write failed'):self.imported(self.payload(dq=[.2,.4,.8],skinning_method=2))
        self.assertEqual(self.case.weights,before);self.assertEqual(self.dq,[0,0,0]);self.assertEqual(self.method,0);self.assertFalse(self.case.graph['exists'])
        self.assertEqual(self.runtime.pending,{})
    def test_locked_or_driven_dq_and_method_are_rejected_before_any_write(self):
        for name in ('skinningMethod','blendWeights','blendWeights[1]'):
            with self.subTest(name=name):
                self.locked={name};before=self.case.weights[:]
                with self.assertRaisesRegex(ValueError,'locked or driven'):self.imported(self.payload(dq=[.2,.4,.8],skinning_method=2))
                self.assertEqual(self.case.weights,before);self.assertFalse(self.case.graph['exists']);self.assertEqual(self.method,0)
        self.locked=set();self.driven={'skinningMethod'}
        with self.assertRaisesRegex(ValueError,'driven'):self.imported(self.payload(skinning_method=2))
    def test_stale_token_target_and_mapping_stop_without_graph_write(self):
        with self.assertRaisesRegex(ValueError,'expired'):self.case.command('import_skin',io_token='expired')
        for changes in (dict(target_uuid='old'),dict(count=4),dict(topology='old'),dict(mapping=['a',None])):
            value=self.payload();value.update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.imported(value)
        self.assertFalse(self.case.graph['exists']);self.assertEqual(self.case.weights,[1,0]*3)
    def test_native_weight_failure_rolls_back_and_existing_data_is_unchanged(self):
        self.case.attach();before=copy.deepcopy(self.case.graph);self.case.fail_write=True
        with self.assertRaisesRegex(RuntimeError,'skin write failed'):self.imported()
        self.assertEqual(self.case.graph,before);self.assertEqual(self.case.weights,[1,0]*3)
    def test_warm_old_planner_gains_import_without_replacing_its_class(self):
        cls=self.ns['LayerCommand'];previous=self.ns['prepare_edit']
        def old(ctx,meta,state,action,data):
            if action=='import_skin':raise ValueError('Old command')
            return previous(ctx,meta,state,action,data)
        self.ns['prepare_edit']=old;self.runtime=backend.install(self.ns)
        command=self.imported();self.assertIs(self.ns['LayerCommand'],cls);command.undoIt();self.assertFalse(self.case.graph['exists'])
    def test_repeated_install_and_relax_refresh_do_not_stack_native_method_wrappers(self):
        first_do=self.ns['LayerCommand'].doIt;first_write=self.ns['LayerCommand'].write
        self.assertIs(backend.install(self.ns),self.runtime);self.assertIs(self.ns['LayerCommand'].doIt,first_do)
        original_do=first_do;original_write=first_write._layer_skin_io_original
        module=self.ns['sibling']('layer_skin_relax')
        for _ in range(5):
            module.install(self.ns);self.runtime=backend.install(self.ns)
            self.assertIs(self.ns['LayerCommand'].doIt,original_do)
            self.assertIs(self.ns['LayerCommand'].write._layer_skin_io_original,original_write)
        command=self.imported();command.undoIt();command.redoIt();self.assertEqual(self.case.weights,[0,1,.4,.6,1,0])
    def test_unrelated_commands_and_previous_import_undo_survive_helper_refresh(self):
        imported=self.imported(self.payload(dq=[.2,.4,.8],skinning_method=2))
        self.ns['sibling']('layer_skin_relax').install(self.ns);self.runtime=backend.install(self.ns)
        imported.undoIt();self.assertEqual(self.dq,[0,0,0]);self.assertEqual(self.method,0)
        imported.redoIt();state=core.decode(self.case.graph['raw']);layer=state['layers'][-1]['id']
        renamed=self.case.command('properties',layer=layer,name='Renamed');self.assertEqual(self.method,2)
        renamed.undoIt();self.assertEqual(core.decode(self.case.graph['raw'])['layers'][-1]['name'],'File import')
