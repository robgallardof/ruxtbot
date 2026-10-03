from rustbot.tracking import Store, valid_steamid64, transition
def test_steamid64_validation():
    assert valid_steamid64('76561197960265728')
    assert not valid_steamid64('base64') and not valid_steamid64('123')
def test_first_observation_is_silent_and_transitions_work():
    assert transition(None, True) is None
    assert transition(True, True) is None
    assert transition(True, False) == 'disconnected'
    assert transition(False, True) == 'connected'
def test_store_persists_settings_and_watches(tmp_path):
    store=Store(str(tmp_path/'state.sqlite3'))
    store.set_settings(10, 20, 'es', True, 120)
    store.add('76561197960265728', '123', 20, 'Scout')
    assert store.settings(10) == (20, 'es', 1, 120)
    assert store.watches()[0].label == 'Scout'


def test_expiration_migrates_and_survives_restart(tmp_path):
    import sqlite3
    from unittest.mock import patch
    from rustbot.tracking import Store
    path = str(tmp_path / 'legacy.db')
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE watches(steamid TEXT,server_id TEXT,channel_id INTEGER,label TEXT,was_online INTEGER,PRIMARY KEY(steamid,server_id,channel_id))')
    conn.execute("INSERT INTO watches VALUES('bm:1','1',1,'legacy',0)")
    conn.commit()
    conn.close()
    with patch('rustbot.tracking.time.time', return_value=1000):
        store = Store(path)
        assert store.watches()[0].expires_at == 1000+7*86400
        store.add('bm:2', '1', 1, owner_id=9, days=15)
        store.conn.close()
    with patch('rustbot.tracking.time.time', return_value=1000+8*86400):
        store = Store(path)
        assert [w.steamid for w in store.watches()] == ['bm:2']
        store.conn.close()
    with patch('rustbot.tracking.time.time', return_value=1000+15*86400):
        store = Store(path)
        assert store.watches() == []
        store.conn.close()
