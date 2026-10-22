"""Read-only Preview, bulk selection, sparse write guards and progress ownership."""
import ast
import json
from pathlib import Path
import types
import unittest
from unittest import mock
import test_copy_skinning as regression


class PreviewTests(unittest.TestCase):
    def setUp(self):
        regression.PlanTests.setUp(self)
        tree=ast.parse(Path(__file__).with_name('copy_skinning_plugin.py').read_text())
        functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('preview_transfer','select_preview_vertices','preview_key')]
        self.ns['json']=json;exec(compile(ast.Module(body=functions,type_ignores=[]),'<read-only actions>','exec'),self.ns)
        self.data={'source':'s','target':'t','method':'surface'}
        self.ns['writable']=mock.Mock(side_effect=AssertionError('Read-only preview must not run write preflight'))
    def preview(self,**kw):return self.ns['preview_transfer'](dict(self.data,**kw),progress=False)
    def test_preview_does_not_preflight_writes_or_build_undo_rows(self):
        monitor=self.ns['PlanProgress'](False);result=self.ns['_plan'](self.data,monitor,read_only=True)
        self.assertEqual(result['vertices'],[0,1]);self.assertEqual(result['before'],[]);self.assertEqual(result['after'],[])
        self.assertEqual(result['summary']['write_preflight'],'deferred until Copy');self.ns['writable'].assert_not_called()
    def test_repeated_preview_reuses_calculation_after_live_reads(self):
        self.ns['context']=mock.Mock(side_effect=lambda name,**kw:self.source if name=='s' else self.target)
        first=self.preview()
        with mock.patch.object(self.ns['core'],'interpolate',side_effect=AssertionError('must reuse validated preview')):
            second=self.preview()
        self.assertEqual(first['changed_ids'],second['changed_ids']);self.assertTrue(second['preview_cache_reused'])
        self.assertEqual(self.ns['context'].call_count,4)
    def test_repeated_preview_does_not_rebuild_even_if_source_index_was_evicted(self):
        self.preview();key=next(key for key in self.cache.entries if key[0]=='preview');payload=self.cache.get(key)
        self.cache.clear();self.cache.put(key,payload,2048)
        with mock.patch.object(self.cache,'surface',side_effect=AssertionError('must not rebuild index')):
            self.assertTrue(self.preview()['preview_cache_reused'])
    def test_source_weight_paint_invalidates_read_only_result(self):
        self.preview();self.source['weights']=[0,1]*3;result=self.preview()
        self.assertFalse(result['preview_cache_reused']);self.assertEqual(result['changed_vertices'],0)
    def test_target_weight_changes_invalidate_read_only_result(self):
        self.preview();self.target['weights']=[1,0]*3;result=self.preview()
        self.assertFalse(result['preview_cache_reused']);self.assertEqual(result['changed_ids'],[0,2])
    def test_changed_geometry_invalidates_read_only_result(self):
        self.preview();original=self.ns['sample_geometry']
        def sample(ctx,*args,**kw):
            points,triangles=original(ctx,*args,**kw)
            return ([(x,y,z+1) for x,y,z in points] if ctx is self.source else points),triangles
        self.ns['sample_geometry']=sample;self.assertFalse(self.preview()['preview_cache_reused'])
    def test_changed_masks_invalidate_read_only_result(self):
        self.preview(method='region',source_mask=True,target_mask=True);self.masks['target']=[0,0,0]
        result=self.preview(method='region',source_mask=True,target_mask=True);self.assertFalse(result['preview_cache_reused']);self.assertEqual(result['changed_vertices'],0)
    def test_changed_dq_invalidates_read_only_result(self):
        self.preview(copy_dq=True);self.target['fn']=types.SimpleNamespace(getBlendWeights=lambda *_:[.1,.1,.1])
        self.assertFalse(self.preview(copy_dq=True)['preview_cache_reused'])
    def test_manual_map_changes_invalidate_read_only_result(self):
        self.preview();result=self.preview(manual_mapping={'a':'b','b':'a'})
        self.assertFalse(result['preview_cache_reused']);self.assertEqual(result['changed_ids'],[0,2])
    def test_caller_cannot_mutate_cached_preview(self):
        first=self.preview();first['changed_ids'].append(999);self.assertEqual(self.preview()['changed_ids'],[0,1])
    def test_copy_always_checks_live_write_permissions_after_preview(self):
        self.preview();self.ns['writable']=mock.Mock(side_effect=ValueError('target became locked'))
        with self.assertRaisesRegex(ValueError,'became locked'):self.ns['plan'](self.data)
        self.ns['writable'].assert_called_once()
    def test_preview_cap_preserves_full_changed_count_without_snapshots(self):
        count=6001;self.source.update(count=count,weights=[1,0]*count);self.target.update(count=count,weights=[0,1]*count)
        result=self.preview(method='id');self.assertEqual(result['changed_vertices'],count);self.assertEqual(len(result['changed_ids']),5000);self.assertTrue(result['changed_ids_truncated'])
    def test_selection_uses_one_component_instead_of_vertex_name_strings(self):
        self.preview();self.selected=[]
        class Selection:
            def __init__(selection):selection.items=[]
            def add(selection,value):selection.items.append(value)
        self.ns['om'].MSelectionList=Selection
        self.ns['om'].MGlobal=types.SimpleNamespace(kReplaceList=0,selectCommand=lambda value,mode:self.selected.append((value.items,mode)))
        summary=self.ns['select_preview_vertices'](self.data,progress=False)
        self.assertTrue(summary['preview_cache_reused']);self.assertEqual(self.selected,[([('t',[0,1])],0)])
    def test_empty_preview_selection_clears_old_selection(self):
        self.source['weights']=[0,1]*3;selected=[]
        class Selection:
            def __init__(selection):selection.items=[]
            def add(selection,value):selection.items.append(value)
        self.ns['om'].MSelectionList=Selection
        self.ns['om'].MGlobal=types.SimpleNamespace(kReplaceList=0,selectCommand=lambda value,mode:selected.append(value.items))
        self.ns['select_preview_vertices'](self.data,progress=False);self.assertEqual(selected,[[]])


