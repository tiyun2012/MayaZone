"""Attach a read-only paint trace to the open Layer Skin window.

Choose the joint/layer and click Paint first. Run this file with runpy.run_path
from Maya's Python Script Editor. Paint a white patch, capture After paint,
switch to another joint, capture Switched away, switch back, capture Back/black,
then Copy report. No plug-in reload or scene edits are performed by this file.
Closing the diagnostic window removes its temporary Python wrappers.
"""
import array
import collections
import datetime
import functools
import hashlib
import heapq
import inspect
import json
import math
import sys
import time
import types

DEBUG_VERSION = "1.1"
HANDLE = "_rtk_layer_skin_debug_trace"
BASE = "__base__"


def _hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stats(values):
    values = list(values or [])
    finite = all(math.isfinite(value) for value in values)
    strong = heapq.nlargest(8, ((abs(v), i, v) for i, v in enumerate(values) if abs(v) > 1e-8))
    return dict(count=len(values), minimum=min(values) if values else None,
                maximum=max(values) if values else None,
                mean=sum(values)/len(values) if values else None,
                nonzero=sum(abs(v) > 1e-8 for v in values), finite=finite,
                digest=hashlib.sha256(array.array("d", values).tobytes()).hexdigest(),
                strongest=[dict(vertex=i, value=v) for _, i, v in strong])


def _difference(left, right):
    if len(left) != len(right):
        return dict(same=False, left_count=len(left), right_count=len(right))
    worst = heapq.nlargest(8, ((abs(a-b), i, a, b) for i, (a, b) in enumerate(zip(left, right)) if abs(a-b) > 2e-6))
    return dict(same=not worst, maximum_error=worst[0][0] if worst else 0.,
                differing_values=sum(abs(a-b) > 2e-6 for a, b in zip(left, right)),
                examples=[dict(index=i, left=a, right=b) for _, i, a, b in worst])


def _layer_values(state, layer_id, joint, mode):
    """Decode the scene data independently of the session's loaded buffer."""
    n = state["vertex_count"]
    ids = state["influences"]
    column = ids.index(joint) if joint in ids else None
    if layer_id == BASE:
        if mode == "mask":
            return [1.]*n
        return state["base"][column::len(ids)] if column is not None else [0.]*n
    layer = next((row for row in state["layers"] if row["id"] == layer_id), None)
    if layer is None:
        raise ValueError("The requested layer is absent from the scene data: " + str(layer_id))
    if mode == "mask":
        return [layer["mask"].get(str(i), 1.) for i in range(n)]
    values = [0.]*n
    if column is not None:
        for source in (layer.get("generated") or {}, layer["samples"]):
            for key, sample in source.items():
                values[int(key)] = sample["weights"][column]*sample["coverage"]
    return values


def _scope(session):
    return dict(mesh=session.target, layer=session.layer, joint=session.joint,
                joint_path=getattr(session, "joint_path", None), mode=session.mode)


def _gate(session):
    stroke = session.stroke
    return dict(active=session.active, readonly=session.readonly,
                view_ready=getattr(session, "_view_ready", None),
                configuring=getattr(session, "_configuring_view", None),
                committing=getattr(session, "_committing", None),
                has_stroke=stroke is not None,
                pending_vertices=len(stroke.get("values", {})) if stroke else 0,
                stroke_error=stroke.get("error") if stroke else None)


def _short(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (tuple, list)):
        return [_short(item) for item in value[:10]]
    if isinstance(value, dict):
        return {str(key): _short(val) for key, val in list(value.items())[:16]}
    return type(value).__name__


