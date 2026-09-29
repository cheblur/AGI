"""Behavioral tests for the local Vowcast broker.

These exercise the trust boundary through the public Python API. The two
database-tamper tests additionally model an attacker who can edit a queued
record but does not possess the sender's local signing key.
"""

import base64
import sqlite3
import tempfile
import unittest
from pathlib import Path

import vowcast


class VowcastBrokerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.db = root / "events.sqlite"
        self.keys = root / "keys"
        vowcast.init_store(self.db, self.keys)
        self.alice_key = vowcast.enroll_agent(self.db, self.keys, "alice")
        self.bob_key = vowcast.enroll_agent(self.db, self.keys, "bob")
        self.carol_key = vowcast.enroll_agent(self.db, self.keys, "carol")

    def send(self, **overrides):
        args = dict(sender="alice", recipient="bob", body="A signed proposal", now=1000)
        args.update(overrides)
        return vowcast.send_message(self.db, self.keys, **args)

    def test_authorized_delivery_and_recipient_acknowledgment(self):
        message_id = self.send()
        self.assertEqual(vowcast.list_inbox(self.db, self.keys, "alice", now=1001), [])
        self.assertEqual(vowcast.list_inbox(self.db, self.keys, "carol", now=1001), [])
        inbox = vowcast.list_inbox(self.db, self.keys, "bob", now=1001)
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0]["id"], message_id)
        self.assertEqual(inbox[0]["body"], "A signed proposal")
        ack_id = vowcast.acknowledge_message(self.db, self.keys, "bob", message_id, now=1002)
        self.assertTrue(ack_id)
        self.assertEqual(vowcast.list_inbox(self.db, self.keys, "bob", now=1003), [])

    def test_replayed_message_id_is_rejected_without_duplicate_delivery(self):
        message_id = "fixed-replay-id"
        self.send(message_id=message_id)
        with self.assertRaises(vowcast.VowcastError):
            self.send(message_id=message_id, body="different content")
        self.assertEqual(len(vowcast.list_inbox(self.db, self.keys, "bob", now=1001)), 1)

    def test_sender_must_be_enrolled(self):
        with self.assertRaises(vowcast.VowcastError):
            self.send(sender="not-enrolled")
        self.assertEqual(vowcast.list_inbox(self.db, self.keys, "bob", now=1001), [])

    def test_other_recipient_cannot_acknowledge(self):
        message_id = self.send()
        with self.assertRaises(vowcast.VowcastError):
            vowcast.acknowledge_message(self.db, self.keys, "carol", message_id, now=1001)
        self.assertEqual(len(vowcast.list_inbox(self.db, self.keys, "bob", now=1001)), 1)

    def test_verified_acknowledgement_is_returned_with_read_mail(self):
        message_id = self.send()
        ack_id = vowcast.acknowledge_message(self.db, self.keys, "bob", message_id, now=1001)
        read_mail = vowcast.list_inbox(self.db, self.keys, "bob", include_read=True, now=1002)
        self.assertEqual([(row["id"], row["ack_id"], row["acked_at"]) for row in read_mail],
                         [(message_id, ack_id, 1001)])
        with self.assertRaises(vowcast.ReplayError):
            vowcast.acknowledge_message(self.db, self.keys, "bob", message_id, now=1003)

    def test_forged_acknowledgement_cannot_hide_mail(self):
        message_id = self.send()
        with sqlite3.connect(self.db) as con:
            con.execute("INSERT INTO acknowledgements VALUES(?,?,?,?,?)",
                        ("forged", message_id, "bob", 1001, "0" * 64))
        for include_read in (False, True):
            with self.subTest(include_read=include_read), self.assertRaises(vowcast.IntegrityError):
                vowcast.list_inbox(self.db, self.keys, "bob", include_read=include_read, now=1002)

    def test_acknowledgement_recipient_and_time_tampering_are_detected(self):
        for field, value in (("recipient", "carol"), ("acked_at", 9999)):
            with self.subTest(field=field):
                message_id = self.send()
                vowcast.acknowledge_message(self.db, self.keys, "bob", message_id, now=1001)
                with sqlite3.connect(self.db) as con:
                    con.execute(f"UPDATE acknowledgements SET {field}=? WHERE message_id=?",
                                (value, message_id))
                with self.assertRaises(vowcast.IntegrityError):
                    vowcast.list_inbox(self.db, self.keys, "bob", now=1002)

    def test_expired_message_cannot_be_delivered_or_acknowledged(self):
        message_id = self.send(expiry_seconds=10)
        self.assertEqual(len(vowcast.list_inbox(self.db, self.keys, "bob", now=1009)), 1)
        self.assertEqual(vowcast.list_inbox(self.db, self.keys, "bob", now=1011), [])
        with self.assertRaises(vowcast.VowcastError):
            vowcast.acknowledge_message(self.db, self.keys, "bob", message_id, now=1011)

    def test_invalid_inputs_are_rejected_before_queueing(self):
        invalid = (
            dict(body={"not": "plain text"}),
            dict(body=""),
            dict(recipient=""),
            dict(expiry_seconds=-1),
            dict(sender="../alice"),
            dict(sender=13),
            dict(message_id=""),
            dict(message_id=42),
        )
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(vowcast.VowcastError):
                self.send(**change)
        self.assertEqual(vowcast.list_inbox(self.db, self.keys, "bob", now=1001), [])

    def test_changed_body_is_detected_before_read_or_ack(self):
        message_id = self.send()
        with sqlite3.connect(self.db) as con:
            con.execute("UPDATE messages SET body=? WHERE id=?", ("Attacker's replacement", message_id))
        with self.assertRaises(vowcast.IntegrityError):
            vowcast.list_inbox(self.db, self.keys, "bob", now=1001)
        with self.assertRaises(vowcast.IntegrityError):
            vowcast.acknowledge_message(self.db, self.keys, "bob", message_id, now=1001)

    def test_forged_signature_is_detected_even_with_matching_body_hash(self):
        message_id = self.send()
        with sqlite3.connect(self.db) as con:
            con.execute("UPDATE messages SET signature=? WHERE id=?", ("0" * 64, message_id))
        with self.assertRaises(vowcast.IntegrityError):
            vowcast.list_inbox(self.db, self.keys, "bob", now=1001)
        with self.assertRaises(vowcast.IntegrityError):
            vowcast.acknowledge_message(self.db, self.keys, "bob", message_id, now=1001)

    def test_export_preserves_records_without_exposing_signing_keys(self):
        self.send()
        destination = Path(self.temp.name) / "events.jsonl"
        count = vowcast.export_events(self.db, destination)
        self.assertGreaterEqual(count, 1)
        exported = destination.read_text(encoding="utf-8")
        self.assertIn("message.delivered", exported)
        self.assertNotIn("A signed proposal", exported)
        self.assertNotIn('"body"', exported)
        for key_path in (self.alice_key, self.bob_key, self.carol_key):
            secret = Path(key_path).read_bytes()
            self.assertNotIn(secret.hex(), exported)
            self.assertNotIn(base64.b64encode(secret).decode("ascii"), exported)
            self.assertNotIn(secret.decode("ascii").strip(), exported)


if __name__ == "__main__":
    unittest.main()
