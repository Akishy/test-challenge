#!/usr/bin/env python3

import argparse
from pathlib import Path
from string import Template


ROOT_DIR = Path(__file__).resolve().parent

TEMPLATES_DIR = ROOT_DIR / "templates"
COMPOSE_TEMPLATE_PATH = TEMPLATES_DIR / "compose.yaml.tpl"
HAPROXY_TEMPLATE_PATH = TEMPLATES_DIR / "haproxy.cfg.tpl"

COMPOSE_OUTPUT_PATH = ROOT_DIR / "compose.yaml"
HAPROXY_OUTPUT_PATH = ROOT_DIR / "lb" / "haproxy.cfg"


def read_template(path: Path) -> Template:
    if not path.exists():
        raise FileNotFoundError(f"Template file not found: {path}")

    return Template(path.read_text(encoding="utf-8"))


def render_template(path: Path, **kwargs: str) -> str:
    template = read_template(path)
    return template.substitute(**kwargs)


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_lb_depends_on(nginx_total: int) -> str:
    return "\n".join(
        f"      - nginx-{index}"
        for index in range(1, nginx_total + 1)
    )


def build_nginx_services(nginx_total: int) -> str:
    services = []

    for index in range(1, nginx_total + 1):
        service_name = f"nginx-{index}"

        services.append(
            f"""  {service_name}:
    <<: *openresty-common
    hostname: {service_name}
    environment:
      <<: *openresty-env
      NGINX_NAME: "{service_name}"
"""
        )

    return "\n".join(services)


def build_haproxy_backend_servers(nginx_total: int) -> str:
    return "\n".join(
        f"    server nginx-{index} nginx-{index}:80 send-proxy"
        for index in range(1, nginx_total + 1)
    )


def generate_compose(nginx_total: int, forward_probability: float) -> str:
    return render_template(
        COMPOSE_TEMPLATE_PATH,
        nginx_total=str(nginx_total),
        forward_probability=str(forward_probability),
        lb_depends_on=build_lb_depends_on(nginx_total),
        nginx_services=build_nginx_services(nginx_total),
    )


def generate_haproxy(nginx_total: int) -> str:
    return render_template(
        HAPROXY_TEMPLATE_PATH,
        backend_servers=build_haproxy_backend_servers(nginx_total),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate docker-compose stand with N OpenResty/nginx reverse proxies "
            "for X-Forwarded-For testing."
        )
    )

    parser.add_argument(
        "nginx_total",
        type=int,
        help="Number of nginx hosts. Must be >= 3.",
    )

    parser.add_argument(
        "-p",
        "--probability",
        type=float,
        default=0.5,
        help=(
            "Probability that each nginx forwards request to another nginx "
            "instead of the app. Default: 0.5."
        ),
    )

    return parser.parse_args()


def validate_args(nginx_total: int, forward_probability: float) -> None:
    if nginx_total < 3:
        raise ValueError("nginx_total must be >= 3")

    if not 0 <= forward_probability <= 1:
        raise ValueError("probability must be between 0 and 1")


def main() -> None:
    args = parse_args()

    validate_args(
        nginx_total=args.nginx_total,
        forward_probability=args.probability,
    )

    compose_content = generate_compose(
        nginx_total=args.nginx_total,
        forward_probability=args.probability,
    )

    haproxy_content = generate_haproxy(
        nginx_total=args.nginx_total,
    )

    write_file(COMPOSE_OUTPUT_PATH, compose_content)
    write_file(HAPROXY_OUTPUT_PATH, haproxy_content)

    print(f"Generated stand with {args.nginx_total} nginx hosts.")
    print(f"Forward probability: {args.probability}")
    print(f"Created: {COMPOSE_OUTPUT_PATH.relative_to(ROOT_DIR)}")
    print(f"Created: {HAPROXY_OUTPUT_PATH.relative_to(ROOT_DIR)}")
    print()
    print("Run:")
    print("  docker compose up -d")
    print()
    print("Test:")
    print("  curl -s http://localhost:8080")
    print("  python3.12 test.py")


if __name__ == "__main__":
    main()