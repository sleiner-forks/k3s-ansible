#!/usr/bin/env python3

# Perform a few tests on a cluster created with this playbook.
# To simplify test execution, the scripts does not depend on any third-party
# packages, only the Python standard library.

import json
import subprocess
import unittest
from pathlib import Path
from time import sleep
from urllib.request import urlopen
from warnings import warn


VAGRANT_DIR = Path(__file__).parent.absolute()
PLAYBOOK_DIR = VAGRANT_DIR.parent.absolute()


class TestK3sCluster(unittest.TestCase):
    def _kubectl(self, args: str, json_out: bool = True) -> dict | None:
        cmd = "kubectl"
        if json_out:
            cmd += " -o json"
        cmd += f" {args}"

        result = subprocess.run(cmd, capture_output=True, shell=True)

        # Catch errors
        if result.stderr:
            warn(f'Output of "{cmd}":\n{result.stderr}')
        self.assertEqual(result.returncode, 0)

        if json_out:
            return json.loads(result.stdout)
        else:
            return None

    def _apply_manifest(self, manifest_file: Path) -> dict:
        apply_result = self._kubectl(
            f'apply --filename="{manifest_file}" --cascade="background"'
        )
        self.addCleanup(
            lambda: self._kubectl(
                f'delete --filename="{manifest_file}"',
                json_out=False,
            )
        )
        return apply_result

    @staticmethod
    def _retry(function, retries: int = 5, seconds_between_retries=1):
        for retry in range(1, retries + 1):
            try:
                return function()
            except Exception as exc:
                if retry < retries:
                    sleep(seconds_between_retries)
                    continue
                else:
                    raise exc

    def _get_load_balancer_ip(
        self,
        service: str,
        namespace: str = "default",
    ) -> str | None:
        svc_description = self._kubectl(
            f'get --namespace="{namespace}" service "{service}"'
        )
        ip = svc_description["status"]["loadBalancer"]["ingress"][0]["ip"]
        return ip

    def test_nodes_exist(self):
        out = self._kubectl("get nodes")
        node_names = {item["metadata"]["name"] for item in out["items"]}
        self.assertEqual(
            node_names,
            {"control1", "control2", "control3", "node1", "node2"},
        )

    def test_nginx_example_page(self):
        # Deploy the manifests to the cluster
        deployment = self._apply_manifest(PLAYBOOK_DIR / "example" / "deployment.yml")
        service = self._apply_manifest(PLAYBOOK_DIR / "example" / "service.yml")

        # Assert that the dummy page is available
        metallb_ip = self._retry(
            lambda: self._get_load_balancer_ip(service["metadata"]["name"])
        )
        metallb_port = service["spec"]["ports"][0]["port"]

        def get_nginx_page():
            with urlopen(f"http://{metallb_ip}:{metallb_port}/", timeout=1) as response:
                return response.read().decode("utf8")

        response_body = self._retry(get_nginx_page)
        self.assertIn("Welcome to nginx!", response_body)


if __name__ == "__main__":
    unittest.main()
