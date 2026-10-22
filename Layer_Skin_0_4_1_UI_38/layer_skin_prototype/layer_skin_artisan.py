"""Native Artisan working array. Authoring weights remain in the layer command.

One built-in network node per mesh stores its array and receives the mesh's
outMesh in a generic surface input. It never drives scene geometry. Keep it
alive after UI close: Maya's native array-paint Undo commands can still refer to
it. New/open scenes discard it naturally. This is not a runtime skin solver.
"""

_buffers = {}
BINDING_REVISION = 'mesh_geometry_1'


class PaintBuffer:
    def __init__(self, api):
        self.api = api
        self.owner = None
        om = api.om
        edit = om.MDGModifier()
        node = edit.createNode('network')
        edit.doIt()
        try:
            fn = om.MFnDependencyNode(node)
            fn.setName(':rtkLayerSkinPaintBuffer')
            fn.setDoNotWrite(True)
            typed = om.MFnTypedAttribute()
            attribute = typed.create('values', 'vals', om.MFnData.kDoubleArray)
            typed.storable = False
            typed.hidden = True
            typed.keyable = False
            fn.addAttribute(attribute)
            geometry = om.MFnGenericAttribute()
            surface = geometry.create('surface', 'surface')
            geometry.addDataType(om.MFnData.kMesh)
            geometry.storable = False
            geometry.cached = False
            geometry.hidden = True
            geometry.keyable = False
            fn.addAttribute(surface)
            self.handle = om.MObjectHandle(node)
            self.plug = fn.findPlug('values', False)
            self.surface = fn.findPlug('surface', False)
        except Exception:
            edit.undoIt()
            raise

    def valid(self):
        return self.handle.isValid() and self.handle.isAlive()

    def attribute(self):
        if not self.valid():
            raise RuntimeError('The native paint buffer was removed. Click Paint again.')
        return self.plug.name()

    def bind(self, mesh):
        """Give Artisan a geometry path to the array host, with no mesh input edit."""
        self.attribute()
        om = self.api.om
        source = om.MFnDependencyNode(self.api.obj(mesh)).findPlug('outMesh', False)
        incoming = self.surface.connectedTo(True, False)
        if len(incoming) == 1 and incoming[0] == source:
            return
        edit = om.MDGModifier()
        for previous in incoming:
            edit.disconnect(previous, self.surface)
        edit.connect(source, self.surface)
        try:
            edit.doIt()
        except Exception:
            edit.undoIt()
            raise
        actual = self.surface.connectedTo(True, False)
        if len(actual) != 1 or actual[0] != source:
            edit.undoIt()
            raise RuntimeError('The paint array has no geometry connection to the selected mesh.')

    def geometry_sources(self):
        self.attribute()
        return [source.name() for source in self.surface.connectedTo(True, False)]

    def write(self, values):
        self.attribute()
        om = self.api.om
        data = om.MFnDoubleArrayData().create(om.MDoubleArray(values))
        # Direct API data transfer is transient and creates no authoring Undo.
        self.plug.setMObject(data)

    def read(self):
        self.attribute()
        return list(self.api.om.MFnDoubleArrayData(self.plug.asMObject()).array())


def get_buffer(api, mesh):
    # Never rebind a native Undo array to a different mesh/vertex count.
    identity = api.om.MFnDependencyNode(api.obj(mesh)).uuid().asString()
    for key in list(_buffers):
        if not _buffers[key].valid():del _buffers[key]
    buffer = _buffers.get(identity)
    if buffer is None:
        buffer = PaintBuffer(api)
        _buffers[identity] = buffer
    buffer.bind(mesh)
    return buffer
