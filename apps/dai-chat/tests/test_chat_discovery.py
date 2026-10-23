# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Finding contacts on the local network (dai_chat/discovery.py): contacts find each other by an hourly tag,
strangers learn nothing lasting, and malformed announcements are ignored. With python3-zeroconf installed,
two real announcers find each other on this computer's network."""
import importlib.util
import socket
import subprocess
import time
import unittest

if importlib.util.find_spec("nacl") is None:  # python3-nacl, in Debian
    raise unittest.SkipTest("PyNaCl is missing")

from dai_chat import discovery, keys


class Info:
    def __init__(self, properties, addresses=("192.168.1.20",), port=7714, name="x._dai-chat._tcp.local."):
        self.properties, self.addresses, self.port, self.name = properties, list(addresses), port, name

    def parsed_addresses(self):
        return self.addresses


class Zc:
    def __init__(self, infos):
        self.infos = infos

    def get_service_info(self, type_, name, timeout):
        return self.infos.get(name)


def someone():
    return discovery.short(keys.Identity.generate().public)


class TagTests(unittest.TestCase):
    def test_only_local_addresses_are_taken_from_the_network(self):
        """Review finding 8: a record naming an internet host must not make us connect there outside Tor."""
        for ok in ("192.168.1.20", "10.0.0.5", "172.16.3.4", "169.254.7.7", "fe80::1", "fd12::3"):
            self.assertTrue(discovery.local_address(ok), ok)
        for bad in ("8.8.8.8", "203.0.113.5", "100.64.0.1", "2001:db8::1", "127.0.0.1", "0.0.0.0", "::1", "nonsense"):
            self.assertFalse(discovery.local_address(bad), bad)

    def test_tags_change_every_hour_and_differ_per_person(self):
        dana, noa = someone(), someone()
        now = 1_800_000_000
        self.assertEqual(len(discovery.tag(dana, now)), 16)
        self.assertNotEqual(discovery.tag(dana, now), discovery.tag(dana, now + 3600))
        self.assertNotEqual(discovery.tag(dana, now), discovery.tag(noa, now))
        self.assertIn(discovery.tag(dana, now - 3600), discovery.tags_now(dana, now))  # a clock a bit behind

    def test_only_the_contact_is_found(self):
        dana, stranger = someone(), someone()
        seen = discovery.Discovery(keys.Identity.generate().public, 7714)
        zc = Zc({"a._dai-chat._tcp.local.": Info({b"t": discovery.tag(dana).encode()}),
                 "b._dai-chat._tcp.local.": Info({b"t": b"not-a-tag"}),
                 "c._dai-chat._tcp.local.": Info({b"t": discovery.tag(dana).encode()}, port=0),
                 "d._dai-chat._tcp.local.": Info({}, addresses=())})
        for name in zc.infos:
            seen.add_service(zc, discovery.SERVICE, name)
        self.assertEqual(seen.find(dana), [discovery.Seen(discovery.tag(dana), "192.168.1.20", 7714)])
        self.assertEqual(seen.find(stranger), [])
        seen.remove_service(zc, discovery.SERVICE, "a._dai-chat._tcp.local.")
        self.assertEqual(seen.find(dana), [])


def _address():
    out = subprocess.run(["hostname", "-I"], capture_output=True, text=True).stdout.split()
    return next((a for a in out if "." in a and not a.startswith("127.")), "")


@unittest.skipIf(importlib.util.find_spec("zeroconf") is None or not _address(), "no zeroconf or no network")
class RealMdnsTests(unittest.TestCase):
    def test_two_computers_find_each_other(self):
        from zeroconf import IPVersion, Zeroconf

        address = _address()
        if not discovery.local_address(address):
            self.skipTest(f"{address} is not a local network address; records naming it are ignored by design")
        alice, bob = keys.Identity.generate(), keys.Identity.generate()
        make = lambda: Zeroconf(interfaces=[address], ip_version=IPVersion.V4Only)  # noqa: E731
        one, two = discovery.Discovery(alice.public, 7714, make), discovery.Discovery(bob.public, 7715, make)
        self.addCleanup(one.stop)
        self.addCleanup(two.stop)
        one.start(address)
        two.start(address)
        for _ in range(40):
            if one.find(discovery.short(bob.public)) and two.find(discovery.short(alice.public)):
                break
            time.sleep(0.25)
        self.assertEqual([(s.host, s.port) for s in one.find(discovery.short(bob.public))], [(address, 7715)])
        self.assertEqual([(s.host, s.port) for s in two.find(discovery.short(alice.public))], [(address, 7714)])
        self.assertNotIn(socket.gethostname(), one.info.name)  # the computer's name is not announced


if __name__ == "__main__":
    unittest.main()
