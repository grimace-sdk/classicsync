import random
from datetime import datetime

USER_NAME_LIMIT = 20
USER_ID_MINIMUM = 0x100
RANDOM_LIMIT = 0x7FFF


def new_identifier(minimum=1):
    return random.randint(minimum, RANDOM_LIMIT)


async def set_user(client, name, pc_id):
    if not 1 <= len(name) <= USER_NAME_LIMIT:
        raise ValueError(f"the HotSync user name must be 1 to {USER_NAME_LIMIT} characters")
    user = await client.read_user_info()
    user_id = user.user_id or new_identifier(USER_ID_MINIMUM)
    await client.write_user_info(user_id, user.viewer_id, pc_id, datetime.now().replace(microsecond=0), name)
    return user_id
