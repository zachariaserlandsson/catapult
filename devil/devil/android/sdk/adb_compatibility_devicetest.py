#!/usr/bin/env python
# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import contextlib
import os
import posixpath
import random
import signal
import sys
import unittest

_CATAPULT_BASE_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..', '..'))

sys.path.append(os.path.join(_CATAPULT_BASE_DIR, 'devil'))
from devil import devil_env
from devil.android import device_errors
from devil.android.sdk import adb_wrapper
from devil.utils import cmd_helper
from devil.utils import timeout_retry

with devil_env.SysPath(os.path.join(_CATAPULT_BASE_DIR, 'third_party', 'mock')):
  import mock # pylint: disable=import-error


_ADB_PATH = os.environ.get('ADB_PATH', 'adb')
_TEST_DATA_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), 'test', 'data'))


def _hostAdbPids():
  ps_status, ps_output = cmd_helper.GetCmdStatusAndOutput(
      ['pgrep', '-l', 'adb'])
  if ps_status != 0:
    return []

  pids_and_names = (line.split() for line in ps_output.splitlines())
  return [int(pid) for pid, name in pids_and_names
          if name == 'adb']


@mock.patch('devil.android.sdk.adb_wrapper.AdbWrapper.GetAdbPath',
            return_value=_ADB_PATH)
