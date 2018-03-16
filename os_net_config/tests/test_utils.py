# -*- coding: utf-8 -*-

# Copyright 2014 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import os
import os.path
import random
import shutil
import tempfile
import yaml

from os_net_config import objects
from os_net_config.tests import base
from os_net_config import utils

from oslo_concurrency import processutils

_PCI_OUTPUT = '''driver: e1000e
version: 3.2.6-k
firmware-version: 0.13-3
expansion-rom-version:
bus-info: 0000:00:19.0
supports-statistics: yes
supports-test: yes
supports-eeprom-access: yes
supports-register-dump: yes
supports-priv-flags: no
'''

_VPPCTL_OUTPUT = '''
            Name               Idx       State          Counter          Count
GigabitEthernet0/9/0              1        down
local0                            0        down

'''

_VPPBOND_OUTPUT = """
              Name                Idx   Link  Hardware
BondEthernet0                      3     up   Slave-Idx: 1 2
TenGigabitEthernet2/0/0            1    slave TenGigabitEthernet2/0/0
TenGigabitEthernet2/0/1            2    slave TenGigabitEthernet2/0/1
"""

_INITIAL_VPP_CONFIG = '''
unix {
  nodaemon
  log /tmp/vpp.log
  full-coredump
}


api-trace {
  on
}

api-segment {
  gid vpp
}

dpdk {
}
'''


