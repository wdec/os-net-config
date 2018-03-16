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

#
# NOTE: When making changes to the object model, remember to also update
#       schema.yaml to reflect changes to the schema of config files!
#

import logging
import netaddr
from oslo_utils import strutils

from os_net_config import utils


logger = logging.getLogger(__name__)

_MAPPED_NICS = None

STANDALONE_FAIL_MODE = 'standalone'
DEFAULT_OVS_BRIDGE_FAIL_MODE = STANDALONE_FAIL_MODE


class InvalidConfigException(ValueError):
    pass


def object_from_json(json):
    obj_type = json.get("type")
    if obj_type == "interface":
        return Interface.from_json(json)
    elif obj_type == "vlan":
        return Vlan.from_json(json)
    elif obj_type == "ovs_bridge":
        return OvsBridge.from_json(json)
    elif obj_type == "ovs_user_bridge":
        return OvsUserBridge.from_json(json)
    elif obj_type == "ovs_bond":
        return OvsBond.from_json(json)
    elif obj_type == "linux_bond":
        return LinuxBond.from_json(json)
    elif obj_type == "team":
        return LinuxTeam.from_json(json)
    elif obj_type == "linux_bridge":
        return LinuxBridge.from_json(json)
    elif obj_type == "ivs_bridge":
        return IvsBridge.from_json(json)
    elif obj_type == "ivs_interface":
        return IvsInterface.from_json(json)
    elif obj_type == "nfvswitch_bridge":
        return NfvswitchBridge.from_json(json)
    elif obj_type == "nfvswitch_internal":
        return NfvswitchInternal.from_json(json)
    elif obj_type == "ovs_tunnel":
        return OvsTunnel.from_json(json)
    elif obj_type == "ovs_patch_port":
        return OvsPatchPort.from_json(json)
    elif obj_type == "ib_interface":
        return IbInterface.from_json(json)
    elif obj_type == "ovs_dpdk_port":
        return OvsDpdkPort.from_json(json)
    elif obj_type == "ovs_dpdk_bond":
        return OvsDpdkBond.from_json(json)
    elif obj_type == "vpp_interface":
        return VppInterface.from_json(json)
    elif obj_type == "vpp_bond":
        return VppBond.from_json(json)


def _get_required_field(json, name, object_name):
    field = json.get(name)
    if not field:
        msg = '%s JSON objects require \'%s\' to be configured.' \
              % (object_name, name)
        raise InvalidConfigException(msg)
    return field


def _update_members(json, nic_mapping, persist_mapping):
    """Update object's members fields and pass mapping info to each member.

    :param json: dictionary containing object values
    :param nic_mapping: mapping of abstractions to actual nic names
    :param persist_mapping: bool indicating mapping file should be permanent
    :returns members: updated members
    """
    members = []

    members_json = json.get('members')
    if members_json:
        if isinstance(members_json, list):
            for member in members_json:
                # If this member already has a nic mapping, don't overwrite it
                if not member.get('nic_mapping'):
                    member.update({'nic_mapping': nic_mapping})
                member.update({'persist_mapping': persist_mapping})
                members.append(object_from_json(member))
        else:
            msg = 'Members must be a list.'
            raise InvalidConfigException(msg)

    return members


def _mapped_nics(nic_mapping=None):
    mapping = nic_mapping or {}
    global _MAPPED_NICS
    if _MAPPED_NICS:
        return _MAPPED_NICS
    _MAPPED_NICS = {}

    if mapping:
        # If mapping file provided, nics need not be active
        available_nics = utils.ordered_available_nics()
        for nic_alias, nic_mapped in mapping.items():

            if netaddr.valid_mac(nic_mapped):
                # If 'nic' is actually a mac address, retrieve actual nic name
                for nic in available_nics:
                    try:
                        mac = utils.interface_mac(nic)
                    except IOError:
                        continue
                    if nic_mapped == mac:
                        logger.debug("%s matches device %s" %
                                     (nic_mapped, nic))
                        nic_mapped = nic
                        break
                else:
                    # The mac could not be found on this system
                    logger.error('mac %s not found in available nics (%s)'
                                 % (nic_mapped, ', '.join(available_nics)))
                    continue

            elif nic_mapped not in available_nics:
                # nic doesn't exist on this system
                logger.error('nic %s not found in available nics (%s)'
                             % (nic_mapped, ', '.join(available_nics)))
                continue

            # Duplicate mappings are not allowed
            if nic_mapped in _MAPPED_NICS.values():
                msg = ('interface %s already mapped, '
                       'check mapping file for duplicates'
                       % nic_mapped)
                raise InvalidConfigException(msg)

            _MAPPED_NICS[nic_alias] = nic_mapped
            logger.info("%s in mapping file mapped to: %s"
                        % (nic_alias, nic_mapped))

    # nics not in mapping file must be active in order to be mapped
    active_nics = utils.ordered_active_nics()

    # Add default numbered mappings, but do not overwrite existing entries
    for nic_mapped in set(active_nics).difference(set(_MAPPED_NICS.values())):
        nic_alias = "nic%i" % (active_nics.index(nic_mapped) + 1)
        if nic_alias in _MAPPED_NICS:
            logger.warning("no mapping for interface %s because "
                           "%s is mapped to %s"
                           % (nic_mapped, nic_alias, _MAPPED_NICS[nic_alias]))
        else:
            _MAPPED_NICS[nic_alias] = nic_mapped
            logger.info("%s mapped to: %s" % (nic_alias, nic_mapped))

    if not _MAPPED_NICS:
        logger.warning('No active nics found.')
    return _MAPPED_NICS


def format_ovs_extra(obj, templates):
    """Map OVS object properties into a string to be used for ovs_extra."""

    return [t.format(name=obj.name) for t in templates or []]


def _add_fail_mode(fail_mode):
    ovs_extra = ['set bridge {name} fail_mode=%s' % fail_mode]
    if fail_mode == STANDALONE_FAIL_MODE:
        ovs_extra.append('del-controller {name}')
    return ovs_extra


