"""Bounded stroke guards; full live weight validation and native Undo stay on.

The metadata guard caches digests of exact scene bytes plus influence order,
never id(state), a last-cache entry, or a partial skin read. NumPy is optional.
"""
from collections import OrderedDict
import array
import hashlib
import importlib.util
import os
import sys

REVISION = 32
HASH_LIMIT = 128
VECTOR_THRESHOLD = 16384
COMPARE_CHUNK = 262144
SCOPED_PLUG_LIMIT = 32768
SCATTER_MIN_ROWS = 16
SCATTER_MIN_VALUES = 128
_NUMPY = None
_NUMPY_TRIED = False
_NUMPY_ERROR = ''
_NUMPY_ROOT = None


def dependency_helpers():
    key='_rtk_layer_skin_dependencies_36'
    if key not in sys.modules:
        spec=importlib.util.spec_from_file_location(key,os.path.join(os.path.dirname(__file__),'layer_skin_dependencies.py'))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);sys.modules[key]=module
    return sys.modules[key]


def configure_numpy_root(root):
    global _NUMPY_ROOT, _NUMPY_TRIED
    if root!=_NUMPY_ROOT and _NUMPY is None:_NUMPY_TRIED=False
    _NUMPY_ROOT=root


def state_cost(state):
    """Estimate state plus one composed buffer within the existing 64 MiB cap.

    The old 80-bytes/value allowance remains for Python lists. Packed float64
    data uses its allocation size plus a second float64 buffer, not that list
    estimate. Conservatively retain the old dense allowance for layer rows.
    """
    values = state['vertex_count'] * len(state['influences'])
    base = state['base']
    cost = (sys.getsizeof(base) + values*8 + 4096 if isinstance(base, array.array)
            and base.typecode == 'd' else values*80)
    for layer in state['layers']:
        cost += (len(layer['samples']) + len(layer.get('generated', {}))) * (500+40*len(state['influences']))
        cost += len(layer['mask'])*128
    cost += len((state.get('reference') or {}).get('points', []))*200
    return cost


def numpy_backend(refresh=False):
    global _NUMPY, _NUMPY_TRIED, _NUMPY_ERROR
    if refresh and _NUMPY is None:
        importlib.invalidate_caches();_NUMPY_TRIED=False
    if not _NUMPY_TRIED:
        _NUMPY_TRIED = True
        try:
            path=dependency_helpers().active_path(_NUMPY_ROOT) if _NUMPY_ROOT else None
            if path and path not in sys.path:sys.path.append(path)
            import numpy
            _NUMPY = numpy;_NUMPY_ERROR=''
        except Exception as exc:
            # An optional binary/DLL import failure must retain the ordinary
            # comparison. Never remove or reload already imported NumPy modules.
            _NUMPY_ERROR=str(exc)
    return _NUMPY


def _block(values, start, end, np):
    try:
        view = memoryview(values)
    except TypeError:
        return np.asarray(values[start:end], dtype=np.float64)
    if view.ndim == 1 and view.c_contiguous and view.format in ('d', 'f'):
        return np.frombuffer(view[start:end], dtype=np.float64 if view.format == 'd' else np.float32)
    return np.asarray(values[start:end], dtype=np.float64)


def same(a, b, tolerance=1e-7):
    """Same absolute tolerance as the native guard; bounded C-array fast path."""
    if len(a) != len(b):
        return False
    if a is b:
        return True
    # Lists and packed arrays implement exact equality in C. Do not ask an
    # ndarray for a truth value; NumPy is an optional implementation detail.
    if isinstance(a, (list, tuple)) or hasattr(a, 'typecode'):
        equal = a == b
        if isinstance(equal, bool) and equal:
            return True
    np = numpy_backend() if len(a) >= VECTOR_THRESHOLD else None
    if np is not None:
        with np.errstate(invalid='ignore', over='ignore'):
            for start in range(0, len(a), COMPARE_CHUNK):
                end = min(len(a), start + COMPARE_CHUNK)
                # Float32 inputs must be promoted before subtraction, keeping
                # the Python float (double) tolerance calculation unchanged.
                left = _block(a, start, end, np).astype(np.float64, copy=False)
                right = _block(b, start, end, np).astype(np.float64, copy=False)
                if not bool(np.all(np.abs(left - right) <= tolerance)):
                    return False
        return True
    return all(abs(x-y) <= tolerance for x, y in zip(a, b))


