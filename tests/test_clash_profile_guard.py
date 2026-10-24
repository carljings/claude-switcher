import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('profile_guard', ROOT / 'core/clash-profile-guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class ProfileGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.base = self.home / '.claude-switcher'
        self.base.mkdir()
        self.clash = self.home / 'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev'
        self.profiles = self.clash / 'profiles'
        self.profiles.mkdir(parents=True)
        self.script = self.profiles / 'fixture.js'
        self.old_script = b'function main(config) { return config; }\n'
        self.script.write_bytes(self.old_script)
        (self.base / 'profile-guard-owned.json').write_text(json.dumps({'fixture.js': hashlib.sha256(self.old_script).hexdigest()}))
        self.policy = self.base / 'exit-policy.json'
        self.policy.write_text(json.dumps({'mode': 'clash-selector', 'group': 'AI',
            'profile_guard_scripts': ['fixture.js'], 'controller_socket': '/test.sock',
            'controller_secret': 'fixture-secret', 'nodes': {'Fixed': '192.0.2.20'}}))
        self.config = self.clash / 'config.yaml'
        self.config.write_bytes(b'ipv6: true\nmode: rule\n')
        self.runtime = {'mode': 'rule', 'tun': {'enable': True}, 'ipv6': True}
        self.calls = []
        fixture = self
        class FakeController:
            def __init__(self, policy): pass
            def request(self, method, path, payload=None):
                fixture.calls.append((method, path, payload))
                if method == 'PATCH':
                    fixture.runtime.update(payload)
                    return None
                if path == '/configs': return dict(fixture.runtime)
                return {'type': 'Selector', 'now': 'Fixed'}
        self.controller = patch.object(guard, 'Controller', FakeController)
        self.controller.start()
        self.addCleanup(self.controller.stop)

    def test_installs_final_script_and_disables_current_and_persistent_ipv6(self):
        result = guard.repair(self.home, 'AI')
        self.assertEqual(self.script.read_bytes(), guard.render('AI'))
        self.assertIn(b'ipv6: false', self.config.read_bytes())
        self.assertIs(self.runtime['ipv6'], False)
        self.assertTrue(result['profile_reload_required'])
        self.assertEqual(guard.repair(self.home, 'AI')['files_changed'], 0)

    def test_unknown_custom_script_is_preserved_without_controller_changes(self):
        self.script.write_bytes(b'function main(c) { c.important=true; return c; }')
        with self.assertRaises(ValueError): guard.repair(self.home, 'AI')
        self.assertIn(b'important', self.script.read_bytes())
        self.assertFalse(self.calls)
        self.assertEqual(self.config.read_bytes(), b'ipv6: true\nmode: rule\n')

    def test_invalid_or_missing_opt_in_is_zero_mutations(self):
        data = json.loads(self.policy.read_text())
        for names in [[], ['../other.js']]:
            data['profile_guard_scripts'] = names
            self.policy.write_text(json.dumps(data))
            with self.assertRaises(ValueError): guard.repair(self.home, 'AI')
        self.assertFalse(self.calls)
        self.assertEqual(self.script.read_bytes(), self.old_script)

    def test_inactive_tun_is_rejected_before_file_changes(self):
        self.runtime['tun'] = {'enable': False}
        with self.assertRaises(ValueError): guard.repair(self.home, 'AI')
        self.assertEqual(self.script.read_bytes(), self.old_script)
        self.assertFalse(any(c[0] == 'PATCH' for c in self.calls))

    def test_failed_readback_restores_original_files_and_ipv6(self):
        def broken(path, content):
            if path.name == 'profile-guard-owned.json': raise OSError('fixture failure')
            return original(path, content)
        original = guard.atomic
        with patch.object(guard, 'atomic', side_effect=broken):
            with self.assertRaises(OSError): guard.repair(self.home, 'AI')
        self.assertEqual(self.script.read_bytes(), self.old_script)
        self.assertEqual(self.config.read_bytes(), b'ipv6: true\nmode: rule\n')
        self.assertIs(self.runtime['ipv6'], True)

    @unittest.skipUnless(shutil.which('node'), 'Node required only for JS fixture')
    def test_rendered_guard_is_idempotent_and_retains_original_rules_and_groups(self):
        code = guard.render('AI').decode() + '''
let cfg={"proxy-groups":[{name:"AI",type:"select",proxies:["Fixed"]}],rules:["MATCH,DIRECT"],dns:{nameserver:["fixture"]}};
let first=JSON.stringify(main(cfg)); let second=JSON.stringify(main(cfg));
if(first!==second||cfg.rules[0]!=="AND,((NETWORK,udp),(DST-PORT,3478)),REJECT"||cfg.rules.at(-1)!=="MATCH,DIRECT"||cfg.ipv6!==false||cfg.dns.ipv6!==false||cfg.dns.nameserver[0]!=="fixture"||cfg["proxy-groups"][0].proxies[0]!=="Fixed")process.exit(1);
'''
        subprocess.run(['node', '-e', code], check=True, capture_output=True, timeout=8)


if __name__ == '__main__': unittest.main()
