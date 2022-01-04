from typing import Tuple, Callable

from trcli.api.api_client import APIClient
from trcli.cli import Environment
from trcli.api.api_request_handler import ApiRequestHandler
from trcli.constants import PROMPT_MESSAGES, FAULT_MAPPING, SuiteModes
from trcli.data_classes.dataclass_testrail import TestRailSuite
from trcli.readers.file_parser import FileParser
from trcli.constants import ProjectErrors
import time


class ResultsUploader:
    """
    Class to be used to upload the results to TestRail.
    Initialized with environment object and result file parser object (any parser derived from FileParser).
    """

    def __init__(self, environment: Environment, result_file_parser: FileParser):
        self.environment = environment
        self.result_file_parser = result_file_parser
        self.parsed_data: TestRailSuite = self.result_file_parser.parse_file()
        # TODO: Remove before creating PR
        if not self.parsed_data.name:
            self.parsed_data.name = "Auto created suite name_" + str(time.time())
        if self.environment.suite_id:
            self.parsed_data.suite_id = self.environment.suite_id
        self.api_request_handler = ApiRequestHandler(
            environment=self.environment,
            api_client=self.__instantiate_api_client(),
            suites_data=self.parsed_data,
        )
        if self.environment.suite_id:
            self.api_request_handler.data_provider.update_data(
                [{"suite_id": self.environment.suite_id}]
            )

    def upload_results(self):
        """
        Does all the job needed to upload the results parsed from result files to TestRail.
        If needed missing items like suite/section/test case would be added to TestRail.
        Exits with result code 1 printing proper message to the user in case of a failure
        or with result code 0 if succeeds.
        """
        start = time.time()
        project_data = self.api_request_handler.get_project_id(self.environment.project)
        if project_data.project_id == ProjectErrors.not_existing_project:
            self.environment.log(project_data.error_message)
            exit(1)
        elif project_data.project_id == ProjectErrors.other_error:
            self.environment.log(
                FAULT_MAPPING["error_checking_project"].format(
                    error_message=project_data.error_message
                )
            )
            exit(1)
        else:
            suite_id, result_code = self.__get_suite_id(
                project_id=project_data.project_id, suite_mode=project_data.suite_mode
            )
            if result_code == -1:
                exit(1)

            added_sections, result_code = self.__add_missing_sections(
                project_data.project_id
            )
            if result_code == -1:
                exit(1)

            start_adding_test_cases = time.time()
            added_test_cases, result_code = self.__add_missing_test_cases(
                project_data.project_id
            )
            if result_code == -1:
                exit(1)
            stop_adding_test_cases = time.time()
            if not self.environment.run_id:
                self.environment.log(f"Creating test run. ", new_line=False)
                added_run, error_message = self.api_request_handler.add_run(
                    project_data.project_id, self.environment.title
                )
                if error_message:
                    self.environment.log(error_message)
                    exit(1)
                self.environment.log("Done.")
                run_id = added_run
            else:
                run_id = self.environment.run_id
            start_adding_results = time.time()
            added_results, error_message = self.api_request_handler.add_results(run_id)
            if error_message:
                self.environment.log(error_message)
                exit(1)

            stop_adding_results = time.time()
            self.environment.log("Closing test run. ", new_line=False)
            response, error_message = self.api_request_handler.close_run(run_id)
            if error_message:
                self.environment.log(error_message)
                exit(1)
            self.environment.log("Done.")
        stop = time.time()

        self.environment.log(f"Executed in: {stop - start}")
        self.environment.log(
            f"Adding test cases in: {stop_adding_test_cases - start_adding_test_cases}"
        )
        self.environment.log(
            f"Adding results in: {stop_adding_results - start_adding_results}"
        )

    def __get_suite_id(self, project_id: int, suite_mode: int) -> Tuple[int, int]:
        """
        Gets and checks suite ID for specified project_id.
        Depending on the entry conditions (suite ID provided or not, suite mode, project ID)
        it will:
            * check if specified suite ID exists and is correct
            * try to create missing suite ID
            * try to fetch suite ID from TestRail
        Returns suite ID if succeeds or -1 in case of failure. Proper information is printed
        on failure.
        """
        suite_id = -1
        result_code = -1
        if not self.api_request_handler.suites_data_from_provider.suite_id:
            if suite_mode == SuiteModes.multiple_suites:
                prompt_message = PROMPT_MESSAGES["create_new_suite"].format(
                    suite_name=self.api_request_handler.suites_data_from_provider.name,
                    project_name=self.environment.project,
                )
                adding_message = (
                    f"Adding missing suites to project {self.environment.project}."
                )
                fault_message = FAULT_MAPPING["no_user_agreement"].format(type="suite")
                added_suites, result_code = self.__prompt_user_and_add_items(
                    prompt_message=prompt_message,
                    adding_message=adding_message,
                    fault_message=fault_message,
                    add_function=self.api_request_handler.add_suites,
                    project_id=project_id,
                )
                if added_suites:
                    suite_id = added_suites[0]["suite_id"]
                else:
                    suite_id = -1
            elif suite_mode == SuiteModes.single_suite_baselines:
                suite_ids, error_message = self.api_request_handler.get_suite_ids(
                    project_id=project_id
                )
                if error_message:
                    self.environment.log(error_message)
                else:
                    if len(suite_ids) > 1:
                        self.environment.log(
                            FAULT_MAPPING[
                                "not_unique_suite_id_single_suite_baselines"
                            ].format(project_name=self.environment.project)
                        )
                    else:
                        suite_id = suite_ids[0]
                        result_code = 1
            elif suite_mode == SuiteModes.single_suite:
                suite_ids, error_message = self.api_request_handler.get_suite_ids(
                    project_id=project_id
                )
                if error_message:
                    self.environment.log(error_message)
                else:
                    suite_id = suite_ids[0]
                    result_code = 1
            else:
                self.environment.log(
                    FAULT_MAPPING["unknown_suite_mode"].format(suite_mode=suite_mode)
                )
        else:
            suite_id, result_code = self.__check_suite_id(
                self.api_request_handler.suites_data_from_provider.suite_id, project_id
            )
        return suite_id, result_code

    def __check_suite_id(self, suite_id: int, project_id: int) -> Tuple[int, int]:
        """
        Checks that suite ID is correct.
        Returns suite ID is succeeds or -1 on failure. Proper information will be printed
        on failure.
        """
        result_code = -1
        if self.api_request_handler.check_suite_id(project_id):
            result_code = 1
        else:
            self.environment.log(
                FAULT_MAPPING["missing_suite"].format(suite_id=suite_id)
            )
        return suite_id, result_code

    def __add_missing_sections(self, project_id: int) -> Tuple[list, int]:
        """
        Checks for missing sections in specified project. Add missing sections if user agrees to
        do so. Returns list of added section IDs if succeeds or empty list with result_code set to
        -1.
        """
        result_code = -1
        added_sections = []
        (
            missing_sections,
            error_message,
        ) = self.api_request_handler.check_missing_section_ids(project_id)
        if missing_sections:
            prompt_message = PROMPT_MESSAGES["create_missing_sections"].format(
                project_name=self.environment.project
            )
            adding_message = "Adding missing sections to the suite."
            fault_message = FAULT_MAPPING["no_user_agreement"].format(type="sections")
            added_sections, result_code = self.__prompt_user_and_add_items(
                prompt_message=prompt_message,
                adding_message=adding_message,
                fault_message=fault_message,
                add_function=self.api_request_handler.add_sections,
                project_id=project_id,
            )
        else:
            if error_message:
                self.environment.log(
                    FAULT_MAPPING["error_checking_missing_item"].format(
                        missing_item="missing sections", error_message=error_message
                    )
                )
            else:
                result_code = 1
        return added_sections, result_code

    def __add_missing_test_cases(self, project_id: int) -> Tuple[list, int]:
        """
        Checks for missing test cases in specified project. Add missing test cases if user agrees to
        do so. Returns list of added test case IDs if succeeds or empty list with result_code set to
        -1.
        """
        added_cases = []
        result_code = -1
        (
            missing_test_cases,
            error_message,
        ) = self.api_request_handler.check_missing_test_cases_ids(project_id)
        if missing_test_cases:
            prompt_message = PROMPT_MESSAGES["create_missing_test_cases"].format(
                project_name=self.environment.project
            )
            adding_message = "Adding missing test cases to the suite."
            fault_message = FAULT_MAPPING["no_user_agreement"].format(type="test cases")
            added_cases, result_code = self.__prompt_user_and_add_items(
                prompt_message=prompt_message,
                adding_message=adding_message,
                fault_message=fault_message,
                add_function=self.api_request_handler.add_cases,
            )
        else:
            if error_message:
                self.environment.log(
                    FAULT_MAPPING["error_checking_missing_item"].format(
                        missing_item="missing test cases", error_message=error_message
                    )
                )
            else:
                result_code = 1
        return added_cases, result_code

    def __prompt_user_and_add_items(
        self,
        prompt_message,
        adding_message,
        fault_message,
        add_function: Callable,
        project_id: int = None,
    ):
        added_items = []
        result_code = -1
        if self.environment.get_prompt_response_for_auto_creation(prompt_message):
            self.environment.log(adding_message)
            if project_id:
                added_items, error_message = add_function(project_id=project_id)
            else:
                added_items, error_message = add_function()
            if error_message:
                self.environment.log(error_message)
            else:
                result_code = 1
        else:
            self.environment.log(fault_message)
        return added_items, result_code

    def __instantiate_api_client(self) -> APIClient:
        """
        Instantiate api client with needed attributes taken from environment.
        """
        logging_function = self.environment.vlog
        if self.environment.timeout:
            api_client = APIClient(
                self.environment.host,
                logging_function=logging_function,
                timeout=self.environment.timeout,
            )
        else:
            api_client = APIClient(
                self.environment.host, logging_function=logging_function
            )
        api_client.username = self.environment.username
        api_client.password = self.environment.password
        api_client.api_key = self.environment.key
        return api_client
