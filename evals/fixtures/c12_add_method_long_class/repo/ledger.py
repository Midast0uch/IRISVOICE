"""A simple money ledger."""


class Ledger:
    """Entries are (date, amount, memo) with ISO dates "YYYY-MM-DD"."""

    def __init__(self):
        self.entries = []

    def deposit(self, date, amount, memo=""):
        if amount <= 0:
            raise ValueError("deposit must be positive")
        self.entries.append((date, amount, memo))

    def withdraw(self, date, amount, memo=""):
        if amount <= 0:
            raise ValueError("withdrawal must be positive")
        self.entries.append((date, -amount, memo))

    def balance(self):
        return sum(amount for _, amount, _ in self.entries)

    def total_rent(self):
        """Sum of entries whose memo mentions 'rent'."""
        return sum(a for _, a, memo in self.entries if "rent" in memo.lower())

    def count_rent(self):
        """Number of entries whose memo mentions 'rent'."""
        return sum(1 for _, _, memo in self.entries if "rent" in memo.lower())

    def total_food(self):
        """Sum of entries whose memo mentions 'food'."""
        return sum(a for _, a, memo in self.entries if "food" in memo.lower())

    def count_food(self):
        """Number of entries whose memo mentions 'food'."""
        return sum(1 for _, _, memo in self.entries if "food" in memo.lower())

    def total_travel(self):
        """Sum of entries whose memo mentions 'travel'."""
        return sum(a for _, a, memo in self.entries if "travel" in memo.lower())

    def count_travel(self):
        """Number of entries whose memo mentions 'travel'."""
        return sum(1 for _, _, memo in self.entries if "travel" in memo.lower())

    def total_salary(self):
        """Sum of entries whose memo mentions 'salary'."""
        return sum(a for _, a, memo in self.entries if "salary" in memo.lower())

    def count_salary(self):
        """Number of entries whose memo mentions 'salary'."""
        return sum(1 for _, _, memo in self.entries if "salary" in memo.lower())

    def total_gift(self):
        """Sum of entries whose memo mentions 'gift'."""
        return sum(a for _, a, memo in self.entries if "gift" in memo.lower())

    def count_gift(self):
        """Number of entries whose memo mentions 'gift'."""
        return sum(1 for _, _, memo in self.entries if "gift" in memo.lower())

    def total_tax(self):
        """Sum of entries whose memo mentions 'tax'."""
        return sum(a for _, a, memo in self.entries if "tax" in memo.lower())

    def count_tax(self):
        """Number of entries whose memo mentions 'tax'."""
        return sum(1 for _, _, memo in self.entries if "tax" in memo.lower())

    def total_fuel(self):
        """Sum of entries whose memo mentions 'fuel'."""
        return sum(a for _, a, memo in self.entries if "fuel" in memo.lower())

    def count_fuel(self):
        """Number of entries whose memo mentions 'fuel'."""
        return sum(1 for _, _, memo in self.entries if "fuel" in memo.lower())

    def total_books(self):
        """Sum of entries whose memo mentions 'books'."""
        return sum(a for _, a, memo in self.entries if "books" in memo.lower())

    def count_books(self):
        """Number of entries whose memo mentions 'books'."""
        return sum(1 for _, _, memo in self.entries if "books" in memo.lower())

    def total_music(self):
        """Sum of entries whose memo mentions 'music'."""
        return sum(a for _, a, memo in self.entries if "music" in memo.lower())

    def count_music(self):
        """Number of entries whose memo mentions 'music'."""
        return sum(1 for _, _, memo in self.entries if "music" in memo.lower())

    def total_sport(self):
        """Sum of entries whose memo mentions 'sport'."""
        return sum(a for _, a, memo in self.entries if "sport" in memo.lower())

    def count_sport(self):
        """Number of entries whose memo mentions 'sport'."""
        return sum(1 for _, _, memo in self.entries if "sport" in memo.lower())

    def total_health(self):
        """Sum of entries whose memo mentions 'health'."""
        return sum(a for _, a, memo in self.entries if "health" in memo.lower())

    def count_health(self):
        """Number of entries whose memo mentions 'health'."""
        return sum(1 for _, _, memo in self.entries if "health" in memo.lower())

    def total_phone(self):
        """Sum of entries whose memo mentions 'phone'."""
        return sum(a for _, a, memo in self.entries if "phone" in memo.lower())

    def count_phone(self):
        """Number of entries whose memo mentions 'phone'."""
        return sum(1 for _, _, memo in self.entries if "phone" in memo.lower())

    def total_power(self):
        """Sum of entries whose memo mentions 'power'."""
        return sum(a for _, a, memo in self.entries if "power" in memo.lower())

    def count_power(self):
        """Number of entries whose memo mentions 'power'."""
        return sum(1 for _, _, memo in self.entries if "power" in memo.lower())

    def total_water(self):
        """Sum of entries whose memo mentions 'water'."""
        return sum(a for _, a, memo in self.entries if "water" in memo.lower())

    def count_water(self):
        """Number of entries whose memo mentions 'water'."""
        return sum(1 for _, _, memo in self.entries if "water" in memo.lower())

    def total_games(self):
        """Sum of entries whose memo mentions 'games'."""
        return sum(a for _, a, memo in self.entries if "games" in memo.lower())

    def count_games(self):
        """Number of entries whose memo mentions 'games'."""
        return sum(1 for _, _, memo in self.entries if "games" in memo.lower())

    def total_tools(self):
        """Sum of entries whose memo mentions 'tools'."""
        return sum(a for _, a, memo in self.entries if "tools" in memo.lower())

    def count_tools(self):
        """Number of entries whose memo mentions 'tools'."""
        return sum(1 for _, _, memo in self.entries if "tools" in memo.lower())

    def total_garden(self):
        """Sum of entries whose memo mentions 'garden'."""
        return sum(a for _, a, memo in self.entries if "garden" in memo.lower())

    def count_garden(self):
        """Number of entries whose memo mentions 'garden'."""
        return sum(1 for _, _, memo in self.entries if "garden" in memo.lower())

    def total_pets(self):
        """Sum of entries whose memo mentions 'pets'."""
        return sum(a for _, a, memo in self.entries if "pets" in memo.lower())

    def count_pets(self):
        """Number of entries whose memo mentions 'pets'."""
        return sum(1 for _, _, memo in self.entries if "pets" in memo.lower())

    def total_school(self):
        """Sum of entries whose memo mentions 'school'."""
        return sum(a for _, a, memo in self.entries if "school" in memo.lower())

    def count_school(self):
        """Number of entries whose memo mentions 'school'."""
        return sum(1 for _, _, memo in self.entries if "school" in memo.lower())

    def total_repair(self):
        """Sum of entries whose memo mentions 'repair'."""
        return sum(a for _, a, memo in self.entries if "repair" in memo.lower())

    def count_repair(self):
        """Number of entries whose memo mentions 'repair'."""
        return sum(1 for _, _, memo in self.entries if "repair" in memo.lower())

    def history(self):
        """Entries sorted by date."""
        return sorted(self.entries, key=lambda e: e[0])
