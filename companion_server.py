"""Upgraded local console on 8081. Frozen 8080 is deliberately untouched."""
import json
import os
import logging
import re
import secrets
import subprocess
from core.subprocess_options import hidden_console
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import dashboard_server as d
from core.solomon_bridge import SolomonBridge
from core.staffing import TeamConflict

ROOT = Path(__file__).resolve().parent
# Fixed allowlist of console files and bundled artwork; request paths never become filesystem paths.
STATIC_FILES = {'/cozy-office.js':'cozy-office.js','/cozy-office.css':'cozy-office.css','/updates':'updates.html','/updates.js':'updates.js','/updates.css':'updates.css','/development-rules.js':'development-rules.js','/setup':'setup.html','/setup.js':'setup.js','/setup.css':'setup.css','/vendor/pixi/csp-support.js':'vendor/pixi/csp-support.js','/office-gpu.js':'office-gpu.js','/vendor/pixi/pixi.min.js':'vendor/pixi/pixi.min.js','/employee-tools.js':'employee-tools.js','/web-tools.js':'web-tools.js','/web-workspace':'web-workspace.html','/web-workspace.js':'web-workspace.js','/web-workspace.css':'web-workspace.css','/furniture-art.js':'furniture-art.js','/furniture-desk-hd.png':'../assets/furniture-desk-hd.png','/furniture-table-hd.png':'../assets/furniture-table-hd.png','/furniture-chair-hd.png':'../assets/furniture-chair-hd.png','/furniture-partition-hd.png':'../assets/furniture-partition-hd.png','/furniture-plant-hd.png':'../assets/furniture-plant-hd.png','/crew-portraits-cozy-hd.png':'../assets/crew-portraits-cozy-hd.png','/crew-portraits-hd.png':'../assets/crew-portraits-hd.png','/game-style.js':'game-style.js','/game-style.css':'game-style.css','/crew-illustrated.png':'../assets/crew-illustrated.png','/office-corporate-hd.png':'../assets/office-corporate-hd.png','/office-creative-hd.png':'../assets/office-creative-hd.png','/office-garden-hd.png':'../assets/office-garden-hd.png','/automation':'automation.html','/automation.js':'automation.js','/automation.css':'automation.css','/office-decor.js':'office-decor.js','/office-view.js':'office-view.js','/office-decor.css':'office-decor.css','/operations.css':'operations.css','/operations':'operations.html','/operations.js':'operations.js','/hermes.js':'hermes.js','/settings':'settings.html','/settings.js':'settings.js','/executive.js':'executive.js','/crew-portraits.png':'../assets/crew-portraits.png','/character-art.js':'character-art.js','/pixel-theme.css':'pixel-theme.css','/remote.css':'remote.css','/devices':'devices.html','/devices.js':'devices.js','/devices.css':'devices.css','/meetings.js': 'meetings.js', '/company.js': 'company.js', '/team-editor.js': 'team-editor.js', '/office': 'office.html', '/office.js': 'office.js', '/office.css': 'office.css', '/': 'index.html', '/console.js': 'console.js', '/console.css': 'console.css',
                '/stage.css': 'stage.css', '/trinity.js': 'trinity.js', '/stage.js': 'stage.js',
                '/missions': 'missions.html', '/missions.css': 'missions.css', '/missions.js': 'missions.js'}


_PICK_LOCK = threading.Lock()


def pick_folder(initial: str = "", timeout: int = 300) -> dict:
    """Open the native folder dialog on this PC's desktop and return {'path': str} ('' when cancelled). One at a time."""
    if not _PICK_LOCK.acquire(blocking=False):
        return {"error": "폴더 선택 창이 이미 열려 있습니다."}
    try:
        out = subprocess.run([sys.executable, str(ROOT / "scripts" / "pick_folder.py"), initial or ""],
                             capture_output=True, timeout=timeout, **hidden_console())
        if out.returncode != 0:
            return {"error": "폴더 선택 창을 열지 못했습니다."}
        return {"path": str(json.loads(out.stdout.decode("ascii") or "{}").get("path", ""))}
    except subprocess.TimeoutExpired:
        return {"error": "폴더 선택 시간이 초과됐습니다."}
    except (OSError, ValueError):
        return {"error": "폴더 선택 창을 열지 못했습니다."}
    finally:
        _PICK_LOCK.release()


def solomon_target_ok(path: str) -> tuple:
    """Solomon may commission work on any git project under config solomon.allowed_roots, except the denied ones
    (the Director itself, Solomon itself, the shared vault). Returns (ok, resolved_or_reason)."""
    cfg = (d.load_config().get('solomon') or {})
    try:
        target = Path(path).resolve()
    except (OSError, ValueError):
        return False, '경로를 해석할 수 없습니다'
    roots = [Path(r).resolve() for r in (cfg.get('allowed_roots') or [])]
    denied = [Path(x).resolve() for x in (cfg.get('denied') or [])] + [ROOT.resolve()]
    if not any(target == r or r in target.parents for r in roots):
        return False, '솔로몬에 허용된 폴더 밖입니다'
    if any(target == x or x in target.parents for x in denied):
        return False, '이 폴더는 솔로몬이 지시할 수 없습니다'
    return True, str(target)


