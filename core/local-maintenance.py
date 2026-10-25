#!/usr/bin/env python3
"""Opt-in, local-only maintenance with fixed scopes, previews and reversible moves.

Cache categories and separation of cleanup from identity work were informed by
CCBaga (MIT), commit bdfb90ceadfc5fae6772ffff597bddecb0b73cc3. This implementation
uses Switcher's own backup protocol; it does not use CCBaga's irreversible reset.
"""
import argparse
from contextlib import contextmanager
import ctypes
import fcntl
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import time

PROFILE = 'Library/Application Support/Claude Protected Edge'
NATIVE = '.claude-native-greencloud'
ID_KEYS = ('userID', 'machineID', 'anonymousId')
CACHE_PATHS = ('Default/Cache', 'Default/Code Cache', 'Default/GPUCache',
               'Default/DawnCache', 'Default/DawnGraphiteCache', 'Default/DawnWebGPUCache',
               'Default/Service Worker/CacheStorage', 'Default/Service Worker/ScriptCache',
               'ShaderCache', 'GrShaderCache', 'GraphiteDawnCache', 'Crashpad/reports')
MODES = {
    'cache': ('browser', '专用浏览器缓存', '保留Cookie、密码、书签和历史；缓存将保存为私有备份。'),
    'browser-reset': ('browser', '专用浏览器资料', '新资料需要重新登录；原资料整体保存，可恢复。'),
    'desktop-ids': ('desktop', '当前Claude桌面本地标识', '可能需要重新验证；只处理当前资料，不修改A/B归档或钥匙串。'),
    'native-ids': ('native', '预置独立CLI目录的本地标识', '仅处理.claude-native-greencloud内指定标识，不修改默认GLM、OAuth或钥匙串。'),
}
TOKEN = re.compile(r'^[0-9a-f]{32}$')
TTL = 600
MAX_JSON = 16 * 1024 * 1024
MAX_RECORD = 64 * 1024 * 1024
MAX_SCAN = 12 * 1024 * 1024  # Leave room for current, staged and backup trees in one journal.


class MaintenanceError(ValueError):
    def __init__(self, code, message, recovery_required=False):
        super().__init__(message)
        self.code, self.message, self.recovery_required = code, message, recovery_required


def fail(code, message, recovery_required=False):
    raise MaintenanceError(code, message, recovery_required)


def _rename(source, destination):
    _exclusive_rename(source, destination)


def _exclusive_rename(source, destination):
    # Never let a late-created destination be replaced by POSIX rename semantics.
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin' and hasattr(libc, 'renamex_np'):
        function = libc.renamex_np
        function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        # sys/stdio.h: RENAME_EXCL | RENAME_NOFOLLOW_ANY. Unsupported flags fail closed.
        arguments = (os.fsencode(source), os.fsencode(destination), 0x00000014)
    elif sys.platform.startswith('linux') and hasattr(libc, 'renameat2'):
        function = libc.renameat2
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        descriptors = []
        try:
            for path in [Path(source), Path(destination)]:
                fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
                try:
                    for part in path.absolute().parent.parts[1:]:
                        child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                        os.close(fd); fd = child
                    descriptors.append(fd)
                except BaseException:
                    os.close(fd); raise
            function.restype = ctypes.c_int
            if function(descriptors[0], os.fsencode(Path(source).name), descriptors[1],
                        os.fsencode(Path(destination).name), 1) != 0:  # RENAME_NOREPLACE
                number = ctypes.get_errno()
                raise OSError(number, os.strerror(number))
            for fd in descriptors:
                os.fsync(fd)
            return
        finally:
            for fd in descriptors:
                os.close(fd)
    else:
        fail('unsupported_move', '系统不支持原子排他移动，未继续。')
    function.restype = ctypes.c_int
    if function(*arguments) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))
    _sync_directory(Path(source).parent)
    if Path(source).parent != Path(destination).parent:
        _sync_directory(Path(destination).parent)