class Route(object):
    """Base class for network routes."""

    def __init__(self, next_hop, ip_netmask="", default=False,
                 route_options=""):
        self.next_hop = next_hop
        self.ip_netmask = ip_netmask
        self.default = default
        self.route_options = route_options

    @staticmethod
    def from_json(json):
        next_hop = _get_required_field(json, 'next_hop', 'Route')
        ip_netmask = json.get('ip_netmask', "")
        route_options = json.get('route_options', "")
        default = strutils.bool_from_string(str(json.get('default', False)))
        return Route(next_hop, ip_netmask, default, route_options)


class Address(object):
    """Base class for network addresses."""

    def __init__(self, ip_netmask):
        self.ip_netmask = ip_netmask
        ip_nw = netaddr.IPNetwork(self.ip_netmask)
        self.ip = str(ip_nw.ip)
        self.netmask = str(ip_nw.netmask)
        self.prefixlen = ip_nw.prefixlen
        self.version = ip_nw.version

    @staticmethod
    def from_json(json):
        ip_netmask = _get_required_field(json, 'ip_netmask', 'Address')
        return Address(ip_netmask)


class _BaseOpts(object):
    """Base abstraction for logical port options."""

    def __init__(self, name, use_dhcp=False, use_dhcpv6=False, addresses=None,
                 routes=None, mtu=None, primary=False, nic_mapping=None,
                 persist_mapping=False, defroute=True, dhclient_args=None,
                 dns_servers=None, nm_controlled=False):
        addresses = addresses or []
        routes = routes or []
        dns_servers = dns_servers or []
        mapped_nic_names = _mapped_nics(nic_mapping)
        self.hwaddr = None
        self.hwname = None
        self.renamed = False
        if name in mapped_nic_names:
            if persist_mapping:
                self.name = name
                self.hwname = mapped_nic_names[name]
                self.hwaddr = utils.interface_mac(self.hwname)
                self.renamed = True
            else:
                self.name = mapped_nic_names[name]
        else:
            self.name = name

        self.mtu = mtu
        self.use_dhcp = use_dhcp
        self.use_dhcpv6 = use_dhcpv6
        self.addresses = addresses
        self.routes = routes
        self.primary = primary
        self.defroute = defroute
        self.dhclient_args = dhclient_args
        self.dns_servers = dns_servers
        self.nm_controlled = nm_controlled
        self.bridge_name = None  # internal
        self.linux_bridge_name = None  # internal
        self.ivs_bridge_name = None  # internal
        self.nfvswitch_bridge_name = None  # internal
        self.linux_bond_name = None  # internal
        self.linux_team_name = None  # internal
        self.ovs_port = False  # internal
        self.primary_interface_name = None  # internal

    def v4_addresses(self):
        v4_addresses = []
        for addr in self.addresses:
            if addr.version == 4:
                v4_addresses.append(addr)

        return v4_addresses

    def v6_addresses(self):
        v6_addresses = []
        for addr in self.addresses:
            if addr.version == 6:
                v6_addresses.append(addr)

        return v6_addresses

    @staticmethod
    def base_opts_from_json(json, include_primary=True):
        use_dhcp = strutils.bool_from_string(str(json.get('use_dhcp', False)))
        use_dhcpv6 = strutils.bool_from_string(str(json.get('use_dhcpv6',
                                               False)))
        defroute = strutils.bool_from_string(str(json.get('defroute',
                                             True)))
        mtu = json.get('mtu', None)
        dhclient_args = json.get('dhclient_args')
        dns_servers = json.get('dns_servers')
        nm_controlled = strutils.bool_from_string(str(json.get('nm_controlled',
                                                      False)))
        primary = strutils.bool_from_string(str(json.get('primary', False)))
        addresses = []
        routes = []

        # addresses
        addresses_json = json.get('addresses')
        if addresses_json:
            if isinstance(addresses_json, list):
                for address in addresses_json:
                    addresses.append(Address.from_json(address))
            else:
                msg = 'Addresses must be a list.'
                raise InvalidConfigException(msg)

        # routes
        routes_json = json.get('routes')
        if routes_json:
            if isinstance(routes_json, list):
                for route in routes_json:
                    routes.append(Route.from_json(route))
            else:
                msg = 'Routes must be a list.'
                raise InvalidConfigException(msg)

        nic_mapping = json.get('nic_mapping')
        persist_mapping = json.get('persist_mapping')

        if include_primary:
            return (use_dhcp, use_dhcpv6, addresses, routes, mtu, primary,
                    nic_mapping, persist_mapping, defroute, dhclient_args,
                    dns_servers, nm_controlled)
        else:
            return (use_dhcp, use_dhcpv6, addresses, routes, mtu,
                    nic_mapping, persist_mapping, defroute, dhclient_args,
                    dns_servers, nm_controlled)


class Interface(_BaseOpts):
    """Base class for network interfaces."""

    def __init__(self, name, use_dhcp=False, use_dhcpv6=False, addresses=None,
                 routes=None, mtu=None, primary=False, nic_mapping=None,
                 persist_mapping=False, defroute=True, dhclient_args=None,
                 dns_servers=None, nm_controlled=False, ethtool_opts=None,
                 hotplug=False):
        addresses = addresses or []
        routes = routes or []
        dns_servers = dns_servers or []
        super(Interface, self).__init__(name, use_dhcp, use_dhcpv6, addresses,
                                        routes, mtu, primary, nic_mapping,
                                        persist_mapping, defroute,
                                        dhclient_args, dns_servers,
                                        nm_controlled)
        self.ethtool_opts = ethtool_opts
        self.hotplug = hotplug

    @staticmethod
    def from_json(json):
        name = _get_required_field(json, 'name', 'Interface')
        hotplug = strutils.bool_from_string(str(json.get('hotplug', False)))
        opts = _BaseOpts.base_opts_from_json(json)
        ethtool_opts = json.get('ethtool_opts', None)
        return Interface(name, *opts, ethtool_opts=ethtool_opts,
                         hotplug=hotplug)


