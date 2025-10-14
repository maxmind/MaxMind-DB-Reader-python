"""Tests for thread-safety and free-threading support."""

from __future__ import annotations

import threading
import time
import unittest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maxminddb.types import Record

try:
    import maxminddb.extension  # noqa: F401

    HAS_EXTENSION = True
except ImportError:
    HAS_EXTENSION = False

from maxminddb import open_database
from maxminddb.const import MODE_MMAP_EXT


@unittest.skipIf(
    not HAS_EXTENSION,
    "No C extension module found. Skipping threading tests",
)
class TestThreadSafety(unittest.TestCase):
    """Test thread safety of the C extension."""

    def test_concurrent_reads(self) -> None:
        """Test multiple threads reading concurrently."""
        reader = open_database(
            "tests/data/test-data/MaxMind-DB-test-ipv4-24.mmdb",
            MODE_MMAP_EXT,
        )

        results: list[Record | None] = [None] * 100
        errors: list[Exception] = []

        def lookup(index: int, ip: str) -> None:
            try:
                results[index] = reader.get(ip)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = []
        for i in range(100):
            ip = f"1.1.1.{(i % 32) + 1}"
            t = threading.Thread(target=lookup, args=(i, ip))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        reader.close()

        self.assertEqual(len(errors), 0, f"Errors during concurrent reads: {errors}")
        # All lookups should have completed
        self.assertNotIn(None, results)

    def test_read_during_close(self) -> None:
        """Test that close is safe when reads are happening concurrently."""
        reader = open_database(
            "tests/data/test-data/MaxMind-DB-test-ipv4-24.mmdb",
            MODE_MMAP_EXT,
        )

        errors: list[Exception] = []
        should_stop = threading.Event()

        def continuous_reader() -> None:
            # Keep reading until signaled to stop or reader is closed
            while not should_stop.is_set():
                try:
                    reader.get("1.1.1.1")
                except ValueError as e:  # noqa: PERF203
                    # Expected once close() is called
                    if "closed MaxMind DB" not in str(e):
                        errors.append(e)
                    break
                except Exception as e:  # noqa: BLE001
                    errors.append(e)
                    break

        # Start multiple readers
        threads = [threading.Thread(target=continuous_reader) for _ in range(10)]
        for t in threads:
            t.start()

        # Let readers run for a bit
        time.sleep(0.05)

        # Close while reads are happening
        reader.close()

        # Signal threads to stop
        should_stop.set()

        # Wait for all threads
        for t in threads:
            t.join(timeout=1.0)

        self.assertEqual(len(errors), 0, f"Errors during close test: {errors}")

    def test_read_after_close(self) -> None:
        """Test that reads after close raise appropriate error."""
        reader = open_database(
            "tests/data/test-data/MaxMind-DB-test-ipv4-24.mmdb",
            MODE_MMAP_EXT,
        )
        reader.close()

        with self.assertRaisesRegex(
            ValueError,
            "Attempt to read from a closed MaxMind DB",
        ):
            reader.get("1.1.1.1")

    def test_concurrent_reads_and_metadata(self) -> None:
        """Test concurrent reads and metadata access."""
        reader = open_database(
            "tests/data/test-data/MaxMind-DB-test-ipv4-24.mmdb",
            MODE_MMAP_EXT,
        )

        errors: list[Exception] = []
        results: list[bool] = []

        def do_reads() -> None:
            try:
                for _ in range(50):
                    reader.get("1.1.1.1")
                results.append(True)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        def do_metadata() -> None:
            try:
                for _ in range(50):
                    reader.metadata()
                results.append(True)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = []
        for _ in range(5):
            threads.append(threading.Thread(target=do_reads))
            threads.append(threading.Thread(target=do_metadata))

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        reader.close()

        self.assertEqual(
            len(errors), 0, f"Errors during concurrent operations: {errors}"
        )
        self.assertEqual(len(results), 10, "All threads should complete")

    def test_concurrent_iteration(self) -> None:
        """Test that iteration is thread-safe."""
        reader = open_database(
            "tests/data/test-data/MaxMind-DB-test-ipv4-24.mmdb",
            MODE_MMAP_EXT,
        )

        errors: list[Exception] = []
        counts: list[int] = []

        def iterate() -> None:
            try:
                count = 0
                for _ in reader:
                    count += 1
                counts.append(count)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=iterate) for _ in range(10)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        reader.close()

        self.assertEqual(len(errors), 0, f"Errors during iteration: {errors}")
        # All threads should see the same number of entries
        self.assertEqual(len(set(counts)), 1, "All threads should see same entry count")

    def test_stress_test(self) -> None:
        """Stress test with many threads and operations."""
        reader = open_database(
            "tests/data/test-data/MaxMind-DB-test-ipv4-24.mmdb",
            MODE_MMAP_EXT,
        )

        errors: list[Exception] = []
        operations_completed = threading.Event()

        def random_operations() -> None:
            try:
                for i in range(100):
                    # Mix different operations
                    if i % 3 == 0:
                        reader.get("1.1.1.1")
                    elif i % 3 == 1:
                        reader.metadata()
                    else:
                        reader.get_with_prefix_len("1.1.1.2")
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=random_operations) for _ in range(20)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        operations_completed.set()
        reader.close()

        self.assertEqual(len(errors), 0, f"Errors during stress test: {errors}")

    def test_multiple_readers_different_databases(self) -> None:
        """Test multiple readers on different databases in parallel."""
        errors: list[Exception] = []

        def use_reader(filename: str) -> None:
            try:
                reader = open_database(filename, MODE_MMAP_EXT)
                for _ in range(50):
                    reader.get("1.1.1.1")
                reader.close()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [
            threading.Thread(
                target=use_reader,
                args=("tests/data/test-data/MaxMind-DB-test-ipv4-24.mmdb",),
            )
            for _ in range(5)
        ]
        threads.extend(
            [
                threading.Thread(
                    target=use_reader,
                    args=("tests/data/test-data/MaxMind-DB-test-ipv6-24.mmdb",),
                )
                for _ in range(5)
            ]
        )

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Errors with multiple readers: {errors}")


if __name__ == "__main__":
    unittest.main()
