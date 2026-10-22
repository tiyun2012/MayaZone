"""Task registry, cancellation boundaries, progress ownership and recovery."""
import ast
import json
from pathlib import Path
import sys
import types
import unittest
from unittest import mock
import skinning_tasks as tasks
import test_copy_skinning as regression
import test_copy_skinning_actions as actions


class ServiceTests(unittest.TestCase):
    def setUp(self):self.now=1.;self.service=tasks.TaskService(lambda:self.now,limit=3);self.identity=self.service.begin('Preview transfer')
    def test_snapshot_reports_elapsed_and_checkpoint_age(self):
        self.now=4.;self.service.checkpoint(self.identity,'Sampling',50);self.now=6.
        item=self.service.snapshot()['active'];self.assertEqual((item['elapsed'],item['since_checkpoint'],item['stage']),(5.,2.,'Sampling'))
    def test_snapshot_cannot_mutate_active_state(self):
        self.service.snapshot()['active']['cancel']=True;self.assertFalse(self.service.active['cancel'])
    def test_second_operation_rejected_with_current_name(self):
        with self.assertRaisesRegex(RuntimeError,'already running: Preview transfer'):self.service.begin('Copy')
    def test_cancel_is_observed_at_next_checkpoint(self):
        self.service.request_stop(self.identity)
        with self.assertRaises(tasks.TaskCancelled):self.service.checkpoint(self.identity,'Read',0)
    def test_force_request_is_explicitly_recorded(self):
        self.service.request_stop(self.identity,force=True);self.assertTrue(self.service.active['force'])
        self.assertEqual(self.service.active['state'],'Force stop requested')
    def test_cancel_does_not_release_active_task_early(self):
        self.service.request_stop(self.identity,True)
        with self.assertRaises(RuntimeError):self.service.begin('Another copy')
        self.assertIsNotNone(self.service.active)
    def test_atomic_write_rejects_stop_request(self):
        self.service.begin_write(self.identity);message=self.service.request_stop(self.identity,True)
        self.assertIn('atomic',message);self.assertFalse(self.service.active['cancel'])
    def test_pending_cancel_cannot_enter_atomic_write(self):
        self.service.request_stop(self.identity)
        with self.assertRaises(tasks.TaskCancelled):self.service.begin_write(self.identity)
        self.assertFalse(self.service.active['atomic'])
    def test_stale_task_id_cannot_stop_current_task(self):
        with self.assertRaisesRegex(ValueError,'no longer active'):self.service.request_stop('old',True)
        self.assertFalse(self.service.active['cancel'])
    def test_finished_history_records_outcome_and_elapsed(self):
        self.now=9.;self.service.finish(self.identity,'Failed','read error');item=self.service.snapshot()['history'][0]
        self.assertEqual((item['state'],item['message'],item['elapsed']),('Failed','read error',8.));self.assertIsNone(self.service.active)
    def test_history_is_bounded_and_copies_are_immutable(self):
        self.service.finish(self.identity)
        for i in range(7):identity=self.service.begin(str(i));self.service.finish(identity)
        values=self.service.snapshot()['history'];self.assertEqual(len(values),3);values[0]['name']='mutated'
        self.assertEqual(self.service.history[0]['name'],'6')
    def test_clear_history_preserves_active_task(self):
        self.service.clear_finished();self.assertEqual(self.service.active['id'],self.identity)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.service=tasks.TaskService();self.native={'title':'Other tool','status':'Idle?','progress':20};self.ends=[]
        self.ns={'task_service':lambda:self.service,'native_progress_info':lambda:self.native,
                 'cmds':types.SimpleNamespace(progressWindow=lambda **kw:self.ends.append(kw))}
        tree=ast.parse(Path(__file__).with_name('copy_skinning_plugin.py').read_text())
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('task_report','stop_task')]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<task recovery>','exec'),self.ns)
    def stop(self,identity='maya-progress',force=True,expected=None):
        return self.ns['stop_task'](identity,force,dict(self.native) if expected is None and self.native else expected)
    def test_list_is_read_only_and_includes_unknown_native_status(self):
        report=self.ns['task_report']();self.assertEqual(report['maya_progress'],self.native);self.assertEqual(self.ends,[])
    def test_unknown_progress_requires_force(self):
        with self.assertRaisesRegex(ValueError,'owner.*unknown'):self.stop(force=False)
        self.assertEqual(self.ends,[])
    def test_force_reset_closes_only_the_selected_progress_ui(self):
        message=self.stop();self.assertEqual(self.ends,[{'endProgress':True}]);self.assertIn('does not terminate',message)
    def test_progress_changed_since_selection_is_not_closed(self):
        old=dict(self.native);self.native['title']='New owner'
        with self.assertRaisesRegex(ValueError,'progress changed'):self.stop(expected=old)
        self.assertEqual(self.ends,[])
    def test_unknown_reset_is_blocked_while_any_tracked_task_runs(self):
        self.service.begin('Copy')
        with self.assertRaisesRegex(ValueError,'tracked task is active'):self.stop()
        self.assertEqual(self.ends,[])
    def test_disappeared_progress_does_not_trigger_close(self):
        self.native=None;self.assertIn('No Maya progress',self.stop());self.assertEqual(self.ends,[])
    def test_known_task_force_stop_sets_flag_without_closing_native_progress(self):
        identity=self.service.begin('Preview');self.stop(identity);self.assertTrue(self.service.active['cancel']);self.assertEqual(self.ends,[])
    def test_native_probe_failures_are_reported_without_window_creation(self):
        tree=ast.parse(Path(__file__).with_name('copy_skinning_plugin.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='native_progress_info')
        call=mock.Mock(side_effect=RuntimeError('No progress'));ns={'cmds':types.SimpleNamespace(progressWindow=call)}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'<native progress probe>','exec'),ns)
        self.assertIsNone(ns['native_progress_info']());call.assert_called_once_with(query=True,title=True)


