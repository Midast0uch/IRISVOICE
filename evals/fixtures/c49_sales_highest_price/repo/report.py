"""Print the row count and the unit total from sales.csv."""

from csv import DictReader

with open("sales.csv", newline="", encoding="utf-8") as fh:
    rows = list(DictReader(fh))

units = sum(int(row["units"]) for row in rows)
print("rows:", len(rows))
print("units:", units)
