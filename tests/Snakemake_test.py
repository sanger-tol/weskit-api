import json, yaml, pytest
from ga4gh.wes.utils import create_run_id


@pytest.mark.skip(reason="architectural decision pending")
def test_post_run(snakemake_executor, database_connection):
    with open("tests/wf1/config.yaml") as file:
        workflow_params = json.dumps(yaml.load(file, Loader=yaml.FullLoader))
    
    data = {
        "workflow_params": workflow_params,
        "workflow_type": "Snakemake",
        "workflow_type_version": "5.8.2",
        "workflow_url": "tests/wf1/Snakefile"
    }

    run = database_connection.create_new_run(create_run_id(), request=data)
    _, status_code = snakemake_executor.execute(run, database_connection)
    assert status_code == 200