def _publish(source, destination):
    if _metadata(destination) is not None:
        fail('record_collision', '维护记录目标已存在，未继续。')
    _exclusive_rename(source, destination)


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _metadata(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if info.st_uid != os.getuid() or stat.S_ISLNK(info.st_mode):
        fail('unsafe_path', '目标存在链接或未知所有者，未继续。')
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        fail('unsafe_path', '目标包含特殊文件，未继续。')
    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
        fail('unsafe_path', '目标包含硬链接，未继续。')
    return info


def _parents(home, path):
    try:
        relative = path.relative_to(home)
    except ValueError:
        fail('unsafe_path', '目标不在允许的资料范围内。')
    result, current = [], home
    for part in ('',) + relative.parts[:-1]:
        current = current / part if part else current
        meta = _metadata(current)
        if meta and (not stat.S_ISDIR(meta.st_mode) or meta.st_mode & 0o022):
            fail('unsafe_path', '资料父目录类型异常。')
        result.append(None if meta is None else [meta.st_dev, meta.st_ino, meta.st_uid])
    return result


def _make_directories(home, path):
    _parents(home, path)
    current = home
    for part in path.relative_to(home).parts:
        current /= part
        meta = _metadata(current)
        if meta is None:
            try:
                current.mkdir(mode=0o700)
                _sync_directory(current.parent)
            except FileExistsError:
                pass
            meta = _metadata(current)
        if not meta or not stat.S_ISDIR(meta.st_mode) or meta.st_mode & 0o022:
            fail('unsafe_store', '资料目录类型或权限异常。')


def _private_dir(home, path):
    _make_directories(home, path)
    meta = _metadata(path)
    if not meta or not stat.S_ISDIR(meta.st_mode) or meta.st_mode & 0o077:
        fail('unsafe_store', '维护目录权限异常，需要本人可读写的私有目录。')


def _snapshot(path, digest=False):
    rows = []
    def visit(item, relative):
        meta = _metadata(item)
        if meta is None:
            return False
        kind = 'dir' if stat.S_ISDIR(meta.st_mode) else 'file'
        row = {'path': relative, 'kind': kind, 'uid': meta.st_uid, 'dev': meta.st_dev,
               'ino': meta.st_ino, 'size': meta.st_size, 'mtime': meta.st_mtime_ns,
               'ctime': meta.st_ctime_ns, 'mode': stat.S_IMODE(meta.st_mode)}
        if kind == 'file' and digest:
            if meta.st_size > MAX_JSON:
                fail('too_large', '标识或配置文件超过允许大小，未继续。')
            row['sha256'] = hashlib.sha256(item.read_bytes()).hexdigest()
        rows.append(row)
        if kind == 'dir':
            for child in sorted(item.iterdir(), key=lambda p: p.name):
                if not visit(child, str(Path(relative) / child.name)):
                    fail('changed', '扫描时资料发生变化，请重新预览。')
        after = _metadata(item)
        if after is None or (meta.st_dev, meta.st_ino, meta.st_mtime_ns, meta.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns):
            fail('changed', '扫描时资料发生变化，请重新预览。')
        return True
    return rows if visit(path, '') else None


def _moved_matches(actual, expected):
    # A rename changes the moved root's ctime. Child identities remain checked.
    if actual is None or expected is None or len(actual) != len(expected):
        return actual == expected
    for index, (left, right) in enumerate(zip(actual, expected)):
        left, right = dict(left), dict(right)
        if index == 0:
            left.pop('ctime', None); right.pop('ctime', None)
        if left != right:
            return False
    return True


def _json_object(path):
    meta = _metadata(path)
    if not meta or not stat.S_ISREG(meta.st_mode) or meta.st_size > MAX_JSON:
        fail('invalid_json', '独立CLI标识配置类型或大小异常。')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                fail('invalid_json', '配置含重复字段，未改写。')
            result[key] = value
        return result
    try:
        value = json.loads(path.read_text(), object_pairs_hook=unique,
                           parse_constant=lambda _: fail('invalid_json', '配置含非标准JSON值。'))
    except (UnicodeError, json.JSONDecodeError):
        fail('invalid_json', '独立CLI配置不是有效JSON对象，未改写。')
    if not isinstance(value, dict):
        fail('invalid_json', '独立CLI配置不是有效JSON对象，未改写。')
    return value


def ensure_closed(home, scope, extra_paths=()):
    """Read process identity only; never terminate processes or return argv."""
    commands = subprocess.run(['/bin/ps', '-ww', '-axo', 'uid=,pid=,comm='],
                              capture_output=True, text=True, errors='replace', timeout=5)
    arguments = subprocess.run(['/bin/ps', '-ww', '-axo', 'pid=,args='],
                               capture_output=True, text=True, errors='replace', timeout=5)
    if commands.returncode or arguments.returncode or not commands.stdout.strip():
        fail('process_state', '无法核对客户端进程，未继续。')
    args = {}
    for line in arguments.stdout.splitlines():
        pair = line.strip().split(None, 1)
        if len(pair) == 2 and pair[0].isdigit():
            args[int(pair[0])] = pair[1]
    for line in commands.stdout.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) != 3 or not all(x.isdigit() for x in fields[:2]):
            fail('process_state', '无法核对客户端进程，未继续。')
        uid, pid = map(int, fields[:2]); command = fields[2]
        if uid != os.getuid():
            continue
        argv = args.get(pid, '')
        if scope == 'browser':
            edge = 'Microsoft Edge' in command or 'crashpad_handler' in command
            if edge and pid not in args:
                fail('process_state', '浏览器进程信息发生变化，请稍后重试。')
            busy = edge and any(str(p) in argv for p in [home / PROFILE, *extra_paths])
        elif scope == 'desktop':
            busy = '/Claude.app/' in command or command == 'Claude'
        else:
            if Path(command).name in ['node', 'bun'] and pid not in args:
                fail('process_state', 'CLI进程信息发生变化，请稍后重试。')
            busy = (Path(command).name == 'claude' or '/claude/versions/' in command
                    or (Path(command).name in ['node', 'bun'] and '/claude-code/' in argv))
        if busy:
            fail('running', '请先保存工作并完全退出相关客户端，再重新预览；不会自动结束进程。')


