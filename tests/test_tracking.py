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
