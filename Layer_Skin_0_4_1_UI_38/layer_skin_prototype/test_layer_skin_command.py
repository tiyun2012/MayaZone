"""Complete command planning/rollback against recording API objects. Native DG is not emulated."""
import array
import copy
import contextlib
import json
import sys
import types
import unittest
from unittest import mock
import layer_skin_core as core
import test_layer_skin as regression


class CommandTests(unittest.TestCase):
    def setUp(self):
        fixture=regression.PluginLoaderTests();fixture.setUp();self.ns=fixture.execute()
        self.graph=dict(exists=False,raw=None);self.log=[];self.ids=['a','b'];self.weights=[1.,0.]*3
        self.fail_data=False;self.fail_write=False;case=self
        class Modifier:
            def __init__(self):self.create=False;self.raw=None;self.delete=False;self.before=None
            def createNode(self,kind):self.create=True;return 'metadata'
            def renameNode(self,*args):pass
            def addAttribute(self,*args):pass
            def connect(self,*args):pass
            def newPlugValueString(self,plug,value):self.raw=value
            def deleteNode(self,node):self.delete=True
            def doIt(self):
                self.before=dict(case.graph);case.log.append('create' if self.create else 'data')
                if self.create:case.graph['exists']=True
                elif case.fail_data:raise RuntimeError('metadata write failed')
                if self.raw is not None:case.graph['raw']=self.raw
                if self.delete:case.graph.update(exists=False,raw=None)
            def undoIt(self):
                case.log.append('undo create' if self.create else 'undo data')
                if self.before is not None:case.graph.update(self.before)
        class Component:
            def __init__(self,obj=None):self.obj=obj if obj is not None else []
            def create(self,*args):return self.obj
            def addElements(self,vertices):self.obj.extend(vertices)
        class Skin:
            def influenceObjects(self):return [types.SimpleNamespace(node=lambda identity=identity:identity) for identity in case.ids]
            def findPlug(self,*args):return 'skin.message'
            def setWeights(self,dag,component,indices,values,normalize):
                case.log.append(('weights',list(component),list(indices),list(values)))
                for row,vertex in enumerate(component):
                    for column,index in enumerate(indices):case.weights[vertex*len(case.ids)+index]=values[row*len(indices)+column]
                if case.fail_write:case.fail_write=False;raise RuntimeError('skin write failed')
            def getWeights(self,dag,component):
                return [value for vertex in component for value in case.weights[vertex*len(case.ids):(vertex+1)*len(case.ids)]],len(case.ids)
        self.skin=Skin();self.dag=types.SimpleNamespace(node=lambda:'mesh-node')
        def context(target):return dict(shape='mesh',skin='skin',fn=self.skin,dag=self.dag,count=3,ids=list(self.ids),topology='topology',weights=list(self.weights))
        def metadata(ctx):return ('metadata',core.remap(core.decode(self.graph['raw']),self.ids)) if self.graph['exists'] else (None,None)
        def dependency(node):return types.SimpleNamespace(findPlug=lambda name,*args:(node,name),uuid=lambda:types.SimpleNamespace(asString=lambda:node))
        def preflight(ctx,meta,before,after,candidates):
            self.log.append(('preflight',list(candidates)));return [v for v in candidates if before[v*len(self.ids):(v+1)*len(self.ids)]!=after[v*len(self.ids):(v+1)*len(self.ids)]]
        self.ns.update(context=context,metadata=metadata,preflight=preflight,obj=lambda node:node)
        self.ns['cmds'].undoInfo=lambda **kw:True
        self.ns['cmds'].getAttr=lambda plug:self.graph['raw']
        self.ns['om'].MDGModifier=Modifier;self.ns['om'].MFnDependencyNode=dependency
        self.ns['om'].MFnSingleIndexedComponent=Component;self.ns['om'].MFn=types.SimpleNamespace(kMeshVertComponent=0)
        self.ns['om'].MIntArray=list;self.ns['om'].MDoubleArray=list
        self.ns['om'].MFnTypedAttribute=lambda:types.SimpleNamespace(create=lambda *args:'state-attr')
        self.ns['om'].MFnMessageAttribute=lambda:types.SimpleNamespace(create=lambda *args:'message-attr')
        self.ns['om'].MFnData=types.SimpleNamespace(kString=0)
        self.ns['om'].MArgDatabase=lambda syntax,args:args
    def command(self,action,**data):
        command=self.ns['LayerCommand']();command.syntax=lambda:None;command.setResult=lambda result:setattr(command,'result',result)
        args=types.SimpleNamespace(isFlagSet=lambda flag:True,flagArgumentString=lambda flag,index:action if flag=='-action' else json.dumps(dict(target='mesh',**data)))
        command.doIt(args);return command
    def attach(self):
        state=core.create(self.weights,3,self.ids,'topology');state=core.edit(state,'add',dict(name='Arm'))
        layer=state['layers'][0]['id'];state=core.edit(state,'membership',dict(layer=layer,joints=self.ids))
        self.graph.update(exists=True,raw=core.encode(state));return layer
    @contextlib.contextmanager
    def assignment_environment(self):
        geometry=self.ns['sibling']('layer_skin_assignment');geometry.CACHE.clear()
        frame=lambda x:dict(position=[x,0.,0.],end=[x+1.,0.,0.],x=[1.,0.,0.],y=[0.,1.,0.],z=[0.,0.,1.])
        reference=dict(points=[[0.,0.,0.],[1.,0.,0.],[2.,0.,0.]],joints={'a':dict(frame(0.),parent=None),'b':dict(frame(2.),parent='a')},time=1.,hierarchy_version=1)
        self.ns['reference_capture']=mock.Mock(return_value=reference)
        self.ns['selected_vertices']=lambda ctx,whole:list(range(3)) if whole else [1]
        class Distance:
            def __init__(self,value,unit):self.value=value
            def asCentimeters(self):return self.value
        Distance.uiUnit=staticmethod(lambda:0);self.ns['om'].MDistance=Distance
        case=self
        class Computation:
            def beginComputation(self,*args):case.log.append('begin assignment')
            def isInterruptRequested(self):return getattr(case,'cancel_assignment',False)
            def endComputation(self):case.log.append('end assignment')
        legacy=types.ModuleType('maya.OpenMaya');legacy.MComputation=Computation
        maya=types.ModuleType('maya');maya.OpenMaya=legacy
        with mock.patch.dict(sys.modules,{'maya':maya,'maya.OpenMaya':legacy}):yield
    def test_value_operation_commits_selected_rows_and_roundtrips_native_command_undo(self):
        layer=self.attach();self.ns['selected_vertices']=lambda ctx,whole:[1]
        self.command('paint',layer=layer,mode='weights',joint='b',values={'1':.4})
        for operation,amount,expected in [('add',.2,.6),('scale',.5,.2),('replace',.8,.8)]:
            with self.subTest(operation=operation):
                raw=self.graph['raw'];weights=self.weights[:]
                command=self.command('value_operation',layer=layer,mode='weights',joint='b',operation=operation,amount=amount)
                self.assertAlmostEqual(self.weights[3],expected);self.assertEqual(self.weights[:2],weights[:2]);self.assertEqual(self.weights[4:],weights[4:])
                after=self.graph['raw'];command.undoIt();self.assertEqual(self.graph['raw'],raw);self.assertEqual(self.weights,weights)
                command.redoIt();self.assertEqual(self.graph['raw'],after);self.assertAlmostEqual(self.weights[3],expected);command.undoIt()
    def test_mask_value_operation_saves_data_without_changing_weight_samples(self):
        layer=self.attach();self.ns['selected_vertices']=lambda ctx,whole:[0,1,2]
        raw=self.graph['raw'];weights=self.weights[:]
        command=self.command('value_operation',layer=layer,mode='mask',operation='add',amount=-.2,whole=True)
        row=core.decode(self.graph['raw'])['layers'][0]
        self.assertEqual(row['mask'],{'0':.8,'1':.8,'2':.8});self.assertEqual(row['samples'],{})
        self.assertEqual(self.weights,weights);command.undoIt();self.assertEqual(self.graph['raw'],raw)
    def test_value_operation_preserves_outside_edit_and_stale_state_guards(self):
        layer=self.attach();self.ns['selected_vertices']=lambda ctx,whole:[1]
        raw=self.graph['raw'];self.weights=[0.,1.]*3
        with self.assertRaisesRegex(ValueError,'outside Layer Skin'):
            self.command('value_operation',layer=layer,mode='weights',joint='b',operation='add',amount=.2)
        self.assertEqual(self.graph['raw'],raw);self.assertEqual(self.weights,[0.,1.]*3)
        self.weights=[1.,0.]*3
        with self.assertRaisesRegex(ValueError,'changed during the stroke'):
            self.command('value_operation',layer=layer,mode='weights',joint='b',operation='add',amount=.2,expected='stale')
        self.assertEqual(self.graph['raw'],raw)
    def test_operation_warm_planner_keeps_registered_class_and_existing_undo_objects(self):
        layer=self.attach();previous=self.command('paint',layer=layer,mode='weights',joint='b',values={'1':.4})
        source=self.ns['prepare_edit'];command_class=self.ns['LayerCommand'];self.ns['selected_vertices']=lambda ctx,whole:[1]
        def legacy(ctx,meta,state,action,data):
            if action=='value_operation':raise ValueError('Old registered planner')
            return source(ctx,meta,state,action,data)
        self.ns['prepare_edit']=legacy;module=self.ns['sibling']('layer_skin_operations');self.assertTrue(module.install(self.ns));module.install(self.ns)
        command=self.command('value_operation',layer=layer,mode='weights',joint='b',operation='scale',amount=.5)
        self.assertIs(self.ns['LayerCommand'],command_class);self.assertAlmostEqual(self.weights[3],.2)
        command.undoIt();self.assertAlmostEqual(self.weights[3],.4);previous.undoIt();self.assertEqual(self.weights,[1.,0.]*3)
        previous.redoIt();command.redoIt();self.assertAlmostEqual(self.weights[3],.2)
    def test_value_operation_failure_rolls_back_skin_and_metadata(self):
        layer=self.attach();self.ns['selected_vertices']=lambda ctx,whole:[1]
        raw=self.graph['raw'];weights=self.weights[:];self.fail_write=True
        with self.assertRaisesRegex(RuntimeError,'skin write failed'):
            self.command('value_operation',layer=layer,mode='weights',joint='b',operation='replace',amount=.6)
        self.assertEqual(self.graph['raw'],raw);self.assertEqual(self.weights,weights)
    def test_direct_paint_records_new_layer_membership_and_weight_in_same_command(self):
        layer=self.attach();state=core.decode(self.graph['raw']);state=core.edit(state,'membership',dict(layer=layer,joints=[]));self.graph['raw']=core.encode(state)
        before=self.graph['raw'];command=self.command('paint',layer=layer,mode='weights',joint='b',values={'1':.6})
        self.assertEqual(core.decode(self.graph['raw'])['layers'][0]['joints'],['b'])
        command.undoIt();self.assertEqual(self.graph['raw'],before);self.assertEqual(self.weights,[1,0]*3)
        command.redoIt();self.assertEqual(core.decode(self.graph['raw'])['layers'][0]['joints'],['b'])
    def test_selected_assignment_generates_only_chosen_joints_and_preserves_paint_mask(self):
        layer=self.attach();self.command('paint',layer=layer,mode='weights',joint='a',values={'0':.4})
        self.command('paint',layer=layer,mode='mask',values={'1':.3})
        before=core.decode(self.graph['raw']);paint=before['layers'][0]['samples'];mask=before['layers'][0]['mask']
        with self.assignment_environment():
            command=self.command('assign',layer=layer,joints=['b'],whole=True,settings=dict(method='point',radius=10.))
        row=core.decode(self.graph['raw'])['layers'][0]
        self.assertTrue(row['generated']);self.assertTrue(all(sample['weights']==[0.,1.] for sample in row['generated'].values()))
        self.assertEqual(row['samples'],paint);self.assertEqual(row['mask'],mask)
        self.assertEqual(row['assignment']['joints'],['b'])
        command.undoIt();self.assertEqual(core.decode(self.graph['raw']),before)
    def test_selected_assignment_registers_an_existing_influence_on_an_empty_layer(self):
        layer=self.attach();state=core.decode(self.graph['raw']);state=core.edit(state,'membership',dict(layer=layer,joints=[]));self.graph['raw']=core.encode(state)
        with self.assignment_environment():self.command('assign',layer=layer,joints=['b'],whole=False,settings=dict(method='bone',radius=10.))
        row=core.decode(self.graph['raw'])['layers'][0]
        self.assertEqual(row['joints'],['b']);self.assertEqual(set(row['generated']),{'1'})
    def test_flood_then_assign_replaces_manual_rows_and_undo_restores_them(self):
        layer=self.attach();self.ns['selected_vertices']=lambda ctx,whole:list(range(3))
        self.command('flood',layer=layer,joint='a',whole=True,value=1.)
        before=self.graph['raw'];weights=self.weights[:]
        with self.assignment_environment():
            command=self.command('assign',layer=layer,joints=['b'],whole=False,replace_manual=True,settings=dict(method='point',radius=10.))
        row=core.decode(self.graph['raw'])['layers'][0]
        self.assertEqual(set(row['samples']),{'0','2'})
        # Nearest assignment has full coverage at the scoped middle vertex;
        # clearing Flood leaves vertices outside the scope untouched.
        for actual,expected in zip(self.weights,[1,0,0,1,1,0]):self.assertAlmostEqual(actual,expected)
        command.undoIt();self.assertEqual(self.graph['raw'],before);self.assertEqual(self.weights,weights)
        command.redoIt()
        for actual,expected in zip(self.weights,[1,0,0,1,1,0]):self.assertAlmostEqual(actual,expected)
    def test_warm_extension_fixes_old_assignment_planner_and_old_core_without_replacing_command_class(self):
        layer=self.attach();previous=self.command('paint',layer=layer,mode='weights',joint='a',values={'0':1.,'1':1.,'2':1.})
        source=self.ns['prepare_edit'];command_class=self.ns['LayerCommand']
        def legacy(ctx,meta,state,action,data):
            if action=='relax_stroke':raise ValueError('Old registered planner')
            old=dict(data);old.pop('replace_manual',None)
            result=source(ctx,meta,state,action,old);data.update(old);return result
        self.ns['prepare_edit']=legacy;module=self.ns['sibling']('layer_skin_relax');module.install(self.ns)
        with self.assignment_environment():
            command=self.command('assign',layer=layer,joints=['b'],whole=True,replace_manual=True,settings=dict(method='point',radius=10.))
        self.assertIs(self.ns['LayerCommand'],command_class)
        for actual,expected in zip(self.weights,[0,1,0,1,0,1]):self.assertAlmostEqual(actual,expected)
        self.assertEqual(core.decode(self.graph['raw'])['layers'][0]['samples'],{})
        command.undoIt();previous.undoIt();self.assertEqual(self.weights,[1.,0.]*3)
    def test_relax_stroke_commits_samples_and_mask_with_sparse_skin_undo(self):
        layer=self.attach();before=self.graph['raw'];weights=self.weights[:]
        command=self.command('relax_stroke',layer=layer,mode='weights',samples={'1':dict(weights=[.4,.6],coverage=1.)})
        self.assertEqual(self.weights,[1,0,.4,.6,1,0]);self.assertEqual(command.vertices,[1])
        command.undoIt();self.assertEqual(self.graph['raw'],before);self.assertEqual(self.weights,weights)
        command.redoIt();mask=self.command('relax_stroke',layer=layer,mode='mask',values={'1':.5})
        self.assertAlmostEqual(self.weights[3],.3);mask.undoIt();self.assertAlmostEqual(self.weights[3],.6)
    def test_relax_stroke_rejects_stale_or_invalid_payload_and_rolls_back_native_failure(self):
        layer=self.attach();before=self.graph['raw'];weights=self.weights[:]
        for data in (dict(expected='stale',samples={'1':dict(weights=[0,1],coverage=1)}),dict(samples={'99':dict(weights=[0,1],coverage=1)}),dict(samples={'1':dict(weights=[0,3],coverage=1)})):
            with self.subTest(data=data),self.assertRaises(ValueError):self.command('relax_stroke',layer=layer,mode='weights',**data)
        self.fail_write=True
        with self.assertRaisesRegex(RuntimeError,'skin write failed'):
            self.command('relax_stroke',layer=layer,mode='weights',samples={'1':dict(weights=[0.,1.],coverage=1.)})
        self.assertEqual(self.graph['raw'],before);self.assertEqual(self.weights,weights)
    def test_warm_extension_accepts_relax_stroke_on_old_registered_command(self):
        layer=self.attach();source=self.ns['prepare_edit']
        def legacy(ctx,meta,state,action,data):
            if action=='relax_stroke':raise ValueError('Unknown action')
            return source(ctx,meta,state,action,data)
        self.ns['prepare_edit']=legacy;module=self.ns['sibling']('layer_skin_relax');module.install(self.ns)
        command=self.command('relax_stroke',layer=layer,mode='weights',samples={'0':dict(weights=[0,1],coverage=1)})
        self.assertEqual(self.weights,[0,1,1,0,1,0]);command.undoIt();self.assertEqual(self.weights,[1,0]*3)
    def test_invalid_assignment_joint_is_rejected_before_capture_or_write(self):
        layer=self.attach();before=self.graph['raw']
        with self.assignment_environment():
            with self.assertRaisesRegex(ValueError,'Choose joints'):self.command('assign',layer=layer,joints=['missing'],whole=True)
            self.ns['reference_capture'].assert_not_called()
        self.assertEqual(self.graph['raw'],before);self.assertFalse(any(isinstance(item,tuple) and item[0]=='weights' for item in self.log))
    def test_axis_partition_writes_child_claim_once_reuses_cache_and_undoes(self):
        layer=self.attach();before_raw=self.graph['raw']
        with self.assignment_environment():
            self.ns['reference_capture'].return_value['points']=[[.5,1000.,0.],[3.,0.,0.],[-1.,0.,0.]]
            command=self.command('assign',layer=layer,joints=['b','a'],whole=True,settings=dict(method='axis'))
            row=core.decode(self.graph['raw'])['layers'][0]
            self.assertEqual(row['generated']['0'],dict(weights=[1.,0.],coverage=1.))
            self.assertEqual(row['generated']['1'],dict(weights=[0.,1.],coverage=1.));self.assertEqual(row['generated']['2'],dict(weights=[1.,0.],coverage=1.))
            self.assertEqual(self.weights,[1.,0.,0.,1.,1.,0.])
            tests=self.ns['sibling']('layer_skin_assignment').CACHE.vertex_tests
            repeat=self.command('assign',layer=layer,joints=['b','a'],whole=True,settings=dict(method='axis'))
            self.assertFalse(repeat.isUndoable());self.assertEqual(self.ns['sibling']('layer_skin_assignment').CACHE.vertex_tests,tests)
            command.undoIt();self.assertEqual(self.graph['raw'],before_raw);self.assertEqual(self.weights,[1.,0.]*3)
            command.redoIt();self.assertEqual(self.weights,[1.,0.,0.,1.,1.,0.])
    def test_cancelled_assignment_closes_computation_and_leaves_the_scene_unchanged(self):
        layer=self.attach();before=self.graph['raw'];self.cancel_assignment=True
        with self.assignment_environment():
            with self.assertRaisesRegex(RuntimeError,'cancelled'):self.command('assign',layer=layer,joints=['b'],whole=True,settings=dict(radius=10.))
        self.assertEqual(self.graph['raw'],before);self.assertIn('end assignment',self.log);self.assertEqual(self.weights,[1,0]*3)
    def test_flood_registers_the_selected_bound_joint_without_a_membership_command(self):
        layer=self.attach();state=core.decode(self.graph['raw']);state=core.edit(state,'membership',dict(layer=layer,joints=[]));self.graph['raw']=core.encode(state)
        self.ns['selected_vertices']=lambda ctx,whole:[1]
        command=self.command('flood',layer=layer,joint='b',whole=False,value=.6)
        self.assertEqual(core.decode(self.graph['raw'])['layers'][0]['joints'],['b'])
        self.assertEqual(command.vertices,[1]);command.undoIt();self.assertEqual(self.weights,[1,0]*3)
    def test_reference_candidates_include_unbound_descendants_without_duplicate_bound_joints(self):
        paths={name:types.SimpleNamespace(fullPathName=lambda name=name:name) for name in ('|a','|a|b','|a|unbound')}
        ctx=dict(influences=[paths['|a'],paths['|a|b']])
        self.ns['joint_roots']=lambda ctx:['|a'];queries=[]
        def relatives(name,**kw):queries.append((name,kw));return ['|a|unbound','|a|b']
        self.ns['cmds'].listRelatives=relatives
        class Selection:
            def add(self,name):self.name=name
            def getDagPath(self,index):return paths[self.name]
        self.ns['om'].MSelectionList=Selection
        actual=self.ns['reference_joint_paths'](ctx)
        self.assertEqual([path.fullPathName() for path in actual],['|a','|a|b','|a|unbound'])
        self.assertEqual(queries,[('|a',dict(allDescendents=True,type='joint',fullPath=True))])
    def test_first_add_captures_base_and_layer_as_one_transaction(self):
        command=self.command('add',name='First');state=core.decode(self.graph['raw'])
        self.assertEqual(state['base'],self.weights);self.assertEqual(len(state['layers']),1)
        self.assertEqual(len(command.before),0);self.assertTrue(command.isUndoable())
        command.undoIt();self.assertFalse(self.graph['exists'])
        command.redoIt();self.assertTrue(self.graph['exists']);self.assertEqual(len(core.decode(self.graph['raw'])['layers']),1)
    def test_first_add_failure_removes_new_metadata(self):
        self.fail_data=True
        with self.assertRaisesRegex(RuntimeError,'metadata write failed'):self.command('add')
        self.assertFalse(self.graph['exists']);self.assertEqual(self.weights,[1.,0.]*3)
    def test_paint_keeps_only_changed_rows_in_undo_buffers(self):
        layer=self.attach();command=self.command('paint',layer=layer,mode='weights',joint='b',values={'1':.6})
        self.assertEqual(command.vertices,[1]);self.assertEqual(list(command.before),[1,0]);self.assertEqual(list(command.after),[.4,.6])
        self.assertNotIn('weights',command.ctx);self.assertEqual(self.weights,[1,0,.4,.6,1,0])
        command.undoIt();self.assertEqual(self.weights,[1,0]*3)
        command.redoIt();self.assertEqual(self.weights,[1,0,.4,.6,1,0])
    def test_skin_write_failure_restores_weights_and_metadata(self):
        layer=self.attach();raw=self.graph['raw'];self.fail_write=True
        with self.assertRaisesRegex(RuntimeError,'skin write failed'):self.command('paint',layer=layer,mode='weights',joint='b',values={'1':.6})
        self.assertEqual(self.weights,[1,0]*3);self.assertEqual(self.graph['raw'],raw)
    def test_noop_property_creates_no_undo_record(self):
        layer=self.attach();command=self.command('properties',layer=layer,name='Arm')
        self.assertFalse(command.isUndoable());self.assertEqual(self.log,[])
    def test_rename_and_disjoint_reorder_skip_weight_recomposition(self):
        layer_a=self.attach();self.command('paint',layer=layer_a,mode='weights',joint='b',values={'0':.5})
        self.command('add',name='Leg');layer_b=core.decode(self.graph['raw'])['layers'][-1]['id']
        self.command('membership',layer=layer_b,joints=self.ids)
        self.command('paint',layer=layer_b,mode='weights',joint='b',values={'2':.5})
        self.log.clear()
        rename=self.command('properties',layer=layer_a,name='Renamed')
        self.assertEqual(rename.vertices,[]);self.assertIn(('preflight',[]),self.log)
        self.log.clear()
        reorder=self.command('reorder',order=[layer_b,layer_a])
        self.assertEqual(reorder.vertices,[]);self.assertIn(('preflight',[]),self.log)
    def test_external_skin_edits_stop_before_metadata_mutation(self):
        layer=self.attach();raw=self.graph['raw'];self.weights[:2]=[.2,.8]
        with self.assertRaisesRegex(ValueError,'outside Layer Skin'):self.command('properties',layer=layer,opacity=.5)
        self.assertEqual(self.graph['raw'],raw);self.assertEqual(self.log,[])
    def test_weight_writer_maps_physical_columns_by_uuid(self):
        layer=self.attach();command=self.command('paint',layer=layer,mode='weights',joint='b',values={'1':.6})
        self.ids=['b','a'];self.weights=[self.weights[i+1] if i%2==0 else self.weights[i-1] for i in range(6)]
        command.undoIt();self.assertEqual(self.weights,[0,1]*3)
        command.redoIt();self.assertEqual(self.weights,[0,1,.6,.4,0,1])
    def test_restore_and_bake_remove_authoring_data_with_undo(self):
        layer=self.attach();self.command('paint',layer=layer,mode='weights',joint='b',values={'1':.6})
        before=list(self.weights);bake=self.command('bake');self.assertFalse(self.graph['exists']);self.assertEqual(self.weights,before)
        bake.undoIt();self.assertTrue(self.graph['exists'])
        restore=self.command('restore');self.assertEqual(self.weights,[1,0]*3);self.assertFalse(self.graph['exists'])
        restore.undoIt();self.assertEqual(self.weights,before);self.assertTrue(self.graph['exists'])
    def test_stale_stroke_rejects_before_maya_edits(self):
        layer=self.attach()
        with self.assertRaisesRegex(ValueError,'changed during the stroke'):self.command('paint',layer=layer,mode='mask',values={'1':0},expected='stale')
        self.assertEqual(self.log,[])
    @contextlib.contextmanager
    def relax_environment(self):
        with self.assignment_environment():
            class Iterator:
                def __init__(self,dag):pass
                def setIndex(self,v):self.v=v
                def getConnectedVertices(self):return {0:[1],1:[0,2],2:[1]}[self.v]
            self.ns['om'].MItMeshVertex=Iterator
            self.ns['om'].MGlobal=types.SimpleNamespace(getActiveSelectionList=lambda:types.SimpleNamespace(length=lambda:0))
            self.ns['sibling']('layer_skin_relax').CACHE.clear()
            yield
    def paint_relax_input(self,layer):
        self.command('paint',layer=layer,mode='weights',joint='a',values={'0':1.})
        self.command('paint',layer=layer,mode='weights',joint='b',values={'1':1.,'2':1.})
    def test_relax_commits_all_rows_in_one_command_and_undo_redo_restore_metadata(self):
        layer=self.attach();self.paint_relax_input(layer);before_raw=self.graph['raw'];before=list(self.weights)
        with self.relax_environment():command=self.command('relax',layer=layer,iterations=1,strength=.5)
        self.assertEqual(self.weights,[.5,.5,.25,.75,0.,1.]);self.assertEqual(command.vertices,[0,1])
        after_raw=self.graph['raw'];command.undoIt();self.assertEqual(self.weights,before);self.assertEqual(self.graph['raw'],before_raw)
        command.redoIt();self.assertEqual(self.graph['raw'],after_raw);self.assertEqual(self.weights,[.5,.5,.25,.75,0.,1.])
    def test_relax_mask_uses_native_planner_even_without_authored_joint_weights(self):
        layer=self.attach();self.command('paint',layer=layer,mode='mask',values={'0':0.})
        raw=self.graph['raw'];weights=self.weights[:]
        with self.relax_environment():command=self.command('relax',layer=layer,mode='mask',iterations=1,strength=.5)
        row=core.decode(self.graph['raw'])['layers'][0]
        self.assertEqual(row['mask'],{'0':.5,'1':.75});self.assertEqual(row['samples'],{})
        self.assertEqual(self.weights,weights);command.undoIt();self.assertEqual(self.graph['raw'],raw)
        command.redoIt();self.assertEqual(core.decode(self.graph['raw'])['layers'][0]['mask'],{'0':.5,'1':.75})
    def test_relax_mask_cancellation_releases_computation_without_writing_data(self):
        layer=self.attach();self.command('paint',layer=layer,mode='mask',values={'0':0.})
        raw=self.graph['raw'];weights=self.weights[:];self.cancel_assignment=True;self.log=[]
        with self.relax_environment(),self.assertRaisesRegex(RuntimeError,'Relax cancelled'):
            self.command('relax',layer=layer,mode='mask',iterations=2)
        self.assertEqual(self.graph['raw'],raw);self.assertEqual(self.weights,weights)
        self.assertIn('end assignment',self.log);self.assertNotIn('data',self.log)
    def test_relax_write_failure_rolls_back_skin_and_layer_data(self):
        layer=self.attach();self.paint_relax_input(layer);before_raw=self.graph['raw'];before=list(self.weights);self.fail_write=True
        with self.relax_environment(),self.assertRaisesRegex(RuntimeError,'skin write failed'):
            self.command('relax',layer=layer,iterations=1)
        self.assertEqual(self.graph['raw'],before_raw);self.assertEqual(self.weights,before)
    def test_cancelled_relax_ends_computation_and_performs_no_authoring_write(self):
        layer=self.attach();self.paint_relax_input(layer);before_raw=self.graph['raw'];before=list(self.weights);self.cancel_assignment=True
        self.log=[]
        with self.relax_environment(),self.assertRaisesRegex(RuntimeError,'Relax cancelled'):
            self.command('relax',layer=layer,iterations=2)
        self.assertEqual(self.graph['raw'],before_raw);self.assertEqual(self.weights,before)
        self.assertIn('end assignment',self.log);self.assertNotIn('data',self.log)
    def test_relax_zero_strength_is_a_native_noop_without_an_undo_record(self):
        layer=self.attach();self.paint_relax_input(layer)
        with self.relax_environment():command=self.command('relax',layer=layer,strength=0.)
        self.assertFalse(command.isUndoable())
    def test_empty_layer_relax_skips_topology_and_creates_no_undo_record(self):
        layer=self.attach();command=self.command('relax',layer=layer)
        self.assertFalse(command.isUndoable())
    def test_relax_does_not_bypass_existing_external_skin_edit_guard(self):
        layer=self.attach();raw=self.graph['raw'];self.weights[:2]=[.5,.5]
        with self.assertRaisesRegex(ValueError,'outside Layer Skin'):self.command('relax',layer=layer)
        self.assertEqual(self.graph['raw'],raw);self.assertEqual(self.log,[])
    def test_live_relax_planner_extension_keeps_command_class_and_previous_undo(self):
        layer=self.attach();previous=self.command('paint',layer=layer,mode='weights',joint='b',values={'1':1.,'2':1.})
        # Model an already-registered pre-UI5 planner which has no relax branch.
        source=self.ns['prepare_edit'];command_class=self.ns['LayerCommand']
        def legacy(ctx,meta,state,action,data):
            if action=='relax':raise ValueError('old command has no relax')
            return source(ctx,meta,state,action,data)
        self.ns['prepare_edit']=legacy
        with self.relax_environment():
            module=self.ns['sibling']('layer_skin_relax');self.assertTrue(module.install(self.ns));self.assertTrue(module.install(self.ns))
            self.assertIs(self.ns['LayerCommand'],command_class);self.assertIs(self.ns['prepare_edit']._layer_skin_relax_original,legacy)
            current=self.command('relax',layer=layer,iterations=1)
        current.undoIt();previous.undoIt();self.assertEqual(self.weights,[1.,0.]*3)
        # Non-relax planning still routes through the previous implementation.
        self.command('properties',layer=layer,name='Still editable')
        self.assertEqual(core.decode(self.graph['raw'])['layers'][0]['name'],'Still editable')


