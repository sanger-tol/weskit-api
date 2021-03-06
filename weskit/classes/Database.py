#  Copyright (c) 2021. Berlin Institute of Health (BIH) and Deutsches Krebsforschungszentrum (DKFZ).
#
#  Distributed under the MIT License. Full text at
#
#      https://gitlab.com/one-touch-pipeline/weskit/api/-/blob/master/LICENSE
#
#  Authors: The WESkit Team
import uuid

from weskit.classes.Run import Run
from bson.son import SON
from weskit.classes.RunStatus import RunStatus
from typing import List, Optional


class Database:
    """Database abstraction."""

    def __init__(self, mongo_client, database_name):
        self.db = mongo_client[database_name]
        self.client = mongo_client

    def _db_runs(self):
        return self.db["run"]

    def aggregate_runs(self, pipeline):
        return dict(self._db_runs().aggregate(pipeline))

    def get_run(self, run_id: str, **kwargs) -> Optional[Run]:
        run_data = self._db_runs().find_one(
            filter={"run_id": run_id}, **kwargs)
        if run_data is not None:
            return Run(run_data)
        return None

    def get_runs(self, query) -> List[Run]:
        runs = []
        runs_data = self._db_runs().find(query)
        if runs_data is not None:
            for run_data in runs_data:
                runs.append(Run(run_data))
        return runs

    def list_run_ids_and_states(self, user_id=None) -> list:
        filter = None
        if user_id is not None:
            filter = {"user_id": user_id}
        return list(self._db_runs().find(
            projection={"_id": False,
                        "run_id": True,
                        "run_status": True,
                        "user_id": True
                        },
            filter=filter))

    def count_states(self):
        """
        Returns the statistics of all job-states ever, for all users.
        """
        pipeline = [
            {"$unwind": "$run_status"},
            {"$group": {"_id": "$run_status", "count": {"$sum": 1}}},
            {"$sort": SON([("count", -1), ("_id", -1)])}
            ]
        counts_data = list(self._db_runs().aggregate(pipeline))
        counts = {}
        for counts_datum in counts_data:
            counts[counts_datum["_id"]] = counts_datum["count"]
        for status in RunStatus:
            if status.name not in counts.keys():
                counts[status.name] = 0
        return counts

    def create_run_id(self):
        run_id = str(uuid.uuid4())
        while not self.get_run(run_id) is None:
            run_id = str(uuid.uuid4())
        return run_id

    def insert_run(self, run: Run) -> bool:
        if self.get_run(run.id) is None:
            return self._db_runs() \
                .insert_one(dict(run)) \
                .acknowledged
        else:
            return False

    def update_run(self, run: Run) -> bool:
        return self._db_runs() \
            .update_one({"run_id": run.id},
                        {"$set": dict(run)}
                        ).acknowledged

    def delete_run(self, run: Run) -> bool:
        return self._db_runs() \
            .delete_one({"run_id": run.id}) \
            .acknowledged

    def list_run_ids_and_states_and_times(self, user_id=Optional[str]) -> list:
        filter = None
        if user_id is not None:
            filter = {"user_id": user_id}
        return list(self._db_runs().find(
            projection={"_id": False,
                        "run_id": True,
                        "run_status": True,
                        "start_time": True,
                        "user_id": True,
                        "request": True
                        },
            filter=filter))
