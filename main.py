import sys
import html
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QFrame,
    QFileDialog,
    QTabWidget,
    QMenu,
    QToolButton,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon, QAction, QKeySequence, QShortcut
from PyQt6.QtWebEngineWidgets import QWebEngineView

from dictionary_manager import DictionaryManager


class ImportWorker(QThread):
    """Background worker to import a single BGL file."""
    finished = pyqtSignal(bool, str)

    def __init__(self, manager: DictionaryManager, bgl_path: str):
        super().__init__()
        self.manager = manager
        self.bgl_path = bgl_path

    def run(self):
        success, msg = self.manager.import_bgl(self.bgl_path)
        self.finished.emit(success, msg)


class ScanWorker(QThread):
    """Background worker to scan and import dictionaries."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(list)

    def __init__(self, manager: DictionaryManager, source_dir: str):
        super().__init__()
        self.manager = manager
        self.source_dir = source_dir

    def run(self):
        self.progress.emit(f"Scanning '{self.source_dir}' for dictionaries...")
        results = self.manager.scan_and_import(self.source_dir)
        self.finished.emit(results)


class SearchWorker(QThread):
    """Background worker for searching (keeps UI responsive)."""
    results_ready = pyqtSignal(list)

    def __init__(self, manager: DictionaryManager, query: str):
        super().__init__()
        self.manager = manager
        self.query = query

    def run(self):
        results = self.manager.search(self.query, limit=50)
        self.results_ready.emit(results)


class ModernDictApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.manager = DictionaryManager()
        self.current_results = []  # Store current results for favorites
        
        self.setWindowTitle("Wordy - Modern Dictionary")
        self.resize(1200, 800)
        
        # Set App Icon
        icon_path = Path(__file__).parent / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        
        # Load Stylesheet
        self._load_stylesheet()
        
        self._init_ui()
        self._setup_shortcuts()
        self._start_auto_scan()

    def _load_stylesheet(self):
        try:
            with open("styles.qss", "r") as f:
                self.setStyleSheet(f.read())
        except Exception as e:
            print(f"Failed to load stylesheet: {e}")

    def _init_ui(self):
        # Main Layout
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Sidebar ---
        sidebar_frame = QFrame()
        sidebar_frame.setFixedWidth(300)
        sidebar_frame.setObjectName("Sidebar")
        sidebar_frame.setStyleSheet("background-color: #252526; border-right: 1px solid #333;")
        
        sidebar_layout = QVBoxLayout(sidebar_frame)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        # App Title in Sidebar
        title_label = QLabel("  📖 WORDY")
        title_label.setObjectName("HeaderTitle")
        title_label.setFixedHeight(50)
        title_label.setStyleSheet("padding-left: 10px; font-weight: bold; font-size: 18px; color: #4ec9b0;")
        sidebar_layout.addWidget(title_label)

        # Sidebar Tabs
        self.sidebar_tabs = QTabWidget()
        self.sidebar_tabs.setStyleSheet("""
            QTabWidget::pane { border: 0; background: #252526; }
            QTabBar::tab { background: #2d2d2d; color: #888; padding: 8px 12px; border: none; }
            QTabBar::tab:selected { background: #37373d; color: #fff; border-bottom: 2px solid #007acc; }
        """)

        # Dictionaries Tab
        dict_widget = QWidget()
        dict_layout = QVBoxLayout(dict_widget)
        dict_layout.setContentsMargins(0, 0, 0, 0)
        
        self.dict_list = QListWidget()
        self.dict_list.currentItemChanged.connect(self._on_dict_selected)
        dict_layout.addWidget(self.dict_list)
        
        # Import Button
        self.import_btn = QPushButton("📥 Import BGL File...")
        self.import_btn.clicked.connect(self._import_bgl)
        self.import_btn.setStyleSheet("""
            QPushButton { background: #0e639c; color: white; border: none; padding: 10px; margin: 8px; border-radius: 4px; }
            QPushButton:hover { background: #1177bb; }
            QPushButton:disabled { background: #3e3e42; color: #666; }
        """)
        dict_layout.addWidget(self.import_btn)
        
        self.sidebar_tabs.addTab(dict_widget, "📚 Libraries")

        # History Tab
        history_widget = QWidget()
        history_layout = QVBoxLayout(history_widget)
        history_layout.setContentsMargins(0, 0, 0, 0)
        
        self.history_list = QListWidget()
        self.history_list.itemDoubleClicked.connect(self._on_history_item_clicked)
        history_layout.addWidget(self.history_list)
        
        btn_clear_history = QPushButton("🗑️ Clear History")
        btn_clear_history.clicked.connect(self._clear_history)
        btn_clear_history.setStyleSheet("QPushButton { background: #333; color: #888; border: none; padding: 8px; margin: 8px; border-radius: 4px; } QPushButton:hover { background: #444; color: #fff; }")
        history_layout.addWidget(btn_clear_history)
        
        self.sidebar_tabs.addTab(history_widget, "🕐 History")

        # Favorites Tab
        favorites_widget = QWidget()
        favorites_layout = QVBoxLayout(favorites_widget)
        favorites_layout.setContentsMargins(0, 0, 0, 0)
        
        self.favorites_list = QListWidget()
        self.favorites_list.itemDoubleClicked.connect(self._on_favorite_item_clicked)
        favorites_layout.addWidget(self.favorites_list)
        
        self.sidebar_tabs.addTab(favorites_widget, "⭐ Favorites")

        sidebar_layout.addWidget(self.sidebar_tabs)

        # Scan Status / ProgressBar
        self.scan_progress = QProgressBar()
        self.scan_progress.setFixedHeight(4)
        self.scan_progress.setTextVisible(False)
        self.scan_progress.setStyleSheet("QProgressBar { border: 0px; background: #2d2d2d; } QProgressBar::chunk { background: #0e639c; }")
        self.scan_progress.hide()
        sidebar_layout.addWidget(self.scan_progress)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("padding: 8px; color: #888; font-size: 12px; background: #252526;")
        sidebar_layout.addWidget(self.status_label)

        main_layout.addWidget(sidebar_frame)

        # --- Main Content Area ---
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(20, 20, 20, 20)
        content_layout.setSpacing(15)

        # Search Area
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search for a word... (Ctrl+F)")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumHeight(50)
        self.search_input.setStyleSheet("font-size: 18px;")
        self.search_input.returnPressed.connect(self._perform_search)
        search_layout.addWidget(self.search_input)
        
        btn_search = QPushButton("🔍 Search")
        btn_search.setMinimumHeight(50)
        btn_search.setMinimumWidth(100)
        btn_search.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_search.clicked.connect(self._perform_search)
        search_layout.addWidget(btn_search)
        
        content_layout.addLayout(search_layout)

        # Web View for Results
        self.web_view = QWebEngineView()
        self.web_view.setHtml(self._get_welcome_html())
        content_layout.addWidget(self.web_view)

        main_layout.addLayout(content_layout)

    def _setup_shortcuts(self):
        """Setup keyboard shortcuts."""
        # Ctrl+F to focus search
        shortcut_search = QShortcut(QKeySequence("Ctrl+F"), self)
        shortcut_search.activated.connect(lambda: self.search_input.setFocus())
        
        # Ctrl+O to import file
        shortcut_import = QShortcut(QKeySequence("Ctrl+O"), self)
        shortcut_import.activated.connect(self._import_bgl)
        
        # Escape to clear search
        shortcut_escape = QShortcut(QKeySequence("Escape"), self)
        shortcut_escape.activated.connect(self.search_input.clear)

    def _import_bgl(self):
        """Open file dialog to import a custom BGL file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select BGL Dictionary File", "", "BGL Files (*.bgl *.BGL)"
        )
        if not path:
            return

        self.import_btn.setEnabled(False)
        self.status_label.setText(f"⏳ Importing '{Path(path).name}'...")

        self.import_worker = ImportWorker(self.manager, path)
        self.import_worker.finished.connect(self._on_import_finished)
        self.import_worker.start()

    def _on_import_finished(self, success: bool, message: str):
        self.import_btn.setEnabled(True)
        if success:
            QMessageBox.information(self, "✅ Success", message)
            self._load_dictionaries()
        else:
            QMessageBox.critical(self, "❌ Import Failed", message)
        self.status_label.setText(message[:80] + "..." if len(message) > 80 else message)

    def _start_auto_scan(self):
        self.scan_progress.show()
        self.scan_progress.setRange(0, 0)
        self.scan_worker = ScanWorker(self.manager, "sources")
        self.scan_worker.progress.connect(self.status_label.setText)
        self.scan_worker.finished.connect(self._on_scan_finished)
        self.scan_worker.start()

    def _on_scan_finished(self, results):
        self.scan_progress.hide()
        import_count = sum(1 for r in results if r['status'] == 'success')
        self.status_label.setText(f"Scan complete. {import_count} imported.")
        self._load_dictionaries()
        self._load_history()
        self._load_favorites()
        
        errors = [r for r in results if r['status'] == 'error']
        if errors:
            msg = "\n".join([f"• {e['file']}: {e['message'][:50]}..." for e in errors])
            QMessageBox.warning(self, "Import Issues", f"Some files could not be imported:\n\n{msg}")

    def _load_dictionaries(self):
        self.dict_list.clear()
        dicts = self.manager.get_dictionaries()
        
        if not dicts:
            item = QListWidgetItem("No dictionaries found")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.dict_list.addItem(item)
            return

        for dict_id, name, count in dicts:
            display_name = name.replace("_", " ").title()
            item = QListWidgetItem(f"📕 {display_name} ({count:,})")
            item.setData(Qt.ItemDataRole.UserRole, dict_id)
            self.dict_list.addItem(item)
        
        if self.dict_list.count() > 0:
            self.dict_list.setCurrentRow(0)

    def _load_history(self):
        self.history_list.clear()
        history = self.manager.get_history(limit=30)
        for query, timestamp in history:
            item = QListWidgetItem(f"🔍 {query}")
            item.setData(Qt.ItemDataRole.UserRole, query)
            item.setToolTip(timestamp)
            self.history_list.addItem(item)

    def _load_favorites(self):
        self.favorites_list.clear()
        favorites = self.manager.get_favorites(limit=50)
        for word, definition, added_at in favorites:
            item = QListWidgetItem(f"⭐ {word}")
            item.setData(Qt.ItemDataRole.UserRole, (word, definition))
            item.setToolTip(f"Added: {added_at}")
            self.favorites_list.addItem(item)

    def _on_dict_selected(self, current: QListWidgetItem, previous: QListWidgetItem):
        if not current:
            return
        dict_id = current.data(Qt.ItemDataRole.UserRole)
        if dict_id:
            self.manager.set_active_dictionary(dict_id)
            self.search_input.setFocus()
            if self.search_input.text():
                self._perform_search()

    def _on_history_item_clicked(self, item: QListWidgetItem):
        query = item.data(Qt.ItemDataRole.UserRole)
        if query:
            self.search_input.setText(query)
            self._perform_search()

    def _on_favorite_item_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            word, definition = data
            self._display_single_result(word, definition)

    def _clear_history(self):
        self.manager.clear_history()
        self._load_history()
        self.status_label.setText("History cleared")

    def _perform_search(self):
        query = self.search_input.text().strip()
        if not query:
            return
        
        # Add to history
        self.manager.add_to_history(query)
        self._load_history()
        
        self.status_label.setText(f"Searching for '{query}'...")
        
        self.search_worker = SearchWorker(self.manager, query)
        self.search_worker.results_ready.connect(self._display_results)
        self.search_worker.start()

    def _display_results(self, results):
        self.status_label.setText("Ready")
        query = self.search_input.text().strip()
        self.current_results = results
        
        if not results:
            self.web_view.setHtml(self._get_no_results_html(query))
            return

        html_content = self._get_base_html()
        html_content += '<div class="results-container">'
        
        for word, definition in results:
            is_fav = self.manager.is_favorite(word)
            fav_icon = "★" if is_fav else "☆"
            formatted_def = definition.replace("\n", "<br>")
            
            html_content += f"""
            <div class="card">
                <div class="word-header">
                    <span>{html.escape(word)}</span>
                    <span class="fav-icon" title="{'Remove from favorites' if is_fav else 'Add to favorites'}">{fav_icon}</span>
                </div>
                <div class="definition">{formatted_def}</div>
            </div>
            """
        
        html_content += "</div></body></html>"
        self.web_view.setHtml(html_content)

    def _display_single_result(self, word: str, definition: str):
        html_content = self._get_base_html()
        formatted_def = definition.replace("\n", "<br>")
        html_content += f"""
        <div class="card">
            <div class="word-header">{html.escape(word)}</div>
            <div class="definition">{formatted_def}</div>
        </div>
        </body></html>
        """
        self.web_view.setHtml(html_content)

    def _get_base_html(self):
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <link href="https://cdn.jsdelivr.net/npm/vazirmatn@35.0.0/Vazirmatn-font-face.css" rel="stylesheet">
            <style>
                body {
                    background-color: #1e1e1e;
                    color: #e0e0e0;
                    font-family: "Vazirmatn", "Segoe UI", "Helvetica Neue", sans-serif;
                    padding: 20px;
                    line-height: 1.8;
                    direction: auto;
                }
                .card {
                    background-color: #252526;
                    border: 1px solid #333;
                    border-radius: 10px;
                    padding: 24px;
                    margin-bottom: 20px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.4);
                    transition: transform 0.2s ease;
                }
                .card:hover {
                    transform: translateY(-2px);
                }
                .word-header {
                    font-size: 28px;
                    color: #4ec9b0;
                    margin-bottom: 12px;
                    border-bottom: 1px solid #3e3e42;
                    padding-bottom: 10px;
                    font-weight: 700;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                }
                .fav-icon {
                    color: #f5c518;
                    cursor: pointer;
                    font-size: 24px;
                }
                .definition {
                    color: #cccccc;
                    font-size: 17px;
                }
                .highlight {
                    background-color: rgba(255, 255, 0, 0.2);
                    color: #fff;
                    border-radius: 3px;
                    padding: 0 2px;
                }
                a { color: #569cd6; text-decoration: none; }
            </style>
        </head>
        <body>
        """

    def _get_welcome_html(self):
        base = self._get_base_html()
        return base + """
            <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 80vh; color: #777;">
                <h1 style="font-size: 56px; margin-bottom: 10px; color: #4ec9b0;">📖 WORDY</h1>
                <p style="font-size: 20px; color: #888;">Type a word above to start searching</p>
                <div style="margin-top: 40px; text-align: left; background: #252526; padding: 24px; border-radius: 12px; max-width: 500px;">
                    <p style="font-size: 16px; color: #aaa;"><strong>⌨️ Keyboard Shortcuts:</strong></p>
                    <ul style="font-size: 14px; color: #888;">
                        <li><code>Ctrl+F</code> - Focus search bar</li>
                        <li><code>Ctrl+O</code> - Import BGL file</li>
                        <li><code>Escape</code> - Clear search</li>
                        <li><code>Enter</code> - Search</li>
                    </ul>
                </div>
            </div>
        </body></html>
        """

    def _get_no_results_html(self, query):
        base = self._get_base_html()
        return base + f"""
            <div style="text-align: center; padding-top: 60px;">
                <h2 style="color: #f44747; font-size: 28px;">No results found</h2>
                <p style="font-size: 18px;">We couldn't find any matches for "<strong>{html.escape(query)}</strong>"</p>
                <p style="color: #666; font-size: 14px;">Try checking the spelling or switching dictionaries.</p>
            </div>
        </body></html>
        """


def main():
    app = QApplication(sys.argv)
    
    # Set app icon globally
    icon_path = Path(__file__).parent / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    
    window = ModernDictApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
