from ..models import UserV2
from services.provisioning.repositories.db_handler import get_db
db = get_db()

def get_user_from_key(key):
    user = db.query(UserV2).filter(UserV2.api_key == key, UserV2.active == True).first()
    return user