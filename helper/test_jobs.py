import multiprocessing
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import job_process
import jobs


def complete_in_process(root, ident, state, outcomes):
    outcomes.put(jobs.Store(root).transition(ident, state))


class JobStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='model-mod-jobs-')
        self.store = jobs.Store(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def create(self):
        return self.store.create(self.tmp.name, 'test', 'chat', None, 'rescue', 'read-only', 'generation')

    def test_terminal_state_race(self):
        record = self.create()
        ident = record['id']
        self.assertFalse(self.store.transition(ident, 'completed'))
        self.assertTrue(self.store.transition(ident, 'starting'))
        self.assertTrue(self.store.transition(ident, 'running'))
        self.assertTrue(self.store.transition(ident, 'cancelling'))
        outcomes = []
        threads = [threading.Thread(target=lambda state=state: outcomes.append(self.store.transition(ident, state)))
                   for state in ('completed', 'cancelled')]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(sorted(outcomes), [False, True])
        self.assertFalse(self.store.transition(ident, 'failed'))

    def test_process_terminal_race(self):
        ident = self.create()['id']
        self.store.transition(ident, 'starting')
        self.store.transition(ident, 'running')
        self.store.transition(ident, 'cancelling')
        outcomes = multiprocessing.Queue()
        processes = [multiprocessing.Process(target=complete_in_process, args=(self.tmp.name, ident, state, outcomes))
                     for state in ('completed', 'cancelled')]
        for process in processes: process.start()
        for process in processes: process.join(5)
        self.assertEqual([p.exitcode for p in processes], [0, 0])
        self.assertEqual(sorted(outcomes.get(timeout=1) for _ in processes), [False, True])

    def test_private_records_and_cleanup(self):
        record = self.create()
        ident = record['id']
        self.assertEqual(os.stat(self.tmp.name).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(self.store.path(ident, '.json')).st_mode & 0o777, 0o600)
        self.assertTrue(self.store.transition(ident, 'starting'))
        self.assertTrue(self.store.transition(ident, 'running'))
        self.assertTrue(self.store.transition(ident, 'completed', result='\x1b[31mhello\x1b[0m'))
        with open(self.store.path(ident, '.result'), encoding='utf-8') as source:
            self.assertEqual(source.read(), 'hello')
        self.assertEqual(os.stat(self.store.path(ident, '.result')).st_mode & 0o777, 0o600)
        self.assertEqual(self.store.clear(older_than=time.time() - jobs.RETENTION_SECONDS), 0)
        self.assertEqual(self.store.clear(workspace=jobs.workspace_hash(self.tmp.name)), 1)
        self.assertEqual(self.store.records(), [])

    def test_group_identity_before_signal(self):
        member = {'pid': 23, 'started': 'start'}
        with patch.object(job_process, 'start_time', return_value='different'), \
             patch.object(job_process.os, 'getpgid', return_value=42), \
             patch.object(job_process.os, 'killpg') as kill:
            self.assertFalse(job_process.cleanup_verified(42, [member]))
            kill.assert_not_called()
        with patch.object(job_process, 'start_time', return_value='start'), \
             patch.object(job_process.os, 'getpgid', return_value=43), \
             patch.object(job_process.os, 'killpg') as kill:
            self.assertFalse(job_process.cleanup_verified(42, [member]))
            kill.assert_not_called()
        with patch.object(job_process, 'start_time', return_value=None), \
             patch.object(job_process.os, 'killpg') as kill:
            self.assertFalse(job_process.cleanup_verified(42, [member]))
            kill.assert_not_called()

    def test_ttl_and_queue_limit(self):
        records = [self.create() for _ in range(5)]
        with self.assertRaisesRegex(ValueError, 'queue'):
            self.create()
        self.assertTrue(self.store.transition(records[0]['id'], 'cancelled'))
        with self.store.locked():
            record = self.store.resolve(records[0]['id'])
            record['updatedAt'] = time.time() - jobs.RETENTION_SECONDS - 1
            self.store.write(record)
        self.assertEqual(self.store.clear(older_than=time.time() - jobs.RETENTION_SECONDS), 1)
        self.assertEqual(len(self.store.records()), 4)

    def test_limit_and_id_resolution(self):
        old = jobs.MAX_JOBS
        jobs.MAX_JOBS = 2
        try:
            first, second = self.create(), self.create()
            self.assertEqual(self.store.resolve(first['id'])['id'], first['id'])
            with self.assertRaises(ValueError): self.store.create(self.tmp.name, 'test', 'chat', None, 'rescue', 'read-only', 'generation')
            with self.assertRaises(ValueError): self.store.resolve('../')
        finally:
            jobs.MAX_JOBS = old
