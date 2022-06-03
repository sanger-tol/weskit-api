#  Copyright (c) 2022. Deutsches Krebsforschungszentrum (DKFZ) and Berlin Institute of Health (BIH)
#
#  Distributed under the MIT License. Full text at
#
#      https://gitlab.com/one-touch-pipeline/weskit/api/-/blob/master/LICENSE
#
#  Authors: The WESkit Team
from __future__ import annotations

from typing import List, Optional, Dict, FrozenSet, Any, Set


class EngineParameter:
    """
    All allowed engine parameters, as they will be used in the configuration (weskit.yaml) and as
    run parameters via the API. The WorkflowEngine subclasses may or may not interpret these.
    """

    def __init__(self,
                 names: Set[str]):
        self._names = frozenset(names)

    @property
    def names(self) -> FrozenSet[str]:
        return self._names

    # EngineParameter is an immutable value type. So we redefine object identity as value identity
    # and the hash key (for dictionaries) based on the values only.
    def __eq__(self, other) -> bool:
        if isinstance(other, type(self)):
            return self.names == other.names
        else:
            return False

    def __hash__(self):
        return hash(self.names)


class ParameterIndex:
    """
    We use a central index of allowed engine parameters to retrieve parameters via any of their
    aliases and ensure that no two parameters share aliases.
    """

    def __init__(self, parameters: List[EngineParameter]):
        checked_params: Dict[str, EngineParameter] = {}
        for param in parameters:
            for name in param.names:
                # It's fine if it is the same name and same object, but not the same name but
                # a different parameter object. This could be refined by making the parameter
                # object a value class (with overridden equality and hashing function).
                if name in checked_params and checked_params[name] != param:
                    raise ValueError(f"Duplicate engine parameter name '{name}'")
                else:
                    checked_params[name] = param
        self._parameters = checked_params

    @property
    def all(self) -> List[EngineParameter]:
        results: Dict[EngineParameter, Any] = {}
        for p in self._parameters.values():
            results[p] = True
        return list(results.keys())

    def get(self, name: str, default: Optional[EngineParameter] = None) ->\
            Optional[EngineParameter]:
        return self._parameters.get(name, default)

    def __getitem__(self, name: str) -> EngineParameter:
        return self._parameters[name]

    def subset(self, names: FrozenSet[str]) -> ParameterIndex:
        """
        Get a subset of the global index. This is usually done in the WorkflowEngines to define
        the engine specific set of allowed parameters.
        """
        return ParameterIndex([
            param
            for param in self.all
            if len(names.intersection(param.names)) > 0
        ])


# (Yet,) Static configuration of allowed parameters. We have this global "database" to promote.
# the usage of similar parameter names for all workflows. We may for instance also add ontology
# terms and term IDs.
KNOWN_PARAMS = ParameterIndex([
    EngineParameter({"trace"}),
    EngineParameter({"timeline"}),
    EngineParameter({"report"}),
    EngineParameter({"tempdir"}),
    EngineParameter({"graph"}),
    EngineParameter({"max-memory"}),
    EngineParameter({"cores"}),
    EngineParameter({"use-singularity"}),
    EngineParameter({"use-conda"}),
    EngineParameter({"profile"})
])


class ActualEngineParameter:
    """
    A WorkflowEngineParam is an AllowedEngineParameter with value.

    Note that the value is basically untyped, i.e. Optional[str]. The types are only known at
    run-time, which would require lots of `cast` etc. to get working. The untyped version seemed
    more straightforward.
    """

    def __init__(self,
                 param: EngineParameter,
                 value: Optional[str] = None,
                 api_parameter: bool = False):
        self._param = param
        self._value = value
        self._api_parameter = api_parameter

    @property
    def is_api_parameter(self) -> bool:
        return self._api_parameter

    @property
    def param(self) -> EngineParameter:
        return self._param

    @property
    def value(self) -> Optional[str]:
        return self._value

    def __repr__(self) -> str:
        return f"ActualEngineParam({self.param.names}, {self.value})"

    def __eq__(self, other) -> bool:
        if isinstance(other, type(self)):
            return self.param == other.param and self.value == other.value
        else:
            return False

    def __hash__(self):
        return hash((self.param, self.value))
