"""Exact-command paint receipts; keep native validation and existing Undo objects."""
import hashlib
import json
import uuid

KEY='_rtk_paint_receipt'
REVISION=37
SUPPORTED_ACTIONS=frozenset(('paint','relax_stroke'))


def install(owner):
    cls=owner.get('LayerCommand');remember=owner.get('remember')
    if cls is None or not callable(remember) or owner.get('VERSION')!='0.4.1':return False
    previous=owner.get('_layer_skin_paint_runtime')
    if previous and (previous.get('revision')==REVISION or previous.get('stack')):return True
    original=getattr(cls.doIt,'_layer_skin_receipt_original',cls.doIt)
    original_remember=getattr(remember,'_layer_skin_receipt_original',remember)
    runtime=dict(requests={},stack=[],revision=REVISION)

    def capture(raw,state,weights=None):
        result=original_remember(raw,state,weights)
        if weights is not None and runtime['stack']:runtime['stack'][-1]['saved']=(raw,state,weights)
        return result

    def execute(command,args):
        if not runtime['requests'] and not runtime['stack']:return original(command,args)
        arguments=owner['om'].MArgDatabase(command.syntax(),args)
        action=arguments.flagArgumentString('-action',0) if arguments.isFlagSet('-action') else 'ui'
        data=json.loads(arguments.flagArgumentString('-data',0)) if action in SUPPORTED_ACTIONS and arguments.isFlagSet('-data') else {}
        request=runtime['requests'].get(data.get(KEY)) if action in SUPPORTED_ACTIONS else None
        if request is not None and request['action']!=action:request=None
        frame={};runtime['stack'].append(frame)
        try:result=original(command,args)
        finally:runtime['stack'].pop()
        if request is None or data!=request['data'] or not command.isUndoable() or 'saved' not in frame:return result
        raw,state,weights=frame['saved'];ctx=command.ctx;scope=request['scope']
        try:
            identity=owner['om'].MFnDependencyNode(ctx['dag'].node()).uuid().asString()
            valid=(ctx['shape'],ctx['skin'],identity,ctx['count'],tuple(ctx['ids']),ctx['topology'])==(
                scope['shape'],scope['skin'],scope['uuid'],scope['count'],tuple(scope['ids']),scope['topology'])
            valid=valid and state['influences']==list(ctx['ids']) and len(weights)==ctx['count']*len(ctx['ids'])
            # A nested callback can edit metadata after remember(). A cheap
            # exact read verifies this command's saved value, never cache order.
            valid=valid and owner['cmds'].getAttr(scope['meta']+'.'+owner['STATE'])==raw
            if valid:request['receipt']=dict(scope=dict(scope),state=state,weights=weights,
                state_hash=hashlib.sha256(raw.encode()).hexdigest(),raw_metadata=raw)
        except Exception:
            pass  # The command already succeeded; use the normal verified readback.
        return result

    execute._layer_skin_receipt_original=original
    capture._layer_skin_receipt_original=original_remember
    capture._layer_skin_performance_runtime=getattr(original_remember,'_layer_skin_performance_runtime',None)
    cls.doIt=execute;owner['remember']=capture
    owner['_layer_skin_paint_runtime']=runtime
    return True


def commit(owner,data,scope,action='paint'):
    if action not in SUPPORTED_ACTIONS:raise ValueError('Unsupported receipt action: '+str(action))
    runtime=owner.get('_layer_skin_paint_runtime')
    if runtime is None:
        owner['cmds'].rtkLayerSkin(action=action,data=json.dumps(data));return None
    token=uuid.uuid4().hex;payload=dict(data,**{KEY:token})
    request=dict(action=action,data=payload,scope=dict(scope),receipt=None);runtime['requests'][token]=request
    try:
        owner['cmds'].rtkLayerSkin(action=action,data=json.dumps(payload))
        return request['receipt']
    finally:runtime['requests'].pop(token,None)
