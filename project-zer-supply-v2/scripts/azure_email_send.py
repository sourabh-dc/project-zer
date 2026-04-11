from __future__ import annotations

import os

from supply_v2.email_provider import AzureCommunicationEmailProvider


def main() -> None:
    provider = AzureCommunicationEmailProvider(
        connection_string=os.environ["AZURE_EMAIL_CONNECTION_STRING"],
        sender_address=os.environ["AZURE_EMAIL_SENDER"],
    )
    result = provider.send(
        to_email=os.environ["AZURE_EMAIL_TO"],
        subject="Supply V2 live email check",
        body="Supply V2 Azure email live check.",
    )
    print(result.message_id)


if __name__ == "__main__":
    main()
