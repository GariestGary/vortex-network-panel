import sys
from pathlib import Path
sys.path.insert(0,str(Path("host-agent")))
import pytest
from vortex_netctl.protocol import parse_request

def test_protocol_accepts_typed_request():
    request,params=parse_request(b'{"version":1,"request_id":"abcdefgh","method":"get_status","params":{}}')
    assert request.method == "get_status"
@pytest.mark.parametrize("body",[b'{}',b'{"version":1,"request_id":"abcdefgh","method":"exec","params":{}}',b'{"version":1,"request_id":"abcdefgh","method":"get_status","params":[]}',b'not json'])
def test_protocol_rejects_arbitrary_or_malformed_request(body):
    with pytest.raises(ValueError): parse_request(body)