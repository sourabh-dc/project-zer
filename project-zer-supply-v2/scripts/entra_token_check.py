from __future__ import annotations

import os

from supply_v2.auth import _decode_bearer_token


def main() -> None:
    token = os.environ["SUPPLY_V2_BEARER_TOKEN"]
    claims = _decode_bearer_token(token)
    print({"sub": claims.get("sub"), "aud": claims.get("aud"), "tid": claims.get("tid")})


if __name__ == "__main__":
    main()
