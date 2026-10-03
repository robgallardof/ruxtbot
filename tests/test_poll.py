import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from rustbot.__main__ import RustBot
from rustbot.tracking import Store
import pytest

@pytest.mark.parametrize('initial,current,send_error,expected_messages,expected_state',[(None,True,False,0,1),(True,False,False,1,0),(False,True,False,1,1),(True,None,False,0,1),(True,False,True,1,1)])
def test_poll_transition_and_delivery(tmp_path,initial,current,send_error,expected_messages,expected_state):
    store=Store(str(tmp_path/'tracker.db'));store.add('bm:42','1',123,'Player @everyone')
    w=store.watches()[0]
    if initial is not None:store.set_state(w,initial)
    role=SimpleNamespace(name='wipe',id=55,mention='<@&55>',mentionable=True)
    channel=SimpleNamespace(guild=SimpleNamespace(id=9,roles=[role]),send=AsyncMock(side_effect=RuntimeError('network') if send_error else None))
    bot=SimpleNamespace(store=store,bm=SimpleNamespace(player_online=AsyncMock(return_value=current)),last_poll={},get_channel=lambda _:channel,settings=SimpleNamespace(poll_interval=10),directory=SimpleNamespace(name=lambda _:'US Medium'))
    asyncio.run(RustBot.poll.coro(bot))
    assert channel.send.await_count==expected_messages
    assert store.watches()[0].was_online==expected_state
    if expected_messages:
        args=channel.send.call_args
        assert '<@&55>' in args.args[0] and 'US Medium' in args.args[0]
        assert args.kwargs['allowed_mentions'].everyone is False
        assert args.kwargs['allowed_mentions'].roles==[role]
    store.conn.close()

def test_readding_does_not_erase_baseline(tmp_path):
    store=Store(str(tmp_path/'tracker.db'));store.add('bm:42','1',123)
    store.set_state(store.watches()[0],True);store.add('bm:42','1',123,'Updated')
    assert store.watches()[0].was_online==1
    store.conn.close()
