from billing.core import calc_total
from billing.report import report

if __name__ == "__main__":
    items = [(2.5, 2)]
    assert calc_total(items) == 5.0
    print(report(items))
