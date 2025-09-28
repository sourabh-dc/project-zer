from fastapi import APIRouter, Body, HTTPException
from ..providers.aifi import AiFiProvider
from ..schemas.entry import EntryCodeCreate, EntryVerifyRequest, EntryVerifyResponse
from typing import Optional

router = APIRouter(prefix="/entry", tags=["entry"])
provider = AiFiProvider()

@router.post("/codes")
async def create_entry_code(payload: dict = Body(...)):
    try:
        return await provider.create_entry_code(payload)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"provider_error: {e}")

@router.post("/verify", response_model=EntryVerifyResponse)
async def verify_entry_code(req: EntryVerifyRequest, store_id: int = Body(..., embed=True), entry_id: int = Body(..., embed=True)):
    try:
        return await provider.verify_entry_code(
            req.verification_code,
            store_id=store_id,
            entry_id=entry_id,
            group_size=req.group_size,
            check_in_device_id=req.check_in_device_id,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"provider_error: {e}")