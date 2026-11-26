# Network sync

Windows CE 2.x and 3.x devices can synchronize over a network card, Wi-Fi or a RAS dial-in instead of a cable. Tested with an HP Jornada 720 on WEP Wi-Fi.

## Requirements

- A partnership made over a cable first. The device only syncs remotely with a desktop it is partnered with.
- The device must resolve the desktop's name, as shown in its partnership: the computer name, upper case, cut to 15 characters (`PHILS-MACBOOK-A`). Add it to your DHCP server's DNS, or to the device's hosts entries (`HKLM\Comm\Tcpip\Hosts\<NAME>`, value `ipaddr`, the address as 4 bytes).
- These ports reachable:

| Port | Direction | Use |
| --- | --- | --- |
| TCP 5679 | device to desktop | connection, keepalives |
| TCP 999 | device to desktop | sync status window on the device |
| TCP 990 | desktop to device | remote API (files, sync) |

## Desktop

In the app, tick "Allow network (Ethernet) and Remote Access Service (RAS) server connection" in Connection Settings (ActiveSync 3.1 look), or Enable Network Connection in the File or tray menu (CE Services 2.2 look).

From the command line:

```
classicsync serve network
```

The device starts a sync as soon as it connects, and Sync Now on the device syncs again.

On Linux, ports below 1024 need privileges. Without them the sync still runs, but the device says "ActiveSync not responding on the desktop computer." Either let Python bind them (`sudo setcap cap_net_bind_service=+ep $(readlink -f $(which python3))`, which applies to everything run by that Python), or, with `serve`, redirect 999 to a higher port and pass that port with `--status-port`.

## Through a gateway

When the device is on a separate network (an old Wi-Fi access point behind a Raspberry Pi, say), forward the ports through the gateway. With SSH:

```
ssh -N -R 15679:127.0.0.1:5679 -R 25999:127.0.0.1:15999 -L 1990:DEVICE_IP:990 GATEWAY
classicsync serve network --network-listen 127.0.0.1:5679 --status-port 15999 --device-rapi 127.0.0.1:1990
```

For the app, use the same tunnel but forward to the app's ports (`-R 15679:127.0.0.1:5679 -R 25999:127.0.0.1:999`), and set Device RAPI to `127.0.0.1:1990` in ClassicSync Settings.

On the gateway, relay its own ports 5679 and 999 (on the device's network) to 15679 and 25999, with `socat` for example, and point the desktop's name at the gateway's address. Remote forwards bind to the gateway's loopback unless `GatewayPorts` is on in its sshd.