class NativeGuardTests(unittest.TestCase):
    def setUp(self):
        fixture=regression.PluginLoaderTests();fixture.setUp();self.ns=fixture.execute();self.locked=[];self.connected=[];self.held=False;self.maximum=False
        self.plug=types.SimpleNamespace(isLocked=False,isDestination=False)
        self.ns['cmds'].referenceQuery=lambda *args,**kw:False
        self.ns['cmds'].attributeQuery=lambda *args,**kw:self.held
        self.ns['cmds'].getAttr=lambda name:self.maximum if name.endswith('.maintainMaxInfluences') else self.held
        self.ns['cmds'].listAttr=lambda *args,**kw:self.locked
        self.ns['om'].MFnDependencyNode=lambda obj:types.SimpleNamespace(isLocked=False)
        self.ns['obj']=lambda node:node
        self.ctx=dict(shape='mesh',skin='skin',ids=['a','b'],count=3,influences=[types.SimpleNamespace(fullPathName=lambda:'joint')]*2,
            fn=types.SimpleNamespace(findPlug=lambda *args:self.plug,getConnections=lambda:self.connected))
    def check(self):return self.ns['preflight'](self.ctx,None,[1,0]*3,[1,0,.5,.5,1,0],[1])
    def test_changed_rows_use_bulk_guards_without_constructing_weight_plugs(self):self.assertEqual(self.check(),[1])
    def test_locked_selected_channel_is_rejected(self):
        self.locked=['weightList[1].weights[0]']
        with self.assertRaisesRegex(ValueError,'locked'):self.check()
    def test_locked_unaffected_row_is_allowed(self):
        self.locked=['weightList[0].weights[0]'];self.assertEqual(self.check(),[1])
    def test_driven_selected_channel_is_rejected(self):
        self.connected=[types.SimpleNamespace(isDestination=True,partialName=lambda **kw:'weightList[1].weights[0]',name=lambda:'skin.weightList[1].weights[0]')]
        with self.assertRaisesRegex(ValueError,'another driver'):self.check()
    def test_held_influence_is_never_unlocked(self):
        self.held=True
        with self.assertRaisesRegex(ValueError,'influence is locked'):self.check()
    def test_maintain_max_influences_requires_explicit_user_change(self):
        self.maximum=True
        with self.assertRaisesRegex(ValueError,'Maintain Max'):self.check()


if __name__=='__main__':unittest.main(verbosity=2)
