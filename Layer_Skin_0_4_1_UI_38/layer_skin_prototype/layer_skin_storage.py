"""Compact production-size skin buffers; standard library only.

Small scenes retain the legacy list representation. Large bases use packed
float64 buffers; imported layer rows and file data keep only nonzero values.
"""
import array
import base64
import bisect
from collections.abc import Sequence
import hashlib
import math
import sys
import zlib

PACK_THRESHOLD = 2_000_000
MAX_BUFFER_BYTES = 1024 * 1024 * 1024
MAX_VALUES = MAX_BUFFER_BYTES // 8
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
CHUNK_VALUES = 262144
CHUNK_BYTES = 1024 * 1024


def dimensions(count, width):
    if type(count) is not int or type(width) is not int or count <= 0 or not 0 < width <= 4096:
        raise ValueError('Invalid skin vertex/influence dimensions.')
    values = count * width
    if values > MAX_VALUES:
        raise ValueError('Skin needs {:.1f} MiB per packed weight buffer; the supported buffer budget is 1024 MiB.'
                         .format(values * 8 / 1024**2))
    return values


class DenseWeights(array.array):
    """Float64 array accepting the same row-slice assignments as a list."""
    def __new__(cls, values=()):
        return super().__new__(cls, 'd', values)

    def __setitem__(self, key, value):
        if isinstance(key, slice) and not isinstance(value, array.array):
            value = array.array('d', value)
        return super().__setitem__(key, value)


def copy_values(values, count=None):
    size = len(values) if count is None else count
    return DenseWeights(values) if size > PACK_THRESHOLD or isinstance(values, array.array) else list(values)


def empty_values(size):
    return DenseWeights() if size > PACK_THRESHOLD else []


def snapshot_rows(values, vertices, width):
    """Packed Undo rows; avoid a Python scalar loop for contiguous buffers."""
    if len(vertices)*width==len(values) and vertices==list(range(len(vertices))):
        return array.array('d',values)
    result=array.array('d')
    for vertex in vertices:result.extend(values[vertex*width:(vertex+1)*width])
    return result


class SparseWeights(Sequence):
    """Immutable normalized row, with ordinary dense indexing/iteration."""
    _rtk_sparse_weights = True
    __slots__=('_width','_entries','_values')

    def __init__(self, width, entries):
        self._width = width
        supplied=tuple(entries)
        if any(type(i) is not int or not isinstance(v,(int,float)) or isinstance(v,bool) for i,v in supplied):
            raise ValueError('Invalid sparse weight entries.')
        pairs = tuple(sorted((i, float(v)) for i, v in supplied if v != 0.))
        if type(width) is not int or not 0 < width <= 4096 or len({i for i, v in pairs}) != len(pairs):
            raise ValueError('Invalid sparse weight row.')
        if any(not 0 <= i < width or not math.isfinite(v) or v < 0 for i, v in pairs):
            raise ValueError('Invalid sparse weight values.')
        self._entries = pairs
        self._values = dict(pairs)

    @property
    def width(self):return self._width

    @property
    def entries(self):return self._entries

    def __len__(self):
        return self.width

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self._values.get(i, 0.) for i in range(*index.indices(self.width))]
        if index < 0:
            index += self.width
        if not 0 <= index < self.width:
            raise IndexError(index)
        return self._values.get(index, 0.)

    def __iter__(self):
        return (self._values.get(i, 0.) for i in range(self.width))

    def __eq__(self, other):
        if self is other:
            return True
        if getattr(other, '_rtk_sparse_weights', False):
            return self.width == other.width and self.entries == other.entries
        return isinstance(other, Sequence) and len(other) == self.width and all(a == b for a, b in zip(self, other))

    def __deepcopy__(self, memo):
        return self

    def packed(self):
        result=DenseWeights([0.])*self.width
        for column,value in self.entries:result[column]=value
        return result


