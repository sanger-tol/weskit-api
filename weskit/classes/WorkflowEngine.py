#  Copyright (c) 2022. Berlin Institute of Health (BIH) and Deutsches Krebsforschungszentrum (DKFZ).
#
#  Distributed under the MIT License. Full text at
#
#      https://gitlab.com/one-touch-pipeline/weskit/api/-/blob/master/LICENSE
#
#  Authors: The WESkit Team
import math
from abc import ABCMeta, abstractmethod
from os import PathLike, getenv
from pathlib import Path, PurePath
from typing import List, Dict, Optional

from weskit.memory_units import Memory, Unit
from weskit.classes.ShellCommand import ShellCommand
from weskit.classes.WorkflowEngineParameters import \
    ActualEngineParameter, ParameterIndex, KNOWN_PARAMS, EngineParameter


class WorkflowEngine(metaclass=ABCMeta):

    def __init__(self,
                 default_params: List[ActualEngineParameter]):
        not_allowed = list(filter(lambda param: param.param not in self.known_parameters().all,
                                  default_params))
        if len(not_allowed) > 0:
            raise ValueError(f"Non-allowed default parameters for {type(self).name()}: " +
                             str(not_allowed))
        self.default_params = default_params

    @classmethod
    @abstractmethod
    def known_parameters(cls) -> ParameterIndex:
        """
        Get an index of the workflow engine parameters allowed for this WorkflowEngine subclass.
        """
        pass

    def _optional_param(self,
                        param: ActualEngineParameter,
                        name: str,
                        argument: str) -> List[str]:
        """
        Helper for parameter processing. This is for flag-like parameters. The boolean value is
        interpreted as presence (True) or absence (False) of the flag.
        """
        def to_bool(value: Optional[str]) -> bool:
            if value is None:
                return False
            elif value.lower() in ["true", "t", "present", "1", "yes", "y"]:
                return True
            elif value.lower() in ["false", "f", "absent", "0", "no", "n"]:
                return False
            else:
                raise ValueError(f"Could not parse '{value}' to boolean")

        if param.param == self.known_parameters()[name]:
            if to_bool(param.value):
                return [argument]
            else:
                return []
        else:
            return []

    def _argument_param(self,
                        param: ActualEngineParameter,
                        name: str,
                        argument: str) -> List[str]:
        """
        Helper for parameter processing. This processor is for arguments of the type key/value,
        with an obligatory value (i.e. the value must not be None). If the parameter is None
        (not the string 'None'), then the parameter is removed (e.g. to turn off a set default
        parameter).
        """
        if param.param == self.known_parameters()[name]:
            if param.value is None:
                return []
            elif isinstance(param.value, list):
                result = []
                for v in param.value:
                    result.extend([argument, v])
                return result
            else:
                return [argument, str(param.value)]
        else:
            return []

    def _normalize_and_check(self, run_params: Dict[str, Optional[str]]) \
            -> Dict[EngineParameter, Optional[str]]:
        """
        Normalized to `Optional[str]` (they could be e.g. `int` if they come from a JSON parser)
        and check that they are among the known parameters for this WorkflowEngine class. Throws
        a KeyError, if the run_parameter name (key) is not among the known parameters.
        """
        result: Dict[EngineParameter, Optional[str]] = {}
        for name, value in run_params.items():
            parameter = self.known_parameters()[name]
            result[parameter] = None if value is None else value
        return result

    def _effective_run_params(self, run_params: Dict[str, Optional[str]]) \
            -> List[ActualEngineParameter]:
        """
        Combine the run (engine) parameters with the default engine parameters. Check the
        validity of the resulting parameter set and return a lists of WorkflowEngineParam objects
        that will be converted to the actual command-line arguments, etc. later.

        If a run-parameter is not among the known parameters or forbidden to be set, then a
        KeyError is thrown.
        """
        checked_run_params = {
            # We map here to avoid excessive if-else statements in the code below.
            p: ActualEngineParameter(p, v) for p, v in self._normalize_and_check(run_params).items()
        }
        result: List[ActualEngineParameter] = []
        for default_param in self.default_params:
            if default_param.is_api_parameter:
                result += [checked_run_params.get(default_param.param, default_param)]
            else:
                if default_param.param in checked_run_params.keys():
                    raise KeyError(f"Parameter {default_param.param.names} is forbidden")
                result += [default_param]
        return result

    @abstractmethod
    def command(self,
                workflow_path: PathLike,
                workdir: Optional[PathLike],
                config_files: List[PathLike],
                engine_params: Dict[str, Optional[str]]) \
            -> ShellCommand:
        """
        Use the instance variables and run parameters to compose a command to be executed
        by the run method. The workflow_engine_params are just a list of parameters. It is a
        responsibility of the WorkflowEngine implementation to sort these into slots and
        check whether they are allowed to be set or not.
        """
        pass

    @staticmethod
    @abstractmethod
    def name() -> str:
        pass


