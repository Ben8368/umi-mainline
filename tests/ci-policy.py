#!/usr/bin/env python3
"""Regression checks for CI privileges, pinned actions and a fail-closed gate."""
import importlib.util
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return yaml.load((ROOT / name).read_text(), Loader=yaml.BaseLoader)


class PolicyTests(unittest.TestCase):
    def test_gate_rejects_missing_failed_cancelled_and_skipped(self):
        spec = importlib.util.spec_from_file_location('ci_result', ROOT / 'scripts/ci-result.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        good = {key: {'result': 'success'} for key in module.REQUIRED}
        self.assertFalse(module.failures(good))
        for key in module.REQUIRED:
            for result in ['failure', 'cancelled', 'skipped', None]:
                self.assertTrue(module.failures({**good, key: {'result': result}}))
            self.assertTrue(module.failures({k: v for k, v in good.items() if k != key}))
        self.assertTrue(module.failures([]))

    def test_ci_routes_every_pull_request_and_aggregates_all_jobs(self):
        ci = load('.github/workflows/ci.yml')
        self.assertIn('pull_request', ci['on'])
        self.assertIn('merge_group', ci['on'])
        self.assertNotIn('paths', ci['on'].get('pull_request') or {})
        self.assertEqual(ci['permissions'], {'contents': 'read'})
        gate = ci['jobs']['result']
        self.assertEqual(gate['name'], 'CI result')
        self.assertEqual(gate['if'], 'always()')
        self.assertCountEqual(gate['needs'], ['governance', 'lint', 'offline'])
        self.assertEqual(ci['jobs']['offline']['strategy']['matrix']['runner'],
                         ['ubuntu-24.04', 'ubuntu-24.04-arm'])

    def test_every_action_is_pinned_and_checkout_drops_credentials(self):
        for path in (ROOT / '.github/workflows').glob('*.yml'):
            doc = load(str(path.relative_to(ROOT)))
            for job in doc['jobs'].values():
                self.assertIn('timeout-minutes', job)
                for step in job.get('steps', []):
                    if action := step.get('uses'):
                        self.assertRegex(action, r'^[\w.-]+/[\w./-]+@[0-9a-f]{40}$')
                        if action.startswith('actions/checkout@'):
                            self.assertEqual(step['with']['persist-credentials'], 'false')

    def test_metadata_workflows_never_checkout_or_execute_issue_input(self):
        for name in ['labeler.yml', 'bot-dispatch.yml', 'stale.yml']:
            doc = load('.github/workflows/' + name)
            for job in doc['jobs'].values():
                for step in job['steps']:
                    self.assertNotIn('checkout', step.get('uses', ''))
                    self.assertNotIn('run', step)
            self.assertNotEqual(doc['permissions'].get('contents'), 'write')

    def test_kernel_build_uses_one_literal_pinned_checkout_per_version(self):
        doc = load('.github/workflows/kernel.yml')
        self.assertEqual(doc['on'], {'workflow_dispatch': ''})
        self.assertEqual(doc['permissions'], {'contents': 'read'})
        job = doc['jobs']['kernel']
        matrix = job['strategy']['matrix']
        self.assertEqual(set(matrix), {'version'})
        steps = job['steps']
        external = [step for step in steps
                    if step.get('with', {}).get('repository')]
        pins = {
            '6.12.94': '0b8f247169e487eff2d4c2dd531bc43f7efda2cb',
            '7.2.12': 'cc9de5d4b5ab6459f5774946aa3195ad51236fa8',
        }
        self.assertCountEqual(matrix['version'], pins)
        self.assertEqual(len(external), len(pins))
        build_index = next(i for i, step in enumerate(steps)
                           if step.get('run') == 'sh scripts/build.sh')
        for version, sha in pins.items():
            matches = [step for step in external
                       if step.get('if') == f"matrix.version == '{version}'"]
            self.assertEqual(len(matches), 1)
            step = matches[0]
            self.assertTrue(step['uses'].startswith('actions/checkout@'))
            self.assertEqual(step['with'], {
                'repository': 'gregkh/linux', 'ref': sha,
                'path': '.kernel-ci', 'persist-credentials': 'false',
            })
            self.assertLess(steps.index(step), build_index)

    def test_bots_never_automerge_and_sensitive_paths_are_excluded(self):
        rabbit = load('.coderabbit.yaml')
        self.assertEqual(rabbit['reviews']['auto_review']['base_branches'], ['master'])
        for setting in rabbit['reviews']['finishing_touches'].values():
            self.assertEqual(setting['enabled'], 'false')
        script = load('.github/workflows/bot-dispatch.yml')['jobs']['dispatch']['steps'][0]['with']['script']
        for word in ['kernel', 'power', 'firmware', 'storage', 'build', 'agent:codex']:
            self.assertIn("'" + word + "'", script)
        self.assertNotRegex(script, r"['\"](?:scripts|power|dts)/\*\*['\"]")
        import json
        renovate = json.loads((ROOT / 'renovate.json').read_text())
        self.assertFalse(renovate['automerge'])
        self.assertTrue(renovate['dependencyDashboardApproval'])


if __name__ == '__main__':
    unittest.main()
