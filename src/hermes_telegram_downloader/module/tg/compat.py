from types import SimpleNamespace

from telethon.utils import get_peer_id


def wrap_message(msg):
    if msg is None or getattr(msg, "from_user", None) is not None:
        return msg

    class _User:
        def __init__(self, uid):
            self.id = uid

    class _Wrapped:
        def __init__(self, m):
            self._m = m
            self.id = m.id
            self.text = m.message or ""
            self.media = m.media
            self.from_user = _User(m.sender_id)
            chat_id = getattr(m, "chat_id", None) or m.sender_id
            self.chat = SimpleNamespace(id=chat_id)
            self.forward_from_chat = None
            self.forward_from_message_id = 0
            fwd = getattr(m, "fwd_from", None)
            if fwd:
                self.forward_from_message_id = getattr(fwd, "channel_post", 0) or 0
                peer = getattr(fwd, "from_id", None)
                if peer is not None:
                    try:
                        pid = get_peer_id(peer)
                    except Exception:
                        pid = None
                    self.forward_from_chat = SimpleNamespace(
                        id=pid,
                        title=getattr(fwd, "from_name", None) or "",
                        username=None,
                    )

        def __getattr__(self, name):
            return getattr(self._m, name)

    return _Wrapped(msg)


def _parse_mode(parse_mode):
    if parse_mode is None:
        return None
    s = str(parse_mode)
    if "HTML" in s.upper() or s == "html":
        return "html"
    if "MARKDOWN" in s.upper() or s in ("md", "markdown"):
        return "md"
    return parse_mode


class BotClientProxy:
    def __init__(self, client):
        self._c = client
        self.is_connected = True

    def __getattr__(self, name):
        return getattr(self._c, name)

    async def send_message(
        self,
        entity,
        text,
        parse_mode=None,
        reply_to_message_id=None,
        reply_to=None,
        buttons=None,
        reply_markup=None,
        **kwargs,
    ):
        return await self._c.send_message(
            entity,
            text,
            parse_mode=_parse_mode(parse_mode),
            reply_to=reply_to or reply_to_message_id,
            buttons=buttons or reply_markup,
        )

    async def edit_message_text(
        self, entity, message_id, text, parse_mode=None, **kwargs
    ):
        return await self._c.edit_message(
            entity, message_id, text, parse_mode=_parse_mode(parse_mode)
        )

    async def get_me(self):
        return await self._c.get_me()

    async def start(self, bot_token=None, **kwargs):
        if bot_token:
            return await self._c.start(bot_token=bot_token)
        return await self._c.start()

    async def stop(self):
        self.is_connected = False
        return await self._c.disconnect()

    async def disconnect(self):
        self.is_connected = False
        return await self._c.disconnect()

    async def set_bot_commands(self, _commands):
        return None

    def add_handler(self, *args, **kwargs):
        return None


class UserClientProxy:
    def __init__(self, client):
        self._c = client

    def __getattr__(self, name):
        return getattr(self._c, name)

    async def get_messages(self, chat_id, message_ids=None, ids=None, **kwargs):
        mid = ids if ids is not None else message_ids
        msg = await self._c.get_messages(chat_id, ids=mid)
        if isinstance(msg, list):
            return msg[0] if msg else None
        return msg

    async def get_chat(self, ident):
        return await self._c.get_entity(ident)

    async def get_me(self):
        return await self._c.get_me()
