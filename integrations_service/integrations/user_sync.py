from typing import Dict

from sqlalchemy.orm import Session

from integrations_service.Models import User
from integrations_service.core.db_config import SessionLocal
from integrations_service.core.helpers import aifi_services as aifi


async def sync_users(delete_remote_missing: bool = False) -> Dict:
    """Reconcile and upsert users to AiFi customers. Optionally delete remote items missing locally."""
    remote_customers = await aifi.fetch_customers()
    existing_by_external = {
        str(c.get("externalId")): c for c in remote_customers if c.get("externalId")
    }

    with SessionLocal() as db:
        users = db.query(User).filter(User.active == True).all()  # noqa: E712

        created = updated = skipped = 0
        results = []

        for user in users:
            if not user.email:
                skipped += 1
                results.append(
                    {"externalId": str(user.user_id), "status": "skip", "reason": "missing_email"}
                )
                continue

            res = await aifi.upsert_customer(user, existing_by_external)
            if res.get("remote_id"):
                db.query(User).filter(User.user_id == user.user_id).update(
                    {"aifi_customer_id": str(res["remote_id"])}
                )
                existing_by_external[str(user.user_id)] = {"id": res["remote_id"], "externalId": str(user.user_id)}
            results.append(res)
            status = res.get("status")
            if status == "created":
                created += 1
            elif status == "updated":
                updated += 1
            else:
                skipped += 1

        # Reconcile IDs from remote externalId mapping
        for ext, remote in existing_by_external.items():
            rid = remote.get("id") or remote.get("customerId")
            if not rid:
                continue
            usr = db.query(User).filter(User.user_id == ext).first()
            if usr and not usr.aifi_customer_id:
                usr.aifi_customer_id = str(rid)
                db.add(usr)

        db.commit()

        local_ids = {str(u.user_id) for u in users}
        remote_ids = set(existing_by_external.keys())
        missing_on_remote = sorted(list(local_ids - remote_ids))
        missing_on_local = sorted(list(remote_ids - local_ids))

        deleted_remote = 0
        if delete_remote_missing and missing_on_local:
            for ext in missing_on_local:
                remote = existing_by_external.get(ext)
                if remote and remote.get("id"):
                    resp = await aifi.delete_customer(str(remote["id"]))
                    if resp.status_code in (200, 204, 404):
                        deleted_remote += 1
                    results.append(
                        {
                            "externalId": ext,
                            "action": "delete_remote",
                            "status_code": resp.status_code,
                            "body": resp.text[:200],
                        }
                    )

        return {
            "total_local": len(users),
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "missing_on_remote": missing_on_remote,
            "missing_on_local": missing_on_local,
            "deleted_remote": deleted_remote,
            "results": results,
        }

