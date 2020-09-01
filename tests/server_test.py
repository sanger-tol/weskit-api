import json
import time
import yaml


def test_get_list_runs(test_app):
    response = test_app.get("/ga4gh/wes/v1/runs")
    assert response.status_code == 200


def test_get_service_info(test_app):
    response = test_app.get("/ga4gh/wes/v1/service-info")
    assert response.status_code == 200
    assert response.json == {
        'auth_instructions_url': 'https://somewhere.org',
        'contact_info_url': 'your@email.de',
        'default_workflow_engine_parameters': [{
            'default_value': '1',
            'name': 'cores',
            'type': 'int'
        }],
        'supported_filesystem_protocols': ['s3', 'posix'],
        'supported_wes_versions': ['1.0.0'],
        'system_state_counts': {
            'CANCELED': 0,
            'CANCELING': 0,
            'COMPLETE': 0,
            'EXECUTOR_ERROR': 0,
            'INITIALIZING': 0,
            'PAUSED': 0,
            'QUEUED': 0,
            'RUNNING': 0,
            'SYSTEM_ERROR': 0,
            'UNKNOWN': 0
        },
        'tags': {'tag1': 'value1', 'tag2': 'value2'},
        'workflow_engine_versions': {'Snakemake': '5.8.2'},
        'workflow_type_versions': {
            'Snakemake': {"workflow_type_version": ['5']}
        }
    }


def get_workflow_data(snakefile, config):
    with open(config) as file:
        workflow_params = json.dumps(yaml.load(file, Loader=yaml.FullLoader))

    data = {
        "workflow_params": workflow_params,
        "workflow_type": "Snakemake",
        "workflow_type_version": "5.8.2",
        "workflow_url": snakefile
    }
    return data


def test_run_workflow(test_app, celery_worker):
    data = get_workflow_data(
        snakefile="tests/wf1/Snakefile",
        config="tests/wf1/config.yaml")
    response = test_app.post("/ga4gh/wes/v1/runs", data=data)
    run_id = response.json["run_id"]
    running = True
    while running:
        time.sleep(1)
        status = test_app.get(
            "/ga4gh/wes/v1/runs/{}/status".format(run_id)
        )
        if (status.json == "COMPLETE"):
            running = False
    assert response.status_code == 200


def test_cancel_workflow(test_app, celery_worker):
    data = get_workflow_data(
        snakefile="tests/wf2/Snakefile",
        config="tests/wf2/config.yaml")
    response = test_app.post("/ga4gh/wes/v1/runs", data=data)
    run_id = response.json["run_id"]
    cancel_run = test_app.post("/ga4gh/wes/v1/runs/{}/cancel".format(run_id))
    assert cancel_run.status_code == 200
    status = test_app.get("/ga4gh/wes/v1/runs/{}/status".format(run_id))
    print(status.json)
    assert status.json == "CANCELED"
