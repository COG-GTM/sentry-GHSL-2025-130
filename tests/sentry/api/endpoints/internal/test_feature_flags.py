from __future__ import annotations

import os
import shutil
import tempfile
from unittest import mock

from django.test import override_settings
from django.urls import reverse

from sentry.testutils.cases import APITestCase

FLAG = "organizations:device-classification"


class InternalFeatureFlagsTest(APITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.path = reverse("sentry-api-0-internal-feature-flags")
        self.login_as(user=self.create_user(is_superuser=True), superuser=True)

    def write_config(self) -> str:
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir)
        py = os.path.join(tmpdir, "sentry.conf.py")
        with open(py, "w") as f:
            f.write("SENTRY_OPTIONS = {}\n")
        return py

    @override_settings(SENTRY_SELF_HOSTED=True)
    def test_writes_normalized_boolean(self) -> None:
        py = self.write_config()
        with (
            mock.patch(
                "sentry.api.endpoints.internal.feature_flags.discover_configs",
                return_value=(os.path.dirname(py), py, None),
            ),
            mock.patch("sentry.api.endpoints.internal.feature_flags.configure"),
        ):
            response = self.client.put(self.path, data={FLAG: "true"}, format="json")

        assert response.status_code == 200
        with open(py) as f:
            contents = f.read()
        assert f"SENTRY_FEATURES[{FLAG!r}]=True\n" in contents

    @override_settings(SENTRY_SELF_HOSTED=True)
    def test_rejects_python_code_injection(self) -> None:
        py = self.write_config()
        with (
            mock.patch(
                "sentry.api.endpoints.internal.feature_flags.discover_configs",
                return_value=(os.path.dirname(py), py, None),
            ),
            mock.patch("sentry.api.endpoints.internal.feature_flags.configure"),
        ):
            response = self.client.put(
                self.path,
                data={FLAG: "False\nimport os; os.system('touch /tmp/pwned')"},
                format="json",
            )

        assert response.status_code == 400
        with open(py) as f:
            contents = f.read()
        assert "os.system" not in contents
        assert "SENTRY_FEATURES" not in contents