class Snakemake(WorkflowEngine):

    def __init__(self,
                 default_params: List[ActualEngineParameter]):
        super().__init__(default_params)

    @staticmethod
    def name():
        return "SMK"

    @classmethod
    def known_parameters(cls) -> ParameterIndex:
        return KNOWN_PARAMS.subset(frozenset({"cores"}))

    def _environment(self, parameters: List[ActualEngineParameter]) -> Dict[str, str]:
        result = {"SINGULARITYENV_PREPEND_PATH": "/software/treeoflife/miniconda3/envs/nf-core_dev/bin",
                  "SINGULARITY_BIND": "/software",
                  "SINGULARITYENV_JAVA_HOME": "/software/treeoflife/miniconda3/envs/nf-core_dev"}
        return result

    def _command_params(self, parameters: List[ActualEngineParameter]) -> List[str]:
        result = []
        for param in parameters:
            result += self._argument_param(param, "cores", "--cores")
        return result

    def command(self,
                workflow_path: PathLike,
                workdir: Optional[PathLike],
                config_files: List[PathLike],
                engine_params: Dict[str, Optional[str]]) \
            -> ShellCommand:
        parameters = self._effective_run_params(engine_params)
        command = ["snakemake",
                   "--snakefile", str(workflow_path)
                   ] + self._command_params(parameters)
        if len(config_files) > 0:
            command += ["--configfile"] + list(map(lambda p: str(p), config_files))
        return ShellCommand(command=command,
                            workdir=None if workdir is None else Path(workdir),
                            environment=self._environment(parameters))


class Nextflow(WorkflowEngine):

    def __init__(self,
                 default_params: List[ActualEngineParameter]):
        super().__init__(default_params)

    @staticmethod
    def name():
        return "NFL"

    @classmethod
    def known_parameters(cls) -> ParameterIndex:
        return KNOWN_PARAMS.subset(frozenset({"trace",
                                              "report",
                                              "timeline",
                                              "graph",
                                              "max-memory",
                                              "r",
                                              "profile",
                                              "c",
                                              "w",
                                              "resume",
                                              "with-tower",
                                              "tempdir"}))

    def _environment(self, parameters: List[ActualEngineParameter]) -> Dict[str, str]:
        result = {}
        for param in parameters:
            if param.param == self.known_parameters()["max-memory"]:
                if param.value is None:
                    raise ValueError("max-memory must have valid value")
                else:
                    result["NXF_OPTS"] = "-Xmx%sm" % \
                                         math.ceil(Memory.from_str(param.value).
                                                   to(Unit.MEGA, False).value)
        return result

    def _command_params(self, parameters: List[ActualEngineParameter]) -> List[str]:
        result = []
        for param in parameters:
            if param.param == self.known_parameters()["tempdir"]:
                if param.value is not None:
                    result += ["-Djava.io.tmpdir=%s" % param.value]
        return result

    def _run_command_params(self, parameters: List[ActualEngineParameter]) -> List[str]:
        """
        An additional parameter slot for `nextflow run`.
        """
        result = []
        for param in parameters:
            result += self._optional_param(param, "trace", "-with-trace")
            result += self._optional_param(param, "report", "-with-report")
            result += self._optional_param(param, "timeline", "-with-timeline")
            result += self._optional_param(param, "graph", "-with-dag")
            result += self._argument_param(param, "r", "-r")
            result += self._argument_param(param, "c", "-c")
            result += self._argument_param(param, "w", "-w")
            result += self._argument_param(param, "profile", "-profile")
            result += self._optional_param(param, "resume", "-resume")
            result += self._argument_param(param, "with-tower", "-with-tower")
        return result

    def command(self,
                workflow_path: PathLike,
                workdir: Optional[PathLike],
                config_files: List[PathLike],
                engine_params: Dict[str, Optional[str]]) \
            -> ShellCommand:
        parameters = self._effective_run_params(engine_params)
        command = ["nextflow"] +\
            self._command_params(parameters) +\
            ["run", str(workflow_path)]
        if len(config_files) == 1:
            command += ["-params-file", str(config_files[0])]
        else:
            raise ValueError("Nextflow accepts only a single parameters file (`-params-file`)")
        command += self._run_command_params(parameters)
        environment_params = self._environment(parameters)
        # As multiple Nextflow workflows will be accessing the $user/.nextflow/assets folder
        # making NXF_ASSETS point to current workdir is safer to avoid GIT index errors.
        environment_params["NXF_ASSETS"] = str(workdir)
        environment_params["TOWER_ACCESS_TOKEN"] = getenv("TOWER_ACCESS_TOKEN")
        run_dir = PurePath(workdir)
        environment_params["NXF_WORK"] = str(Path(getenv("NFL_TMP")) / run_dir.parent.name
                                             / run_dir.name / Path("work"))
        return ShellCommand(command=command,
                            workdir=None if workdir is None else Path(workdir),
                            environment=environment_params)
