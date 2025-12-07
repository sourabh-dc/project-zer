import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import Depends, APIRouter, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

app = APIRouter(prefix="/integration", tags=["Approvals"])

@app.post("/product-sync")
async def product_sync_with_cv():
    pass

@app.post("/customer-sync")
async def customer_sync_with_cv():
    pass