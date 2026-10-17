import requests
import json
import os


class BaseExpectation:
    @staticmethod
    def generate_expectation(
        method: str,
        endpoint: str,
        response_json: dict,
        status_code: int,
        path_params: dict = None,
        query_params: dict = None,
        number_of_calls: int = None,
        priority: int = None,
        expected_headers: dict = None,
        request_body=None,
        request_schema_name: str = None,
    ):
        if request_schema_name is not None:
            this_path = os.path.dirname(__file__)
            schema_rel_path = f"mock_schemas/{request_schema_name}"
            schema_file_obj = open(os.path.join(this_path, schema_rel_path))
            request_schema = json.load(schema_file_obj)
        else:
            request_schema = None
        expectation = BaseExpectation.general_configs(
            method,
            endpoint,
            path_params,
            query_params,
            number_of_calls,
            priority,
            expected_headers,
            request_body,
            request_schema,
        )

        headers = {"Content-Type": ["application/json", "charset=utf-8"]}
        body = {"type": "JSON", "json": response_json}
        expectation["httpResponse"] = {
            "headers": headers,
            "body": body,
            "statusCode": status_code,
        }

        return expectation

    @staticmethod
    def generate_error(
        method: str,
        endpoint: str,
        error_json,
        path_params: dict = None,
        query_params: dict = None,
        number_of_calls: int = None,
        priority: int = None,
        expected_headers: dict = None,
        request_body=None,
    ):
        expectation = BaseExpectation.general_configs(
            method,
            endpoint,
            path_params,
            query_params,
            number_of_calls,
            priority,
            expected_headers,
            request_body,
            None,
        )
        expectation["httpError"] = error_json

        return expectation

    @staticmethod
    def general_configs(
        method,
        endpoint,
        path_params,
        query_params,
        number_of_calls,
        priority,
        expected_headers,
        request_body,
        request_schema,
    ):
        expectation = {}
        expectation["httpRequest"] = {"method": method.upper(), "path": endpoint}

        if path_params is not None:
            expectation["httpRequest"]["pathParameters"] = path_params

        if expected_headers is not None:
            expectation["httpRequest"]["headers"] = expected_headers

        if query_params is not None:
            expectation["httpRequest"]["queryStringParameters"] = query_params
        if request_body is not None:
            expectation["httpRequest"]["body"] = {"type": "JSON", "json": request_body}
        elif request_schema is not None:
            expectation["httpRequest"]["body"] = {
                "type": "JSON_SCHEMA",
                "jsonSchema": request_schema,
            }
        if number_of_calls is not None:
            expectation["times"] = {
                "remainingTimes": number_of_calls,
                "unlimited": False,
            }
        if priority is not None:
            expectation["priority"] = priority
        return expectation


class Mock(object):
    def __init__(
        self,
        host=os.environ.get("MOCK_HOST", os.environ.get("SERVER_LOCALHOST", "localhost")),
        port=os.environ.get("MOCK_PORT", "1080")
    ):
        self.port = port
        self.host = host
        self.url = f"http://{self.host}:{self.port}/mockserver"

    def clear(self):
        response = requests.request("PUT", self.url + "/reset")
        if response.status_code != 200:
            raise Exception(f"Failed to clear mockserver at {self.url}")
        return response

    def add_expectations(self, expectations):
        headers = {"Content-type": "application/json"}
        resp = requests.request("PUT", self.url + "/expectation", json=expectations, headers=headers)
        if resp.status_code not in [200, 201]:
            raise Exception(f"Failed to add expectations at {self.url}")
        return resp

    def load_expectations(self, path):
        with open(path, "rt") as f:
            expectations = json.load(f)

        if isinstance(expectations, list):
            for expectation in expectations:
                self.add_expectations(expectation)
        else:
            self.add_expectations(expectations)

    def generate_expectation(
        self,
        method: str,
        endpoint: str,
        response_json: dict,
        status_code: int,
        path_params: dict = None,
        query_params: dict = None,
    ):
        expectation = dict()
        expectation["httpRequest"] = {"method": method.upper(), "path": endpoint}
        headers = {"Content-Type": ["application/json", "charset=utf-8"]}

        if path_params is not None:
            expectation["httpRequest"]["pathParameters"] = path_params

        if query_params is not None:
            expectation["httpRequest"]["queryStringParameters"] = query_params

        body = {"type": "JSON", "json": response_json}
        expectation["httpResponse"] = {
            "headers": headers,
            "body": body,
            "statusCode": status_code,
        }
        self.add_expectations(expectation)

    def verify(self, path, time_at_least, time_at_most):
        payload = {
            "httpRequest": {"path": path},
            "times": {"atLeast": time_at_least, "atMost": time_at_most},
        }
        response = requests.request("PUT", self.url + "/verify", json=payload)
        return response

    def assert_times(self, path, times):
        with open(path, "rt") as f:
            expectations = json.load(f)
            req_path = expectations[0]["httpRequest"]["path"]
        return self.verify(req_path, times, times)

    def retrieve_requests(self, method=None, path=None):
        uri = f"{self.url}/retrieve?type=REQUESTS"
        payload = {}
        if method is not None:
            payload["method"] = method
        if path is not None:
            payload["path"] = path

        response = requests.request("PUT", uri, json=payload)
        return response.json()
