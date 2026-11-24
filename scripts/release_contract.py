"""Source-only release contract shared by package preflight and Windows setup."""
SETUP_FLOW=1
REQUIRED_SETUP_FILES={'core/mcp_runtime.py','core/github_resources.py','core/game_team_setup.py','core/team_recommendations.py','assets/crew-portraits-cozy-hd.png','console/cozy-office.js','console/cozy-office.css','release_version.py','core/app_updates.py','core/update_protocol.py','scripts/update_worker.py','scripts/sign_update.py','console/updates.html','console/updates.js','console/updates.css','core/development_rules.py','console/development-rules.js',
 'native_app.py','requirements-native.txt','core/setup_assistant.py','core/web_workspace.py','core/employee_tools.py',
 'scripts/setup_web_tools.py','scripts/director_mcp.py','scripts/web_audit.mjs','scripts/release_contract.py',
 'console/setup.html','console/setup.js','console/setup.css','console/web-workspace.html','console/web-workspace.js','console/web-tools.js',
 'tools/web/package.json','tools/web/package-lock.json','console/vendor/monaco/vs/loader.js','console/vendor/monaco/vs/editor/editor.main.js',
 'console/vendor/monaco/vs/editor/editor.main.css','console/vendor/monaco/LICENSE',
 'console/vendor/pixi/pixi.min.js','console/vendor/pixi/csp-support.js','console/vendor/pixi/LICENSE',
}

def require_setup_files(files):
    missing=REQUIRED_SETUP_FILES-set(files)
    if missing:raise ValueError('설치·연결 기능의 필수 파일이 빠졌습니다: '+', '.join(sorted(missing)))