class Vlan(_BaseOpts):
    """Base class for VLANs.

       NOTE: the name parameter must be formated w/ vlan<num> where <num>
       matches the vlan ID being used. Example: vlan5
    """

    def __init__(self, device, vlan_id, use_dhcp=False, use_dhcpv6=False,
                 addresses=None, routes=None, mtu=None, primary=False,
                 nic_mapping=None, persist_mapping=False, defroute=True,
                 dhclient_args=None, dns_servers=None, nm_controlled=False):
        addresses = addresses or []
        routes = routes or []
        dns_servers = dns_servers or []
        name = 'vlan%i' % vlan_id
        super(Vlan, self).__init__(name, use_dhcp, use_dhcpv6, addresses,
                                   routes, mtu, primary, nic_mapping,
                                   persist_mapping, defroute, dhclient_args,
                                   dns_servers, nm_controlled)
        self.vlan_id = int(vlan_id)

        mapped_nic_names = _mapped_nics(nic_mapping)
        if device in mapped_nic_names:
            self.device = mapped_nic_names[device]
        else:
            self.device = device

    @staticmethod
    def from_json(json):
        # A vlan on an OVS bridge won't require a device (OVS Int Port)
        device = json.get('device')
        vlan_id = _get_required_field(json, 'vlan_id', 'Vlan')
        opts = _BaseOpts.base_opts_from_json(json)
        return Vlan(device, vlan_id, *opts)


class IvsInterface(_BaseOpts):
    """Base class for ivs interfaces."""

    def __init__(self, vlan_id, name='ivs', use_dhcp=False, use_dhcpv6=False,
                 addresses=None, routes=None, mtu=1500, primary=False,
                 nic_mapping=None, persist_mapping=False, defroute=True,
                 dhclient_args=None, dns_servers=None, nm_controlled=False):
        addresses = addresses or []
        routes = routes or []
        dns_servers = dns_servers or []
        name_vlan = '%s%i' % (name, vlan_id)
        super(IvsInterface, self).__init__(name_vlan, use_dhcp, use_dhcpv6,
                                           addresses, routes, mtu, primary,
                                           nic_mapping, persist_mapping,
                                           defroute, dhclient_args,
                                           dns_servers, nm_controlled)
        self.vlan_id = int(vlan_id)

    @staticmethod
    def from_json(json):
        name = json.get('name')
        vlan_id = _get_required_field(json, 'vlan_id', 'IvsInterface')
        opts = _BaseOpts.base_opts_from_json(json)
        return IvsInterface(vlan_id, name, *opts)


class NfvswitchInternal(_BaseOpts):
    """Base class for nfvswitch internal interfaces."""

    def __init__(self, vlan_id, name='nfvswitch', use_dhcp=False,
                 use_dhcpv6=False, addresses=None, routes=None, mtu=1500,
                 primary=False, nic_mapping=None, persist_mapping=False,
                 defroute=True, dhclient_args=None, dns_servers=None,
                 nm_controlled=False):
        addresses = addresses or []
        routes = routes or []
        dns_servers = dns_servers or []
        name_vlan = '%s%i' % (name, vlan_id)
        super(NfvswitchInternal, self).__init__(name_vlan, use_dhcp,
                                                use_dhcpv6, addresses, routes,
                                                mtu, primary, nic_mapping,
                                                persist_mapping, defroute,
                                                dhclient_args, dns_servers,
                                                nm_controlled)
        self.vlan_id = int(vlan_id)

    @staticmethod
    def from_json(json):
        name = json.get('name')
        vlan_id = _get_required_field(json, 'vlan_id', 'NfvswitchInternal')
        opts = _BaseOpts.base_opts_from_json(json)
        return NfvswitchInternal(vlan_id, name, *opts)


class OvsBridge(_BaseOpts):
    """Base class for OVS bridges."""

    def __init__(self, name, use_dhcp=False, use_dhcpv6=False, addresses=None,
                 routes=None, mtu=None, members=None, ovs_options=None,
                 ovs_extra=None, nic_mapping=None, persist_mapping=False,
                 defroute=True, dhclient_args=None, dns_servers=None,
                 nm_controlled=False, fail_mode=None):
        addresses = addresses or []
        routes = routes or []
        members = members or []
        dns_servers = dns_servers or []
        super(OvsBridge, self).__init__(name, use_dhcp, use_dhcpv6, addresses,
                                        routes, mtu, False, nic_mapping,
                                        persist_mapping, defroute,
                                        dhclient_args, dns_servers,
                                        nm_controlled)
        self.members = members
        self.ovs_options = ovs_options
        ovs_extra = ovs_extra or []
        if fail_mode:
            ovs_extra.extend(_add_fail_mode(fail_mode))
        self.ovs_extra = format_ovs_extra(self, ovs_extra)
        for member in self.members:
            member.bridge_name = name
            if not isinstance(member, OvsTunnel):
                member.ovs_port = True
            if member.primary:
                if self.primary_interface_name:
                    msg = 'Only one primary interface allowed per bridge.'
                    raise InvalidConfigException(msg)
                if member.primary_interface_name:
                    self.primary_interface_name = member.primary_interface_name
                else:
                    self.primary_interface_name = member.name

    @staticmethod
    def from_json(json):
        name = _get_required_field(json, 'name', 'OvsBridge')
        (use_dhcp, use_dhcpv6, addresses, routes, mtu, nic_mapping,
         persist_mapping, defroute,
         dhclient_args, dns_servers,
         nm_controlled) = _BaseOpts.base_opts_from_json(
             json, include_primary=False)
        ovs_options = json.get('ovs_options')
        ovs_extra = json.get('ovs_extra', [])
        if not isinstance(ovs_extra, list):
            ovs_extra = [ovs_extra]
        fail_mode = json.get('ovs_fail_mode', DEFAULT_OVS_BRIDGE_FAIL_MODE)

        members = _update_members(json, nic_mapping, persist_mapping)

        return OvsBridge(name, use_dhcp=use_dhcp, use_dhcpv6=use_dhcpv6,
                         addresses=addresses, routes=routes, mtu=mtu,
                         members=members, ovs_options=ovs_options,
                         ovs_extra=ovs_extra, nic_mapping=nic_mapping,
                         persist_mapping=persist_mapping, defroute=defroute,
                         dhclient_args=dhclient_args, dns_servers=dns_servers,
                         nm_controlled=nm_controlled, fail_mode=fail_mode)


