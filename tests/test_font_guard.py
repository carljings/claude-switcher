"""Font-only content script checks in Node VM; never opens a browser/profile."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / 'core/font-guard'
HOSTS = [
    'https://claude.ai/*', 'https://*.claude.ai/*',
    'https://claude.com/*', 'https://*.claude.com/*',
    'https://ippure.com/*', 'https://www.ippure.com/*',
]


class FontGuardManifestTests(unittest.TestCase):
    def test_manifest_is_static_narrow_and_has_no_extra_capabilities(self):
        manifest = json.loads((EXTENSION / 'manifest.json').read_text())
        self.assertEqual(manifest['manifest_version'], 3)
        self.assertEqual(manifest['name'], 'Claude Protected Font Guard')
        self.assertEqual(manifest['version'], '0.1.0')
        for key in ['permissions', 'optional_permissions', 'host_permissions',
                    'optional_host_permissions', 'background', 'action']:
            self.assertNotIn(key, manifest)
        self.assertEqual(manifest['content_scripts'], [{
            'matches': HOSTS, 'js': ['font-guard.js'], 'world': 'MAIN',
            'run_at': 'document_start', 'all_frames': True,
            'match_about_blank': True, 'match_origin_as_fallback': True,
        }])

    def test_original_mit_credit_and_source_are_preserved(self):
        license_text = (EXTENSION / 'LICENSE').read_text()
        self.assertIn('MIT License', license_text)
        self.assertIn('Copyright (c) 2026 LinXiaoTao', license_text)
        script = (EXTENSION / 'font-guard.js').read_text()
        self.assertIn('bb0015805a4a92a7ed9221693219a69315123aee', script)
        self.assertIn('https://github.com/LinXiaoTao/FuckClaude', script)


@unittest.skipUnless(shutil.which('node'), 'Node required for content script fixtures')
class FontGuardBehaviorTests(unittest.TestCase):
    def run_case(self, code):
        fixture = r'''
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8');
function makeContext() {
  class Canvas {
    constructor() { this.font = '16px Arial'; this.measured = []; this.drawn = []; }
    measureText(text) {
      this.measured.push(this.font);
      if (text === 'throw') throw new TypeError('native failure');
      return {width: /PingFang|STHeiti|STSong|Hiragino|SimSun/i.test(this.font) ? 99 : 10,
              actualBoundingBoxLeft: 1};
    }
    fillText(text) { this.drawn.push({text, font: this.font}); }
  }
  class Offscreen {
    constructor() { this.font = '16px Arial'; this.measured = []; }
    measureText(text) { this.measured.push(this.font); return {width: 10}; }
  }
  class Fonts {
    constructor() { this.checked = []; }
    check(font, text) {
      this.checked.push({font, text});
      if (font === 'invalid') throw new SyntaxError('native invalid font');
      return true;
    }
  }
  const navigator = {language: 'en-US', userAgent: 'native fixture',
                     platform: 'MacIntel', languages: ['en-US', 'en']};
  const DateConstructor = Date;
  const intl = Intl;
  const webRtc = function NativeRTCPeerConnection() {};
  const context = vm.createContext({CanvasRenderingContext2D: Canvas,
      OffscreenCanvasRenderingContext2D: Offscreen, FontFaceSet: Fonts,
      navigator, Date: DateConstructor, Intl: intl, RTCPeerConnection: webRtc,
      fetch() { throw new Error('network forbidden'); }});
  const original = {navigator, DateConstructor, intl, webRtc,
      fillText: Canvas.prototype.fillText, measure: Canvas.prototype.measureText};
  return {context, Canvas, Offscreen, Fonts, original};
}
const {context, Canvas, Offscreen, Fonts, original} = makeContext();
vm.runInContext(source, context);
'''
        result = subprocess.run(['node', '-e', fixture + code, str(EXTENSION / 'font-guard.js')],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_hidden_family_uses_fallback_for_measurement_and_restores_font(self):
        self.run_case(r'''
const ctx = new Canvas();
for (const font of ['72px "PingFang SC", monospace',
                    "italic bold 24px 'STHeiti', serif", '16px SimSun, Arial']) {
  ctx.font = font;
  assert.equal(ctx.measureText('probe').width, 10);
  assert.equal(ctx.font, font);
  assert.ok(!/PingFang|STHeiti|SimSun/.test(ctx.measured.at(-1)));
}
ctx.font = '16px "STSong"';
ctx.measureText('probe');
assert.equal(ctx.measured.at(-1), '16px sans-serif');
assert.equal(ctx.font, '16px "STSong"');
''')

    def test_native_error_still_restores_the_original_font(self):
        self.run_case(r'''
const ctx = new Canvas();
ctx.font = '16px "PingFang SC", monospace';
assert.throws(() => ctx.measureText('throw'), TypeError);
assert.equal(ctx.font, '16px "PingFang SC", monospace');
''')

    def test_normal_measurement_and_actual_drawing_are_unchanged(self):
        self.run_case(r'''
const ctx = new Canvas();
ctx.font = 'italic 16px Arial, serif';
const metric = ctx.measureText('normal');
assert.equal(metric.width, 10);
assert.equal(metric.actualBoundingBoxLeft, 1);
assert.equal(ctx.measured.at(-1), ctx.font);
assert.equal(Canvas.prototype.fillText, original.fillText);
ctx.font = '16px "PingFang SC", monospace';
ctx.measureText('probe');
ctx.fillText('中文');
assert.deepEqual(ctx.drawn, [{text: '中文', font: '16px "PingFang SC", monospace'}]);
''')

    def test_font_check_filters_the_list_but_preserves_other_native_behavior(self):
        self.run_case(r'''
const fonts = new Fonts();
assert.equal(fonts.check('16px "PingFang SC"', 'probe'), false);
assert.equal(fonts.check('16px "pingfang sc", serif', 'probe'), false);
assert.equal(fonts.checked.length, 0);
assert.equal(fonts.check('16px Arial', 'text'), true);
assert.deepEqual(fonts.checked, [{font: '16px Arial', text: 'text'}]);
assert.throws(() => fonts.check('invalid'), SyntaxError);
''')

    def test_same_realm_offscreen_is_filtered_and_duplicate_injection_is_noop(self):
        self.run_case(r'''
const canvasMethod = Canvas.prototype.measureText;
const offscreenMethod = Offscreen.prototype.measureText;
const checkMethod = Fonts.prototype.check;
vm.runInContext(source, context);
assert.equal(Canvas.prototype.measureText, canvasMethod);
assert.equal(Offscreen.prototype.measureText, offscreenMethod);
assert.equal(Fonts.prototype.check, checkMethod);
const ctx = new Offscreen();
ctx.font = '16px "Hiragino Sans GB", monospace';
ctx.measureText('probe');
assert.equal(ctx.measured.at(-1), '16px monospace');
assert.equal(ctx.font, '16px "Hiragino Sans GB", monospace');
''')

    def test_timezone_language_ua_and_webrtc_objects_are_not_replaced(self):
        self.run_case(r'''
assert.equal(context.navigator, original.navigator);
assert.equal(context.Date, original.DateConstructor);
assert.equal(context.Intl, original.intl);
assert.equal(context.RTCPeerConnection, original.webRtc);
assert.equal(context.navigator.language, 'en-US');
assert.equal(context.navigator.userAgent, 'native fixture');
''')


if __name__ == '__main__':
    unittest.main()
