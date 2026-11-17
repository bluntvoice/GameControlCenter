"""Changing addresses, mDNS aliases and truthful preparation checks."""
import subprocess
import unittest
from unittest.mock import Mock,patch

from backend import Center
from device_connection import connect_device


SERVICES='adb-phone-session _adb._tcp. 192.0.2.45:5555\nadb-phone-session _adb-tls-connect._tcp. 192.0.2.45:42441\n'
MDNS='adb-phone-session._adb-tls-connect._tcp.'


def reply(text='',code=0):return subprocess.CompletedProcess([],code,text,'')


class DeviceConnectionTests(unittest.TestCase):
    def test_new_ip_replaces_old_address_and_deduplicates_aliases(self):
        run=Mock(side_effect=[reply(MDNS+' device\n192.0.2.45:5555 device'),reply(SERVICES),reply('device')])
        result=connect_device(dict(serial='192.0.2.100:5555'),run)
        self.assertEqual(result,dict(serial=MDNS,phone_address='192.0.2.45:42441',device_identity='adb-phone'))
        self.assertFalse(any(c.args[0]=='disconnect' for c in run.call_args_list))

    def test_online_ip_is_replaced_by_tcp_alias_before_projection_starts(self):
        run=Mock(side_effect=[reply('192.0.2.45:5555 device\n'+MDNS+' device'),reply(SERVICES),reply('device')])
        result=connect_device(dict(serial='192.0.2.45:5555',device_identity='adb-phone'),run)
        self.assertEqual(result['serial'],MDNS)
        self.assertEqual(run.call_args.args,('-s',MDNS,'get-state'))

    def test_active_ip_projection_is_not_redirected_to_another_channel(self):
        serial='192.0.2.45:5555'
        run=Mock(side_effect=[reply(serial+' device\n'+MDNS+' device'),reply(SERVICES),reply('device')])
        result=connect_device(dict(serial=serial,device_identity='adb-phone'),run,active_serial=serial)
        self.assertEqual(result['serial'],serial)

    def test_unusable_alias_falls_back_to_verified_ip_endpoint(self):
        run=Mock(side_effect=[reply(MDNS+' device\n192.0.2.45:5555 device'),reply(SERVICES),reply('offline',1),reply('device')])
        result=connect_device(dict(serial='192.0.2.45:5555',device_identity='adb-phone'),run)
        self.assertEqual(result['serial'],'192.0.2.45:5555')

    def test_active_mdns_session_is_preserved_and_ip_is_resolved(self):
        run=Mock(side_effect=[reply(MDNS+' device'),reply(SERVICES),reply('device')])
        result=connect_device(dict(serial=MDNS,device_identity='adb-phone'),run)
        self.assertEqual(result['serial'],MDNS)
        self.assertEqual(result['phone_address'],'192.0.2.45:42441')

    def test_multiple_phones_are_not_silently_selected(self):
        run=Mock(side_effect=[reply('other device'),reply(SERVICES)])
        with self.assertRaisesRegex(RuntimeError,'多台手机'):
            connect_device(dict(serial='old'),run)

    def test_bound_phone_is_not_replaced_by_another_phone(self):
        run=Mock(side_effect=[reply('other device'),reply(''),reply('other')])
        with self.assertRaisesRegex(RuntimeError,'未发现已选择'):
            connect_device(dict(serial='old',device_identity='adb-phone'),run)

    def test_bound_online_ip_is_verified_when_mdns_is_empty(self):
        serial='192.0.2.56:5555'
        run=Mock(side_effect=[reply(serial+' device'),reply(''),reply('phone\n'),reply('device')])
        result=connect_device(dict(serial=serial,device_identity='adb-phone'),run,active_serial=serial)
        self.assertEqual(result,dict(serial=serial,phone_address=serial,device_identity='adb-phone'))
        self.assertEqual(run.call_args_list[2].args,('-s',serial,'shell','getprop','ro.serialno'))
        self.assertFalse(any(c.args[0] in ('connect','disconnect') for c in run.call_args_list))

    def test_bound_phone_can_move_ip_without_mdns(self):
        serial='192.0.2.56:5555'
        run=Mock(side_effect=[reply(serial+' device'),reply(''),reply('phone'),reply('device')])
        result=connect_device(dict(serial='192.0.2.45:5555',device_identity='adb-phone'),run)
        self.assertEqual(result['serial'],serial)
        self.assertEqual(result['device_identity'],'adb-phone')

    def test_hardware_verification_selects_bound_phone_among_multiple_devices(self):
        run=Mock(side_effect=[reply('other device\n192.0.2.56:5555 device'),reply(''),reply('other'),reply('phone'),reply('device')])
        result=connect_device(dict(serial='old',device_identity='adb-phone'),run)
        self.assertEqual(result['serial'],'192.0.2.56:5555')

    def test_hardware_verification_failure_does_not_trust_single_online_ip(self):
        for answer in (reply('',1),reply(''),reply('unknown'),RuntimeError('读取超时')):
            with self.subTest(answer=answer):
                run=Mock(side_effect=[reply('192.0.2.56:5555 device'),reply(''),answer])
                with self.assertRaisesRegex(RuntimeError,'未发现已选择'):
                    connect_device(dict(serial='192.0.2.56:5555',device_identity='adb-phone'),run)
                self.assertEqual(run.call_count,3)

    def test_usb_serial_matches_saved_mdns_identity(self):
        run=Mock(side_effect=[reply('phone device'),reply(''),reply('phone'),reply('device')])
        result=connect_device(dict(serial='old',device_identity='adb-phone'),run)
        self.assertEqual(result['serial'],'phone')

    def test_tls_endpoint_is_used_when_legacy_port_is_unreachable(self):
        def run(*args,**kwargs):
            if args[0]=='devices':return reply('')
            if args[0]=='mdns':return reply(SERVICES)
            if args==('connect','192.0.2.45:5555'):raise RuntimeError('连接超时')
            if args[0]=='connect':return reply('connected')
            return reply('device')
        result=connect_device(dict(serial='old'),run)
        self.assertEqual(result['serial'],'192.0.2.45:42441')

    def test_prepare_does_not_launch_adapter_or_report_ready_after_connection_failure(self):
        c=Center.__new__(Center);c.connect_phone=Mock(side_effect=RuntimeError('离线'))
        c.open_component=Mock();c.request_pad=Mock();c.event=Mock()
        with self.assertRaisesRegex(RuntimeError,'离线'):c.prepare()
        c.open_component.assert_not_called();c.request_pad.assert_not_called();c.event.assert_not_called()

    def test_prepare_reports_missing_projection_instead_of_success(self):
        c=Center.__new__(Center);c.config=dict(serial='phone')
        c.connect_phone=Mock();c.open_component=Mock();c.request_pad=Mock();c.event=Mock()
        with patch('backend.winprobe.windows',return_value=[]):
            with self.assertRaisesRegex(RuntimeError,'投屏窗口尚未打开'):c.prepare()
        c.request_pad.assert_not_called();c.event.assert_not_called()
