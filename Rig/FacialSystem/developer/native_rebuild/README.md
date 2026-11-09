# Offline native reconstruction sources

The ready-to-open native scene is already bundled under
`facial_system/templates`. Rebuilding is unnecessary for fitting and animation.

To rebuild that original template from the cleaned source scene, run standard
Python from the extracted `FacialSystem` folder:

```text
python developer/native_rebuild/rebuild.py "C:\source\facialRig(1).ma" --output "C:\output\rebuilt"
```

The default behavior model is `facial_system/data/behavior.json`. The compiler
uses the original cleaned source scene as input and writes a new native Maya
ASCII scene, expressions, and manifest. It does not overwrite the open Maya rig
or require DNA to compile the already-decoded behavior. Supply your own original
cleaned scene; it is not duplicated in this package.

`dna25.py` is the original scoped binary DNA 2.5 decoder. `model.py` retains the
portable evaluator and data conversion functions. They are development sources;
the running Maya rig does not call them. Unsupported learned or twist/swing
behavior in another DNA still requires an explicit implementation.

`build_manifest.json` and `docs/reference` are historical build/audit records.
They describe the original native template, not the fitted character's neutral
positions. The combined window's Behavior Check adjusts the translation
references to the current scene constants.