class OvsUserBridge(_BaseOpts):
    """Base class for OVS User bridges."""

    def __init__(self, name, use_dhcp=False, use_dhcpv6=False, addresses=None,
                 routes=None, mtu=None, members=None, ovs_options=None,
                 ovs_extra=None, nic_mapping=None, persist_mapping=False,
                 defroute=True, dhclient_args=None, dns_servers=None,
                 nm_controlled=False, fail_mode=None):
        super(OvsUserBridge, self).__init__(name, use_dhcp, use_dhcpv6,
                                            addresses, routes, mtu, False,
                                            nic_mapping, persist_mapping,
                                            defroute, dhclient_args,
                                            dns_servers, nm_controlled)
        self.members = members or []
        self.ovs_options = ovs_options
        ovs_extra = ovs_extra or []
        if fail_mode:
            ovs_extra.extend(_add_fail_mode(fail_mode))
        self.ovs_extra = format_ovs_extra(self, ovs_extra)
        for member in self.members:
            member.bridge_name = name
            if not isinstance(member, OvsTunnel) and \
               not isinstance(member, OvsDpdkPort) and \
               not isinstance(member, OvsDpdkBond):
                member.ovs_port = True
            if member.primary:
                if self.primary_interface_name:
                    msg = 'Only one primary interface allowed per bridge.'
                    raise InvalidConfigException(msg)
                if member.primary_interface_name:
                    self.primary_interface_name = member.primary_interface_name
                else:
                    self.primary_interface_name = member.name

    @staticmethod
    def from_json(json):
        name = _get_required_field(json, 'name', 'OvsUserBridge')
        (use_dhcp, use_dhcpv6, addresses, routes, mtu, nic_mapping,
         persist_mapping, defroute,
         dhclient_args, dns_servers,
         nm_controlled) = _BaseOpts.base_opts_from_json(
             json, include_primary=False)
        ovs_options = json.get('ovs_options')
        ovs_extra = json.get('ovs_extra', [])
        if not isinstance(ovs_extra, list):
            ovs_extra = [ovs_extra]
        fail_mode = json.get('ovs_fail_mode', DEFAULT_OVS_BRIDGE_FAIL_MODE)

        members = _update_members(json, nic_mapping, persist_mapping)

        return OvsUserBridge(name, use_dhcp=use_dhcp, use_dhcpv6=use_dhcpv6,
                             addresses=addresses, routes=routes, mtu=mtu,
                             members=members, ovs_options=ovs_options,
                             ovs_extra=ovs_extra, nic_mapping=nic_mapping,
                             persist_mapping=persist_mapping,
                             defroute=defroute, dhclient_args=dhclient_args,
                             dns_servers=dns_servers,
                             nm_controlled=nm_controlled, fail_mode=fail_mode)


class LinuxBridge(_BaseOpts):
    """Base class for Linux bridges."""

    def __init__(self, name, use_dhcp=False, use_dhcpv6=False, addresses=None,
                 routes=None, mtu=None, members=None, nic_mapping=None,
                 persist_mapping=False, defroute=True, dhclient_args=None,
                 dns_servers=None, nm_controlled=False):
        addresses = addresses or []
        routes = routes or []
        members = members or []
        dns_servers = dns_servers or []
        super(LinuxBridge, self).__init__(name, use_dhcp, use_dhcpv6,
                                          addresses, routes, mtu, False,
                                          nic_mapping, persist_mapping,
                                          defroute, dhclient_args, dns_servers,
                                          nm_controlled)
        self.members = members
        for member in self.members:
            member.linux_bridge_name = name
            member.ovs_port = False
            if member.primary:
                if self.primary_interface_name:
                    msg = 'Only one primary interface allowed per bridge.'
                    raise InvalidConfigException(msg)
                if member.primary_interface_name:
                    self.primary_interface_name = member.primary_interface_name
                else:
                    self.primary_interface_name = member.name

    @staticmethod
    def from_json(json):
        name = _get_required_field(json, 'name', 'LinuxBridge')
        (use_dhcp, use_dhcpv6, addresses, routes, mtu, nic_mapping,
         persist_mapping, defroute, dhclient_args,
         dns_servers, nm_controlled) = _BaseOpts.base_opts_from_json(
             json, include_primary=False)

        members = _update_members(json, nic_mapping, persist_mapping)

        return LinuxBridge(name, use_dhcp=use_dhcp, use_dhcpv6=use_dhcpv6,
                           addresses=addresses, routes=routes, mtu=mtu,
                           members=members, nic_mapping=nic_mapping,
                           persist_mapping=persist_mapping, defroute=defroute,
                           dhclient_args=dhclient_args,
                           dns_servers=dns_servers,
                           nm_controlled=nm_controlled)


class IvsBridge(_BaseOpts):
    """Base class for IVS bridges.

    Indigo Virtual Switch (IVS) is a virtual switch for Linux.
    It is compatible with the KVM hypervisor and leveraging the
    Open vSwitch kernel module for packet forwarding. There are
    three major differences between IVS and OVS:
    1. Each node can have at most one ivs, no name required.
    2. Bond is not allowed to attach to an ivs. It is the SDN
    controller's job to dynamically form bonds on ivs.
    3. IP address can only be statically assigned.
    """

    def __init__(self, name='ivs', use_dhcp=False, use_dhcpv6=False,
                 addresses=None, routes=None, mtu=1500, members=None,
                 nic_mapping=None, persist_mapping=False, defroute=True,
                 dhclient_args=None, dns_servers=None, nm_controlled=False):
        addresses = addresses or []
        routes = routes or []
        members = members or []
        dns_servers = dns_servers or []
        super(IvsBridge, self).__init__(name, use_dhcp, use_dhcpv6,
                                        addresses, routes, mtu, False,
                                        nic_mapping, persist_mapping,
                                        defroute, dhclient_args, dns_servers,
                                        nm_controlled)
        self.members = members
        for member in self.members:
            if isinstance(member, OvsBond) or isinstance(member, LinuxBond):
                msg = 'IVS does not support bond interfaces.'
                raise InvalidConfigException(msg)
            member.ivs_bridge_name = name
            member.ovs_port = False
            self.primary_interface_name = None  # ivs doesn't use primary intf

    @staticmethod
    def from_json(json):
        name = 'ivs'
        (use_dhcp, use_dhcpv6, addresses, routes, mtu, nic_mapping,
         persist_mapping, defroute, dhclient_args,
         dns_servers, nm_controlled) = _BaseOpts.base_opts_from_json(
             json, include_primary=False)

        members = _update_members(json, nic_mapping, persist_mapping)

        return IvsBridge(name, use_dhcp=use_dhcp, use_dhcpv6=use_dhcpv6,
                         addresses=addresses, routes=routes, mtu=mtu,
                         members=members, nic_mapping=nic_mapping,
                         persist_mapping=persist_mapping, defroute=defroute,
                         dhclient_args=dhclient_args,
                         dns_servers=dns_servers, nm_controlled=nm_controlled)


