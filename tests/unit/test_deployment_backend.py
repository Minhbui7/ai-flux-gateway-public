"""Offline backend/region regressions; also runnable using stdlib unittest only."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.deployment.launcher import (
    ATTESTATIONS,
    ROOT,
    DeploymentError,
    Launcher,
    load_config,
    read_json,
    write_json,
)


class DeploymentBackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "source"
        for root in ("terraform", "models"):
            (self.root / "infra" / root).mkdir(parents=True)
            (self.root / "infra" / root / "versions.tf").write_text('terraform { backend "azurerm" {} }\n')
        self.directory = self.base / "environment"
        self.directory.mkdir()
        self.config = read_json(ROOT / "infra/deployment/customer.example.json")
        for index, key in enumerate(
            ("tenant_id", "subscription_id", "bootstrap_object_id", "sql_admin_object_id"), 1
        ):
            self.config[key] = f"00000000-0000-0000-0000-{index:012d}"
        self.config.update(
            location="southeastasia",
            sql_location="southeastasia",
            operator_ip="8.8.8.8",
            dns_label="customer-pilot",
        )
        self.config["attestations"] = dict.fromkeys(ATTESTATIONS, True)
        self.backend = {
            "resource_group_name": "backend-rg",
            "storage_account_name": "existingstate",
            "container_name": "tfstate",
            "main_key": self.config["name_prefix"] + "/main.tfstate",
            "models_key": self.config["name_prefix"] + "/models.tfstate",
        }
        self.config["backend"] = self.backend
        self.commands = []
        self.exists = False
        self.fail = False
        self.data_dirs = []
        self.overrides = []
        self.patcher = patch("scripts.deployment.launcher.ROOT", self.root)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.launcher = Launcher(self.config, self.directory, self.run_command)
        self.launcher.preflight = lambda: None
        self.launcher.source_fingerprint = lambda: "source-v1"

    def run_command(self, args, *, json_output=True):
        self.commands.append(args)
        if args[0] == "az":
            return {"exists": self.exists}
        root = Path(args[1].removeprefix("-chdir="))
        override = root / "backend_override.tf"
        self.overrides.append(override.read_text() if override.exists() else None)
        self.data_dirs.append(os.environ["TF_DATA_DIR"])
        if self.fail:
            raise DeploymentError("simulated Terraform failure")
        if args[2] == "plan":
            Path(next(arg[5:] for arg in args if arg.startswith("-out="))).write_bytes(b"saved-plan")
        if args[2] == "show":
            return {"resource_changes": []}
        return {} if json_output else b""

    def validate(self):
        path = self.directory / "config.json"
        write_json(path, self.config)
        return load_config(path)

    def test_australian_models_use_distinct_remote_key_and_profile_binding(self):
        self.config.update(deployment_profile="australiaeast-luna", sql_location="australiaeast")
        self.config.pop("location")
        model_root = self.root / "infra" / "models-australiaeast"
        model_root.mkdir()
        (model_root / "main.tf").write_text('terraform { backend "azurerm" {} }\n')
        self.validate()
        self.launcher.tf("terraform", "init", "-input=false")
        self.launcher.tf("models-australiaeast", "init", "-input=false")
        content = (self.directory / "models-australiaeast.backend.hcl").read_text()
        self.assertIn('key = "' + self.backend["models_key"] + '"', content)
        self.assertNotIn('key = "' + self.backend["main_key"] + '"', content)
        self.config["deployment_profile"] = "legacy"
        with self.assertRaisesRegex(DeploymentError, "binding changed"):
            self.launcher.tf("terraform", "output", "-json")

    def test_southeastasia_keeps_models_and_security(self):
        self.validate()
        values = self.launcher.main_inputs("prerequisites")
        self.assertEqual(values["location"], "southeastasia")
        self.assertEqual(values["model_location"], "eastus")
        self.assertEqual(values["sql_location"], "southeastasia")
        self.assertEqual(self.launcher.hostname, "customer-pilot.southeastasia.cloudapp.azure.com")
        self.assertTrue(values["hybrid_private_data_enabled"])
        for name in ("sql", "key_vault", "function_storage"):
            self.assertFalse(values[name + "_public_network_access_enabled"])
        self.assertNotIn("dev_openai_inference_enabled", values)
        with patch("scripts.deployment.launcher.ROOT", ROOT):
            catalog = self.launcher.catalog()
        self.assertEqual(
            {backend["region"] for model in catalog["models"] for backend in model["backends"]},
            {"eastus", "swedencentral"},
        )

    def test_invalid_region_and_backend_inputs_fail_closed(self):
        mutations = (
            {"location": "swedencentral"},
            {"model_location": "southeastasia"},
            {"sql_location": "unknown"},
            {"backend": None},
            {"backend": {**self.backend, "access_key": "not-allowed"}},
            {"backend": {**self.backend, "container_name": "other"}},
            {"backend": {**self.backend, "storage_account_name": "invalid-account"}},
            {"backend": {**self.backend, "models_key": self.backend["main_key"]}},
            {"backend": {**self.backend, "main_key": "other/main.tfstate"}},
            {"backend": {**self.backend, "main_key": self.config["name_prefix"] + "/../main.tfstate"}},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), patch.dict(self.config, mutation):
                with self.assertRaises(DeploymentError):
                    self.validate()
        self.assertEqual(self.commands, [])

    def test_remote_init_plan_apply_and_outputs_use_distinct_backends(self):
        approval = self.launcher.plan("prerequisites")
        self.launcher.apply("prerequisites", approval)
        self.launcher.outputs()
        self.launcher.tf("models", "init", "-input=false")
        main = (self.directory / "terraform.backend.hcl").read_text()
        models = (self.directory / "models.backend.hcl").read_text()
        self.assertIn('key = "' + self.backend["main_key"] + '"', main)
        self.assertIn('key = "' + self.backend["models_key"] + '"', models)
        for content in (main, models):
            self.assertIn("use_azuread_auth = true", content)
            self.assertIn("use_cli = true", content)
            self.assertNotIn("access_key", content)
        terraform = [command for command in self.commands if command[0] == "terraform"]
        self.assertTrue(any(command[2] == "apply" for command in terraform))
        self.assertTrue(any(command[2] == "output" for command in terraform))
        for command in terraform:
            self.assertFalse(
                any(arg.startswith(("-state", "-migrate-state", "-force-copy")) for arg in command)
            )
        self.assertEqual(set(self.overrides), {None})
        self.assertEqual(
            set(self.data_dirs), {str(self.directory / "terraform-data"), str(self.directory / "models-data")}
        )
        self.assertFalse(any(self.root.glob("infra/*/backend_override.tf")))
        self.assertNotIn("TF_DATA_DIR", os.environ)
        blobs = [command for command in self.commands if command[0] == "az"]
        self.assertEqual(len(blobs), 2)
        for command in blobs:
            self.assertIn("login", command)
            self.assertIn(self.config["subscription_id"], command)

    def test_declared_remote_backends_do_not_get_duplicate_overrides(self):
        for root in ("terraform", "models"):
            (self.root / "infra" / root / "versions.tf").write_text('terraform { backend "azurerm" {} }\n')
        self.launcher.tf("terraform", "init", "-input=false")
        self.launcher.tf("models", "init", "-input=false")
        terraform = [command for command in self.commands if command[0] == "terraform"]
        self.assertEqual(len(terraform), 2)
        self.assertEqual(set(self.overrides), {None})
        for command in terraform:
            self.assertTrue(any(arg.startswith("-backend-config=") for arg in command))
        self.assertFalse(any(self.root.glob("infra/*/backend_override.tf")))

    def test_declared_remote_root_rejects_missing_backend_configuration(self):
        del self.config["backend"]
        (self.root / "infra/terraform/versions.tf").write_text('terraform { backend "azurerm" {} }\n')
        with self.assertRaisesRegex(DeploymentError, "Azure Blob backend"):
            self.launcher.tf("terraform", "init", "-input=false")
        self.assertEqual(self.commands, [])

    def test_local_mode_is_refused(self):
        del self.config["backend"]
        self.validate()
        with self.assertRaisesRegex(DeploymentError, "Azure Blob backend"):
            self.launcher.tf("terraform", "init", "-input=false")
        self.assertEqual(self.commands, [])

    def test_existing_remote_state_is_not_adopted(self):
        self.exists = True
        with self.assertRaisesRegex(DeploymentError, "adoption"):
            self.launcher.tf("terraform", "init", "-input=false")
        self.assertFalse((self.directory / "backend-binding.json").exists())
        self.assertFalse(any(command[0] == "terraform" for command in self.commands))

    def test_existing_local_state_and_metadata_are_not_migrated(self):
        for relative in ("main.tfstate", "models.tfstate.backup", "terraform-data/terraform.tfstate"):
            path = self.directory / relative
            path.parent.mkdir(exist_ok=True)
            path.write_text("existing")
            with self.subTest(relative=relative), self.assertRaisesRegex(DeploymentError, "migration"):
                self.launcher.tf("terraform", "init", "-input=false")
            path.unlink()
        self.assertEqual(self.commands, [])

    def test_changed_backend_binding_is_refused(self):
        self.launcher.tf("terraform", "init", "-input=false")
        self.backend["main_key"] = self.config["name_prefix"] + "/changed.tfstate"
        with self.assertRaisesRegex(DeploymentError, "binding changed"):
            self.launcher.tf("terraform", "init", "-input=false")

    def test_override_collision_is_never_overwritten_or_deleted(self):
        for name in ("backend_override.tf", "custom_override.tf", "override.tf.json"):
            override = self.root / "infra/terraform" / name
            override.write_text("customer-owned")
            with self.subTest(name=name), self.assertRaisesRegex(DeploymentError, "collision"):
                self.launcher.tf("terraform", "init", "-input=false")
            self.assertEqual(override.read_text(), "customer-owned")
            override.unlink()
        self.assertEqual(self.commands, [])

    def test_override_and_environment_cleanup_on_failure(self):
        os.environ["TF_DATA_DIR"] = "previous"
        self.fail = True
        with self.assertRaisesRegex(DeploymentError, "simulated"):
            self.launcher.tf("terraform", "init", "-input=false")
        self.assertFalse(any(self.root.glob("infra/*/backend_override.tf")))
        self.assertEqual(os.environ["TF_DATA_DIR"], "previous")
        self.assertFalse((self.root / ".deployment/terraform-root-lock/deployment.lock").exists())

    def test_credential_or_workspace_injection_is_refused(self):
        for name in (
            "ARM_ACCESS_KEY",
            "ARM_SAS_TOKEN",
            "ARM_CLIENT_SECRET",
            "TF_CLI_ARGS_init",
            "TF_WORKSPACE",
        ):
            with self.subTest(name=name), patch.dict(os.environ, {name: "unexpected"}):
                with self.assertRaisesRegex(DeploymentError, "overrides"):
                    self.launcher.tf("terraform", "init", "-input=false")
        self.assertEqual(self.commands, [])

    def test_location_invalidates_image_and_saved_plan_bindings(self):
        self.launcher.identity = lambda: {}
        before = self.launcher.build_fingerprint()
        approval = self.launcher.plan("prerequisites")
        self.config["location"] = "eastus"
        self.assertNotEqual(before, self.launcher.build_fingerprint())
        with self.assertRaisesRegex(DeploymentError, "changed"):
            self.launcher.apply("prerequisites", approval)


if __name__ == "__main__":
    unittest.main()
