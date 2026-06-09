"""
Tests for utils module.
"""

import unittest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import greet, add, multiply


class TestGreet(unittest.TestCase):
    """Tests for the greet function."""

    def test_greet_basic(self):
        self.assertEqual(greet("World"), "Hello, World!")

    def test_greet_empty_string(self):
        self.assertEqual(greet(""), "Hello, !")

    def test_greet_with_spaces(self):
        self.assertEqual(greet("John Doe"), "Hello, John Doe!")


class TestAdd(unittest.TestCase):
    """Tests for the add function."""

    def test_add_integers(self):
        self.assertEqual(add(2, 3), 5)

    def test_add_negative_numbers(self):
        self.assertEqual(add(-1, -1), -2)

    def test_add_floats(self):
        self.assertAlmostEqual(add(1.5, 2.5), 4.0)

    def test_add_mixed_types(self):
        self.assertEqual(add(1, 2.5), 3.5)


class TestMultiply(unittest.TestCase):
    """Tests for the multiply function."""

    def test_multiply_integers(self):
        self.assertEqual(multiply(3, 4), 12)

    def test_multiply_by_zero(self):
        self.assertEqual(multiply(5, 0), 0)

    def test_multiply_negative_numbers(self):
        self.assertEqual(multiply(-2, 3), -6)

    def test_multiply_floats(self):
        self.assertAlmostEqual(multiply(1.5, 2.0), 3.0)


if __name__ == "__main__":
    unittest.main()
