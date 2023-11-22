#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


import asyncio
import logging
from pathlib import Path

import pytest
import requests
import yaml
from helpers import get_unit_address, run_juju_ssh_command
from pytest_operator.plugin import OpsTest
import json

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]

ssc_app_name = "ssc"
alert_app_name = "alertmanager-k8s"

app_names = [APP_NAME, ssc_app_name]


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    # Given a fresh build of the charm
    # When deploying it
    # Then it should eventually go idle/active

    charm = await ops_test.build_charm(".")
    resources = {
        "catalogue-image": METADATA["resources"]["catalogue-image"]["upstream-source"]}
    await ops_test.model.deploy(charm, resources=resources, application_name=APP_NAME)

    # issuing dummy update_status just to trigger an event
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="active",
            raise_on_blocked=True,
            timeout=1000,
        )

    assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"


async def test_tls(ops_test: OpsTest):
    await asyncio.gather(
        ops_test.model.deploy(
            "ch:self-signed-certificates",
            application_name=ssc_app_name,
            channel="edge",
            trust=True,
        ),
    )
    await ops_test.model.add_relation(APP_NAME, ssc_app_name)
    await ops_test.model.wait_for_idle(apps=app_names, status="active")

    address = await get_unit_address(ops_test, APP_NAME, 0)
    url = f"https://{address}/"
    response = requests.get(url, verify=False)
    assert response.status_code == 200


async def test_app_integration(ops_test: OpsTest):
    await asyncio.gather(
        ops_test.model.deploy(
            alert_app_name,
            application_name=alert_app_name,
            channel="1.0/stable",
            trust=True,
        ),
    )

    await ops_test.model.integrate(f"{APP_NAME}", alert_app_name)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, alert_app_name], status="active", raise_on_blocked=True, timeout=1000
    )
    # retrieve the content of /web/config.json which holds application data in the catalogue
    new_config = await run_juju_ssh_command(model_full_name=ops_test.model_full_name,
                                      container_name="catalogue",
                                      unit_name= f"{APP_NAME}/0",
                                      command="cat /web/config.json",)
    config_dict = json.loads(new_config)
    first_app_name = config_dict['apps'][0]['name']
    assert first_app_name == 'Alertmanager'