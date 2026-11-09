import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).parent / 'attachments'))
from test_core import fixture
from facial_system import core, project


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.document, _ = fixture()

    def test_project_round_trip_keeps_defaults_groups_mapping_and_reports(self):
        original = copy.deepcopy(self.document)
        mapping = {'mesh': '|Head_FitTarget|Head_FitTargetShape'}
        result = {'passed': True, 'applied_to_scene': True}
        with tempfile.TemporaryDirectory() as folder:
            path = project.save(folder, self.document, mapping,
                                scene=str(Path(folder) / 'scenes/character.ma'), fit_result=result, current_step=2)
            loaded = project.load(path)
            self.assertEqual(loaded['document'], original)
            self.assertEqual(loaded['mapping'], mapping)
            self.assertEqual(loaded['reports']['fit_result'], result)
            self.assertTrue(loaded['reports_match_data'])
            self.assertEqual(loaded['manifest']['current_step'], 2)
            self.assertEqual(self.document, original)

    def test_relative_data_and_scene_paths_survive_moving_project(self):
        with tempfile.TemporaryDirectory() as folder:
            old = Path(folder) / 'old'
            new = Path(folder) / 'new'
            project.save(old, self.document, {}, scene=str(old / 'scenes/character.ma'))
            shutil.move(str(old), str(new))
            loaded = project.load(new)
            self.assertEqual(Path(loaded['scene']), new / 'scenes/character.ma')
            self.assertTrue(Path(loaded['neutral_path']).is_file())

    def test_invalid_mapping_does_not_write_a_project(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                project.save(folder, self.document, {'missing': 'target'})
            self.assertFalse((Path(folder) / project.PROJECT_FILE).exists())

    def test_manifest_write_failure_preserves_previous_complete_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'manifest.json'
            project.write_json(path, {'old': True})
            with mock.patch.object(project.os, 'replace', side_effect=OSError('disk error')):
                with self.assertRaises(OSError):
                    project.write_json(path, {'new': True})
            self.assertEqual(json.loads(path.read_text()), {'old': True})
            self.assertEqual([p.name for p in Path(folder).iterdir()], ['manifest.json'])

    def test_changed_attachment_data_invalidates_saved_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            path = project.save(folder, self.document, {}, fit_result={'passed': True})
            edited = core.load(Path(folder) / 'data/driveNeutralData.json')
            edited['joints'][0]['group_name'] = 'edited_group'
            core.save(edited, Path(folder) / 'data/driveNeutralData.json')
            loaded = project.load(path)
            self.assertFalse(loaded['reports_match_data'])
            self.assertEqual(loaded['reports'], {})

    def test_timestamps_do_not_invalidate_fitting_fingerprint(self):
        first = project.data_fingerprint(self.document, {})
        self.document['updated_utc'] = 'later'
        self.assertEqual(first, project.data_fingerprint(self.document, {}))

    def test_cage_data_and_stable_step_id_round_trip(self):
        from test_cage_core import cage_fixture
        layer = cage_fixture()
        with tempfile.TemporaryDirectory() as folder:
            path = project.save(folder, self.document, {}, current_step=2,
                                current_step_id='wrap', wrap_data=layer)
            loaded = project.load(path)
            self.assertEqual(loaded['wrap_data'], layer)
            self.assertEqual(loaded['manifest']['current_step_id'], 'wrap')
            self.assertEqual(loaded['manifest']['current_step'], 2)

    def test_legacy_project_without_cage_data_still_loads(self):
        with tempfile.TemporaryDirectory() as folder:
            path = project.save(folder, self.document, {}, current_step=3)
            loaded = project.load(path)
            self.assertIsNone(loaded['wrap_data'])
            self.assertNotIn('current_step_id', loaded['manifest'])


if __name__ == '__main__':
    unittest.main()
