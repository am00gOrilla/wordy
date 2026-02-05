import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Optional, List, Tuple
from pyglossary.glossary_v2 import Glossary

# Initialize plugins once
Glossary.init()


class DictionaryManager:
    def __init__(self, db_path: str = "dictionaries.db"):
        self.db_path = db_path
        self.current_dict_id: Optional[int] = None
        self._init_db()

    def _init_db(self):
        """Initialize DB with schema migration support"""
        with sqlite3.connect(self.db_path) as conn:
            # Create tables if they don't exist
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dictionaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    source_path TEXT NOT NULL,
                    word_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dictionary_id INTEGER NOT NULL,
                    word TEXT NOT NULL,
                    definition TEXT NOT NULL,
                    FOREIGN KEY(dictionary_id) REFERENCES dictionaries(id) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_word ON entries(word)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dict_word ON entries(dictionary_id, word)"
            )

            # Search history table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS search_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    dictionary_id INTEGER,
                    searched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(dictionary_id) REFERENCES dictionaries(id) ON DELETE SET NULL
                )
            """)

            # Favorites/Bookmarks table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    word TEXT NOT NULL,
                    definition TEXT NOT NULL,
                    dictionary_id INTEGER,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(dictionary_id) REFERENCES dictionaries(id) ON DELETE SET NULL
                )
            """)

            # Schema migration: add is_encrypted column if missing
            try:
                conn.execute(
                    "ALTER TABLE dictionaries ADD COLUMN is_encrypted BOOLEAN DEFAULT 0"
                )
                conn.commit()
            except sqlite3.OperationalError:
                # Column already exists
                pass

    def _is_encrypted_bgl(self, file_path: str) -> Tuple[bool, str]:
        """Detect if BGL file is encrypted (common with Persian commercial dictionaries)"""
        try:
            with open(file_path, "rb") as f:
                header = f.read(32)

                # Unencrypted BGL typically starts with 0x00 0x01 or 0x01 0x00
                if header.startswith(b"\x00\x01") or header.startswith(b"\x01\x00"):
                    return False, "Unencrypted BGL detected"

                # Common encryption signatures in commercial Babylon dictionaries
                if (
                    b"BAB" in header
                    or b"\xff\xfe" in header[:4]
                    or b"\xfe\xff" in header[:4]
                ):
                    return (
                        True,
                        "ENCRYPTED: Commercial Babylon dictionary (DRM protected)",
                    )

                # Persian commercial dictionaries often have these patterns
                if any(
                    sig in header
                    for sig in [b"hFarsi", b"Aryanpur", b"BGL", b"\x1f\x8b"]
                ):
                    # Heuristic: if it has dictionary name but not standard BGL header → likely encrypted
                    if not (
                        header.startswith(b"\x00\x01") or header.startswith(b"\x01\x00")
                    ):
                        return (
                            True,
                            "LIKELY ENCRYPTED: Persian commercial dictionary (Aryanpur/hFarsi)",
                        )

                return False, "Unknown format - may be unencrypted"
        except Exception as e:
            return False, f"Error checking header: {str(e)}"

    def import_bgl(self, bgl_path: str) -> Tuple[bool, str]:
        """Import BGL file with encryption detection and explicit format handling"""
        try:
            bgl_path = os.path.abspath(bgl_path)
            if not os.path.exists(bgl_path):
                return False, f"File not found: {bgl_path}"

            if not bgl_path.lower().endswith(".bgl"):
                return False, "File must have .bgl extension (case-insensitive check)"

            # Pre-check for encryption (saves time on failed imports)
            is_encrypted, hint = self._is_encrypted_bgl(bgl_path)
            if is_encrypted:
                return False, (
                    "🔒 ENCRYPTION DETECTED\n\n"
                    f"File appears to be a commercial encrypted dictionary ({hint}).\n\n"
                    "⚠️  Babylon's Persian dictionaries (Aryanpur Pro, hFarsi Advanced) use proprietary DRM\n"
                    "that cannot be legally decrypted by third-party tools.\n\n"
                    "✅ WORKING ALTERNATIVES:\n"
                    "   • Use FREE unencrypted dictionaries from: https://github.com/ilius/pyglossary/wiki/BGL\n"
                    "   • Convert StarDict format (.dict.dz + .idx) using pyglossary\n"
                    "   • Export definitions via Babylon's official software first"
                )

            dict_name = (
                Path(bgl_path)
                .stem.replace(" ", "_")
                .replace(".", "_")
                .replace("-", "_")
            )

            # Normalize extension to lowercase for pyglossary compatibility
            if bgl_path != bgl_path.lower():
                normalized_path = str(Path(bgl_path).with_suffix(".bgl").resolve())
                if not os.path.exists(normalized_path):
                    # Create lowercase symlink/copy for compatibility
                    try:
                        import shutil

                        shutil.copy2(bgl_path, normalized_path)
                        bgl_path = normalized_path
                    except:
                        pass  # Proceed with original path

            with tempfile.TemporaryDirectory() as tmpdir:
                glos = Glossary()

                # Use directRead for glossary_v2 API
                try:
                    glos.directRead(bgl_path, formatName="BabylonBgl")
                except Exception as e:
                    err = str(e).lower()
                    if any(
                        k in err for k in ["encrypt", "password", "drm", "protected"]
                    ):
                        return False, (
                            "🔒 DECRYPTION FAILED\n\n"
                            "This is a commercial encrypted Babylon dictionary.\n"
                            "No legal tool can decrypt these files.\n\n"
                            "✅ Get FREE Persian dictionaries:\n"
                            "   https://github.com/kiomarszadeh/Persian-Dictionary"
                        )
                    return False, f"BGL parsing error: {str(e)}"

                # Collect entries by iterating over the glossary
                entries = []
                try:
                    for entry in glos:
                        if entry.isData():
                            continue
                        word = entry.s_word
                        defi = entry.defi
                        if word and defi:
                            entries.append((word, defi))
                except Exception as e:
                    glos.cleanup()
                    return False, f"Error reading entries: {str(e)}"

                glos.cleanup()

                if not entries:
                    return (
                        False,
                        "Dictionary contains no entries (likely encrypted or corrupted)",
                    )

                # Clean entries (handle encoding issues common in Persian text)
                cleaned = []
                for word, defi in entries:
                    try:
                        w = str(word).strip()
                        d = str(defi).strip()
                        if w and d:
                            cleaned.append((w, d))
                    except:
                        continue

                if not cleaned:
                    return (
                        False,
                        "No valid entries after cleaning (encoding issues)",
                    )

                # Import into main DB
                with sqlite3.connect(self.db_path) as conn:
                    # Store dictionary metadata
                    conn.execute(
                        """INSERT OR REPLACE INTO dictionaries 
                           (name, source_path, word_count, is_encrypted) 
                           VALUES (?, ?, ?, 0)""",
                        (dict_name, bgl_path, len(cleaned)),
                    )
                    dict_id = conn.execute(
                        "SELECT id FROM dictionaries WHERE name = ?", (dict_name,)
                    ).fetchone()[0]

                    # Store entries
                    conn.execute(
                        "DELETE FROM entries WHERE dictionary_id = ?", (dict_id,)
                    )
                    conn.executemany(
                        "INSERT INTO entries (dictionary_id, word, definition) VALUES (?, ?, ?)",
                        [(dict_id, w, d) for w, d in cleaned],
                    )
                    conn.commit()
                    self.current_dict_id = dict_id
                    return (
                        True,
                        f"✅ Imported {len(cleaned):,} entries from '{dict_name}'",
                    )

        except Exception as e:
            return False, f"Import failed: {type(e).__name__}: {str(e)}"

    def search(self, query: str, limit: int = 20) -> List[Tuple[str, str]]:
        if not self.current_dict_id or not query.strip():
            return []

        query = query.strip().lower()
        with sqlite3.connect(self.db_path) as conn:
            results = conn.execute(
                """
                SELECT word, definition 
                FROM entries 
                WHERE dictionary_id = ? AND LOWER(word) LIKE ?
                ORDER BY word
                LIMIT ?
            """,
                (self.current_dict_id, f"{query}%", limit),
            ).fetchall()
            return results

    def get_suggestions(self, prefix: str, limit: int = 10) -> List[str]:
        if not self.current_dict_id or not prefix.strip():
            return []

        prefix = prefix.strip().lower()
        with sqlite3.connect(self.db_path) as conn:
            words = conn.execute(
                """
                SELECT DISTINCT word 
                FROM entries 
                WHERE dictionary_id = ? AND LOWER(word) LIKE ?
                ORDER BY word
                LIMIT ?
            """,
                (self.current_dict_id, f"{prefix}%", limit),
            ).fetchall()
            return [w[0] for w in words]

    def get_dictionaries(self) -> List[Tuple[int, str, int]]:
        """Backward compatible: handle missing is_encrypted column"""
        with sqlite3.connect(self.db_path) as conn:
            try:
                return conn.execute(
                    "SELECT id, name, word_count FROM dictionaries ORDER BY name"
                ).fetchall()
            except sqlite3.OperationalError:
                # Fallback for very old schema
                return conn.execute(
                    "SELECT id, name, 0 as word_count FROM dictionaries ORDER BY name"
                ).fetchall()

    def set_active_dictionary(self, dict_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            exists = conn.execute(
                "SELECT 1 FROM dictionaries WHERE id = ?", (dict_id,)
            ).fetchone()
            if exists:
                self.current_dict_id = dict_id
                return True
            return False

    def scan_and_import(self, directory: str) -> List[dict]:
        """
        Scans a directory for .bgl files and imports them if not already present.
        Returns a list of results for each file found.
        """
        results = []
        directory_path = Path(directory)

        if not directory_path.exists():
            return [{"status": "error", "message": f"Directory not found: {directory}"}]

        # Find all BGL files (case-insensitive)
        files = []
        for f in directory_path.iterdir():
            if f.is_file() and f.suffix.lower() == ".bgl":
                files.append(f)

        if not files:
            return [{"status": "info", "message": "No BGL files found in directory"}]

        # Get existing dictionary paths to avoid re-importing
        with sqlite3.connect(self.db_path) as conn:
            existing_paths = {
                row[0]
                for row in conn.execute(
                    "SELECT source_path FROM dictionaries"
                ).fetchall()
            }

        for file_path in files:
            abs_path = str(file_path.absolute())
            file_name = file_path.name

            # Skip if already imported
            if abs_path in existing_paths:
                results.append(
                    {"file": file_name, "status": "skip", "message": "Already imported"}
                )
                continue

            # Attempt import
            success, msg = self.import_bgl(str(file_path))
            results.append(
                {
                    "file": file_name,
                    "status": "success" if success else "error",
                    "message": msg,
                }
            )

        return results

    # ==================== History Methods ====================

    def add_to_history(self, query: str) -> None:
        """Add a search query to history."""
        if not query.strip():
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO search_history (query, dictionary_id) VALUES (?, ?)",
                (query.strip(), self.current_dict_id),
            )
            # Keep only last 100 entries
            conn.execute("""
                DELETE FROM search_history WHERE id NOT IN (
                    SELECT id FROM search_history ORDER BY searched_at DESC LIMIT 100
                )
            """)
            conn.commit()

    def get_history(self, limit: int = 20) -> List[Tuple[str, str]]:
        """Get recent search history. Returns list of (query, timestamp)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """SELECT query, searched_at FROM search_history 
                   ORDER BY searched_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return rows

    def clear_history(self) -> None:
        """Clear all search history."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM search_history")
            conn.commit()

    # ==================== Favorites Methods ====================

    def add_to_favorites(self, word: str, definition: str) -> bool:
        """Add a word to favorites. Returns True if added, False if already exists."""
        with sqlite3.connect(self.db_path) as conn:
            # Check if already favorited
            exists = conn.execute(
                "SELECT 1 FROM favorites WHERE word = ? AND dictionary_id = ?",
                (word, self.current_dict_id),
            ).fetchone()
            if exists:
                return False
            conn.execute(
                "INSERT INTO favorites (word, definition, dictionary_id) VALUES (?, ?, ?)",
                (word, definition, self.current_dict_id),
            )
            conn.commit()
            return True

    def remove_from_favorites(self, word: str) -> bool:
        """Remove a word from favorites."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM favorites WHERE word = ? AND dictionary_id = ?",
                (word, self.current_dict_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_favorites(self, limit: int = 50) -> List[Tuple[str, str, str]]:
        """Get favorites. Returns list of (word, definition, added_at)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """SELECT word, definition, added_at FROM favorites 
                   ORDER BY added_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return rows

    def is_favorite(self, word: str) -> bool:
        """Check if a word is in favorites."""
        with sqlite3.connect(self.db_path) as conn:
            exists = conn.execute(
                "SELECT 1 FROM favorites WHERE word = ? AND dictionary_id = ?",
                (word, self.current_dict_id),
            ).fetchone()
            return exists is not None
