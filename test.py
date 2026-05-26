#!/usr/bin/env python3

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any


FAKE_XFF_IPS = ["8.8.8.8", "1.1.1.1"]
FAKE_VISITED_NGINX = ["nginx-1", "nginx-2", "nginx-3"]


@dataclass
class CurlResult:
    status: int
    body: str
    json_body: dict[str, Any] | None


class TestFailure(Exception):
    pass


def run_curl(url: str, headers: list[str] | None = None, timeout: int = 10) -> CurlResult:
    command = [
        "curl",
        "-sS",
        "--max-time",
        str(timeout),
    ]

    for header in headers or []:
        command.extend(["-H", header])

    command.append(url)

    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    if completed.returncode != 0:
        raise TestFailure(
            "curl failed\n"
            f"command: {' '.join(command)}\n"
            f"exit code: {completed.returncode}\n"
            f"stderr: {completed.stderr.strip()}"
        )

    body = completed.stdout.strip()

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = None

    return CurlResult(
        status=completed.returncode,
        body=body,
        json_body=parsed,
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise TestFailure(message)


def get_json(result: CurlResult) -> dict[str, Any]:
    require(result.json_body is not None, f"Response is not valid JSON:\n{result.body}")
    return result.json_body or {}


def split_csv(value: str | None) -> list[str]:
    if not value:
        return []

    return [part.strip() for part in value.split(",") if part.strip()]


def assert_no_fake_ips(x_forwarded_for: str | None) -> None:
    require(x_forwarded_for is not None, "x_forwarded_for is missing")

    for fake_ip in FAKE_XFF_IPS:
        require(
            fake_ip not in x_forwarded_for,
            f"Fake IP {fake_ip} leaked into X-Forwarded-For: {x_forwarded_for}",
        )


def assert_xff_chain_shape(payload: dict[str, Any]) -> None:
    xff = payload.get("headers").get("X-Forwarded-For")
    visited = payload.get("headers").get("X-Visited-Nginx")

    require(isinstance(xff, str) and xff, "x_forwarded_for must be a non-empty string")
    require(isinstance(visited, str) and visited, "x_visited_nginx must be a non-empty string")

    xff_items = split_csv(xff)
    visited_items = split_csv(visited)

    require(
        len(xff_items) >= 2,
        "X-Forwarded-For must contain at least client IP and one nginx IP. "
        f"Actual value: {xff}",
    )

    require(
        len(xff_items) == len(visited_items) + 1,
        "X-Forwarded-For length must be equal to client IP + visited nginx count. "
        f"xff={xff_items}, visited={visited_items}",
    )

    require(
        len(visited_items) == len(set(visited_items)),
        f"Visited nginx chain contains duplicates, possible cycle: {visited}",
    )


def test_basic_request(url: str) -> tuple[str, str]:
    result = run_curl(url)
    payload = get_json(result)

    assert_xff_chain_shape(payload)
    assert_no_fake_ips(payload.get("x_forwarded_for"))

    return payload["headers"]["X-Forwarded-For"], payload["headers"]["X-Visited-Nginx"]


def test_fake_x_forwarded_for_is_dropped(url: str) -> tuple[str, str]:
    result = run_curl(
        url,
        headers=["X-Forwarded-For: 8.8.8.8, 1.1.1.1"],
    )
    payload = get_json(result)

    assert_xff_chain_shape(payload)
    assert_no_fake_ips(payload.get("x_forwarded_for"))

    return payload["headers"]["X-Forwarded-For"], payload["headers"]["X-Visited-Nginx"]


def test_fake_x_visited_nginx_is_dropped(url: str) -> tuple[str, str]:
    result = run_curl(
        url,
        headers=[
            "X-Forwarded-For: 8.8.8.8, 1.1.1.1",
            "X-Visited-Nginx: nginx-1,nginx-2,nginx-3",
        ],
    )
    payload = get_json(result)

    assert_xff_chain_shape(payload)
    assert_no_fake_ips(payload.get("x_forwarded_for"))

    visited_items = split_csv(payload.get("x_visited_nginx"))

    require(
        visited_items != FAKE_VISITED_NGINX,
        "User-provided X-Visited-Nginx was not reset by the first nginx",
    )

    return payload["headers"]["X-Forwarded-For"], payload["headers"]["X-Visited-Nginx"]


def test_multiple_requests(url: str, requests_count: int) -> set[str]:
    routes = set()

    for _ in range(requests_count):
        result = run_curl(url)
        payload = get_json(result)

        assert_xff_chain_shape(payload)
        assert_no_fake_ips(payload.get("headers").get("X-Forwarded-For"))

        routes.add(payload["headers"]["X-Visited-Nginx"])

    return routes


def print_ok(name: str, details: str | None = None) -> None:
    print(f"[OK] {name}")
    if details:
        print(details)


def print_warn(message: str) -> None:
    print(f"[WARN] {message}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run curl-based tests for X-Forwarded-For nginx stand."
    )

    parser.add_argument(
        "--url",
        default="http://localhost:8080",
        help="Public stand URL. Default: http://localhost:8080",
    )

    parser.add_argument(
        "--requests",
        type=int,
        default=10,
        help="Number of ordinary requests for route sampling. Default: 10.",
    )

    parser.add_argument(
        "--require-multiple-routes",
        action="store_true",
        help=(
            "Fail if repeated requests produce only one route. "
            "Useful when FORWARD_PROBABILITY is greater than 0."
        ),
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="curl timeout in seconds. Default: 10.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if shutil.which("curl") is None:
        print("curl is not installed or not available in PATH", file=sys.stderr)
        return 1

    try:
        xff, visited = test_basic_request(args.url)
        print_ok(
            "ordinary request contains client IP and nginx chain",
            f"  x_forwarded_for: {xff}\n  x_visited_nginx: {visited}",
        )

        xff, visited = test_fake_x_forwarded_for_is_dropped(args.url)
        print_ok(
            "fake X-Forwarded-For is dropped",
            f"  x_forwarded_for: {xff}\n  x_visited_nginx: {visited}",
        )

        xff, visited = test_fake_x_visited_nginx_is_dropped(args.url)
        print_ok(
            "fake X-Visited-Nginx does not control route",
            f"  x_forwarded_for: {xff}\n  x_visited_nginx: {visited}",
        )

        routes = test_multiple_requests(args.url, args.requests)
        print_ok(
            f"{args.requests} repeated requests are valid",
            "  unique routes:\n" + "\n".join(f"  - {route}" for route in sorted(routes)),
        )

        if len(routes) < 2:
            message = (
                "Only one unique route was observed. This can be normal when "
                "FORWARD_PROBABILITY=0 or because of random choice on a small sample."
            )

            if args.require_multiple_routes:
                raise TestFailure(message)

            print_warn(message)

    except TestFailure as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        return 1

    print("All curl-based tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
