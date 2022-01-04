from trcli.api.api_client import APIClient, APIClientResult
from trcli.cli import Environment
from trcli.data_classes.dataclass_testrail import TestRailSuite
from trcli.data_providers.api_data_provider import ApiDataProvider
from trcli.constants import (
    ProjectErrors,
    FAULT_MAPPING,
    MAX_WORKERS_ADD_RESULTS,
    MAX_WORKERS_ADD_CASE,
)
from typing import List
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed


@dataclass
class ProjectData:
    project_id: int
    suite_mode: int
    error_message: str


class ApiRequestHandler:
    """Sends requests based on DataProvider bodies"""

    def __init__(
        self,
        environment: Environment,
        api_client: APIClient,
        suites_data: TestRailSuite,
    ):
        self.environment = environment
        self.client = api_client
        self.data_provider = ApiDataProvider(suites_data)
        self.suites_data_from_provider = self.data_provider.suites_input

    def get_project_id(self, project_name: str) -> ProjectData:
        """
        Send get_projects with project name
        :project_name: Project name
        :returns: ProjectData
        """
        response = self.client.send_get("get_projects")
        if not response.error_message:
            available_projects = [
                project
                for project in response.response_text["projects"]
                if project["name"] == project_name
            ]
            if len(available_projects) == 1:
                return ProjectData(
                    project_id=int(available_projects[0]["id"]),
                    suite_mode=int(available_projects[0]["suite_mode"]),
                    error_message=response.error_message,
                )
            elif len(available_projects) > 1:
                return ProjectData(
                    project_id=ProjectErrors.multiple_project_same_name,
                    suite_mode=-1,
                    error_message=FAULT_MAPPING["more_than_one_project"],
                )
            else:
                return ProjectData(
                    project_id=ProjectErrors.not_existing_project,
                    suite_mode=-1,
                    error_message=f"{project_name} {FAULT_MAPPING['project_doesnt_exists']}",
                )
        else:
            return ProjectData(
                project_id=ProjectErrors.other_error,
                suite_mode=-1,
                error_message=response.error_message,
            )

    def check_suite_id(self, project_id: int) -> (bool, str):
        """
        Check if suite from DataProvider exist using get_suites endpoint
        :project_id: project id
        :returns: True if exists in suites. False if not.
        """
        suite_id = self.suites_data_from_provider.suite_id
        response = self.client.send_get(f"get_suites/{project_id}")
        if not response.error_message:
            available_suites = [suite["id"] for suite in response.response_text]
            return (True, "") if suite_id in available_suites else (False, "")
        else:
            return None, response.error_message

    def get_suite_ids(self, project_id: int) -> (List[int], str):
        """Get suite IDs for requested project_id.
        : project_id: project id
        : returns: tuple with list of suite ids and error string"""
        available_suites = []
        returned_resources = []
        error_message = ""
        response = self.client.send_get(f"get_suites/{project_id}")
        if not response.error_message:
            for suite in response.response_text:
                available_suites.append(suite["id"])
                returned_resources.append(
                    {
                        "suite_id": suite["id"],
                        "name": suite["name"],
                    }
                )
        else:
            error_message = response.error_message

        self.data_provider.update_data(suite_data=returned_resources) if len(
            returned_resources
        ) > 0 else "Update skipped"
        return available_suites, error_message

    def add_suites(self, project_id: int) -> (List[dict], str):
        """
        Adds suites that doesn't have ID's in DataProvider.
        Runs update_data in data_provider for successfully created resources.
        :project_id: project_id
        :returns: Tuple with list of dict created resources and error string.
        """
        add_suite_data = self.data_provider.add_suites_data()
        responses = []
        error_message = ""
        for body in add_suite_data["bodies"]:
            response = self.client.send_post(f"add_suite/{project_id}", body)
            if not response.error_message:
                responses.append(response)
            else:
                error_message = response.error_message
                break

        returned_resources = [
            {
                "suite_id": response.response_text["id"],
                "name": response.response_text["name"],
            }
            for response in responses
        ]
        self.data_provider.update_data(suite_data=returned_resources) if len(
            returned_resources
        ) > 0 else "Update skipped"
        return returned_resources, error_message

    def check_missing_section_ids(self, project_id: int) -> (List[int], str):
        """
        Check what section id's are missing in DataProvider.
        :project_id: project_id
        :returns: Tuple with list missing section ID and error string.
        """
        suite_id = self.suites_data_from_provider.suite_id
        sections = [
            section.section_id
            for section in self.suites_data_from_provider.testsections
        ]
        response = self.client.send_get(
            f"get_sections/{project_id}&suite_id={suite_id}"
        )
        if not response.error_message:
            return (
                list(
                    set(sections)
                    - set(
                        [
                            section.get("id")
                            for section in response.response_text["sections"]
                        ]
                    )
                ),
                response.error_message,
            )
        else:
            return [], response.error_message

    def add_sections(self, project_id: int) -> (List[dict], str):
        """
        Add sections that doesn't have ID in DataProvider.
        Runs update_data in data_provider for successfully created resources.
        :project_id: project_id
        :returns: Tuple with list of dict created resources and error string.
        """
        add_sections_data = self.data_provider.add_sections_data()
        responses = []
        error_message = ""
        for body in add_sections_data["bodies"]:
            response = self.client.send_post(f"add_section/{project_id}", body)
            if not response.error_message:
                responses.append(response)
            else:
                error_message = response.error_message
                break
        returned_resources = [
            {
                "section_id": response.response_text["id"],
                "suite_id": response.response_text["suite_id"],
                "name": response.response_text["name"],
            }
            for response in responses
        ]
        self.data_provider.update_data(section_data=returned_resources) if len(
            returned_resources
        ) > 0 else "Update skipped"
        return returned_resources, error_message

    def check_missing_test_cases_ids(self, project_id: int) -> (List[int], str):
        """
        Check what test cases id's are missing in DataProvider.
        :project_id: project_id
        :returns: Tuple with list test case ID missing and error string.
        """
        suite_id = self.suites_data_from_provider.suite_id
        test_cases = [
            test_case["case_id"]
            for sections in self.suites_data_from_provider.testsections
            for test_case in sections.testcases
            # TODO: uncomment this/update with main
            # if test_case.case_id is not None
        ]

        response = self.client.send_get(f"get_cases/{project_id}&suite_id={suite_id}")
        if not response.error_message:
            return (
                list(
                    set(test_cases)
                    - set(
                        [
                            test_case.get("id")
                            for test_case in response.response_text["cases"]
                        ]
                    )
                ),
                response.error_message,
            )
        else:
            return [], response.error_message

    def add_cases(self) -> (List[dict], str):
        """
        Add cases that doesn't have ID in DataProvider.
        Runs update_data in data_provider for successfully created resources.
        :returns: Tuple with list of dict created resources and error string.
        """
        add_case_data = self.data_provider.add_cases()
        responses = []
        error_message = ""

        with self.environment.get_progress_bar(
            results_amount=len(add_case_data["bodies"]), prefix="Adding test cases"
        ) as progress_bar:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS_ADD_CASE) as executor:
                futures = {
                    executor.submit(
                        self.client.send_post,
                        f"add_case/{body.pop('section_id')}",
                        body,
                    ): body
                    for body in add_case_data["bodies"]
                }
                responses, error_message = self.handle_futures(
                    futures=futures, action_string="add_case", progress_bar=progress_bar
                )
            if error_message:
                # When error_message is present we cannot be sure that responses contains all added items.
                # Iterate through futures to get all responses from done tasks (not cancelled)
                responses = ApiRequestHandler.retrieve_results_after_cancelling(futures)
        returned_resources = [
            {
                "case_id": response.response_text["id"],
                "section_id": response.response_text["section_id"],
                "title": response.response_text["title"],
            }
            for response in responses
        ]
        self.data_provider.update_data(case_data=returned_resources) if len(
            returned_resources
        ) > 0 else "Update skipped"

        return returned_resources, error_message

    def add_run(self, project_id: int, run_name: str) -> (List[dict], str):
        """
        Creates a new test run.
        :project_id: project_id
        :run_name: run name
        :returns: Tuple with run id and error string.
        """
        add_run_data = self.data_provider.add_run(run_name)
        response = self.client.send_post(f"add_run/{project_id}", add_run_data)
        return response.response_text.get("id"), response.error_message

    def add_results(self, run_id: int) -> (dict, str):
        """
        Adds one or more new test results.
        :run_id: run id
        :returns: Tuple with dict created resources and error string.
        """
        responses = []
        error_message = ""
        add_results_data_chunks = self.data_provider.add_results_for_cases(
            self.environment.batch_size
        )
        results_amount = sum(
            [len(results["results"]) for results in add_results_data_chunks]
        )

        with self.environment.get_progress_bar(
            results_amount=results_amount, prefix="Adding results"
        ) as progress_bar:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS_ADD_RESULTS) as executor:
                futures = {
                    executor.submit(
                        self.client.send_post, f"add_results_for_cases/{run_id}", body
                    ): body
                    for body in add_results_data_chunks
                }
                responses, error_message = self.handle_futures(
                    futures=futures,
                    action_string="add_results",
                    progress_bar=progress_bar,
                )
            if error_message:
                # When error_message is present we cannot be sure that responses contains all added items.
                # Iterate through futures to get all responses from done tasks (not cancelled)
                responses = ApiRequestHandler.retrieve_results_after_cancelling(futures)
        responses = [response.response_text for response in responses]
        return responses, error_message

    def close_run(self, run_id: int) -> (dict, str):
        """
        Closes an existing test run and archives its tests & results.
        :run_id: run id
        :returns: Tuple with dict created resources and error string.
        """
        body = {"run_id": run_id}
        response = self.client.send_post(f"close_run/{run_id}", body)
        return response.response_text, response.error_message

    def handle_futures(self, futures, action_string, progress_bar):
        responses = []
        error_message = ""
        try:
            for future in as_completed(futures):
                arguments = futures[future]
                response = future.result()
                if not response.error_message:
                    responses.append(response)
                    if action_string == "add_results":
                        progress_bar.update(len(arguments["results"]))
                    else:
                        progress_bar.update(1)
                else:
                    error_message = response.error_message
                    self.environment.log(
                        f"\nError during {action_string}. Trying to cancel scheduled tasks."
                    )
                    self.__cancel_running_futures(futures, action_string)
                    break
            else:
                progress_bar.set_postfix_str(s="Done.")
        except KeyboardInterrupt:
            self.__cancel_running_futures(futures, action_string)
            raise KeyboardInterrupt
        return responses, error_message

    @staticmethod
    def retrieve_results_after_cancelling(futures):
        responses = []
        for future in as_completed(futures):
            if not future.cancelled():
                responses.append(future.result())
        return responses

    def __cancel_running_futures(self, futures, action_string):
        self.environment.log(
            f"\nAborting: {action_string}. Trying to cancel scheduled tasks."
        )
        for future in futures:
            future.cancel()
