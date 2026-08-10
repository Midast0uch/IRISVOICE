import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.voice.tts_normalizer import normalize_for_speech

def test_markdown_stripping():
    assert normalize_for_speech("**Hello** world") == "Hello world"
    assert normalize_for_speech("__Hello__ _world_") == "Hello world"
    assert normalize_for_speech("## Header\nText") == "Header Text"
    assert normalize_for_speech("~~striked~~") == "striked"
    assert normalize_for_speech("Here is `inline_code`.") == "Here is inline code."
    print("test_markdown_stripping passed")
    
def test_list_stripping():
    text = "- Item 1\n* Item 2\n• Item 3\n1. Item 4"
    assert normalize_for_speech(text) == "Item 1 Item 2 Item 3 Item 4"
    print("test_list_stripping passed")

def test_windows_paths():
    assert normalize_for_speech(r"See C:\Users\Midas\project\audio_engine.py") == "See C drive, Users, Midas, project, audio engine dot p y"
    assert normalize_for_speech(r"In D:\data\config.json.") == "In D drive, data, config dot json."
    print("test_windows_paths passed")
    
def test_unix_paths():
    assert normalize_for_speech("Edit /backend/voice/audio_engine.py file") == "Edit backend, voice, audio engine dot p y file"
    assert normalize_for_speech("Log at /var/log/syslog now") == "Log at var, log, syslog now"
    print("test_unix_paths passed")

def test_urls():
    assert normalize_for_speech("Go to https://google.com/search") == "Go to a link"
    assert normalize_for_speech("Read http://example.com/api.") == "Read a link."
    print("test_urls passed")

def test_symbols():
    assert normalize_for_speech("^Remove this^") == "Remove this"
    assert normalize_for_speech("func() -> int") == "func()  returns  int"
    assert normalize_for_speech("a => b") == "a  maps to  b"
    assert normalize_for_speech("x !== y") == "x  is not equal to  y"
    assert normalize_for_speech("x === y") == "x  is strictly equal to  y"
    assert normalize_for_speech("a >= b and c <= d") == "a  greater than or equal to  b and c  less than or equal to  d"
    assert normalize_for_speech("start_recording process") == "start recording process"
    print("test_symbols passed")
    
def test_drop_inline_comments():
    text = "const x = 5; // this is a variable\nlet y = 6;"
    assert normalize_for_speech(text) == "const x = 5; let y = 6;"
    print("test_drop_inline_comments passed")
    
def test_mid_sentence_periods():
    assert normalize_for_speech("Item 1. item 2. Item 3.") == "Item 1, item 2. Item 3."
    print("test_mid_sentence_periods passed")
    
def test_whitespace_collapsing():
    text = "Hello\n\nWorld   \n  Testing"
    assert normalize_for_speech(text) == "Hello World Testing"
    print("test_whitespace_collapsing passed")

if __name__ == "__main__":
    test_markdown_stripping()
    test_list_stripping()
    test_windows_paths()
    test_unix_paths()
    test_urls()
    test_symbols()
    test_drop_inline_comments()
    test_mid_sentence_periods()
    test_whitespace_collapsing()
    print("ALL TESTS PASSED")