class TestUtils(base.TestCase):

    def setUp(self):
        super(TestUtils, self).setUp()
        rand = str(int(random.random() * 100000))
        utils._DPDK_MAPPING_FILE = '/tmp/dpdk_mapping_' + rand + '.yaml'

    def tearDown(self):
        super(TestUtils, self).tearDown()
        if os.path.isfile(utils._DPDK_MAPPING_FILE):
            os.remove(utils._DPDK_MAPPING_FILE)

    def test_ordered_active_nics(self):

        tmpdir = tempfile.mkdtemp()
        self.stubs.Set(utils, '_SYS_CLASS_NET', tmpdir)

        def test_is_available_nic(interface_name, check_active):
            return True
        self.stubs.Set(utils, '_is_available_nic', test_is_available_nic)

        for nic in ['a1', 'em1', 'em2', 'eth2', 'z1',
                    'enp8s0', 'enp10s0', 'enp1s0f0']:
            with open(os.path.join(tmpdir, nic), 'w') as f:
                f.write(nic)

        nics = utils.ordered_active_nics()
        self.assertEqual('em1', nics[0])
        self.assertEqual('em2', nics[1])
        self.assertEqual('eth2', nics[2])
        self.assertEqual('a1', nics[3])
        self.assertEqual('enp1s0f0', nics[4])
        self.assertEqual('enp8s0', nics[5])
        self.assertEqual('enp10s0', nics[6])
        self.assertEqual('z1', nics[7])

        shutil.rmtree(tmpdir)

    def test_get_pci_address_success(self):
        def test_execute(name, dummy1, dummy2=None, dummy3=None):
            if 'ethtool' in name:
                out = _PCI_OUTPUT
                return out, None
        self.stubs.Set(processutils, 'execute', test_execute)
        pci = utils.get_pci_address('nic2', False)
        self.assertEqual('0000:00:19.0', pci)

    def test_get_pci_address_exception(self):
        def test_execute(name, dummy1, dummy2=None, dummy3=None):
            if 'ethtool' in name:
                raise processutils.ProcessExecutionError
        self.stubs.Set(processutils, 'execute', test_execute)
        pci = utils.get_pci_address('nic2', False)
        self.assertEqual(None, pci)

    def test_get_pci_address_error(self):
        def test_execute(name, dummy1, dummy2=None, dummy3=None):
            if 'ethtool' in name:
                return None, 'Error'
        self.stubs.Set(processutils, 'execute', test_execute)
        pci = utils.get_pci_address('nic2', False)
        self.assertEqual(None, pci)

    def test_get_stored_pci_address_success(self):
        def test_get_dpdk_map():
            return [{'name': 'eth1', 'pci_address': '0000:00:09.0',
                     'mac_address': '01:02:03:04:05:06',
                     'driver': 'vfio-pci'}]

        self.stubs.Set(utils, '_get_dpdk_map', test_get_dpdk_map)
        pci = utils.get_stored_pci_address('eth1', False)
        self.assertEqual('0000:00:09.0', pci)

    def test_get_stored_pci_address_empty(self):
        def test_get_dpdk_map():
            return []

        self.stubs.Set(utils, '_get_dpdk_map', test_get_dpdk_map)
        pci = utils.get_stored_pci_address('eth1', False)
        self.assertEqual(None, pci)

    def test_bind_dpdk_interfaces(self):
        def test_execute(name, dummy1, dummy2=None, dummy3=None):
            if 'ethtool' in name:
                out = _PCI_OUTPUT
                return out, None
            if 'driverctl' in name:
                return None, None

        def test_get_dpdk_mac_address(name):
            return '01:02:03:04:05:06'
        self.stubs.Set(processutils, 'execute', test_execute)
        self.stubs.Set(utils, '_get_dpdk_mac_address',
                       test_get_dpdk_mac_address)
        try:
            utils.bind_dpdk_interfaces('nic2', 'vfio-pci', False)
        except utils.OvsDpdkBindException:
            self.fail("Received OvsDpdkBindException unexpectedly")

    def test_bind_dpdk_interfaces_fail(self):
        def test_execute(name, dummy1, dummy2=None, dummy3=None):
            if 'ethtool' in name:
                out = _PCI_OUTPUT
                return out, None
            if 'driverctl' in name:
                return None, 'Error'

        def test_get_dpdk_mac_address(name):
            return '01:02:03:04:05:06'
        self.stubs.Set(processutils, 'execute', test_execute)
        self.stubs.Set(utils, '_get_dpdk_mac_address',
                       test_get_dpdk_mac_address)

        self.assertRaises(utils.OvsDpdkBindException,
                          utils.bind_dpdk_interfaces, 'eth1', 'vfio-pci',
                          False)

    def test_bind_dpdk_interfaces_skip_valid_device(self):
        def test_execute(name, dummy1, dummy2=None, dummy3=None):
            if 'ethtool' in name:
                return None, 'Error'
            if 'driverctl' in name:
                return None, None

        def test_get_dpdk_mac_address(name):
            return '01:02:03:04:05:06'

        def test_get_dpdk_map():
            return [{'name': 'eth1', 'pci_address': '0000:00:09.0',
                     'mac_address': '01:02:03:04:05:06',
                     'driver': 'vfio-pci'}]

        self.stubs.Set(utils, '_get_dpdk_map', test_get_dpdk_map)
        self.stubs.Set(processutils, 'execute', test_execute)
        self.stubs.Set(utils, '_get_dpdk_mac_address',
                       test_get_dpdk_mac_address)
        try:
            utils.bind_dpdk_interfaces('eth1', 'vfio-pci', False)
        except utils.OvsDpdkBindException:
            self.fail("Received OvsDpdkBindException unexpectedly")

    def test_bind_dpdk_interfaces_fail_invalid_device(self):
        def test_execute(name, dummy1, dummy2=None, dummy3=None):
            if 'ethtool' in name:
                return None, 'Error'
            if 'driverctl' in name:
                return None, None

        def test_get_dpdk_mac_address(name):
            return '01:02:03:04:05:06'

        def test_get_dpdk_map():
            return [{'name': 'eth1', 'pci_address': '0000:00:09.0',
                     'mac_address': '01:02:03:04:05:06',
                     'driver': 'vfio-pci'}]

        self.stubs.Set(utils, '_get_dpdk_map', test_get_dpdk_map)
        self.stubs.Set(processutils, 'execute', test_execute)
        self.stubs.Set(utils, '_get_dpdk_mac_address',
                       test_get_dpdk_mac_address)

        self.assertRaises(utils.OvsDpdkBindException,
                          utils.bind_dpdk_interfaces, 'eth2', 'vfio-pci',
                          False)

    def test__update_dpdk_map_new(self):
        utils._update_dpdk_map('eth1', '0000:03:00.0', '01:02:03:04:05:06',
                               'vfio-pci')
        contents = utils.get_file_data(utils._DPDK_MAPPING_FILE)

        dpdk_map = yaml.load(contents) if contents else []
        self.assertEqual(1, len(dpdk_map))
        dpdk_test = [{'name': 'eth1', 'pci_address': '0000:03:00.0',
                      'mac_address': '01:02:03:04:05:06',
                      'driver': 'vfio-pci'}]
        self.assertListEqual(dpdk_test, dpdk_map)

    def test_update_dpdk_map_exist(self):
        dpdk_test = [{'name': 'eth1', 'pci_address': '0000:03:00.0',
                      'mac_address': '01:02:03:04:05:06',
                      'driver': 'vfio-pci'}]
        utils.write_yaml_config(utils._DPDK_MAPPING_FILE, dpdk_test)

        utils._update_dpdk_map('eth1', '0000:03:00.0', '01:02:03:04:05:06',
                               'vfio-pci')
        contents = utils.get_file_data(utils._DPDK_MAPPING_FILE)

        dpdk_map = yaml.load(contents) if contents else []
        self.assertEqual(1, len(dpdk_map))
        self.assertListEqual(dpdk_test, dpdk_map)

    def test_update_dpdk_map_value_change(self):
        dpdk_test = [{'name': 'eth1', 'pci_address': '0000:03:00.0',
                      'driver': 'vfio-pci'}]
        utils.write_yaml_config(utils._DPDK_MAPPING_FILE, dpdk_test)

        dpdk_test = [{'name': 'eth1', 'pci_address': '0000:03:00.0',
                      'mac_address': '01:02:03:04:05:06',
                      'driver': 'vfio-pci'}]
        utils._update_dpdk_map('eth1', '0000:03:00.0', '01:02:03:04:05:06',
                               'vfio-pci')
        try:
            contents = utils.get_file_data(utils._DPDK_MAPPING_FILE)
        except IOError:
            pass

        dpdk_map = yaml.load(contents) if contents else []
        self.assertEqual(1, len(dpdk_map))
        self.assertListEqual(dpdk_test, dpdk_map)

    def test_ordered_active_nics_with_dpdk_mapping(self):

        tmpdir = tempfile.mkdtemp()
        self.stubs.Set(utils, '_SYS_CLASS_NET', tmpdir)

        def test_is_available_nic(interface_name, check_active):
            return True
        self.stubs.Set(utils, '_is_available_nic', test_is_available_nic)

        for nic in ['a1', 'em1', 'em2', 'eth2', 'z1',
                    'enp8s0', 'enp10s0', 'enp1s0f0']:
            with open(os.path.join(tmpdir, nic), 'w') as f:
                f.write(nic)

        utils._update_dpdk_map('eth1', '0000:03:00.0', '01:02:03:04:05:06',
                               'vfio-pci')
        utils._update_dpdk_map('p3p1', '0000:04:00.0', '01:02:03:04:05:07',
                               'igb_uio')

        nics = utils.ordered_active_nics()

        self.assertEqual('em1', nics[0])
        self.assertEqual('em2', nics[1])
        self.assertEqual('eth1', nics[2])  # DPDK bound nic
        self.assertEqual('eth2', nics[3])
        self.assertEqual('a1', nics[4])
        self.assertEqual('enp1s0f0', nics[5])
        self.assertEqual('enp8s0', nics[6])
        self.assertEqual('enp10s0', nics[7])
        self.assertEqual('p3p1', nics[8])  # DPDK bound nic
        self.assertEqual('z1', nics[9])

        shutil.rmtree(tmpdir)

    def test_interface_mac_raises(self):
        self.assertRaises(IOError, utils.interface_mac, 'ens20f2p3')

    def test_is_active_nic_for_sriov_vf(self):

        tmpdir = tempfile.mkdtemp()
        self.stubs.Set(utils, '_SYS_CLASS_NET', tmpdir)

        # SR-IOV PF = ens802f0
        # SR-IOV VF = enp129s2
        for nic in ['ens802f0', 'enp129s2']:
            nic_path = os.path.join(tmpdir, nic)
            os.makedirs(nic_path)
            os.makedirs(os.path.join(nic_path, 'device'))
            with open(os.path.join(nic_path, 'operstate'), 'w') as f:
                f.write('up')
            with open(os.path.join(nic_path, 'address'), 'w') as f:
                f.write('1.2.3.4')

        nic_path = os.path.join(tmpdir, 'enp129s2', 'device', 'physfn')
        os.makedirs(nic_path)

        self.assertEqual(utils._is_active_nic('ens802f0'), True)
        self.assertEqual(utils._is_active_nic('enp129s2'), False)

        shutil.rmtree(tmpdir)

    def test_get_vpp_interface_name(self):
        def test_execute(name, dummy1, dummy2=None, dummy3=None):
            if 'systemctl' in name:
                return None, None
            if 'vppctl' in name:
                return _VPPCTL_OUTPUT, None

        self.stubs.Set(processutils, 'execute', test_execute)

        self.assertEqual('GigabitEthernet0/9/0',
                         utils._get_vpp_interface_name('0000:00:09.0'))
        self.assertIsNone(utils._get_vpp_interface_name(None))
        self.assertIsNone(utils._get_vpp_interface_name('0000:01:09.0'))
        self.assertRaises(utils.VppException,
                          utils._get_vpp_interface_name, '0000:09.0')

    def test_get_vpp_bond(self):
        def test_execute(name, dummy1, dummy2=None, dummy3=None,
                         dummy4=None):
            if 'systemctl' in name:
                return None, None
            if 'vppctl' in name:
                return _VPPBOND_OUTPUT, None

        self.stubs.Set(processutils, 'execute', test_execute)
        bond_info = utils._get_vpp_bond(['1', '2'])
        self.assertIsNotNone(bond_info)
        self.assertEqual('BondEthernet0', bond_info['name'])
        self.assertEqual('3', bond_info['index'])
        self.assertIsNone(utils._get_vpp_bond(['1']))
        self.assertIsNone(utils._get_vpp_bond(['1', '2', '3']))
        self.assertIsNone(utils._get_vpp_bond([]))

    def test_generate_vpp_config(self):
        tmpdir = tempfile.mkdtemp()
        config_path = os.path.join(tmpdir, 'startup.conf')
        with open(config_path, 'w') as f:
            f.write(_INITIAL_VPP_CONFIG)
        vpp_exec_path = os.path.join(tmpdir, 'vpp-exec')
        utils._VPP_EXEC_FILE = vpp_exec_path

        int1 = objects.VppInterface('em1', options="vlan-strip-offload off")
        int1.pci_dev = '0000:00:09.0'
        int2 = objects.VppInterface('em2')
        int2.pci_dev = '0000:00:09.1'
        interfaces = [int1, int2]
        bonds = []
        expected_config = '''
unix {
  exec %s
  nodaemon
  log /tmp/vpp.log
  full-coredump
}


api-trace {
  on
}

api-segment {
  gid vpp
}

dpdk {
  dev 0000:00:09.1
  uio-driver vfio-pci
  dev 0000:00:09.0 {vlan-strip-offload off}

}
''' % vpp_exec_path
        self.assertEqual(expected_config,
                         utils.generate_vpp_config(config_path, interfaces,
                                                   bonds))

        bonds = [objects.VppBond('net_bonding0', members=interfaces,
                                 bonding_options='mode=2')]
        expected_config = '''
unix {
  exec %s
  nodaemon
  log /tmp/vpp.log
  full-coredump
}


api-trace {
  on
}

api-segment {
  gid vpp
}

dpdk {
  vdev net_bonding0,slave=0000:00:09.0,slave=0000:00:09.1,mode=2
  dev 0000:00:09.1
  uio-driver vfio-pci
  dev 0000:00:09.0 {vlan-strip-offload off}

}
''' % vpp_exec_path
        self.assertEqual(expected_config,
                         utils.generate_vpp_config(config_path, interfaces,
                                                   bonds))

    def test_update_vpp_mapping(self):
        tmpdir = tempfile.mkdtemp()
        vpp_exec_path = os.path.join(tmpdir, 'vpp-exec')
        utils._VPP_EXEC_FILE = vpp_exec_path

        def test_get_dpdk_map():
            return [{'name': 'eth1', 'pci_address': '0000:00:09.0',
                     'mac_address': '01:02:03:04:05:06',
                     'driver': 'vfio-pci'}]

        self.stubs.Set(utils, '_get_dpdk_map', test_get_dpdk_map)

        def test_execute(name, dummy1, dummy2=None, dummy3=None):
            return None, None
        self.stubs.Set(processutils, 'execute', test_execute)

        def test_get_vpp_interface_name(pci_dev):
            return {'name': 'GigabitEthernet0/9/0', 'index': '1'}

        self.stubs.Set(utils, '_get_vpp_interface',
                       test_get_vpp_interface_name)

        int1 = objects.VppInterface('eth1', options="vlan-strip-offload off")
        int1.pci_dev = '0000:00:09.0'
        int1.hwaddr = '01:02:03:04:05:06'
        int2 = objects.VppInterface('eth2')
        int2.pci_dev = '0000:00:09.1'
        int2.hwaddr = '01:02:03:04:05:07'
        interfaces = [int1, int2]

        utils.update_vpp_mapping(interfaces, [])

        contents = utils.get_file_data(utils._DPDK_MAPPING_FILE)

        dpdk_test = [{'name': 'eth1', 'pci_address': '0000:00:09.0',
                      'mac_address': '01:02:03:04:05:06',
                      'driver': 'vfio-pci'},
                     {'name': 'eth2', 'pci_address': '0000:00:09.1',
                      'mac_address': '01:02:03:04:05:07',
                      'driver': 'vfio-pci'}]
        dpdk_map = yaml.load(contents) if contents else []
        self.assertEqual(2, len(dpdk_map))
        self.assertListEqual(dpdk_test, dpdk_map)
