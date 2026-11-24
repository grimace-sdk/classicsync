from classicsync.link import hdlc


def test_fcs_check_value():
    assert hdlc.fcs16(b"123456789") ^ 0xFFFF == 0x906E


def test_round_trip_with_full_accm():
    payload = bytes(range(256))
    encoded = hdlc.encode_frame(payload)
    assert all(byte >= 0x20 or byte in (hdlc.FLAG,) for byte in encoded[1:-1] if byte != hdlc.ESCAPE)
    frames, text = hdlc.FrameDecoder().feed(encoded)
    assert frames == [payload]
    assert text == b""


def test_round_trip_with_empty_accm_leaves_control_bytes():
    payload = b"\x01\x02\x7e\x7d"
    encoded = hdlc.encode_frame(payload, accm=0)
    assert b"\x01\x02" in encoded
    frames, _ = hdlc.FrameDecoder().feed(encoded)
    assert frames == [payload]


def test_corrupt_frame_dropped():
    encoded = bytearray(hdlc.encode_frame(b"\xff\x03\xc0\x21hello"))
    encoded[5] ^= 0x01
    decoder = hdlc.FrameDecoder()
    frames, _ = decoder.feed(bytes(encoded))
    assert frames == []
    assert decoder.bad_frames == 1


def test_text_outside_frames_is_reported():
    decoder = hdlc.FrameDecoder()
    frames, text = decoder.feed(b"CLIENT")
    assert frames == [] and text == b"CLIENT"


def test_handshake_after_stray_flag_is_reported():
    decoder = hdlc.FrameDecoder()
    frames, text = decoder.feed(b"\x7eCLIENT")
    assert frames == [] and text == b"CLIENT"


def test_split_feed():
    payload = b"\xff\x03\x00\x21" + bytes(100)
    encoded = hdlc.encode_frame(payload)
    decoder = hdlc.FrameDecoder()
    frames = []
    for byte in encoded:
        found, _ = decoder.feed(bytes([byte]))
        frames += found
    assert frames == [payload]