def project_registry() -> list:
    """Projects Solomon can target: config `projects:` entries, every project a mission ever ran on, and git folders
    one level under the allowed roots. Each entry carries the latest mission and whether a deliverable awaits."""
    from core.mission import MissionStore
    cfg = d.load_config()
    seen = {}

    def add(path, origin):
        ok, resolved = solomon_target_ok(path)
        if not ok or not Path(resolved).is_dir():
            return
        key = resolved.casefold()
        entry = seen.setdefault(key, {'path': resolved, 'name': Path(resolved).name, 'origins': [], 'git': (Path(resolved) / '.git').exists(),
                                      'missions': 0, 'last_mission': None})
        if origin not in entry['origins']:
            entry['origins'].append(origin)
    for key in (cfg.get('projects') or {}):
        add(key, 'config')
    for root in (cfg.get('solomon') or {}).get('allowed_roots') or []:
        try:
            for child in sorted(Path(root).iterdir()):
                if child.is_dir() and (child / '.git').exists():
                    add(child, 'root')
        except OSError:
            pass
    missions = sorted(MissionStore().all(), key=lambda m: m.get('updated_at', ''))
    for m in missions:
        add(m.get('project_path', ''), 'mission')
        ok, resolved = solomon_target_ok(m.get('project_path', ''))
        if ok and resolved.casefold() in seen:
            e = seen[resolved.casefold()]
            e['missions'] += 1
            e['last_mission'] = {'mission_id': m['mission_id'], 'status': m.get('status'), 'goal': (m.get('goal') or '')[:160],
                                 'updated_at': m.get('updated_at'), 'applied': (m.get('applied') or {}).get('status')}
    return sorted(seen.values(), key=lambda e: (e['last_mission'] is None, -(e['missions']), e['name']))


