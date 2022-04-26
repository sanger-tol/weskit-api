#!/usr/bin/env python3

#  Copyright (c) 2021. Berlin Institute of Health (BIH) and Deutsches Krebsforschungszentrum (DKFZ).
#
#  Distributed under the MIT License. Full text at
#
#      https://gitlab.com/one-touch-pipeline/weskit/api/-/blob/master/LICENSE
#
#  Authors: The WESkit Team

import logging
import os
import sys
from logging.config import dictConfig
from typing import Optional

import yaml
from celery import Celery
from flask import Flask
from pymongo import MongoClient

from weskit.api.RunRequestValidator import RunRequestValidator
from weskit.classes.Database import Database
from weskit.classes.ErrorCodes import ErrorCodes
from weskit.classes.Manager import Manager
from weskit.classes.ServiceInfo import ServiceInfo
from weskit.classes.WorflowEngineFactory import WorkflowEngineFactory
from weskit.oidc import Factory as OIDCFactory
from weskit.oidc.Login import Login
from weskit.utils import create_validator

logger = logging.getLogger(__name__)


class WESApp(Flask):
    """We make a subclass of Flask that takes the important app-global
    (~thread local) resources.
    Compare https://stackoverflow.com/a/21845744/8784544"""

    def __init__(self,
                 manager: Manager,
                 service_info: ServiceInfo,
                 request_validators: dict,
                 oidc_login: Optional[Login] = None,
                 *args, **kwargs):
        super().__init__(__name__, *args, **kwargs)
        setattr(self, 'manager', manager)
        setattr(self, 'service_info', service_info)
        setattr(self, 'request_validators', request_validators)
        setattr(self, 'oidc_login', oidc_login)


def create_celery(**kwargs):
    broker_url = os.environ.get("BROKER_URL")
    # Provide RESULT_BACKEND as lower-priority variable than the native CELERY_RESULT_BACKEND.
    backend_url = os.environ.get("CELERY_RESULT_BACKEND",
                                 os.environ.get("RESULT_BACKEND"))
    return Celery(
        app="WESkit",
        broker=broker_url,
        backend=backend_url,
        **kwargs)


def read_swagger():
    """Read the swagger file."""
    # This is hardcoded, because if it is changed, probably also quite some
    # code needs to be changed.
    swagger_file = "weskit/api/workflow_execution_service_1.0.0.yaml"
    with open(swagger_file, "r") as yaml_file:
        swagger = yaml.safe_load(yaml_file)

    return swagger


def create_database(database_url=None):
    if database_url is None:
        database_url = os.getenv("WESKIT_DATABASE_URL")
    logger.info("Connecting to %s" % database_url)
    # The connect=False postpones the creation of a connection object until the uwsgi server
    # has forked.
    return Database(MongoClient(database_url, connect=False), "WES")


def create_app(celery: Celery,
               database: Database) -> WESApp:

    if os.getenv("WESKIT_CONFIG") is not None:
        config_file = os.getenv("WESKIT_CONFIG", "")
    else:
        raise ValueError("Cannot start WESkit: Environment variable WESKIT_CONFIG is undefined")
    if os.getenv("REMOTE_CONFIG") is not None:
        remote_config_path = os.getenv("REMOTE_CONFIG", "")
    else:
        raise ValueError("Cannot start WESkit: Environment variable REMOTE_CONFIG is undefined")
    if os.getenv("NFL_TMP") is None:
        raise ValueError("Cannot start WESkit: Environment variable NFL_TMP is undefined")
    log_config_file = os.getenv(
        "WESKIT_LOG_CONFIG",
        os.path.join("config", "log-config.yaml"))

    validation_config_file = os.getenv(
        "WESKIT_VALIDATION_CONFIG",
        os.path.join("config", "validation.yaml"))

    workflows_base_dir = os.getenv(
        "WESKIT_WORKFLOWS",
        os.path.join(os.getcwd(), "workflows"))

    weskit_data = os.getenv("WESKIT_DATA", "./tmp")

    remote_validation_config = \
        os.path.join("config", "remote-config-validation.yaml")

    request_validation_config = \
        os.path.join("config", "request-validation.yaml")

    with open(log_config_file, "r") as yaml_file:
        log_config = yaml.safe_load(yaml_file)
        dictConfig(log_config)
        logger.info("Read log config from " + log_config_file)

    with open(config_file, "r") as yaml_file:
        config = yaml.safe_load(yaml_file)
        logger.info("Read config from " + config_file)

    with open(validation_config_file, "r") as yaml_file:
        validation = yaml.safe_load(yaml_file)
        logger.debug("Read validation specification from " +
                     validation_config_file)

    with open(request_validation_config, "r") as yaml_file:
        request_validation = yaml.safe_load(yaml_file)

    with open(remote_validation_config, "r") as yaml_file:
        remote_config = yaml.safe_load(yaml_file)
        logger.info("Read remote validation config from " + remote_validation_config)

    with open(remote_config_path, "r") as yaml_file:
        lsf_config = yaml.safe_load(yaml_file)
        logger.info("Read remote config from " + remote_config_path)

    # Validate remote configuration YAML.
    validated_lsf_config = create_validator(remote_config)(lsf_config)
    if isinstance(validated_lsf_config, list):
        logger.error("Could not validate remote config.yaml: {}".
                     format(validated_lsf_config))
        sys.exit(ErrorCodes.CONFIGURATION_ERROR)

    # Validate configuration YAML.
    validation_result = create_validator(validation)(config)
    if isinstance(validation_result, list):
        logger.error("Could not validate config.yaml: {}".
                     format(validation_result))
        sys.exit(ErrorCodes.CONFIGURATION_ERROR)
    else:
        # The validation result contains the normalized config (with default values set).
        config = validation_result

    secrets_path = "/home/weskit/secrets/tower_access_token.secret"
    try:
        with open(secrets_path) as f:
            access_token = f.read()
            # Saving NF Tower access token to env var 'TOWER_ACCESS_TOKEN'
            os.environ["TOWER_ACCESS_TOKEN"] = str(access_token)
    except Exception as e:
        logger.error(f"Could not read access token from '{secrets_path}'")
        logger.error(e)
        sys.exit(ErrorCodes.CONFIGURATION_ERROR)

    # Insert the "celery" section from the configuration file into the Celery config.
    celery.conf.update(**config.get("celery", {}))

    manager = \
        Manager(celery_app=celery,
                database=database,
                workflow_engines=WorkflowEngineFactory.
                create(config["static_service_info"]["default_workflow_engine_parameters"]),
                workflows_base_dir=workflows_base_dir,
                data_dir=weskit_data,
                require_workdir_tag=config["require_workdir_tag"],
                remote_config=validated_lsf_config)

    service_info = ServiceInfo(config["static_service_info"],
                               read_swagger(),
                               database)

    # Create validators for each of the request types in the
    # request-validation.yaml. These are used in the API-calls to validate
    # the input.
    request_validators = {
        "run_request": RunRequestValidator(create_validator(
            request_validation["run_request"]),
            service_info.workflow_engine_versions(),
            data_dir=weskit_data,
            require_workdir_tag=manager.require_workdir_tag)
    }

    app = WESApp(manager,
                 service_info,
                 request_validators)

    app.log_config = log_config
    app.logger = logger

    from weskit.api.wes import bp as wes_bp
    app.register_blueprint(wes_bp)

    OIDCFactory.setup(app, config)

    return app
