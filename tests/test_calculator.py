import unittest
from calculator import add
from calculator import subtract ,multiply ,power ,average ,modulo


class CalculatorTests(unittest.TestCase):
    def test_adds_numbers(self):
        self.assertEqual(add(2, 3), 5)

    def test_subtracts_numbers(self):
        self.assertEqual(subtract(5, 3), 2)

    def test_multiply_numbers(self):
        self.assertEqual(multiply(2, 3), 6)
    
    def test_power(self):
        self.assertEqual(power(2, 3), 8)

    def test_average(self):
        self.assertEqual(average([2, 4, 6]), 4)

    def test_average_rejects_empty_input(self):
        with self.assertRaises(ValueError):
            average([])
    
    def test_modulo(self):
        self.assertEqual(modulo(10, 3), 1)


if __name__ == "__main__":
    unittest.main()