class SparseMatrix(Sequence):
    """Read-only CSR file weights with a flattened sequence interface."""
    _rtk_sparse_matrix = True
    __slots__=('_count','_width','_offsets','_columns','_values')

    def __init__(self, count, width, offsets, columns, values):
        dimensions(count, width)
        if len(offsets) != count + 1 or offsets[0] != 0 or offsets[-1] != len(values) or len(columns) != len(values):
            raise ValueError('Invalid sparse row offsets.')
        self._count, self._width = count, width
        def readonly(values,kind):
            if not isinstance(values,(array.array,memoryview)):values=array.array(kind,values)
            return memoryview(values).toreadonly()
        self._offsets=readonly(offsets,'Q');self._columns=readonly(columns,'I');self._values=readonly(values,'d')

    @property
    def count(self):return self._count

    @property
    def width(self):return self._width

    @property
    def offsets(self):return self._offsets

    @property
    def columns(self):return self._columns

    @property
    def values(self):return self._values

    def __len__(self):
        return self.count * self.width

    def entries(self, vertex):
        start, end = self.offsets[vertex:vertex + 2]
        return ((self.columns[i], self.values[i]) for i in range(start, end))

    def row(self, vertex):
        return SparseWeights(self.width, self.entries(vertex))

    def __getitem__(self, index):
        if isinstance(index, slice):
            start, stop, step = index.indices(len(self))
            if step == 1 and stop - start == self.width and start % self.width == 0:
                return self.row(start // self.width)[:]
            return [self[i] for i in range(start, stop, step)]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        vertex, column = divmod(index, self.width)
        start, end = self.offsets[vertex:vertex + 2]
        found = bisect.bisect_left(self.columns, column, start, end)
        return self.values[found] if found < end and self.columns[found] == column else 0.

    def __iter__(self):
        for vertex in range(self.count):
            yield from self.row(vertex)


def row_entries(values, vertex, width):
    if getattr(values, '_rtk_sparse_matrix', False):
        return values.entries(vertex)
    return ((i, value) for i, value in enumerate(values[vertex * width:(vertex + 1) * width]) if value != 0.)


def row_valid(row, width):
    if len(row) != width:
        return False
    values = [value for index, value in row.entries] if getattr(row, '_rtk_sparse_weights', False) else row
    return bool(values) and all(math.isfinite(v) and v >= 0 for v in values) and abs(math.fsum(values) - 1.) <= 1e-6


def chunks(values, kind='d'):
    """Little-endian byte chunks; no full-size temporary bytes copy."""
    if isinstance(values,memoryview) and values.format==kind and sys.byteorder=='little':
        view=values.cast('B')
        for start in range(0,len(view),CHUNK_BYTES):yield view[start:start+CHUNK_BYTES]
        return
    packed = values if isinstance(values, array.array) and values.typecode == kind else array.array(kind, values)
    if sys.byteorder != 'little':
        packed = array.array(kind, packed)
        packed.byteswap()
    view = memoryview(packed).cast('B')
    for start in range(0, len(view), CHUNK_BYTES):
        yield view[start:start + CHUNK_BYTES]


def digest_values(values, kind='d'):
    result = hashlib.sha256()
    for chunk in chunks(values, kind):
        result.update(chunk)
    return result.hexdigest()


def decompress(payload, limit):
    decoder = zlib.decompressobj()
    value = decoder.decompress(payload, limit + 1)
    if len(value) > limit or decoder.unconsumed_tail or not decoder.eof or decoder.unused_data:
        raise ValueError('Packed skin data is truncated, excessive or has trailing content.')
    return value


def json_default(value):
    if isinstance(value, array.array) and value.typecode == 'd':
        if len(value) > MAX_VALUES:
            raise ValueError('Packed skin buffer exceeds the memory budget.')
        packed = value
        if sys.byteorder != 'little':
            packed = array.array('d', value)
            packed.byteswap()
        raw = memoryview(packed).cast('B')
        return {'__rtk_buffer__': 'f64le-zlib-v1', 'count': len(value),
                'sha256': hashlib.sha256(raw).hexdigest(),
                'data': base64.b64encode(zlib.compress(raw, 6)).decode('ascii')}
    if getattr(value, '_rtk_sparse_weights', False):
        return {'__rtk_row__': 'sparse-v1', 'width': len(value), 'entries': value.entries}
    raise TypeError('Unsupported layer value: ' + type(value).__name__)


def json_object(value):
    if '__rtk_buffer__' in value:
        count = value.get('count')
        if value['__rtk_buffer__'] != 'f64le-zlib-v1' or type(count) is not int or not 0 < count <= MAX_VALUES:
            raise ValueError('Unsupported or excessive packed layer buffer.')
        raw = decompress(base64.b64decode(value['data'], validate=True), count * 8)
        if len(raw) != count * 8 or hashlib.sha256(raw).hexdigest() != value.get('sha256'):
            raise ValueError('Packed layer buffer checksum/length mismatch.')
        result = DenseWeights()
        result.frombytes(raw)
        if sys.byteorder != 'little':
            result.byteswap()
        return result
    if '__rtk_row__' in value:
        if value['__rtk_row__'] != 'sparse-v1':
            raise ValueError('Unsupported sparse layer row.')
        return SparseWeights(value['width'], value['entries'])
    return value