def changed_vertices(before,after,count,width,candidates=None,tolerance=1e-12):
    """Bounded contiguous/scattered row checks, retaining candidate order.

    Scattered C-buffer rows are gathered only in bounded batches. Small scopes,
    Python lists and missing NumPy keep their row comparison. No full-mesh
    difference/index array is allocated; float32 arithmetic promotes to double.
    """
    if before is after:return []
    scope=range(count) if candidates is None else candidates
    if isinstance(scope,(list,tuple,range)) and len(scope)<SCATTER_MIN_ROWS and len(scope)*width<VECTOR_THRESHOLD:
        return [v for v in scope if not same(before[v*width:(v+1)*width],after[v*width:(v+1)*width],tolerance)]
    np=numpy_backend() if len(before)>=VECTOR_THRESHOLD else None
    if np is None:
        return [v for v in scope if not same(before[v*width:(v+1)*width],after[v*width:(v+1)*width],tolerance)]
    result=[]
    def run(first,end):
        if np is None or (end-first)*width<VECTOR_THRESHOLD or width>COMPARE_CHUNK:
            result.extend(v for v in range(first,end)
                if not same(before[v*width:(v+1)*width],after[v*width:(v+1)*width],tolerance))
            return
        rows=max(1,COMPARE_CHUNK//width)
        with np.errstate(invalid='ignore',over='ignore'):
            for start in range(first,end,rows):
                stop=min(end,start+rows)
                left=_block(before,start*width,stop*width,np).astype(np.float64,copy=False)
                right=_block(after,start*width,stop*width,np).astype(np.float64,copy=False)
                equal=np.all((np.abs(left-right)<=tolerance).reshape(stop-start,width),axis=1)
                result.extend((np.flatnonzero(~equal)+start).tolist())
    if isinstance(scope,range) and scope.step==1:
        run(scope.start,scope.stop)
        return result
    scattered=[];batch_rows=max(1,COMPARE_CHUNK//width)
    views=None;views_tried=False
    def flush():
        nonlocal views,views_tried
        if not scattered:return
        use_vector=len(scattered)>=SCATTER_MIN_ROWS and len(scattered)*width>=SCATTER_MIN_VALUES and width<=COMPARE_CHUNK
        if use_vector and not views_tried:
            views_tried=True
            try:
                left=memoryview(before);right=memoryview(after)
                if all(v.ndim==1 and v.c_contiguous and v.format in ('d','f') for v in (left,right)):
                    views=tuple(np.frombuffer(v,dtype=np.float64 if v.format=='d' else np.float32).reshape(count,width)
                                for v in (left,right))
            except (TypeError,ValueError):views=None
        if use_vector and views is not None:
            with np.errstate(invalid='ignore',over='ignore'):
                indices=np.asarray(scattered,dtype=np.int64)
                left=views[0][indices].astype(np.float64,copy=False)
                right=views[1][indices].astype(np.float64,copy=False)
                equal=np.all(np.abs(left-right)<=tolerance,axis=1)
                result.extend(scattered[i] for i in np.flatnonzero(~equal).tolist())
        else:
            result.extend(v for v in scattered if not same(before[v*width:(v+1)*width],after[v*width:(v+1)*width],tolerance))
        scattered.clear()
    def finish_run(first,end):
        if (end-first)*width>=VECTOR_THRESHOLD:
            flush();run(first,end);return
        while first<end:
            stop=min(end,first+batch_rows-len(scattered))
            scattered.extend(range(first,stop));first=stop
            if len(scattered)==batch_rows:flush()
    first=previous=None
    for v in scope:
        if previous is not None and v!=previous+1:finish_run(first,previous+1);first=None
        if first is None:first=v
        previous=v
    if first is not None:finish_run(first,previous+1)
    flush()
    return result


def _put(cache, key, value):
    cache.pop(key, None)
    while len(cache) >= HASH_LIMIT:
        cache.popitem(last=False)
    cache[key] = value


def _key(owner, raw, influences):
    encoder = owner['core'].encode
    runtime = owner.get('_layer_skin_performance_runtime')
    if runtime is not None and runtime.get('encoder') is not encoder:
        # Old functions retain their module globals. Drop them on reload so a
        # small digest cache cannot pin old core modules and packed payloads.
        runtime['hashes'].clear()
        runtime['encoder'] = encoder
    return (hashlib.sha256(raw.encode()).hexdigest(), tuple(influences), encoder)


def state_hash(owner, ctx, state):
    """Canonical guard, including legacy compression and UUID remapping.

    Only metadata() may associate an immutable decoded state with scene bytes.
    Arbitrary caller-created or edited states always take the normal encoder.
    Cached keys retain no state, buffer, or full metadata string.
    """
    runtime = owner.get('_layer_skin_performance_runtime')
    raw = ctx.get('raw_metadata')
    key = (_key(owner, raw, state['influences']) if runtime is not None
           and isinstance(raw, str) and ctx.get('_layer_skin_metadata_state') is state else None)
    cache = runtime['hashes'] if runtime is not None else None
    if key is not None and key in cache:
        value = cache[key]
        cache.move_to_end(key)
        return value
    value = hashlib.sha256(owner['core'].encode(state).encode()).hexdigest()
    if key is not None:
        _put(cache, key, value)
    return value


def _weight_guards(owner, ctx, vertices):
    """Inspect every allocated weight plug in changed rows, including parents.

    A parent's unlocked state does not imply that its children are unlocked.
    Floods use the old bulk scan; small strokes never enumerate every row.
    """
    cmds = owner['cmds']
    weights = ctx['fn'].findPlug('weightList', False)
    if weights.isLocked or weights.isDestination:
        raise ValueError('Skin weightList is locked or driven.')
    if len(vertices)*len(ctx['ids']) <= SCOPED_PLUG_LIMIT and callable(getattr(weights, 'elementByLogicalIndex', None)):
        def check(plug):
            if plug.isLocked:
                raise ValueError('Skin weight channel is locked: ' + plug.name())
            if plug.isDestination:
                raise ValueError('Skin weight channel has another driver: ' + plug.name())
        for vertex in vertices:
            row = weights.elementByLogicalIndex(vertex)
            check(row)
            # skinCluster.weightList has one child: the weights multi.
            values = row.child(0)
            check(values)
            # numElements alone can omit unevaluated connected elements.
            # Evaluate this one row so its driven leaves cannot escape checks.
            evaluate = getattr(values, 'evaluateNumElements', None)
            count = evaluate() if callable(evaluate) else values.numElements()
            for index in range(count):
                check(values.elementByPhysicalIndex(index))
        return
    changed = set(vertices)
    def affected(name):
        name = name.split('.', 1)[1] if name.startswith(ctx['skin']+'.') else name
        if name == 'weightList':
            return True
        if not name.startswith('weightList['):
            return False
        try:
            return int(name.split('[', 1)[1].split(']', 1)[0]) in changed
        except ValueError:
            raise ValueError('Cannot validate weight channel: ' + name)
    for name in cmds.listAttr(ctx['skin']+'.weightList', locked=True, multi=True) or []:
        if affected(name):
            raise ValueError('Skin weight channel is locked: ' + name)
    for plug in ctx['fn'].getConnections():
        if plug.isDestination and affected(plug.partialName(includeNonMandatoryIndices=True, useLongNames=True)):
            raise ValueError('Skin weight channel has another driver: ' + plug.name())


def preflight(owner, ctx, meta, before, after, candidates=None):
    cmds = owner['cmds']; om = owner['om']
    for node in (ctx['shape'], ctx['skin'], meta):
        if node and (cmds.referenceQuery(node, isNodeReferenced=True) or om.MFnDependencyNode(owner['obj'](node)).isLocked):
            raise ValueError('Referenced or locked setup cannot be edited: ' + node)
    if meta:
        plug = om.MFnDependencyNode(owner['obj'](meta)).findPlug(owner['STATE'], False)
        if plug.isLocked or plug.isDestination:
            raise ValueError('Layer data is locked or driven.')
    if before is after:
        return []
    width = len(ctx['ids'])
    vertices = changed_vertices(before,after,ctx['count'],width,candidates)
    if not vertices:
        return vertices
    if cmds.getAttr(ctx['skin']+'.maintainMaxInfluences'):
        raise ValueError('Turn OFF Maintain Max Influences on the skinCluster before testing layer edits.')
    for j, path in enumerate(ctx['influences']):
        name = path.fullPathName()
        if cmds.attributeQuery('lockInfluenceWeights', node=name, exists=True) and cmds.getAttr(name+'.lockInfluenceWeights'):
            if any(abs(before[v*width+j]-after[v*width+j]) > 1e-12 for v in vertices):
                raise ValueError('A changed influence is locked: ' + name)
    _weight_guards(owner, ctx, vertices)
    return vertices


def install(owner):
    """Refresh normal helpers, retaining MPxCommand registration and old Undo."""
    if owner.get('VERSION') != '0.4.1' or not all(callable(owner.get(name)) for name in ('metadata', 'remember', 'prepare_edit')):
        return False
    internal=getattr(owner.get('cmds'),'internalVar',None)
    if callable(internal):
        try:configure_numpy_root(dependency_helpers().dependency_root(internal(userAppDir=True)))
        except (RuntimeError,ValueError,TypeError):pass
    runtime = owner.get('_layer_skin_performance_runtime')
    if runtime is None or runtime.get('revision') != REVISION:
        runtime = dict(revision=REVISION, hashes=OrderedDict())
        owner['_layer_skin_performance_runtime'] = runtime
    if runtime.get('encoder') is not owner['core'].encode:
        runtime['hashes'].clear()
        runtime['encoder'] = owner['core'].encode
    owner['same'] = same
    owner['state_cost'] = state_cost
    owner['state_hash'] = lambda ctx, state: state_hash(owner, ctx, state)
    current_preflight = owner.get('preflight')
    # A custom API's preflight remains its own; native adapters have this name
    # and marker. Never replace a caller's recording or application validator.
    if (getattr(current_preflight, '__name__', '') == 'preflight'
            and getattr(current_preflight, '__code__', None)
            and current_preflight.__code__.co_filename.replace('\\', '/').endswith('/layer_skin_test.py')) or getattr(current_preflight, '_layer_skin_performance_preflight', False):
        def check(ctx, meta, before, after, candidates=None):
            return preflight(owner, ctx, meta, before, after, candidates)
        check._layer_skin_performance_preflight = True
        owner['preflight'] = check
    previous = owner['metadata']
    if getattr(previous, '_layer_skin_performance_runtime', None) is not runtime:
        def metadata(ctx):
            meta, state = previous(ctx)
            ctx['_layer_skin_metadata_state'] = state
            return meta, state
        metadata._layer_skin_performance_runtime = runtime
        owner['metadata'] = metadata
    remember_original = owner['remember']
    if getattr(remember_original, '_layer_skin_performance_runtime', None) is not runtime:
        def remember(raw, state, weights=None):
            result = remember_original(raw, state, weights)
            # Non-None weights are published only after the native command has
            # encoded this state and verified its write. Legacy scene reads
            # call remember(raw,state) and must canonicalize once instead.
            if weights is not None:
                key = _key(owner, raw, state['influences'])
                _put(runtime['hashes'], key, key[0])
            return result
        remember._layer_skin_performance_runtime = runtime
        owner['remember'] = remember
    planner = owner['prepare_edit']
    if getattr(planner, '_layer_skin_performance_runtime', None) is not runtime:
        def prepare(ctx, meta, state, action, data):
            if state is not None and data.get('expected'):
                if data['expected'] != state_hash(owner, ctx, state):
                    raise ValueError('Layer data changed during the stroke. The unfinished stroke was discarded.')
                data = dict(data); data.pop('expected')
            return planner(ctx, meta, state, action, data)
        prepare._layer_skin_performance_runtime = runtime
        prepare._layer_skin_relax_original = getattr(planner, '_layer_skin_relax_original', planner)
        owner['prepare_edit'] = prepare
    previous_clear = owner.get('clear_cache')
    if callable(previous_clear) and getattr(previous_clear, '_layer_skin_performance_runtime', None) is not runtime:
        def clear():
            result = previous_clear()
            runtime['hashes'].clear()
            cache = getattr(owner['core'], '_PACKED_BASE_ENCODINGS', None)
            if cache is not None:cache.clear()
            return result
        clear._layer_skin_performance_runtime = runtime
        owner['clear_cache'] = clear
    return True
