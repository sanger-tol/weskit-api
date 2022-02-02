#  Copyright (c) 2021. Berlin Institute of Health (BIH) and Deutsches Krebsforschungszentrum (DKFZ).
#
#  Distributed under the MIT License. Full text at
#
#      https://gitlab.com/one-touch-pipeline/weskit/api/-/blob/master/LICENSE
#
#  Authors: The WESkit Team

import yaml
import json
import logging
import os
from pathlib import Path
from typing import List, Dict
from asyncssh import SFTPError

from weskit.classes.ShellCommand import ShellCommand
from weskit.classes.executor.Executor import CommandResult
from weskit.classes.executor.SshExecutor import SshExecutor
from weskit.classes.executor.cluster.lsf.LsfExecutor import LsfExecutor
from weskit.classes.executor.Executor import ExecutionSettings
from weskit.classes.executor.ExecutorException import ExecutorException
from weskit.utils import get_current_timestamp, collect_relative_paths_from

logger = logging.getLogger(__name__)


def run_command(command: List[str],
                base_workdir: str,
                sub_workdir: str,
                lsf_config: Dict,
                workflow_path: str,
                request_config_params_path: str,
                environment: Dict[str, str] = None,
                log_base: str = ".weskit"):
    """
    Run a command in a working directory. The workdir has to be an relative path, such that
    `base_workdir/sub_workdir` is the absolute path in which the command is executed. base_workdir
    can be absolute or relative.

    Write log files into a timestamp sub-directory of `sub_workdir/log_base`. There will be
    `stderr` and `stdout` files for the respective output of the command and `log.json` with
    general logging information, including the "command", "start_time", "end_time", and the
    "exit_code". Paths in the execution log are all relative.

    Returns a dict with fields "stdout_file", "stderr_file", "log_file" for the three log
    files, and "output_files" for all files created by the process, but not the three log-files.

    "exit_code" is set to -1, if no result could be produced from the command, e.g. if a prior
    mkdir failed, or similar abnormal situations.

    Note: The interface is not based on ShellCommand because that would have required a means of
          (de)serializing ShellCommand for transfer from the REST-server to the Celery worker.
    """
    shared_workdir = lsf_config["lsf_submission_host"]["bsub_params"]["shared_workdir"]
    if environment is None:
        environment = {}
    base_workdir_path = Path(base_workdir)
    sub_workdir_path = Path(sub_workdir)
    log_base_path = Path(log_base)
    remote_base_workdir_path = Path(shared_workdir)
    remote_sub_workdir_path = Path(workflow_path)

    workdir_abs = base_workdir_path / sub_workdir_path
    remote_workdir_abs = remote_base_workdir_path / remote_sub_workdir_path.parent
    logger.info("Running command in {}: {}".format(remote_workdir_abs, command))

    shell_command = ShellCommand(command=command,
                                 workdir=remote_workdir_abs,
                                 # Let this explicitly inherit the task environment for the moment,
                                 # e.g. for conda.
                                 environment={**dict(os.environ), **environment})
    start_time = get_current_timestamp()
    log_dir_rel = log_base_path / start_time
    stderr_file_rel = f"{start_time}_stderr"
    stdout_file_rel = f"{start_time}_stdout"
    execution_log_rel = f"{start_time}_log.json"

    remote_log_dir_rel = log_base_path / start_time
    remote_stderr_file_rel = f"{start_time}_stderr"
    remote_stdout_file_rel = f"{start_time}_stdout"
    remote_execution_log_rel = f"{start_time}_log.json"

    result: CommandResult
    try:
        stderr_file_abs = workdir_abs / stderr_file_rel
        stdout_file_abs = workdir_abs / stdout_file_rel
        remote_stderr_file_abs = remote_workdir_abs / remote_stderr_file_rel
        remote_stdout_file_abs = remote_workdir_abs / remote_stdout_file_rel
        remote_log_dir_abs = remote_workdir_abs / remote_log_dir_rel
        # os.makedirs(log_dir_abs) #TODO: implement remove file creation
        settings = ExecutionSettings(**(lsf_config['lsf_submission_host']['bsub_params']))
        executor = LsfExecutor(SshExecutor(**(lsf_config['lsf_submission_host']['ssh'])))
        logger.info(f"Copying the config.yaml ({request_config_params_path}) file to path : {remote_workdir_abs}")
        _copy_remote_file(request_config_params_path, remote_workdir_abs, executor.executor, "put")
        process = executor.execute(shell_command, remote_stdout_file_abs, remote_stderr_file_abs, settings=settings)
        result = executor.wait_for(process)
        logger.info("Copying log files to local directory")
        logger.info(f"remote_stdout_file_abs : {remote_stdout_file_abs} to stdout :{stdout_file_abs}")
        _copy_remote_file(remote_stdout_file_abs, stdout_file_abs, executor.executor, "get")
        logger.info(f"remote_stderr_file_abs : {remote_stderr_file_abs} to stderr :{stderr_file_abs}")
        _copy_remote_file(remote_stderr_file_abs, stderr_file_abs, executor.executor, "get")
    finally:
        # Collect files, but ignore those, that are in the .weskit/ directory. They are tracked by
        # the fields in the execution log (or that of previous runs in this directory).
        outputs = list(filter(
            lambda fn: os.path.commonpath([fn, str(log_base_path)]) != str(log_base_path),
            collect_relative_paths_from(workdir_abs)))
        if result is None:
            # result may be None, if the execution failed because the command does not exist
            exit_code = -1
        else:
            # result.status should not be None, unless the process did not finish, which would be
            # a bug at this place.
            exit_code = result.status.code
        execution_log = {
            "start_time": start_time,
            "cmd": command,
            "env": environment,
            "remote_workdir": str(remote_workdir_abs),
            "workdir": str(workdir_abs),
            "end_time": get_current_timestamp(),
            "exit_code": exit_code,
            "remote_stdout_file": str(remote_stdout_file_rel),
            "remote_stderr_file": str(remote_stderr_file_rel),
            "stdout_file": str(stdout_file_rel),
            "stderr_file": str(stderr_file_rel),
            "log_dir": str(remote_log_dir_rel),
            "log_file": str(remote_execution_log_rel),
            "output_files": outputs
        }

        execution_log_abs = workdir_abs / execution_log_rel
        with open(execution_log_abs, "w") as fh:
            json.dump(execution_log, fh)
        remote_execution_log_abs = remote_workdir_abs / remote_execution_log_rel
        _copy_remote_file(execution_log_abs, remote_execution_log_abs, executor.executor, "put")
        logger.info(f" Copying execution_log: {execution_log} to {remote_execution_log_abs}")

    return execution_log


def _copy_remote_file(src_path, dst_path, executor, action):
    """
        TODO: Add method description
    """
    try:
        logger.info(f" Reading remote file from path : {src_path}")
        executor.event_loop.run_until_complete(getattr(executor, action)(srcpath=src_path, dstpath=dst_path))
        logger.info(f" Created to local file path : {dst_path}")
    except (SFTPError, OSError, ValueError) as e:
        logger.error(f"Attempt to copy remote file failed for file: {src_path}")
        logger.error(e, exc_info=True)
        raise FileNotFoundError
