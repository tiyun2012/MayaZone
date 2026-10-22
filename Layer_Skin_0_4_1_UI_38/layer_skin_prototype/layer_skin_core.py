"""Layer Skin: pure Python composition; no Maya or NumPy dependency."""
import base64
from collections import OrderedDict
import copy
import hashlib
import json
import math
import uuid
import zlib
import array
import importlib.util
import os
import sys
import weakref

# Both the outer payload and packed base buffers favor interactive saves.
# The existing zlib-v1 readers also accept prior compression levels.
COMPRESSION_LEVEL = 1
PACKED_BASE_CACHE_BYTES = 16 * 1024 * 1024
_PACKED_BASE_ENCODINGS = OrderedDict()
LOCAL_ROW_CACHE_LIMIT = 256
PACKED_ROW_CACHE_BYTES = 1024 * 1024

_INFLUENCE_RULES=None


def influence_rules():
    global _INFLUENCE_RULES
    if _INFLUENCE_RULES is None:
        import importlib.util
        import os
        path=os.path.join(os.path.dirname(__file__),'layer_skin_influence.py')
        spec=importlib.util.spec_from_file_location('_rtk_layer_skin_influence_18',path)
        _INFLUENCE_RULES=importlib.util.module_from_spec(spec);spec.loader.exec_module(_INFLUENCE_RULES)
    return _INFLUENCE_RULES

def storage():
    key='_rtk_layer_skin_storage_20'
    if key not in sys.modules:
        spec=importlib.util.spec_from_file_location(key,os.path.join(os.path.dirname(__file__),'layer_skin_storage.py'))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);sys.modules[key]=module
    return sys.modules[key]


SCHEMA = 2
MAX_VALUES = storage().MAX_VALUES  # One GiB per packed float64 buffer.
MAX_LAYERS = 32

_VERTEX_KEYS = OrderedDict()
_VALID_BASE = OrderedDict()
_VALID_REF = OrderedDict()
_VALID_GEN = OrderedDict()


def _remember_valid(cache, key, obj):
    stored=obj
    if isinstance(obj,array.array) and len(obj)*obj.itemsize>8*1024*1024:
        # Base snapshots are immutable inside core.edit. A weak identity check
        # reuses their validation without pinning production-size buffers.
        def forget(reference):
            if cache.get(key) is reference:cache.pop(key,None)
        try:stored=weakref.ref(obj,forget)
        except TypeError:return
    elif isinstance(obj,dict) and len(obj)>8192:
        return
    cache.pop(key, None)
    while len(cache) >= 8:
        cache.popitem(last=False)
    cache[key] = stored


def _cached_valid(cache,key,obj):
    stored=cache.get(key)
    return stored is obj or (isinstance(stored,weakref.ReferenceType) and stored() is obj)


def _vertex_keys(n):
    keys = _VERTEX_KEYS.get(n)
    if keys is None:
        while len(_VERTEX_KEYS) >= 8:
            _VERTEX_KEYS.popitem(last=False)
        keys = frozenset(str(i) for i in range(n))
        _VERTEX_KEYS[n] = keys
    return keys


def unit(value):
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise ValueError("Value must be finite and between 0 and 1.")
    return value


def normalized(row):
    row = [float(v) for v in row]
    if not row or min(row) < 0.0:
        raise ValueError("Invalid influence weights.")
    total = sum(row)
    if not math.isfinite(total):
        raise ValueError("Invalid influence weights.")
    if total <= 1e-12:
        raise ValueError("A nonempty weight distribution must have a positive sum.")
    return [v / total for v in row]


def _validate_samples(samples, valid_keys, k):
    if not samples:
        return
    if not valid_keys.issuperset(samples):
        raise ValueError("Invalid layer vertex.")
    # Reuse only within this validation call. Mutable dictionaries and nested
    # rows are always checked again on the next validate()/encode().
    row_valid=storage().row_valid;seen={}
    for sample in samples.values():
        row = sample["weights"]
        key=id(row)
        if seen.get(key) is not row:
            if not row_valid(row,k):raise ValueError("Invalid layer weights.")
            if len(seen)<LOCAL_ROW_CACHE_LIMIT:seen[key]=row
        unit(sample["coverage"])


