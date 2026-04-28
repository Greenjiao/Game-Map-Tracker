import tempfile
import unittest
from pathlib import Path

from route_manager import RouteManager


class RouteCategoryTests(unittest.TestCase):
    def test_missing_routes_root_creates_empty_root_without_default_categories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            routes_dir = Path(tmp) / "routes"

            manager = RouteManager(str(routes_dir))

            self.assertTrue(routes_dir.is_dir())
            self.assertEqual(manager.categories, [])
            self.assertEqual([path.name for path in routes_dir.iterdir() if path.is_dir()], [])

    def test_existing_category_directories_are_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            routes_dir = Path(tmp) / "routes"
            (routes_dir / "b").mkdir(parents=True)
            (routes_dir / "a").mkdir()

            manager = RouteManager(str(routes_dir))

            self.assertEqual(manager.categories, ["a", "b"])
            self.assertEqual(set(manager.route_groups), {"a", "b"})

    def test_deleted_default_named_category_stays_deleted_after_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            routes_dir = Path(tmp) / "routes"
            category_name = "\u690d\u7269"
            category_path = routes_dir / category_name
            category_path.mkdir(parents=True)
            manager = RouteManager(str(routes_dir))

            self.assertTrue(manager.delete_category(category_name))
            manager.reload()

            self.assertFalse(category_path.exists())
            self.assertNotIn(category_name, manager.categories)


if __name__ == "__main__":
    unittest.main()
