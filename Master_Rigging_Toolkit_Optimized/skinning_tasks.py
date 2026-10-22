"""Bounded session task records. No Maya/Qt objects, threads or scene callbacks."""
import time

VERSION='0.4.3'


class TaskCancelled(RuntimeError):pass


class TaskService:
    def __init__(self,clock=None,limit=20):
        self.clock=clock or time.monotonic;self.limit=limit;self.active=None;self.history=[];self.serial=0
    def begin(self,name):
        if self.active:
            raise RuntimeError('Skinning task already running: {} · {}. Open Tasks to request cancellation.'.format(self.active['name'],self.active['stage']))
        self.serial+=1;now=self.clock()
        self.active=dict(id=str(self.serial),name=str(name),state='Running',stage='Starting',progress=0,
                         started=now,checkpoint=now,elapsed=0.,cancel=False,force=False,atomic=False,native_progress=False,message='')
        return self.active['id']
    def record(self,identity):
        if not self.active or self.active['id']!=identity:raise ValueError('This task is no longer active. Refresh the task list.')
        return self.active
    def checkpoint(self,identity,stage,value):
        item=self.record(identity);item.update(stage=str(stage),progress=int(value),checkpoint=self.clock())
        if item['cancel'] and not item['atomic']:
            raise TaskCancelled('Copy Skinning cancelled before any weight writes. Task: '+item['name'])
    def mark_progress(self,identity,owned):self.record(identity)['native_progress']=bool(owned)
    def begin_write(self,identity):
        item=self.record(identity)
        if item['cancel']:raise TaskCancelled('Copy Skinning cancelled before any weight writes. Task: '+item['name'])
        item.update(atomic=True,state='Writing / verifying',stage='Writing / verifying · rollback on failure')
    def request_stop(self,identity,force=False):
        item=self.record(identity)
        if item['atomic']:return 'Weights are being written or verified. Wait for this atomic step and any rollback to finish.'
        item.update(cancel=True,force=bool(force or item['force']),state='Force stop requested' if force else 'Cancel requested')
        return 'Stop requested. The task will exit at its next checkpoint; a native Maya call must return first.'
    def finish(self,identity,state='Completed',message=''):
        item=self.record(identity);now=self.clock();item.update(state=state,message=str(message),elapsed=max(0.,now-item['started']))
        self.history.insert(0,dict(item));self.history=self.history[:self.limit];self.active=None
    def snapshot(self):
        now=self.clock();active=dict(self.active) if self.active else None
        if active:active.update(elapsed=max(0.,now-active['started']),since_checkpoint=max(0.,now-active['checkpoint']))
        return {'active':active,'history':[dict(item) for item in self.history]}
    def clear_finished(self):self.history=[]


SERVICE=TaskService()