class BulkGuardTests(unittest.TestCase):
    def setUp(self):
        tree=ast.parse(Path(__file__).with_name('copy_skinning_plugin.py').read_text())
        functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('writable','blocked_weight_channel')]
        self.locked=[];self.connections=[];self.root=types.SimpleNamespace(isLocked=False,isDestination=False)
        self.fn=types.SimpleNamespace(findPlug=mock.Mock(return_value=self.root),getConnections=mock.Mock(side_effect=lambda:self.connections))
        self.ctx={'skin':'skin','shape':'shape','fn':self.fn,'width':2,'weights':[.5,.5]*3,'influences':[]}
        self.cmds=types.SimpleNamespace(referenceQuery=lambda *a,**kw:False,listConnections=lambda *a,**kw:[],attributeQuery=lambda *a,**kw:False,
            getAttr=lambda *a,**kw:False,listAttr=mock.Mock(side_effect=lambda *a,**kw:self.locked))
        ns={'cmds':self.cmds,'om':types.SimpleNamespace(MFnDependencyNode=lambda *_:types.SimpleNamespace(isLocked=False)),'object_':lambda name:name}
        exec(compile(ast.Module(body=functions,type_ignores=[]),'<bulk write guards>','exec'),ns);self.validate=ns['writable']
    def check(self,vertices=(0,1),dq=False,callback=None):self.validate(self.ctx,list(vertices),[.5,.5]*len(vertices),dq,callback)
    def connected(self,name,destination=True):return types.SimpleNamespace(isDestination=destination,partialName=mock.Mock(return_value=name))
    def test_large_scope_uses_one_lock_query_and_one_connection_query(self):
        self.check(range(20000));self.cmds.listAttr.assert_called_once();self.fn.getConnections.assert_called_once();self.fn.findPlug.assert_called_once_with('weightList',False)
    def test_locked_scalar_weight_is_rejected(self):
        self.locked=['weightList[1].weights[7]']
        with self.assertRaisesRegex(ValueError,'locked'):self.check()
    def test_locked_vertex_parent_is_rejected(self):
        self.locked=['weightList[0]']
        with self.assertRaises(ValueError):self.check()
    def test_locked_weights_array_is_rejected(self):
        self.locked=['weightList[0].weights']
        with self.assertRaises(ValueError):self.check()
    def test_locked_other_vertex_does_not_block_selected_scope(self):
        self.locked=['weightList[2].weights[7]'];self.check()
    def test_full_node_prefix_from_lock_query_is_handled(self):
        self.locked=['skin.weightList[0].weights[0]']
        with self.assertRaises(ValueError):self.check()
    def test_driven_scalar_weight_is_rejected(self):
        self.connections=[self.connected('weightList[1].weights[500]')]
        with self.assertRaisesRegex(ValueError,'incoming driver'):self.check()
    def test_driven_vertex_parent_is_rejected(self):
        self.connections=[self.connected('weightList[0]')]
        with self.assertRaisesRegex(ValueError,'incoming driver'):self.check()
    def test_other_drivers_and_output_connections_are_allowed(self):
        self.connections=[self.connected('matrix[0]'),self.connected('weightList[2].weights[0]'),self.connected('weightList[0].weights[0]',False)]
        self.check()
    def test_dq_is_checked_only_when_copied(self):
        self.locked=['blendWeights[0]'];self.check()
        with self.assertRaises(ValueError):self.check(dq=True)
    def test_dq_incoming_driver_is_rejected(self):
        self.connections=[self.connected('blendWeights[0]')]
        with self.assertRaisesRegex(ValueError,'incoming driver'):self.check(dq=True)
    def test_locked_root_is_rejected_before_bulk_query(self):
        self.root.isLocked=True
        with self.assertRaises(ValueError):self.check()
        self.cmds.listAttr.assert_not_called()
    def test_locked_influence_change_is_rejected(self):
        self.ctx['influences']=[{'path':'|held'}];self.cmds.attributeQuery=lambda *a,**kw:True
        self.cmds.getAttr=lambda name:False if name.endswith('maintainMaxInfluences') else True
        with self.assertRaisesRegex(ValueError,'influence is locked'):self.validate(self.ctx,[0],[.25,.75])
    def test_unchanged_held_influence_is_allowed(self):
        self.ctx['influences']=[{'path':'|held'}];self.cmds.attributeQuery=lambda *a,**kw:True
        self.cmds.getAttr=lambda name:False if name.endswith('maintainMaxInfluences') else True
        self.check()
    def test_bulk_exception_scan_is_cancellable(self):
        self.locked=['visibility']*1000;calls=[]
        def cancel():
            calls.append(1)
            if len(calls)>5:raise RuntimeError('cancelled guard')
        with self.assertRaisesRegex(RuntimeError,'cancelled guard'):self.check(callback=cancel)