def validate(state):
    if state.get('schema') == 1:
        state = copy.deepcopy(state); state['schema'] = SCHEMA
        for layer in state.get('layers', []):
            if 'joints' not in layer:
                layer['joints'] = [identity for i, identity in enumerate(state['influences'])
                                   if any(sample['weights'][i] > 0 for sample in layer['samples'].values())]
    if state.get("schema") != SCHEMA:
        raise ValueError("Unsupported layer data version.")
    n, k = state["vertex_count"], len(state["influences"])
    storage().dimensions(n,k)
    if n*k>MAX_VALUES:raise ValueError('Skin exceeds the configured packed-buffer budget.')
    influence_set = set(state["influences"])
    base = state["base"]
    if len(influence_set) != k or len(base) != n * k:
        raise ValueError("Invalid base weights or influence identities.")
    base_key = (id(base), n, k)
    if not _cached_valid(_VALID_BASE,base_key,base):
        if min(base) < 0.0:
            raise ValueError("Base weights must be nonnegative and normalized.")
        for offset in range(0, n * k, k):
            row = base[offset:offset + k]
            if not (abs(sum(row) - 1.0) <= 1e-6) or min(row) < 0.0:
                raise ValueError("Base weights must be nonnegative and normalized.")
        _remember_valid(_VALID_BASE, base_key, base)
    ids = set()
    if len(state["layers"]) > MAX_LAYERS:
        raise ValueError("Prototype supports at most 32 layers.")
    valid_keys = _vertex_keys(n)
    for layer in state["layers"]:
        if 'influence_locks' in layer or 'redistribution' in layer:influence_rules().validate(layer)
        if layer["id"] in ids:
            raise ValueError("Duplicate layer identity.")
        ids.add(layer["id"])
        unit(layer["opacity"])
        if not isinstance(layer["enabled"], bool):
            raise ValueError("Invalid layer visibility.")
        joints = layer.get('joints', [])
        if len(set(joints)) != len(joints) or any(identity not in influence_set for identity in joints):
            raise ValueError('Layer joint membership is stale.')
        generated = layer.get('generated', {})
        if generated:
            gen_key = (id(generated), n, k)
            if _VALID_GEN.get(gen_key) is not generated:
                _validate_samples(generated, valid_keys, k)
                _remember_valid(_VALID_GEN, gen_key, generated)
        _validate_samples(layer["samples"], valid_keys, k)
        mask = layer["mask"]
        if mask:
            if not valid_keys.issuperset(mask):
                raise ValueError("Invalid mask vertex.")
            for value in mask.values():
                unit(value)
    reference = state.get('reference')
    if reference is not None:
        ref_key = (id(reference), n)
        if _VALID_REF.get(ref_key) is not reference:
            points = reference['points']
            if len(points) != n:
                raise ValueError('Reference vertex count changed.')
            isfinite = math.isfinite
            for point in points:
                if len(point) != 3 or not (isfinite(point[0]) and isfinite(point[1]) and isfinite(point[2])):
                    raise ValueError('Invalid reference points.')
            for record in reference['joints'].values():
                for name in ('position', 'x', 'y', 'z', 'end'):
                    value = record[name]
                    if len(value) != 3 or not (isfinite(value[0]) and isfinite(value[1]) and isfinite(value[2])):
                        raise ValueError('Invalid reference joint frame.')
            _remember_valid(_VALID_REF, ref_key, reference)
    return state


def _encode_value(value):
    if isinstance(value,array.array) and value.typecode=='d':
        if len(value)>storage().MAX_VALUES:raise ValueError('Packed skin buffer exceeds the memory budget.')
        packed=value
        if sys.byteorder!='little':
            packed=array.array('d',value);packed.byteswap()
        raw=memoryview(packed).cast('B')
        return {'__rtk_buffer__':'f64le-zlib-v1','count':len(value),
                'sha256':hashlib.sha256(raw).hexdigest(),
                'data':base64.b64encode(zlib.compress(raw,COMPRESSION_LEVEL)).decode('ascii')}
    return storage().json_default(value)