class NfvswitchBridge(_BaseOpts):
    """Base class for NFVSwitch bridges.

    NFVSwitch is a virtual switch for Linux.
    It is compatible with the KVM hypervisor and uses DPDK for packet
    forwarding.
    """

    def __init__(self, name='nfvswitch', use_dhcp=False, use_dhcpv6=False,
                 addresses=None, routes=None, mtu=1500, members=None,
                 nic_mapping=None, persist_mapping=False, defroute=True,
                 dhclient_args=None, dns_servers=None, nm_controlled=False,
                 options=""):
        addresses = addresses or []
        routes = routes or []
        members = members or []
        dns_servers = dns_servers or []
        super(NfvswitchBridge, self).__init__(name, use_dhcp, use_dhcpv6,
                                              addresses, routes, mtu, False,
                                              nic_mapping, persist_mapping,
                                              defroute, dhclient_args,
                                              dns_servers, nm_controlled)
        self.options = options
        self.members = members
        for member in self.members:
            if isinstance(member, OvsBond) or isinstance(member, LinuxBond):
                msg = 'NFVSwitch does not support bond interfaces.'
                raise InvalidConfigException(msg)
            member.nfvswitch_bridge_name = name
            member.ovs_port = False
            self.primary_interface_name = None

    @staticmethod
    def from_json(json):
        name = 'nfvswitch'
        (use_dhcp, use_dhcpv6, addresses, routes, mtu, nic_mapping,
         persist_mapping, defroute, dhclient_args,
         dns_servers, nm_controlled) = _BaseOpts.base_opts_from_json(
             json, include_primary=False)

        members = _update_members(json, nic_mapping, persist_mapping)

        options = json.get('options')
        if not options:
            msg = 'Config "options" is mandatory.'
            raise InvalidConfigException(msg)

        return NfvswitchBridge(name, use_dhcp=use_dhcp, use_dhcpv6=use_dhcpv6,
                               addresses=addresses, routes=routes, mtu=mtu,
                               members=members, nic_mapping=nic_mapping,
                               persist_mapping=persist_mapping,
                               defroute=defroute, dhclient_args=dhclient_args,
                               dns_servers=dns_servers,
                               nm_controlled=nm_controlled, options=options)


class LinuxTeam(_BaseOpts):
    """Base class for Linux bonds using teamd."""

    def __init__(self, name, use_dhcp=False, use_dhcpv6=False, addresses=None,
                 routes=None, mtu=None, primary=False, members=None,
                 bonding_options=None, nic_mapping=None, persist_mapping=False,
                 defroute=True, dhclient_args=None, dns_servers=None,
                 nm_controlled=False):
        addresses = addresses or []
        routes = routes or []
        members = members or []
        dns_servers = dns_servers or []
        super(LinuxTeam, self).__init__(name, use_dhcp, use_dhcpv6, addresses,
                                        routes, mtu, primary, nic_mapping,
                                        persist_mapping, defroute,
                                        dhclient_args, dns_servers,
                                        nm_controlled)
        self.members = members
        self.bonding_options = bonding_options
        for member in self.members:
            member.linux_team_name = name
            if member.primary:
                if self.primary_interface_name:
                    msg = 'Only one primary interface allowed per team.'
                    raise InvalidConfigException(msg)
                if member.primary_interface_name:
                    self.primary_interface_name = member.primary_interface_name
                else:
                    self.primary_interface_name = member.name

    @staticmethod
    def from_json(json):
        name = _get_required_field(json, 'name', 'LinuxTeam')
        (use_dhcp, use_dhcpv6, addresses, routes, mtu, nic_mapping,
         persist_mapping, defroute, dhclient_args,
         dns_servers, nm_controlled) = _BaseOpts.base_opts_from_json(
             json, include_primary=False)
        bonding_options = json.get('bonding_options')

        members = _update_members(json, nic_mapping, persist_mapping)

        return LinuxTeam(name, use_dhcp=use_dhcp, use_dhcpv6=use_dhcpv6,
                         addresses=addresses, routes=routes, mtu=mtu,
                         members=members, bonding_options=bonding_options,
                         nic_mapping=nic_mapping,
                         persist_mapping=persist_mapping, defroute=defroute,
                         dhclient_args=dhclient_args, dns_servers=dns_servers,
                         nm_controlled=nm_controlled)


class LinuxBond(_BaseOpts):
    """Base class for Linux bonds."""

    def __init__(self, name, use_dhcp=False, use_dhcpv6=False, addresses=None,
                 routes=None, mtu=None, primary=False, members=None,
                 bonding_options=None, nic_mapping=None, persist_mapping=False,
                 defroute=True, dhclient_args=None, dns_servers=None,
                 nm_controlled=False):
        addresses = addresses or []
        routes = routes or []
        members = members or []
        dns_servers = dns_servers or []
        super(LinuxBond, self).__init__(name, use_dhcp, use_dhcpv6, addresses,
                                        routes, mtu, primary, nic_mapping,
                                        persist_mapping, defroute,
                                        dhclient_args, dns_servers,
                                        nm_controlled)
        self.members = members
        self.bonding_options = bonding_options
        for member in self.members:
            member.linux_bond_name = name
            if member.primary:
                if self.primary_interface_name:
                    msg = 'Only one primary interface allowed per bond.'
                    raise InvalidConfigException(msg)
                if member.primary_interface_name:
                    self.primary_interface_name = member.primary_interface_name
                else:
                    self.primary_interface_name = member.name

    @staticmethod
    def from_json(json):
        name = _get_required_field(json, 'name', 'LinuxBond')
        (use_dhcp, use_dhcpv6, addresses, routes, mtu, nic_mapping,
         persist_mapping, defroute, dhclient_args,
         dns_servers, nm_controlled) = _BaseOpts.base_opts_from_json(
             json, include_primary=False)
        bonding_options = json.get('bonding_options')

        members = _update_members(json, nic_mapping, persist_mapping)

        return LinuxBond(name, use_dhcp=use_dhcp, use_dhcpv6=use_dhcpv6,
                         addresses=addresses, routes=routes, mtu=mtu,
                         members=members, bonding_options=bonding_options,
                         nic_mapping=nic_mapping,
                         persist_mapping=persist_mapping, defroute=defroute,
                         dhclient_args=dhclient_args, dns_servers=dns_servers,
                         nm_controlled=nm_controlled)