class InterruptTests(unittest.TestCase):
    setUp_plan=regression.PlanTests.setUp
    assert_closed=regression.ProgressTests.assert_closed
    def setUp(self):regression.ProgressTests.setUp(self)
    def test_native_interrupt_cleans_up_monitor_and_window(self):
        interrupt=types.SimpleNamespace(beginComputation=mock.Mock(),isInterruptRequested=lambda:True,endComputation=mock.Mock())
        self.ns['make_interrupt_monitor']=lambda:interrupt
        with self.assertRaisesRegex(RuntimeError,'cancelled'):self.ns['plan']({'source':'s','target':'t'},progress=True)
        interrupt.beginComputation.assert_called_once_with(False,True,False);interrupt.endComputation.assert_called_once();self.assert_closed()
    def test_native_monitor_cleanup_failure_still_closes_window(self):
        interrupt=types.SimpleNamespace(beginComputation=lambda *a:None,isInterruptRequested=lambda:False,endComputation=mock.Mock(side_effect=RuntimeError('monitor close failed')))
        self.ns['make_interrupt_monitor']=lambda:interrupt
        with self.assertRaisesRegex(RuntimeError,'monitor close failed'):self.ns['plan']({'source':'s','target':'t'},progress=True)
        self.assert_closed()
    def test_monitor_start_failure_still_closes_owned_window(self):
        interrupt=types.SimpleNamespace(beginComputation=mock.Mock(side_effect=RuntimeError('start failed')),endComputation=mock.Mock())
        self.ns['make_interrupt_monitor']=lambda:interrupt
        with self.assertRaisesRegex(RuntimeError,'start failed'):self.ns['plan']({'source':'s','target':'t'},progress=True)
        interrupt.endComputation.assert_called_once();self.assert_closed()
    def test_time_budget_stops_calculation_before_writes_and_cleans_up(self):
        with self.assertRaisesRegex(RuntimeError,'time limit'):
            self.ns['plan']({'source':'s','target':'t','max_seconds':.01},progress=True)
        self.assertEqual(self.guard,[]);self.assert_closed()
    def test_zero_time_budget_keeps_calculation_unlimited(self):
        monitor=self.ns['PlanProgress'](False,0)
        self.ns['time']=types.SimpleNamespace(monotonic=lambda:1e9);monitor.check()
    def test_time_budget_is_checked_without_a_progress_window(self):
        monitor=self.ns['PlanProgress'](False,1)
        self.ns['time']=types.SimpleNamespace(monotonic=lambda:1e9)
        with self.assertRaisesRegex(RuntimeError,'time limit'):monitor.check()
    def test_invalid_time_budget_does_not_reserve_a_window(self):
        with self.assertRaisesRegex(ValueError,'time limit'):
            self.ns['plan']({'source':'s','target':'t','max_seconds':-1},progress=True)
        self.assertEqual(self.events,[]);self.assertFalse(self.ns['_active_plan'])


