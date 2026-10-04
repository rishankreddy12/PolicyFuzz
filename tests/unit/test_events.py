import pytest
from policyfuzz import db, events

@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.init_schema(c)
    yield c
    c.close()

def test_log_and_list_events(conn):
    events.log_event(conn, "run1", "Parse", "INFO", "Started parsing")
    events.log_event(conn, "run1", "Parse", "INFO", "Finished parsing", {"clauses": 10})
    
    evs = events.list_events(conn, "run1")
    assert len(evs) == 2
    assert evs[0]['message'] == "Started parsing"
    assert evs[1]['message'] == "Finished parsing"
    assert '"clauses": 10' in evs[1]['payload_json']
    
    # Test since_id filter
    evs_filtered = events.list_events(conn, "run1", since_id=evs[0]['id'])
    assert len(evs_filtered) == 1
    assert evs_filtered[0]['id'] == evs[1]['id']
