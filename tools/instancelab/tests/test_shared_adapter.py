from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from instancelab.adapters import (
    SharedRepositoryError,
    discover_shared_instances,
    find_shared_repository_root,
    load_shared_instances,
    scan_shared_instances,
    shared_repository_fingerprint,
)

from tests.test_clipp_reader import REPOSITORY_LAYOUT


class SharedRepositoryAdapterTests(unittest.TestCase):
    def test_discovers_new_instances_without_expected_counts(self):
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            synthetic = root / "data/input/syntetic_generated"
            real = root / "data/input/real_instances/New-City"
            synthetic.mkdir(parents=True)
            real.mkdir(parents=True)
            (synthetic / "instance_A.txt").write_text(
                REPOSITORY_LAYOUT, encoding="utf-8"
            )
            (synthetic / "instance_F.txt").write_text(
                REPOSITORY_LAYOUT, encoding="utf-8"
            )
            (real / "instance.txt").write_text(REPOSITORY_LAYOUT, encoding="utf-8")
            (real / "instance.solution.txt").write_text("ignored", encoding="utf-8")

            sources = discover_shared_instances(root)
            loaded = load_shared_instances(root)

        self.assertEqual(
            tuple((source.name, source.group) for source in sources),
            (
                ("instance_A", "synthetic"),
                ("instance_F", "synthetic"),
                ("New-City", "real"),
            ),
        )
        self.assertEqual(len(loaded), 3)
        self.assertTrue(all(instance.num_streets == 3 for _, instance in loaded))

    def test_rejects_folder_without_shared_layout(self):
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            with self.assertRaisesRegex(SharedRepositoryError, "not found"):
                discover_shared_instances(folder)

    def test_finds_repository_root_from_nested_directory(self):
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            nested = root / "tools/instancelab/src"
            nested.mkdir(parents=True)
            (root / "data/input").mkdir(parents=True)

            detected = find_shared_repository_root(nested)

        self.assertEqual(detected, root.resolve())

    def test_fingerprint_changes_for_added_or_modified_instance(self):
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            synthetic = root / "data/input/syntetic_generated"
            synthetic.mkdir(parents=True)
            first = synthetic / "instance_A.txt"
            first.write_text(REPOSITORY_LAYOUT, encoding="utf-8")
            original = shared_repository_fingerprint(root)

            first.write_text(REPOSITORY_LAYOUT + "\n", encoding="utf-8")
            modified = shared_repository_fingerprint(root)
            (synthetic / "instance_B.txt").write_text(
                REPOSITORY_LAYOUT,
                encoding="utf-8",
            )
            added = shared_repository_fingerprint(root)

        self.assertNotEqual(original, modified)
        self.assertNotEqual(modified, added)
        self.assertEqual(len(added), 2)

    def test_scan_keeps_valid_instances_and_reports_invalid_ones(self):
        with TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            synthetic = root / "data/input/syntetic_generated"
            synthetic.mkdir(parents=True)
            (synthetic / "instance_A.txt").write_text(
                REPOSITORY_LAYOUT,
                encoding="utf-8",
            )
            (synthetic / "instance_B.txt").write_text(
                "not a CLIPP instance",
                encoding="utf-8",
            )

            scan = scan_shared_instances(root)

        self.assertEqual([source.name for source, _ in scan.loaded], ["instance_A"])
        self.assertEqual(len(scan.failures), 1)
        self.assertEqual(scan.failures[0].source.name, "instance_B")
        self.assertIn("expected header", scan.failures[0].reason)
        self.assertNotIn(str(root), scan.failures[0].reason)


if __name__ == "__main__":
    unittest.main()