class OvsBond(_BaseOpts):
    """Base class for OVS bonds."""

    def __init__(self, name, use_dhcp=False, use_dhcpv6=False, addresses=None,
                 routes=None, mtu=None, primary=False, members=None,
                 ovs_options=None, ovs_extra=None, nic_mapping=None,
                 persist_mapping=False, defroute=True, dhclient_args=None,
                 dns_servers=None, nm_controlled=False):
        addresses = addresses or []
        routes = routes or []
        members = members or []
        dns_servers = dns_servers or []
        super(OvsBond, self).__init__(name, use_dhcp, use_dhcpv6, addresses,
                                      routes, mtu, primary, nic_mapping,
                                      persist_mapping, defroute, dhclient_args,
                                      dns_servers, nm_controlled)
        self.members = members
        self.ovs_options = ovs_options
        self.ovs_extra = format_ovs_extra(self, ovs_extra)
        for member in self.members:
            if member.primary:
                if self.primary_interface_name:
                    msg = 'Only one primary interface allowed per bond.'
                    raise InvalidConfigException(msg)
                if member.primary_interface_name:
                    self.primary_interface_name = member.primary_interface_name
                else:
                    self.primary_interface_name = member.name
        if not self.primary_interface_name:
            bond_members = list(self.members)
            bond_members.sort(key=lambda x: x.name)
            self.primary_interface_name = bond_members[0].name

    @staticmethod
    def from_json(json):
        name = _get_required_field(json, 'name', 'OvsBond')
        (use_dhcp, use_dhcpv6, addresses, routes, mtu, nic_mapping,
         persist_mapping, defroute, dhclient_args,
         dns_servers, nm_controlled) = _BaseOpts.base_opts_from_json(
             json, include_primary=False)
        ovs_options = json.get('ovs_options')
        ovs_extra = json.get('ovs_extra', [])
        if not isinstance(ovs_extra, list):
            ovs_extra = [ovs_extra]

        members = _update_members(json, nic_mapping, persist_mapping)

        return OvsBond(name, use_dhcp=use_dhcp, use_dhcpv6=use_dhcpv6,
                       addresses=addresses, routes=routes, mtu=mtu,
                       members=members, ovs_options=ovs_options,
                       ovs_extra=ovs_extra, nic_mapping=nic_mapping,
                       persist_mapping=persist_mapping, defroute=defroute,
                       dhclient_args=dhclient_args, dns_servers=dns_servers,
                       nm_controlled=nm_controlled)


class OvsTunnel(_BaseOpts):
    """Base class for OVS Tunnels."""

    def __init__(self, name, use_dhcp=False, use_dhcpv6=False, addresses=None,
                 routes=None, mtu=None, primary=False, nic_mapping=None,
                 persist_mapping=False, defroute=True, dhclient_args=None,
                 dns_servers=None, nm_controlled=False, tunnel_type=None,
                 ovs_options=None, ovs_extra=None):
        addresses = addresses or []
        routes = routes or []
        dns_servers = dns_servers or []
        super(OvsTunnel, self).__init__(name, use_dhcp, use_dhcpv6, addresses,
                                        routes, mtu, primary, nic_mapping,
                                        persist_mapping, defroute,
                                        dhclient_args, dns_servers,
                                        nm_controlled)
        self.tunnel_type = tunnel_type
        self.ovs_options = ovs_options or []
        self.ovs_extra = format_ovs_extra(self, ovs_extra)

    @staticmethod
    def from_json(json):
        name = _get_required_field(json, 'name', 'OvsTunnel')
        tunnel_type = _get_required_field(json, 'tunnel_type', 'OvsTunnel')
        ovs_options = json.get('ovs_options', [])
        ovs_options = ['options:%s' % opt for opt in ovs_options]
        ovs_extra = json.get('ovs_extra', [])
        if not isinstance(ovs_extra, list):
            ovs_extra = [ovs_extra]
        opts = _BaseOpts.base_opts_from_json(json)
        return OvsTunnel(name, *opts, tunnel_type=tunnel_type,
                         ovs_options=ovs_options, ovs_extra=ovs_extra)


class OvsPatchPort(_BaseOpts):
    """Base class for OVS Patch Ports."""

    def __init__(self, name, use_dhcp=False, use_dhcpv6=False, addresses=None,
                 routes=None, mtu=None, primary=False, nic_mapping=None,
                 persist_mapping=False, defroute=True, dhclient_args=None,
                 dns_servers=None, nm_controlled=False, bridge_name=None,
                 peer=None, ovs_options=None, ovs_extra=None):
        addresses = addresses or []
        routes = routes or []
        dns_servers = dns_servers or []
        super(OvsPatchPort, self).__init__(name, use_dhcp, use_dhcpv6,
                                           addresses, routes, mtu, primary,
                                           nic_mapping, persist_mapping,
                                           defroute, dhclient_args,
                                           dns_servers, nm_controlled)
        self.bridge_name = bridge_name
        self.peer = peer
        self.ovs_options = ovs_options or []
        self.ovs_extra = format_ovs_extra(self, ovs_extra)

    @staticmethod
    def from_json(json):
        name = _get_required_field(json, 'name', 'OvsPatchPort')
        bridge_name = _get_required_field(json, 'bridge_name', 'OvsPatchPort')
        peer = _get_required_field(json, 'peer', 'OvsPatchPort')
        ovs_options = json.get('ovs_options', [])
        ovs_options = ['options:%s' % opt for opt in ovs_options]
        ovs_extra = json.get('ovs_extra', [])
        if not isinstance(ovs_extra, list):
            ovs_extra = [ovs_extra]
        opts = _BaseOpts.base_opts_from_json(json)
        return OvsPatchPort(name, *opts, bridge_name=bridge_name, peer=peer,
                            ovs_options=ovs_options, ovs_extra=ovs_extra)