class AdbCompatibilityTest(unittest.TestCase):

  def testStartServer(self, *_args):
    # Manually kill off any instances of adb.
    adb_pids = _hostAdbPids()
    for p in adb_pids:
      os.kill(p, signal.SIGKILL)

    self.assertIsNotNone(
        timeout_retry.WaitFor(
            lambda: not _hostAdbPids(), wait_period=0.1, max_tries=10))

    # start the adb server
    start_server_status, _ = cmd_helper.GetCmdStatusAndOutput(
        [_ADB_PATH, 'start-server'])

    # verify that the server is now online
    self.assertEquals(0, start_server_status)
    self.assertIsNotNone(
        timeout_retry.WaitFor(
            lambda: bool(_hostAdbPids()), wait_period=0.1, max_tries=10))

  def testKillServer(self, *_args):
    adb_pids = _hostAdbPids()
    if not adb_pids:
      adb_wrapper.AdbWrapper.StartServer()

    adb_pids = _hostAdbPids()
    self.assertEqual(1, len(adb_pids))

    kill_server_status, _ = cmd_helper.GetCmdStatusAndOutput(
        [_ADB_PATH, 'kill-server'])
    self.assertEqual(0, kill_server_status)

    adb_pids = _hostAdbPids()
    self.assertEqual(0, len(adb_pids))

  def testDevices(self, *_args):
    devices = adb_wrapper.AdbWrapper.Devices()
    self.assertNotEqual(0, len(devices), 'No devices found.')

  def getTestInstance(self):
    """Creates a real AdbWrapper instance for testing."""
    devices = adb_wrapper.AdbWrapper.Devices()
    if not devices:
      self.skipTest('No test device available.')
    return adb_wrapper.AdbWrapper(devices[0])

  def testShell(self, *_args):
    under_test = self.getTestInstance()
    shell_ls_result = under_test.Shell('ls')
    self.assertIsInstance(shell_ls_result, str)
    self.assertTrue(bool(shell_ls_result))

  def testShell_failed(self, *_args):
    under_test = self.getTestInstance()
    with self.assertRaises(device_errors.AdbShellCommandFailedError):
      under_test.Shell('ls /foo/bar/baz')

  def testShell_externalStorageDefined(self, *_args):
    under_test = self.getTestInstance()
    external_storage = under_test.Shell('echo $EXTERNAL_STORAGE')
    self.assertIsInstance(external_storage, str)
    self.assertTrue(posixpath.isabs(external_storage))

  @contextlib.contextmanager
  def getTestPushDestination(self, under_test):
    """Creates a temporary directory suitable for pushing to."""
    external_storage = under_test.Shell('echo $EXTERNAL_STORAGE').strip()
    if not external_storage:
      self.skipTest('External storage not available.')
    while True:
      random_hex = hex(random.randint(0, 2 ** 52))[2:]
      name = 'tmp_push_test%s' % random_hex
      path = posixpath.join(external_storage, name)
      try:
        under_test.Shell('ls %s' % path)
      except device_errors.AdbShellCommandFailedError:
        break
    under_test.Shell('mkdir %s' % path)
    try:
      yield path
    finally:
      under_test.Shell('rm -rf %s' % path)

  def testPush_fileToFile(self, *_args):
    under_test = self.getTestInstance()
    with self.getTestPushDestination(under_test) as push_target_directory:
      src = os.path.join(_TEST_DATA_DIR, 'push_file.txt')
      dest = posixpath.join(push_target_directory, 'push_file.txt')
      with self.assertRaises(device_errors.AdbShellCommandFailedError):
        under_test.Shell('ls %s' % dest)
      under_test.Push(src, dest)
      self.assertEquals(dest, under_test.Shell('ls %s' % dest).strip())

  def testPush_fileToDirectory(self, *_args):
    under_test = self.getTestInstance()
    with self.getTestPushDestination(under_test) as push_target_directory:
      src = os.path.join(_TEST_DATA_DIR, 'push_file.txt')
      dest = push_target_directory
      resulting_file = posixpath.join(dest, 'push_file.txt')
      with self.assertRaises(device_errors.AdbShellCommandFailedError):
        under_test.Shell('ls %s' % resulting_file)
      under_test.Push(src, dest)
      self.assertEquals(
          resulting_file,
          under_test.Shell('ls %s' % resulting_file).strip())

  def testPush_directoryToDirectory(self, *_args):
    under_test = self.getTestInstance()
    with self.getTestPushDestination(under_test) as push_target_directory:
      src = os.path.join(_TEST_DATA_DIR, 'push_directory')
      dest = posixpath.join(push_target_directory, 'push_directory')
      with self.assertRaises(device_errors.AdbShellCommandFailedError):
        under_test.Shell('ls %s' % dest)
      under_test.Push(src, dest)
      self.assertEquals(
          sorted(os.listdir(src)),
          sorted(under_test.Shell('ls %s' % dest).strip().split()))

  def testPush_directoryToExistingDirectory(self, *_args):
    under_test = self.getTestInstance()
    with self.getTestPushDestination(under_test) as push_target_directory:
      src = os.path.join(_TEST_DATA_DIR, 'push_directory')
      dest = posixpath.join(push_target_directory, 'push_directory')
      with self.assertRaises(device_errors.AdbShellCommandFailedError):
        under_test.Shell('ls %s' % dest)
      under_test.Shell('mkdir %s' % dest)
      under_test.Push(src, dest)
      self.assertEquals(
          sorted(os.listdir(src)),
          sorted(under_test.Shell('ls %s' % dest).strip().split()))

  # TODO(jbudorick): Implement tests for the following:
  # taskset -c
  # devices [-l]
  # pull
  # shell
  # ls
  # logcat [-c] [-d] [-v] [-b]
  # forward [--remove] [--list]
  # jdwp
  # install [-l] [-r] [-s] [-d]
  # install-multiple [-l] [-r] [-s] [-d] [-p]
  # uninstall [-k]
  # backup -f [-apk] [-shared] [-nosystem] [-all]
  # restore
  # wait-for-device
  # get-state (BROKEN IN THE M SDK)
  # get-devpath
  # remount
  # reboot
  # reboot-bootloader
  # root
  # emu

  @classmethod
  def tearDownClass(cls):
    version_status, version_output = cmd_helper.GetCmdStatusAndOutput(
        [_ADB_PATH, 'version'])
    if version_status != 0:
      version = ['(unable to determine version)']
    else:
      version = version_output.splitlines()

    print
    print
    print 'tested %s' % _ADB_PATH
    for l in version:
      print '  %s' % l
    print 'connected devices:'
    try:
      for d in adb_wrapper.AdbWrapper.Devices():
        print '  %s' % d
    except device_errors.AdbCommandFailedError:
      print '  <failed to list devices>'
      raise
    finally:
      print


if __name__ == '__main__':
  sys.exit(unittest.main())
