"""Route evidence and consecutive-failure decisions without live network or accounts."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('network_audit', ROOT / 'core/network-audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def connection(host='api.anthropic.com', port=12345, chains=None, process=''):
    return {'metadata': {'host': host, 'sourcePort': str(port), 'processPath': process},
            'chains': ['Fixed-A', 'AI'] if chains is None else chains,
            'rule': 'DomainSuffix', 'rulePayload': 'anthropic.com'}


class NetworkAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        base = self.home / '.claude-switcher'
        base.mkdir()
        self.policy = base / 'exit-policy.json'
        self.policy.write_text(json.dumps({'mode': 'clash-selector', 'group': 'AI',
            'nodes': {'Fixed-A': {'ip': '192.0.2.20', 'country': 'US'}},
            'controller_socket': '/private/test.sock', 'controller_secret': 'SECRET'}))
        self.controller = Mock()
        self.config = {'mode': 'rule', 'tun': {'enable': True}, 'ipv6': False, 'mixed-port': 7897}
        self.proxies = {'Fixed-A': {'dialer-proxy': 'Airport'},
                        'Airport': {'now': 'Entry'}, 'Entry': {}}
        self.observed = []
        self.selected = 'Fixed-A'

        def query(path):
            return {'/proxies/AI': {'type': 'Selector', 'now': self.selected},
                    '/configs': self.config, '/proxies': {'proxies': self.proxies},
                    '/connections': {'connections': self.observed}}[path]

        self.controller.get.side_effect = query
        self.controller_patch = patch.object(audit, 'Controller', return_value=self.controller)
        self.controller_patch.start()
        self.addCleanup(self.controller_patch.stop)
        self.probe_patch = patch.object(audit, 'probe', side_effect=lambda client, port, host, path, group, selected, **options:
            {'host': host, 'state': 'ok', 'http_status': '401', 'transport_ok': True,
             'chains': [selected, group]})
        self.probes = self.probe_patch.start()
        self.addCleanup(self.probe_patch.stop)

    def run_audit(self, **options):
        return audit.audit(self.home, 'AI', **options)

    def test_no_application_connections_do_not_become_a_claim_of_app_verification(self):
        report = self.run_audit()
        self.assertEqual(report['state'], 'info')
        self.assertIn('尚未观察', report['detail'])
        self.assertEqual(report['transit_selection'], ['Airport', 'Entry'])
        self.assertEqual(len(report['probes']), 2)
        self.assertNotIn('SECRET', json.dumps(report))

    def test_missing_policy_is_explicitly_unverified(self):
        self.policy.unlink()
        self.assertEqual(self.run_audit()['state'], 'warn')
        self.probes.assert_not_called()

    def test_unreadable_policy_does_not_fall_back_to_success(self):
        self.policy.write_text('{bad json')
        self.assertEqual(self.run_audit()['state'], 'fail')

    def test_wrong_mode_or_disabled_tun_stops_before_probes(self):
        for mode, enable in [('global', True), ('rule', False)]:
            self.config.update(mode=mode, tun={'enable': enable})
            self.assertEqual(self.run_audit()['state'], 'fail')
        self.probes.assert_not_called()

    def test_missing_http_port_is_not_a_route_pass(self):
        self.config.pop('mixed-port')
        self.assertEqual(self.run_audit()['state'], 'warn')
        self.probes.assert_not_called()

    def test_ipv6_enabled_or_unknown_stops_before_probes(self):
        for value in [True, None]:
            self.config['ipv6'] = value
            self.assertEqual(self.run_audit()['state'], 'fail')
        self.probes.assert_not_called()

    def test_pin_mismatch_blocks_both_regular_scan_and_desktop_guard(self):
        pin = self.home / '.claude-switcher/expected-exit-ip'
        pin.write_text('192.0.2.21')
        for guard in [False, True]:
            self.assertEqual(self.run_audit(guard=guard)['state'], 'fail')
        self.probes.assert_not_called()
        pin.write_text('192.0.2.20')
        with patch.object(audit, 'exit_probe', return_value=True):
            self.assertEqual(self.run_audit(guard=True)['state'], 'info')

    def test_unknown_selected_exit_and_controller_failure_are_failures(self):
        self.selected = 'Unknown'
        self.assertEqual(self.run_audit()['state'], 'fail')
        self.controller.get.side_effect = OSError('SECRET /private/test.sock')
        report = self.run_audit()
        self.assertEqual(report['state'], 'fail')
        self.assertNotIn('SECRET', json.dumps(report))
        self.assertNotIn('/private/test.sock', json.dumps(report))

    def test_observed_wrong_application_chain_fails_despite_good_probe(self):
        self.observed = [connection(process='/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
                                    chains=['DIRECT'])]
        report = self.run_audit()
        self.assertEqual(report['state'], 'fail')
        self.assertEqual(report['observations'][0]['client'], '浏览器')

    def test_unknown_process_is_not_presented_as_a_real_claude_client(self):
        self.observed = [connection(process='/usr/bin/python3')]
        self.assertEqual(self.run_audit()['observations'], [])

    def test_guard_limits_observations_to_desktop_and_checks_actual_exit(self):
        self.observed = [connection(process='/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
                                    chains=['DIRECT'])]
        with patch.object(audit, 'exit_probe', return_value=True) as exit_check:
            report = self.run_audit(guard=True)
        self.assertEqual(report['state'], 'info')
        self.assertEqual(len(report['probes']), 1)
        self.assertEqual(report['observations'], [])
        exit_check.assert_called_once_with(7897, '192.0.2.20', 'US')
        with patch.object(audit, 'exit_probe', return_value=False):
            self.assertEqual(self.run_audit(guard=True)['state'], 'fail')

    def test_selection_race_is_not_reported_as_a_pass(self):
        def change(client, port, host, path, group, selected):
            self.selected = 'Changed'
            return {'host': host, 'state': 'ok', 'http_status': '401', 'transport_ok': True}
        self.probes.side_effect = change
        self.assertEqual(self.run_audit()['state'], 'warn')

    def test_proxy_dependency_cycle_is_not_silently_ignored(self):
        self.proxies['Entry']['dialer-proxy'] = 'Fixed-A'
        self.assertEqual(self.run_audit()['state'], 'fail')

    def configure_protected_listener(self):
        data = json.loads(self.policy.read_text())
        data['protected_listener'] = {'name': 'Claude-Protected-HTTP', 'port': 17897, 'proxy': 'Fixed-A'}
        self.policy.write_text(json.dumps(data))
        (self.home / '.claude-switcher/expected-exit-ip').write_text('192.0.2.20')
        self.proxies['Fixed-A']['type'] = 'Http'

    def test_protected_listener_probes_only_its_port_and_does_not_attribute_other_profiles(self):
        self.configure_protected_listener()
        self.observed = [connection(process='/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
                                    chains=['DIRECT'])]
        report = self.run_audit(protected=True)
        self.assertEqual(report['state'], 'info')
        self.assertEqual(report['protected_port'], 17897)
        self.assertEqual(report['protected_listener'], 'Claude-Protected-HTTP')
        self.assertEqual(report['protected_proxy'], 'Fixed-A')
        self.assertEqual(report['observations'], [])
        self.assertIn('不按浏览器资料', report['detail'])
        self.assertEqual({item['host'] for item in report['probes']},
                         {'claude.ai', 'api.anthropic.com', 'www.cloudflare.com'})
        for call in self.probes.call_args_list:
            self.assertEqual(call.args[1], 17897)
            self.assertIsNone(call.args[4])
            self.assertEqual(call.kwargs['inbound'], 'Claude-Protected-HTTP')
            self.assertEqual(call.kwargs.get('expected_exit'),
                             ('192.0.2.20', 'US') if call.args[2] == 'www.cloudflare.com' else None)
        self.assertNotIn('SECRET', json.dumps(report))

    def test_protected_listener_requires_valid_configuration_and_fixed_us_pin(self):
        self.configure_protected_listener()
        original = json.loads(self.policy.read_text())
        cases = [None, {}, {'name': 'bad name', 'port': 17897, 'proxy': 'Fixed-A'},
                 {'name': 'Claude-Protected-HTTP', 'port': 7897, 'proxy': 'Fixed-A'},
                 {'name': 'Claude-Protected-HTTP', 'port': True, 'proxy': 'Fixed-A'},
                 {'name': 'Claude-Protected-HTTP', 'port': 1023, 'proxy': 'Fixed-A'},
                 {'name': 'Claude-Protected-HTTP', 'port': 65536, 'proxy': 'Fixed-A'},
                 {'name': 'Claude-Protected-HTTP', 'port': 17897, 'proxy': 'DIRECT'},
                 {'name': 'Claude-Protected-HTTP', 'port': 17897, 'proxy': 'AI'},
                 {'name': 'Claude-Protected-HTTP', 'port': 17897, 'proxy': 'Other'}]
        for listener in cases:
            with self.subTest(listener=listener):
                self.policy.write_text(json.dumps(dict(original, protected_listener=listener)))
                self.assertEqual(self.run_audit(protected=True)['state'], 'fail')
        self.policy.write_text(json.dumps(original))
        pin = self.home / '.claude-switcher/expected-exit-ip'
        pin.unlink()
        self.assertEqual(self.run_audit(protected=True)['state'], 'fail')
        pin.write_text('192.0.2.21')
        self.assertEqual(self.run_audit(protected=True)['state'], 'fail')
        pin.write_text('192.0.2.20')
        original['nodes']['Fixed-A']['country'] = 'JP'
        self.policy.write_text(json.dumps(original))
        self.assertEqual(self.run_audit(protected=True)['state'], 'fail')
        self.probes.assert_not_called()

    def test_protected_listener_cannot_bind_a_group_or_unknown_outbound_type(self):
        self.configure_protected_listener()
        for kind in [None, 'Selector', 'URLTest', 'Fallback', 'LoadBalance', 'Relay', 'Direct', 'Reject']:
            with self.subTest(kind=kind):
                self.proxies['Fixed-A']['type'] = kind
                self.assertEqual(self.run_audit(protected=True)['state'], 'fail')
        self.probes.assert_not_called()

    def test_protected_probe_failure_or_missing_evidence_never_passes(self):
        self.configure_protected_listener()
        for state in ['fail', 'warn']:
            with self.subTest(state=state):
                self.probes.side_effect = lambda *args, **kwargs: {
                    'host': args[2], 'state': state, 'http_status': '200', 'transport_ok': True}
                self.assertEqual(self.run_audit(protected=True)['state'], state)


class TLSProbeTests(unittest.TestCase):
    def test_protected_probe_requires_its_inbound_and_concrete_node_without_the_selection_group(self):
        for inbound, chains, expected in [('Claude-Protected-HTTP', ['Fixed-A'], 'ok'),
                                         ('Mixed', ['Fixed-A'], 'fail'),
                                         (None, ['Fixed-A'], 'fail'),
                                         ('Claude-Protected-HTTP', ['Fixed-A', 'DIRECT'], 'fail'),
                                         ('Claude-Protected-HTTP', ['Other'], 'fail')]:
            with self.subTest(inbound=inbound, chains=chains):
                item = connection(chains=chains)
                item['metadata'].update(inboundIP='127.0.0.1', inboundPort='17897', specialProxy='Fixed-A')
                if inbound is not None:
                    item['metadata']['inboundName'] = inbound
                client, secure = Mock(), Mock()
                client.get.return_value = {'connections': [item]}
                secure.sock.getsockname.return_value = ('127.0.0.1', 12345)
                secure.getresponse.return_value.status = 401
                with patch.object(audit.http.client, 'HTTPSConnection', return_value=secure):
                    result = audit.probe(client, 17897, 'api.anthropic.com', '/v1/models',
                                         None, 'Fixed-A', inbound='Claude-Protected-HTTP')
                self.assertEqual(result['state'], expected)
                self.assertTrue(result['transport_ok'])

    def test_protected_probe_requires_actual_port_loopback_and_forced_proxy(self):
        cases = [{'specialProxy': None}, {'specialProxy': 'Other'},
                 {'inboundPort': None}, {'inboundPort': '7897'},
                 {'inboundIP': None}, {'inboundIP': '0.0.0.0'}, {'inboundIP': '::1'}]
        for changed in cases:
            with self.subTest(changed=changed):
                item = connection(chains=['Fixed-A'])
                item['metadata'].update(inboundName='Claude-Protected-HTTP', inboundIP='127.0.0.1',
                                        inboundPort='17897', specialProxy='Fixed-A')
                for key, value in changed.items():
                    if value is None:
                        item['metadata'].pop(key)
                    else:
                        item['metadata'][key] = value
                client, secure = Mock(), Mock()
                client.get.return_value = {'connections': [item]}
                secure.sock.getsockname.return_value = ('127.0.0.1', 12345)
                secure.getresponse.return_value.status = 401
                with patch.object(audit.http.client, 'HTTPSConnection', return_value=secure):
                    result = audit.probe(client, 17897, 'api.anthropic.com', '/v1/models',
                                         None, 'Fixed-A', inbound='Claude-Protected-HTTP')
                self.assertEqual(result['state'], 'fail')
                self.assertTrue(result['transport_ok'])

    def test_protected_trace_checks_actual_exit_on_the_same_verified_connection(self):
        for status, raw, expected in [(200, b'ip=192.0.2.20\nloc=US\n', 'ok'),
                                      (200, b'ip=192.0.2.21\nloc=US\n', 'fail'),
                                      (200, b'ip=192.0.2.20\nloc=JP\n', 'fail'),
                                      (403, b'blocked', 'fail'),
                                      (200, b'x' * 16385, 'fail')]:
            with self.subTest(status=status, expected=expected):
                item = connection(host='www.cloudflare.com', chains=['Fixed-A'])
                item['metadata'].update(inboundName='Claude-Protected-HTTP', inboundIP='127.0.0.1',
                                        inboundPort='17897', specialProxy='Fixed-A')
                client, secure = Mock(), Mock()
                client.get.return_value = {'connections': [item]}
                secure.sock.getsockname.return_value = ('127.0.0.1', 12345)
                secure.getresponse.return_value.status = status
                secure.getresponse.return_value.read.return_value = raw
                with patch.object(audit.http.client, 'HTTPSConnection', return_value=secure):
                    result = audit.probe(client, 17897, 'www.cloudflare.com', '/cdn-cgi/trace',
                                         None, 'Fixed-A', inbound='Claude-Protected-HTTP',
                                         expected_exit=('192.0.2.20', 'US'))
                self.assertEqual(result['state'], expected)
                self.assertNotIn('192.0.2.', json.dumps(result))
                secure.close.assert_called_once()

    def test_http_request_or_response_failure_is_a_transport_failure(self):
        for operation in ['request', 'getresponse']:
            with self.subTest(operation=operation):
                client, secure = Mock(), Mock()
                client.get.return_value = {'connections': [connection()]}
                secure.sock.getsockname.return_value = ('127.0.0.1', 12345)
                getattr(secure, operation).side_effect = OSError('private failure details')
                with patch.object(audit.http.client, 'HTTPSConnection', return_value=secure):
                    result = audit.probe(client, 7897, 'api.anthropic.com', '/v1/models', 'AI', 'Fixed-A')
                self.assertEqual(result['state'], 'fail')
                self.assertFalse(result['transport_ok'])
                self.assertEqual(result['http_status'], '000')
                self.assertEqual(result['chains'], ['Fixed-A', 'AI'])
                self.assertNotIn('private failure details', json.dumps(result))
                secure.close.assert_called_once()

    def test_controller_failure_does_not_hide_a_completed_http_response(self):
        client, secure = Mock(), Mock()
        client.get.side_effect = OSError('private controller details')
        secure.sock.getsockname.return_value = ('127.0.0.1', 12345)
        secure.getresponse.return_value.status = 401
        with patch.object(audit.http.client, 'HTTPSConnection', return_value=secure):
            result = audit.probe(client, 7897, 'api.anthropic.com', '/v1/models', 'AI', 'Fixed-A')
        self.assertEqual(result['state'], 'warn')
        self.assertTrue(result['transport_ok'])
        self.assertEqual(result['http_status'], '401')
        self.assertNotIn('private controller details', json.dumps(result))
        secure.request.assert_called_once()
        secure.close.assert_called_once()

    def test_matches_own_source_port_and_host_not_an_unrelated_connection(self):
        client = Mock()
        client.get.return_value = {'connections': [connection(port=11111, chains=['DIRECT']), connection()]}
        secure = Mock()
        secure.sock.getsockname.return_value = ('127.0.0.1', 12345)
        secure.getresponse.return_value.status = 401
        with patch.object(audit.http.client, 'HTTPSConnection', return_value=secure):
            result = audit.probe(client, 7897, 'api.anthropic.com', '/v1/models', 'AI', 'Fixed-A')
        self.assertEqual(result['state'], 'ok')
        self.assertEqual(result['http_status'], '401')
        secure.set_tunnel.assert_called_once_with('api.anthropic.com', 443)
        self.assertNotIn('Authorization', secure.request.call_args.kwargs['headers'])
        secure.close.assert_called_once()

    def test_direct_and_other_exit_are_failures(self):
        for chain in [['DIRECT'], ['Fixed-B', 'AI'], ['Fixed-A', 'AI', 'DIRECT']]:
            self.assertFalse(audit.matches_exit(connection(chains=chain), 'AI', 'Fixed-A'))

    def test_missing_connection_is_unverified_and_tls_failure_is_failure(self):
        client, secure = Mock(), Mock()
        client.get.return_value = {'connections': []}
        secure.sock.getsockname.return_value = ('127.0.0.1', 12345)
        secure.getresponse.return_value.status = 403
        with patch.object(audit.http.client, 'HTTPSConnection', return_value=secure):
            result = audit.probe(client, 7897, 'claude.ai', '/', 'AI', 'Fixed-A')
            self.assertEqual(result['state'], 'warn')
            self.assertTrue(result['transport_ok'])
            self.assertEqual(result['http_status'], '403')
            secure.connect.side_effect = OSError('private connection details')
            result = audit.probe(client, 7897, 'claude.ai', '/', 'AI', 'Fixed-A')
        self.assertEqual(result['state'], 'fail')
        self.assertNotIn('private connection details', json.dumps(result))


class GuardDecisionTests(unittest.TestCase):
    def test_missing_evidence_counts_towards_stop_and_idle_or_verified_recovery_clears_it(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'status.json'
            uncertain = {'state': 'warn', 'selected': 'Fixed-A'}
            self.assertFalse(audit.guard_state(uncertain, path)['terminate_desktop'])
            self.assertTrue(audit.guard_state(uncertain, path)['terminate_desktop'])
            recovered = audit.guard_state({'state': 'info', 'selected': 'Fixed-A'}, path)
            self.assertEqual(recovered['consecutive_failures'], 0)
            self.assertFalse(audit.guard_state(uncertain, path)['terminate_desktop'])
            idle = audit.guard_state({'state': 'warn', 'idle': True}, path)
            self.assertEqual(idle['state'], 'idle')
            self.assertEqual(idle['consecutive_failures'], 0)
            self.assertFalse(idle['terminate_desktop'])

    def test_two_http_blackholes_after_tls_trigger_the_desktop_decision(self):
        client, secure = Mock(), Mock()
        client.get.return_value = {'connections': [connection()]}
        secure.sock.getsockname.return_value = ('127.0.0.1', 12345)
        secure.getresponse.side_effect = TimeoutError('response timed out')
        with tempfile.TemporaryDirectory() as folder, patch.object(audit.http.client, 'HTTPSConnection', return_value=secure):
            path = Path(folder) / 'status.json'
            for expected in [False, True]:
                result = audit.probe(client, 7897, 'api.anthropic.com', '/v1/models', 'AI', 'Fixed-A')
                snapshot = audit.guard_state({'state': result['state'], 'selected': 'Fixed-A'}, path)
                self.assertEqual(snapshot['terminate_desktop'], expected)

    def test_consecutive_failures_persist_and_recovery_resets_them(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'status.json'
            bad = {'state': 'fail', 'selected': 'Fixed-A'}
            self.assertFalse(audit.guard_state(bad, path)['terminate_desktop'])
            self.assertTrue(audit.guard_state(bad, path)['terminate_desktop'])
            healthy = audit.guard_state({'state': 'info', 'selected': 'Fixed-A'}, path)
            self.assertEqual(healthy['consecutive_failures'], 0)
            self.assertFalse(audit.guard_state(bad, path)['terminate_desktop'])

    def test_selection_change_and_idle_do_not_reuse_old_failure_count(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'status.json'
            audit.guard_state({'state': 'fail', 'selected': 'Fixed-A'}, path)
            self.assertFalse(audit.guard_state({'state': 'fail', 'selected': 'Fixed-B'}, path)['terminate_desktop'])
            state = audit.guard_state({'state': 'info', 'idle': True}, path)
            self.assertEqual(state['state'], 'idle')
            self.assertFalse(state['network_verified'])
            self.assertEqual(state['consecutive_failures'], 0)


if __name__ == '__main__':
    unittest.main()
