from ryxpress import hello, __version__, rxp_phart, RRunResult

def test_hello():
    assert hello() == "Hello from ryxpress!"

def test_version():
    assert isinstance(__version__, str)


def test_exports_available():
    assert callable(rxp_phart)
    assert RRunResult is not None