class Trace:
    """Temporary instance wrappers. No commands that edit the Maya scene."""
    def __init__(self, window):
        self.window = window
        self.session = window.session
        self.api = self.session.api
        self.started = time.monotonic()
        self.created = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.origin = _scope(self.session)
        if (not self.origin["mesh"] or not self.origin["layer"] or self.origin["layer"] == BASE
                or not self.session.active or self.session.readonly or getattr(self.session, "closed", False)):
            raise RuntimeError("Choose an editable layer and joint, then click Paint before starting this trace.")
        self.events = collections.deque(maxlen=240)
        self.counts = collections.Counter()
        self.sample_groups = collections.Counter()
        self.snapshots = collections.deque(maxlen=12)
        self.patches = []
        self.active = False
        self.dialog = None
        self.baseline_counts = dict(getattr(self.session, "paint_events", {}))
        self.source_files = {}
        self.environment = dict(python=sys.version)
        try:
            self.environment["maya_version"] = self.api.cmds.about(version=True)
            self.environment["maya_api_version"] = self.api.cmds.about(apiVersion=True)
        except Exception:
            pass
        for name, method in (("session", type(self.session).start),
                             ("ui", type(window).choose_joint),
                             ("plugin", self.api.context), ("core", self.api.core.decode)):
            try:
                self.source_files[name] = inspect.getsourcefile(method)
            except (TypeError, OSError):
                self.source_files[name] = None

    def _event(self, name, **data):
        try:
            self.events.append(dict(t=round(time.monotonic()-self.started, 5), event=name, **data))
        except Exception:
            pass  # A diagnostic failure must never change paint behavior.

    def _patch(self, owner, name, factory):
        original = getattr(owner, name, None)
        if not callable(original):
            return
        had_local = name in vars(owner)
        raw = vars(owner).get(name)
        wrapper = factory(original)
        setattr(owner, name, wrapper)
        self.patches.append((owner, name, wrapper, had_local, raw))

    def _boundary(self, name):
        def factory(original):
            @functools.wraps(original)
            def wrapped(*args, **kwargs):
                self.counts[name] += 1
                large_snapshot = name in ("prepare", "refresh_view")
                self._event(name+":enter", args="snapshot" if args and large_snapshot else _short(args),
                            kwargs={key: ("snapshot" if key == "snapshot" else _short(value)) for key, value in kwargs.items()},
                            scope=_scope(self.session), gate=_gate(self.session))
                try:
                    result = original(*args, **kwargs)
                except BaseException as exc:
                    self._event(name+":exception", error=type(exc).__name__+": "+str(exc))
                    raise
                self._event(name+":exit", result=type(result).__name__ if large_snapshot else _short(result), scope=_scope(self.session),
                            gate=_gate(self.session), last_stroke=_short(getattr(self.session, "last_stroke", None)))
                return result
            return wrapped
        return factory

    def _sample(self, name):
        def factory(original):
            @functools.wraps(original)
            def wrapped(*args, **kwargs):
                self.counts[name] += 1
                gate = _gate(self.session) if name == "set_value" else None
                accepted = getattr(self.session, "paint_events", {}).get("accepted_sample", 0)
                try:
                    result = original(*args, **kwargs)
                except BaseException as exc:
                    self._event(name+":exception", args=_short(args), error=type(exc).__name__+": "+str(exc))
                    raise
                try:
                    if name == "get_value":
                        group = "get id={}:{}".format(args[0] if args else "?", "nonzero" if result else "zero")
                    elif name == "can_begin_stroke":
                        group = "can_begin_stroke="+str(bool(result))
                    else:
                        saved = getattr(self.session, "paint_events", {}).get("accepted_sample", 0) > accepted
                        self.counts["set_value.accepted" if saved else "set_value.ignored"] += 1
                        flags = {key: value for key, value in gate.items() if key != "pending_vertices"}
                        group = "set id={}:{} gate={}".format(args[0] if args else "?", "accepted" if saved else "ignored", json.dumps(flags, sort_keys=True))
                    if group not in self.sample_groups and len(self.sample_groups) >= 64:
                        group = name+":other_groups"
                    self.sample_groups[group] += 1
                    # Counts cover every callback; only a few examples are kept.
                    # No native reads or state serialization occur per vertex.
                    if self.sample_groups[group] <= 3:
                        self._event(name, args=_short(args), result=_short(result), group=group)
                except Exception:
                    pass
                return result
            return wrapped
        return factory

    def attach(self):
        if self.active:
            return
        try:
            for name in ("initialize", "surface", "before_stroke", "after_stroke", "finalize",
                         "flush_pending", "start", "stop", "tool_cleanup", "prepare", "reload_feedback", "refresh_view",
                         "array_attribute", "_capture_array"):
                self._patch(self.session, name, self._boundary(name))
            for name in ("get_value", "set_value", "can_begin_stroke"):
                self._patch(self.session, name, self._sample(name))
            for name in ("choose_joint", "stop_paint", "commit_released_stroke"):
                self._patch(self.window, name, self._boundary("ui."+name))
            self.active = True
        except Exception:
            self.stop()
            raise
        self._event("trace_attached")

    def stop(self):
        for owner, name, wrapper, had_local, raw in reversed(self.patches):
            if getattr(owner, name, None) is wrapper:
                if had_local:
                    setattr(owner, name, raw)
                else:
                    delattr(owner, name)
        self.patches = []
        self.active = False
        self._event("trace_stopped")

    def snapshot(self, label):
        session = self.session
        snapshot = dict(label=label, t=round(time.monotonic()-self.started, 5),
                        scope=_scope(session), gate=_gate(session),
                        loaded_values=_stats(session.values),
                        last_error=getattr(session, "last_error", None),
                        last_stroke=_short(getattr(session, "last_stroke", None)),
                        callback_counts=dict(getattr(session, "paint_events", {})))
        errors = {}
        ui = {}
        for name, getter in (("layer", self.window.selected_id), ("joint", self.window.active_joint),
                             ("joint_path", lambda: self.window._active_joint_path),
                             ("hierarchy_selection", lambda: self.window.browser.joints()),
                             ("status", lambda: self.window.status.text()),
                             ("range", lambda: self.window.display_range.text())):
            try:
                ui[name] = getter()
            except Exception as exc:
                errors["ui."+name] = str(exc)
        snapshot["ui"] = ui
        if getattr(session, "buffer", None) is not None:
            try:
                snapshot["native_paint_array"] = _stats(session.buffer.read())
                snapshot["array_vs_loaded"] = _difference(session.buffer.read(), session.values)
            except Exception as exc:
                errors["native_paint_array"] = str(exc)
        stroke = session.stroke
        if stroke is not None:
            snapshot["pending"] = dict(scope=_short(stroke.get("scope")), expected=stroke.get("expected"),
                                       error=stroke.get("error"), samples=_stats(list(stroke.get("values", {}).values())),
                                       examples=list(stroke.get("values", {}).items())[:8],
                                       baseline=_stats(stroke.get("baseline", [])))
        try:
            snapshot["paint_info"] = session.paint_report()
        except Exception as exc:
            errors["paint_info"] = str(exc)
        try:
            ctx = self.api.context(self.origin["mesh"])
            meta, cached = self.api.metadata(ctx)
            scene = dict(mesh=ctx["shape"], skin=ctx["skin"], vertex_count=ctx["count"],
                         mesh_uuid=ctx.get("uuid"), influence_count=len(ctx["ids"]), metadata_node=meta)
            snapshot["scene"] = scene
            if not meta:
                scene["error"] = "No layer metadata node found."
            else:
                # Read/decode the actual attribute, bypassing the plug-in's decoded cache.
                raw = self.api.cmds.getAttr(meta+".rtkLayerSkinData")
                saved = self.api.core.remap(self.api.core.decode(raw), ctx["ids"])
                scene.update(raw_length=len(raw), raw_hash=_hash(raw),
                             remapped_state_hash=_hash(self.api.core.encode(saved)),
                             decoded_cache_matches_scene=cached == saved)
                scene["layers"] = [dict(id=row["id"], name=row["name"], enabled=row["enabled"],
                                        opacity=row["opacity"], members=len(row.get("joints", [])),
                                        manual_vertices=len(row["samples"]), generated_vertices=len(row.get("generated") or {}),
                                        mask_vertices=len(row["mask"])) for row in saved["layers"]]
                tracked = _layer_values(saved, self.origin["layer"], self.origin["joint"], self.origin["mode"])
                scene["original_joint_layer_values"] = _stats(tracked)
                if session.target == ctx["shape"] and session.layer:
                    if session.mode == "skin":
                        column = ctx["ids"].index(session.joint) if session.joint in ctx["ids"] else None
                        current = ctx["weights"][column::len(ctx["ids"])] if column is not None else [0.]*ctx["count"]
                    else:
                        current = _layer_values(saved, session.layer, session.joint, session.mode)
                    scene["current_view_saved_values"] = _stats(current)
                    scene["loaded_vs_saved"] = _difference(session.values, current)
                if self.origin["joint"] in ctx["ids"]:
                    col = ctx["ids"].index(self.origin["joint"])
                    scene["original_joint_native_skin_values"] = _stats(ctx["weights"][col::len(ctx["ids"])])
                scene["native_vs_saved_composite"] = _difference(ctx["weights"], self.api.core.composite(saved))
        except Exception as exc:
            errors["scene_read"] = type(exc).__name__+": "+str(exc)
        if errors:
            snapshot["query_errors"] = errors
        self.snapshots.append(snapshot)
        self._event("snapshot", label=label)
        return snapshot

    def findings(self):
        notes = []
        native_array = self.session.buffer is not None if hasattr(self.session, "buffer") else False
        if not self.counts["set_value"] and not native_array:
            notes.append("No Python set_value callbacks observed since attachment. The callback path needs inspection.")
        elif self.counts["set_value"]:
            accepted = self.counts["set_value.accepted"]
            if not accepted:
                notes.append("Python received set_value calls, but the session accepted none. Inspect sample_groups and their gate flags.")
        for snap in self.snapshots:
            scene = snap.get("scene", {})
            label = snap["label"]+": "
            if scene.get("decoded_cache_matches_scene") is False:
                notes.append(label+"the decoded metadata cache disagrees with the actual scene attribute.")
            if scene.get("loaded_vs_saved", {}).get("same") is False:
                notes.append(label+"the session display buffer differs from saved data for the current view.")
            if scene.get("native_vs_saved_composite", {}).get("same") is False:
                notes.append(label+"native skin weights differ from the saved layer composite.")
            receipt = snap.get("last_stroke") or {}
            if receipt.get("status") in ("rejected", "verification_failed"):
                notes.append(label+"stroke "+receipt["status"]+": "+str(receipt.get("error")))
            ui = snap.get("ui", {})
            scope = snap["scope"]
            if snap["gate"]["active"] and (ui.get("joint") != scope["joint"] or ui.get("layer") != scope["layer"]):
                notes.append(label+"the hierarchy/layer selection and active paint scope disagree.")
        marked = {row["label"]: row for row in self.snapshots}
        after = marked.get("after_paint", {}).get("scene", {}).get("original_joint_layer_values", {})
        back = marked.get("back_to_painted_joint", {}).get("scene", {}).get("original_joint_layer_values", {})
        if after.get("nonzero") and back.get("count") and not back.get("nonzero"):
            notes.append("The original joint has saved nonzero layer values after paint and zero saved values after switching back.")
        if after.get("nonzero") and back.get("digest") == after.get("digest"):
            notes.append("The original joint's saved layer values survived the joint round trip. Inspect loaded_vs_saved and get_value callbacks for display loading.")
        return notes or ["No mismatch identified in the captured data. Reproduce the black view before copying the report."]

    def report(self):
        return dict(debug_version=DEBUG_VERSION, created_utc=self.created,
                    package_version=getattr(self.api, "VERSION", None), source_files=self.source_files, environment=self.environment,
                    tracing=self.active, original_view=self.origin, findings=self.findings(),
                    callback_counts=dict(self.counts), sample_groups=dict(self.sample_groups),
                    baseline_callback_counts=self.baseline_counts,
                    snapshots=list(self.snapshots), events=list(self.events))


