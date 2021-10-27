#  Copyright (c) 2021. Berlin Institute of Health (BIH) and Deutsches Krebsforschungszentrum (DKFZ).
#
#  Distributed under the MIT License. Full text at
#
#      https://gitlab.com/one-touch-pipeline/weskit/api/-/blob/master/LICENSE
#
#  Authors: The WESkit Team
import asyncio
import logging
import shlex
import uuid
from asyncio.subprocess import PIPE, DEVNULL
from datetime import datetime
from os import PathLike
from pathlib import PurePath
from typing import Optional, List

import asyncssh
from asyncssh import SSHClientConnection, SSHKey, SSHClientProcess, ChannelOpenError,\
    ProcessError, SSHCompletedProcess
from itertools import compress

from weskit.classes.ShellCommand import ShellCommand
from weskit.classes.executor.Executor \
    import Executor, ExecutionSettings, ExecutedProcess, CommandResult, RunStatus, ProcessId
from weskit.classes.executor.ExecutorException import ExecutorException

logger = logging.getLogger(__name__)


class SshExecutor(Executor):
    """
    Execute commands via SSH on a remote host. Only key-based authentication is supported.
    """

    def __init__(self, username: str,
                 hostname: str,
                 keyfile: PathLike,
                 keyfile_passphrase: str,
                 knownhosts_file: PathLike,
                 connection_timeout: str = "2m",
                 keepalive_interval: str = "0",
                 keepalive_count_max: int = 3,
                 port: int = 22):
        """
        Keepalive: This is for a server application. The default is to have a keep-alive, but one
                    that allows
                   recovery

        :param username: Remote SSH user name.
        :param hostname: Remote host.
        :param keyfile: Only key-based authentication is supported.
        :param knownhosts_file: Path to a knownHosts file to authenticate the server side.
        :param port: Defaults to 22.
        """
        self._username = username
        self._hostname = hostname
        self._keyfile = keyfile
        self._keyfile_passphrase = keyfile_passphrase
        self._port = port
        self._connection_timeout = connection_timeout
        self._keepalive_interval = keepalive_interval
        self._keepalive_count_max = keepalive_count_max
        self._knownhosts_file = knownhosts_file
        self._executor_id = uuid.uuid4()
        self._event_loop = asyncio.get_event_loop()
        self._connect()

    @property
    def username(self) -> str:
        return self._username

    @property
    def hostname(self) -> str:
        return self._hostname

    @property
    def port(self) -> int:
        return self._port

    @property
    def _remote_name(self) -> str:
        return f"{self.username}@{self.hostname}:{self.port}"

    @property
    def keyfile(self) -> PathLike:
        return self._keyfile

    def _connect(self):
        # Some related docs:
        # * https://asyncssh.readthedocs.io/en/latest/api.html#specifying-known-hosts
        # * https://asyncssh.readthedocs.io/en/latest/api.html#specifying-private-keys
        # * https://asyncssh.readthedocs.io/en/latest/api.html#sshclientconnectionoptions
        ssh_keys: List[SSHKey] = asyncssh.read_private_key_list(self._keyfile,
                                                                self._keyfile_passphrase)
        logger.info(f"Read private keys from {self._keyfile}. " +
                    f"sha256 fingerprints: {list(map(lambda k: k.get_fingerprint(), ssh_keys))}")
        try:
            self._connection: SSHClientConnection = \
                self._event_loop.run_until_complete(
                    asyncssh.connect(host=self.hostname,
                                     port=self.port,
                                     username=self.username,
                                     client_keys=ssh_keys,
                                     known_hosts=str(self._knownhosts_file),
                                     login_timeout=self._connection_timeout,
                                     keepalive_interval=self._keepalive_interval,
                                     keepalive_count_max=self._keepalive_count_max,
                                     # By default do not forward the local environment.
                                     env={}, send_env={}))
            logger.debug(f"Connected to {self._remote_name}")
        except asyncssh.DisconnectError as e:
            raise ExecutorException("Connection error (disconnect)", e)
        except asyncio.TimeoutError as e:
            raise ExecutorException("Connection error (timeout)", e)

    async def _check_working_directory(self, workdir: PathLike):
        process: SSHClientProcess = await self._connection. \
                       run(command=f"cd {shlex.quote(str(workdir))}",
                           stdin=DEVNULL, stdout=PIPE, stderr=DEVNULL)
        if process.returncode != 0:
            # This is raising an exception, just like subprocess.Popen raises an exception, if the
            # working directory is not accessible.
            raise ExecutorException(f"Couldn't change to working directory '{str(workdir)}'" +
                                    f" ({self._remote_name})")

    def _process_directory(self, process_id: uuid.UUID) -> PurePath:
        return PurePath(".weskit_tmp") / str(self._executor_id) / str(process_id)

    def _wrapper_path(self, process_id: uuid.UUID) -> PurePath:
        return self._process_directory(process_id) / "wrapper.sh"

    async def _upload_wrapper(self, process_id: uuid.UUID, command: ShellCommand):
        """
        SSH usually does not allow to set environment variables. Therefore we create a little
        script that sets up the environment for the remote process.

        The wrapper will be put into a directory that uniquely identifies the process and uses
        information about the parent process (the one running the SSHExecutor).

        :param command:
        :return:
        """
        remote_dir = self._process_directory(process_id)
        await self._connection.\
            run(f"mkdir -p {shlex.quote(str(remote_dir))}", check=True)

        wrapper_code = "".join(
            [f"cd {shlex.quote(str(command.workdir))}\n"] +
            list([f"export {it[0]}={shlex.quote(it[1])}\n" for it in command.environment.items()]))

        wrapper_path = self._wrapper_path(process_id)
        # We use run() rather than sftp, because sftp is not turned on on all SSH servers.
        await self._connection.\
            run(f"cat - > {shlex.quote(str(wrapper_path))}",
                input=wrapper_code,
                encoding="utf-8",
                check=True)

    async def _is_executable(self, path: PathLike) -> bool:
        """
        Given the remote path of a file, check whether the file is executable for the logged-in
        user. To check the executability, first the path to the executable is determined, then its
        execute-bit is checked.
        """
        # `which` only returns exit code 0, if the provided argument -- with or without path --
        # is executable.
        result: SSHCompletedProcess = await self._connection.run(f"which {shlex.quote(str(path))}")
        return result.returncode == 0

    async def _check_executables(self, paths: List[PathLike]):
        is_executable: List[bool] = await asyncio.gather(*list(map(self._is_executable, paths)),
                                                         return_exceptions=True)
        if not all(list(is_executable)):
            non_executable_paths = \
                list(compress(map(str, paths),
                              map(lambda p: not p, is_executable)))
            raise ExecutorException(f"Not executable on {self._remote_name}: " +
                                    str(non_executable_paths))

    async def _execute(self,
                       command: ShellCommand,
                       stdout_file: Optional[PathLike] = None,
                       stderr_file: Optional[PathLike] = None,
                       stdin_file: Optional[PathLike] = None,
                       settings: Optional[ExecutionSettings] = None) -> ExecutedProcess:
        """
        Only client-side stdout/stderr/stdin-files are supported. If you want that standard input,
        output and error refer to remote files, then include them into the command (e.g. with
        shell redirections).

        :param command:
        :param stdout_file:
        :param stderr_file:
        :param stdin_file:
        :param settings:
        :return:
        """
        start_time = datetime.now()
        try:
            process_id = uuid.uuid4()
            logger.debug(f"Executing SSH process {str(process_id)}")

            # SSH happens always into the user's home-directory, which may not be the selected
            # working directory. To ensure a similar protocol as LocalExecutor and because the
            # convolution of a working directory test and business code is complex, we first make
            # the test.
            await self._check_working_directory(command.workdir)

            # If LocalExecutor tries to run an non-executable binary, it raises an exception.
            # We make an explicit pre-check here to simulate that behaviour.
            await self._check_executables(command.executables)

            # Unless AcceptEnv or PermitUserEnvironment are configured in the sshd_config of
            # the server, environment variables to be set for the target process cannot be used
            # with the standard SSH-client code (e.g. via the env-parameter). For this reason,
            # we create a remote temporary file on the remote host, that is loaded before the
            # actual command is executed remotely.
            await self._upload_wrapper(process_id, command)

            # Therefore, modify the command to change into the working
            # directory. The following does attempts to change to the working directory on the
            # remote host, and exits with code 127, if this is not possible.
            effective_command = \
                ["source", str(self._wrapper_path(process_id)), "&&"] + \
                list(map(shlex.quote, command.command))

            # SSH is always associated with a shell. Therefore a string is processed, rather than
            # an executable with a sequence of parameters, all in a list (compare
            # subprocess.run/Popen). Make a shell command that is correctly evaluated in the shell.
            final_command_str = " ".join(effective_command)
            logger.debug(f"Executed command: {final_command_str}")
            process: SSHClientProcess = await self._connection.\
                create_process(command=final_command_str,
                               stdin=PIPE if stdin_file is None else stdin_file,
                               stdout=PIPE if stdout_file is None else stdout_file,
                               stderr=PIPE if stderr_file is None else stderr_file)
        except ChannelOpenError as e:
            raise ExecutorException("Couldn't execute process", e)

        return ExecutedProcess(command=command,
                               executor=self,
                               process_handle=process,
                               pre_result=CommandResult(id=ProcessId(process_id),
                                                        stdout_file=stdout_file,
                                                        stderr_file=stderr_file,
                                                        stdin_file=stdin_file,
                                                        run_status=RunStatus(),
                                                        start_time=start_time))

    def execute(self, *args, **kwargs) -> ExecutedProcess:
        return self._event_loop.run_until_complete(self._execute(*args, **kwargs))

    def get_status(self, process: ExecutedProcess) -> RunStatus:
        return RunStatus(process.handle.returncode)

    def update_process(self, process: ExecutedProcess) -> ExecutedProcess:
        """
        Update the the executed process, if possible.
        """
        result = process.result
        return_code = process.handle.returncode
        if return_code is not None:
            result.status = RunStatus(return_code)
            result.end_time = datetime.now()
            process.result = result
        return process

    async def _wait_for(self, process: ExecutedProcess) -> CommandResult:
        try:
            process._handle = await process.handle.wait()
            self.update_process(process)
            wrapper_path = self._wrapper_path(process.id.value)
            await self._connection.run(f"rm {shlex.quote(str(wrapper_path))}", check=True)
            process_dir = self._process_directory(process.id.value)
            await self._connection.run(f"rmdir {shlex.quote(str(process_dir))}", check=True)
        except TimeoutError as e:
            ExecutorException(f"Process {process.id.value} timed out:" +
                              str(process.command.command), e)
        except ProcessError as e:
            ExecutorException(f"Error during cleanup of {process.id.value}:" +
                              str(process.command.command), e)
        return process.result

    def wait_for(self, process: ExecutedProcess) -> CommandResult:
        return self._event_loop.run_until_complete(self._wait_for(process))

    def kill(self, process: ExecutedProcess):
        try:
            process.handle.kill()
            self.wait_for(process)
        except OSError as e:
            ExecutorException(f"Could not kill process ({process.command.command})", e)