def _encode_base(base):
    """Cache only the immutable packed base; never samples, masks or a state."""
    if not isinstance(base,array.array) or base.typecode!='d':return _encode_value(base)
    key=(id(base),COMPRESSION_LEVEL)
    cached=_PACKED_BASE_ENCODINGS.get(key)
    if cached and cached[0]() is base:
        _PACKED_BASE_ENCODINGS.move_to_end(key)
        return cached[1]
    _PACKED_BASE_ENCODINGS.pop(key,None)
    payload=_encode_value(base);cost=len(payload['data'])+512
    if cost<=PACKED_BASE_CACHE_BYTES:
        while _PACKED_BASE_ENCODINGS and (len(_PACKED_BASE_ENCODINGS)>=4 or
                sum(value[2] for value in _PACKED_BASE_ENCODINGS.values())+cost>PACKED_BASE_CACHE_BYTES):
            _PACKED_BASE_ENCODINGS.popitem(last=False)
        cache=_PACKED_BASE_ENCODINGS
        def forget(reference):
            entry=cache.get(key)
            if entry and entry[0] is reference:cache.pop(key,None)
        try:reference=weakref.ref(base,forget)
        except TypeError:return payload
        cache[key]=(reference,payload,cost)
    return payload


def encode(state):
    state = validate(state)
    rows={}
    def default(value):
        if value is state['base']:return _encode_base(value)
        if getattr(value,'_rtk_sparse_weights',False):
            key=id(value);cached=rows.get(key)
            if cached is not None and cached[0] is value:return cached[1]
            payload=_encode_value(value)
            if len(rows)<LOCAL_ROW_CACHE_LIMIT:rows[key]=(value,payload)
            return payload
        return _encode_value(value)
    raw = json.dumps(state, separators=(",", ":"), allow_nan=False,default=default).encode("utf-8")
    return base64.b64encode(zlib.compress(raw, COMPRESSION_LEVEL)).decode("ascii")


def decode(text):
    raw=storage().decompress(base64.b64decode(text,validate=True),storage().MAX_BUFFER_BYTES)
    return validate(json.loads(raw.decode('utf-8'),object_hook=storage().json_object))


def create(base, count, influences, topology):
    influences=list(influences);storage().dimensions(count,len(influences))
    state = {"schema": SCHEMA, "vertex_count": count, "influences": list(influences),
             "topology": topology, "base": storage().copy_values(base), "layers": []}
    return validate(state)


