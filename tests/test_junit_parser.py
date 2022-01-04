from pathlib import Path
import pytest
import json
from junitparser import JUnitXmlError
from trcli.readers.junit_xml import JunitParser
from typing import Union
from dataclasses import asdict
from trcli.data_classes.dataclass_testrail import TestRailSuite


class TestJunitParser:
    @pytest.mark.parametrize(
        "input_xml_path, expected_path",
        [
            (
                Path(__file__).parent / "test_data/XML/no_root.xml",
                Path(__file__).parent / "test_data/json/no_root.json",
            ),
            (
                Path(__file__).parent / "test_data/XML/root.xml",
                Path(__file__).parent / "test_data/json/root.json",
            ),
            (
                Path(__file__).parent / "test_data/XML/empty.xml",
                Path(__file__).parent / "test_data/json/empty.json",
            ),
        ],
        ids=[
            "XML without testsuites root",
            "XML with testsuites root",
            "XML with no data",
        ],
    )
    def test_junit_xml_parser_valid_files(
        self, input_xml_path: Union[str, Path], expected_path: str
    ):
        file_reader = JunitParser(input_xml_path)
        read_junit = self.__clear_unparsable_junit_elements(file_reader.parse_file())
        parsing_result_json = asdict(read_junit)
        file_json = open(expected_path)
        expected_json = json.load(file_json)
        assert (
            parsing_result_json == expected_json
        ), "Result of parsing Junit XML is different than expected"

    def test_junit_xml_parser_invalid_file(self):
        file_reader = JunitParser("test_data/XML/invalid.xml")
        with pytest.raises(JUnitXmlError):
            file_reader.parse_file()

    def test_junit_xml_parser_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            JunitParser("not_found.xml")

    def __clear_unparsable_junit_elements(
        self, test_rail_suite: TestRailSuite
    ) -> TestRailSuite:
        """helper method to delete junit_result_unparsed field,
        which asdict() method of dataclass can't handle"""
        for section in test_rail_suite.testsections:
            for case in section.testcases:
                case.result.junit_result_unparsed = []
        return test_rail_suite