class CompanionHandler(d.DashboardHandler):
    def do_GET(self):
        if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0]:
            return self._send_json({'error': 'local requests only'}, 403)
        path = urlsplit(self.path).path
        try:                                    # a GET that carries a body: read it, or closing the socket with unread
            unread = int(self.headers.get('Content-Length') or 0)       # data resets the connection mid-response
        except ValueError:
            unread = 0
        if 0 < unread <= 65536:
            self.rfile.read(unread)
        if path=='/ops/updates':
            from core.app_updates import public
            return self._send_json(public())
        if path=='/ops/development-rules':
            try:
                from core import development_rules as rules, web_workspace as web
                project=web.project(parse_qs(urlsplit(self.path).query).get('project_path',[''])[0])
                return self._send_json(rules.public(project))
            except (ValueError,OSError) as exc:return self._send_json({'error':str(exc)},400)
        if path=='/ops/setup':
            from core.setup_assistant import public
            return self._send_json(public())
        if path.startswith('/vendor/monaco/'):
            from mimetypes import guess_type
            from urllib.parse import unquote
            relative=unquote(path[len('/vendor/monaco/'):])
            base=ROOT/'console/vendor/monaco'
            target=base/relative
            if '..' in Path(relative).parts or target.is_symlink() or not target.resolve().is_relative_to(base.resolve()) or not target.is_file() or target.suffix not in {'.js','.css','.ttf','.json'}:
                return self._send_json({'error':'asset not found'},404)
            body=target.read_bytes();self.send_response(200);self.send_header('Content-Type',guess_type(target.name)[0] or 'application/octet-stream');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','private, max-age=86400');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body);return
        if path in ('/ops/web-workspace','/ops/web-artifact','/ops/employee-tools'):
            try:
                from core import web_workspace as web, employee_tools
                if path=='/ops/employee-tools':return self._send_json(employee_tools.public())
                query=parse_qs(urlsplit(self.path).query);project=web.project(query.get('project_path',[''])[0])
                if path=='/ops/web-workspace':
                    result={'server':web.server_status(project),'reports':web.reports(project)} if query.get('light')==['1'] else web.listing(project)
                    return self._send_json(result)
                import re
                ident=query.get('id',[''])[0];asset=query.get('asset',[''])[0]
                if not re.fullmatch('AUD-[a-f0-9]{20}',ident) or asset not in {'desktop.png','tablet.png','mobile.png'}:raise ValueError('보고서 이미지 경로를 확인하세요.')
                file=web.folder(project)/'reports'/ident/asset
                if not file.is_file():return self._send_json({'error':'보고서 이미지가 없습니다.'},404)
                body=file.read_bytes();self.send_response(200);self.send_header('Content-Type','image/png');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body);return
            except (ValueError,OSError) as exc:return self._send_json({'error':str(exc)},400)
        if path in ('/ops/automation','/ops/youtube'):
            try:
                from core import scheduled_work, youtube_channel
                return self._send_json(scheduled_work.listing() if path=='/ops/automation' else youtube_channel.public())
            except (ValueError,OSError) as exc:return self._send_json({'error':str(exc)},400)
        if path == '/ops/office-layout':
            from core.office_layout import public
            return self._send_json(public())
        if path in ('/ops/backup','/ops/knowledge','/ops/secretary'):
            try:
                from core import company_backup, company_knowledge, secretary_desk
                if path == '/ops/backup': result=company_backup.status()
                elif path == '/ops/knowledge': result=company_knowledge.listing()
                else: result=secretary_desk.summary()
                return self._send_json(result)
            except (ValueError,OSError) as exc: return self._send_json({'error':str(exc)},400)
        if path in ('/ops/devices','/ops/devices/qr'):
            from core.device_link import manager
            link=manager(self.server,ROOT)
            if path.endswith('/qr'):
                if not link.server:return self._send_json({'error':'기기 연결을 먼저 켜세요.'},400)
                import qrcode, qrcode.image.svg
                import io
                out=io.BytesIO();qrcode.make(link.origin+'/pair',image_factory=qrcode.image.svg.SvgPathImage).save(out)
                body=out.getvalue();self.send_response(200);self.send_header('Content-Type','image/svg+xml');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
            return self._send_json(link.status())
        if path == '/ops/roles':
            from core.role_settings import current
            return self._send_json({'roles': current(d.load_config()), 'csrf': self.server.bridge_token})
        if path == '/ops/projects':
            return self._send_json(d.build_project_choices())
        if path == '/ops/desktop-health':
            from desktop_launcher import APP_ID, PROTOCOL, installation_id
            from core.app_updates import current_version
            return self._send_json({'version':current_version(),'app': APP_ID, 'protocol': PROTOCOL, 'installation_id': installation_id(ROOT), 'ui': '/missions'})
        if path == '/ops/meetings':
            from core import company_meetings
            try:
                query=parse_qs(urlsplit(self.path).query)
                ident=query.get('id',[''])[0][:80]
                result=company_meetings.report(ident) if ident else (company_meetings.compact_listing(query.get('revision',[''])[0][:80]) if query.get('compact')==['1'] else company_meetings.listing())
                return self._send_json(result or {'error':'회의 보고서를 찾을 수 없습니다.'},200 if result else 404)
            except (OSError,ValueError) as exc:
                return self._send_json({'error':str(exc)},500)
        if path in ('/ops/hermes/settings','/ops/hermes/tasks'):
            from core import hermes_agent
            try:
                query=parse_qs(urlsplit(self.path).query)
                return self._send_json(hermes_agent.public() if path.endswith('/settings') else hermes_agent.listing(query.get('revision',[''])[0][:80]))
            except (OSError,ValueError): return self._send_json({'error':'Hermes 설정·보고함을 읽지 못했습니다.'},500)
        if path in ('/ops/ai-connections','/ops/skill-library'):
            from core import ai_connections, skill_library
            return self._send_json(ai_connections.public() if path.endswith('ai-connections') else skill_library.current())
        if path == '/ops/office':
            from core.office_maps import snapshot
            return self._send_json(snapshot(d, parse_qs(urlsplit(self.path).query)))
        if path == '/ops/briefings':
            from core.executive_briefing import listing, compact_listing
            query=parse_qs(urlsplit(self.path).query)
            return self._send_json(compact_listing(query.get('revision',[''])[0][:80]) if query.get('compact')==['1'] else listing())
        if path == '/ops/company':
            from core import company
            try:
                return self._send_json(company.current())
            except (OSError, ValueError) as exc:
                return self._send_json({'error': '회사 설정을 읽지 못했습니다: ' + str(exc)}, 500)
        if path == '/ops/team':
            from core import staffing
            try:
                return self._send_json({'team': staffing.current(), 'default_team': staffing.default_team(),
                    'slots': staffing.SLOTS, 'specialties': staffing.SPECIALTIES, 'max_members': staffing.MAX_MEMBERS, 'departments': staffing.DEPARTMENTS, 'positions': staffing.POSITIONS, 'department_limit': staffing.DEPARTMENT_LIMIT})
            except (OSError, ValueError) as exc:
                return self._send_json({'error': '팀 설정을 읽지 못했습니다: ' + str(exc)}, 500)
        if path == '/ops/workflows':
            from core.workflows import catalog
            return self._send_json({'workflows': catalog(), 'mode': 'director-native-guidance'})
        if path == '/ops/project-memory':
            from core.project_context import collect_project_context
            from core.workflows import project_history
            raw = parse_qs(urlsplit(self.path).query).get('path', [''])[0]
            ok, resolved = d.validate_project_path(raw) if len(raw) <= 4096 else (False, '경로가 너무 깁니다')
            if not ok:
                return self._send_json({'error': resolved}, 400)
            return self._send_json({'project_path': resolved, 'history': project_history(resolved),
                                    'discovery': collect_project_context(resolved)['project_discovery']})
        if path == '/ops/mission-launch':
            from core.mission_launch import LaunchStore
            ident = parse_qs(urlsplit(self.path).query).get('request_id', [''])[0][:80]
            receipt = LaunchStore().get(ident)
            return self._send_json(receipt or {'error': '요청 기록이 없습니다'}, 200 if receipt else 404)
        if path == '/ops/mission-step':
            q = parse_qs(urlsplit(self.path).query)
            try:
                result = d.build_mission_step_payload(q.get('mission_id', [''])[0][:80], int(q.get('index', ['0'])[0]))
                return self._send_json(result or {'error': '단계 기록이 없습니다'}, 200 if result else 404)
            except (ValueError, TypeError):
                return self._send_json({'error': '단계 번호가 올바르지 않습니다'}, 400)
        if path in STATIC_FILES:
            name = STATIC_FILES[path]
            body = (ROOT / 'console' / name).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', {'html': 'text/html; charset=utf-8', 'js': 'text/javascript; charset=utf-8', 'css': 'text/css; charset=utf-8', 'png':'image/png'}[name.rsplit('.', 1)[1]])
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'private, max-age=86400' if name.endswith('.png') else 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            policy = "default-src 'self'; frame-ancestors 'none'; base-uri 'none'"
            if path == '/web-workspace': policy += "; frame-src http: https:; form-action 'self'; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'"
            self.send_header('Content-Security-Policy', policy)
            self.end_headers(); self.wfile.write(body); return
        if path == '/classic':
            body=d.render_html().replace('</head>','<link rel="stylesheet" href="/pixel-theme.css"></head>',1).replace('<body>','<body class="pixel-workshop">',1).encode('utf-8')
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body);return
        elif path == '/ops/state':
            report = ROOT / 'data' / 'cli_diagnostics.json'
            return self._send_json({'csrf': self.server.bridge_token,
                'orders': self.server.bridge.list(), 'allowed_projects': sorted(self.server.bridge.allowed),
                'diagnostics': json.loads(report.read_text(encoding='utf-8')) if report.exists() else None,
                'status': d.cached_status_payload(), 'solomon_url': 'http://127.0.0.1:8710'})
        elif path.startswith('/bridge/'):
            if not self.authorized():
                return self._send_json({'error': 'bridge authentication required'}, 403)
            try:
                if path == '/bridge/status':
                    return self._send_json({'ok': True, 'version': '1.0', 'orders': self.server.bridge.list()})
                if path == '/bridge/order':
                    ident = parse_qs(urlsplit(self.path).query).get('id', [''])[0]
                    return self._send_json(self.server.bridge.status(ident))
                if path == '/bridge/projects':
                    return self._send_json({'projects': project_registry()})
                if path == '/bridge/digest':
                    return self._send_json(d.build_digest_payload())
                if path == '/bridge/missions':
                    from core.mission import MissionStore
                    rows = sorted(MissionStore().all(), key=lambda m: m.get('updated_at', ''), reverse=True)[:30]
                    return self._send_json({'missions': [d.mission_view(m) for m in rows]})
                if path.startswith('/bridge/missions/'):
                    from core.mission import MissionStore
                    ident = path.split('/')[3][:80]
                    m = MissionStore().load(ident)
                    if not m:
                        return self._send_json({'error': '알 수 없는 미션입니다'}, 404)
                    return self._send_json(d.mission_view(m))
            except ValueError as exc:
                return self._send_json({'error': str(exc)}, 400)
        return super().do_GET()

    def authorized(self):
        return secrets.compare_digest(self.headers.get('X-Solomon-Bridge', ''), self.server.bridge_token)

    def do_POST(self):
        from core.company_backup import LOCK
        with LOCK:
            from core.company_backup import root
            if (root()/'restore_pending').is_dir() and self.path not in ('/ops/backup','/ops/shutdown','/ops/missions/stop'):
                return self._send_json({'error':'운영 기록 복구가 예약되어 새 변경을 잠갔습니다. 시스템을 중지하고 다시 실행하거나 비서실에서 복구 예약을 취소하세요.'},409)
            if getattr(self.server,'maintenance',False) and self.path!='/ops/shutdown':return self._send_json({'error':'업데이트 적용 중입니다. 잠시 후 다시 실행됩니다.'},503)
            return self._post_locked()

    def _post_locked(self):
        if self.path=='/ops/updates':
            if not d.is_request_origin_allowed(self.headers,self.server.server_address[1])[0] or not self.authorized():return self._send_json({'error':'local authenticated request required'},403)
            try:
                size=int(self.headers.get('Content-Length') or 0)
                if not 0<size<=16000 or self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('올바른 업데이트 요청이 필요합니다.')
                value=json.loads(self.rfile.read(size))
                if not isinstance(value,dict):raise ValueError('JSON 객체가 필요합니다.')
                from core import app_updates as updates
                action=value.get('action')
                if action=='settings':result=updates.save(value)
                elif action=='check':result=updates.check()
                elif action=='download':result=updates.download()
                elif action=='apply':result=updates.apply(self.server)
                else:raise ValueError('지원하지 않는 업데이트 동작입니다.')
                return self._send_json(result)
            except (ValueError,TypeError,OSError) as exc:return self._send_json({'error':str(exc)},400)
        if self.path=='/ops/development-rules':
            if not d.is_request_origin_allowed(self.headers,self.server.server_address[1])[0] or not self.authorized():return self._send_json({'error':'local authenticated request required'},403)
            try:
                size=int(self.headers.get('Content-Length') or 0)
                if not 0<size<=12000 or self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('올바른 규칙 설정 JSON이 필요합니다.')
                value=json.loads(self.rfile.read(size))
                if not isinstance(value,dict):raise ValueError('JSON 객체가 필요합니다.')
                from core.development_rules import save
                return self._send_json(save(value,d.validate_project_path))
            except TeamConflict as exc:return self._send_json({'error':str(exc)},409)
            except (ValueError,TypeError,OSError) as exc:return self._send_json({'error':str(exc)},400)
        if self.path=='/ops/setup':
            if not d.is_request_origin_allowed(self.headers,self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error':'local authenticated request required'},403)
            try:
                size=int(self.headers.get('Content-Length') or 0)
                if not 0<size<=12000 or self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('올바른 설정 요청이 필요합니다.')
                value=json.loads(self.rfile.read(size))
                if not isinstance(value,dict):raise ValueError('JSON 객체가 필요합니다.')
                from core import setup_assistant as setup
                action=value.get('action')
                if action=='install':result=setup.install()
                elif action=='cancel':result=setup.cancel()
                elif action=='check-mcp':result=setup.check_mcp(value)
                elif action=='registration':result=setup.registration(value)
                elif action=='finish-intro':result=setup.finish_intro()
                else:raise ValueError('지원하지 않는 설치·점검 동작입니다.')
                return self._send_json(result)
            except (ValueError,TypeError,OSError,subprocess.SubprocessError) as exc:return self._send_json({'error':str(exc)},400)
        if self.path in ('/ops/web-workspace','/ops/employee-tools','/ops/employee-tools/invoke','/ops/research-desk'):
            if not d.is_request_origin_allowed(self.headers,self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error':'local authenticated request required'},403)
            try:
                size=int(self.headers.get('Content-Length') or 0)
                if not 0<size<=1500000 or self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('올바른 JSON 요청이 필요합니다.')
                value=json.loads(self.rfile.read(size))
                if not isinstance(value,dict):raise ValueError('JSON 객체가 필요합니다.')
                from core import web_workspace as web, employee_tools
                if self.path=='/ops/employee-tools':result=employee_tools.save(value)
                elif self.path=='/ops/employee-tools/invoke':result=employee_tools.invoke(value.get('staff_id'),value.get('tool'),value.get('arguments'))
                elif self.path=='/ops/research-desk':result=employee_tools.research(value,d.validate_project_path)
                else:
                    if value.get('action') in {'save','restore'}:
                        from core.ai_connections import assert_idle
                        assert_idle()
                        if web.server_status(web.project(value.get('project_path')))['running'] and value.get('action')=='restore':raise ValueError('복구 전 개발 서버를 중지하세요.')
                    result=web.action(value)
                return self._send_json(result)
            except TeamConflict as exc:return self._send_json({'error':str(exc)},409)
            except (ValueError,TypeError,KeyError,OSError,subprocess.SubprocessError) as exc:return self._send_json({'error':str(exc)},400)
        if self.path in ('/ops/automation','/ops/automation/asset','/ops/automation/reconcile','/ops/youtube'):
            if not d.is_request_origin_allowed(self.headers,self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error':'local authenticated request required'},403)
            try:
                size=int(self.headers.get('Content-Length') or 0)
                if not 0<size<=20000 or self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('올바른 JSON 요청이 필요합니다.')
                value=json.loads(self.rfile.read(size))
                if not isinstance(value,dict):raise ValueError('JSON 객체가 필요합니다.')
                from core import scheduled_work as work, youtube_channel as youtube
                if self.path=='/ops/automation/asset':result=work.attach(value)
                elif self.path=='/ops/automation/reconcile':result=work.reconcile(value.get('id'),value.get('video_id') or None,value.get('confirmed',False))
                elif self.path=='/ops/youtube':
                    if work.ACTIVE:raise ValueError('업로드가 끝나거나 중지된 뒤 채널 설정을 변경하세요.')
                    if value.get('action')=='settings':result=youtube.save_settings(value)
                    elif value.get('action')=='login':result=youtube.start_login()
                    elif value.get('action')=='cancel-login':youtube.cancel_login();result=youtube.public()
                    elif value.get('action')=='disconnect':work.pause();result=youtube.disconnect()
                    else:raise ValueError('YouTube 연결 동작을 선택하세요.')
                elif value.get('action')=='preview':result={'plan':work.parse_command(value.get('command'))}
                elif value.get('action')=='plan':result=work.save_plan(value)
                elif value.get('action')=='prepare':result=work.prepare(value.get('id'))
                elif value.get('action')=='pause':result=work.pause(value.get('id'))
                else:result=work.action(value)
                return self._send_json(result)
            except (ValueError,TypeError,KeyError,OSError,TeamConflict) as exc:return self._send_json({'error':str(exc)},400)
        if self.path in ('/ops/backup','/ops/knowledge','/ops/office-layout'):
            if not d.is_request_origin_allowed(self.headers,self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error':'local authenticated request required'},403)
            try:
                size=int(self.headers.get('Content-Length') or 0)
                if not 0<size<=16000 or self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('올바른 JSON 요청이 필요합니다.')
                value=json.loads(self.rfile.read(size))
                if not isinstance(value,dict):raise ValueError('JSON 객체가 필요합니다.')
                from core import company_backup, company_knowledge
                if self.path == '/ops/office-layout':
                    from core.office_layout import save
                    result=save(value)
                elif self.path == '/ops/knowledge':result=company_knowledge.submit(value,d.validate_project_path)
                elif value.get('action')=='settings': result=company_backup.save_settings(value)
                elif value.get('action')=='create': result=company_backup.create()
                elif value.get('action')=='restore': result=company_backup.stage_restore(value.get('id'),value.get('confirmation'))
                elif value.get('action')=='cancel': result=company_backup.cancel_restore()
                else:raise ValueError('동작을 선택하세요.')
                return self._send_json(result)
            except (ValueError,TypeError,KeyError,OSError, TeamConflict) as exc:return self._send_json({'error':str(exc)},400)

        if self.path == '/ops/devices':
            if not d.is_request_origin_allowed(self.headers,self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error':'local authenticated request required'},403)
            try:
                size=int(self.headers.get('Content-Length') or 0)
                if not 0<size<=2048 or self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('올바른 기기 설정 JSON 요청이 필요합니다.')
                value=json.loads(self.rfile.read(size))
                if not isinstance(value,dict):raise ValueError('JSON 객체가 필요합니다.')
                from core.device_link import manager
                link=manager(self.server,ROOT);action=value.get('action')
                if action=='enable':result=link.start(value.get('address'),value.get('port',8443))
                elif action=='disable':result=link.close()
                elif action=='code':result=link.issue_code()
                elif action=='revoke':result=link.revoke(value.get('id'))
                else:raise ValueError('기기 연결 동작을 선택하세요.')
                return self._send_json(result)
            except (ValueError,TypeError) as exc:return self._send_json({'error':str(exc)},400)
            except (OSError,ImportError) as exc:return self._send_json({'error':'기기 연결을 준비하지 못했습니다. 최신 설치 파일로 재설치하세요. '+str(exc)},500)
        if self.path in ('/ops/mission-launch', '/ops/mission-control'):
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error': 'local authenticated request required'}, 403)
            from core.mission_launch import LaunchBusy, LaunchConflict
            try:
                size = int(self.headers.get('Content-Length') or 0)
                if not 0 < size <= 64000 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('올바른 JSON 요청이 필요합니다')
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError('JSON 객체가 필요합니다')
                if self.path == '/ops/mission-launch':
                    result, code = d.submit_mission_launch(payload)
                    return self._send_json(result, code)
                ident, action = payload.get('mission_id'), payload.get('action')
                if not isinstance(ident, str) or action not in ('apply', 'resume', 'extend', 'replan'):
                    raise ValueError('올바른 미션과 동작을 선택하세요')
                mission = next((m for m in d.MissionStore().all() if m['mission_id'] == ident), None)
                if not mission:
                    return self._send_json({'error': '미션을 찾을 수 없습니다'}, 404)
                from core.mission import _pid_alive
                if mission.get('status') == 'RUNNING' and (_pid_alive(mission.get('owner_pid')) or action == 'apply'):
                    raise LaunchBusy('미션이 진행 중입니다')
                if action != 'apply' and (mission.get('status') == 'DONE' or not mission.get('steps')):
                    raise ValueError('이 미션은 이어서 진행할 수 없습니다. 새 미션으로 요청하세요')
                reason = payload.get('reason', '')
                if not isinstance(reason, str) or len(reason) > 300:
                    raise ValueError('수정 지시는 300자 이하여야 합니다')
                result = d.decide_mission(ident, action, reason=reason, on_conflict='block', by='HUMAN')
                return self._send_json(result, 409 if result.get('status') == 'busy' else 400 if result.get('status') == 'error' else 200)
            except (LaunchBusy, LaunchConflict) as exc:
                return self._send_json({'error': str(exc)}, 409)
            except (ValueError, TypeError) as exc:
                return self._send_json({'error': str(exc)}, 400)
            except Exception as exc:
                return self._send_json({'error': str(exc)[:300]}, 500)
        if self.path in ('/ops/hermes/settings','/ops/hermes/probe','/ops/hermes/tasks','/ops/hermes/decide','/ops/hermes/stop'):
            if not d.is_request_origin_allowed(self.headers,self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error':'local authenticated request required'},403)
            from core import hermes_agent, staffing
            try:
                size=int(self.headers.get('Content-Length') or 0)
                if not 0<size<=64000 or self.headers.get('Content-Type','').split(';')[0]!='application/json': raise ValueError('올바른 JSON 요청이 필요합니다.')
                payload=json.loads(self.rfile.read(size))
                if not isinstance(payload,dict): raise ValueError('JSON 객체가 필요합니다.')
                if self.path.endswith('/settings'): result=hermes_agent.save(payload)
                elif self.path.endswith('/probe'): result=hermes_agent.probe()
                elif self.path.endswith('/tasks'):
                    job=hermes_agent.submit(payload,d.validate_project_path)
                    return self._send_json({'id':job['id'],'status':job['status']},202)
                elif self.path.endswith('/decide'): result=hermes_agent.decide(payload)
                else: result=hermes_agent.stop(payload.get('id'))
                return self._send_json(result)
            except staffing.TeamConflict as exc:return self._send_json({'error':str(exc)},409)
            except (ValueError,TypeError,KeyError) as exc:return self._send_json({'error':str(exc)},400)
            except Exception:return self._send_json({'error':'Hermes 요청을 처리하지 못했습니다.'},500)
        if self.path in ('/ops/ai-connections','/ops/ai-login','/ops/skill-library','/ops/skill-preview'):
            if not d.is_request_origin_allowed(self.headers,self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error':'local authenticated request required'},403)
            from core import ai_connections, skill_library, staffing
            try:
                size=int(self.headers.get('Content-Length') or 0)
                if not 0<size<=260000 or self.headers.get('Content-Type','').split(';')[0]!='application/json': raise ValueError('올바른 JSON 요청이 필요합니다.')
                payload=json.loads(self.rfile.read(size))
                if not isinstance(payload,dict): raise ValueError('JSON 객체가 필요합니다.')
                ai_connections.assert_idle()
                if self.path=='/ops/ai-connections': result=ai_connections.save(payload)
                elif self.path=='/ops/ai-login': result=ai_connections.login(payload.get('domain'))
                elif self.path=='/ops/skill-preview': result=skill_library.preview(payload.get('url'))
                else: result=skill_library.save(payload)
                return self._send_json(result)
            except staffing.TeamConflict as exc: return self._send_json({'error':str(exc)},409)
            except (ValueError,TypeError,KeyError) as exc: return self._send_json({'error':str(exc)},400)
            except Exception: return self._send_json({'error':'설정을 처리하지 못했습니다. 연결·파일 접근 상태를 확인하세요.'},500)
        if self.path == '/ops/briefings':
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error':'local authenticated request required'},403)
            from core import executive_briefing, staffing
            try:
                size=int(self.headers.get('Content-Length') or 0)
                if not 0<size<=8000 or self.headers.get('Content-Type','').split(';')[0]!='application/json': raise ValueError('올바른 JSON 요청이 필요합니다.')
                return self._send_json(executive_briefing.submit(json.loads(self.rfile.read(size)),d.validate_project_path))
            except staffing.TeamConflict as exc: return self._send_json({'error':str(exc)},409)
            except (ValueError,TypeError) as exc: return self._send_json({'error':str(exc)},400)
        if self.path in ('/ops/meetings', '/ops/meetings/decide'):
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error':'local authenticated request required'},403)
            from core import company_meetings, staffing
            try:
                size=int(self.headers.get('Content-Length') or 0)
                if not 0<size<=12000 or self.headers.get('Content-Type','').split(';')[0]!='application/json': raise ValueError('올바른 회의 JSON 요청이 필요합니다.')
                payload=json.loads(self.rfile.read(size))
                if self.path.endswith('/decide'): return self._send_json(company_meetings.decide(payload))
                meeting=company_meetings.submit(payload,d.load_config(),d.validate_project_path)
                return self._send_json({'id':meeting['id'],'status':meeting['status']},202)
            except staffing.TeamConflict as exc:
                return self._send_json({'error':str(exc)},409)
            except (ValueError,TypeError) as exc:
                return self._send_json({'error':str(exc)},400)
            except Exception as exc:
                return self._send_json({'error':str(exc)[:400]},500)
        if self.path == '/ops/company':
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error': 'local authenticated request required'}, 403)
            from core import company, staffing
            try:
                size = int(self.headers.get('Content-Length') or 0)
                if not 0 < size <= 4096 or self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                    raise ValueError('회사 설정 요청 형식이 올바르지 않습니다.')
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict): raise ValueError('JSON 객체가 필요합니다.')
                return self._send_json(company.save(payload.get('company'), payload.get('expected_revision')))
            except staffing.TeamConflict as exc:
                return self._send_json({'error': str(exc)}, 409)
            except (ValueError, TypeError) as exc:
                return self._send_json({'error': str(exc)}, 400)
            except OSError:
                return self._send_json({'error': '회사 설정을 저장하지 못했습니다.'}, 500)
        if self.path in ('/ops/team/recommendations', '/ops/team/game-ready'):
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error': 'local authenticated request required'}, 403)
            from core import staffing, team_recommendations
            from core.mission import MissionStore
            try:
                size = int(self.headers.get('Content-Length') or 0)
                if not 0 < size <= 64000 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('직원 추천 요청 형식을 확인하세요.')
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict) or set(payload) - {'team', 'expected_revision', 'goal', 'project_path', 'policy', 'game_project_path'}:
                    raise ValueError('직원 추천 요청을 확인하세요.')
                if payload.get('expected_revision') != staffing.current()['revision']:
                    raise staffing.TeamConflict('다른 창에서 직원 구성이 변경됐습니다. 다시 불러온 뒤 추천받으세요.')
                policy = payload.get('policy', 'specialty')
                if policy not in ('specialty', 'game_departments'):
                    raise ValueError('직원 배치 방식을 확인하세요.')
                from core import game_team_setup
                planner = game_team_setup.propose if policy == 'game_departments' or self.path.endswith('/game-ready') else team_recommendations.recommend
                result = planner(payload.get('team'), MissionStore().all(), payload.get('goal', ''), payload.get('project_path', ''))
                if self.path.endswith('/game-ready'):
                    if not result['team_ready']:
                        raise ValueError('자동 구성을 저장하지 않았습니다. ' + ' '.join(result['blocked'] + result['missing_slots'] + result['missing_managers']))
                    checks = game_team_setup.readiness(result['prepared_team'], d.load_config(), payload.get('game_project_path', ''))
                    saved = staffing.save(result['prepared_team'], payload.get('expected_revision'))
                    if payload.get('goal', '').strip():
                        checks['starter_brief']['goal'] = payload['goal'].strip()
                    return self._send_json({'team': saved, 'department_plan': result['department_plan'], 'readiness': checks, 'message': '게임 개발팀을 저장했습니다. 다음 미션부터 적용됩니다.'})
                return self._send_json(result)
            except staffing.TeamConflict as exc:
                return self._send_json({'error': str(exc)}, 409)
            except (ValueError, TypeError) as exc:
                return self._send_json({'error': str(exc)}, 400)
            except OSError:
                return self._send_json({'error': '현재 직원·업무를 읽지 못했습니다. 잠시 후 다시 시도하세요.'}, 503)
        if self.path == '/ops/team':
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error': 'local authenticated request required'}, 403)
            from core import staffing
            try:
                size = int(self.headers.get('Content-Length') or 0)
                if not 0 < size <= 64000 or self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                    raise ValueError('팀 설정 요청 형식이 올바르지 않습니다.')
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict): raise ValueError('팀 설정은 JSON 객체여야 합니다.')
                team = staffing.save(payload.get('team'), payload.get('expected_revision'))
                return self._send_json({'team': team, 'message': '팀 설정을 저장했습니다. 다음 미션부터 적용됩니다.'})
            except staffing.TeamConflict as exc:
                return self._send_json({'error': str(exc)}, 409)
            except (ValueError, TypeError) as exc:
                return self._send_json({'error': str(exc)}, 400)
            except OSError:
                return self._send_json({'error': '팀 설정을 저장하지 못했습니다.'}, 500)
        if self.path == '/ops/roles':
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error': 'local authenticated request required'}, 403)
            try:
                from core.role_settings import save
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 1024 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('Invalid role request')
                roles = save(json.loads(self.rfile.read(size)))
                try:
                    # Make the provider cards show the new HEAD/BUILDER/REVIEWER labels right away instead of
                    # after the next run (resolve_roles rewrites provider_health.current_role; can_proceed is ignored here).
                    from core.provider_manager import ProviderManager
                    ProviderManager().resolve_roles(roles['head'], roles['builder'], roles['reviewer'], strict=True)
                    d.invalidate_status_cache()
                except Exception as exc:  # bookkeeping only; the saved file is already the source of truth
                    logging.getLogger('director.companion').warning('role bookkeeping refresh failed: %s', exc)
                return self._send_json({'roles': roles, 'message': '저장됨 · 다음 대화/작업부터 적용됩니다. 진행 중인 실행은 유지됩니다.'})
            except (ValueError, TypeError, KeyError) as exc:
                return self._send_json({'error': str(exc)}, 400)
            except OSError:
                return self._send_json({'error': '역할 설정을 저장하지 못했습니다.'}, 500)
        if self.path == '/ops/missions/stop':
            # 작업 정지 (2026-11-03): stop running missions + kill their CLI processes; the dashboard stays up.
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error': 'local authenticated request required'}, 403)
            try:
                size = int(self.headers.get('Content-Length') or 0)
                payload = json.loads(self.rfile.read(size)) if 0 < size <= 4096 else {}
                if not isinstance(payload, dict):
                    payload = {}
                return self._send_json(d.stop_missions(str(payload.get('reason', ''))[:300], payload.get('mission_id') or None, by=str(payload.get('by') or '사용자')[:40]))
            except (ValueError, TypeError) as exc:
                return self._send_json({'error': str(exc)}, 400)
        if self.path == '/ops/shutdown':
            # "시스템 중지" (2026-11-02): stop the companion from the console or from Solomon. Records, worktrees and
            # mission state stay on disk; resume_on_start picks interrupted missions up again when it is restarted.
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error': 'local authenticated request required'}, 403)
            try:
                unread = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                unread = 0
            if 0 < unread <= 65536:
                self.rfile.read(unread)
            from core.web_workspace import shutdown as stop_web_tools
            from core.setup_assistant import shutdown as stop_setup
            stop_setup()
            stop_web_tools()
            self.server.stopping = True
            logging.getLogger('director.companion').warning('shutdown requested from %s', self.headers.get('Referer') or 'local client')
            import threading
            threading.Thread(target=self.server.shutdown, name='director-shutdown', daemon=True).start()
            return self._send_json({'stopping': True, 'message': 'AI DEV를 멈춥니다. 기록과 작업본은 남고, 다시 켜면 중단된 미션을 이어갑니다.'})
        if self.path == '/ops/pick-folder':
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error': 'local authenticated request required'}, 403)
            try:
                current = (d.cached_status_payload() or {}).get('project_path') or ''
            except Exception:
                current = ''
            result = pick_folder(current)
            return self._send_json(result, 409 if 'error' in result else 200)
        if self.path == '/bridge/missions' or (self.path.startswith('/bridge/missions/') and self.path.endswith('/decide')):
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error': 'bridge authentication required'}, 403)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 32000 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('JSON request required')
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError('object required')
                if self.path == '/bridge/missions':
                    ident = str(payload.get('request_id', ''))
                    if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', ident):
                        raise ValueError('안정적인 request_id가 필요합니다')
                    from core.mission import MissionStore
                    known = [m for m in MissionStore().all() if m.get('request_id') == ident]
                    if known:                                  # retries never start a second mission
                        return self._send_json({'status': 'duplicate', 'mission_id': known[0]['mission_id'], 'mission': d.mission_view(known[0])})
                    ok, target = solomon_target_ok(str(payload.get('project_path', '')))
                    if not ok:
                        raise ValueError(target)
                    goal = str(payload.get('goal', '')).strip()
                    if not 5 <= len(goal) <= 6000:
                        raise ValueError('작업 목표는 5~6000자여야 합니다')
                    result = d.start_goal_mission(target, goal, profile=payload.get('profile'), source='solomon', request_id=ident,
                                                  create_project=bool(payload.get('create_project')), auto_apply=payload.get('auto_apply'))
                    code = {'started': 202, 'busy': 409, 'question': 200, 'escalated': 200}.get(result.get('status'), 400)
                    return self._send_json(result, code)
                ident = self.path.split('/')[3][:80]
                result = d.decide_mission(ident, str(payload.get('action', '')), reason=str(payload.get('reason', ''))[:500],
                                          max_steps=payload.get('max_steps'), on_conflict=str(payload.get('on_conflict', 'block')), by='SOLOMON')
                return self._send_json(result, 200 if result.get('status') != 'error' else 400)
            except (ValueError, TypeError, KeyError) as exc:
                return self._send_json({'error': str(exc)}, 400)
            except Exception as exc:
                return self._send_json({'error': str(exc)[:500]}, 500)
        if self.path == '/bridge/orders':
            if not d.is_request_origin_allowed(self.headers, self.server.server_address[1])[0] or not self.authorized():
                return self._send_json({'error': 'bridge authentication required'}, 403)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 32000:
                    raise ValueError('request size rejected')
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('JSON required')
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError('object required')
                return self._send_json(self.server.bridge.submit(payload), 202)
            except (ValueError, TypeError, KeyError) as exc:
                return self._send_json({'error': str(exc)}, 400)
            except Exception as exc:
                return self._send_json({'error': str(exc)[:500]}, 500)
        return super().do_POST()


def run():
    probe_mode=os.environ.get('DIRECTOR_UPDATE_PROBE')=='1'
    if not probe_mode and (ROOT/'data/update_exit.json').exists():raise RuntimeError('업데이트 적용·복구 중에는 서버를 시작할 수 없습니다.')
    config = json.loads((ROOT / 'companion.json').read_text(encoding='utf-8'))
    # Reserve the port first: a second launch must never restore data under a live backend.
    server = d.DashboardServer(('127.0.0.1', config.get('port', 8081)), CompanionHandler)
    from core import company_backup
    try:
        company_backup.apply_pending()
        d._ensure_schema()
    except Exception:
        server.server_close()
        raise
    token_path = ROOT / 'data' / 'solomon-bridge.token'
    if not token_path.exists():
        token_path.write_text(secrets.token_urlsafe(48), encoding='utf-8')
    server.bridge_token = token_path.read_text(encoding='utf-8').strip()
    server.bridge = SolomonBridge(d, config.get('allowed_projects', []))
    if not probe_mode and (d.load_config().get('autonomy') or {}).get('resume_on_start'):
        threading.Thread(target=d.resume_interrupted_missions, name='director-mission-resume', daemon=True).start()
    from core.device_link import manager
    try:
        if not probe_mode:manager(server,ROOT).restore()
    except (ValueError,OSError) as exc:logging.getLogger('director.companion').error('Device link configuration failed: %s',exc)
    backup_stop=threading.Event()
    server.background_stop=backup_stop;server.maintenance=probe_mode
    if not probe_mode:company_backup.start_scheduler(backup_stop)
    from core import scheduled_work
    if not probe_mode:
        scheduled_work.start_scheduler(backup_stop)
        from core.app_updates import start_scheduler
        start_scheduler(backup_stop)
    server.stopping = False
    print('AI DEV × SOLOMON http://127.0.0.1:' + str(server.server_address[1]), flush=True)
    try:
        server.serve_forever()
    finally:
        backup_stop.set()
        scheduled_work.stop_active()
        from core.youtube_channel import cancel_login
        cancel_login()
        if hasattr(server,'device_link'):server.device_link.close(revoke=False,persist=False)
        server.server_close()
        print('AI DEV companion stopped (system stop)', flush=True)


if __name__ == '__main__':
    run()
