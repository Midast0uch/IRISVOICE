"""Read settings.ini."""

import configparser

parser = configparser.ConfigParser()
parser.read("settings.ini", encoding="utf-8")
print(parser.sections())