class IbInterface(_BaseOpts):
    """Base class for InfiniBand network interfaces."""

    def __init__(self, name, use_dhcp=False, use_dhcpv6=False, addresses=None,
                 routes=None, mtu=None, primary=False, nic_mapping=None,
                 persist_mapping=False, defroute=True, dhclient_args=None,
                 dns_servers=None, nm_controlled=False, ethtool_opts=None):
        addresses = addresses or []
        routes = routes or []
        dns_servers = dns_servers or []
        super(IbInterface, self).__init__(name, use_dhcp, use_dhcpv6,
                                          addresses, routes, mtu, primary,
                                          nic_mapping, persist_mapping,
                                          defroute, dhclient_args, dns_servers,
                                          nm_controlled)
        self.ethtool_opts = ethtool_opts

    @staticmethod
    def from_json(json):
        name = _get_required_field(json, 'name', 'IbInterface')
        ethtool_opts = json.get('ethtool_opts', None)
        opts = _BaseOpts.base_opts_from_json(json)
        return IbInterface(name, *opts, ethtool_opts=ethtool_opts)


class OvsDpdkPort(_BaseOpts):
    """Base class for OVS Dpdk Ports."""

    def __init__(self, name, use_dhcp=False, use_dhcpv6=False, addresses=None,
                 routes=None, mtu=None, primary=False, nic_mapping=None,
                 persist_mapping=False, defroute=True, dhclient_args=None,
                 dns_servers=None, nm_controlled=False, members=None,
                 driver='vfio-pci', ovs_options=None, ovs_extra=None,
                 rx_queue=None):

        super(OvsDpdkPort, self).__init__(name, use_dhcp, use_dhcpv6,
                                          addresses, routes, mtu, primary,
                                          nic_mapping, persist_mapping,
                                          defroute, dhclient_args,
                                          dns_servers, nm_controlled)
        self.members = members or []
        self.ovs_options = ovs_options or []
        self.ovs_extra = format_ovs_extra(self, ovs_extra)
        self.driver = driver
        self.rx_queue = rx_queue

    @staticmethod
    def from_json(json):
        name = _get_required_field(json, 'name', 'OvsDpdkPort')
        # driver name by default will be 'vfio-pci' if not specified
        (use_dhcp, use_dhcpv6, addresses, routes, mtu, primary, nic_mapping,
         persist_mapping, defroute, dhclient_args,
         dns_servers, nm_controlled) = _BaseOpts.base_opts_from_json(json)

        driver = json.get('driver')
        if not driver:
            driver = 'vfio-pci'

        # members
        members = []
        members_json = json.get('members')
        if members_json:
            if isinstance(members_json, list):
                if len(members_json) == 1:
                    member = members_json[0]
                    if not member.get('nic_mapping'):
                        member.update({'nic_mapping': nic_mapping})
                    member.update({'persist_mapping': persist_mapping})
                    iface = object_from_json(member)
                    if isinstance(iface, Interface):
                        # TODO(skramaja): Add checks for IP and route not to
                        # be set in the interface part of DPDK Port
                        members.append(iface)
                    else:
                        msg = 'OVS DPDK Port should have only interface member'
                        raise InvalidConfigException(msg)
                else:
                    msg = 'OVS DPDK Port should have only one member'
                    raise InvalidConfigException(msg)
            else:
                msg = 'Members must be a list.'
                raise InvalidConfigException(msg)
        else:
            msg = 'DPDK Port should have one member as Interface'
            raise InvalidConfigException(msg)

        rx_queue = json.get('rx_queue', None)
        ovs_options = json.get('ovs_options', [])
        ovs_options = ['options:%s' % opt for opt in ovs_options]
        ovs_extra = json.get('ovs_extra', [])
        if not isinstance(ovs_extra, list):
            ovs_extra = [ovs_extra]
        return OvsDpdkPort(name, use_dhcp=use_dhcp, use_dhcpv6=use_dhcpv6,
                           addresses=addresses, routes=routes, mtu=mtu,
                           primary=primary, nic_mapping=nic_mapping,
                           persist_mapping=persist_mapping, defroute=defroute,
                           dhclient_args=dhclient_args,
                           dns_servers=dns_servers,
                           nm_controlled=nm_controlled, members=members,
                           driver=driver, ovs_options=ovs_options,
                           ovs_extra=ovs_extra, rx_queue=rx_queue)


