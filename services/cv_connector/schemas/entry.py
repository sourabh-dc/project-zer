from pydantic import BaseModel

class EntryCodeCreate(BaseModel):
    userExternalId: str | None = None
    groupSize: int | None = None
    # add any AiFi-supported fields you need (validity, role, metadata, etc.)
    # arbitrary passthrough:
    extra: dict | None = None

class EntryVerifyRequest(BaseModel):
    verification_code: str
    group_size: int | None = None
    check_in_device_id: int | None = None

class EntryVerifyResponse(BaseModel):
    status: str
    sessionId: str | None = None
    reason: str | None = None
    shoppersRole: str | None = None