class Maintenance:
    def __init__(self, home):
        self.home = Path(home).absolute()
        self.root = self.home / '.claude-switcher/maintenance'
        home_info = _metadata(self.home)
        if not home_info or not stat.S_ISDIR(home_info.st_mode):
            fail('unsafe_path', '用户目录不可用。')
        _private_dir(self.home, self.root)
        for name in ['plans', 'backups']:
            _private_dir(self.home, self.root / name)
        bootstrap = self.root / 'initialization.lock'
        fd = os.open(bootstrap, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            named, opened = _metadata(bootstrap), os.fstat(fd)
            if not named or named.st_mode & 0o077 or (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino):
                fail('unsafe_store', '维护初始化锁异常。')
            fcntl.flock(fd, fcntl.LOCK_EX)
            key = self.root / 'key'
            if _metadata(key) is None:
                if any(TOKEN.fullmatch(p.name) for p in (self.root / 'backups').iterdir()) or any((self.root / 'plans').glob('*.json')):
                    fail('unsafe_store', '已有维护记录但密钥缺失，未重新生成密钥。')
                with tempfile.NamedTemporaryFile(dir=self.root, prefix='.key-', delete=False) as handle:
                    temporary = Path(handle.name)
                    try:
                        handle.write(secrets.token_bytes(32)); handle.flush(); os.fsync(handle.fileno())
                        temporary.chmod(0o600); _exclusive_rename(temporary, key)
                    finally:
                        temporary.unlink(missing_ok=True)
            meta = _metadata(key)
            if not meta or not stat.S_ISREG(meta.st_mode) or meta.st_mode & 0o077:
                fail('unsafe_store', '维护密钥权限异常。')
            self.key = key.read_bytes()
            if len(self.key) != 32:
                fail('unsafe_store', '维护密钥无效。')
        finally:
            os.close(fd)

    def _write(self, path, value):
        _parents(self.home, path)
        old = _metadata(path)
        if old and (not stat.S_ISREG(old.st_mode) or old.st_mode & 0o077):
            fail('unsafe_store', '维护记录权限异常。')
        body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        envelope = {'data': value, 'mac': hmac.new(self.key, body.encode(), hashlib.sha256).hexdigest()}
        encoded = json.dumps(envelope, ensure_ascii=False).encode()
        if len(encoded) > MAX_RECORD:
            fail('record_too_large', '维护记录超过安全大小上限，未继续。')
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.record-', delete=False) as handle:
            temporary = Path(handle.name)
            try:
                handle.write(encoded)
                handle.flush(); os.fsync(handle.fileno()); temporary.chmod(0o600)
                temporary.replace(path)
                _sync_directory(path.parent)
            finally:
                temporary.unlink(missing_ok=True)

    def _read(self, path):
        _parents(self.home, path)
        meta = _metadata(path)
        if not meta or not stat.S_ISREG(meta.st_mode) or meta.st_mode & 0o077 or meta.st_size > MAX_RECORD:
            fail('invalid_record', '维护记录缺失、权限异常或超限。')
        try:
            envelope = json.loads(path.read_text()); value = envelope['data']
            if not isinstance(value, dict):
                raise ValueError()
            body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
            if not hmac.compare_digest(envelope['mac'], hmac.new(self.key, body.encode(), hashlib.sha256).hexdigest()):
                raise ValueError()
            if value.get('home') != str(self.home) or value.get('owner') != os.getuid():
                raise ValueError()
            return value
        except (ValueError, KeyError, TypeError, UnicodeError):
            fail('invalid_record', '维护记录无法校验，未继续。')

    def _id(self, value):
        if not isinstance(value, str) or not TOKEN.fullmatch(value):
            fail('invalid_id', '无效的维护记录编号。')
        return value

    def _targets(self, mode):
        if mode not in MODES:
            fail('invalid_mode', '不支持的维护范围。')
        if mode == 'cache':
            return [self.home / PROFILE / p for p in CACHE_PATHS]
        if mode == 'browser-reset':
            return [self.home / PROFILE]
        if mode == 'desktop-ids':
            return [self.home / 'Library/Application Support/Claude' / p for p in ['ant-did', 'ant-device-registry.json']]
        return [self.home / NATIVE / p for p in ['.user-id', '.machine-id', '.claude.json']]

    def _target_names(self, mode):
        return [str(path.relative_to(self.home)) for path in self._targets(mode)]

    def _require_target_binding(self, record):
        if (type(record.get('schema_version')) is not int or record['schema_version'] != 1
                or record.get('targets') != self._target_names(record['mode'])):
            fail('incompatible_record', '维护记录与当前资料范围不兼容，未继续；请保留备份供核对。')

    def _scan(self, mode):
        targets = self._targets(mode)
        parents = [_parents(self.home, p) for p in targets]
        trees = [_snapshot(p, mode.endswith('-ids')) for p in targets]
        if mode.endswith('-ids') and any(value and value[0]['kind'] != 'file' for value in trees):
            fail('unsafe_path', '本地标识目标不是普通文件，未继续。')
        active = [i for i, value in enumerate(trees) if value is not None]
        if mode == 'native-ids' and 2 in active and not any(k in _json_object(targets[2]) for k in ID_KEYS):
            active.remove(2)
        result = {'parents': parents, 'trees': trees, 'active': active}
        if mode == 'desktop-ids':
            result['desktop'] = self._desktop_marker()
        if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_SCAN:
            fail('scan_too_large', '资料项目过多，扫描记录超过安全上限；未执行清理。')
        return result

    def _desktop_marker(self):
        path = self.home / '.claude-switcher/current'
        _parents(self.home, path)
        tree = _snapshot(path, True)
        if tree is None:
            return {'slot': '未初始化', 'tree': None}
        if tree[0]['kind'] != 'file' or tree[0]['size'] > 16:
            fail('invalid_slot', '当前档案标记类型异常，未处理桌面标识。')
        try:
            value = path.read_text().strip()
        except UnicodeError:
            fail('invalid_slot', '当前档案标记无效，未处理桌面标识。')
        if value not in ['A', 'B'] or _snapshot(path, True) != tree:
            fail('invalid_slot', '当前档案标记无效或发生变化，未处理桌面标识。')
        return {'slot': value, 'tree': tree}

    def _check_slot(self, record):
        if record['mode'] == 'desktop-ids' and self._desktop_marker()['slot'] != record.get('desktop_slot'):
            fail('different_slot', '备份所属桌面档案与当前档案不同，未恢复本地标识。',
                 record.get('state') in ['applying', 'recovery_required'])

    def _label(self, mode, slot=None):
        return MODES[mode][1] + (' · 档案' + slot if slot and slot != '未初始化' else ' · 未初始化' if slot else '')

    def _backup(self, ident, validate_targets=True):
        ident = self._id(ident)
        folder = self.root / 'backups' / ident
        _parents(self.home, folder / 'record.json')
        data = self._read(folder / 'record.json')
        if (data.get('backup_id') != ident or data.get('mode') not in MODES
                or data.get('state') not in ['applying', 'recovery_required', 'completed', 'rolled_back', 'consumed']):
            fail('invalid_record', '备份记录无效。')
        if validate_targets:
            self._require_target_binding(data)
        return folder, data

    def _pending(self, scope):
        for folder in (self.root / 'backups').iterdir():
            if TOKEN.fullmatch(folder.name):
                _, data = self._backup(folder.name, validate_targets=False)
                if MODES[data['mode']][0] == scope and data.get('state') in ['applying', 'recovery_required']:
                    self._require_target_binding(data)
                    return True
        return False

    @contextmanager
    def _lock(self, scope, allow_pending=False, shared=False):
        if scope not in ['browser', 'desktop', 'native']:
            fail('invalid_scope', '无效的维护范围。')
        if shared and scope != 'native':
            fail('invalid_scope', '此范围不接受共享启动锁。')
        path = self.root / (scope + '.lock')
        meta = _metadata(path)
        if meta and (not stat.S_ISREG(meta.st_mode) or meta.st_mode & 0o077):
            fail('unsafe_store', '维护锁权限异常。')
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            actual = os.fstat(fd); named = _metadata(path)
            if named is None or named.st_mode & 0o077 or (actual.st_dev, actual.st_ino) != (named.st_dev, named.st_ino):
                fail('unsafe_store', '维护锁发生变化。')
            try:
                fcntl.flock(fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
            except BlockingIOError:
                fail('busy', '该范围正在操作，请稍后重试。')
            if not allow_pending and self._pending(scope):
                fail('recovery_required', '存在未完成维护，请先从备份记录恢复。', True)
            yield fd
        finally:
            os.close(fd)

    def _plan(self, mode, operation, scan, backup_id=None, backup_snapshot=None):
        targets = self._targets(mode)
        active = scan['active'] if operation == 'clean' else list(range(len(targets)))
        prior = [None] * len(targets)
        if operation == 'restore':
            prior = backup_snapshot
            active = [i for i in active if scan['trees'][i] is not None or prior[i] is not None]
        if operation == 'recover':
            _, record = self._backup(backup_id)
            active = sorted({int(label.split(':')[1]) for step in record.get('steps', [])
                             for label in [step['from'], step['to']] if label.startswith('live:')})
        def describe(index):
            if operation == 'recover':
                return '回滚未完成步骤；冲突时保留现场'
            if operation == 'restore':
                if mode == 'native-ids' and index == 2:
                    return '仅恢复本地ID字段；保留当前其他配置'
                if prior[index] is None:
                    return '将当前新增资料移入新备份，恢复原先不存在状态'
                return '备份当前同名项目（如有），再恢复备份'
            return '重建资料' if mode == 'browser-reset' else '窄改本地ID字段' if mode == 'native-ids' and index == 2 else '移动至私有备份'
        items = [{'path': str(targets[i].relative_to(self.home)),
                  'bytes': sum(r['size'] for tree in [scan['trees'][i], prior[i]]
                               for r in tree or [] if r['kind'] == 'file'),
                  'operation': describe(i)}
                 for i in active]
        if operation != 'clean' and not items:
            items = [{'path': '.claude-switcher/maintenance', 'bytes': 0, 'operation': '恢复未完成事务记录'}]
        token = secrets.token_hex(16) if items else ''
        expiry = time.time() + TTL
        plan = {'schema_version': 1, 'targets': self._target_names(mode),
                'home': str(self.home), 'owner': os.getuid(), 'token': token, 'mode': mode,
                'operation': operation, 'scan': scan, 'expires_at': expiry, 'used': False,
                'backup_id': backup_id, 'backup_snapshot': backup_snapshot}
        if token:
            self._write(self.root / 'plans' / (token + '.json'), plan)
        impact = (MODES[mode][2] if operation == 'clean' else
                  '回滚未完成操作；冲突时停止并保留现场，不创建新的备份。' if operation == 'recover' else
                  '恢复前保存当前同范围资料（如有）；不会覆盖未预览的新变化。')
        return {'schema_version': 1, 'ok': True, 'token': token, 'mode': mode, 'operation': operation,
                'scope': self._label(mode, scan.get('desktop', {}).get('slot')), 'items': items, 'item_count': len(items),
                'total_bytes': sum(i['bytes'] for i in items), 'impact': impact,
                'expires_at': expiry, 'can_apply': bool(token)}

    def preview(self, mode):
        self._targets(mode)
        with self._lock(MODES[mode][0]):
            ensure_closed(self.home, MODES[mode][0])
            return self._plan(mode, 'clean', self._scan(mode))

    def _payload_snapshot(self, folder, mode):
        return [_snapshot(folder / 'before' / str(i), mode.endswith('-ids'))
                for i in range(len(self._targets(mode)))]

    def preview_restore(self, backup_id):
        folder, record = self._backup(backup_id); mode = record['mode']
        with self._lock(MODES[mode][0]):
            ensure_closed(self.home, MODES[mode][0], [folder])
            self._check_slot(record)
            if record.get('state') != 'completed':
                fail('invalid_backup', '此记录当前不能作为普通备份恢复。')
            payload = self._payload_snapshot(folder, mode)
            if payload != record.get('before'):
                fail('backup_changed', '备份资料发生变化，未继续。')
            return self._plan(mode, 'restore', self._scan(mode), backup_id, payload)

    def preview_recover(self, backup_id):
        folder, record = self._backup(backup_id); mode = record['mode']
        with self._lock(MODES[mode][0], allow_pending=True):
            ensure_closed(self.home, MODES[mode][0], [folder])
            self._check_slot(record)
            if record.get('state') not in ['applying', 'recovery_required']:
                fail('invalid_backup', '此记录没有待恢复事务。')
            self._rollback_check(folder, record)
            return self._plan(mode, 'recover', self._scan(mode), backup_id,
                              hashlib.sha256((folder / 'record.json').read_bytes()).hexdigest())

    def backups(self):
        result = []
        for folder in (self.root / 'backups').iterdir():
            if not TOKEN.fullmatch(folder.name):
                continue
            _, record = self._backup(folder.name)
            state = record.get('state')
            if state in ['applying', 'recovery_required', 'completed']:
                result.append({'backup_id': folder.name, 'mode': record['mode'],
                               'created_at': record['created_at'], 'label': self._label(record['mode'], record.get('desktop_slot')),
                               'state': 'completed' if state == 'completed' else 'recovery_required'})
        return {'schema_version': 1, 'ok': True,
                'backups': sorted(result, key=lambda r: r['created_at'], reverse=True)}

    def _location(self, folder, record, location):
        kind, number = location.split(':'); index = int(number)
        targets = self._targets(record['mode'])
        if not 0 <= index < len(targets):
            fail('invalid_record', '事务记录范围无效。')
        if kind == 'live':
            return targets[index]
        if kind in ['before', 'new']:
            return folder / kind / str(index)
        if kind == 'restore':
            return self.root / 'backups' / self._id(record['restore_id']) / 'before' / str(index)
        fail('invalid_record', '事务记录范围无效。')

    def _prepare_parent(self, path):
        _make_directories(self.home, path.parent)
        _parents(self.home, path)

    def _move_step(self, folder, record, step):
        mode = record['mode']; source = self._location(folder, record, step['from']); dest = self._location(folder, record, step['to'])
        ensure_closed(self.home, MODES[mode][0], [folder])
        if mode == 'desktop-ids' and self._desktop_marker() != record['desktop_marker']:
            fail('changed', '当前桌面档案标记发生变化，已停止。')
        _parents(self.home, source)
        for label in (step['from'], step['to']):
            if label.startswith('live:'):
                index = int(label.split(':')[1]); live = self._targets(mode)[index]
                if _parents(self.home, live) != record['live_parents'][index]:
                    fail('changed', '资料父目录发生变化，未继续。')
        self._prepare_parent(dest)
        if step['to'].startswith('live:'):
            index = int(step['to'].split(':')[1])
            record['live_parents'][index] = _parents(self.home, dest)
            self._write(folder / 'record.json', record)
        if _snapshot(source, mode.endswith('-ids')) != step['tree'] or _metadata(dest) is not None:
            fail('changed', '操作期间目标发生变化，已停止。')
        if source.lstat().st_dev != dest.parent.stat().st_dev:
            fail('different_volume', '原资料与备份不在同一卷，未继续。')
        _rename(source, dest)

    def _rollback_check(self, folder, record):
        # Simulate the inverse in memory first; never start recovery with an ambiguous path.
        self._check_slot(record)
        states = {}
        def get(label):
            if label not in states:
                path = self._location(folder, record, label)
                parents = _parents(self.home, path)
                if label.startswith('live:') and parents != record['live_parents'][int(label.split(':')[1])]:
                    fail('recovery_conflict', '资料父目录已变化，恢复暂停。', True)
                states[label] = _snapshot(path, record['mode'].endswith('-ids'))
            return states[label]
        actions = []
        for step in reversed(record.get('steps', [])):
            source, dest, expected = get(step['from']), get(step['to']), step['tree']
            if source is None and _moved_matches(dest, expected):
                actions.append(step); states[step['from']] = dest; states[step['to']] = None
            elif dest is None and _moved_matches(source, expected):
                continue
            else:
                fail('recovery_conflict', '恢复位置有新资料或备份发生变化，已保留双方，请人工核对。', True)
        return actions

    def _rollback(self, folder, record):
        self._rollback_check(folder, record)
        # A final-commit write may have failed after the in-memory state changed.
        # Every reverse-move checkpoint must remain pending until all recovery ends.
        record['state'] = 'recovery_required'
        self._write(folder / 'record.json', record)
        while record['steps']:
            step = record['steps'][-1]
            ensure_closed(self.home, MODES[record['mode']][0], [folder])
            self._check_slot(record)
            source = self._location(folder, record, step['to']); dest = self._location(folder, record, step['from'])
            original = _snapshot(dest, record['mode'].endswith('-ids'))
            moved = _snapshot(source, record['mode'].endswith('-ids'))
            if original is None and _moved_matches(moved, step['tree']):
                self._prepare_parent(dest); _rename(source, dest)
            elif moved is None and _moved_matches(original, step['tree']):
                pass  # The forward move did not run, or recovery stopped before recording this inverse.
            else:
                fail('recovery_conflict', '恢复时资料发生变化，备份已保留。', True)
            record['steps'].pop()
            self._write(folder / 'record.json', record)
        if record.get('restore_id'):
            old_folder, old_record = self._backup(record['restore_id'])
            old_record['before'] = self._payload_snapshot(old_folder, record['mode'])
            old_record['state'] = 'completed'
            self._write(old_folder / 'record.json', old_record)
        record['state'] = 'rolled_back'; self._write(folder / 'record.json', record)

    def _stage_json(self, path, value):
        with path.open('xb') as handle:
            handle.write((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode())
            handle.flush(); os.fsync(handle.fileno())
        path.chmod(0o600)

    def _fresh_profile(self, path):
        helper = Path(__file__).with_name('protected-access.py')
        if helper.is_symlink() or not helper.is_file():
            fail('missing_helper', '缺少专用浏览器配套模块。')
        spec = importlib.util.spec_from_file_location('maintenance_protected_preferences', helper)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        module.seed_profile(path); module.profile_baseline(path)

    def apply(self, token):
        token = self._id(token); plan_path = self.root / 'plans' / (token + '.json'); plan = self._read(plan_path)
        mode = plan.get('mode'); self._targets(mode); operation = plan.get('operation')
        self._require_target_binding(plan)
        if operation not in ['clean', 'restore', 'recover']:
            fail('invalid_record', '维护方案无效。')
        with self._lock(MODES[mode][0], allow_pending=operation == 'recover'):
            plan = self._read(plan_path)
            if plan.get('used') or plan.get('token') != token:
                fail('used_token', '该方案已执行或失效，请重新预览。')
            if not isinstance(plan.get('expires_at'), (int, float)) or time.time() > plan['expires_at']:
                fail('expired', '预览已过期，请重新扫描。')
            ensure_closed(self.home, MODES[mode][0])
            if self._scan(mode) != plan.get('scan'):
                fail('changed', '预览后资料发生变化，请重新扫描。')
            old_folder = old_record = None
            if operation in ['restore', 'recover']:
                old_folder, old_record = self._backup(plan['backup_id'])
                if old_record['mode'] != mode:
                    fail('invalid_record', '备份范围不一致。')
                self._check_slot(old_record)
                ensure_closed(self.home, MODES[mode][0], [old_folder])
                if operation == 'recover':
                    if old_record.get('state') not in ['applying', 'recovery_required'] or hashlib.sha256((old_folder / 'record.json').read_bytes()).hexdigest() != plan['backup_snapshot']:
                        fail('changed', '恢复事务已变化，请重新预览。', True)
                    self._rollback_check(old_folder, old_record)
                elif old_record.get('state') != 'completed' or self._payload_snapshot(old_folder, mode) != old_record.get('before') or old_record.get('before') != plan['backup_snapshot']:
                    fail('backup_changed', '备份发生变化，请重新核对。')
            plan['used'] = True; self._write(plan_path, plan)
            if operation == 'recover':
                try:
                    self._rollback(old_folder, old_record)
                except (OSError, MaintenanceError):
                    old_record['state'] = 'recovery_required'; self._write(old_folder / 'record.json', old_record)
                    fail('recovery_required', '恢复未完成，原资料与恢复现场保留。', True)
                return {'schema_version': 1, 'ok': True, 'mode': mode, 'operation': operation,
                        'backup_id': plan['backup_id'], 'message': '未完成操作已回滚。', 'recovery_required': False}

            ident = secrets.token_hex(16); folder = self.root / 'backups' / ident
            initial = self.root / 'backups' / ('.init-' + ident)
            _private_dir(self.home, initial)
            for name in ['before', 'new']:
                _private_dir(self.home, initial / name)
            record = {'schema_version': 1, 'targets': self._target_names(mode),
                      'home': str(self.home), 'owner': os.getuid(), 'backup_id': ident,
                      'mode': mode, 'operation': operation, 'created_at': time.time(),
                      'state': 'applying', 'restore_id': plan.get('backup_id'), 'steps': [],
                      'live_parents': plan['scan']['parents'],
                      'desktop_slot': plan['scan'].get('desktop', {}).get('slot'),
                      'desktop_marker': plan['scan'].get('desktop')}
            self._write(initial / 'record.json', record)
            _publish(initial, folder)
            try:
                targets = self._targets(mode); desired = {}
                active = plan['scan']['active'] if operation == 'clean' else list(range(len(targets)))
                if operation == 'clean' and mode == 'browser-reset':
                    self._fresh_profile(folder / 'new/0'); desired[0] = 'new:0'
                if mode == 'native-ids' and (2 in active or operation == 'restore'):
                    current = _json_object(targets[2]) if targets[2].exists() else {}
                    if operation == 'restore':
                        prior = _json_object(old_folder / 'before/2') if (old_folder / 'before/2').exists() else {}
                    else:
                        prior = {}
                    for key in ID_KEYS:
                        current.pop(key, None)
                        if key in prior:
                            current[key] = prior[key]
                    if targets[2].exists() or any(k in current for k in ID_KEYS):
                        self._stage_json(folder / 'new/2', current); desired[2] = 'new:2'
                if operation == 'restore':
                    for i, value in enumerate(old_record['before']):
                        if value is not None and not (mode == 'native-ids' and i == 2):
                            desired[i] = 'restore:' + str(i)
                desired_trees = {i: (old_record['before'][i] if label.startswith('restore:')
                                    else _snapshot(self._location(folder, record, label), mode.endswith('-ids')))
                                 for i, label in desired.items()}
                # Persist each move intent before making it; an interrupted pending move
                # can be identified from its inode and complete tree snapshot.
                if self._scan(mode) != plan['scan']:
                    fail('changed', '操作前资料发生变化，未继续。')
                for i in active:
                    source = targets[i]
                    if _snapshot(source, mode.endswith('-ids')) != plan['scan']['trees'][i]:
                        fail('changed', '执行期间资料发生变化，已停止。')
                    if plan['scan']['trees'][i] is not None:
                        step = {'from': 'live:' + str(i), 'to': 'before:' + str(i),
                                'tree': plan['scan']['trees'][i]}
                        record['steps'].append(step); self._write(folder / 'record.json', record)
                        self._move_step(folder, record, step)
                    if i in desired:
                        source = self._location(folder, record, desired[i])
                        step = {'from': desired[i], 'to': 'live:' + str(i),
                                'tree': desired_trees[i]}
                        record['steps'].append(step); self._write(folder / 'record.json', record)
                        self._move_step(folder, record, step)
                after = self._scan(mode)
                expected_after = list(plan['scan']['trees'])
                for i in active:
                    expected_after[i] = desired_trees.get(i)
                if any(not _moved_matches(actual, expected) for actual, expected in zip(after['trees'], expected_after)):
                    fail('changed', '提交前资料发生变化，已停止。')
                if after['parents'] != record['live_parents'] or after.get('desktop') != plan['scan'].get('desktop'):
                    fail('changed', '提交前资料目录或档案标记发生变化，已停止。')
                record['before'] = self._payload_snapshot(folder, mode)
                if old_record is not None:
                    old_record['state'] = 'consumed'; self._write(old_folder / 'record.json', old_record)
                record['state'] = 'completed'; self._write(folder / 'record.json', record)
                return {'schema_version': 1, 'ok': True, 'mode': mode, 'operation': operation,
                        'backup_id': ident, 'message': '操作完成，原资料已保存为私有备份。', 'recovery_required': False}
            except (OSError, ValueError, TypeError, ImportError, subprocess.SubprocessError) as original_error:
                try:
                    self._rollback(folder, record)
                except (OSError, ValueError, TypeError, subprocess.SubprocessError):
                    record['state'] = 'recovery_required'; self._write(folder / 'record.json', record)
                    fail('recovery_required', '操作未完成，备份与现场已保留，请先恢复未完成操作。', True)
                if isinstance(original_error, MaintenanceError):
                    raise original_error
                fail('operation_failed', '操作未完成，已恢复原资料；请重新预览。')


@contextmanager
def entry_lock(home, scope, shared=False):
    with Maintenance(home)._lock(scope, shared=shared) as fd:
        yield fd


def verify_lock(home, scope, descriptor):
    if scope != 'desktop' or not re.fullmatch(r'[0-9]{1,6}', descriptor or '') or int(descriptor) < 3:
        fail('invalid_lock', '账号操作缺少有效维护锁。')
    manager = Maintenance(home); fd = int(descriptor)
    try:
        opened, named = os.fstat(fd), _metadata(manager.root / (scope + '.lock'))
        if not named or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            raise ValueError()
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, ValueError):
        fail('invalid_lock', '账号操作缺少有效维护锁。')
    if manager._pending(scope):
        fail('recovery_required', '存在未完成维护，请先恢复。', True)


def guard_switch(home, target):
    if target not in ['A', 'B']:
        fail('invalid_target', '账号只能为A或B。')
    core = Path(__file__).with_name('claude-switch.sh')
    if not core.is_file():
        core = Path(home) / '.local/bin/claude-switch.sh'
    if core.is_symlink() or not core.is_file():
        fail('missing_core', '找不到账号切换核心。')
    with entry_lock(home, 'desktop') as fd:
        return subprocess.run(['/bin/bash', str(core), '_maintenance-switch', target],
                              env=dict(os.environ, CLAUDE_SWITCHER_MAINTENANCE_FD=str(fd)),
                              pass_fds=(fd,)).returncode


def main(argv=None):
    class Parser(argparse.ArgumentParser):
        def error(self, message):
            fail('invalid_arguments', '维护命令参数不正确。')
    parser = Parser(description=__doc__)
    parser.add_argument('action', choices=['preview', 'preview-restore', 'preview-recover', 'apply', 'backups', 'guard-switch', 'verify-lock'])
    parser.add_argument('arguments', nargs='*')
    args = None
    try:
        args = parser.parse_args(argv)
        expected = 0 if args.action == 'backups' else 2 if args.action == 'verify-lock' else 1
        if len(args.arguments) != expected:
            fail('invalid_arguments', '维护命令参数不正确。')
        home = Path.home()
        if getattr(args, 'action', None) == 'guard-switch':
            return guard_switch(home, args.arguments[0])
        if args.action == 'verify-lock':
            verify_lock(home, *args.arguments)
            result = {'schema_version': 1, 'ok': True}
        else:
            manager = Maintenance(home)
            method = getattr(manager, args.action.replace('-', '_'))
            result = method(*args.arguments)
        print(json.dumps(result, ensure_ascii=False)); return 0
    except (MaintenanceError, OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        if not isinstance(error, MaintenanceError):
            error = MaintenanceError('io_error', '读取或写入维护资料失败，未宣称操作成功。')
        if getattr(args, 'action', None) == 'guard-switch':
            print('FAIL:' + error.message)
        else:
            print(json.dumps({'schema_version': 1, 'ok': False, 'code': error.code,
                              'message': error.message, 'recovery_required': error.recovery_required}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
