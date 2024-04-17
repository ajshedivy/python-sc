import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar, Union

from dataclasses_json import dataclass_json

from python_sc.client.sql_job import SQLJob
from python_sc.types import QueryOptions

T = TypeVar("T")


class QueryState(Enum):
    NOT_YET_RUN = (1,)
    RUN_MORE_DATA_AVAIL = (2,)
    RUN_DONE = (3,)
    ERROR = 4


class Query(Generic[T]):
    global_query_list: List["Query[Any]"] = []

    def __init__(
        self,
        job: SQLJob,
        query: str,
        opts: Optional[Union[Dict[str, Any], QueryOptions]] = QueryOptions(
            isClCommand=False, parameters="", autoClose=False
        ),
    ) -> None:
        self.job = job
        self.is_prepared: bool = None is opts.parameters
        self.parameters: Optional[List] = opts.parameters
        self.sql: str = query
        self.is_cl_command: bool = opts.isClCommand
        self.should_auto_close: bool = opts.autoClose
        self.is_terse_results: bool = opts.isTerseResults

        self._rows_to_fetch: int = 100
        self._state: QueryState = QueryState.NOT_YET_RUN

        Query.global_query_list.append(self)

    def run(self, rows_to_fetch: int = None):
        if rows_to_fetch is None:
            rows_to_fetch = self._rows_to_fetch
        else:
            self._rows_to_fetch = rows_to_fetch

        match self._state:
            case QueryState.RUN_MORE_DATA_AVAIL:
                raise Exception("Statement has already been run")
            case QueryState.RUN_DONE:
                raise Exception("Statement has already been fully run")

        query_object = {}
        if self.is_cl_command:
            query_object = {
                "id": self.job._get_unique_id("clcommand"),
                "type": "cl",
                "terse": self.is_terse_results,
                "cmd": self.sql,
            }
        else:
            query_object = {
                "id": self.job._get_unique_id("query"),
                "type": "prepare_sql_execute" if self.is_prepared else "sql",
                "sql": self.sql,
                "terse": self.is_terse_results,
                "rows": rows_to_fetch,
                "parameters": self.parameters,
            }

        result = self.job.send(json.dumps(query_object))
        query_result: Dict[str, Any] = json.loads(self.job._socket.recv())

        self._state = (
            QueryState.RUN_DONE
            if query_result.get("is_done", False)
            else QueryState.RUN_MORE_DATA_AVAIL
        )

        if not query_result.get("success", False) and not self.is_cl_command:
            self._state = QueryState.ERROR
            error_keys = ["error", "sql_state", "sql_rc"]
            error_list = [query_result[key] for key in error_keys if key in query_result.keys()]
            if len(error_list) == 0:
                error_list.append("failed to run query for unknown reason")

            raise Exception(error_list.join(", "))

        self._correlation_id = query_result["id"]
        
        return query_result