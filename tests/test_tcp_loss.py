import os
import random

from classicsync.net import tcp


def test_transfer_survives_dropped_frames(run, linked_pair, monkeypatch):
    monkeypatch.setattr(tcp, "INITIAL_RTO", 0.2)
    monkeypatch.setattr(tcp, "MIN_RTO", 0.05)
    monkeypatch.setattr(tcp, "MAX_RETRIES", 50)

    async def scenario():
        pair = linked_pair()
        await pair.start()
        chooser = random.Random(1234)
        dropped = []
        for transport in (pair.desktop_link.transport, pair.device_link.transport):
            original_write = transport.write

            def lossy_write(data, original_write=original_write):
                if chooser.random() < 0.1:
                    dropped.append(len(data))
                    return
                original_write(data)

            transport.write = lossy_write

        listener = pair.device.listen(990)
        desktop_side = await pair.desktop.connect(990)
        device_side = await listener.accept()
        blob = os.urandom(100_000)
        desktop_side.write(blob)
        received = await device_side.readexactly(len(blob))
        assert received == blob
        reply = os.urandom(20_000)
        device_side.write(reply)
        assert await desktop_side.readexactly(len(reply)) == reply
        assert dropped
        await pair.close()

    run(scenario)
