"""Portable checks for explicit backend boundaries; not native Windows acceptance."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


PACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACK / "lib"))
import apply_antigravity_setup as publisher
import shared_core_skills as skills
import validate_project_config as config
import windows_bootstrap as bootstrap
import windows_fs
from platform_fs import os as platform_os


class Backend:
    def __getattr__(self, name):
        return getattr(platform_os, name)


class DirectoryEnumerationTest(unittest.TestCase):
    def test_exhaustion_and_failed_iteration_release_owned_directory_once(self):
        for failed in (False, True):
            owner = Mock()
            def entries():
                yield "first"
                if failed:
                    raise OSError("enumeration failed")
            iterator = windows_fs._Entries(entries(), owner)
            with self.subTest(failed=failed):
                if failed:
                    with self.assertRaisesRegex(OSError, "enumeration failed"):
                        list(iterator)
                else:
                    self.assertEqual(list(iterator), ["first"])
                owner.close.assert_called_once_with()
                iterator.close()
                owner.close.assert_called_once_with()

    def test_early_context_exit_stops_iteration_and_close_is_idempotent(self):
        owner = Mock()
        with windows_fs._Entries(["first", "second"], owner) as iterator:
            self.assertEqual(next(iterator), "first")
        self.assertEqual(list(iterator), [])
        iterator.close()
        owner.close.assert_called_once_with()

    def test_borrowed_directory_iterator_does_not_own_callers_handle(self):
        iterator = windows_fs._Entries(["first"])
        self.assertEqual(list(iterator), ["first"])
        iterator.close()
        self.assertIsNone(iterator.directory)


class SkillBackendBoundaryTest(unittest.TestCase):
    def test_inventory_and_journal_read_through_checked_descriptors(self):
        for name, validator, label in (
            ("_read_inventory", "_validate_inventory_object", "Managed Skill state"),
            ("_read_transaction", "_validate_transaction_object", "Managed Skill transaction"),
        ):
            path = Path("state.json")
            with self.subTest(reader=name), patch.object(skills, "_require_regular_file"), \
                    patch.object(skills, "_read_regular_path", return_value=b'{}') as read, \
                    patch.object(skills, validator, return_value="validated") as validate:
                self.assertEqual(getattr(skills, name)(path, "xy-workflow"), "validated")
                read.assert_called_once_with(path, label)
                validate.assert_called_once_with({}, "xy-workflow")

    def test_content_read_rejects_hardlink_swapped_after_metadata_check(self):
        require = skills._require_regular_file
        for name in ("_read_inventory", "_read_transaction"):
            with self.subTest(reader=name), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                path, external = root / "state.json", root / "external.json"
                path.write_bytes(b"{}")
                external.write_bytes(b"{}")
                def checked_then_swapped(checked, label):
                    info = require(checked, label)
                    checked.unlink()
                    os.link(external, checked)
                    return info
                with patch.object(skills, "_require_regular_file", side_effect=checked_then_swapped), \
                        self.assertRaises(skills.SharedCoreSkillError):
                    getattr(skills, name)(path, "xy-workflow")
                self.assertEqual(external.read_bytes(), b"{}")

    def test_staging_snapshot_creates_all_directories_through_backend(self):
        snapshot = SimpleNamespace(name="xy-workflow", nodes=(("references", "directory"),), files=())
        with tempfile.TemporaryDirectory() as raw:
            staging = Path(raw)
            backend = Backend()
            backend.mkdir = Mock()
            with patch.object(skills, "os", backend), \
                    patch.object(skills, "_load_shared_core_skills", return_value=((snapshot.name,), (snapshot,))), \
                    patch.object(skills, "_require_empty_staging_root"):
                self.assertEqual(skills.stage_shared_core_skills(PACK, staging), (snapshot.name,))
            self.assertEqual([call.args[0] for call in backend.mkdir.call_args_list],
                             [staging / snapshot.name, staging / snapshot.name / "references"])
            self.assertFalse((staging / snapshot.name).exists())

    def test_sync_stage_creation_cannot_bypass_backend(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "xy-workflow"
            backend = Backend()
            backend.mkdir = Mock(side_effect=OSError("checked mkdir refused"))
            with patch.object(skills, "os", backend), \
                    patch.object(skills, "_validated_source_tree", return_value={}), \
                    patch.object(skills, "_source_inventory", return_value={}), \
                    patch.object(skills, "_path_exists_without_following", return_value=False), \
                    patch.object(skills, "_write_json_atomically"), \
                    self.assertRaisesRegex(OSError, "checked mkdir refused"):
                skills.sync_skill_tree(root / "source", target, target.name)
            backend.mkdir.assert_called_once()
            self.assertEqual(list(root.iterdir()), [])


class AntigravityCandidateTest(unittest.TestCase):
    def test_windows_publication_prepares_candidate_on_project_volume(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            project, staging = root / "project", root / "external-temp"
            project.mkdir()
            staging.mkdir()
            candidate = staging / "candidate"
            (candidate / "references").mkdir(parents=True)
            (candidate / "SKILL.md").write_bytes(b"managed fixture\n")
            (candidate / "references/r.md").write_bytes(b"reference\n")
            target = project / "skills/xy-workflow"
            target.parent.mkdir()
            plan = publisher.Plan(PACK, project, staging, "fixture-nonce")
            change = publisher.DirectoryChange(target, candidate, publisher.Fingerprint("missing"), None)
            backend = Backend()
            backend.name = "nt"
            def rename(source, destination):
                # Model a system-temp volume that cannot be renamed into the project.
                self.assertEqual(source.parent, target.parent)
                os.rename(source, destination)
            backend.rename = Mock(side_effect=rename)
            with patch.object(publisher, "os", backend), \
                    patch.object(windows_fs, "flush_tree") as flush:
                publisher._publish_directory(change, plan)
            backend.rename.assert_called_once_with(change.candidate, target)
            flush.assert_called_once_with(change.candidate)
            self.assertTrue(candidate.is_dir())
            self.assertEqual((target / "SKILL.md").read_bytes(), b"managed fixture\n")
            self.assertEqual((target / "references/r.md").read_bytes(), b"reference\n")
            self.assertFalse(change.candidate.exists())

    def test_failed_candidate_copy_never_moves_existing_target(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            target = root / "skills/xy-workflow"
            target.mkdir(parents=True)
            (target / "user.txt").write_bytes(b"preserve\n")
            plan = publisher.Plan(PACK, root, root, "fixture-nonce")
            before = publisher._fingerprint(target, read_file=False)
            change = publisher.DirectoryChange(target, root / "source", before,
                                               publisher._tree_fingerprint(target))
            backend = Backend()
            backend.name = "nt"
            backend.rename = Mock()
            backend.replace = Mock()
            with patch.object(publisher, "os", backend), \
                    patch.object(publisher, "_copy_managed_tree", side_effect=OSError("copy refused")), \
                    self.assertRaisesRegex(OSError, "copy refused"):
                publisher._publish_directory(change, plan)
            backend.rename.assert_not_called()
            backend.replace.assert_not_called()
            self.assertEqual((target / "user.txt").read_bytes(), b"preserve\n")


class TypedMountPathTest(unittest.TestCase):
    def test_git_mount_conversion_uses_verified_git_tool_only_for_typed_paths(self):
        original = {"AGENT_WORKFLOW_BASH": r"C:\Program Files\Git\bin\bash.exe", "PATH": "caller-path"}
        backend = SimpleNamespace(name="nt", environ=original)
        run = Mock(return_value=subprocess.CompletedProcess([], 0, "D:/Git temp/项目\n", ""))
        argv = ["-c", "/tmp/项目", '/tmp/regex|{"path":"/tmp/json"}', "/c/project"]
        with patch.object(bootstrap, "os", backend), \
                patch.object(bootstrap, "subprocess", SimpleNamespace(run=run, SubprocessError=subprocess.SubprocessError)):
            result = bootstrap._convert(argv, (1, 3))
        self.assertEqual(result, ["-c", "D:/Git temp/项目", argv[2], "C:/project"])
        command = run.call_args.args[0]
        self.assertEqual(command, [r"C:\Program Files\Git\usr\bin\cygpath.exe", "-am", "--", "/tmp/项目"])
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(original, {"AGENT_WORKFLOW_BASH": r"C:\Program Files\Git\bin\bash.exe", "PATH": "caller-path"})

    def test_mount_path_requires_explicit_verified_git_and_rejects_remote_result(self):
        for environment, output in (({}, "C:/tmp"),
                                    ({"AGENT_WORKFLOW_BASH": r"C:\Git\bin\bash.exe"}, "//server/share/tmp\n")):
            with self.subTest(environment=environment), \
                    patch.object(bootstrap, "os", SimpleNamespace(name="nt", environ=environment)), \
                    patch.object(bootstrap, "subprocess", SimpleNamespace(run=Mock(
                        return_value=subprocess.CompletedProcess([], 0, output, "")), SubprocessError=subprocess.SubprocessError)), \
                    self.assertRaises(ValueError):
                bootstrap._native_path("/tmp/fixture")

    def test_failed_tool_never_falls_back_to_path_search_or_unconverted_input(self):
        environment = {"AGENT_WORKFLOW_BASH": r"C:\Git\usr\bin\bash.exe"}
        for failure in (FileNotFoundError("missing cygpath"), subprocess.TimeoutExpired("cygpath", 10)):
            run = Mock(side_effect=failure)
            with self.subTest(failure=type(failure).__name__), \
                    patch.object(bootstrap, "os", SimpleNamespace(name="nt", environ=environment)), \
                    patch.object(bootstrap, "subprocess", SimpleNamespace(
                        run=run, SubprocessError=subprocess.SubprocessError)), \
                    self.assertRaisesRegex(ValueError, "cannot convert typed Git mount path"):
                bootstrap._native_path("/tmp/fixture")
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0][0], r"C:\Git\usr\bin\cygpath.exe")

    def test_invalid_converter_status_or_output_is_rejected(self):
        environment = {"AGENT_WORKFLOW_BASH": r"C:\Git\bin\bash.exe"}
        for status, output in ((1, "C:/tmp\n"), (0, ""), (0, "relative/path\n"),
                               (0, "C:/one\nC:/two\n"), (0, "C:/nul\0name\n")):
            with self.subTest(status=status, output=output), \
                    patch.object(bootstrap, "os", SimpleNamespace(name="nt", environ=environment)), \
                    patch.object(bootstrap, "subprocess", SimpleNamespace(
                        run=Mock(return_value=subprocess.CompletedProcess([], status, output, "")),
                        SubprocessError=subprocess.SubprocessError)), self.assertRaises(ValueError):
                bootstrap._native_path("/tmp/fixture")


class ConfigurationReadTest(unittest.TestCase):
    def test_native_configuration_content_uses_secure_read_before_validation(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            path = root / "project.yaml"
            with patch.object(config, "os", SimpleNamespace(name="nt"), create=True), \
                    patch.object(windows_fs, "read_file", return_value=b"project_name: fixture\n") as read, \
                    patch.object(config, "hook_mode", side_effect=RuntimeError("validation reached")), \
                    self.assertRaisesRegex(RuntimeError, "validation reached"):
                config.validate_with_profile(path, root, root / "roles")
            read.assert_called_once_with(path)


if __name__ == "__main__":
    unittest.main()