class OvsDpdkBond(_BaseOpts):
    """Base class for OVS DPDK bonds."""

    def __init__(self, name, use_dhcp=False, use_dhcpv6=False, addresses=None,
                 routes=None, mtu=None, primary=False, members=None,
                 ovs_options=None, ovs_extra=None, nic_mapping=None,
                 persist_mapping=False, defroute=True, dhclient_args=None,
                 dns_servers=None, nm_controlled=False, rx_queue=None):
        super(OvsDpdkBond, self).__init__(name, use_dhcp, use_dhcpv6,
                                          addresses, routes, mtu, primary,
                                          nic_mapping, persist_mapping,
                                          defroute, dhclient_args, dns_servers,
                                          nm_controlled)
        self.members = members or []
        self.ovs_options = ovs_options
        self.ovs_extra = format_ovs_extra(self, ovs_extra)
        self.rx_queue = rx_queue

        for member in self.members:
            if member.primary:
                if self.primary_interface_name:
                    msg = 'Only one primary interface allowed per bond (dpdk).'
                    raise InvalidConfigException(msg)
                if member.primary_interface_name:
                    self.primary_interface_name = member.primary_interface_name
                else:
                    self.primary_interface_name = member.name
        if not self.primary_interface_name:
            bond_members = list(self.members)
            bond_members.sort(key=lambda x: x.name)
            self.primary_interface_name = bond_members[0].name

    @staticmethod
    def from_json(json):
        name = _get_required_field(json, 'name', 'OvsDpdkBond')
        (use_dhcp, use_dhcpv6, addresses, routes, mtu, nic_mapping,
         persist_mapping, defroute, dhclient_args,
         dns_servers, nm_controlled) = _BaseOpts.base_opts_from_json(
             json, include_primary=False)
        rx_queue = json.get('rx_queue', None)
        ovs_options = json.get('ovs_options')
        ovs_extra = json.get('ovs_extra', [])
        if not isinstance(ovs_extra, list):
            ovs_extra = [ovs_extra]
        members = []

        # members
        members_json = json.get('members')
        if members_json:
            if isinstance(members_json, list):
                for member in members_json:
                    if not member.get('nic_mapping'):
                        member.update({'nic_mapping': nic_mapping})
                    member.update({'persist_mapping': persist_mapping})
                    obj = object_from_json(member)
                    if isinstance(obj, OvsDpdkPort):
                        members.append(obj)
                    else:
                        msg = 'Members must be of type ovs_dpdk_port'
                        raise InvalidConfigException(msg)
            else:
                msg = 'Members must be a list.'
                raise InvalidConfigException(msg)

        return OvsDpdkBond(name, use_dhcp=use_dhcp, use_dhcpv6=use_dhcpv6,
                           addresses=addresses, routes=routes, mtu=mtu,
                           members=members, ovs_options=ovs_options,
                           ovs_extra=ovs_extra, nic_mapping=nic_mapping,
                           persist_mapping=persist_mapping,
                           defroute=defroute, dhclient_args=dhclient_args,
                           dns_servers=dns_servers,
                           nm_controlled=nm_controlled, rx_queue=rx_queue)


class VppInterface(_BaseOpts):
    """Base class for VPP Interface.

    Vector Packet Processing (VPP) is a high performance packet processing
    stack that runs in user space in Linux. VPP is used as an alternative to
    kernel networking stack for accelerated network data path. VPP uses DPDK
    poll-mode drivers to bind system interfaces rather than kernel drivers.
    VPP bound interfaces are not visible to kernel networking stack, so we
    must handle them separately.

    The following parameters can be specified in addition to base Interface:
      - uio_driver: DPDK poll-mode driver name. Defaults to 'vfio-pci', valid
                    values are 'uio_pci_generic' and 'vfio-pci'.
      - options: Interface options such as vlan stripping and tx/rx transmit
                 queues specification. Defaults to None. Reference for those
                 configurations can be found at
                 https://wiki.fd.io/view/VPP/Command-line_Arguments
                 Example: 'vlan-strip-offload on num-rx-queues 3'

    Note that 'name' attribute is used to indicate the kernel nic that should
    be bound to VPP. Once VPP binds the interface, a mapping file will be
    updated with the interface's information, and this file will be used in
    subsequent runs of os-net-config.
    """
    def __init__(self, name, use_dhcp=False, use_dhcpv6=False, addresses=None,
                 routes=None, mtu=None, primary=False, nic_mapping=None,
                 persist_mapping=False, defroute=True, dhclient_args=None,
                 dns_servers=None, nm_controlled=False, uio_driver='vfio-pci',
                 options=None):
        addresses = addresses or []

        super(VppInterface, self).__init__(name, use_dhcp, use_dhcpv6,
                                           addresses, routes, mtu, primary,
                                           nic_mapping, persist_mapping,
                                           defroute, dhclient_args,
                                           dns_servers, nm_controlled)
        self.uio_driver = uio_driver
        self.options = options
        # pci_dev contains pci address for the interface, it will be populated
        # when interface is added to config object. It will be determined
        # either through ethtool or by looking up the dpdk mapping file.
        self.pci_dev = None

    @staticmethod
    def from_json(json):
        name = _get_required_field(json, 'name', 'VppInterface')
        uio_driver = json.get('uio_driver', 'vfio-pci')
        options = json.get('options', '')

        opts = _BaseOpts.base_opts_from_json(json)
        return VppInterface(name, *opts, uio_driver=uio_driver,
                            options=options)


class VppBond(_BaseOpts):
    """Base class for VPP Bond."""
    def __init__(self, name, use_dhcp=False, use_dhcpv6=False, addresses=None,
                 routes=None, mtu=None, primary=False, nic_mapping=None,
                 persist_mapping=False, defroute=True, dhclient_args=None,
                 dns_servers=None, nm_controlled=False,
                 members=None, bonding_options=None):
        addresses = addresses or []
        members = members or []

        super(VppBond, self).__init__(name, use_dhcp, use_dhcpv6,
                                      addresses, routes, mtu, primary,
                                      nic_mapping, persist_mapping,
                                      defroute, dhclient_args,
                                      dns_servers, nm_controlled)
        self.members = members
        self.bonding_options = bonding_options

    @staticmethod
    def from_json(json):
        name = _get_required_field(json, 'name', 'VppBond')
        bonding_options = json.get('bonding_options', '')

        (use_dhcp, use_dhcpv6, addresses, routes, mtu, nic_mapping,
         persist_mapping, defroute, dhclient_args,
         dns_servers, nm_controlled) = _BaseOpts.base_opts_from_json(
             json, include_primary=False)

        members = []
        members_json = json.get('members', None)
        if members_json:
            if isinstance(members_json, list):
                for member in members_json:
                    if not member.get('nic_mapping'):
                        member.update({'nic_mapping': nic_mapping})
                    member.update({'persist_mapping': persist_mapping})
                    obj = object_from_json(member)
                    if isinstance(obj, VppInterface):
                        members.append(obj)
                    else:
                        msg = 'Members must be of type vpp_interface'
                        raise InvalidConfigException(msg)
            else:
                msg = 'Members must be a list.'
                raise InvalidConfigException(msg)

        return VppBond(name, use_dhcp=use_dhcp, use_dhcpv6=use_dhcpv6,
                       addresses=addresses, routes=routes, mtu=mtu,
                       members=members, nic_mapping=nic_mapping,
                       persist_mapping=persist_mapping,
                       defroute=defroute, dhclient_args=dhclient_args,
                       dns_servers=dns_servers, nm_controlled=nm_controlled,
                       bonding_options=bonding_options)
