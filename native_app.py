"""Dedicated Qt desktop shell. The backend uses the installed Python environment."""
import argparse
import json
import hashlib
import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
from urllib.parse import urlsplit

from desktop_launcher import DesktopError, ensure_server, show_error, startup_path


def app_root(explicit=None):
    if explicit:
        candidates = [Path(explicit).resolve()]
    elif getattr(sys, 'frozen', False):
        candidates = list(Path(sys.executable).resolve().parents)
    else:
        candidates = [Path(__file__).resolve().parent]
    for candidate in candidates:
        if (candidate / 'companion_server.py').is_file() and (candidate / 'companion.json').is_file():
            return candidate
    raise DesktopError('설치 폴더를 찾을 수 없습니다. INSTALL_DESKTOP.cmd를 다시 실행하세요.')


def navigation_kind(url, base):
    if url == 'about:blank':
        return 'internal'
    target, origin = urlsplit(url), urlsplit(base)
    if (target.scheme, target.netloc) == (origin.scheme, origin.netloc):
        return 'internal'
    return 'external' if target.scheme == 'https' else 'blocked'


def preview_frame_allowed(url,base,current_url,main_frame):
    if main_frame:return False
    try:
        target=urlsplit(url);current=urlsplit(current_url);origin=urlsplit(base)
        return (current.scheme,current.netloc)==(origin.scheme,origin.netloc) and current.path=='/web-workspace' and target.scheme in {'http','https'} and bool(target.hostname) and target.username is None and target.password is None
    except ValueError:return False


def native_logger(root):
    log = logging.getLogger('director.native.' + str(root))
    if not log.handlers:
        path = Path(root) / 'data' / 'desktop-native.log'
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=2, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False
    return log


def configure_graphics(hardware=False):
    # Use software composition by default: stage WebGL must not take down the embedded UI.
    if not hardware:
        flags = os.environ.get('QTWEBENGINE_CHROMIUM_FLAGS', '').split()
        if '--disable-gpu' not in flags:
            flags.append('--disable-gpu')
        os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = ' '.join(flags)


