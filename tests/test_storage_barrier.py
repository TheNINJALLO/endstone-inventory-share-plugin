import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from endstone_inventory_share_plugin.persistence import require_complete_storage, recover_pending, SessionBusy


def test_handoff_waits_for_pending_backpack_snapshot(tmp_path):
    path = tmp_path / 'backpacks recovery.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE pending (storage_id TEXT PRIMARY KEY, payload TEXT)')
        db.execute('INSERT INTO pending VALUES (?, ?)', ('pack_large', '{}'))
    data = {'storage_barriers': [{'journal': str(path), 'storage_ids': ['pack_large']}]}
    with pytest.raises(SessionBusy):
        require_complete_storage(data)
    with sqlite3.connect(path) as db:
        db.execute('DELETE FROM pending')
    require_complete_storage(data)


def test_recovery_does_not_release_failed_capture(plugin, snapshot):
    snapshot['capture_failed'] = True
    plugin.journal.put('token', '123', snapshot)
    store = SimpleNamespace(save=Mock())
    assert recover_pending(store, plugin.journal, plugin.logger) == 1
    store.save.assert_not_called()
    assert plugin.journal.entries()[0][2]['capture_failed']


def test_final_capture_failure_keeps_shared_lock_and_last_snapshot(plugin, snapshot):
    player = SimpleNamespace(xuid='123', name='TestPlayer')
    plugin._ready_players.add('token')
    plugin.journal.put('token', '123', snapshot)
    plugin._queue_snapshot = Mock(side_effect=ValueError('could not read bundle NBT'))
    plugin._persist_snapshot = Mock()
    plugin._finish_session(player, 'token')
    plugin.executor.submit(lambda: None).result(timeout=5)
    plugin._persist_snapshot.assert_not_called()
    saved = plugin.journal.entries()[0][2]
    assert saved['inv_json'] == snapshot['inv_json']
    assert saved['capture_failed'] is True


def test_missing_barrier_journal_cannot_silently_release_ownership(tmp_path):
    with pytest.raises(sqlite3.OperationalError):
        require_complete_storage({'storage_barriers': [{'journal': str(tmp_path / 'missing.sqlite3'),
                                                       'storage_ids': ['pack_large']}]})