class RunningTests(unittest.TestCase):
    def setUp(self):
        self.fixture=regression.ProgressTests();self.fixture.setUp();self.ns=self.fixture.ns;self.service=self.fixture.task_service
    def test_running_task_exposes_current_stage(self):
        original=self.ns['context'];records=[]
        def context(name,**kw):records.append(self.service.snapshot()['active']);return original(name,**kw)
        self.ns['context']=context;self.fixture.plan()
        self.assertEqual(records[0]['name'],'Build transfer plan');self.assertEqual(records[0]['stage'],'Reading source mesh and weights')
        self.assertIsNone(self.service.active);self.assertEqual(self.service.history[0]['state'],'Completed')
    def test_force_stop_during_source_read_cancels_before_sampling(self):
        original=self.ns['context']
        def context(name,**kw):self.service.request_stop(self.service.active['id'],True);return original(name,**kw)
        self.ns['context']=context
        with self.assertRaises(tasks.TaskCancelled):self.fixture.plan()
        self.fixture.assert_closed();self.assertEqual(self.fixture.samples,[]);self.assertEqual(self.fixture.guard,[])
        self.assertEqual(self.service.history[0]['state'],'Cancelled')
    def test_failed_task_keeps_stage_and_error_for_review(self):
        self.ns['context']=mock.Mock(side_effect=ValueError('bad source'))
        with self.assertRaises(ValueError):self.fixture.plan()
        item=self.service.history[0];self.assertEqual(item['state'],'Failed');self.assertIn('source',item['stage']);self.assertEqual(item['message'],'bad source')
    def test_command_write_cannot_be_force_reset_mid_write(self):
        case=actions.CopyProgressTests();case.setUp();original=case.command.write
        def write(which):
            active=case.task_service.active;self.assertTrue(active['atomic'])
            self.assertIn('atomic',case.task_service.request_stop(active['id'],True));original(which)
        case.command.write=write;case.command.doIt(case.args)
        self.assertEqual(case.writes,['after']);self.assertEqual(case.task_service.history[0]['state'],'Completed');case.assert_closed()
    def test_rollback_finishes_before_failed_task_is_released(self):
        case=actions.CopyProgressTests();case.setUp();original=case.command.write
        def write(which):
            self.assertTrue(case.task_service.active['atomic']);original(which)
            if which=='after':raise RuntimeError('write failure')
        case.command.write=write
        with self.assertRaises(RuntimeError):case.command.doIt(case.args)
        self.assertEqual(case.writes,['after','before']);self.assertIsNone(case.task_service.active);self.assertEqual(case.task_service.history[0]['state'],'Failed')
    def test_editor_write_uses_same_tracked_atomic_scope(self):
        case=actions.CopyProgressTests();case.setUp()
        case.ns['edit_plan']=lambda *args,**kwargs:{'ctx':{'width':2},'vertices':[0],'summary':{'action':'set'}}
        args=types.SimpleNamespace(flagArgumentString=lambda *a:json.dumps({'operation':'edit','action':'set'}))
        original=case.command.write
        def write(which):self.assertTrue(case.task_service.active['atomic']);original(which)
        case.command.write=write;case.command.doIt(args)
        self.assertEqual(case.task_service.history[0]['name'],'Weight edit · set');self.assertEqual(case.writes,['after']);case.assert_closed()
    def test_foreign_progress_error_does_not_close_it(self):
        self.fixture.can_open=False
        with self.assertRaisesRegex(RuntimeError,'could not create'):self.fixture.plan()
        self.assertFalse(any(e.get('endProgress') for e in self.fixture.events));self.assertIsNone(self.service.active)


class SharedTests(unittest.TestCase):
    def test_ui_helper_and_registered_command_share_one_task_registry(self):
        fixture=regression.PluginLoaderTests();fixture.setUp()
        with mock.patch.dict(sys.modules):
            sys.modules.pop('_rtk_skinning_tasks_043',None)
            first=fixture.execute();second=fixture.execute();a=first['task_service']();b=second['task_service']();self.assertIs(a,b)
            identity=a.begin('Copy skinning');b.request_stop(identity,True);self.assertTrue(a.active['cancel']);a.finish(identity,'Cancelled')


if __name__=='__main__':unittest.main(verbosity=2)