def run(root, initial_url=None, hardware_graphics=False):
    configure_graphics(hardware_graphics)
    log = native_logger(root)
    from PySide6.QtCore import QThread, Signal, QUrl, Qt, QTimer, qInstallMessageHandler
    from PySide6.QtGui import QDesktopServices, QIcon, QAction, QColor
    from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QStackedWidget, QFileDialog, QDialog, QFormLayout, QLineEdit, QComboBox, QPushButton, QMessageBox
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView

    if os.name == 'nt':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('AiDevDirector.MissionCenter.Native.v3')
    if not QApplication.instance() and not hardware_graphics:
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    previous_qt_handler = qInstallMessageHandler(lambda kind, context, message: log.warning('Qt: %s', message))
    log.info('Window starting; hardware_graphics=%s', hardware_graphics)
    app.setApplicationName('AI DEV DIRECTOR')
    app.setOrganizationName('AI Dev Director')
    icon = QIcon(str(Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'assets' / 'director.svg'))
    app.setWindowIcon(icon)

    class Startup(QThread):
        ready = Signal(str)
        failed = Signal(str)

        def run(self):
            try:
                self.ready.emit(initial_url or ensure_server(root=root))
            except Exception as exc:
                self.failed.emit(str(exc))

    class Page(QWebEnginePage):
        def acceptNavigationRequest(self, url, kind, main_frame):
            decision = navigation_kind(url.toString(), window.base)
            if preview_frame_allowed(url.toString(),window.base,window.view.url().toString(),main_frame):
                return True
            if decision == 'internal':
                return True
            if decision == 'external' and kind == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
                QDesktopServices.openUrl(url)
            return False

    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.base = 'about:blank'
            self.closing = False
            self.has_loaded = False
            self.setWindowTitle('AI DEV DIRECTOR')
            self.setWindowIcon(icon)
            self.resize(1280, 860)
            self.stack = QStackedWidget(self)
            self.setCentralWidget(self.stack)
            self.message = QLabel('AI DEV DIRECTOR\n\n프로그램을 시작하고 있습니다…')
            self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.message.setStyleSheet('background:#101719;color:#b5f9de;font-size:20px;padding:30px')
            self.stack.addWidget(self.message)
            self.profile = QWebEngineProfile('director-native', self)
            self.profile.setPersistentStoragePath(str(root / 'data' / 'webview' / 'storage'))
            try:
                cache_version = json.loads((root / 'desktop_distribution.json').read_text(encoding='utf-8')).get('version', 'development')
            except (OSError, ValueError):
                cache_version = 'development'
            cache_key = hashlib.sha256(str(cache_version).encode()).hexdigest()[:16]
            self.profile.setCachePath(str(root / 'data' / 'webview' / 'cache' / cache_key))
            self.profile.downloadRequested.connect(self.download)
            self.view = QWebEngineView(self)
            self.page = Page(self.profile, self.view)
            self.view.setPage(self.page)
            self.page.newWindowRequested.connect(self.open_popup)
            self.page.setBackgroundColor(QColor('#101719'))
            self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, hardware_graphics)
            self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, hardware_graphics)
            self.page.renderProcessTerminated.connect(self.renderer_stopped)
            self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
            self.page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
            self.view.loadFinished.connect(self.loaded)
            self.stack.addWidget(self.view)
            menu = self.menuBar().addMenu('앱')
            for label, shortcut, callback in (
                ('업데이트 확인', None, lambda: self.navigate('/updates')),
                ('설치·연결 점검', None, lambda: self.navigate('/setup')),
                ('웹 작업실', None, lambda: self.navigate('/web-workspace')),
                ('회사 사무실', None, lambda: self.navigate('/office')),
                ('AI·스킬 설정', None, lambda: self.navigate('/settings')),
                ('예약 업무 · YouTube', None, lambda: self.navigate('/automation')),
                ('비서실·백업·회사 지식', None, lambda: self.navigate('/operations')),
                ('미션 센터', None, lambda: self.navigate('/missions')),
                ('태블릿·휴대폰 연결', None, lambda: self.navigate('/devices')),
                ('새로고침', 'Ctrl+R', self.reload_page),
                ('확대', 'Ctrl++', lambda: self.view.setZoomFactor(min(2, self.view.zoomFactor() + .1))),
                ('축소', 'Ctrl+-', lambda: self.view.setZoomFactor(max(.5, self.view.zoomFactor() - .1))),
                ('게임 프로젝트 검증 설정…', None, self.engine_setup),
                ('기록 폴더 열기', None, lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(root / 'data')))),
            ):
                action = QAction(label, self)
                if shortcut:
                    action.setShortcut(shortcut)
                action.triggered.connect(callback)
                menu.addAction(action)
            import psutil
            self.client_file=root/'data/desktop_clients'/(str(os.getpid())+'.json')
            self.client_file.parent.mkdir(parents=True,exist_ok=True)
            self.client_file.write_text(json.dumps({'pid':os.getpid(),'created':psutil.Process().create_time(),'installation_id':hashlib.sha256(os.path.normcase(str(root.resolve())).encode()).hexdigest()}),encoding='utf-8')
            self.update_notice=None
            self.update_timer=QTimer(self);self.update_timer.timeout.connect(self.check_update_exit);self.update_timer.start(1000)
            self.worker = Startup(self)
            self.worker.ready.connect(self.ready)
            self.worker.failed.connect(self.failed)
            self.worker.finished.connect(self.finish_start)
            self.worker.start()

        def check_update_exit(self):
            marker=root/'data/update_exit.json'
            try:
                if marker.exists():
                    record=json.loads(marker.read_text(encoding='utf-8'));ident=record.get('job_id','')
                    import re
                    if re.fullmatch('UPD-[a-f0-9]{20}',ident) and (root/'data/app_updates'/ident/'job.json').is_file():
                        self.close();app.quit();return
                path=root/'data/update_state.json'
                if path.exists():
                    state=json.loads(path.read_text(encoding='utf-8'));key=(state.get('status'),state.get('version'))
                    if key!=self.update_notice:
                        self.update_notice=key
                        if state.get('status') in {'AVAILABLE','READY','INSTALLER_REQUIRED','ROLLED_BACK','ERROR'}:self.statusBar().showMessage('업데이트: '+state.get('message','')+' · 앱 메뉴의 업데이트 확인',15000)
            except (OSError,ValueError):pass

        def engine_setup(self):
            from core.engine_settings import save
            dialog = QDialog(self)
            dialog.setWindowTitle('게임 프로젝트 검증 설정')
            dialog.resize(660, 260)
            form = QFormLayout(dialog)
            engine = QComboBox();engine.addItems(['Godot', 'Unity'])
            project = QLineEdit();executable = QLineEdit()
            platform = QComboBox();platform.addItems(['EditMode', 'PlayMode'])
            form.addRow('게임 엔진', engine)
            form.addRow('프로젝트 폴더', project)
            choose_project = QPushButton('프로젝트 폴더 찾아보기')
            choose_project.clicked.connect(lambda: project.setText(QFileDialog.getExistingDirectory(dialog, '게임 프로젝트 루트', project.text()) or project.text()))
            form.addRow('', choose_project)
            form.addRow('엔진 실행 파일', executable)
            choose_executable = QPushButton('실행 파일 찾아보기')
            choose_executable.clicked.connect(lambda: executable.setText(QFileDialog.getOpenFileName(dialog, '엔진 실행 파일', executable.text())[0] or executable.text()))
            form.addRow('', choose_executable)
            form.addRow('Unity 테스트 모드', platform)
            note = QLabel('Godot: project.godot 폴더 · Unity: Assets/ProjectSettings가 있는 폴더\n다음 작업부터 적용됩니다. 실행 중인 작업은 먼저 완료하거나 중지하세요.\n테스트 준비 방법은 설치 폴더 docs/GAME_DEVELOPMENT_KO.md를 확인하세요.')
            note.setWordWrap(True);form.addRow(note)
            button = QPushButton('이 프로젝트의 엔진 테스트 설정 저장')
            def store():
                try:
                    save(root, project.text(), engine.currentText().lower(), executable.text(), platform.currentText())
                    dialog.accept()
                    self.statusBar().showMessage('게임 엔진 검증 설정을 저장했습니다. 다음 미션부터 적용됩니다.', 10000)
                except Exception as exc:
                    QMessageBox.warning(dialog, '설정 확인', str(exc))
            button.clicked.connect(store);form.addRow(button)
            dialog.exec()

        def ready(self, url):
            if not self.closing:
                destination = QUrl(url)
                if initial_url is None:
                    destination.setPath(startup_path(root))
                self.base = destination.toString()
                self.view.load(destination)

        def loaded(self, ok):
            if ok:
                self.has_loaded = True
                self.stack.setCurrentWidget(self.view)
                self.statusBar().clearMessage()
            elif self.has_loaded:
                # An aborted/rejected navigation is not a reason to hide a working page.
                log.warning('Navigation did not finish; keeping existing UI: %s', self.view.url().toString())
                self.statusBar().showMessage('화면 이동이 완료되지 않았습니다. 필요하면 Ctrl+R로 새로고침하세요.', 8000)
            else:
                self.message.setText('화면에 연결할 수 없습니다.\n앱 메뉴에서 새로고침하거나 앱을 다시 실행하세요.')
                self.stack.setCurrentWidget(self.message)

        def navigate(self, path):
            if self.base != 'about:blank':
                destination = QUrl(self.base)
                destination.setPath(path)
                destination.setQuery('')
                destination.setFragment('')
                self.view.load(destination)

        def reload_page(self):
            if self.base != 'about:blank':
                current = self.view.url()
                if navigation_kind(current.toString(), self.base) == 'internal' and current.scheme() in ('http', 'https'):
                    self.view.reload()
                else:
                    self.view.load(QUrl(self.base))

        def open_popup(self, request):
            # OAuth must open in the system browser, including user-clicked target=_blank links.
            if not request.isUserInitiated():
                return
            url = request.requestedUrl()
            kind = navigation_kind(url.toString(), self.base)
            if kind == 'external':
                QDesktopServices.openUrl(url)
            elif kind == 'internal':
                self.view.load(url)

        def renderer_stopped(self, status, code):
            log.error('Renderer stopped: status=%s exit_code=%s url=%s', status, code, self.view.url().toString())
            self.message.setText('화면 엔진이 중단됐습니다. 앱 메뉴에서 새로고침을 눌러주세요.\n진행 중인 작업은 서버에서 유지됩니다.\n기록: data/desktop-native.log')
            self.stack.setCurrentWidget(self.message)

        def failed(self, message):
            log.error('Startup failed: %s', message)
            self.message.setText('시작하지 못했습니다.\n\n' + message)
            show_error(message, root)

        def finish_start(self):
            if self.closing:
                self.close()

        def closeEvent(self, event):
            if self.worker.isRunning():
                self.closing = True
                self.hide()
                event.ignore()
            else:
                event.accept()

        def download(self, request):
            path, _ = QFileDialog.getSaveFileName(self, '파일 저장', request.suggestedFileName())
            if not path:
                request.cancel()
                return
            destination = Path(path)
            request.setDownloadDirectory(str(destination.parent))
            request.setDownloadFileName(destination.name)
            request.accept()

    window = Window()
    def dispose():
        # Qt profiles must outlive every page; QObject child creation order is insufficient.
        import shiboken6
        if shiboken6.isValid(window.view):
            shiboken6.delete(window.view)
        if shiboken6.isValid(window.profile):
            shiboken6.delete(window.profile)
        window.update_timer.stop()
        window.client_file.unlink(missing_ok=True)
        log.info('Window closed')
        qInstallMessageHandler(previous_qt_handler)

    app.aboutToQuit.connect(dispose)
    window.show()
    # Also useful for embedding and automated UI verification; no second event loop is started here.
    return app, window


def main():
    parser = argparse.ArgumentParser(description='AI DEV DIRECTOR native desktop app')
    parser.add_argument('--app-root')
    parser.add_argument('--hardware-graphics', action='store_true', help='Opt into GPU rendering instead of stable software mode')
    args = parser.parse_args()
    root = None
    try:
        root = app_root(args.app_root)
        log = native_logger(root)
        def report_exception(kind, value, traceback):
            log.error('Unhandled GUI exception', exc_info=(kind, value, traceback))
        sys.excepthook = report_exception
        import faulthandler
        with (root / 'data' / 'desktop-fault.log').open('a', encoding='utf-8') as faults:
            faulthandler.enable(file=faults)
            try:
                app, window = run(root, hardware_graphics=args.hardware_graphics)
                return app.exec()
            finally:
                faulthandler.disable()
    except Exception as exc:
        show_error(str(exc), root or Path(__file__).resolve().parent)
        return 1


if __name__ == '__main__':
    sys.exit(main())
