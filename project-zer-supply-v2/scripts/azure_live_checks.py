from __future__ import annotations

import json
import subprocess
from pathlib import Path
import shlex


ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str]) -> dict:
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def main() -> None:
    service_bus = _run(
        [
            "az",
            "servicebus",
            "namespace",
            "authorization-rule",
            "keys",
            "list",
            "--resource-group",
            "RG_Zeroque",
            "--namespace-name",
            "zeroque",
            "--name",
            "RootManageSharedAccessKey",
            "-o",
            "json",
        ]
    )
    communication = _run(
        [
            "az",
            "communication",
            "list-key",
            "--name",
            "zeroque-communication-service",
            "--resource-group",
            "RG_Zeroque",
            "-o",
            "json",
        ]
    )
    domain = _run(
        [
            "az",
            "resource",
            "show",
            "--ids",
            "/subscriptions/034e3bbe-3173-49da-af03-bbcf44401ef7/resourceGroups/RG_Zeroque/providers/Microsoft.Communication/emailServices/zq-email/domains/AzureManagedDomain",
            "-o",
            "json",
        ]
    )
    sender = f"DoNotReply@{domain['properties']['fromSenderDomain']}"
    env_file = ROOT / ".env.azure.live"
    env_file.write_text(
        "\n".join(
            [
                "SUPPLY_V2_AUTH_MODE=entra",
                "SUPPLY_V2_ENTRA_TENANT_ID=0a5984c6-0ba5-4431-be9d-9c7f64cf7e1c",
                "SUPPLY_V2_ENTRA_CLIENT_ID=9c67784b-9ab5-4ecf-84bc-9924c3ea4dc4",
                "SUPPLY_V2_BROKER_BACKEND=azure_service_bus",
                "SUPPLY_V2_EMAIL_BACKEND=azure",
                f"AZURE_SERVICE_BUS_CONNECTION_STRING={shlex.quote(service_bus['primaryConnectionString'])}",
                "AZURE_SERVICE_BUS_QUEUE_NAME=outbox-task-queue",
                f"AZURE_EMAIL_CONNECTION_STRING={shlex.quote(communication['primaryConnectionString'])}",
                f"AZURE_EMAIL_SENDER={shlex.quote(sender)}",
            ]
        )
        + "\n"
    )
    print(str(env_file))


if __name__ == "__main__":
    main()
