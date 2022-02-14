#  Copyright (c) 2021. Berlin Institute of Health (BIH) and Deutsches Krebsforschungszentrum (DKFZ).
#
#  Distributed under the MIT License. Full text at
#
#      https://gitlab.com/one-touch-pipeline/weskit/api/-/blob/master/LICENSE
#
#  Authors: The WESkit Team
import logging
from datetime import datetime
from os import PathLike
from typing import Pattern, Optional


from weskit.classes.ShellCommand import ShellCommand
from weskit.classes.executor.Executor import \
    Executor, CommandResult, ProcessId, ExecutionSettings, ExecutedProcess, RunStatus
from weskit.classes.executor.cluster.ClusterExecutor import ClusterExecutor, execute, CommandSet
from weskit.classes.executor.cluster.lsf.LsfCommandSet import LsfCommandSet
from weskit.classes.executor.ExecutorException import ExecutorException


logger = logging.getLogger(__name__)


class LsfExecutor(ClusterExecutor):
    """
    Execute LSF job-management operations via shell commands issued on a local/remote host.
    """

    def __init__(self, executor: Executor):
        """
        Provide an executor that is used to execute the cluster commands. E.g. if this the commands
        should run locally, you can use a command_executor.LocalExecutor. If you need to submit via
        a remote connection you can use an command_executor.SshExecutor.
        """
        self.__command_set = LsfCommandSet()
        self._executor = executor

    @property
    def _command_set(self) -> CommandSet:
        return self.__command_set

    @property
    def executor(self) -> Executor:
        return self._executor

    _match_jid: Pattern = r'Job <(\d+)> is submitted to .+.\n'
    _split_delimiter: str = " "
    _match_status: Pattern = r'(\d+)\s+(\S+)\s+(-|\d+)'
    _success_status_name: str = "DONE"
    _success_exit_code: str = "-"

    def execute(self,
                command: ShellCommand,
                stdout_file: Optional[PathLike] = None,
                stderr_file: Optional[PathLike] = None,
                stdin_file: Optional[PathLike] = None,
                settings: Optional[ExecutionSettings] = None,
                **kwargs) -> ExecutedProcess:
        """
        stdout, stderr, and stdin files are *remote files on the cluster nodes*.

        WARNING: Do not set too many environment variables in `command.environment`. The
                implementation uses `bsub -env` and too many variables may result in a too long
                command-line.
        """

        if stdin_file is not None:
            logger.error("stdin_file is not supported in ClusterExecutor.execute()")
        # Note that there are at two shells involved: The environment on the submission host
        # and the environment on the compute node, on which the actual command is executed.
        submission_command = ShellCommand(self._command_set.submit(command=command,
                                                                   stdout_file=stdout_file,
                                                                   stderr_file=stderr_file,
                                                                   settings=settings))
        # The actual submission is done quickly. We wait here for the
        # result and then use the cluster job ID returned from the submission command,
        # as process ID to query the cluster job status later.

        with execute(self._executor, submission_command) \
             as (result, stdout, stderr):
            stdout_lines = stdout.readlines()
            stderr_lines = stderr.readlines()
            start_time = datetime.now()
            if result.status.failed:
                raise ExecutorException(f"Failed to submit cluster job: {result}" +
                                        f"stdout={stdout_lines}, " +
                                        f"stderr={stderr_lines}")
            else:
                cluster_job_id = \
                    ProcessId(self.extract_jobid_from_submission_output(stdout_lines))

        logger.debug(f"Cluster job ID {cluster_job_id}: {submission_command}")

        # NOTE: We could now create an additional `wait` process that waits for the cluster job
        # ID. However, we postpone the creation of this to a later stage.
        # The process handle is just the cluster job ID.
        return ExecutedProcess(executor=self,
                               process_handle=cluster_job_id,
                               pre_result=CommandResult(command=command,
                                                        id=cluster_job_id,
                                                        stderr_file=stderr_file,
                                                        stdout_file=stdout_file,
                                                        stdin_file=stdin_file,
                                                        run_status=RunStatus(None),
                                                        start_time=start_time))