class _PackedRows:
    """Fixed-width expansion memo owned by one composite call.

    Bound packed bytes plus estimated entry overhead; stop looking up rows
    when misses show that a source has little sharing. Never churn a full
    table of unique rows or retain it across snapshots.
    """
    __slots__=('rows','limit','hits','misses','enabled')
    def __init__(self,width):
        self.rows={};self.hits=0;self.misses=0
        self.limit=min(LOCAL_ROW_CACHE_LIMIT,max(0,PACKED_ROW_CACHE_BYTES//(width*8+256)))
        self.enabled=bool(self.limit)
    def get(self,weights):
        if not self.enabled:return weights.packed()
        key=id(weights);cached=self.rows.get(key)
        if cached is not None and cached[0] is weights:
            self.hits+=1;return cached[1]
        packed=weights.packed();self.misses+=1
        if self.misses>max(32,self.limit) and self.hits*8<self.misses:
            self.rows.clear();self.enabled=False
        elif len(self.rows)<self.limit:self.rows[key]=(weights,packed)
        return packed


def _compact_manual_row(row,enabled):
    """Use the existing sparse schema only for sufficiently empty wide rows."""
    if not enabled or getattr(row,'_rtk_sparse_weights',False):return row
    entries=[(i,value) for i,value in enumerate(row) if value!=0.]
    # Dense or narrow rows can be smaller than SparseWeights' tuple/dict data.
    # Preserve invalid nonzero entries so validation cannot silently hide them.
    return storage().SparseWeights(len(row),entries) if len(entries)*4<len(row) else row


def composite(state):
    """Layers are stored bottom to top; untouched vertices remain transparent."""
    result = storage().copy_values(state["base"])
    k = len(state["influences"])
    packed_rows=_PackedRows(k)
    for layer in state["layers"]:
        if not layer["enabled"] or not layer["opacity"]:
            continue
        opacity = layer["opacity"]
        mask = layer["mask"]
        for key, sample in effective_samples(layer).items():
            alpha = opacity * (mask.get(key, 1.0) if mask else 1.0) * sample["coverage"]
            if not alpha:
                continue
            start = int(key) * k
            weights = sample["weights"]
            if alpha == 1.0:
                result[start:start + k] = packed_rows.get(weights) if getattr(weights,'_rtk_sparse_weights',False) else weights
            else:
                inv = 1.0 - alpha
                if getattr(weights,'_rtk_sparse_weights',False):
                    row=[inv*a for a in result[start:start+k]]
                    for col,value in weights.entries:row[col]+=alpha*value
                    result[start:start+k]=row
                else:
                    result[start:start + k] = [inv * a + alpha * b for a, b in
                                               zip(result[start:start + k], weights)]
    return result


def effective_samples(layer):
    generated = layer.get('generated')
    samples = layer['samples']
    if not generated:
        return dict(samples)
    if not samples:
        return dict(generated)
    result = dict(generated)
    result.update(samples)
    return result


def weighted_influences(state, layer_id, tolerance=1e-8):
    """Authored nonzero contributions, independent of mask, alpha and enable.

    Manual samples override generated samples, including zero-coverage erases.
    This inspects saved rows only; it does not compose or read the Maya skin.
    """
    identities = state['influences']; width = len(identities); found = set()
    if layer_id == '__base__':
        base = state['base']
        for column, identity in enumerate(identities):
            if any(base[offset] > tolerance for offset in range(column, len(base), width)):
                found.add(identity)
        return found
    layer = next((row for row in state['layers'] if row['id'] == layer_id), None)
    if layer is None:
        return found
    manual = layer['samples']
    for source in (layer.get('generated') or {}, manual):
        for key, sample in source.items():
            if source is not manual and key in manual:
                continue
            coverage = sample['coverage']
            if coverage <= tolerance:
                continue
            threshold = tolerance / coverage
            weights=sample['weights']
            if getattr(weights,'_rtk_sparse_weights',False):found.update(identities[col] for col,value in weights.entries if value>threshold)
            else:found.update(identity for identity, value in zip(identities, weights) if value > threshold)
            if len(found) == width:
                return found
    return found


def composite_vertices(state, vertices):
    """Compose only requested rows. No per-frame evaluation is installed."""
    if not vertices:
        return []
    k = len(state['influences'])
    base = state['base']
    active_layers = [
        (layer['opacity'], layer['samples'], layer.get('generated') or {}, layer['mask'])
        for layer in state['layers']
        if layer['enabled'] and layer['opacity'] and (layer['samples'] or layer.get('generated'))
    ]
    output = storage().empty_values(len(vertices)*k)
    if not active_layers:
        for vertex in vertices:
            start = vertex * k
            output.extend(base[start:start + k])
        return output
    packed_rows=_PackedRows(k)
    for vertex in vertices:
        start = vertex * k
        row = base[start:start + k]
        key = str(vertex)
        for opacity, samples, generated, mask in active_layers:
            sample = samples.get(key) or generated.get(key)
            if sample is None:
                continue
            alpha = opacity * (mask.get(key, 1.0) if mask else 1.0) * sample['coverage']
            weights=sample['weights']
            if alpha == 1.0:
                row = packed_rows.get(weights) if getattr(weights,'_rtk_sparse_weights',False) else weights[:]
            elif alpha:
                inv = 1.0 - alpha
                if getattr(weights,'_rtk_sparse_weights',False):
                    row=[inv*a for a in row]
                    for col,value in weights.entries:row[col]+=alpha*value
                else:row = [inv * a + alpha * b for a, b in zip(row, weights)]
        output.extend(row)
    return output


def remap(state, influences):
    """Remap all saved buffers by UUID; adding zero-weight columns is lossless."""
    influences = list(influences)
    old = state['influences']
    if influences == old:
        return state
    influence_set = set(influences)
    if len(influence_set) != len(influences):
        raise ValueError('Duplicate influence identities.')
    old_index = {identity: i for i, identity in enumerate(old)}
    removed = [i for i, identity in enumerate(old) if identity not in influence_set]
    mapping = [old_index.get(identity, -1) for identity in influences]
    old_k = len(old)
    n = state['vertex_count']
    base = state['base']
    if removed:
        for offset in range(0, n * old_k, old_k):
            if any(base[offset + i] > 1e-10 for i in removed):
                raise ValueError('An influence with saved weights was removed. Restore it before editing.')
        for layer in state['layers']:
            for source in (layer['samples'], layer.get('generated') or {}):
                for sample in source.values():
                    weights = sample['weights']
                    if any(weights[i] > 1e-10 for i in removed):
                        raise ValueError('An influence with saved weights was removed. Restore it before editing.')
    def remap_row(values):
        if getattr(values,'_rtk_sparse_weights',False):
            new_columns={old_index[identity]:i for i,identity in enumerate(influences) if identity in old_index}
            return storage().SparseWeights(len(influences),((new_columns[col],value) for col,value in values.entries if col in new_columns))
        return [values[idx] if idx >= 0 else 0.0 for idx in mapping]
    storage().dimensions(n,len(influences))
    new_base = storage().copy_values((base[offset + idx] if idx >= 0 else 0.0
                for offset in range(0, n * old_k, old_k) for idx in mapping),n*len(influences))
    new_layers = []
    for layer in state['layers']:
        new_layer = dict(layer)
        new_layer['samples'] = {
            k: {'weights': remap_row(s['weights']), 'coverage': s['coverage']}
            for k, s in layer['samples'].items()
        }
        if 'generated' in layer:
            new_layer['generated'] = {
                k: {'weights': remap_row(s['weights']), 'coverage': s['coverage']}
                for k, s in layer['generated'].items()
            }
        new_layer['mask'] = dict(layer['mask'])
        new_layer['joints'] = [identity for identity in layer.get('joints', []) if identity in influence_set]
        new_layers.append(new_layer)
    result = dict(state, influences=influences, base=new_base, layers=new_layers)
    return validate(result)


def edit(state, action, data):
    """Return a new state; never mutate the caller's snapshot."""
    # Base and reference are immutable snapshots. Share them across edits;
    # shallow-copy only the layer and sub-dictionary that are about to change.
    result = dict(state, layers=list(state['layers']))
    if action == "add":
        if len(result["layers"]) >= MAX_LAYERS:
            raise ValueError("Prototype supports at most 32 layers.")
        result["layers"].append({"id": uuid.uuid4().hex, "name": str(data.get("name") or "Layer"),
                                 "enabled": True, "opacity": 1.0, "samples": {}, "mask": {},
                                 'joints': [], 'generated': {}})
        return validate(result)
    if action == 'reference':
        ref = data['reference']
        result['reference'] = {
            'points': [list(p) for p in ref['points']],
            'joints': copy.deepcopy(ref['joints']),
            **{k: copy.deepcopy(v) for k, v in ref.items() if k not in ('points', 'joints')},
        }
        return validate(result)
    layers = result["layers"]
    if action == "reorder":
        order = data.get("order")
        expected = [layer["id"] for layer in layers]
        if (not isinstance(order, list) or any(not isinstance(identity, str) for identity in order)
                or len(order) != len(expected) or len(set(order)) != len(order) or set(order) != set(expected)):
            raise ValueError("Layer order changed. Refresh and drag the layer again.")
        by_id = {layer["id"]: layer for layer in layers}
        result["layers"] = [by_id[identity] for identity in order]
        return validate(result)
    matches = [i for i, x in enumerate(layers) if x["id"] == data.get("layer")]
    if not matches:
        raise ValueError("Select a layer first.")
    index = matches[0]
    if action == "delete":
        layers.pop(index)
        return validate(result)
    if action == "move":
        direction = int(data["direction"])
        destination = index + direction
        if direction not in (-1, 1) or not 0 <= destination < len(layers):
            raise ValueError("Layer is already at this end of the stack.")
        layers[index], layers[destination] = layers[destination], layers[index]
        return validate(result)
    layer = dict(layers[index]); layers[index] = layer
    if action == "properties":
        layer["name"] = str(data.get("name", layer["name"]))
        layer["opacity"] = unit(data.get("opacity", layer["opacity"]))
        if "enabled" in data:
            if not isinstance(data["enabled"], bool):
                raise ValueError("Enabled must be true or false.")
            layer["enabled"] = data["enabled"]
    elif action == 'influence_settings':
        if 'influence_locks' in data:layer['influence_locks']=list(data['influence_locks']) if isinstance(data['influence_locks'],list) else data['influence_locks']
        if 'redistribution' in data:layer['redistribution']=data['redistribution']
        influence_rules().validate(layer)
    elif action == 'membership':
        layer['joints'] = list(dict.fromkeys(data['joints']))
    elif action == 'assign':
        if type(data.get('replace_manual',False)) is not bool:
            raise ValueError('Replace painted edits must be true or false.')
        if 'joints' in data:
            layer['joints'] = list(dict.fromkeys(layer.get('joints', []) + data['joints']))
        n = result['vertex_count']
        k = len(result['influences'])
        valid_keys = _vertex_keys(n)
        incoming = data['generated']
        if 'scope' not in data or data['scope'] is None:
            full_scope = True
            allowed = valid_keys
        else:
            scope = data['scope']
            if any(type(v) is not int or not 0 <= v < n for v in scope):
                raise ValueError('Invalid assignment scope.')
            scope_set = set(scope)
            full_scope = len(scope_set) == n
            allowed = valid_keys if full_scope else {str(v) for v in scope_set}
        if not allowed.issuperset(incoming):
            raise ValueError('Generated samples are outside the assignment scope.')
        copied_incoming = {
            key: {'weights': sample['weights'] if getattr(sample['weights'],'_rtk_sparse_weights',False) else sample['weights'][:], 'coverage': float(sample['coverage'])}
            for key, sample in incoming.items()
        }
        _validate_samples(copied_incoming, valid_keys, k)
        if full_scope:
            generated = copied_incoming
        else:
            generated = dict(layer.get('generated', {}))
            for key in allowed & generated.keys():
                del generated[key]
            generated.update(copied_incoming)
        _remember_valid(_VALID_GEN, (id(generated), n, k), generated)
        layer['generated'] = generated
        if data.get('replace_manual'):
            layer['samples']={key:sample for key,sample in layer['samples'].items() if key not in allowed}
        layer['assignment'] = copy.deepcopy(data.get('assignment', {}))
    elif action == 'paint':
        values = data['values']; mode = data['mode']; k = len(result['influences'])
        if mode not in ('mask', 'weights'):
            raise ValueError('Unknown paint mode.')
        valid_keys = _vertex_keys(result['vertex_count'])
        if not valid_keys.issuperset(values):
            raise ValueError('Invalid painted vertex.')
        clean_values = [(key, unit(val)) for key, val in values.items()]
        if mode == 'mask':
            mask = dict(layer['mask'])
            for key, value in clean_values:
                if value == 1.0:
                    mask.pop(key, None)
                else:
                    mask[key] = value
            layer['mask'] = mask
        else:
            influence = result['influences'].index(data['joint'])
            if data['joint'] in layer.get('influence_locks',()):return state
            if clean_values and data['joint'] not in layer.get('joints', []):
                layer['joints'] = layer.get('joints', []) + [data['joint']]
            other_members = [result['influences'].index(identity) for identity in layer.get('joints', []) if identity != data['joint']]
            compact=result['vertex_count']*k>storage().PACK_THRESHOLD and k>=16
            one_hot = storage().SparseWeights(k,((influence,1.),)) if compact else [1.0 if j == influence else 0.0 for j in range(k)]
            zero_row = [0.0] * k
            samples = dict(layer['samples'])
            generated = layer.get('generated') or {}
            if layer.get('influence_locks') or layer.get('redistribution')=='equal':
                rules=influence_rules();locked=rules.columns(result,layer)
                for key,value in clean_values:
                    painted=rules.paint(samples.get(key) or generated.get(key),influence,value,locked,k,layer.get('redistribution','proportional'))
                    row=_compact_manual_row(painted['weights'],compact)
                    samples[key]=dict(painted,weights=row) if row is not painted['weights'] else painted
            elif not other_members:
                for key, value in clean_values:
                    samples[key] = {'weights': one_hot if compact else one_hot[:], 'coverage': value}
            else:
                for key, value in clean_values:
                    sample = samples.get(key) or generated.get(key)
                    if sample is None:
                        samples[key] = {'weights': one_hot if compact else one_hot[:], 'coverage': value}
                        continue
                    s_weights = sample['weights']
                    s_cov = sample['coverage']
                    others = 0.0
                    for j in other_members:
                        others += s_weights[j] * s_cov
                    if others <= 1e-12:
                        samples[key] = {'weights': one_hot if compact else one_hot[:], 'coverage': value}
                        continue
                    amounts = zero_row[:]
                    amounts[influence] = value
                    scale = (1.0 - value) / others if value + others > 1.0 else 1.0
                    for j in other_members:
                        amounts[j] = (s_weights[j] * s_cov) * scale
                    coverage = sum(amounts)
                    weights = _compact_manual_row([a / coverage for a in amounts],compact) if coverage > 1e-12 else one_hot if compact else one_hot[:]
                    samples[key] = {'weights': weights, 'coverage': min(1.0, coverage)}
            layer['samples'] = samples
    elif action in ("flood", "mask", "clear"):
        n = result["vertex_count"]
        vertices = sorted(set(data.get("vertices", [])))
        if not vertices or any(type(v) is not int or not 0 <= v < n for v in vertices):
            raise ValueError("Choose vertices on the loaded mesh, or enable Whole mesh.")
        k = len(result["influences"])
        value = unit(data.get("value", 1))
        if action == "clear":
            samples = dict(layer["samples"])
            for v in vertices:
                samples.pop(str(v), None)  # Preserve independent mask.
            layer["samples"] = samples
        elif action == "mask":
            mask = dict(layer["mask"])
            if value == 1.0:
                for v in vertices:
                    mask.pop(str(v), None)
            else:
                for v in vertices:
                    mask[str(v)] = value
            layer["mask"] = mask
        else:
            influence = int(data["influence"])
            if not 0 <= influence < k:
                raise ValueError("Invalid influence.")
            if layer.get('influence_locks') or layer.get('redistribution')=='equal':
                return edit(state,'paint',dict(layer=layer['id'],mode='weights',joint=result['influences'][influence],values={str(v):value for v in vertices}))
            if k == 1 and value != 1.0:
                raise ValueError("A single-influence skin requires weight 1.")
            samples = dict(layer["samples"])
            generated = layer.get('generated') or {}
            missing = [v for v in vertices if str(v) not in samples and str(v) not in generated]
            underlying = dict(state, layers=state["layers"][:index])
            if not missing:
                fallback = {}
            elif len(missing) * 2 < n:
                comp = composite_vertices(underlying, missing)
                fallback = {v: comp[i * k:(i + 1) * k] for i, v in enumerate(missing)}
            else:
                comp = composite(underlying)
                fallback = {v: comp[v * k:(v + 1) * k] for v in missing}
            for v in vertices:
                key = str(v)
                existing = samples.get(key) or generated.get(key)
                row = existing["weights"][:] if existing is not None else fallback[v][:]
                remaining = sum(row) - row[influence]
                if remaining <= 1e-12 and value < 1.0:
                    # There is no meaningful recipient to redistribute to.
                    raise ValueError("No other weighted influence can receive the remainder. Flood another influence to 1 first.")
                scale = (1.0 - value) / remaining if remaining > 1e-12 else 0.0
                for j in range(k):
                    row[j] = value if j == influence else row[j] * scale
                samples[key] = {"weights": normalized(row), "coverage": 1.0}
            layer["samples"] = samples
    else:
        raise ValueError("Unknown layer action: " + action)
    if layer.get('influence_locks') and action in ('assign','clear','flood'):
        keys=(set(layer.get('generated',{}))|set(layer['samples'])|set(state['layers'][index].get('generated',{}))|set(state['layers'][index]['samples']))
        if action in ('clear','flood'):keys={str(v) for v in vertices}
        elif not full_scope:keys &= allowed
        result=influence_rules().protect(state,result,layer['id'],keys)
    return validate(result)