class CopyProgressTests(unittest.TestCase):
    setUp_plan=regression.PlanTests.setUp
    assert_closed=regression.ProgressTests.assert_closed
    def setUp(self):
        regression.ProgressTests.setUp(self);self.writes=[];self.results=[]
        tree=ast.parse(Path(__file__).with_name('copy_skinning_plugin.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='CopyCommand')
        self.ns.update(json=json,components=list)
        self.ns['cmds'].undoInfo=lambda **kw:True
        self.ns['om'].MPxCommand=object;self.ns['om'].MIntArray=list;self.ns['om'].MArgDatabase=lambda syntax,args:args
        self.ns['_plan']=lambda data,monitor:{'ctx':{'width':2},'vertices':[0],'summary':{'changed_vertices':1}}
        exec(compile(ast.Module(body=[cls],type_ignores=[]),'<copy progress ownership>','exec'),self.ns)
        self.command=self.ns['CopyCommand']();self.command.syntax=lambda:None;self.command.setResult=self.results.append
        self.command.write=self.write
        self.args=types.SimpleNamespace(flagArgumentString=lambda *a:json.dumps({'source':'s','target':'t'}))
    def write(self,which):
        self.assertTrue(self.open);self.assertTrue(self.status.startswith('Writing and verifying'));self.writes.append(which)
    def test_owned_window_remains_open_through_native_write(self):
        self.command.doIt(self.args);self.assertEqual(self.writes,['after']);self.assert_closed();self.assertEqual(len(self.results),1)
    def test_failed_write_rolls_back_before_progress_cleanup(self):
        def fail(which):
            self.write(which)
            if which=='after':raise RuntimeError('native write failed')
        self.command.write=fail
        with self.assertRaisesRegex(RuntimeError,'native write failed'):self.command.doIt(self.args)
        self.assertEqual(self.writes,['after','before']);self.assert_closed()
    def test_cancel_at_write_boundary_writes_nothing(self):
        self.cancel_at='Writing and verifying'
        with self.assertRaisesRegex(RuntimeError,'cancelled'):self.command.doIt(self.args)
        self.assertEqual(self.writes,[]);self.assert_closed()
    def test_escape_after_successful_atomic_write_does_not_report_failure(self):
        def write(which):self.write(which);self.cancel_at='Writing and verifying'
        self.command.write=write;self.command.doIt(self.args)
        self.assertEqual(self.writes,['after']);self.assertEqual(len(self.results),1);self.assert_closed()


if __name__=='__main__':unittest.main(verbosity=2)
