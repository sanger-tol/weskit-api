import json
import time
import yaml
import os


def get_workflow_data(workflow_file, config):
    with open(config) as file:
        workflow_params = json.dumps(yaml.load(file, Loader=yaml.FullLoader))

    data = {
        "workflow_params": workflow_params,
        "workflow_type": "snakemake",
        "workflow_type_version": "5.8.2",
        "workflow_url": workflow_file
    }
    return data


def test_get_service_info(test_app):
    response = test_app.get("/ga4gh/wes/v1/service-info")
    assert response.status_code == 200
    

def test_login_restriction(test_app):
    snakefile = os.path.join(os.getcwd(), "tests/wf1/Snakefile")
    data = get_workflow_data(
        workflow_file=snakefile,
        config="tests/wf1/config.yaml")
    response = test_app.post("/ga4gh/wes/v1/runs", data=data)
    assert response.status_code == 401


def test_login(test_app):
    login_data = {'password': 'test', 'username': 'test'}
    response = test_app.post("/login", data=login_data)
    assert response.status == '302 FOUND'


# WARNING: This test fails with 401 unauthorized, if run isolated.
#          Run it together with the other server_test.py tests!
def test_run_snakemake(test_app):
    snakefile = os.path.join(os.getcwd(), "tests/wf1/Snakefile")
    data = get_workflow_data(
        workflow_file=snakefile,
        config="tests/wf1/config.yaml")
    response = test_app.post("/ga4gh/wes/v1/runs", data=data)
    assert response.status_code == 200
    run_id = response.json["run_id"]
    running = True
    while running:
        time.sleep(1)
        print("Waiting for workflow to finish ...")
        status = test_app.get(
            "/ga4gh/wes/v1/runs/{}/status".format(run_id)
        )
        if status.json in ["UNKNOWN", "EXECUTOR_ERROR", "SYSTEM_ERROR",
                           "CANCELED", "CANCELING"]:
            assert False, "Failing run status '{}'".format(status.json)
        elif status.json == "COMPLETE":
            running = False  # = success


def test_get_runs(test_app):
    response = test_app.get("/ga4gh/wes/v1/runs")
    assert response.status_code == 200


def test_logout(test_app):
    login_data=dict()
    response=test_app.post("/logout",data=login_data)
    assert response.status == '200 OK'


def test_logout_successfull(test_app):
    snakefile = os.path.join(os.getcwd(), "tests/wf1/Snakefile")
    data = get_workflow_data(
        workflow_file=snakefile,
        config="tests/wf1/config.yaml")
    response = test_app.post("/ga4gh/wes/v1/runs", data=data)
    assert response.status_code == 401