def _qt():
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtWidgets
    return QtCore, QtWidgets


def _find_window(QtWidgets):
    app = QtWidgets.QApplication.instance()
    if app is None:
        raise RuntimeError("Run this script inside Maya with Layer Skin open.")
    candidates = [w for w in app.topLevelWidgets()
                  if w.objectName() == "rtkLayerSkinPrototypeWindow" and w.isVisible()
                  and hasattr(w, "session") and not getattr(w, "_closed", False)]
    if len(candidates) != 1:
        raise RuntimeError("Expected one visible Layer Skin window; found {}. Open the tool and keep one window.".format(len(candidates)))
    return candidates[0]


def start(window=None):
    """Re-running this script detaches the previous trace before attaching."""
    QtCore, QtWidgets = _qt()
    previous = getattr(sys.modules.get(HANDLE), "trace", None)
    if previous is not None:
        previous.stop()
        if previous.dialog is not None:
            try:
                previous.dialog.close()
            except RuntimeError:
                pass  # The parent Layer Skin widget may already be deleted.
    window = window if window is not None else _find_window(QtWidgets)
    trace = Trace(window)

    class DebugDialog(QtWidgets.QDialog):
        def __init__(self):
            super(DebugDialog, self).__init__(window)
            self.setObjectName("rtkLayerSkinPaintDebug")
            self.setWindowTitle("Layer Skin · Paint trace")
            self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
            self.resize(570, 330)
            layout = QtWidgets.QVBoxLayout(self)
            instructions = QtWidgets.QLabel("Paint a white patch on the chosen joint, then capture each stage.\nSwitch away and back using the Layer Skin joint hierarchy.")
            instructions.setWordWrap(True)
            layout.addWidget(instructions)
            row = QtWidgets.QHBoxLayout()
            layout.addLayout(row)
            for title, label in (("1 · After paint", "after_paint"), ("2 · Switched away", "switched_away"), ("3 · Back / black", "back_to_painted_joint")):
                button = QtWidgets.QPushButton(title)
                row.addWidget(button)
                button.clicked.connect(lambda checked=False, label=label: self.capture(label))
            self.log = QtWidgets.QPlainTextEdit()
            self.log.setReadOnly(True)
            layout.addWidget(self.log)
            row = QtWidgets.QHBoxLayout()
            layout.addLayout(row)
            button = QtWidgets.QPushButton("Copy report")
            row.addWidget(button)
            button.clicked.connect(self.copy_report)
            button = QtWidgets.QPushButton("Stop trace")
            row.addWidget(button)
            button.clicked.connect(self.stop_trace)

        def capture(self, label):
            try:
                snapshot = trace.snapshot(label)
                scene = snapshot.get("scene", {})
                saved = scene.get("original_joint_layer_values", {})
                self.log.appendPlainText("{} | loaded max={} | original joint saved max={} | pending={} | last save={}".format(
                    label, snapshot["loaded_values"]["maximum"], saved.get("maximum"),
                    snapshot["gate"]["pending_vertices"], (snapshot.get("last_stroke") or {}).get("status", "none")))
                if snapshot.get("query_errors"):
                    self.log.appendPlainText("Read errors: "+json.dumps(snapshot["query_errors"], ensure_ascii=False))
            except Exception as exc:
                self.log.appendPlainText("Capture error: "+str(exc))

        def copy_report(self):
            text = "LAYER_SKIN_DEBUG_BEGIN\n"+json.dumps(trace.report(), indent=2, ensure_ascii=False, default=str)+"\nLAYER_SKIN_DEBUG_END"
            QtWidgets.QApplication.clipboard().setText(text)
            print(text)
            self.log.appendPlainText("Report copied and printed in the Script Editor. Paste it into the conversation.")

        def stop_trace(self):
            trace.stop()
            self.log.appendPlainText("Trace stopped; temporary Python wrappers removed. Captured report is still available.")

        def closeEvent(self, event):
            trace.stop()
            super(DebugDialog, self).closeEvent(event)

    dialog = DebugDialog()
    trace.dialog = dialog
    def dialog_destroyed(*_):
        trace.stop()
        trace.dialog = None
    dialog.destroyed.connect(dialog_destroyed)
    # Own the trace independently of runpy's transient globals.
    holder = types.ModuleType(HANDLE)
    holder.trace = trace
    sys.modules[HANDLE] = holder
    try:
        trace.attach()
        dialog.capture("before_paint")
        dialog.show()
    except Exception:
        trace.stop()
        dialog.close()
        raise
    print("Layer Skin paint trace attached. No plug-in reload required. Close the trace window to detach.")
    return trace


if __name__ == "__main__":
    start()
